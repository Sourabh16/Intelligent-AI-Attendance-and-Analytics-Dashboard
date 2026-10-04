"""Contract tests for the data layer, run against the SQLite backend.

The Supabase backend implements the same interface against the same schema
(supabase/schema.sql); test_schema_parity checks the two schemas agree.
"""

import re
import sqlite3
from pathlib import Path

import pytest

from src.db.base import DuplicateError

ROOT = Path(__file__).resolve().parent.parent


def _setup(repo):
    t = repo.create_teacher("ananya", "Ananya Roy", "hash")
    s = repo.create_subject(t["teacher_id"], "CS101", "Programming", "A", 75, "ABC234")
    a = repo.create_student("R1", "Asha", [[0.1] * 128], None)
    b = repo.create_student("R2", "Bilal", [[0.2] * 128, [0.3] * 128], [0.5] * 256)
    return t, s, a, b


def test_teacher_and_student_uniqueness(repo):
    _setup(repo)
    with pytest.raises(DuplicateError):
        repo.create_teacher("ananya", "Other", "hash")
    with pytest.raises(DuplicateError):
        repo.create_student("R1", "Other", [], None)
    assert repo.get_teacher_by_username("ananya")["name"] == "Ananya Roy"
    assert repo.get_teacher_by_username("nobody") is None


def test_embeddings_roundtrip_as_lists(repo):
    _, _, a, b = _setup(repo)
    got = repo.get_student_by_roll("R2")
    assert got["face_embeddings"] == [[0.2] * 128, [0.3] * 128]
    assert got["voice_embedding"] == [0.5] * 256
    assert repo.get_student(a["student_id"])["voice_embedding"] is None
    assert set(repo.all_face_embeddings()) == {a["student_id"], b["student_id"]}
    repo.update_student(a["student_id"], voice_embedding=[0.1] * 256)
    assert repo.get_student(a["student_id"])["voice_embedding"] == [0.1] * 256


def test_subjects_join_codes_and_counts(repo):
    t, s, a, b = _setup(repo)
    with pytest.raises(DuplicateError):  # same teacher, code and section
        repo.create_subject(t["teacher_id"], "CS101", "Again", "A", 75, "XYZ789")
    with pytest.raises(DuplicateError):  # join code collision
        repo.create_subject(t["teacher_id"], "CS102", "Other", "A", 75, "ABC234")
    found = repo.subject_by_join_code("ABC234")
    assert found["subject_id"] == s["subject_id"] and found["teacher_name"] == "Ananya Roy"
    assert found["join_open"] is True
    assert repo.enroll(s["subject_id"], a["student_id"]) is True
    assert repo.enroll(s["subject_id"], a["student_id"]) is False  # already enrolled
    repo.enroll(s["subject_id"], b["student_id"])
    (row,) = repo.teacher_subjects(t["teacher_id"])
    assert row["n_students"] == 2 and row["n_sessions"] == 0
    repo.update_subject(s["subject_id"], join_open=False, target_pct=80)
    got = repo.get_subject(s["subject_id"])
    assert got["join_open"] is False and got["target_pct"] == 80


def test_roster_and_student_subjects(repo):
    t, s, a, b = _setup(repo)
    repo.enroll(s["subject_id"], b["student_id"])
    repo.enroll(s["subject_id"], a["student_id"])
    assert [r["roll_no"] for r in repo.roster(s["subject_id"])] == ["R1", "R2"]
    (sub,) = repo.student_subjects(a["student_id"])
    assert sub["teacher_name"] == "Ananya Roy" and sub["name"] == "Programming"
    repo.unenroll(s["subject_id"], a["student_id"])
    assert repo.student_subjects(a["student_id"]) == []


def test_record_session_and_records_view(repo):
    t, s, a, b = _setup(repo)
    sid = repo.record_session(s["subject_id"], "face", [
        {"student_id": a["student_id"], "status": "present", "source": "face", "confidence": 0.9},
        {"student_id": b["student_id"], "status": "absent", "source": "manual"},
    ])
    rows = repo.records(teacher_id=t["teacher_id"])
    assert len(rows) == 2 and {r["session_id"] for r in rows} == {sid}
    assert {r["roll_no"]: r["status"] for r in rows} == {"R1": "present", "R2": "absent"}
    assert repo.records(student_id=a["student_id"])[0]["confidence"] == pytest.approx(0.9)
    assert repo.records(teacher_id=999) == []
    repo.set_attendance(sid, b["student_id"], "present")
    assert {r["status"] for r in repo.records(subject_id=s["subject_id"])} == {"present"}
    assert repo.teacher_subjects(t["teacher_id"])[0]["n_sessions"] == 1


def test_record_session_is_atomic(repo):
    _, s, a, _ = _setup(repo)
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_session(s["subject_id"], "face", [
            {"student_id": a["student_id"], "status": "present", "source": "face"},
            {"student_id": a["student_id"], "status": "present", "source": "face"},  # duplicate key
        ])
    assert repo.records(subject_id=s["subject_id"]) == []
    assert repo.teacher_subjects(s["teacher_id"])[0]["n_sessions"] == 0  # no orphan session


def test_deletes_cascade(repo):
    t, s, a, b = _setup(repo)
    repo.enroll(s["subject_id"], a["student_id"])
    sid = repo.record_session(s["subject_id"], "manual", [
        {"student_id": a["student_id"], "status": "present", "source": "manual"},
        {"student_id": b["student_id"], "status": "present", "source": "manual"}])
    repo.delete_student(a["student_id"])  # privacy: all their data goes
    assert repo.get_student(a["student_id"]) is None
    assert [r["roll_no"] for r in repo.records(subject_id=s["subject_id"])] == ["R2"]
    repo.delete_session(sid)
    assert repo.records(subject_id=s["subject_id"]) == []
    repo.delete_subject(s["subject_id"])
    assert repo.teacher_subjects(t["teacher_id"]) == []


def _pg_columns():
    sql = (ROOT / "supabase" / "schema.sql").read_text()
    tables = {}
    for name, body in re.findall(r"create table if not exists (\w+) \((.*?)\n\);", sql, re.S):
        cols = set()
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith(("--", "primary key", "unique")):
                cols.add(line.split()[0])
        tables[name] = cols
    return tables


def test_schema_parity(repo):
    pg = _pg_columns()
    assert set(pg) == {"teachers", "students", "subjects", "enrollments", "sessions", "attendance"}
    for table, cols in pg.items():
        lite = {r["name"] for r in repo._q(f"PRAGMA table_info({table})")}
        assert lite == cols, table
