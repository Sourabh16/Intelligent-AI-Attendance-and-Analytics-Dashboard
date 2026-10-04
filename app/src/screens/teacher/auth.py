"""Teacher sign-in and registration (username + bcrypt-hashed password)."""

from __future__ import annotations

import streamlit as st

from src.core import security
from src.db import DuplicateError, Repository


def _sign_in(teacher: dict) -> None:
    st.session_state["teacher"] = {k: teacher[k] for k in ("teacher_id", "username", "name")}
    st.rerun()


def render(repo: Repository) -> None:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        login_tab, register_tab = st.tabs(["Sign in", "Create account"])
        with login_tab:
            _login(repo)
        with register_tab:
            _register(repo)


def _login(repo: Repository) -> None:
    throttle = security.LoginThrottle(st.session_state, "teacher")
    with st.form("teacher_login"):
        username = st.text_input("Username", placeholder="ananya.roy")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch",
                                          icon=":material/login:")
    if not submitted:
        return
    if wait := throttle.locked_for():
        st.error(f"Too many failed attempts. Try again in {wait} s.")
        return
    teacher = repo.get_teacher_by_username(security.normalise_username(username))
    # Same message for unknown user and wrong password: don't reveal which.
    if teacher and security.check_password(password, teacher["password_hash"]):
        throttle.succeed()
        _sign_in(teacher)
    else:
        throttle.fail()
        st.error("Incorrect username or password.")


def _register(repo: Repository) -> None:
    with st.form("teacher_register"):
        name = st.text_input("Full name", placeholder="Ananya Roy")
        username = st.text_input("Username", placeholder="ananya.roy",
                                 help="3-30 characters: lowercase letters, digits, '_' or '.'")
        password = st.text_input("Password", type="password",
                                 help="At least 8 characters with a letter and a digit.")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account", type="primary", width="stretch",
                                          icon=":material/person_add:")
    if not submitted:
        return
    username = security.normalise_username(username)
    problem = (
        ("Please enter your name." if not name.strip() else None)
        or security.username_problem(username)
        or security.password_problem(password)
        or ("Passwords do not match." if password != confirm else None)
    )
    if problem:
        st.error(problem)
        return
    try:
        teacher = repo.create_teacher(username, name.strip(), security.hash_password(password))
    except DuplicateError:
        st.error("That username is taken.")
        return
    st.toast(f"Welcome, {teacher['name']}!", icon=":material/celebration:")
    _sign_in(teacher)
