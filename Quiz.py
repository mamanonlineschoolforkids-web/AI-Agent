from typing import TypedDict, List
from groq import Groq
import os, json, re
import time
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
MAX_CHARS_PER_CHUNK = 6000


# ── Safe LLM Call ──────────────────────────────────────
def safe_llm_call(messages: list, temperature: float = 0.3, json_mode: bool = False) -> str:
    try:
        kwargs = dict(
            model=MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=4000
        )
        # JSON mode بيخلي الموديل ملتزم بإخراج JSON صحيح نحوياً (مش هيرجع نص عشوائي حواليه)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            wait = re.search(r"try again in (.+?)\.", err)
            wait_msg = wait.group(1) if wait else "بعد شوية"
            raise Exception(f"⏳ وصلت للحد المسموح، حاول تاني بعد {wait_msg}")
        elif "413" in err:
            raise Exception("📝 النص طويل جداً")
        else:
            raise Exception(f"❌ خطأ: {err[:100]}")


# ── Helper: تلخيص الـ transcript لو كبير ──────────────
def smart_transcript(transcript: str) -> str:
    if len(transcript) <= MAX_CHARS_PER_CHUNK:
        return transcript

    chunks = [transcript[i:i+MAX_CHARS_PER_CHUNK]
              for i in range(0, len(transcript), MAX_CHARS_PER_CHUNK)]
    print(f"📄 Transcript كبير — بيتلخص في {len(chunks)} أجزاء...")

    summaries = []
    for idx, chunk in enumerate(chunks):
        prompt = f"""
Summarize the key educational facts from this text in Arabic.
Max 250 words. Only facts useful for quiz questions.
Be specific — include names, numbers, definitions, and examples.
Text: {chunk}
"""
        summary = safe_llm_call([{"role": "user", "content": prompt}], temperature=0)
        summaries.append(f"[Part {idx+1}]\n{summary}")
        print(f"   ✅ Chunk {idx+1}/{len(chunks)} done")
        time.sleep(8)
    return "\n\n".join(summaries)


# ── State ──────────────────────────────────────────────
class QuizState(TypedDict):
    lesson_name: str
    transcript: str
    difficulty: str
    q_type: str
    num_questions: int
    smart_text: str
    questions: List[dict]
    weak_indices: List[int]
    is_approved: bool
    attempts: int


# ── Node 1: Preprocessor ───────────────────────────────
def preprocessor_node(state: QuizState) -> dict:
    # لو smart_text جاهز تخطى التلخيص فوراً
    if state.get("smart_text"):
        return {"smart_text": state["smart_text"]}

    transcript = state["transcript"]
    if not transcript or len(transcript.strip()) < 50:
        return {"smart_text": "", "transcript": ""}

    smart = smart_transcript(transcript)
    print(f"✅ Transcript جاهز ({len(transcript)} حرف)")
    return {"smart_text": smart[:8000]}


# ── Helper: استخلاص الأسئلة من رد الموديل بأمان ────────
def extract_questions(content: str) -> list:
    """يقبل الرد سواء كان list مباشرة أو object فيه key زي questions."""
    content = content.strip()
    # شيل أي ```json ... ``` fences لو الموديل حطها بالغلط
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # آخر محاولة: هات أول [...] موجودة في النص
        match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # الموديل ممكن يرجع {"questions": [...]}
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


# ── Helper: خلط ترتيب الاختيارات عشان نمنع "الإجابة الصحيحة دايماً حرف ب" ─
def shuffle_question_options(q: dict) -> dict:
    import random
    options = q.get("options")
    correct = q.get("correct_answer")
    if options and isinstance(options, list) and correct in options:
        shuffled = options[:]
        random.shuffle(shuffled)
        q["options"] = shuffled
        q["correct_answer"] = correct  # القيمة نفسها لسه موجودة في الاختيارات بعد الخلط
    return q


