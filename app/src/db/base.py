"""The data-access contract.

Screens talk only to a `Repository`. Two implementations exist:

* `SupabaseRepository`: production, Postgres on Supabase.
* `SqliteRepository`: local development and tests, no account needed.

Both are tested against the same contract tests (tests/test_repository.py),
so switching backends cannot change behaviour.

All methods return plain dicts / lists of dicts. Embeddings are lists of
floats; timestamps are ISO-8601 strings in UTC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

Row = dict[str, Any]


class DuplicateError(Exception):
    """A unique constraint was violated (username, roll number, ...)."""


class Repository(ABC):
    backend_name: str = "?"

    # ---- teachers -----------------------------------------------------------
    @abstractmethod
    def get_teacher_by_username(self, username: str) -> Row | None: ...

    @abstractmethod
    def create_teacher(self, username: str, name: str, password_hash: str) -> Row: ...

    # ---- students -----------------------------------------------------------
    @abstractmethod
    def get_student(self, student_id: int) -> Row | None: ...

    @abstractmethod
    def get_student_by_roll(self, roll_no: str) -> Row | None: ...

    @abstractmethod
    def create_student(
        self, roll_no: str, name: str, face_embeddings: list[list[float]],
        voice_embedding: list[float] | None,
    ) -> Row: ...

    @abstractmethod
    def all_face_embeddings(self) -> dict[int, list[list[float]]]:
        """student_id -> face embeddings, for duplicate-registration checks."""

    @abstractmethod
    def update_student(self, student_id: int, **fields: Any) -> None:
        """Update name / face_embeddings / voice_embedding."""

    @abstractmethod
    def delete_student(self, student_id: int) -> None:
        """Remove the student, their biometrics and all their records."""

    # ---- subjects -----------------------------------------------------------
    @abstractmethod
    def create_subject(
        self, teacher_id: int, subject_code: str, name: str, section: str,
        target_pct: float, join_code: str,
    ) -> Row: ...

    @abstractmethod
    def get_subject(self, subject_id: int) -> Row | None: ...

    @abstractmethod
    def subject_by_join_code(self, join_code: str) -> Row | None: ...

    @abstractmethod
    def teacher_subjects(self, teacher_id: int) -> list[Row]:
        """Subjects with `n_students` and `n_sessions` counts."""

    @abstractmethod
    def update_subject(self, subject_id: int, **fields: Any) -> None:
        """Update join_code / join_open / target_pct / name / section."""

    @abstractmethod
    def delete_subject(self, subject_id: int) -> None: ...

    # ---- enrollments --------------------------------------------------------
    @abstractmethod
    def enroll(self, subject_id: int, student_id: int) -> bool:
        """False when the student was already enrolled."""

    @abstractmethod
    def unenroll(self, subject_id: int, student_id: int) -> None: ...

    @abstractmethod
    def roster(self, subject_id: int) -> list[Row]:
        """Enrolled students with their embeddings, ordered by roll number."""

    @abstractmethod
    def student_subjects(self, student_id: int) -> list[Row]:
        """Subjects a student is enrolled in, with `teacher_name`."""

    # ---- sessions & attendance ---------------------------------------------
    @abstractmethod
    def record_session(self, subject_id: int, method: str, rows: Sequence[Row]) -> int:
        """Atomically create a session and its attendance rows."""

    @abstractmethod
    def set_attendance(self, session_id: int, student_id: int, status: str) -> None:
        """Teacher correction of one past record (marked edited, source manual)."""

    @abstractmethod
    def delete_session(self, session_id: int) -> None: ...

    @abstractmethod
    def records(
        self, *, teacher_id: int | None = None, subject_id: int | None = None,
        student_id: int | None = None,
    ) -> list[Row]:
        """Rows of the attendance_records view, filtered."""
