import numpy as np
from tests.conftest import unit

from src.core import voice


def test_match_embedding_threshold_and_margin(rng):
    a, b = unit(rng.normal(size=256)), unit(rng.normal(size=256))
    profiles = {1: a.tolist(), 2: b.tolist()}
    sid, sim, amb = voice.match_embedding(unit(a + 0.02 * rng.normal(size=256)), profiles, threshold=0.7)
    assert sid == 1 and sim > 0.9 and not amb
    sid, _, _ = voice.match_embedding(unit(rng.normal(size=256)), profiles, threshold=0.7)
    assert sid is None


def test_match_embedding_ambiguous(rng):
    a = unit(rng.normal(size=256))
    profiles = {1: a.tolist(), 2: a.tolist()}
    sid, _, amb = voice.match_embedding(a, profiles, threshold=0.5, margin=0.03)
    assert sid is not None and amb


def test_match_embedding_no_profiles(rng):
    assert voice.match_embedding(unit(rng.normal(size=256)), {1: None}) == (None, 0.0, False)


def test_best_per_student_keeps_strongest_unambiguous():
    m = voice.SegmentMatch
    best = voice.best_per_student([
        m(0, 1, 1, 0.80, False), m(2, 3, 1, 0.90, False), m(4, 5, 2, 0.95, True), m(6, 7, None, 0.5, False)])
    assert set(best) == {1} and best[1].similarity == 0.90


def test_split_segments_finds_speech_bursts():
    sr = 16_000
    t = np.arange(int(0.8 * sr)) / sr
    burst = 0.5 * np.sin(2 * np.pi * 220 * t)
    blip = 0.5 * np.sin(2 * np.pi * 220 * t[: int(0.1 * sr)])
    silence = np.zeros(int(0.7 * sr))
    audio = np.concatenate([silence, burst, silence, blip, silence, burst, silence]).astype(np.float32)
    segs = voice.split_segments(audio, sr, min_seconds=0.5)
    assert len(segs) == 2  # the 0.1 s blip is dropped
