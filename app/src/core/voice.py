"""Speaker recognition for roll-call attendance.

The teacher records the class while each student says "present". The
recording is cut at the silences, each spoken segment is turned into a 256-d
Resemblyzer voice embedding, and every segment is compared with the voice
profiles of students enrolled in the subject (closed-set, like faces).

Embeddings from Resemblyzer are L2-normalised, so the dot product is the
cosine similarity: 1.0 means identical, unrelated voices sit around 0.5-0.7.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from src import config


@dataclass(frozen=True)
class SegmentMatch:
    start_s: float
    end_s: float
    student_id: int | None
    similarity: float
    ambiguous: bool


def load_encoder():
    from resemblyzer import VoiceEncoder

    return VoiceEncoder(device="cpu", verbose=False)


def load_audio(data: bytes, sr: int = config.VOICE_SAMPLE_RATE) -> np.ndarray:
    """Decode WAV/MP3/M4A bytes to mono float32 at `sr` Hz."""
    import librosa

    audio, _ = librosa.load(io.BytesIO(data), sr=sr, mono=True)
    return audio.astype(np.float32)


def split_segments(
    audio: np.ndarray,
    sr: int = config.VOICE_SAMPLE_RATE,
    top_db: float = config.VOICE_SILENCE_TOP_DB,
    min_seconds: float = config.VOICE_MIN_SEGMENT_SECONDS,
) -> list[tuple[int, int]]:
    """Sample ranges of the non-silent parts, dropping very short blips."""
    import librosa

    if audio.size == 0:
        return []
    intervals = librosa.effects.split(audio, top_db=top_db)
    return [(int(s), int(e)) for s, e in intervals if (e - s) >= min_seconds * sr]


def embed(encoder, audio: np.ndarray, sr: int = config.VOICE_SAMPLE_RATE) -> np.ndarray:
    from resemblyzer import preprocess_wav

    wav = preprocess_wav(audio, source_sr=sr)
    if wav.size < sr * 0.3:  # preprocess trims silence; too little speech left
        raise ValueError("Not enough speech in the recording.")
    return encoder.embed_utterance(wav)


def enrollment_embedding(encoder, data: bytes) -> list[float]:
    """Voice profile from one enrollment clip (a sentence of 3-10 seconds)."""
    return embed(encoder, load_audio(data)).tolist()


# ---- Matching (pure numpy, unit-tested) -------------------------------------


def match_embedding(
    embedding: np.ndarray,
    profiles: Mapping[int, Sequence[float]],
    threshold: float = config.VOICE_MATCH_THRESHOLD,
    margin: float = config.VOICE_AMBIGUITY_MARGIN,
) -> tuple[int | None, float, bool]:
    """Best student for one voice segment.

    Returns (student_id or None, similarity, ambiguous). Below `threshold`
    nobody is returned; within `margin` of the runner-up the match is
    flagged ambiguous.
    """
    ids = [sid for sid, p in profiles.items() if p is not None and len(p) > 0]
    if not ids:
        return None, 0.0, False
    P = np.asarray([profiles[s] for s in ids], dtype=float)
    sims = P @ np.asarray(embedding, dtype=float)
    order = np.argsort(sims)[::-1]
    best = float(sims[order[0]])
    if best < threshold:
        return None, best, False
    ambiguous = len(order) > 1 and best - float(sims[order[1]]) < margin
    return ids[int(order[0])], best, ambiguous


def best_per_student(matches: Sequence[SegmentMatch]) -> dict[int, SegmentMatch]:
    """Keep each student's strongest unambiguous segment.

    A student who speaks twice (or coughs) only needs to be recognised once.
    """
    best: dict[int, SegmentMatch] = {}
    for m in matches:
        if m.student_id is None or m.ambiguous:
            continue
        if m.student_id not in best or m.similarity > best[m.student_id].similarity:
            best[m.student_id] = m
    return best


def analyse_roll_call(
    encoder,
    data: bytes,
    profiles: Mapping[int, Sequence[float]],
    threshold: float = config.VOICE_MATCH_THRESHOLD,
    margin: float = config.VOICE_AMBIGUITY_MARGIN,
) -> list[SegmentMatch]:
    """Split a classroom recording and match every spoken segment."""
    sr = config.VOICE_SAMPLE_RATE
    audio = load_audio(data, sr)
    out = []
    for s, e in split_segments(audio, sr):
        try:
            emb = embed(encoder, audio[s:e], sr)
        except ValueError:
            continue
        sid, sim, amb = match_embedding(emb, profiles, threshold, margin)
        out.append(SegmentMatch(s / sr, e / sr, sid, sim, amb))
    return out
