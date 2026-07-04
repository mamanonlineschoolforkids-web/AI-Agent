from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os, json
from datetime import datetime, timezone

from Quiz import run_quiz_graph, evaluate_answers

app = FastAPI(
    title="AI Quiz Generator",
    description="API لتوليد وتصحيح الكويزات بالذكاء الاصطناعي",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

QUIZZES_FOLDER = "quizzes"
os.makedirs(QUIZZES_FOLDER, exist_ok=True)


# ============================================================
# REQUEST MODELS
# ============================================================
class GenerateRequest(BaseModel):
    lesson_name: str
    transcript: str
    difficulty: str = "easy"
    q_type: str = "MCQ"
    num_q: int = 5

class SaveRequest(BaseModel):
    lesson_name: str
    difficulty: str
    q_type: str
    questions: List[dict]

class EvaluateRequest(BaseModel):
    questions: List[dict]
    answers: List[str]


# ============================================================
# STORAGE HELPERS
# ============================================================
def make_filename(lesson_name, difficulty, q_type):
    safe_q_type = q_type.replace("/", "-")
    return f"{lesson_name}_{difficulty}_{safe_q_type}.json".replace(" ", "_")

def save_quiz_file(lesson_name, difficulty, q_type, questions):
    filename = make_filename(lesson_name, difficulty, q_type)
    data = {
        "lesson_name": lesson_name,
        "difficulty":  difficulty,
        "q_type":      q_type,
        "questions":   questions,
        "created_at":  datetime.now(timezone.utc).isoformat()
    }
    path = os.path.join(QUIZZES_FOLDER, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path

def load_quiz_file(lesson_name, difficulty, q_type):
    path = os.path.join(QUIZZES_FOLDER, make_filename(lesson_name, difficulty, q_type))
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def list_quizzes_files():
    quizzes = []
    for file in os.listdir(QUIZZES_FOLDER):
        if file.endswith(".json"):
            with open(os.path.join(QUIZZES_FOLDER, file), "r", encoding="utf-8") as f:
                data = json.load(f)
                quizzes.append({
                    "lesson_name":   data.get("lesson_name", ""),
                    "difficulty":    data.get("difficulty", ""),
                    "q_type":        data.get("q_type", ""),
                    "num_questions": len(data.get("questions", [])),
                    "created_at":    data.get("created_at", "")
                })
    return quizzes

def delete_quiz_file(lesson_name, difficulty, q_type):
    path = os.path.join(QUIZZES_FOLDER, make_filename(lesson_name, difficulty, q_type))
    if os.path.exists(path):
        os.remove(path)
        return True
    return False

def get_quiz_html(lesson_name, difficulty, q_type):
    data = load_quiz_file(lesson_name, difficulty, q_type)
    if not data:
        return None
    title = f"{lesson_name} - {difficulty} - {q_type}"
    return generate_html(data["questions"], title)

def generate_html(questions, quiz_name):
    letters = ["أ", "ب", "ج", "د"]
    questions_html = ""
    for i, q in enumerate(questions):
        opts = q.get("options", [])
        options_html = ""
        if opts:
            for j, opt in enumerate(opts):
                letter = letters[j] if j < len(letters) else str(j+1)
                options_html += f'<div class="option"><span class="letter">{letter}</span> {opt}</div>'
        else:
            options_html = '<div class="option blank">الإجابة: ___________________________</div>'
        questions_html += f"""<div class="q-block">
            <div class="q-text">{i+1}. {q.get("question","")}</div>
            {options_html}</div>"""
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="UTF-8"><title>{quiz_name}</title>
<style>
  body{{font-family:Arial,sans-serif;direction:rtl;padding:40px;color:#222}}
  h1{{text-align:center;color:#1a1a2e}}
  .q-block{{border-right:4px solid #3498db;background:#f9f9f9;padding:12px 16px;margin-bottom:16px;border-radius:4px}}
  .q-text{{font-weight:bold;margin-bottom:8px;font-size:15px}}.option{{padding:3px 12px;color:#444}}
  .letter{{font-weight:bold;margin-left:6px}}.blank{{color:#999;font-style:italic}}
</style></head><body>
  <h1>{quiz_name}</h1>
  {questions_html}
  <p style="text-align:center;color:#aaa;margin-top:30px;font-size:12px">Ctrl+P → Save as PDF</p>
</body></html>"""


# ============================================================
# ENDPOINTS
# ============================================================
@app.get("/")
def root():
    return {"message": "AI Quiz Generator API v3 (LangGraph) is running ✅"}


@app.post("/generate-quiz")
def generate(req: GenerateRequest):
    if not req.transcript or len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="الـ transcript قصير جداً أو فاضي")
    if len(req.transcript) > 50000:
        raise HTTPException(status_code=400, detail="الـ transcript كبير جداً، الحد الأقصى 50,000 حرف")
    try:
        questions = run_quiz_graph(
            lesson_name=req.lesson_name,
            transcript=req.transcript,
            difficulty=req.difficulty,
            q_type=req.q_type,
            num_questions=req.num_q
        )
    except Exception as e:
        status = 429 if "وصلت للحد" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))

    if not questions:
        raise HTTPException(status_code=500, detail="فشل توليد الأسئلة، حاول تاني")

    save_quiz_file(req.lesson_name, req.difficulty, req.q_type, questions)

    return {
        "lesson_name": req.lesson_name,
        "questions":   questions,
        "count":       len(questions),
        "saved":       True
    }


@app.post("/save-quiz")
def save(req: SaveRequest):
    try:
        save_quiz_file(req.lesson_name, req.difficulty, req.q_type, req.questions)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    filename = make_filename(req.lesson_name, req.difficulty, req.q_type)
    return {"message": "تم الحفظ ✅", "file": filename}


@app.get("/quizzes")
def get_all():
    return list_quizzes_files()


@app.get("/quiz/{lesson_name}/{difficulty}/{q_type}")
def get_one(lesson_name: str, difficulty: str, q_type: str):
    data = load_quiz_file(lesson_name, difficulty, q_type)
    if not data:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return data


@app.delete("/quiz/{lesson_name}/{difficulty}/{q_type}")
def remove(lesson_name: str, difficulty: str, q_type: str):
    if not delete_quiz_file(lesson_name, difficulty, q_type):
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return {"message": "تم الحذف ✅"}


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    if len(req.questions) != len(req.answers):
        raise HTTPException(status_code=400, detail="عدد الأسئلة والإجابات مش متطابق")
    try:
        score, feedback = evaluate_answers(req.questions, req.answers)
        total = len(req.questions)
        return {
            "score":      score,
            "total":      total,
            "percentage": round(score / total * 100) if total > 0 else 0,
            "feedback":   feedback
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/quiz/{lesson_name}/{difficulty}/{q_type}/download", response_class=HTMLResponse)
def download_quiz(lesson_name: str, difficulty: str, q_type: str):
    html = get_quiz_html(lesson_name, difficulty, q_type)
    if not html:
        raise HTTPException(status_code=404, detail="الكويز مش موجود")
    return HTMLResponse(content=html)