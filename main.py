from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os

from quiz_agents_v2 import (
    find_transcript, generate_questions,
    save_quiz, load_quiz, list_quizzes,
    evaluate_answers_ai, generate_quiz_pdf,
)

app = FastAPI(
    title="AI Quiz Generator",
    description="API لتوليد وتصحيح الكويزات بالذكاء الاصطناعي",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    lesson_name: str
    difficulty: str
    q_type: str
    num_q: int

class SaveRequest(BaseModel):
    quiz_name: str
    lesson_name: str
    difficulty: str
    q_type: str
    questions: List[dict]

class EvaluateRequest(BaseModel):
    questions: List[dict]
    answers: List[str]

@app.get("/")
def root():
    return {"message": "AI Quiz Generator API is running"}

@app.post("/generate-quiz")
def generate(req: GenerateRequest):
    transcript, lesson_name = find_transcript(req.lesson_name)
    if not transcript:
        raise HTTPException(status_code=404, detail="الدرس مش موجود")
    try:
        questions = generate_questions(transcript, req.difficulty, req.q_type, req.num_q)
    except Exception as e:
        raise HTTPException(status_code=429, detail=str(e))
    if not questions:
        raise HTTPException(status_code=500, detail="فشل توليد الأسئلة")
    return {"lesson_name": lesson_name, "questions": questions}

@app.post("/save-quiz")
def save(req: SaveRequest):
    save_quiz(req.quiz_name, req.lesson_name, req.difficulty, req.q_type, req.questions)
    return {"message": "تم الحفظ", "quiz_name": req.quiz_name}

@app.get("/quizzes")
def get_all():
    return list_quizzes()

@app.get("/quiz/{quiz_name}")
def get_one(quiz_name: str):
    data = load_quiz(quiz_name)
    if not data:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return data

@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    try:
        score, feedback = evaluate_answers_ai(req.questions, req.answers)
        total = len(req.questions)
        return {
            "score": score,
            "total": total,
            "percentage": round(score / total * 100) if total > 0 else 0,
            "feedback": feedback
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/quiz/{quiz_name}/download/student")
def student_file(quiz_name: str):
    data = load_quiz(quiz_name)
    if not data:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    path = generate_quiz_pdf(data["questions"], quiz_name, show_answers=False)
    return FileResponse(path, media_type="text/html", filename=f"{quiz_name}.html")

@app.get("/quiz/{quiz_name}/download/teacher")
def teacher_file(quiz_name: str):
    data = load_quiz(quiz_name)
    if not data:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    path = generate_quiz_pdf(data["questions"], quiz_name, show_answers=True)
    return FileResponse(path, media_type="text/html", filename=f"{quiz_name}_answers.html")