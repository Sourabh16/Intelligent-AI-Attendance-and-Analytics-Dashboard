"""End-to-end UI tests with Streamlit's headless AppTest runner.

They drive the real app.py (local SQLite backend, fresh database per test)
through the flows that need no camera: teacher registration, subject
creation, manual attendance, analytics, and the student join dialog.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTENDSENSE_DB", str(tmp_path / "ui.db"))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    from src.db import get_repo

    get_repo.clear()
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _register_teacher(at):
    _button(at, "Open teacher portal").click().run()
    next(t for t in at.text_input if t.label == "Full name").input("Ananya Roy")
    # two "Username"/"Password" inputs exist (sign-in and register tabs): take the register ones
    usernames = [t for t in at.text_input if t.label == "Username"]
    passwords = [t for t in at.text_input if t.label == "Password"]
    usernames[1].input("ananya.roy")
    passwords[1].input("goodpass1")
    next(t for t in at.text_input if t.label == "Confirm password").input("goodpass1")
    _button(at, "Create account").click().run()
    assert not at.exception


def test_each_test_gets_a_fresh_database(app):
    from src.db import get_repo

    assert get_repo().get_teacher_by_username("ananya.roy") is None


def test_home_renders_with_local_notice(app):
    assert any("local SQLite" in i.value for i in app.info)
    assert [b.label for b in app.button][:2] == ["Open teacher portal", "Open student portal"]


def test_teacher_register_rejects_weak_password(app):
    _button(app, "Open teacher portal").click().run()
    next(t for t in app.text_input if t.label == "Full name").input("A")
    [t for t in app.text_input if t.label == "Username"][1].input("abc")
    [t for t in app.text_input if t.label == "Password"][1].input("short")
    next(t for t in app.text_input if t.label == "Confirm password").input("short")
    _button(app, "Create account").click().run()
    assert any("at least 8" in e.value for e in app.error)


def test_teacher_full_flow(app):
    from src.db import get_repo

    _register_teacher(app)
    assert app.session_state["teacher"]["username"] == "ananya.roy"

    repo = get_repo()
    t = repo.get_teacher_by_username("ananya.roy")
    s = repo.create_subject(t["teacher_id"], "CS101", "Programming", "A", 75, "TEST23")
    a = repo.create_student("R1", "Asha", [[0.0] * 128], None)
    b = repo.create_student("R2", "Bilal", [[1.0] * 128], None)
    repo.enroll(s["subject_id"], a["student_id"])
    repo.enroll(s["subject_id"], b["student_id"])

    app.run()  # Take attendance section is the default
    assert not app.exception
    assert len(app.dataframe) == 1, "review table should be shown"
    _button(app, "Mark everyone present").click().run()
    _button(app, "Save attendance").click().run()
    assert not app.exception
    rows = repo.records(subject_id=s["subject_id"])
    assert len(rows) == 2 and {r["status"] for r in rows} == {"present"}

    app.segmented_control[0].set_value("Analytics").run()
    assert not app.exception
    assert any(m.label == "Classes held" and m.value == "1" for m in app.metric)

    app.segmented_control[0].set_value("Subjects").run()
    assert not app.exception
    assert any(m.label == "Students" and m.value == "2" for m in app.metric)


def test_join_link_routes_to_student_portal(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTENDSENSE_DB", str(tmp_path / "ui.db"))
    from src.db import get_repo

    get_repo.clear()
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["join"] = "abc234"
    at.run()
    assert not at.exception
    assert at.session_state["portal"] == "student"
    assert at.session_state["pending_join"] == "ABC234"
    assert any("ABC234" in i.value for i in at.info)


def test_student_dashboard_and_join(app):
    from src.db import get_repo

    repo = get_repo()
    t = repo.create_teacher("t1", "Teacher One", "x")
    s = repo.create_subject(t["teacher_id"], "CS101", "Programming", "", 75, "JOIN23")
    stu = repo.create_student("R1", "Asha", [[0.0] * 128], None)
    other = repo.create_student("R2", "Bilal", [[1.0] * 128], None)
    repo.enroll(s["subject_id"], stu["student_id"])
    repo.enroll(s["subject_id"], other["student_id"])
    for status in ("present", "absent", "absent", "present"):
        repo.record_session(s["subject_id"], "face", [
            {"student_id": stu["student_id"], "status": status, "source": "face"},
            {"student_id": other["student_id"], "status": "present", "source": "face"}])

    app.session_state["portal"] = "student"
    app.session_state["student_id"] = stu["student_id"]
    app.run()
    assert not app.exception
    # 2 of 4 = 50%: needs (0.75*4-2)/0.25 = 4 consecutive classes
    assert any("next **4**" in e.value for e in app.error)

    # A join link opens the dialog with the code filled in.
    app.session_state["pending_join"] = "JOIN45"
    app.run()
    assert not app.exception
    field = next(t for t in app.text_input if t.label == "Join code from your teacher")
    assert field.value == "JOIN45"


def test_join_subject_rules():
    from src.db.sqlite_repo import SqliteRepository
    from src.screens.student.main import join_subject

    repo = SqliteRepository(":memory:")
    t = repo.create_teacher("t1", "Teacher One", "x")
    s = repo.create_subject(t["teacher_id"], "CS101", "Programming", "", 75, "JOIN23")
    shut = repo.create_subject(t["teacher_id"], "CS102", "Closed", "", 75, "SHUT23")
    repo.update_subject(shut["subject_id"], join_open=False)
    stu = repo.create_student("R1", "Asha", [[0.0] * 128], None)

    assert join_subject(repo, stu["student_id"], " join 23 ")[0] is True  # normalised
    ok, msg = join_subject(repo, stu["student_id"], "JOIN23")
    assert not ok and "already" in msg
    ok, msg = join_subject(repo, stu["student_id"], "SHUT23")
    assert not ok and "closed" in msg
    ok, msg = join_subject(repo, stu["student_id"], "NOPE99")
    assert not ok and "No subject" in msg
    assert [x["subject_id"] for x in repo.student_subjects(stu["student_id"])] == [s["subject_id"]]
