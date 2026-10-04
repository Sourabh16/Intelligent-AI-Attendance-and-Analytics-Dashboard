"""Teacher: take attendance from photos, a voice roll-call, or by hand.

All sources feed one *draft* held in session state. Nothing is written to the
database until the teacher reviews the table and presses Save. Photos and audio
are processed in memory and never stored.
"""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from src import config, services
from src.core import attendance as att
from src.core import voice
from src.db import Repository
from src.screens.teacher.common import subject_label


def _new_draft(subject_id: int) -> dict:
    v = st.session_state.get("draft", {}).get("version", 0) + 1
    return {"subject_id": subject_id, "hits": {}, "photos": [], "segments": [],
            "ambiguous": [], "sources": set(), "bulk": None, "camera": [], "version": v}


def render(repo: Repository, teacher: dict) -> None:
    st.header("Take attendance")
    subjects = repo.teacher_subjects(teacher["teacher_id"])
    if not subjects:
        st.info("Create a subject first (Subjects tab).", icon=":material/menu_book:")
        return

    by_id = {s["subject_id"]: s for s in subjects}
    subject_id = st.selectbox("Subject", list(by_id), format_func=lambda i: subject_label(by_id[i]))
    draft = st.session_state.get("draft")
    if draft is None or draft["subject_id"] != subject_id:
        draft = st.session_state["draft"] = _new_draft(subject_id)

    roster = repo.roster(subject_id)
    if not roster:
        st.info("No students have joined this subject yet. Share its join code from the Subjects tab.",
                icon=":material/group_add:")
        return
    names = {s["student_id"]: s["name"] for s in roster}

    with st.expander("Recognition strictness", icon=":material/tune:"):
        st.caption("Stricter means fewer false 'present' marks but more students to tick by hand.")
        f_thr = st.slider("Face match distance (lower = stricter)", 0.35, 0.65,
                          config.FACE_MATCH_THRESHOLD, 0.01)
        v_thr = st.slider("Voice similarity (higher = stricter)", 0.55, 0.90,
                          config.VOICE_MATCH_THRESHOLD, 0.01)

    photo_tab, voice_tab = st.tabs([":material/photo_camera: Photos", ":material/mic: Voice roll-call"])
    with photo_tab:
        _photo_input(draft, roster, names, f_thr)
    with voice_tab:
        _voice_input(draft, roster, v_thr)

    st.divider()
    _review_and_save(repo, draft, roster, subject_id)


# ---- Photos -----------------------------------------------------------------


def _photo_input(draft: dict, roster: list[dict], names: dict, threshold: float) -> None:
    with_faces = sum(1 for s in roster if s["face_embeddings"])
    st.caption(f"{with_faces}/{len(roster)} enrolled students have a face profile. "
               "Take 2-3 photos from different corners so every face is visible and not too small.")
    files = st.file_uploader("Classroom photos", type=["jpg", "jpeg", "png", "webp"],
                             accept_multiple_files=True, key=f"photos_{draft['version']}")
    # A toggle, not an expander: Streamlit renders collapsed expanders, so the
    # browser would ask for camera permission every time the page opens.
    if st.toggle("Use the camera instead", key=f"cam_on_{draft['version']}"):
        shot = st.camera_input("Snapshot", key=f"cam_{draft['version']}", label_visibility="collapsed")
        if shot is not None:
            digest = hashlib.sha1(shot.getvalue()).hexdigest()
            if digest not in {d for d, _ in draft["camera"]}:
                draft["camera"].append((digest, shot.getvalue()))
        if draft["camera"]:
            st.caption(f"{len(draft['camera'])} camera snapshot(s) waiting to be analysed.")

    pending = [(f.name, f.getvalue()) for f in files or []]
    pending += [(f"Camera {i + 1}", data) for i, (_, data) in enumerate(draft["camera"])]
    if st.button(f"Analyse {len(pending)} photo(s)", type="primary", disabled=not pending,
                 icon=":material/center_focus_strong:"):
        done = len(draft["photos"])
        bar = st.progress(0.0, "Detecting faces...")
        for i, (label, data) in enumerate(pending):
            try:
                res = services.analyse_class_photo(data, f"Photo {done + i + 1}", roster,
                                                   threshold, config.FACE_AMBIGUITY_MARGIN)
            except Exception:  # unreadable/corrupt image
                st.error(f"Could not read {label}.")
                continue
            draft["photos"].append(res)
            draft["ambiguous"] += att.add_face_results(draft["hits"], res.matches, res.label)
            draft["sources"].add("face")
            bar.progress((i + 1) / len(pending), f"Analysed {label}")
        draft["camera"] = []
        draft["version"] += 1  # clears the uploader and camera
        st.rerun()

    for res in draft["photos"]:
        st.image(res.annotated, width="stretch",
                 caption=(f"{res.label}: {res.n_faces} faces · {res.count('matched')} recognised · "
                          f"{res.count('ambiguous')} need review · {res.count('unknown')} unknown"))
    if draft["ambiguous"]:
        maybe = sorted({names.get(m.student_id, "?") for m in draft["ambiguous"]})
        st.warning("Some faces were too close to call and were **not** marked automatically. "
                   f"Possible: {', '.join(maybe)}. Check them in the table below.", icon=":material/help:")


