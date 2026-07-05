FROM python:3.9

# إعدادات الحماية الخاصة بـ Hugging Face
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# نسخ وتثبيت المكتبات
COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# نسخ باقي ملفات المشروع
COPY --chown=user . /app

# أمر تشغيل الـ FastAPI على بورت 7860 الإجباري لـ Hugging Face
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
