import os
import re
import uuid
import time

import fitz
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv

from models import db, Quiz, Question, Student

# ------------------ SETUP ------------------
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

# ✅ PROPER CORS
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "quiz.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()

# ------------------ HELPERS ------------------

def extract_text_from_pdf(path, max_chars=8000):
    doc = fitz.open(path)
    text = " ".join(page.get_text("text") for page in doc)
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def build_prompt(src_text, num_q):
    return f"""
Generate exactly {num_q} multiple-choice questions.

Format:
Q1: Question
A. option
B. option
C. option
D. option
Answer: B
Explanation: reason

Text:
\"\"\"{src_text}\"\"\"
""".strip()


def call_llm(prompt, timeout_sec=40):
    """
    Groq API call with HARD TIME LIMIT
    """
    start = time.time()

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.3,
            messages=[
                {"role": "system", "content": "You generate MCQs"},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as e:
        print("❌ Groq API error:", e)
        raise RuntimeError("Groq API failed")

    elapsed = time.time() - start
    print(f"✅ Groq response in {elapsed:.2f}s")

    if elapsed > timeout_sec:
        raise RuntimeError("Groq timeout")

    return resp.choices[0].message.content


def parse_mcqs(text):
    blocks = re.split(r"\n?(?=Q\d+:)", text)
    mcqs = []

    for b in blocks:
        q = re.search(r"Q\d+:\s*(.*)", b)
        opts = re.findall(r"\n([ABCD])\.\s*(.*)", b)
        ans = re.search(r"Answer:\s*([ABCD])", b)
        exp = re.search(r"Explanation:\s*(.*)", b)

        if not q or len(opts) != 4 or not ans:
            continue

        mcqs.append({
            "q": q.group(1).strip(),
            "options": [o[1].strip() for o in opts],
            "answer_letter": ans.group(1),
            "explanation": exp.group(1).strip() if exp else ""
        })

    return mcqs

# ------------------ ROUTES ------------------

@app.route("/api/generate", methods=["POST"])
def generate():
    print("👉 /api/generate called")

    file = request.files.get("pdf")
    paragraph = request.form.get("paragraph", "")
    num_q = int(request.form.get("num_q", 5))  # 🔥 LIMIT TO 5
    quiz_time = int(request.form.get("quiz_time", 5))

    if file:
        print("📄 PDF received")
        os.makedirs("uploads", exist_ok=True)
        path = os.path.join("uploads", file.filename)
        file.save(path)
        text = extract_text_from_pdf(path)
    elif paragraph:
        print("📝 Paragraph received")
        text = paragraph
    else:
        return jsonify({"error": "Input required"}), 400

    try:
        print("🤖 Calling Groq...")
        raw = call_llm(build_prompt(text, num_q))
        print("✅ Groq finished")

        questions = parse_mcqs(raw)
        print(f"❓ Parsed {len(questions)} questions")

        if not questions:
            return jsonify({"error": "Failed to generate questions"}), 500

    except Exception as e:
        print("❌ Generation failed:", e)
        return jsonify({"error": "AI generation failed. Try again."}), 500

    quiz_id = str(uuid.uuid4())[:8]
    quiz = Quiz(id=quiz_id, time=quiz_time)
    db.session.add(quiz)

    for q in questions:
        db.session.add(Question(
            quiz_id=quiz_id,
            question=q["q"],
            options=q["options"],
            answer_letter=q["answer_letter"],
            explanation=q["explanation"]
        ))

    db.session.commit()
    print("💾 Quiz saved")

    return jsonify({
        "quiz_id": quiz_id,
        "count": len(questions),
        "time": quiz_time
    })


@app.route("/api/quiz/<quiz_id>", methods=["GET"])
def get_quiz(quiz_id):
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404

    questions = Question.query.filter_by(quiz_id=quiz_id).all()

    return jsonify({
        "quiz_id": quiz_id,
        "time": quiz.time,
        "questions": [
            {"q": q.question, "options": q.options}
            for q in questions
        ]
    })


@app.route("/api/quiz/<quiz_id>/join", methods=["POST"])
def join_quiz(quiz_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "Name required"}), 400

    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404

    existing = Student.query.filter_by(quiz_id=quiz_id, name=name).first()
    if not existing:
        db.session.add(Student(name=name, quiz_id=quiz_id))
        db.session.commit()

    return jsonify({"success": True})


@app.route("/api/quiz/<quiz_id>/submit", methods=["POST"])
def submit_quiz(quiz_id):
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    answers = data.get("answers", {})

    questions = Question.query.filter_by(quiz_id=quiz_id).all()

    score = 0
    results = []

    for i, q in enumerate(questions):
        selected = answers.get(str(i))
        correct = q.answer_letter
        is_correct = selected == correct
        if is_correct:
            score += 1

        results.append({
            "question": q.question,
            "options": q.options,
            "selected": selected,
            "correct": correct,
            "isCorrect": is_correct,
            "explanation": q.explanation
        })

    student = Student.query.filter_by(quiz_id=quiz_id, name=name).first()
    if student:
        student.score = score
        student.finished = True
        db.session.commit()

    return jsonify({
        "score": score,
        "total": len(questions),
        "results": results
    })


@app.route("/api/quiz/<quiz_id>/admin", methods=["GET"])
def admin_panel(quiz_id):
    students = Student.query.filter_by(quiz_id=quiz_id).all()
    return jsonify({
        "quiz_id": quiz_id,
        "students": [
            {"name": s.name, "score": s.score, "finished": s.finished}
            for s in students
        ]
    })


# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
