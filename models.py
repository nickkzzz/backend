from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Quiz(db.Model):
    __tablename__ = "quiz"

    id = db.Column(db.String(10), primary_key=True)
    time = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    students = db.relationship("Student", backref="quiz", lazy=True)
    questions = db.relationship("Question", backref="quiz", lazy=True)


class Question(db.Model):
    __tablename__ = "question"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.String(10), db.ForeignKey("quiz.id"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    options = db.Column(db.JSON, nullable=False)
    answer_letter = db.Column(db.String(1), nullable=False)
    explanation = db.Column(db.Text)


class Student(db.Model):
    __tablename__ = "student"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quiz_id = db.Column(db.String(10), db.ForeignKey("quiz.id"), nullable=False)
    score = db.Column(db.Integer, default=0)        # FIX
    finished = db.Column(db.Boolean, default=False)
