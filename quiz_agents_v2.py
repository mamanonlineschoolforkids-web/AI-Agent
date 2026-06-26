from groq import Groq
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
MAX_CHARS_PER_CHUNK = 3000


# ============================================================
# SAFE LLM CALL
# ============================================================
def safe_llm_call(messages: list, temperature: float = 0.7) -> str:
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=1500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            import re
            wait = re.search(r"try again in (.+?)\.", err)
            wait_msg = wait.group(1) if wait else "بعد شوية"
            raise Exception(f"⏳ وصلت للحد المسموح، حاول تاني بعد {wait_msg}")
        elif "413" in err:
            raise Exception("📝 النص طويل جداً، جرب transcript أقصر")
        else:
            raise Exception(f"❌ خطأ في الـ AI: {err[:100]}")


# ============================================================
# HELPER: تلخيص الـ transcript لو كبير
# ============================================================
def smart_transcript(transcript: str) -> str:
    if len(transcript) <= MAX_CHARS_PER_CHUNK:
        return transcript

    chunks = [transcript[i:i + MAX_CHARS_PER_CHUNK]
              for i in range(0, len(transcript), MAX_CHARS_PER_CHUNK)]
    print(f"📄 Transcript split into {len(chunks)} chunks, summarizing...")

    summaries = []
    for idx, chunk in enumerate(chunks):
        prompt = f"""
Summarize the key educational facts from this text in Arabic.
Max 150 words. Only facts useful for quiz questions.
Text: {chunk}
"""
        summary = safe_llm_call([{"role": "user", "content": prompt}], temperature=0)
        summaries.append(f"[Part {idx + 1}]\n{summary}")
        print(f"   ✅ Chunk {idx + 1}/{len(chunks)} summarized")

    return "\n\n".join(summaries)


# ============================================================
# AGENT 1: Question Generator
# ============================================================
class QuestionGeneratorAgent:
    def generate(self, transcript, difficulty, q_type, num_q, existing_questions=None):
        smart_text = smart_transcript(transcript)[:5000]

        avoid_section = ""
        if existing_questions:
            existing_texts = [q.get("question", "") for q in existing_questions]
            avoid_section = f"""
Do NOT generate any of these questions again:
{json.dumps(existing_texts, ensure_ascii=False)}
"""
        prompt = f"""
You are an AI teacher for children.

Generate {num_q} {q_type} questions from the following transcript.
Difficulty level: {difficulty}

Rules:
- VERY IMPORTANT: Generate ALL questions and answers in Arabic language only.
- Every question must be UNIQUE. No duplicates.
- Do NOT repeat transcript sentences directly.
- If difficulty is hard, questions must require thinking.
- Cover different parts of the transcript, not just one section.
{avoid_section}
Question formats (follow exactly):
1) MCQ: question, options (array of exactly 4), correct_answer
2) True/False: question, options=["صح","خطأ"], correct_answer ("صح" or "خطأ")
3) Complete: question (with "___"), correct_answer. NO options field.

Return ONLY a valid JSON array. No text before or after.

Transcript:
{smart_text}
"""
        content = safe_llm_call([{"role": "user", "content": prompt}], temperature=0.7)

        # تنظيف الـ markdown بطريقة أقوى
        import re
        # شيل أي ```json ... ``` أو ``` ... ```
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        content = content.strip()

        # جيب أول [ لحد آخر ] بالظبط
        start_idx = content.find("[")
        end_idx = content.rfind("]")
        if start_idx != -1 and end_idx != -1:
            content = content[start_idx:end_idx + 1]

        if not content:
            return []

        try:
            questions = json.loads(content)
            seen = set()
            unique = []
            for q in questions:
                key = q.get("question", "").strip().lower()
                if key not in seen:
                    seen.add(key)
                    unique.append(q)
            return unique
        except json.JSONDecodeError as e:
            print(f"⚠️ Generator returned invalid JSON: {e}")
            print(f"⚠️ Content preview: {content[:200]}")
            return []