# ── Node 2: Generator ──────────────────────────────────
def generator_node(state: QuizState) -> dict:
    smart_text    = state["smart_text"]
    difficulty    = state["difficulty"]
    q_type        = state["q_type"]
    num_questions = state["num_questions"]
    weak_indices  = state.get("weak_indices", [])
    existing_questions = state.get("questions", [])

    num_to_generate = len(weak_indices) if weak_indices else num_questions

    avoid_section = ""
    if existing_questions:
        good_qs = [q for i, q in enumerate(existing_questions) if i not in weak_indices]
        if good_qs:
            avoid_section = f"""
These questions already exist — do NOT repeat them or test the same concept:
{json.dumps([q.get("question","") for q in good_qs], ensure_ascii=False)}
"""

    hard_rules = ""
    if difficulty == "hard":
        hard_rules = """
HARD DIFFICULTY RULES:
- STRICTLY FORBIDDEN question starts: "ما هو", "ما هي", "عرف", "ما تعريف", or any rewording of a definition question.
- Every question must start with or clearly require: لماذا / كيف / ماذا يحدث لو / ما النتيجة المترتبة على / قارن بين
- The question must force the student to connect at least two ideas from the text, or apply the idea to a new situation not mentioned literally in the text.
- Wrong options must be plausible misunderstandings a student could actually believe — not random or absurd, but not so close they are ambiguous with the correct answer either.
- BAD example (reject this style): "ما هي المثابرة؟" with an option that is literally the definition.
- GOOD example (use this style): "لماذا يعتبر تغيير الوسيلة عند مواجهة عقبة سلوكاً مثابراً وليس استسلاماً؟"
"""
    elif difficulty == "medium":
        hard_rules = """
MEDIUM DIFFICULTY RULES:
- Mix between direct and analytical questions.
- Some questions should ask about examples or real-life applications of concepts.
- Avoid very obvious true/false statements that any student would know without reading.
- Wrong options should be somewhat plausible — not random or absurd.
- Good example: "ما الفرق بين الشخص المثابر والشخص المستسلم عند مواجهة عقبة؟"
"""

    prompt = f"""
You are an AI teacher for children.
⚠️ IMPORTANT: Generate ONLY {q_type} questions. Do NOT generate any other type.
Generate {num_to_generate} {q_type} questions from the following text.
Difficulty level: {difficulty}

Rules:
- Generate ALL questions and answers in Arabic only.
- Every question must be UNIQUE in BOTH wording AND idea.
- Cover DIFFERENT parts of the text.
- Wrong answer options must be logical but clearly different from each other.
- NEVER use "لجميع الإجابات السابقة" as an answer option.
- NEVER include Chinese, English, or any non-Arabic characters in questions or options.
{hard_rules}
{avoid_section}

Question formats — follow EXACTLY based on q_type:
1) If q_type is MCQ: {{"question":"...","options":["...","...","...","..."],"correct_answer":"..."}}
   options must have EXACTLY 4 items.
2) If q_type is True/False: {{"question":"...","options":["صح","خطأ"],"correct_answer":"صح or خطأ"}}
   options must have EXACTLY 2 items: ["صح","خطأ"] — NEVER 4 items for True/False.
3) If q_type is Complete: {{"question":"... ___ ...","correct_answer":"..."}}
   NO options field at all.

Current q_type is: {q_type}
Generate ONLY {q_type} questions. Do not mix types.

Do not use markdown.
Do not add explanations.
Return ONLY a valid JSON object with this exact shape (no text before or after):
{{
"questions": [
  {{
    "question":"...",
    "options":["...","..."],
    "correct_answer":"..."
  }}
]
}}

Text:
{smart_text}
"""
    # نحاول نولد الأسئلة، ولو الـ JSON اترفض نعيد المحاولة لحد 3 مرات
    # بدل ما نرجع قائمة فاضية على طول ونضيع البatch كله
    new_questions = []
    last_error = None
    for attempt in range(3):
        try:
            content = safe_llm_call(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                json_mode=True
            )
        except Exception as e:
            print(f"❌ Generator error (attempt {attempt+1}): {e}")
            last_error = e
            time.sleep(3)
            continue

        new_questions = extract_questions(content)
        if new_questions:
            break

        print(f"⚠️ Invalid/empty JSON from model, retrying ({attempt+1}/3)...")
        time.sleep(2)

    if not new_questions and last_error:
        raise last_error

    # خلط ترتيب الاختيارات عشان الإجابة الصحيحة متبقاش دايماً في نفس المكان
    new_questions = [shuffle_question_options(q) for q in new_questions]

    if weak_indices and existing_questions:
        updated = existing_questions.copy()

        for i, idx in enumerate(weak_indices):
            if i < len(new_questions) and idx < len(updated):
                updated[idx] = new_questions[i]

        return {
            "questions": updated,
            "attempts": state.get("attempts", 0) + 1,
            "weak_indices": []
        }

    return {
        "questions": new_questions,
        "attempts": state.get("attempts", 0) + 1,
        "weak_indices": []
    }

