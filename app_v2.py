import streamlit as st
import json
import os
from quiz_agents_v2 import (
    find_transcript, generate_questions,
    save_quiz, load_quiz, list_quizzes,
    evaluate_answers_ai, generate_quiz_pdf
)

st.set_page_config(page_title="AI Quiz Agent", page_icon="🤖")

defaults = {
    "mode": None, "step": 0,
    "lesson_text": None, "lesson_name": None,
    "questions": [], "answers": [],
    "current_quiz_name": None,
    "difficulty": "easy", "q_type": "MCQ",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state.mode is None:
    st.title("🤖 AI Quiz Agent")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("👨‍🏫 معلم", use_container_width=True):
            st.session_state.mode = "teacher"
            st.rerun()
    with col2:
        if st.button("👦 طالب", use_container_width=True):
            st.session_state.mode = "student"
            st.rerun()

elif st.session_state.mode == "teacher":
    st.title("👨‍🏫 لوحة المعلم")
    if st.button("🔙 رجوع"):
        st.session_state.clear(); st.rerun()

    if st.session_state.step == 0:
        st.chat_message("assistant").write("📚 اكتب اسم الدرس")
        user_input = st.chat_input("اسم الدرس")
        if user_input:
            lesson, lesson_name = find_transcript(user_input)
            if lesson:
                st.session_state.lesson_text = lesson
                st.session_state.lesson_name = lesson_name
                st.session_state.step = 1
                st.rerun()
            else:
                st.error("❌ مش لاقي الدرس ده")

    elif st.session_state.step == 1:
        st.success(f"✅ درس: **{st.session_state.lesson_name}**")
        difficulty = st.selectbox("الصعوبة", ["easy", "medium", "hard"])
        q_type = st.selectbox("نوع الأسئلة", ["MCQ", "True/False", "Complete"])
        num_q = st.slider("عدد الأسئلة", 1, 10, 5)
        if st.button("🚀 ولّد الأسئلة"):
            with st.spinner("🤖 الـ Agents شغالين..."):
                st.session_state.questions = generate_questions(
                    st.session_state.lesson_text, difficulty, q_type, num_q)
                st.session_state.difficulty = difficulty
                st.session_state.q_type = q_type
            st.session_state.step = 2
            st.rerun()

    elif st.session_state.step == 2:
        st.subheader("🔍 راجع الأسئلة")
        for i, q in enumerate(st.session_state.questions):
            with st.expander(f"س{i+1}: {q['question']}"):
                st.write(f"**✅ الإجابة:** {q.get('correct_answer','')}")
                if "options" in q:
                    for opt in q["options"]:
                        st.write(f"  - {opt}")
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("❌ أعد التوليد", use_container_width=True):
                st.session_state.step = 1; st.rerun()
        with col2:
            if st.button("✅ موافق - احفظ", use_container_width=True):
                st.session_state.step = 3; st.rerun()

    elif st.session_state.step == 3:
        st.subheader("💾 احفظ الكويز")
        quiz_name = st.text_input(
            "اسم الكويز",
            value=f"{st.session_state.lesson_name}_{st.session_state.difficulty}"
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 احفظ", use_container_width=True):
                if quiz_name.strip():
                    save_quiz(quiz_name.strip(), st.session_state.lesson_name,
                              st.session_state.difficulty, st.session_state.q_type,
                              st.session_state.questions)
                    st.session_state.current_quiz_name = quiz_name.strip()
                    st.success(f"✅ تم حفظ **{quiz_name}**!")
                    st.balloons()
        with col2:
            if st.button("📄 تحميل HTML", use_container_width=True):
                try:
                    html_path = generate_quiz_pdf(
                        st.session_state.questions,
                        quiz_name.strip() or "quiz",
                        show_answers=True
                    )
                    with open(html_path, "rb") as f:
                        st.download_button(
                            "⬇️ اضغط للتحميل",
                            data=f.read(),
                            file_name=f"{quiz_name.strip()}_answers.html",
                            mime="text/html"
                        )
                except Exception as e:
                    st.error(f"❌ {e}")
        if st.button("🆕 كويز جديد"):
            st.session_state.clear(); st.rerun()

elif st.session_state.mode == "student":
    st.title("👦 حل الكويز")
    if st.button("🔙 رجوع"):
        st.session_state.clear(); st.rerun()

    if st.session_state.step == 0:
        quizzes = list_quizzes()
        if not quizzes:
            st.warning("📭 مفيش كويزات متاحة.")
        else:
            st.write("### اختار الكويز:")
            for qz in quizzes:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"📝 **{qz['quiz_name']}** | {qz['lesson_name']} | {qz['difficulty']} | {qz['num_questions']} أسئلة")
                with col2:
                    if st.button("▶️ حله", key=f"solve_{qz['file']}"):
                        data = load_quiz(qz['file'])
                        if data:
                            st.session_state.questions = data["questions"]
                            st.session_state.current_quiz_name = qz["quiz_name"]
                            st.session_state.step = 1
                            st.rerun()
                with col3:
                    if st.button("📄 HTML", key=f"html_{qz['file']}"):
                        data = load_quiz(qz['file'])
                        if data:
                            try:
                                html_path = generate_quiz_pdf(
                                    data["questions"],
                                    qz["quiz_name"],   # ✅ صح
                                    show_answers=False
                                )
                                with open(html_path, "rb") as f:
                                    st.download_button(
                                        "⬇️ تحميل",
                                        data=f.read(),
                                        file_name=f"{qz['quiz_name']}.html",  # ✅ صح
                                        mime="text/html",
                                        key=f"dl_{qz['file']}"
                                    )
                            except Exception as e:
                                st.error(f"❌ {e}")

    elif st.session_state.step == 1:
        st.subheader(f"✍️ {st.session_state.current_quiz_name}")
        temp_answers = []
        for i, q in enumerate(st.session_state.questions):
            st.write(f"**س{i+1}:** {q['question']}")
            if "options" in q and q["options"]:
                ans = st.radio("اختار إجابة", q["options"], key=f"q_{i}", index=None)
            else:
                ans = st.text_input("اكتب إجابتك", key=f"q_{i}")
            temp_answers.append(ans if ans else "")
            st.divider()
        if st.button("✅ صحح الكويز"):
            st.session_state.answers = temp_answers
            st.session_state.step = 2
            st.rerun()

    elif st.session_state.step == 2:
        st.subheader("🎯 نتيجتك")
        with st.spinner("🤖 بيصحح..."):
            score, feedback = evaluate_answers_ai(
                st.session_state.questions, st.session_state.answers)
        total = len(st.session_state.questions)
        percentage = score / total if total > 0 else 0
        if percentage >= 0.8:
            st.success(f"🌟 ممتاز! {score}/{total}")
        elif percentage >= 0.5:
            st.warning(f"👍 كويس! {score}/{total}")
        else:
            st.error(f"💪 حاول تاني! {score}/{total}")
        for i, fb in enumerate(feedback):
            if fb["status"] == "Correct":
                st.success(f"س{i+1}: صح ✅")
            else:
                st.error(f"س{i+1}: غلط ❌")
                if fb["explanation"]:
                    st.info(f"💡 {fb['explanation']}")
        if st.button("🔄 كويز تاني"):
            st.session_state.step = 0
            st.session_state.questions = []
            st.session_state.answers = []
            st.rerun()