"""Teacher: create subjects, share join codes, manage rosters."""

from __future__ import annotations

import io

import segno
import streamlit as st

from src import config
from src.core import security
from src.db import DuplicateError, Repository
from src.screens.teacher.common import owned_subject
from src.ui import components as ui


def render(repo: Repository, teacher: dict) -> None:
    head, action = st.columns([3, 1], vertical_alignment="bottom")
    head.header("Subjects")
    if action.button("New subject", type="primary", width="stretch", icon=":material/add:"):
        _create_dialog(repo, teacher)

    subjects = repo.teacher_subjects(teacher["teacher_id"])
    if not subjects:
        st.info("No subjects yet. Create one, then share its join code with your class.",
                icon=":material/menu_book:")
        return
    for s in subjects:
        _subject_card(repo, teacher, s)


def _subject_card(repo: Repository, teacher: dict, s: dict) -> None:
    sid = s["subject_id"]
    with st.container(border=True):
        info, stats = st.columns([3, 2], vertical_alignment="center")
        with info:
            st.subheader(s["name"])
            joining = ui.chip("Joining open") if s["join_open"] else ui.chip("Joining paused", "warn")
            section = ui.chip(f"Section {s['section']}") if s["section"] else ""
            st.html(f"{ui.chip(s['subject_code'])}{section}{ui.chip(s['join_code'], 'mono')}{joining}")
        with stats:
            a, b, c = st.columns(3)
            a.metric("Students", s["n_students"])
            b.metric("Classes", s["n_sessions"])
            c.metric("Target", f"{s['target_pct']:.0f}%")

        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Share", key=f"share_{sid}", icon=":material/qr_code_2:", width="stretch"):
            _share_dialog(s)
        if b2.button("Roster", key=f"roster_{sid}", icon=":material/groups:", width="stretch"):
            _roster_dialog(repo, teacher, sid)
        if b3.button("Settings", key=f"settings_{sid}", icon=":material/tune:", width="stretch"):
            _settings_dialog(repo, teacher, sid)
        if b4.button("Delete", key=f"delete_{sid}", icon=":material/delete:", width="stretch"):
            _delete_dialog(repo, teacher, sid)


def join_link(join_code: str) -> str:
    return f"{config.app_url()}/?join={join_code}"


def qr_png(text: str) -> bytes:
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=10, border=2, dark="#0F172A")
    return buf.getvalue()


@st.dialog("New subject")
def _create_dialog(repo: Repository, teacher: dict) -> None:
    with st.form("new_subject", border=False):
        code = st.text_input("Subject code", placeholder="CS101")
        name = st.text_input("Subject name", placeholder="Introduction to Programming")
        section = st.text_input("Section (optional)", placeholder="A")
        target = st.number_input("Attendance target (%)", 0.0, 100.0, config.DEFAULT_TARGET_PCT, step=5.0)
        ok = st.form_submit_button("Create subject", type="primary", width="stretch")
    if not ok:
        return
    code, name, section = code.strip().upper(), name.strip(), section.strip().upper()
    if not code or not name:
        st.error("Subject code and name are required.")
        return
    existing = repo.teacher_subjects(teacher["teacher_id"])
    if any(e["subject_code"] == code and e["section"] == section for e in existing):
        st.error(f"You already have {code} section {section or '-'}.")
        return
    for _ in range(5):  # a join-code collision is very unlikely; retry anyway
        try:
            repo.create_subject(teacher["teacher_id"], code, name, section, float(target),
                                security.new_join_code())
            break
        except DuplicateError:
            continue
    else:
        st.error("Could not generate a unique join code. Try again.")
        return
    st.toast(f"Created {name}", icon=":material/check_circle:")
    st.rerun()


@st.dialog("Share with your class", width="large")
def _share_dialog(s: dict) -> None:
    link = join_link(s["join_code"])
    left, right = st.columns([1, 1], vertical_alignment="center")
    with left:
        st.markdown(f"**{ui.esc(s['name'])}**")
        st.caption("Students scan the QR or open the link, sign in, and confirm.")
        st.code(link, language=None)
        st.caption("Or enter this code in the student portal:")
        st.code(s["join_code"], language=None)
        if not s["join_open"]:
            st.warning("Joining is paused for this subject. Open it in Settings.")
    with right:
        png = qr_png(link)
        st.image(png, width="stretch")
        st.download_button("Download QR", png, file_name=f"{s['subject_code']}-join-qr.png",
                           mime="image/png", width="stretch", icon=":material/download:")


@st.dialog("Roster", width="large")
def _roster_dialog(repo: Repository, teacher: dict, subject_id: int) -> None:
    s = owned_subject(repo, teacher, subject_id)
    if s is None:
        st.error("Subject not found.")
        return
    roster = repo.roster(subject_id)
    st.markdown(f"**{ui.esc(s['name'])}**: {len(roster)} students")
    if not roster:
        st.info("Nobody has joined yet. Share the join code.")
        return
    for r in roster:
        c1, c2, c3, c4 = st.columns([2, 4, 2, 1], vertical_alignment="center")
        c1.markdown(f"`{r['roll_no']}`")
        c2.write(r["name"])
        voice = ":material/mic: voice" if r.get("voice_embedding") else ":material/mic_off: no voice"
        c3.caption(f"{len(r['face_embeddings'])} face samples · {voice}")
        if c4.button("", key=f"rm_{subject_id}_{r['student_id']}", icon=":material/person_remove:",
                     help="Remove from this subject"):
            repo.unenroll(subject_id, r["student_id"])
            st.rerun()


@st.dialog("Subject settings")
def _settings_dialog(repo: Repository, teacher: dict, subject_id: int) -> None:
    s = owned_subject(repo, teacher, subject_id)
    if s is None:
        st.error("Subject not found.")
        return
    with st.form("subject_settings", border=False):
        name = st.text_input("Name", s["name"])
        target = st.number_input("Attendance target (%)", 0.0, 100.0, float(s["target_pct"]), step=5.0)
        join_open = st.toggle("Allow new students to join", s["join_open"])
        regen = st.checkbox("Generate a new join code (the old link and QR stop working)")
        ok = st.form_submit_button("Save", type="primary", width="stretch")
    if not ok:
        return
    fields = {"name": name.strip() or s["name"], "target_pct": float(target), "join_open": join_open}
    if regen:
        fields["join_code"] = security.new_join_code()
    try:
        repo.update_subject(subject_id, **fields)
    except DuplicateError:
        st.error("Join code collision. Save again.")
        return
    st.rerun()


@st.dialog("Delete subject")
def _delete_dialog(repo: Repository, teacher: dict, subject_id: int) -> None:
    s = owned_subject(repo, teacher, subject_id)
    if s is None:
        st.error("Subject not found.")
        return
    st.warning(f"This permanently deletes **{ui.esc(s['name'])}**, its roster and all of its "
               "attendance records.", icon=":material/warning:")
    typed = st.text_input(f"Type the subject code **{s['subject_code']}** to confirm")
    if st.button("Delete permanently", type="primary", disabled=typed.strip().upper() != s["subject_code"],
                 width="stretch"):
        repo.delete_subject(subject_id)
        st.rerun()
