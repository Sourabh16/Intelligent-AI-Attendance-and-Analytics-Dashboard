import io

import numpy as np
from PIL import Image

from src.core import face


def _emb(rng, scale=1.0):
    return rng.normal(0, scale, 128)


def test_distance_uses_closest_sample(rng):
    a = _emb(rng)
    gallery = {1: [a + 5, a + 0.01], 2: [a + 3]}
    D, sids = face.distance_matrix([a], gallery)
    assert sids == [1, 2]
    assert D[0, 0] < 0.2 and D[0, 1] > 1


def test_clear_match_and_unknown(rng):
    a, b, stranger = _emb(rng), _emb(rng), _emb(rng)
    gallery = {10: [a], 20: [b]}
    res = face.match_faces([a + 0.001, stranger], gallery)
    assert res[0].student_id == 10 and res[0].status == "matched"
    assert res[1].status == "unknown" and res[1].student_id is None


def test_one_to_one_assignment(rng):
    """Two faces both nearest to student 1: only one may be marked as student 1,
    and it must be the more confident one (Hungarian would pick the other)."""
    a = _emb(rng)
    d = rng.normal(0, 1, 128)
    d /= np.linalg.norm(d)
    f1 = a + 0.05 * d  # 0.05 from student 1, 0.30 from student 2
    f2 = a - 0.10 * d  # 0.10 from student 1, 0.45 from student 2
    gallery = {1: [a], 2: [a + 0.35 * d]}
    res = face.match_faces([f1, f2], gallery, threshold=0.5, margin=0.0)
    assert res[0].student_id == 1
    assert res[1].student_id == 2
    assert len({r.student_id for r in res}) == 2


def test_assign_greedy_respects_threshold():
    D = np.array([[0.1, 0.9], [0.2, 0.8]])
    assert face.assign_greedy(D, threshold=0.5) == {0: 0}


def test_ambiguous_when_two_students_equally_close(rng):
    a = _emb(rng)
    d = rng.normal(0, 1, 128)
    d /= np.linalg.norm(d)
    gallery = {1: [a + 0.2 * d], 2: [a - 0.2 * d]}
    (res,) = face.match_faces([a], gallery, threshold=0.5, margin=0.05)
    assert res.status == "ambiguous"


def test_empty_gallery_and_no_faces(rng):
    assert face.match_faces([], {1: [_emb(rng)]}) == []
    (res,) = face.match_faces([_emb(rng)], {})
    assert res.status == "unknown" and res.confidence == 0.0


def test_verify_face(rng):
    a = _emb(rng)
    assert face.verify_face(a + 0.001, [a])[0]
    assert not face.verify_face(a + 1.0, [a])[0]
    assert not face.verify_face(a, [])[0]


def test_max_pairwise_distance(rng):
    a = _emb(rng)
    assert face.max_pairwise_distance([a]) == 0.0
    assert np.isclose(face.max_pairwise_distance([a, a + 3 / np.sqrt(128)]), 3.0)


def _landmarks(nose_x):
    pts = np.zeros((68, 2))
    pts[0] = (100, 200)
    pts[16] = (300, 200)
    pts[30] = (nose_x, 210)
    return pts


def test_head_turn_offset():
    assert abs(face.head_turn_offset(_landmarks(200))) < 1e-9
    assert np.isclose(face.head_turn_offset(_landmarks(260)), 0.3)
    assert np.isclose(face.head_turn_offset(_landmarks(140)), -0.3)


def test_load_image_applies_exif_rotation_and_downscale():
    img = Image.new("RGB", (400, 200), "red")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° on display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    arr = face.load_image(buf.getvalue(), max_side=100)
    assert arr.shape == (100, 50, 3) and arr.dtype == np.uint8


def test_annotate_draws_on_copy(rng):
    image = np.zeros((200, 300, 3), dtype=np.uint8)
    f = face.DetectedFace((50, 60, 120, 140), _emb(rng), np.zeros((68, 2)))
    m = face.FaceMatch(0, 7, 0.3, "matched")
    out = face.annotate(image, [f], [m], {7: "Asha"})
    assert out.size == (300, 200)
    assert np.asarray(out).sum() > 0 and image.sum() == 0
