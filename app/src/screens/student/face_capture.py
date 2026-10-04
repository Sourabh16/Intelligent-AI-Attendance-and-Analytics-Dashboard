"""Reusable multi-shot face capture used by registration and re-enrollment."""

from __future__ import annotations

import streamlit as st

from src import config, services
from src.core import face

SHOT_PROMPTS = [
    "Look straight at the camera",
    "Turn your head slightly to one side",
    "Turn your head slightly to the other side",
]


def capture_shots(state_key: str) -> list | None:
    """Walk the student through FACE_ENROLL_SHOTS photos.

    Returns the list of embeddings once every shot is accepted and they are
    consistent (same person), otherwise None while capture is in progress.
    """
    shots: list = st.session_state.setdefault(state_key, [])
    n = config.FACE_ENROLL_SHOTS
    st.progress(len(shots) / n, f"Face photos: {len(shots)} of {n}")

    if len(shots) < n:
        prompt = SHOT_PROMPTS[len(shots)]
        st.markdown(f"**Photo {len(shots) + 1}: {prompt}.**")
        pic = st.camera_input(prompt, key=f"{state_key}_cam_{len(shots)}", label_visibility="collapsed")
        if pic is not None:
            with st.spinner("Checking photo..."):
                res = services.analyse_selfie(pic.getvalue(), jitters=2)
            if not res.ok:
                st.error(res.message + " Clear the photo and retake it.")
            else:
                shots.append(res.embedding)
                st.rerun()
        return None

    spread = face.max_pairwise_distance(shots)
    if spread > config.FACE_ENROLL_CONSISTENCY:
        st.error("The photos don't look like the same person. Please retake them.")
        if st.button("Retake photos", key=f"{state_key}_retake"):
            st.session_state[state_key] = []
            st.rerun()
        return None
    st.success("Face photos captured.", icon=":material/check_circle:")
    if st.button("Retake photos", key=f"{state_key}_retake_ok", type="tertiary"):
        st.session_state[state_key] = []
        st.rerun()
    return shots


def find_duplicate(all_embeddings: dict[int, list], new_shots: list, exclude: int | None = None) -> int | None:
    """student_id of an existing student with the same face, if any."""
    for sid, samples in all_embeddings.items():
        if sid == exclude or not samples:
            continue
        for emb in new_shots:
            ok, _ = face.verify_face(emb, samples, config.FACE_DUPLICATE_THRESHOLD)
            if ok:
                return sid
    return None
