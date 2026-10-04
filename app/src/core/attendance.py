"""Turn recognition results into an editable attendance draft and back.

The teacher can run several photos and a voice recording for the same class.
Every result is merged into one draft: a student is present if *any* source
recognised them, and we keep the strongest evidence for display. The teacher
reviews the draft (ticking or unticking students) before it is saved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from src.core.face import FaceMatch
from src.core.voice import SegmentMatch


@dataclass
class Hit:
    source: str  # "face" | "voice"
    confidence: float
    evidence: list[str] = field(default_factory=list)


def merge_hit(hits: dict[int, Hit], student_id: int, source: str, confidence: float, evidence: str) -> None:
    """Record that `student_id` was recognised; keep the best confidence."""
    h = hits.get(student_id)
    if h is None:
        hits[student_id] = Hit(source, confidence, [evidence])
        return
    h.evidence.append(evidence)
    if confidence > h.confidence:
        h.source, h.confidence = source, confidence


def add_face_results(hits: dict[int, Hit], matches: Sequence[FaceMatch], photo_label: str) -> list[FaceMatch]:
    """Merge one photo's matches; return the ambiguous ones for the teacher."""
    ambiguous = []
    for m in matches:
        if m.status == "matched" and m.student_id is not None:
            merge_hit(hits, m.student_id, "face", m.confidence, photo_label)
        elif m.status == "ambiguous":
            ambiguous.append(m)
    return ambiguous


def add_voice_results(hits: dict[int, Hit], best: Mapping[int, SegmentMatch]) -> None:
    for sid, m in best.items():
        merge_hit(hits, sid, "voice", m.similarity, f"voice {m.start_s:.1f}s")


def build_draft(roster: Iterable[Mapping], hits: Mapping[int, Hit]) -> pd.DataFrame:
    """One row per enrolled student, ready for st.data_editor."""
    rows = []
    for s in roster:
        h = hits.get(s["student_id"])
        rows.append({
            "student_id": s["student_id"],
            "roll_no": s["roll_no"],
            "name": s["name"],
            "present": h is not None,
            "source": h.source if h else "manual",
            "confidence": round(h.confidence, 2) if h else None,
            "evidence": ", ".join(h.evidence) if h else "",
        })
    return pd.DataFrame(rows, columns=["student_id", "roll_no", "name", "present",
                                       "source", "confidence", "evidence"])


def rows_from_draft(original: pd.DataFrame, edited: pd.DataFrame) -> list[dict]:
    """Attendance rows to save. A changed tick-box becomes a manual mark."""
    before = original.set_index("student_id")["present"].to_dict()
    out = []
    for r in edited.itertuples(index=False):
        changed = bool(r.present) != bool(before.get(r.student_id, False))
        source = "manual" if changed or pd.isna(r.confidence) else r.source
        out.append({
            "student_id": int(r.student_id),
            "status": "present" if r.present else "absent",
            "source": source,
            "confidence": None if source == "manual" or pd.isna(r.confidence) else float(r.confidence),
        })
    return out


def session_method(sources_used: set[str]) -> str:
    """'face', 'voice', 'manual' or 'mixed' for the sessions table."""
    sources_used = sources_used - {"manual"} or {"manual"}
    return sources_used.pop() if len(sources_used) == 1 else "mixed"
