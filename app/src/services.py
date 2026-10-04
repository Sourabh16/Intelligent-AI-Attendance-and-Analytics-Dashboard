"""Streamlit-side wiring: cached ML models and the recognition workflows.

Models are loaded once per server process (st.cache_resource) because dlib's
models are ~100 MB and Resemblyzer loads a PyTorch network.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import streamlit as st
from PIL import Image

from src import config
from src.core import face, voice


@st.cache_resource(show_spinner="Loading face models...")
def face_models() -> face.FaceModels:
    return face.FaceModels()


@st.cache_resource(show_spinner="Loading voice model...")
def voice_encoder():
    return voice.load_encoder()


@dataclass
class PhotoResult:
    label: str
    annotated: Image.Image
    matches: list[face.FaceMatch]

    @property
    def n_faces(self) -> int:
        return len(self.matches)

    def count(self, status: str) -> int:
        return sum(m.status == status for m in self.matches)


def analyse_class_photo(
    data: bytes, label: str, roster: list[dict], threshold: float, margin: float
) -> PhotoResult:
    image = face.load_image(data)
    faces = face.detect_faces(image, face_models(), upsample=config.FACE_UPSAMPLE_CLASSROOM)
    gallery = {s["student_id"]: s["face_embeddings"] for s in roster}
    names = {s["student_id"]: s["name"] for s in roster}
    matches = face.match_faces([f.embedding for f in faces], gallery, threshold, margin)
    return PhotoResult(label, face.annotate(image, faces, matches, names), matches)


@dataclass
class SelfieResult:
    ok: bool
    message: str
    embedding: np.ndarray | None = None
    turn: float = 0.0


def analyse_selfie(data: bytes, jitters: int = 1) -> SelfieResult:
    """Exactly one face, with its embedding and head-turn estimate."""
    image = face.load_image(data, max_side=1280)
    faces = face.detect_faces(image, face_models(), upsample=config.FACE_UPSAMPLE_SELFIE, jitters=jitters)
    if not faces:
        return SelfieResult(False, "No face found. Face the camera in good light.")
    if len(faces) > 1:
        return SelfieResult(False, "More than one face in the frame. Only you should be visible.")
    f = faces[0]
    return SelfieResult(True, "", f.embedding, face.head_turn_offset(f.landmarks))
