import os
from groq import Groq
from dotenv import load_dotenv
import json


load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
TRANSCRIPTS_FOLDER = "transcripts"

def find_transcript(user_text):
    user_text = user_text.lower()

    for file in os.listdir(TRANSCRIPTS_FOLDER):
        name = file.replace(".txt", "").lower()

        if name in user_text or user_text in name:
            with open(
                os.path.join(TRANSCRIPTS_FOLDER, file),
                "r",
                encoding="utf-8"
            ) as f:
                return f.read(), name

    return None, None

def generate_questions(transcript, difficulty, q_type, num_q):
    prompt = f"""
    You are an AI teacher for children.

    Generate {num_q} {q_type} questions from the following transcript.
    Difficulty level: {difficulty}

    
    Rules:
    - If difficulty is hard, questions must be indirect and require thinking.
    - Do NOT repeat transcript sentences directly.
    - Output JSON only as a list of objects.
    - Each object must have:
    - question (string)
    -Do NOT return plain strings.
    - Do Not Include correct_answer and explanation.

    Question formats(very important, follow exactly):

        1) If q_type is "MCQ":
        - Each object must have:
        - question (string)
        - options (array of strings)

        2) If q_type is "True/False":
        - Each object must have:
        - question (string)
        - options = ["True", "False"]

        3) If q_type is "Complete":
        - Each object must have:
        - question (string)
        - Do NOT include options at all.
            
    Transcript:
    {transcript}
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    content = response.choices[0].message.content.strip()
    
    # 🟢 لو المحتوى فارغ، رجع قائمة فاضية بدل crash
    if not content:
        return []

    # 🟢 حاول نحول المحتوى لـ JSON
    try:
        questions = json.loads(content)
    except json.JSONDecodeError:
        print("⚠️ Warning: Model returned invalid JSON:")
        print(content)
        return []

    return questions

def evaluate_answers_ai(questions, student_answers):
    score = 0
    feedback = []

    total = min(len(questions), len(student_answers))

    for i in range(total):
        q = questions[i]
        student_answer = student_answers[i]

        # لو الإجابة فاضية
        if not student_answer or student_answer.strip() == "":
            feedback.append({
                "status": "Wrong",
                "explanation": "لم يتم إدخال إجابة"
            })
            continue

        prompt = f"""
        You are an AI evaluator for children.

        Question:
        {q["question"]}

        Student Answer:
        {student_answer}

        Rules:
        - Decide if the answer is correct or wrong.
        - Respond in JSON ONLY.

        Output format:
        {{
          "is_correct": true,
          "explanation": "short explanation in Arabic"
        }}
        """

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        raw = response.choices[0].message.content.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1

        result = json.loads(raw[start:end])

        if result["is_correct"]:
            score += 1
            feedback.append({
                "status": "Correct",
                "explanation": ""
            })
        else:
            feedback.append({
                "status": "Wrong",
                "explanation": result["explanation"]
            })

    return score, feedback
