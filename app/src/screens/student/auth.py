"""Student sign-in (roll number + face + head-turn liveness) and registration.

Why not face-only login? Searching the whole school for a face (1:N) lets
anyone who looks similar log in as someone else, and a printed photo works.
Here the student claims an identity with their roll number, the face must
match *that* student (1:1), and a second photo with the head turned must also
match: a flat photo cannot turn its head.
"""

from __future__ import annotations

import streamlit as st

from src import config, services
from src.core import face, security, voice
from src.db import DuplicateError, Repository
from src.screens.student.face_capture import capture_shots, find_duplicate


def sign_in(student: dict) -> None:
    for k in ("s_login", "reg_shots"):
        st.session_state.pop(k, None)
    st.session_state["student_id"] = student["student_id"]
    st.rerun()


def render(repo: Repository) -> None:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        login_tab, register_tab = st.tabs(["Sign in", "Register"])
        with login_tab:
            _login(repo)
        with register_tab:
            _register(repo)


# ---- Sign in ----------------------------------------------------------------


def _login(repo: Repository) -> None:
    state = st.session_state.setdefault("s_login", {"step": "roll"})
    throttle = security.LoginThrottle(st.session_state, "student")
    if wait := throttle.locked_for():
        st.error(f"Too many failed attempts. Try again in {wait} s.")
        return

    if state["step"] == "roll":
        with st.form("s_roll"):
            roll = st.text_input("Roll number", placeholder="21BCS042")
            ok = st.form_submit_button("Continue", type="primary", width="stretch")
        if ok:
            student = repo.get_student_by_roll(security.normalise_roll(roll))
            if student is None:
                st.error("No student with that roll number. Register first.")
            else:
                state.update(step="front", student_id=student["student_id"], name=student["name"])
                st.rerun()
        return

    student = repo.get_student(state["student_id"])
    if student is None:
        st.session_state["s_login"] = {"step": "roll"}
        st.rerun()
    st.markdown(f"Signing in as **{student['name']}** · `{student['roll_no']}`")
    if st.button("Not you?", type="tertiary"):
        st.session_state["s_login"] = {"step": "roll"}
        st.rerun()

    if state["step"] == "front":
        st.markdown("**Step 1 of 2:** look straight at the camera.")
        pic = st.camera_input("Front photo", key="s_login_front", label_visibility="collapsed")
        if pic is not None:
            res = services.analyse_selfie(pic.getvalue())
            if not res.ok:
                st.error(res.message)
                return
            if abs(res.turn) > config.LIVENESS_FRONTAL_MAX_OFFSET:
                st.warning("Please face the camera directly for this photo, then retake.")
                return
            ok, _ = face.verify_face(res.embedding, student["face_embeddings"])
            if not ok:
                throttle.fail()
                st.error("Face does not match this roll number.")
                return
            state.update(step="turn", front_turn=res.turn)
            st.rerun()

    elif state["step"] == "turn":
        st.markdown("**Step 2 of 2:** now **turn your head to one side** and take another photo. "
                    "This proves you're a real person, not a picture.")
        pic = st.camera_input("Turned photo", key="s_login_turn", label_visibility="collapsed")
        if pic is not None:
            res = services.analyse_selfie(pic.getvalue())
            if not res.ok:
                st.error(res.message)
                return
            if abs(res.turn - state["front_turn"]) < config.LIVENESS_TURN_MIN_OFFSET:
                st.warning("Turn your head a little more (about 30°) and retake.")
                return
            ok, _ = face.verify_face(res.embedding, student["face_embeddings"],
                                     config.FACE_MATCH_THRESHOLD + 0.05)  # profile views are harder
            if not ok:
                throttle.fail()
                st.error("Face does not match this roll number.")
                st.session_state["s_login"] = {"step": "front", "student_id": student["student_id"]}
                return
            throttle.succeed()
            st.toast(f"Welcome back, {student['name']}!", icon=":material/waving_hand:")
            sign_in(student)


# ---- Register ---------------------------------------------------------------


def _register(repo: Repository) -> None:
    name = st.text_input("Full name", placeholder="Rahul Sharma", key="reg_name")
    roll = st.text_input("Roll number", placeholder="21BCS042", key="reg_roll")

    shots = capture_shots("reg_shots")

    st.markdown("**Optional: voice profile** for roll-call attendance")
    st.caption("Read aloud for about 5 seconds, e.g. “My name is Rahul Sharma and I am present today.”")
    clip = st.audio_input("Voice sample", key="reg_voice", label_visibility="collapsed")

    consent = st.checkbox(
        "I agree that my face (and voice, if recorded) are converted into numeric templates and stored "
        "to mark my attendance. Photos and audio themselves are not stored. I can delete my data any time.",
        key="reg_consent")

    if not st.button("Create my profile", type="primary", width="stretch",
                     disabled=shots is None or not consent):
        return

    roll_no = security.normalise_roll(roll)
    problem = ("Please enter your name." if not name.strip() else None) or security.roll_problem(roll_no)
    if problem:
        st.error(problem)
        return
    if repo.get_student_by_roll(roll_no):
        st.error("That roll number is already registered. Sign in instead.")
        return
    with st.spinner("Checking for duplicate registrations..."):
        if find_duplicate(repo.all_face_embeddings(), shots) is not None:
            st.error("This face is already registered under another roll number. "
                     "Ask your teacher if you think this is a mistake.")
            return

    voice_emb = None
    if clip is not None:
        try:
            voice_emb = voice.enrollment_embedding(services.voice_encoder(), clip.getvalue())
        except Exception:
            st.warning("Couldn't use that voice sample (too short or silent). "
                       "You can add your voice later from your profile.")
    try:
        student = repo.create_student(roll_no, name.strip(), [e.tolist() for e in shots], voice_emb)
    except DuplicateError:
        st.error("That roll number is already registered.")
        return
    st.toast(f"Profile created. Hi {student['name']}!", icon=":material/celebration:")
    sign_in(student)