# ============================================================
# AGENT 2: Quality Checker
# ============================================================
class QualityCheckerAgent:
    def __init__(self):
        self.generator = QuestionGeneratorAgent()

    def review(self, questions, transcript, difficulty, q_type):
        if not questions:
            return questions

        reflection_prompt = f"""
You are a quality reviewer for children's quiz questions.
Quiz type is {q_type} ONLY.

Review these questions and identify any that are:
- NOT written in Arabic
- Unclear or confusing for a child
- Missing correct_answer
- Grammatically broken
- Wrong format for {q_type}
- Duplicate

Questions:
{json.dumps(questions, ensure_ascii=False)}

Return ONLY JSON:
{{
  "needs_revision": true/false,
  "weak_indices": [list of 0-based indices]
}}
"""
        raw = safe_llm_call([{"role": "user", "content": reflection_prompt}], temperature=0)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            result = json.loads(raw[start:end])
        except json.JSONDecodeError:
            return questions

        if result.get("needs_revision") and result.get("weak_indices"):
            weak = result["weak_indices"]
            print(f"🔄 Reflection: regenerating {len(weak)} weak questions...")
            good_questions = [q for i, q in enumerate(questions) if i not in weak]
            new_questions = self.generator.generate(
                transcript, difficulty, q_type, len(weak),
                existing_questions=good_questions
            )
            for i, idx in enumerate(weak):
                if i < len(new_questions) and idx < len(questions):
                    questions[idx] = new_questions[i]

        return questions


# ============================================================
# AGENT 3: Evaluator
# ============================================================
class EvaluatorAgent:
    def evaluate(self, questions, student_answers):
        score = 0
        feedback = []

        for i in range(min(len(questions), len(student_answers))):
            q = questions[i]
            student_ans = student_answers[i]
            correct_ans = q.get("correct_answer", "")

            prompt = f"""
You are a fair AI teacher correcting a child's answer.
Question: {q['question']}
Correct Answer: {correct_ans}
Student's Answer: {student_ans}
Rules:
- Be flexible with wording, short answers are ok
- If student didn't answer, say "لم يتم إدخال إجابة"
- Only mark wrong if clearly incorrect
Return ONLY JSON:
{{"is_correct": true/false, "explanation": "شرح بالعربية لو غلط، فاضي لو صح"}}
"""
            raw = safe_llm_call([{"role": "user", "content": prompt}], temperature=0)
            try:
                start = raw.find("{")
                end = raw.rfind("}") + 1
                result = json.loads(raw[start:end])
            except json.JSONDecodeError:
                result = {"is_correct": False, "explanation": "خطأ في التصحيح"}

            if result.get("is_correct"):
                score += 1
                feedback.append({"status": "Correct", "explanation": ""})
            else:
                feedback.append({"status": "Wrong", "explanation": result.get("explanation", "")})

        return score, feedback


# ============================================================
# STORAGE — JSON files محلي
# ============================================================
QUIZZES_FOLDER = "quizzes"
os.makedirs(QUIZZES_FOLDER, exist_ok=True)