# ── Node 3: Checker (rule-based فقط لتوفير tokens) ─────
def checker_node(state: QuizState) -> dict:
    questions = state["questions"]
    q_type    = state["q_type"]

    if not questions:
        return {"is_approved": False, "weak_indices": []}

    weak_indices = []
    seen_questions = set()

    for i, q in enumerate(questions):
        reasons = []
        if not q.get("question", "").strip():
            reasons.append("سؤال فارغ")
        if not q.get("correct_answer", "").strip():
            reasons.append("مفيش إجابة صحيحة")

        if q_type == "MCQ":
            opts = q.get("options", [])
            if len(opts) != 4:
                reasons.append(f"عدد الاختيارات {len(opts)} مش 4")
            if q.get("correct_answer") and q.get("correct_answer") not in opts:
                reasons.append("الإجابة الصحيحة مش في الاختيارات")

        if q_type == "True/False":
            # تصحيح أوتوماتيك للـ options
            q["options"] = ["صح", "خطأ"]
            # تصحيح الـ correct_answer لو مش صح أو خطأ
            ans = q.get("correct_answer", "")
            if ans not in ["صح", "خطأ"]:
                if any(w in ans for w in ["لا", "غلط", "خطأ", "False", "false"]):
                    q["correct_answer"] = "خطأ"
                else:
                    q["correct_answer"] = "صح"

        if q_type == "Complete" and q.get("options"):
            reasons.append("Complete مفروض مفيش options")
        # فحص جودة أسئلة الـ Hard
        if state["difficulty"] == "hard":
            bad_words = ["ما هو", "ما هي", "عرف", "تعريف", "اذكر"]

            question_text = q.get("question", "")

            if any(word in question_text for word in bad_words):
                reasons.append("Hard question is too direct")

            # لازم يكون فيه تفكير مش مجرد حفظ
            thinking_words = [
            "لماذا",
            "كيف",
            "ماذا يحدث",
            "ما النتيجة",
            "قارن"
    ]

            if not any(word in question_text for word in thinking_words):
                reasons.append("Hard question needs deeper thinking")


        q_text = q.get("question", "").strip().lower()
        if q_text in seen_questions:
            reasons.append("سؤال متكرر")
        else:
            seen_questions.add(q_text)

        if reasons:
            print(f"⚠️ سؤال {i+1} فيه مشاكل: {', '.join(reasons)}")
            weak_indices.append(i)

    if weak_indices:
        print(f"🔄 Rule-based: {len(weak_indices)} أسئلة فيها مشاكل")
        return {"is_approved": False, "weak_indices": weak_indices}

    print("✅ Checker: كل الأسئلة تمام")
    return {"is_approved": True, "weak_indices": []}


# ── Conditional Edge ───────────────────────────────────
def should_continue(state: QuizState) -> str:
    if state["is_approved"]:
        return END
    elif state.get("attempts", 0) >= 5:
        print("⚠️ وصلنا للحد الأقصى من المحاولات")
        return END
    else:
        return "generator"


# ── Build Graph ────────────────────────────────────────
graph = StateGraph(QuizState)
graph.add_node("preprocessor", preprocessor_node)
graph.add_node("generator",    generator_node)
graph.add_node("checker",      checker_node)

graph.set_entry_point("preprocessor")
graph.add_edge("preprocessor", "generator")
graph.add_edge("generator",    "checker")
graph.add_conditional_edges("checker", should_continue)

app = graph.compile()


