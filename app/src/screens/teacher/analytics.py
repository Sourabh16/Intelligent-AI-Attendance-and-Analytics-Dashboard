"""Teacher: attendance analytics, past-session corrections and exports."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.core import analytics as an
from src.db import Repository
from src.screens.teacher.common import owned_subject, subject_label
from src.ui import components as ui

TEAL, AMBER, RED, GREY = "#0F766E", "#D97706", "#DC2626", "#94A3B8"


def render(repo: Repository, teacher: dict) -> None:
    st.header("Analytics")
    subjects = repo.teacher_subjects(teacher["teacher_id"])
    if not subjects:
        st.info("Create a subject and take attendance to see analytics.")
        return
    by_id = {s["subject_id"]: s for s in subjects}
    c1, c2 = st.columns([2, 2])
    subject_id = c1.selectbox("Subject", list(by_id), format_func=lambda i: subject_label(by_id[i]),
                              key="an_subject")
    subject = by_id[subject_id]
    target = float(subject["target_pct"])

    df = an.records_frame(repo.records(subject_id=subject_id))
    if df.empty:
        st.info("No attendance recorded for this subject yet.", icon=":material/insights:")
        return

    lo, hi = df["date"].min(), df["date"].max()
    picked = c2.date_input("Date range", (lo, hi), min_value=lo, max_value=hi, key="an_range")
    if isinstance(picked, tuple) and len(picked) == 2:
        df = df[(df["date"] >= picked[0]) & (df["date"] <= picked[1])]
    if df.empty:
        st.warning("No sessions in that date range.")
        return

    _kpis(df, target)
    overview_tab, students_tab, sessions_tab, export_tab = st.tabs(
        [":material/monitoring: Overview", ":material/groups: Students",
         ":material/event_note: Sessions", ":material/download: Export"])
    with overview_tab:
        _overview_charts(df, target)
    with students_tab:
        _students(df, target)
    with sessions_tab:
        _sessions(repo, teacher, df)
    with export_tab:
        _export(df, target, subject)


def _kpis(df: pd.DataFrame, target: float) -> None:
    o = an.overview(df, target)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Classes held", o["sessions"], border=True)
    k2.metric("Students", o["students"], border=True)
    k3.metric("Average attendance", f"{o['avg_pct']:.1f}%",
              f"{o['avg_pct'] - target:+.1f} pts vs target", border=True)
    k4.metric(f"Below {target:.0f}% target", f"{o['below_target']} of {o['students']}", border=True)


def _overview_charts(df: pd.DataFrame, target: float) -> None:
    tr = an.trend(df)
    base = alt.Chart(tr).encode(x=alt.X("started_at:T", title=None))
    line = base.mark_line(color=GREY, point=alt.OverlayMarkDef(color=TEAL, size=50)).encode(
        y=alt.Y("pct:Q", title="Attendance %", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("started_at:T", title="Class", format="%d %b %H:%M"),
                 alt.Tooltip("pct:Q", format=".1f", title="%"), "present", "total", "method"])
    rolling = base.mark_line(color=TEAL, strokeWidth=3).encode(y="rolling_pct:Q")
    rule = alt.Chart(pd.DataFrame({"y": [target]})).mark_rule(color=RED, strokeDash=[6, 4]).encode(y="y:Q")
    st.markdown("**Attendance per class** · thick line = 5-class average · dashed = target")
    st.altair_chart((line + rolling + rule).properties(height=280), width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("**By weekday**")
        wd = an.weekday_profile(df)
        st.altair_chart(alt.Chart(wd).mark_bar(color=TEAL, cornerRadiusEnd=4).encode(
            x=alt.X("weekday:N", sort=list(wd["weekday"].astype(str)), title=None),
            y=alt.Y("pct:Q", title="Avg %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["weekday:N", alt.Tooltip("pct:Q", format=".1f"), "sessions:Q"],
        ).properties(height=230), width="stretch")
    with right:
        st.markdown("**How present students were recognised**")
        mix = an.method_mix(df)
        if mix.empty:
            st.caption("No present marks yet.")
        else:
            st.altair_chart(alt.Chart(mix).mark_arc(innerRadius=55).encode(
                theta="count:Q",
                color=alt.Color("source:N", scale=alt.Scale(domain=["face", "voice", "manual"],
                                                            range=[TEAL, "#6366F1", GREY])),
                tooltip=["source:N", "count:Q"]).properties(height=230), width="stretch")

    st.markdown("**Who attended which class**")
    hm = an.heatmap_frame(df)
    n_students = hm["student"].nunique()
    st.altair_chart(alt.Chart(hm).mark_rect(stroke="white", strokeWidth=1).encode(
        x=alt.X("session:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("student:N", title=None, axis=alt.Axis(labelLimit=240, labelOverlap=False)),
        color=alt.Color("status:N", scale=alt.Scale(domain=["present", "absent"], range=[TEAL, "#FCA5A5"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["student:N", "session:N", "status:N"],
    ).properties(height=max(160, 22 * n_students)), width="stretch")


def _students(df: pd.DataFrame, target: float) -> None:
    s = an.student_summary(df, target)
    below = s[s["pct"] < target]
    if not below.empty:
        st.error(f"**{len(below)} student(s) below {target:.0f}%:** " +
                 ", ".join(f"{r.student_name} ({r.pct:.0f}%)" for r in below.itertuples()),
                 icon=":material/priority_high:")
    st.dataframe(
        s[["roll_no", "student_name", "attended", "total", "pct", "status", "need", "can_miss"]],
        hide_index=True, width="stretch",
        column_config={
            "roll_no": "Roll no", "student_name": "Name", "attended": "Attended", "total": "Classes",
            "pct": st.column_config.ProgressColumn("Attendance", min_value=0, max_value=100, format="%.0f%%"),
            "status": "Status",
            "need": st.column_config.NumberColumn("Must attend next", help="Consecutive classes needed to reach the target"),
            "can_miss": st.column_config.NumberColumn("Can still miss", help="Classes that can be missed while staying on target"),
        })
    if not below.empty:
        st.download_button("Download defaulter list (CSV)",
                           below[["roll_no", "student_name", "attended", "total", "pct", "need"]]
                           .to_csv(index=False).encode(),
                           file_name="defaulters.csv", mime="text/csv", icon=":material/download:")


def _sessions(repo: Repository, teacher: dict, df: pd.DataFrame) -> None:
    ss = an.session_summary(df)
    st.caption("Select a class to correct individual marks or delete it.")
    view = ss.assign(when=ss["started_at"].dt.strftime("%a %d %b %Y, %I:%M %p"))
    event = st.dataframe(
        view[["when", "method", "present", "total", "pct"]], hide_index=True, width="stretch",
        on_select="rerun", selection_mode="single-row", key="an_sessions",
        column_config={"when": "Class", "method": "Taken by", "present": "Present", "total": "Enrolled",
                       "pct": st.column_config.ProgressColumn("Attendance", min_value=0, max_value=100,
                                                              format="%.0f%%")})
    rows = event.selection.rows if event else []
    if rows:
        session_id = int(ss.iloc[rows[0]]["session_id"])
        _edit_session(repo, teacher, df[df["session_id"] == session_id], session_id)


def _edit_session(repo: Repository, teacher: dict, sdf: pd.DataFrame, session_id: int) -> None:
    if owned_subject(repo, teacher, int(sdf["subject_id"].iloc[0])) is None:
        st.error("Not your subject.")
        return
    when = ui.ist(sdf["started_at"].iloc[0])
    with st.container(border=True):
        st.markdown(f"**Correct class of {when}**")
        base = sdf[["student_id", "roll_no", "student_name", "present", "source"]].reset_index(drop=True)
        edited = st.data_editor(base, key=f"fix_{session_id}", hide_index=True, width="stretch",
                                disabled=["student_id", "roll_no", "student_name", "source"],
                                column_order=["present", "roll_no", "student_name", "source"],
                                column_config={"present": st.column_config.CheckboxColumn("Present")})
        changed = edited[edited["present"] != base["present"]]
        c1, c2 = st.columns(2)
        if c1.button(f"Save {len(changed)} change(s)", type="primary", disabled=changed.empty,
                     width="stretch", key=f"fix_save_{session_id}"):
            for r in changed.itertuples():
                repo.set_attendance(session_id, int(r.student_id), "present" if r.present else "absent")
            st.toast("Corrections saved", icon=":material/check_circle:")
            st.rerun()
        confirm = c2.checkbox("Confirm delete", key=f"fix_del_ok_{session_id}")
        if c2.button("Delete this class", disabled=not confirm, width="stretch", key=f"fix_del_{session_id}"):
            repo.delete_session(session_id)
            st.rerun()


def _export(df: pd.DataFrame, target: float, subject: dict) -> None:
    stem = f"{subject['subject_code']}{('-' + subject['section']) if subject['section'] else ''}-attendance"
    st.markdown("The Excel file has four sheets: overview, per-student summary, per-class summary and the raw log.")
    c1, c2 = st.columns(2)
    c1.download_button("Excel workbook", an.to_excel(df, target), file_name=f"{stem}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch", type="primary", icon=":material/table_view:")
    c2.download_button("Raw log (CSV)", an.to_csv(df), file_name=f"{stem}.csv", mime="text/csv",
                       width="stretch", icon=":material/description:")
