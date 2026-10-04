"""Teacher portal: sign-in gate, then three sections."""

from __future__ import annotations

import streamlit as st

from src.db import Repository
from src.screens.teacher import analytics, auth, subjects, take_attendance
from src.ui import components as ui

_SECTIONS = {
    "Take attendance": (":material/how_to_reg:", take_attendance.render),
    "Subjects": (":material/menu_book:", subjects.render),
    "Analytics": (":material/insights:", analytics.render),
}


def render(repo: Repository) -> None:
    teacher = st.session_state.get("teacher")
    if teacher is None:
        if ui.top_bar("Teacher portal", "Back to home", key="t_home"):
            st.session_state["portal"] = None
            st.rerun()
        auth.render(repo)
        return

    if ui.top_bar(f"Signed in as {teacher['name']}", "Sign out", key="t_logout"):
        for k in [k for k in st.session_state if k.startswith(("teacher", "draft", "photo", "voice"))]:
            del st.session_state[k]
        st.session_state["portal"] = None
        st.rerun()

    section = st.segmented_control(
        "Section", list(_SECTIONS), default="Take attendance", key="teacher_section",
        format_func=lambda s: f"{_SECTIONS[s][0]} {s}", label_visibility="collapsed",
    ) or "Take attendance"
    st.divider()
    _SECTIONS[section][1](repo, teacher)

