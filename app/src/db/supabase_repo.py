"""Supabase (Postgres) backend.

Runs only on the Streamlit server with the project's *secret* key, so the key
never reaches a browser. Tables have row-level security enabled with no
policies (see supabase/schema.sql), which blocks the public anon key.
"""

from __future__ import annotations

from datetime import UTC

from src.db.base import DuplicateError, Repository, Row

_PAGE = 1000  # PostgREST returns at most 1000 rows per request by default


class SupabaseRepository(Repository):
    backend_name = "Supabase"

    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self.sb = create_client(url, key)

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def _run(query):
        from postgrest.exceptions import APIError

        try:
            return query.execute().data
        except APIError as e:
            if getattr(e, "code", None) == "23505":  # unique_violation
                raise DuplicateError(e.message) from e
            raise

    def _first(self, query) -> Row | None:
        data = self._run(query.limit(1))
        return data[0] if data else None

    def _all(self, make_query) -> list[Row]:
        """Fetch every row, page by page. `make_query()` builds a fresh query."""
        out: list[Row] = []
        start = 0
        while True:
            page = self._run(make_query().range(start, start + _PAGE - 1))
            out.extend(page)
            if len(page) < _PAGE:
                return out
            start += _PAGE

    # ---- teachers -----------------------------------------------------------
    def get_teacher_by_username(self, username):
        return self._first(self.sb.table("teachers").select("*").eq("username", username))

    def create_teacher(self, username, name, password_hash):
        return self._run(self.sb.table("teachers").insert(
            {"username": username, "name": name, "password_hash": password_hash}))[0]

    # ---- students -----------------------------------------------------------
    def get_student(self, student_id):
        return self._first(self.sb.table("students").select("*").eq("student_id", student_id))

    def get_student_by_roll(self, roll_no):
        return self._first(self.sb.table("students").select("*").eq("roll_no", roll_no))

    def create_student(self, roll_no, name, face_embeddings, voice_embedding):
        from datetime import datetime

        return self._run(self.sb.table("students").insert({
            "roll_no": roll_no, "name": name, "face_embeddings": face_embeddings,
            "voice_embedding": voice_embedding,
            "consent_at": datetime.now(UTC).isoformat(),
        }))[0]

    def all_face_embeddings(self):
        rows = self._all(lambda: self.sb.table("students").select("student_id, face_embeddings").order("student_id"))
        return {r["student_id"]: r["face_embeddings"] for r in rows}

    def update_student(self, student_id, **fields):
        if fields:
            self._run(self.sb.table("students").update(fields).eq("student_id", student_id))

    def delete_student(self, student_id):
        self._run(self.sb.table("students").delete().eq("student_id", student_id))

    # ---- subjects -----------------------------------------------------------
    def create_subject(self, teacher_id, subject_code, name, section, target_pct, join_code):
        return self._run(self.sb.table("subjects").insert({
            "teacher_id": teacher_id, "subject_code": subject_code, "name": name,
            "section": section, "target_pct": target_pct, "join_code": join_code,
        }))[0]

    def get_subject(self, subject_id):
        return self._first(self.sb.table("subjects").select("*").eq("subject_id", subject_id))

    def subject_by_join_code(self, join_code):
        row = self._first(self.sb.table("subjects").select("*, teachers(name)").eq("join_code", join_code))
        if row:
            row["teacher_name"] = (row.pop("teachers") or {}).get("name", "")
        return row

    def teacher_subjects(self, teacher_id):
        rows = self._run(
            self.sb.table("subjects")
            .select("*, enrollments(count), sessions(count)")
            .eq("teacher_id", teacher_id)
            .order("created_at"))
        for r in rows:
            r["n_students"] = (r.pop("enrollments") or [{"count": 0}])[0]["count"]
            r["n_sessions"] = (r.pop("sessions") or [{"count": 0}])[0]["count"]
            r["target_pct"] = float(r["target_pct"])
        return rows

    def update_subject(self, subject_id, **fields):
        if fields:
            self._run(self.sb.table("subjects").update(fields).eq("subject_id", subject_id))

    def delete_subject(self, subject_id):
        self._run(self.sb.table("subjects").delete().eq("subject_id", subject_id))

    # ---- enrollments --------------------------------------------------------
    def enroll(self, subject_id, student_id):
        try:
            self._run(self.sb.table("enrollments").insert({"subject_id": subject_id, "student_id": student_id}))
            return True
        except DuplicateError:
            return False

    def unenroll(self, subject_id, student_id):
        self._run(self.sb.table("enrollments").delete().eq("subject_id", subject_id).eq("student_id", student_id))

    def roster(self, subject_id):
        rows = self._all(lambda: self.sb.table("enrollments").select("enrolled_at, students(*)")
                         .eq("subject_id", subject_id).order("student_id"))
        out = [{**r["students"], "enrolled_at": r["enrolled_at"]} for r in rows]
        return sorted(out, key=lambda s: s["roll_no"])

    def student_subjects(self, student_id):
        rows = self._run(self.sb.table("enrollments").select("enrolled_at, subjects(*, teachers(name))")
                         .eq("student_id", student_id))
        out = []
        for r in rows:
            s = dict(r["subjects"])
            s["teacher_name"] = (s.pop("teachers") or {}).get("name", "")
            s["enrolled_at"] = r["enrolled_at"]
            s["target_pct"] = float(s["target_pct"])
            out.append(s)
        return sorted(out, key=lambda s: s["name"])

    # ---- sessions & attendance ---------------------------------------------
    def record_session(self, subject_id, method, rows):
        payload = [{"student_id": r["student_id"], "status": r["status"], "source": r["source"],
                    "confidence": r.get("confidence")} for r in rows]
        data = self._run(self.sb.rpc("record_session",
                                     {"p_subject_id": subject_id, "p_method": method, "p_rows": payload}))
        return int(data)

    def set_attendance(self, session_id, student_id, status):
        self._run(self.sb.table("attendance")
                  .update({"status": status, "source": "manual", "edited": True})
                  .eq("session_id", session_id).eq("student_id", student_id))

    def delete_session(self, session_id):
        self._run(self.sb.table("sessions").delete().eq("session_id", session_id))

    def records(self, *, teacher_id=None, subject_id=None, student_id=None):
        def build():
            q = self.sb.table("attendance_records").select("*")
            for col, val in (("teacher_id", teacher_id), ("subject_id", subject_id), ("student_id", student_id)):
                if val is not None:
                    q = q.eq(col, val)
            return q.order("started_at").order("session_id").order("roll_no")

        return self._all(build)