# ── Evaluate Function ──────────────────────────────────
def evaluate_answers(questions: list, student_answers: list):
    score = 0
    feedback = []

    for i in range(min(len(questions), len(student_answers))):
        q           = questions[i]
        student_ans = student_answers[i].strip()
        correct_ans = q.get("correct_answer", "").strip()
        has_options = bool(q.get("options"))

        if has_options:
            is_correct = student_ans.lower() == correct_ans.lower()
            if is_correct:
                score += 1
                feedback.append({"status": "Correct", "explanation": ""})
            else:
                feedback.append({
                    "status": "Wrong",
                    "explanation": f"الإجابة الصحيحة: {correct_ans}"
                })
        else:
            if not student_ans:
                feedback.append({"status": "Wrong", "explanation": "لم يتم إدخال إجابة"})
                continue

            prompt = f"""
You are a fair AI teacher correcting a child's answer.
Question: {q['question']}
Correct Answer: {correct_ans}
Student's Answer: {student_ans}
Return ONLY JSON:
{{"is_correct": true/false, "explanation": "شرح بالعربية لو غلط"}}
"""
            raw = safe_llm_call([{"role": "user", "content": prompt}], temperature=0, json_mode=True)
            try:
                start  = raw.find("{")
                end    = raw.rfind("}") + 1
                result = json.loads(raw[start:end])
            except (json.JSONDecodeError, ValueError):
                result = {"is_correct": False, "explanation": "خطأ في التصحيح"}

            if result.get("is_correct"):
                score += 1
                feedback.append({"status": "Correct", "explanation": ""})
            else:
                feedback.append({"status": "Wrong", "explanation": result.get("explanation", "")})

    return score, feedback


# ── Public Function للاستخدام من main.py ───────────────
def run_quiz_graph(lesson_name: str, transcript: str, difficulty: str,
                   q_type: str, num_questions: int) -> List[dict]:

    BATCH_SIZE = 5

    # 1. التلخيص مرة واحدة بس
    print("⏳ جاري تحضير النص...")
    initial_state = app.invoke({
        "lesson_name":   lesson_name,
        "transcript":    transcript,
        "difficulty":    difficulty,
        "q_type":        q_type,
        "num_questions": min(BATCH_SIZE, num_questions),
        "smart_text":    "",
        "questions":     [],
        "weak_indices":  [],
        "is_approved":   False,
        "attempts":      0
    })

    smart_text_ready = initial_state.get("smart_text", "")
    all_questions    = initial_state.get("questions", [])
    remaining        = num_questions - len(all_questions)

    # 2. باقي الـ batches بدون تلخيص تاني
    max_iterations = 5
    iteration = 0
    while remaining > 0 and iteration < max_iterations:
        batch = min(BATCH_SIZE, remaining)
        print(f"📦 توليد دفعة {batch} أسئلة...")

        result = app.invoke({
            "lesson_name":   lesson_name,
            "transcript":    "",
            "difficulty":    difficulty,
            "q_type":        q_type,
            "num_questions": batch,
            "smart_text":    smart_text_ready,
            "questions":     all_questions,
            "weak_indices":  [],
            "is_approved":   False,
            "attempts":      0
        })

        new_batch = result.get("questions", [])

        # خدي بس الأسئلة الجديدة — مش القديمة اللي اتبعتت في الـ avoid_section
        existing_texts = {q.get("question", "").strip().lower() for q in all_questions}
        batch_questions = [
            q for q in new_batch
            if q.get("question")
            and q.get("correct_answer")
            and q.get("question", "").strip().lower() not in existing_texts
        ]

        all_questions.extend(batch_questions)
        remaining = num_questions - len(all_questions)
        iteration += 1
        print(f"✅ {len(all_questions)}/{num_questions} أسئلة")
        if remaining > 0:
            time.sleep(2)

    # فلترة المكررات
    seen   = set()
    unique = []
    for q in all_questions:
        key = q.get("question", "").strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(q)

    return unique


# ── تست مباشر ──────────────────────────────────────────
if __name__ == "__main__":
    print("🔑 API Key موجود:", bool(os.getenv("GROQ_API_KEY")))

    sample = "المثابرة تعني الاستمرار على الفعل حتى لو قابلت عقبات. المثابر لا يترك هدفه بل يغير الطريق إذا لزم."

    try:
        questions = run_quiz_graph(
            lesson_name="تست",
            transcript=sample,
            difficulty="easy",
            q_type="MCQ",
            num_questions=2
        )
        print(f"\n✅ نجح! اتولد {len(questions)} سؤال")
        for q in questions:
            print(q)
    except Exception as e:
        print(f"\n❌ فشل: {e}")