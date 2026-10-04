"""Attendance analytics on flat records.

Every function takes the DataFrame returned by `records_frame`, one row per
(session, student) with these columns:

    session_id, started_at (tz-aware), method, subject_id, subject_code,
    subject_name, section, student_id, student_name, roll_no, status,
    source, confidence

so the same code powers the teacher dashboard, the student dashboard and the
Excel export, and is tested without a database.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable, Mapping

import pandas as pd

from src import config

RECORD_COLUMNS = [
    "session_id", "started_at", "method", "subject_id", "subject_code",
    "subject_name", "section", "student_id", "student_name", "roll_no",
    "status", "source", "confidence",
]


def records_frame(rows: Iterable[Mapping]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows), columns=RECORD_COLUMNS)
    df["started_at"] = pd.to_datetime(df["started_at"], utc=True).dt.tz_convert(config.TIMEZONE)
    df["present"] = df["status"].eq("present")
    df["date"] = df["started_at"].dt.date
    return df


# ---- The 75% arithmetic -----------------------------------------------------


def pct(attended: int, total: int) -> float:
    return 100.0 * attended / total if total else 0.0


def classes_needed(attended: int, total: int, target_pct: float) -> int:
    """Consecutive classes to attend to reach the target.

    Smallest k with (attended + k) / (total + k) >= target.
    """
    t = target_pct / 100.0
    if total == 0 or attended / total >= t:
        return 0
    if t >= 1.0:
        return -1 if attended < total else 0  # 100% is unreachable once missed
    return math.ceil((t * total - attended) / (1.0 - t) - 1e-9)


def classes_can_miss(attended: int, total: int, target_pct: float) -> int:
    """Classes that can be skipped while staying at or above the target.

    Largest m with attended / (total + m) >= target.
    """
    t = target_pct / 100.0
    if total == 0 or t <= 0 or attended / total < t:
        return 0
    return max(0, math.floor(attended / t - total + 1e-9))


# ---- Summaries --------------------------------------------------------------


def student_summary(df: pd.DataFrame, target_pct: float = config.DEFAULT_TARGET_PCT) -> pd.DataFrame:
    """Per student (and subject): attended, total, %, status, what to do next."""
    if df.empty:
        return pd.DataFrame(columns=[
            "subject_name", "subject_code", "roll_no", "student_name", "attended",
            "total", "pct", "status", "need", "can_miss"])
    g = (
        df.groupby(["subject_id", "subject_name", "subject_code", "student_id",
                    "roll_no", "student_name"], as_index=False)
        .agg(attended=("present", "sum"), total=("session_id", "nunique"))
    )
    g["attended"] = g["attended"].astype(int)
    g["pct"] = [pct(a, t) for a, t in zip(g["attended"], g["total"], strict=False)]
    g["status"] = ["On track" if p >= target_pct else "Below target" for p in g["pct"]]
    g["need"] = [classes_needed(a, t, target_pct) for a, t in zip(g["attended"], g["total"], strict=False)]
    g["can_miss"] = [classes_can_miss(a, t, target_pct) for a, t in zip(g["attended"], g["total"], strict=False)]
    return g.sort_values(["subject_name", "pct", "roll_no"]).reset_index(drop=True)


def session_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per class session: when, how it was taken, present / total, %."""
    if df.empty:
        return pd.DataFrame(columns=["session_id", "started_at", "subject_name",
                                     "subject_code", "method", "present", "total", "pct"])
    g = (
        df.groupby(["session_id", "started_at", "subject_id", "subject_name",
                    "subject_code", "method"], as_index=False)
        .agg(present=("present", "sum"), total=("student_id", "nunique"))
    )
    g["present"] = g["present"].astype(int)
    g["pct"] = [pct(p, t) for p, t in zip(g["present"], g["total"], strict=False)]
    return g.sort_values("started_at", ascending=False).reset_index(drop=True)


def overview(df: pd.DataFrame, target_pct: float = config.DEFAULT_TARGET_PCT) -> dict:
    """Headline numbers for KPI tiles."""
    if df.empty:
        return {"sessions": 0, "students": 0, "avg_pct": 0.0, "below_target": 0,
                "last_session_pct": None}
    sessions = session_summary(df)
    students = student_summary(df, target_pct)
    return {
        "sessions": int(df["session_id"].nunique()),
        "students": int(df["student_id"].nunique()),
        "avg_pct": float(sessions["pct"].mean()),
        "below_target": int((students["pct"] < target_pct).sum()),
        "last_session_pct": float(sessions.iloc[0]["pct"]),
    }


def defaulters(df: pd.DataFrame, target_pct: float = config.DEFAULT_TARGET_PCT) -> pd.DataFrame:
    s = student_summary(df, target_pct)
    return s[s["pct"] < target_pct].sort_values("pct").reset_index(drop=True)


def trend(df: pd.DataFrame) -> pd.DataFrame:
    """Attendance % of each session in time order, with a 5-session rolling mean."""
    s = session_summary(df).sort_values("started_at").reset_index(drop=True)
    s["rolling_pct"] = s["pct"].rolling(5, min_periods=1).mean()
    return s


def weekday_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Average attendance % by day of week (which days students skip)."""
    s = session_summary(df)
    if s.empty:
        return pd.DataFrame(columns=["weekday", "pct", "sessions"])
    s["weekday"] = s["started_at"].dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    out = s.groupby("weekday", as_index=False).agg(pct=("pct", "mean"), sessions=("session_id", "count"))
    out["weekday"] = pd.Categorical(out["weekday"], order, ordered=True)
    return out.sort_values("weekday").reset_index(drop=True)


def heatmap_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Long-form (student, session) grid for a present/absent heatmap."""
    if df.empty:
        return pd.DataFrame(columns=["student", "session", "status"])
    h = df.copy()
    h["student"] = h["roll_no"] + " · " + h["student_name"]
    h["session"] = h["started_at"].dt.strftime("%d %b %H:%M")
    return h[["student", "session", "started_at", "status"]].sort_values("started_at")


def method_mix(df: pd.DataFrame) -> pd.DataFrame:
    """How students were marked present: face, voice or manual."""
    p = df[df["present"]]
    if p.empty:
        return pd.DataFrame(columns=["source", "count"])
    return p.groupby("source", as_index=False).size().rename(columns={"size": "count"})


# ---- Export -----------------------------------------------------------------


def to_excel(df: pd.DataFrame, target_pct: float = config.DEFAULT_TARGET_PCT) -> bytes:
    """Multi-sheet workbook: overview, per-student, per-session, raw log."""
    students = student_summary(df, target_pct)
    sessions = session_summary(df)
    raw = df.drop(columns=["present", "date"]).copy()
    for frame in (sessions, raw):
        frame["started_at"] = frame["started_at"].dt.tz_localize(None)
    ov = pd.DataFrame(list(overview(df, target_pct).items()), columns=["metric", "value"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        ov.to_excel(xw, sheet_name="Overview", index=False)
        students.to_excel(xw, sheet_name="Students", index=False)
        sessions.to_excel(xw, sheet_name="Sessions", index=False)
        raw.to_excel(xw, sheet_name="Raw log", index=False)
    return buf.getvalue()


def to_csv(df: pd.DataFrame) -> bytes:
    out = df.drop(columns=["present", "date"]).copy()
    out["started_at"] = out["started_at"].dt.strftime("%Y-%m-%d %H:%M")
    return out.to_csv(index=False).encode()
