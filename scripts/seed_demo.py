"""Fill the database with a realistic demo semester.

    python scripts/seed_demo.py            # local SQLite (default)
    python scripts/seed_demo.py --reset    # delete the local database first

Creates teacher `demo` / password `demo1234`, three subjects, 32 students and
six weeks of classes with believable patterns (a few chronic absentees, a
Friday dip, mostly face-recognised marks). Demo students have random face
templates, so they can't sign in with a camera; register yourself for that.

Uses Supabase instead when SUPABASE_URL and SUPABASE_KEY are set in the
environment. Don't run it against a production database.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from src import config  # noqa: E402
from src.core import security  # noqa: E402

FIRST = ["Aarav", "Diya", "Kabir", "Ananya", "Vihaan", "Isha", "Arjun", "Meera", "Rohan", "Sara",
         "Aditya", "Tara", "Kunal", "Nisha", "Yash", "Pooja", "Rahul", "Zoya", "Dev", "Riya",
         "Farhan", "Kavya", "Siddharth", "Aisha", "Manav", "Sneha", "Harsh", "Neha", "Omar", "Priya",
         "Varun", "Lakshmi"]
LAST = ["Sharma", "Patel", "Iyer", "Khan", "Singh", "Reddy", "Das", "Gupta", "Nair", "Joshi"]

SUBJECTS = [  # code, name, section, weekdays (Mon=0), hour IST
    ("CS201", "Data Structures", "A", (0, 2, 4), 9),
    ("CS305", "Machine Learning", "A", (1, 3), 11),
    ("MA102", "Linear Algebra", "B", (0, 3, 4), 14),
]


def make_repo():
    if config.use_supabase():
        from src.db.supabase_repo import SupabaseRepository

        return SupabaseRepository(config.supabase_url(), config.supabase_key())
    from src.db.sqlite_repo import SqliteRepository

    return SqliteRepository(config.local_db_path())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete the local SQLite database first")
    ap.add_argument("--weeks", type=int, default=6)
    args = ap.parse_args()

    if args.reset and not config.use_supabase():
        config.local_db_path().unlink(missing_ok=True)
    repo = make_repo()
    if repo.get_teacher_by_username("demo"):
        sys.exit("Demo data already present (teacher 'demo' exists). Use --reset for a fresh local DB.")

    rng = np.random.default_rng(7)
    teacher = repo.create_teacher("demo", "Prof. Demo Teacher", security.hash_password("demo1234"))

    students = []
    for i, first in enumerate(FIRST):
        emb = rng.normal(0, 0.09, 128)
        voice = rng.normal(size=256)
        students.append(repo.create_student(
            f"DEMO{i + 1:03d}", f"{first} {LAST[i % len(LAST)]}",
            [(emb + rng.normal(0, 0.01, 128)).tolist() for _ in range(3)],
            (voice / np.linalg.norm(voice)).tolist() if i % 3 else None))

    # Each student's underlying attendance habit; a few are chronic absentees.
    habit = {s["student_id"]: float(np.clip(rng.normal(0.86, 0.08), 0.5, 0.99)) for s in students}
    for s in rng.choice(students, 5, replace=False):
        habit[s["student_id"]] = float(rng.uniform(0.45, 0.68))

    start = (datetime.now(UTC) - timedelta(weeks=args.weeks)).date()
    for code, name, section, days, hour in SUBJECTS:
        subj = repo.create_subject(teacher["teacher_id"], code, name, section, 75.0, security.new_join_code())
        members = [s for s in students if rng.random() < 0.8]
        for s in members:
            repo.enroll(subj["subject_id"], s["student_id"])
        for d in range(args.weeks * 7):
            day = start + timedelta(days=d)
            if day.weekday() not in days or day >= datetime.now(UTC).date():
                continue
            friday_dip = 0.12 if day.weekday() == 4 else 0.0
            method = rng.choice(["face", "face", "face", "voice", "mixed"])
            rows = []
            for s in members:
                present = rng.random() < habit[s["student_id"]] - friday_dip
                source = ("voice" if method == "voice" else "face") if present else "manual"
                if present and rng.random() < 0.05:
                    source = "manual"  # teacher ticked someone the AI missed
                rows.append({"student_id": s["student_id"], "status": "present" if present else "absent",
                             "source": source,
                             "confidence": round(float(rng.uniform(0.55, 0.95)), 2) if source != "manual" else None})
            session_id = repo.record_session(subj["subject_id"], str(method), rows)
            ist = datetime(day.year, day.month, day.day, hour, 0, tzinfo=config.TIMEZONE)
            when = ist.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if hasattr(repo, "_set_session_time"):
                repo._set_session_time(session_id, when)
            else:
                repo.sb.table("sessions").update({"started_at": when}).eq("session_id", session_id).execute()
        print(f"{code}: {len(members)} students, join code {subj['join_code']}")

    print(f"\nDone on {repo.backend_name}. Sign in as teacher 'demo' / 'demo1234'.")


if __name__ == "__main__":
    main()
