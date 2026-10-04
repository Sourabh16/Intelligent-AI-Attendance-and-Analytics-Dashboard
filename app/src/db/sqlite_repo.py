"""SQLite backend: the same schema as supabase/schema.sql, in a local file.

Used automatically when no Supabase secrets are configured, and by the test
suite (with an in-memory or temporary database).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.db.base import DuplicateError, Repository, Row

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS teachers (
    teacher_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS students (
    student_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no         TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    face_embeddings TEXT NOT NULL DEFAULT '[]',
    voice_embedding TEXT,
    consent_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS subjects (
    subject_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id   INTEGER NOT NULL REFERENCES teachers(teacher_id) ON DELETE CASCADE,
    subject_code TEXT NOT NULL,
    name         TEXT NOT NULL,
    section      TEXT NOT NULL DEFAULT '',
    join_code    TEXT NOT NULL UNIQUE,
    join_open    INTEGER NOT NULL DEFAULT 1,
    target_pct   REAL NOT NULL DEFAULT 75,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (teacher_id, subject_code, section)
);
CREATE TABLE IF NOT EXISTS enrollments (
    subject_id  INTEGER NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    enrolled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (subject_id, student_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    method     TEXT NOT NULL CHECK (method IN ('face','voice','manual','mixed'))
);
CREATE TABLE IF NOT EXISTS attendance (
    session_id INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN ('present','absent')),
    source     TEXT NOT NULL CHECK (source IN ('face','voice','manual')),
    confidence REAL,
    edited     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, student_id)
);
CREATE VIEW IF NOT EXISTS attendance_records AS
SELECT a.session_id, se.started_at, se.method, su.subject_id, su.subject_code,
       su.name AS subject_name, su.section, su.teacher_id, st.student_id,
       st.name AS student_name, st.roll_no, a.status, a.source, a.confidence
FROM attendance a
JOIN sessions se ON se.session_id = a.session_id
JOIN subjects su ON su.subject_id = se.subject_id
JOIN students st ON st.student_id = a.student_id;
"""

_JSON_COLS = ("face_embeddings", "voice_embedding")


