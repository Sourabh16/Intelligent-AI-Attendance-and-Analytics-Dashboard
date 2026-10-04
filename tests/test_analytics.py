import pandas as pd
import pytest

from src.core import analytics as an


@pytest.mark.parametrize("a,t,target,expected", [
    (6, 10, 75, 6),     # (6+6)/(10+6) = 0.75
    (7, 10, 75, 2),     # (7+2)/(12) = 0.75
    (8, 10, 75, 0),     # already above
    (0, 0, 75, 0),      # no classes yet
    (0, 4, 75, 12),     # 12/16
    (9, 10, 100, -1),   # unreachable
])
def test_classes_needed(a, t, target, expected):
    assert an.classes_needed(a, t, target) == expected


@pytest.mark.parametrize("a,t,target,expected", [
    (9, 10, 75, 2),     # 9/12 = 0.75
    (6, 8, 75, 0),      # exactly at target
    (5, 10, 75, 0),     # below target
    (30, 30, 75, 10),   # 30/40
])
def test_classes_can_miss(a, t, target, expected):
    assert an.classes_can_miss(a, t, target) == expected


def _records():
    rows = []
    sessions = [(1, "2026-09-07T04:00:00Z"), (2, "2026-09-08T04:00:00Z"), (3, "2026-09-14T04:00:00Z"),
                (4, "2026-09-15T04:00:00Z")]
    pattern = {101: [1, 1, 1, 1], 102: [1, 0, 1, 0], 103: [0, 0, 0, 1]}
    for sid, ts in sessions:
        for stu, marks in pattern.items():
            rows.append({
                "session_id": sid, "started_at": ts, "method": "face", "subject_id": 1,
                "subject_code": "CS101", "subject_name": "Programming", "section": "A",
                "student_id": stu, "student_name": f"S{stu}", "roll_no": f"R{stu}",
                "status": "present" if marks[sid - 1] else "absent",
                "source": "face" if marks[sid - 1] else "manual", "confidence": 0.8,
            })
    return an.records_frame(rows)


def test_records_frame_converts_to_ist():
    df = _records()
    assert str(df["started_at"].dt.tz) == "Asia/Kolkata"
    assert df["started_at"].iloc[0].hour == 9 and df["started_at"].iloc[0].minute == 30


def test_student_summary():
    s = an.student_summary(_records(), 75).set_index("student_id")
    assert s.loc[101, "pct"] == 100 and s.loc[101, "can_miss"] == 1
    assert s.loc[102, "pct"] == 50 and s.loc[102, "need"] == 4
    assert s.loc[103, "status"] == "Below target"


def test_session_summary_and_overview():
    df = _records()
    ss = an.session_summary(df)
    assert list(ss["session_id"]) == [4, 3, 2, 1]  # newest first
    assert ss.set_index("session_id").loc[2, "present"] == 1
    o = an.overview(df, 75)
    assert o == {"sessions": 4, "students": 3, "avg_pct": pytest.approx(58.333, 0.01),
                 "below_target": 2, "last_session_pct": pytest.approx(66.667, 0.01)}


def test_defaulters_trend_weekday_heatmap_mix():
    df = _records()
    assert list(an.defaulters(df, 75)["student_id"]) == [103, 102]
    tr = an.trend(df)
    assert tr["started_at"].is_monotonic_increasing and "rolling_pct" in tr
    wd = an.weekday_profile(df)
    assert list(wd["weekday"].astype(str)) == ["Monday", "Tuesday"]
    assert len(an.heatmap_frame(df)) == 12
    assert an.method_mix(df).set_index("source")["count"].to_dict() == {"face": 7}


def test_empty_frames_are_safe():
    df = an.records_frame([])
    assert an.student_summary(df).empty and an.session_summary(df).empty
    assert an.overview(df)["sessions"] == 0


def test_exports():
    df = _records()
    xlsx = an.to_excel(df, 75)
    sheets = pd.read_excel(__import__("io").BytesIO(xlsx), sheet_name=None)
    assert set(sheets) == {"Overview", "Students", "Sessions", "Raw log"}
    assert len(sheets["Raw log"]) == 12
    assert an.to_csv(df).decode().splitlines()[0].startswith("session_id,started_at")
