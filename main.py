from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os

from quiz_agents_v2 import (
    generate_questions, save_quiz, load_quiz,
    list_quizzes, delete_quiz, evaluate_answers_ai, get_quiz_html,
)

app = FastAPI(
    title="AI Quiz Generator",
    description="API لتوليد وتصحيح الكويزات بالذكاء الاصطناعي",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST MODELS
# ============================================================
class GenerateRequest(BaseModel):
    lesson_name: str
    transcript: str          # ← الجديد: النص بييجي في الـ request
    difficulty: str = "easy"
    q_type: str = "MCQ"
    num_q: int = 5

class SaveRequest(BaseModel):
    quiz_name: str
    lesson_name: str
    difficulty: str
    q_type: str
    questions: List[dict]

class EvaluateRequest(BaseModel):
    questions: List[dict]
    answers: List[str]


# ============================================================
# ENDPOINTS
# ============================================================
@app.get("/")
def root():
    return {"message": "AI Quiz Generator API v2 is running ✅"}


@app.post("/generate-quiz")
def generate(req: GenerateRequest):
    # validation بسيط على حجم الـ transcript
    if not req.transcript or len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="الـ transcript قصير جداً أو فاضي")

    if len(req.transcript) > 50000:
        raise HTTPException(status_code=400, detail="الـ transcript كبير جداً، الحد الأقصى 50,000 حرف")

    try:
        questions = generate_questions(
            req.transcript, req.difficulty, req.q_type, req.num_q
        )
    except Exception as e:
        status = 429 if "وصلت للحد" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))

    if not questions:
        raise HTTPException(status_code=500, detail="فشل توليد الأسئلة، حاول تاني")

    return {
        "lesson_name": req.lesson_name,
        "questions": questions,
        "count": len(questions)
    }


@app.post("/save-quiz")
def save(req: SaveRequest):
    try:
        save_quiz(req.quiz_name, req.lesson_name, req.difficulty, req.q_type, req.questions)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "تم الحفظ ✅", "quiz_name": req.quiz_name}


@app.get("/quizzes")
def get_all():
    try:
        return list_quizzes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/quiz/{quiz_name}")
def get_one(quiz_name: str):
    data = load_quiz(quiz_name)
    if not data:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return data


@app.delete("/quiz/{quiz_name}")
def remove(quiz_name: str):
    deleted = delete_quiz(quiz_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return {"message": "تم الحذف ✅"}


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    if len(req.questions) != len(req.answers):
        raise HTTPException(status_code=400, detail="عدد الأسئلة والإجابات مش متطابق")
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


# HTML endpoints — بترجع الـ HTML مباشرة بدون حفظ ملف (مناسب لـ HF)
@app.get("/quiz/{quiz_name}/download/student", response_class=HTMLResponse)
def student_html(quiz_name: str):
    html = get_quiz_html(quiz_name, show_answers=False)
    if not html:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return HTMLResponse(content=html)


@app.get("/quiz/{quiz_name}/download/teacher", response_class=HTMLResponse)
def teacher_html(quiz_name: str):
    html = get_quiz_html(quiz_name, show_answers=True)
    if not html:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return HTMLResponse(content=html)