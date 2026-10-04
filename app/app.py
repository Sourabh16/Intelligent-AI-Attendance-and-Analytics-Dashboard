"""AttendSense: AI attendance with face and voice recognition.

Run locally:  streamlit run app/app.py

Routing is a tiny state machine in st.session_state:
    portal = None       -> home screen (choose Teacher / Student)
    portal = "teacher"  -> teacher login, then teacher dashboard
    portal = "student"  -> student face login, then student dashboard

A join link (?join=CODE) sends the visitor to the student portal and offers
enrollment right after they sign in.
"""

import streamlit as st

from src import config
from src.core.security import normalise_join_code
from src.db import get_repo
from src.screens import home
from src.screens.student import main as student_main
from src.screens.teacher import main as teacher_main
from src.ui import components as ui

st.set_page_config(
    page_title=f"{config.APP_NAME} · AI Attendance",
    page_icon=":material/how_to_reg:",
    layout="wide",
)
ui.apply_theme()

repo = get_repo()
st.session_state["_backend_name"] = repo.backend_name

join = st.query_params.get("join")
if join:
    st.session_state["pending_join"] = normalise_join_code(join)
    st.session_state["portal"] = "student"
    del st.query_params["join"]

match st.session_state.get("portal"):
    case "teacher":
        teacher_main.render(repo)
    case "student":
        student_main.render(repo)
    case _:
        home.render(repo)

ui.footer()