# ---- Voice ------------------------------------------------------------------


def _voice_input(draft: dict, roster: list[dict], threshold: float) -> None:
    profiles = {s["student_id"]: s["voice_embedding"] for s in roster if s.get("voice_embedding")}
    st.caption(f"{len(profiles)}/{len(roster)} enrolled students have a voice profile. "
               "Record the class while students say “present” one after another, with a short pause between.")
    if not profiles:
        st.info("No student in this subject has enrolled their voice yet.")
        return
    rec = st.audio_input("Record roll-call", key=f"rec_{draft['version']}")
    up = st.file_uploader("…or upload a recording", type=["wav", "mp3", "m4a", "ogg", "webm"],
                          key=f"audio_{draft['version']}")
    source = rec or up
    if st.button("Analyse recording", type="primary", disabled=source is None, icon=":material/graphic_eq:"):
        with st.spinner("Separating and recognising voices..."):
            try:
                segments = voice.analyse_roll_call(services.voice_encoder(), source.getvalue(), profiles,
                                                   threshold, config.VOICE_AMBIGUITY_MARGIN)
            except Exception:
                st.error("Could not read that recording. Try WAV or MP3.")
                return
        draft["segments"] = segments
        att.add_voice_results(draft["hits"], voice.best_per_student(segments))
        draft["sources"].add("voice")
        draft["version"] += 1
        st.rerun()

    if draft["segments"]:
        names = {s["student_id"]: s["name"] for s in roster}
        st.dataframe(pd.DataFrame([{
            "From (s)": round(m.start_s, 1), "To (s)": round(m.end_s, 1),
            "Speaker": names.get(m.student_id, "Unrecognised") if m.student_id else "Unrecognised",
            "Similarity": round(m.similarity, 2),
            "Note": "too close to call" if m.ambiguous else "",
        } for m in draft["segments"]]), hide_index=True, width="stretch")


# ---- Review & save ----------------------------------------------------------


def _review_and_save(repo: Repository, draft: dict, roster: list[dict], subject_id: int) -> None:
    st.subheader("Review and save")
    original = att.build_draft(roster, draft["hits"])
    start = original.copy()
    if draft["bulk"] is not None:
        start["present"] = draft["bulk"]

    b1, b2, b3 = st.columns(3)
    if b1.button("Mark everyone present", width="stretch", icon=":material/done_all:"):
        draft["bulk"], draft["version"] = True, draft["version"] + 1
        st.rerun()
    if b2.button("Mark everyone absent", width="stretch", icon=":material/remove_done:"):
        draft["bulk"], draft["version"] = False, draft["version"] + 1
        st.rerun()
    if b3.button("Start over", width="stretch", icon=":material/restart_alt:"):
        st.session_state["draft"] = _new_draft(subject_id)
        st.rerun()

    edited = st.data_editor(
        start, key=f"editor_{draft['version']}", hide_index=True, width="stretch",
        disabled=["student_id", "roll_no", "name", "source", "confidence", "evidence"],
        column_order=["present", "roll_no", "name", "source", "confidence", "evidence"],
        column_config={
            "present": st.column_config.CheckboxColumn("Present", width="small"),
            "roll_no": "Roll no",
            "name": "Name",
            "source": "Recognised by",
            "confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.2f"),
            "evidence": "Seen in",
        },
    )
    n_present = int(edited["present"].sum())
    st.metric("Present", f"{n_present} / {len(edited)}", f"{100 * n_present / len(edited):.0f}%",
              delta_color="off")

    if st.button("Save attendance", type="primary", icon=":material/save:", width="stretch"):
        rows = att.rows_from_draft(original, edited)
        sources = set(draft["sources"]) | {r["source"] for r in rows if r["status"] == "present"}
        try:
            repo.record_session(subject_id, att.session_method(sources), rows)
        except Exception as e:
            st.error(f"Saving failed, nothing was written. ({e})")
            return
        st.session_state["draft"] = _new_draft(subject_id)
        st.toast(f"Saved: {n_present}/{len(rows)} present", icon=":material/check_circle:")
        st.rerun()
