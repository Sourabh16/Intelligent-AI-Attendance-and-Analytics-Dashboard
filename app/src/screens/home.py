"""Landing screen inside the app: pick a portal."""

from __future__ import annotations

import streamlit as st

from src import config
from src.db import Repository
from src.ui import components as ui


def _go(portal: str) -> None:
    st.session_state["portal"] = portal
    st.rerun()


def render(repo: Repository) -> None:
    ui.brand(config.APP_TAGLINE)
    st.html(
        f'<div class="as-hero"><h1>Attendance in seconds, not minutes.</h1>'
        f'<p>{ui.esc(config.APP_NAME)} recognises every student in a classroom photo or a '
        f'roll-call recording. Then the teacher reviews it and saves it with one click.</p></div>'
    )
    if repo.backend_name.startswith("SQLite"):
        ui.local_mode_notice()

    teacher, student = st.columns(2, gap="large")
    with teacher, st.container(border=True):
        st.subheader(":material/school: I'm a teacher")
        st.write("Create subjects, share a join QR, take attendance from photos or voice, "
                 "and track who is falling below the attendance target.")
        if st.button("Open teacher portal", type="primary", width="stretch", key="go_teacher"):
            _go("teacher")
    with student, st.container(border=True):
        st.subheader(":material/face: I'm a student")
        st.write("Sign in with your roll number and face, join classes with a code, "
                 "and see exactly how many classes you need to stay above target.")
        if st.button("Open student portal", type="primary", width="stretch", key="go_student"):
            _go("student")

    st.space("medium")
    c1, c2, c3, c4 = st.columns(4)
    for col, icon, title, text in (
        (c1, ":material/photo_camera:", "Photo attendance", "Several photos per class; each face is matched to one student."),
        (c2, ":material/mic:", "Voice roll-call", "Students say “present”; speakers are recognised from one recording."),
        (c3, ":material/verified_user:", "Liveness check", "Student login asks for a head turn, so a printed photo fails."),
        (c4, ":material/insights:", "Analytics", "Trends, defaulters, weekday patterns, Excel export."),
    ):
        with col:
            st.markdown(f"**{icon} {title}**")
            st.caption(text)
