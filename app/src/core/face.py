"""Face detection, embedding, matching and drawing.

The pipeline for one image:

    bytes --load_image--> RGB array --detect_faces--> [DetectedFace]
          --match_faces(embeddings, gallery)--> [FaceMatch]

Matching is *closed-set*: the gallery only contains students enrolled in the
subject being marked, so a face can never be matched to someone from another
class. Each student may have several enrollment embeddings; the distance to a
student is the distance to their closest embedding.

Faces are assigned to students one-to-one, most confident pair first, so two
faces in the same photo can never both claim the same student.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from src import config

Embedding = np.ndarray  # shape (128,)
Gallery = Mapping[int, Sequence[Sequence[float]]]  # student_id -> embeddings
MatchStatus = Literal["matched", "ambiguous", "unknown"]

# dlib 68-point landmark indices used for head pose.
_JAW_LEFT, _JAW_RIGHT, _NOSE_TIP = 0, 16, 30


@dataclass(frozen=True)
class DetectedFace:
    box: tuple[int, int, int, int]  # left, top, right, bottom
    embedding: Embedding
    landmarks: np.ndarray  # (68, 2)


@dataclass(frozen=True)
class FaceMatch:
    face_index: int
    student_id: int | None  # best candidate (None when nobody is close)
    distance: float  # distance to that candidate (inf when gallery empty)
    status: MatchStatus

    @property
    def confidence(self) -> float:
        """0..1 score for display: 1 at distance 0, 0 at the threshold."""
        if not np.isfinite(self.distance):
            return 0.0
        return float(max(0.0, 1.0 - self.distance / config.FACE_MATCH_THRESHOLD))


# ---- Models (dlib) ----------------------------------------------------------


class FaceModels:
    """dlib detector + 68-point landmark predictor + ResNet face encoder."""

    def __init__(self) -> None:
        import dlib
        import face_recognition_models as frm

        self.detector = dlib.get_frontal_face_detector()
        self.predictor = dlib.shape_predictor(frm.pose_predictor_model_location())
        self.encoder = dlib.face_recognition_model_v1(frm.face_recognition_model_location())


# ---- Image loading ----------------------------------------------------------


def load_image(data: bytes, max_side: int = config.MAX_IMAGE_SIDE) -> np.ndarray:
    """Decode an uploaded image into an RGB uint8 array.

    Applies the EXIF rotation (phone photos are often stored sideways) and
    downscales very large photos so detection stays fast.
    """
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    return np.ascontiguousarray(np.asarray(img, dtype=np.uint8))


# ---- Detection + embedding --------------------------------------------------


def detect_faces(
    image: np.ndarray, models: FaceModels, upsample: int = 1, jitters: int = 1
) -> list[DetectedFace]:
    """Find every face and compute its 128-d embedding and landmarks.

    `jitters` > 1 re-samples the face with small distortions and averages the
    embeddings: slower, slightly more robust. Used for enrollment selfies.
    """
    faces = []
    for rect in models.detector(image, upsample):
        shape = models.predictor(image, rect)
        emb = np.asarray(models.encoder.compute_face_descriptor(image, shape, jitters))
        pts = np.array([(p.x, p.y) for p in shape.parts()], dtype=float)
        box = (max(rect.left(), 0), max(rect.top(), 0), rect.right(), rect.bottom())
        faces.append(DetectedFace(box=box, embedding=emb, landmarks=pts))
    return faces


# ---- Matching (pure numpy, unit-tested) -------------------------------------


def distance_matrix(
    embeddings: Sequence[Embedding], gallery: Gallery
) -> tuple[np.ndarray, list[int]]:
    """Euclidean distance from each face to each student's *closest* sample.

    Returns (D, student_ids) where D has shape (n_faces, n_students).
    """
    student_ids = [sid for sid, samples in gallery.items() if len(samples) > 0]
    n_faces = len(embeddings)
    if n_faces == 0 or not student_ids:
        return np.zeros((n_faces, len(student_ids))), student_ids
    faces = np.asarray(embeddings, dtype=float)  # (F, 128)
    D = np.empty((n_faces, len(student_ids)))
    for j, sid in enumerate(student_ids):
        samples = np.asarray(gallery[sid], dtype=float)  # (k, 128)
        dists = np.linalg.norm(faces[:, None, :] - samples[None, :, :], axis=2)
        D[:, j] = dists.min(axis=1)
    return D, student_ids


def assign_greedy(D: np.ndarray, threshold: float) -> dict[int, int]:
    """One-to-one face -> student assignment, most confident pair first.

    Repeatedly takes the smallest remaining distance whose face and student
    are both still free. Unlike the Hungarian algorithm (which minimises the
    *total* distance) this never gives a near-certain face to the wrong
    student just to make the sum smaller.
    """
    pairs = sorted((D[i, j], i, j) for i in range(D.shape[0]) for j in range(D.shape[1]) if D[i, j] <= threshold)
    used_faces: set[int] = set()
    used_students: set[int] = set()
    assigned: dict[int, int] = {}
    for _, i, j in pairs:
        if i not in used_faces and j not in used_students:
            assigned[i] = j
            used_faces.add(i)
            used_students.add(j)
    return assigned


def match_faces(
    embeddings: Sequence[Embedding],
    gallery: Gallery,
    threshold: float = config.FACE_MATCH_THRESHOLD,
    margin: float = config.FACE_AMBIGUITY_MARGIN,
) -> list[FaceMatch]:
    """Assign faces to students one-to-one.

    * Pairs further apart than `threshold` are never assigned.
    * A face whose runner-up student is within `margin` of its best is marked
      "ambiguous": shown to the teacher but not auto-marked present.
    """
    D, sids = distance_matrix(embeddings, gallery)
    n_faces = len(embeddings)
    if not sids:
        return [FaceMatch(i, None, float("inf"), "unknown") for i in range(n_faces)]

    assigned = assign_greedy(D, threshold)
    results = []
    for i in range(n_faces):
        if i not in assigned:
            j = int(D[i].argmin())
            results.append(FaceMatch(i, None, float(D[i, j]), "unknown"))
            continue
        j = assigned[i]
        d = float(D[i, j])
        others = np.delete(D[i], j)
        ambiguous = others.size > 0 and float(others.min()) - d < margin
        results.append(FaceMatch(i, sids[j], d, "ambiguous" if ambiguous else "matched"))
    return results


def verify_face(
    embedding: Embedding,
    samples: Sequence[Sequence[float]],
    threshold: float = config.FACE_MATCH_THRESHOLD,
) -> tuple[bool, float]:
    """1:1 check: is this face the owner of `samples`? Used for student login."""
    if not samples:
        return False, float("inf")
    d = float(np.linalg.norm(np.asarray(samples) - embedding, axis=1).min())
    return d <= threshold, d


def max_pairwise_distance(embeddings: Sequence[Embedding]) -> float:
    """Largest distance between any two embeddings (0 for fewer than two)."""
    E = np.asarray(embeddings, dtype=float)
    if len(E) < 2:
        return 0.0
    return float(np.linalg.norm(E[:, None] - E[None, :], axis=2).max())


def head_turn_offset(landmarks: np.ndarray) -> float:
    """Signed horizontal head-turn estimate from landmarks.

    The nose tip's position across the jaw width: 0 when looking straight at
    the camera, about +-0.2 or more when the head is clearly turned. The sign
    is not used because browser cameras may or may not mirror the image.
    """
    left = landmarks[_JAW_LEFT, 0]
    right = landmarks[_JAW_RIGHT, 0]
    width = right - left
    if width <= 0:
        return 0.0
    return float((landmarks[_NOSE_TIP, 0] - left) / width - 0.5)


# ---- Drawing ----------------------------------------------------------------

_COLOURS = {"matched": (22, 163, 74), "ambiguous": (217, 119, 6), "unknown": (220, 38, 38)}


def annotate(
    image: np.ndarray,
    faces: Sequence[DetectedFace],
    matches: Sequence[FaceMatch],
    names: Mapping[int, str],
) -> Image.Image:
    """Draw a coloured box and label on every detected face."""
    img = Image.fromarray(image)
    draw = ImageDraw.Draw(img)
    line = max(2, img.width // 400)
    try:
        font = ImageFont.load_default(size=max(14, img.width // 60))
    except TypeError:  # very old Pillow
        font = ImageFont.load_default()
    for face, m in zip(faces, matches, strict=False):
        colour = _COLOURS[m.status]
        draw.rectangle(face.box, outline=colour, width=line)
        if m.status == "unknown" or m.student_id is None:
            label = "Unknown"
        else:
            label = names.get(m.student_id, str(m.student_id))
            if m.status == "ambiguous":
                label += " ?"
        x, y = face.box[0], face.box[1]
        tb = draw.textbbox((x, y), label, font=font)
        h = tb[3] - tb[1] + 6
        draw.rectangle((x, y - h, x + (tb[2] - tb[0]) + 8, y), fill=colour)
        draw.text((x + 4, y - h + 2), label, fill="white", font=font)
    return img