class QuizStorage:
    def save(self, quiz_name, lesson_name, difficulty, q_type, questions):
        data = {
            "quiz_name": quiz_name,
            "lesson_name": lesson_name,
            "difficulty": difficulty,
            "q_type": q_type,
            "questions": questions,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        path = os.path.join(QUIZZES_FOLDER, f"{quiz_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def load(self, quiz_name):
        path = os.path.join(QUIZZES_FOLDER, f"{quiz_name}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_all(self):
        quizzes = []
        for file in os.listdir(QUIZZES_FOLDER):
            if file.endswith(".json"):
                with open(os.path.join(QUIZZES_FOLDER, file), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    quizzes.append({
                        "quiz_name": data.get("quiz_name", ""),
                        "lesson_name": data.get("lesson_name", ""),
                        "difficulty": data.get("difficulty", ""),
                        "q_type": data.get("q_type", ""),
                        "num_questions": len(data.get("questions", [])),
                        "created_at": data.get("created_at", "")
                    })
        return quizzes

    def delete(self, quiz_name):
        path = os.path.join(QUIZZES_FOLDER, f"{quiz_name}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False


# ============================================================
# ORCHESTRATOR
# ============================================================
class QuizOrchestratorAgent:
    def __init__(self):
        self.generator = QuestionGeneratorAgent()
        self.checker   = QualityCheckerAgent()
        self.evaluator = EvaluatorAgent()
        self.storage   = QuizStorage()

    def generate_quiz(self, transcript, difficulty, q_type, num_q):
        print(f"\n🚀 Generating {num_q} {q_type} questions ({difficulty})...")
        questions = self.generator.generate(transcript, difficulty, q_type, num_q)
        print(f"✅ Generator created {len(questions)} questions")
        questions = self.checker.review(questions, transcript, difficulty, q_type)
        print(f"✅ Quality check done")
        return questions

    def save_quiz(self, quiz_name, lesson_name, difficulty, q_type, questions):
        return self.storage.save(quiz_name, lesson_name, difficulty, q_type, questions)

    def load_quiz(self, quiz_name):
        return self.storage.load(quiz_name)

    def list_quizzes(self):
        return self.storage.list_all()

    def delete_quiz(self, quiz_name):
        return self.storage.delete(quiz_name)

    def evaluate_quiz(self, questions, student_answers):
        return self.evaluator.evaluate(questions, student_answers)


# ============================================================
# HTML GENERATOR
# ============================================================
def generate_quiz_html(questions: list, quiz_name: str, show_answers: bool = False) -> str:
    label = "نسخة المعلم" if show_answers else "نسخة الطالب"
    letters = ["أ", "ب", "ج", "د"]

    questions_html = ""
    for i, q in enumerate(questions):
        options_html = ""
        opts = q.get("options", [])
        if opts:
            for j, opt in enumerate(opts):
                letter = letters[j] if j < len(letters) else str(j + 1)
                options_html += f'<div class="option"><span class="letter">{letter}</span> {opt}</div>'
        else:
            options_html = '<div class="option blank">الإجابة: ___________________________</div>'

        answer_html = ""
        if show_answers and q.get("correct_answer"):
            answer_html = f'<div class="answer">✓ الإجابة الصحيحة: {q["correct_answer"]}</div>'

        questions_html += f"""<div class="q-block">
            <div class="q-text">{i + 1}. {q.get("question", "")}</div>
            {options_html}{answer_html}
        </div>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<title>{quiz_name}</title>
<style>
  body {{ font-family: Arial, sans-serif; direction: rtl; padding: 40px; color: #222; }}
  h1 {{ text-align: center; color: #1a1a2e; }}
  .label {{ text-align: center; color: #888; margin-bottom: 30px; }}
  .q-block {{ border-right: 4px solid #3498db; background: #f9f9f9;
              padding: 12px 16px; margin-bottom: 16px; border-radius: 4px; }}
  .q-text {{ font-weight: bold; margin-bottom: 8px; font-size: 15px; }}
  .option {{ padding: 3px 12px; color: #444; }}
  .letter {{ font-weight: bold; margin-left: 6px; }}
  .blank {{ color: #999; font-style: italic; }}
  .answer {{ margin-top: 8px; padding-top: 6px; border-top: 1px dashed #ccc;
             color: #27ae60; font-weight: bold; }}
  @media print {{ body {{ padding: 20px; }} }}
</style>
</head>
<body>
  <h1>{quiz_name}</h1>
  <p class="label">({label})</p>
  {questions_html}
  <p style="text-align:center;color:#aaa;margin-top:30px;font-size:12px;">
    لطباعة PDF: اضغط Ctrl+P واختار "Save as PDF"
  </p>
</body>
</html>"""


# ============================================================
# PUBLIC API
# ============================================================
orchestrator = QuizOrchestratorAgent()


def generate_questions(transcript: str, difficulty: str, q_type: str, num_q: int):
    return orchestrator.generate_quiz(transcript, difficulty, q_type, num_q)


def save_quiz(quiz_name: str, lesson_name: str, difficulty: str, q_type: str, questions: list):
    return orchestrator.save_quiz(quiz_name, lesson_name, difficulty, q_type, questions)


def load_quiz(quiz_name: str):
    return orchestrator.load_quiz(quiz_name)


def list_quizzes():
    return orchestrator.list_quizzes()


def delete_quiz(quiz_name: str):
    return orchestrator.delete_quiz(quiz_name)


def evaluate_answers_ai(questions: list, student_answers: list, transcript=None):
    return orchestrator.evaluate_quiz(questions, student_answers)


def get_quiz_html(quiz_name: str, show_answers: bool = False) -> str:
    data = orchestrator.load_quiz(quiz_name)
    if not data:
        return None
    return generate_quiz_html(data["questions"], quiz_name, show_answers)