# AI Quiz Generator API

## تشغيل الـ API

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

الـ API بيشتغل على: http://localhost:8000

## الـ Endpoints

| Method | URL | الوصف |
|--------|-----|-------|
| POST | /generate-quiz | توليد أسئلة |
| POST | /save-quiz | حفظ كويز |
| GET | /quizzes | قائمة الكويزات |
| GET | /quiz/{name} | جيب كويز |
| POST | /evaluate | تصحيح إجابات |
| GET | /quiz/{name}/pdf/student | PDF بدون إجابات |
| GET | /quiz/{name}/pdf/teacher | PDF بالإجابات |

## Documentation
بعد التشغيل افتح: http://localhost:8000/docs

## الـ .env
```
GROQ_API_KEY=your_key_here
```

## الـ Folder Structure
```
project/
├── main.py
├── quiz_agents_v2.py
├── requirements.txt
├── .env
├── transcripts/     ← ملفات الدروس .txt
└── quizzes/         ← الكويزات المحفوظة (تلقائي)
```

## مثال استخدام

### توليد كويز
```json
POST /generate-quiz
{
  "lesson_name": "المثابرة",
  "difficulty": "easy",
  "q_type": "MCQ",
  "num_q": 5
}
```

### تصحيح إجابات
```json
POST /evaluate
{
  "questions": [...],
  "answers": ["إجابة 1", "إجابة 2", ...]
}
```