"""Helpers shared by the teacher sections."""

from __future__ import annotations

from src.db import Repository


def owned_subject(repo: Repository, teacher: dict, subject_id: int) -> dict | None:
    """The subject, only if it belongs to this teacher (authorisation check)."""
    s = repo.get_subject(subject_id)
    return s if s and s["teacher_id"] == teacher["teacher_id"] else None


def subject_label(s: dict) -> str:
    section = f" · Sec {s['section']}" if s.get("section") else ""
    return f"{s['name']} ({s['subject_code']}{section})"
