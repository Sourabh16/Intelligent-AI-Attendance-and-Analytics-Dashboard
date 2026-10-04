"""Student: subjects with the 75% calculator, history, and privacy controls."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src import services
from src.core import analytics as an
from src.core import voice
from src.db import Repository
from src.screens.student.face_capture import capture_shots, find_duplicate
from src.ui import components as ui


def render(repo: Repository, student: dict) -> None:
    from src.screens.student.main import join_dialog  # avoid import cycle

    subjects = repo.student_subjects(student["student_id"])
    df = an.records_frame(repo.records(student_id=student["student_id"]))

    head, action = st.columns([3, 1], vertical_alignment="bottom")
    head.header("My attendance")
    if action.button("Join a subject", type="primary", width="stretch", icon=":material/add:"):
        join_dialog(repo, student)

    subj_tab, hist_tab, profile_tab = st.tabs(
        [":material/menu_book: Subjects", ":material/history: History", ":material/shield_person: Profile & privacy"])
    with subj_tab:
        _subjects(repo, student, subjects, df)
    with hist_tab:
        _history(df)
    with profile_tab:
        _profile(repo, student)


def _subjects(repo: Repository, student: dict, subjects: list[dict], df: pd.DataFrame) -> None:
    if not subjects:
        st.info("You haven't joined any subject. Scan your teacher's QR or enter the join code.",
                icon=":material/qr_code_2:")
        return
    cols = st.columns(2)
    for i, s in enumerate(subjects):
        sdf = df[df["subject_id"] == s["subject_id"]]
        attended, total = int(sdf["present"].sum()), int(sdf["session_id"].nunique())
        target = float(s["target_pct"])
        p = an.pct(attended, total)
        with cols[i % 2], st.container(border=True):
            st.subheader(s["name"])
            sec = ui.chip(f"Section {s['section']}") if s["section"] else ""
            st.html(f"{ui.chip(s['subject_code'])}{sec}{ui.chip(s['teacher_name'])}")
            if total == 0:
                st.caption("No classes recorded yet.")
            else:
                st.html(f"<b style='font-size:1.6rem'>{p:.0f}%</b> "
                        f"<span style='color:#64748B'>· {attended} of {total} classes · target {target:.0f}%</span>"
                        + ui.pct_bar(p, target))
                need = an.classes_needed(attended, total, target)
                if need > 0:
                    st.error(f"Attend the next **{need}** class(es) in a row to reach {target:.0f}%.",
                             icon=":material/trending_up:")
                elif need < 0:
                    st.error(f"{target:.0f}% can no longer be reached.", icon=":material/block:")
                else:
                    miss = an.classes_can_miss(attended, total, target)
                    st.success(f"On track. You can miss **{miss}** class(es) and stay above {target:.0f}%.",
                               icon=":material/check_circle:")
            with st.popover("Leave subject", icon=":material/logout:"):
                st.caption("Your past attendance stays with the teacher.")
                if st.button("Confirm leave", key=f"leave_{s['subject_id']}", type="primary"):
                    repo.unenroll(s["subject_id"], student["student_id"])
                    st.rerun()


def _history(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No attendance recorded yet.")
        return
    d = df.sort_values("started_at")
    d["cum_pct"] = d.groupby("subject_id")["present"].transform(lambda x: x.expanding().mean() * 100)
    st.markdown("**Running attendance % per subject**")
    st.altair_chart(alt.Chart(d).mark_line(point=True).encode(
        x=alt.X("started_at:T", title=None),
        y=alt.Y("cum_pct:Q", title="%", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("subject_name:N", title=None, legend=alt.Legend(orient="top")),
        tooltip=["subject_name", alt.Tooltip("started_at:T", format="%d %b %H:%M"), "status",
                 alt.Tooltip("cum_pct:Q", format=".0f")],
    ).properties(height=260), width="stretch")
    view = d.sort_values("started_at", ascending=False).assign(
        when=lambda x: x["started_at"].dt.strftime("%a %d %b %Y, %I:%M %p"))
    st.dataframe(view[["when", "subject_name", "status", "source"]], hide_index=True, width="stretch",
                 column_config={"when": "Class", "subject_name": "Subject", "status": "Status",
                                "source": "Marked by"})


def _profile(repo: Repository, student: dict) -> None:
    st.markdown("**What we store about you**")
    st.markdown(
        f"- Name and roll number: **{ui.esc(student['name'])}**, `{student['roll_no']}`\n"
        f"- Face templates: **{len(student['face_embeddings'])}** lists of 128 numbers "
        "(not photos; a template cannot be turned back into your picture)\n"
        f"- Voice template: **{'yes' if student.get('voice_embedding') else 'no'}** (256 numbers, not audio)\n"
        "- Your attendance marks in subjects you joined")

    with st.expander("Add or replace my voice profile", icon=":material/mic:"):
        clip = st.audio_input("Read a sentence aloud for ~5 seconds", key="prof_voice")
        if st.button("Save voice profile", disabled=clip is None):
            try:
                emb = voice.enrollment_embedding(services.voice_encoder(), clip.getvalue())
            except Exception:
                st.error("Not enough speech in that recording. Try again a bit louder and longer.")
            else:
                repo.update_student(student["student_id"], voice_embedding=emb)
                st.toast("Voice profile saved", icon=":material/check_circle:")
                st.rerun()
        if student.get("voice_embedding") and st.button("Remove my voice profile", type="tertiary"):
            repo.update_student(student["student_id"], voice_embedding=None)
            st.rerun()

    # Toggle rather than expander so the camera is only requested when wanted.
    if st.toggle("Retake my face photos", key="prof_face_on",
                 help="Useful if your look changed (glasses, beard) and photo attendance misses you."):
        shots = capture_shots("prof_shots")
        if shots is not None and st.button("Save new face profile", type="primary"):
            if find_duplicate(repo.all_face_embeddings(), shots, exclude=student["student_id"]) is not None:
                st.error("These photos match a different registered student.")
            else:
                repo.update_student(student["student_id"], face_embeddings=[e.tolist() for e in shots])
                st.session_state.pop("prof_shots", None)
                st.toast("Face profile updated", icon=":material/check_circle:")
                st.rerun()

    with st.expander("Delete my account and data", icon=":material/delete_forever:"):
        st.warning("Deletes your face and voice templates, your enrollments and every attendance "
                   "mark. This cannot be undone.")
        typed = st.text_input(f"Type your roll number **{student['roll_no']}** to confirm", key="del_confirm")
        if st.button("Delete everything", type="primary", disabled=typed.strip().upper() != student["roll_no"]):
            repo.delete_student(student["student_id"])
            for k in [k for k in st.session_state if k.startswith(("student", "s_", "reg_", "prof_", "del_"))]:
                del st.session_state[k]
            st.session_state["portal"] = None
            st.rerun()
