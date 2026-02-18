import streamlit as st
from quiz_agent import find_transcript, generate_questions

st.set_page_config(page_title="Agentic Quiz")

# -------- Session State --------
if "step" not in st.session_state:
    st.session_state.step = 0

if "lesson_text" not in st.session_state:
    st.session_state.lesson_text = None

if "questions" not in st.session_state:
    st.session_state.questions = []

if "answers" not in st.session_state:
    st.session_state.answers = []


st.title("🤖 AI Quiz Agent")

# -------- Step 0: Ask lesson --------
if st.session_state.step == 0:
    st.chat_message("assistant").write(
        "👋 أهلاً! تحب تعمل كويز عن درس إيه؟"
    )

    user_input = st.chat_input("اكتب اسم الدرس")

    if user_input:
        lesson, lesson_name = find_transcript(user_input)

        if lesson:
            st.session_state.lesson_text = lesson
            st.session_state.lesson_name = lesson_name
            st.session_state.step = 1
            st.rerun()
        else:
            st.chat_message("assistant").write(
                "❌ مش لاقي الدرس ده، حاول تكتب اسم تاني."
            )

# -------- Step 1: Generate quiz --------
elif st.session_state.step == 1:
    st.chat_message("assistant").write(
        f"📘 تمام! هنعمل كويز عن درس **{st.session_state.lesson_name}**"
    )
    st.session_state.difficulty = st.selectbox(
        "تحب الصعوبة إيه؟",
        ["easy", "hard"]
    )

    st.session_state.q_type = st.selectbox(
        "تحب نوع الأسئلة؟",
        ["MCQ", "True/False", "Complete"]
    )

    num_q = st.slider("عدد الأسئلة", 1, 10, 5)

    if st.button("ابدأ الكويز 🚀"):
        st.session_state.questions = generate_questions(
            st.session_state.lesson_text,
            st.session_state.difficulty,
            st.session_state.q_type,
            num_q
        )
        st.session_state.step = 2
        st.rerun()

# 
# -------- Step 2: Quiz --------
elif st.session_state.step == 2:
    st.subheader("✍️ جاوب على الأسئلة")

    temp_answers = [] # نستخدم قائمة مؤقتة

    for i, q in enumerate(st.session_state.questions):
        st.write(f"Q{i+1}: {q['question']}")

        # لو فيه خيارات اظهر راديو، لو مفيش اظهر مكان للكتابة
        if "options" in q and q["options"]:
            ans = st.radio(
                "اختار إجابة",
                q["options"],
                key=f"q_{i}"
            )
        else:
            ans = st.text_input(
                "اكتب إجابتك هنا",
                key=f"q_{i}"
            )
        temp_answers.append(ans)

    if st.button("صحح الكويز ✅"):
        st.session_state.answers = temp_answers # حفظ الإجابات في السيشين
        st.session_state.step = 3
        st.rerun()
# -------- Step 3: Result --------
elif st.session_state.step == 3:
    st.subheader("🎯 نتيجة الكويز")
    
    with st.spinner("جاري تصحيح إجاباتك بواسطة المعلم الذكي..."):
        # هنا بنادي الدالة اللي بتستخدم AI للتصحيح
        from quiz_agent import evaluate_answers_ai 
        score, feedback = evaluate_answers_ai(
            st.session_state.questions, 
            st.session_state.answers
        )

    # عرض النتيجة النهائية
    st.success(f"🎯 نتيجتك الإجمالية: {score}/{len(st.session_state.questions)}")

    # عرض تفاصيل كل سؤال
    for i, fb in enumerate(feedback):
        if fb["status"] == "Correct":
            st.success(f"السؤال {i+1}: إجابة صحيحة! برافو ✅")
        else:
            st.error(f"السؤال {i+1}: إجابة غير دقيقة ❌")
            st.info(f"الشرح: {fb['explanation']}")

    if st.button("كويز جديد 🔄"):
        st.session_state.clear()
        st.rerun()        
