"""Student portal: sign-in gate, join-link handling, dashboard."""

from __future__ import annotations

import streamlit as st

from src.core import security
from src.db import Repository
from src.screens.student import auth, dashboard
from src.ui import components as ui


def render(repo: Repository) -> None:
    student_id = st.session_state.get("student_id")
    student = repo.get_student(student_id) if student_id else None

    if student is None:
        st.session_state.pop("student_id", None)
        if ui.top_bar("Student portal", "Back to home", key="s_home"):
            st.session_state["portal"] = None
            st.session_state.pop("pending_join", None)
            st.rerun()
        if code := st.session_state.get("pending_join"):
            st.info(f"Sign in or register to join the class with code **{ui.esc(code)}**.",
                    icon=":material/qr_code_2:")
        auth.render(repo)
        return

    if ui.top_bar(f"{student['name']} · {student['roll_no']}", "Sign out", key="s_logout"):
        for k in [k for k in st.session_state if k.startswith(("student", "s_", "reg_", "pending"))]:
            del st.session_state[k]
        st.session_state["portal"] = None
        st.rerun()

    if code := st.session_state.pop("pending_join", None):
        join_dialog(repo, student, code)

    dashboard.render(repo, student)


def join_subject(repo: Repository, student_id: int, code: str) -> tuple[bool, str]:
    """Enroll a student by join code. Returns (joined, message)."""
    subject = repo.subject_by_join_code(security.normalise_join_code(code))
    if subject is None:
        return False, "No subject with that code. Check it with your teacher."
    if not subject["join_open"]:
        return False, "Joining is closed for this subject. Ask your teacher to open it."
    if not repo.enroll(subject["subject_id"], student_id):
        return False, f"You're already in {subject['name']}."
    return True, f"Joined {subject['name']} ({subject['teacher_name']})"


@st.dialog("Join a subject")
def join_dialog(repo: Repository, student: dict, code: str = "") -> None:
    code = st.text_input("Join code from your teacher", value=code, placeholder="K7Q2MX", max_chars=12)
    if not st.button("Join", type="primary", width="stretch"):
        return
    joined, message = join_subject(repo, student["student_id"], code)
    if joined:
        st.toast(message, icon=":material/check_circle:")
        st.rerun()
    st.error(message)
