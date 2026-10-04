from src.core import attendance as att
from src.core.face import FaceMatch
from src.core.voice import SegmentMatch

ROSTER = [{"student_id": 1, "roll_no": "A1", "name": "Asha"},
          {"student_id": 2, "roll_no": "A2", "name": "Bilal"},
          {"student_id": 3, "roll_no": "A3", "name": "Chen"}]


def test_merge_keeps_best_evidence():
    hits = {}
    amb = att.add_face_results(hits, [FaceMatch(0, 1, 0.25, "matched"), FaceMatch(1, 2, 0.3, "ambiguous")], "Photo 1")
    att.add_face_results(hits, [FaceMatch(0, 1, 0.10, "matched")], "Photo 2")
    att.add_voice_results(hits, {3: SegmentMatch(1.0, 2.0, 3, 0.85, False)})
    assert set(hits) == {1, 3} and len(amb) == 1
    assert hits[1].evidence == ["Photo 1", "Photo 2"] and hits[1].confidence == FaceMatch(0, 1, 0.10, "matched").confidence
    assert hits[3].source == "voice"


def test_draft_roundtrip_marks_manual_changes():
    hits = {}
    att.add_face_results(hits, [FaceMatch(0, 1, 0.2, "matched")], "Photo 1")
    original = att.build_draft(ROSTER, hits)
    assert list(original["present"]) == [True, False, False]
    edited = original.copy()
    edited.loc[edited["student_id"] == 2, "present"] = True  # teacher ticks Bilal
    rows = {r["student_id"]: r for r in att.rows_from_draft(original, edited)}
    assert rows[1] == {"student_id": 1, "status": "present", "source": "face", "confidence": rows[1]["confidence"]}
    assert rows[1]["confidence"] > 0
    assert rows[2]["status"] == "present" and rows[2]["source"] == "manual" and rows[2]["confidence"] is None
    assert rows[3]["status"] == "absent" and rows[3]["source"] == "manual"


def test_session_method():
    assert att.session_method({"face"}) == "face"
    assert att.session_method({"face", "manual"}) == "face"
    assert att.session_method({"face", "voice"}) == "mixed"
    assert att.session_method(set()) == "manual"
    assert att.session_method({"manual"}) == "manual"