class SqliteRepository(Repository):
    backend_name = "SQLite (local)"

    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()  # Streamlit serves sessions on threads
        with self._lock:
            self._conn.executescript(_SCHEMA)

    # ---- helpers ------------------------------------------------------------
    def _q(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = [self._decode(dict(r)) for r in cur.fetchall()]
            self._conn.commit()
        return rows

    def _one(self, sql: str, params: Sequence[Any] = ()) -> Row | None:
        rows = self._q(sql, params)
        return rows[0] if rows else None

    def _insert(self, table: str, data: Row) -> Row:
        data = {k: json.dumps(v) if k in _JSON_COLS and v is not None else v for k, v in data.items()}
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        try:
            return self._q(f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING *", list(data.values()))[0]
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) or "PRIMARY KEY" in str(e):
                raise DuplicateError(str(e)) from e
            raise

    def _update(self, table: str, key: str, key_value: int, fields: Row) -> None:
        if not fields:
            return
        fields = {k: json.dumps(v) if k in _JSON_COLS and v is not None else v for k, v in fields.items()}
        sets = ", ".join(f"{k} = ?" for k in fields)
        try:
            self._q(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*fields.values(), key_value])
        except sqlite3.IntegrityError as e:
            raise DuplicateError(str(e)) from e

    @staticmethod
    def _decode(row: Row) -> Row:
        for col in _JSON_COLS:
            if col in row and isinstance(row[col], str):
                row[col] = json.loads(row[col])
        if "join_open" in row:
            row["join_open"] = bool(row["join_open"])
        return row

    # ---- teachers -----------------------------------------------------------
    def get_teacher_by_username(self, username):
        return self._one("SELECT * FROM teachers WHERE username = ?", [username])

    def create_teacher(self, username, name, password_hash):
        return self._insert("teachers", {"username": username, "name": name, "password_hash": password_hash})

    # ---- students -----------------------------------------------------------
    def get_student(self, student_id):
        return self._one("SELECT * FROM students WHERE student_id = ?", [student_id])

    def get_student_by_roll(self, roll_no):
        return self._one("SELECT * FROM students WHERE roll_no = ?", [roll_no])

    def create_student(self, roll_no, name, face_embeddings, voice_embedding):
        return self._insert("students", {
            "roll_no": roll_no, "name": name,
            "face_embeddings": face_embeddings, "voice_embedding": voice_embedding,
        })

    def all_face_embeddings(self):
        rows = self._q("SELECT student_id, face_embeddings FROM students")
        return {r["student_id"]: r["face_embeddings"] for r in rows}

    def update_student(self, student_id, **fields):
        self._update("students", "student_id", student_id, fields)

    def delete_student(self, student_id):
        self._q("DELETE FROM students WHERE student_id = ?", [student_id])

    # ---- subjects -----------------------------------------------------------
    def create_subject(self, teacher_id, subject_code, name, section, target_pct, join_code):
        return self._insert("subjects", {
            "teacher_id": teacher_id, "subject_code": subject_code, "name": name,
            "section": section, "target_pct": target_pct, "join_code": join_code,
        })

    def get_subject(self, subject_id):
        return self._one("SELECT * FROM subjects WHERE subject_id = ?", [subject_id])

    def subject_by_join_code(self, join_code):
        return self._one(
            "SELECT s.*, t.name AS teacher_name FROM subjects s "
            "JOIN teachers t USING (teacher_id) WHERE join_code = ?", [join_code])

    def teacher_subjects(self, teacher_id):
        return self._q(
            """SELECT s.*,
                 (SELECT COUNT(*) FROM enrollments e WHERE e.subject_id = s.subject_id) AS n_students,
                 (SELECT COUNT(*) FROM sessions x WHERE x.subject_id = s.subject_id) AS n_sessions
               FROM subjects s WHERE teacher_id = ? ORDER BY s.created_at, s.subject_id""",
            [teacher_id])

    def update_subject(self, subject_id, **fields):
        if "join_open" in fields:
            fields["join_open"] = int(bool(fields["join_open"]))
        self._update("subjects", "subject_id", subject_id, fields)

    def delete_subject(self, subject_id):
        self._q("DELETE FROM subjects WHERE subject_id = ?", [subject_id])

    # ---- enrollments --------------------------------------------------------
    def enroll(self, subject_id, student_id):
        try:
            self._insert("enrollments", {"subject_id": subject_id, "student_id": student_id})
            return True
        except DuplicateError:
            return False

    def unenroll(self, subject_id, student_id):
        self._q("DELETE FROM enrollments WHERE subject_id = ? AND student_id = ?", [subject_id, student_id])

    def roster(self, subject_id):
        return self._q(
            """SELECT st.*, e.enrolled_at FROM enrollments e
               JOIN students st USING (student_id)
               WHERE e.subject_id = ? ORDER BY st.roll_no""", [subject_id])

    def student_subjects(self, student_id):
        return self._q(
            """SELECT s.*, t.name AS teacher_name, e.enrolled_at FROM enrollments e
               JOIN subjects s USING (subject_id) JOIN teachers t USING (teacher_id)
               WHERE e.student_id = ? ORDER BY s.name""", [student_id])

    # ---- sessions & attendance ---------------------------------------------
    def record_session(self, subject_id, method, rows):
        with self._lock:  # one transaction: all or nothing
            try:
                cur = self._conn.execute(
                    "INSERT INTO sessions (subject_id, method) VALUES (?, ?)", [subject_id, method])
                sid = cur.lastrowid
                self._conn.executemany(
                    "INSERT INTO attendance (session_id, student_id, status, source, confidence) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(sid, r["student_id"], r["status"], r["source"], r.get("confidence")) for r in rows])
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return int(sid)

    def set_attendance(self, session_id, student_id, status):
        self._q("UPDATE attendance SET status = ?, source = 'manual', edited = 1 "
                "WHERE session_id = ? AND student_id = ?", [status, session_id, student_id])

    def delete_session(self, session_id):
        self._q("DELETE FROM sessions WHERE session_id = ?", [session_id])

    def records(self, *, teacher_id=None, subject_id=None, student_id=None):
        where, params = [], []
        for col, val in (("teacher_id", teacher_id), ("subject_id", subject_id), ("student_id", student_id)):
            if val is not None:
                where.append(f"{col} = ?")
                params.append(val)
        sql = "SELECT * FROM attendance_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return self._q(sql + " ORDER BY started_at, roll_no", params)

    # ---- testing helper -----------------------------------------------------
    def _set_session_time(self, session_id: int, iso_utc: str) -> None:
        self._q("UPDATE sessions SET started_at = ? WHERE session_id = ?", [iso_utc, session_id])
