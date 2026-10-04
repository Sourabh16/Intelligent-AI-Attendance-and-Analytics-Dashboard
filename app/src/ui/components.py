"""Shared look and small reusable widgets.

Colours and radius come from .streamlit/config.toml; the CSS below only adds
the brand font, hides Streamlit's default chrome and styles our own HTML.
All user-supplied text inserted into HTML goes through `esc()`.
"""

from __future__ import annotations

import html

import streamlit as st

from src import config

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
/* Set the font once on the app root; Material icons keep their own font. */
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea {
    font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
}
h1, h2, h3 { font-family: 'Plus Jakarta Sans', system-ui, sans-serif !important; letter-spacing: -0.02em; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 2rem; max-width: 1180px; }

.as-brand { display:flex; align-items:center; gap:.7rem; }
.as-logo { width:42px; height:42px; border-radius:12px; display:grid; place-items:center;
           background:linear-gradient(135deg,#0F766E,#14B8A6); color:white; font-weight:800; font-size:1.1rem; }
.as-name { font-weight:800; font-size:1.35rem; color:#0F172A; line-height:1; }
.as-sub  { font-size:.8rem; color:#64748B; margin-top:.2rem; }

.as-hero { text-align:center; padding:2.2rem 1rem 1.2rem; }
.as-hero h1 { font-size:2.6rem; margin:0 0 .4rem; color:#0F172A; }
.as-hero p { color:#475569; font-size:1.05rem; margin:0; }

.as-chip { display:inline-block; padding:.1rem .55rem; border-radius:999px; font-size:.78rem;
           font-weight:600; background:#E6F4F1; color:#0F766E; margin-right:.3rem; }
.as-chip.warn { background:#FEF3C7; color:#92400E; }
.as-chip.bad  { background:#FEE2E2; color:#991B1B; }
.as-chip.mono { font-family: ui-monospace, Menlo, monospace; letter-spacing:.08em; }

.as-foot { text-align:center; color:#94A3B8; font-size:.8rem; margin-top:3rem; }
.as-bar { height:8px; border-radius:999px; background:#E2E8F0; overflow:hidden; margin:.35rem 0 .2rem; }
.as-bar > span { display:block; height:100%; border-radius:999px; }
</style>
"""


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def apply_theme() -> None:
    st.html(_CSS)


def brand(subtitle: str | None = None) -> None:
    sub = f'<div class="as-sub">{esc(subtitle)}</div>' if subtitle else ""
    st.html(
        f'<div class="as-brand"><div class="as-logo">AS</div>'
        f'<div><div class="as-name">{esc(config.APP_NAME)}</div>{sub}</div></div>'
    )


def top_bar(subtitle: str, button_label: str, key: str) -> bool:
    """Brand on the left, one action button on the right. Returns clicked."""
    left, right = st.columns([3, 1], vertical_alignment="center")
    with left:
        brand(subtitle)
    with right:
        return st.button(button_label, key=key, width="stretch")


def chip(text: str, kind: str = "") -> str:
    return f'<span class="as-chip {kind}">{esc(text)}</span>'


def pct_bar(pct: float, target: float) -> str:
    colour = "#0F766E" if pct >= target else ("#D97706" if pct >= target - 10 else "#DC2626")
    width = max(0.0, min(100.0, pct))
    return f'<div class="as-bar"><span style="width:{width:.1f}%;background:{colour}"></span></div>'


def footer() -> None:
    backend = st.session_state.get("_backend_name", "")
    st.html(f'<div class="as-foot">{esc(config.APP_NAME)} · face &amp; voice attendance'
            f'{" · " + esc(backend) if backend else ""}</div>')


def local_mode_notice() -> None:
    st.info(
        "Running on the **local SQLite database**: no Supabase keys configured. "
        "Data stays on this machine. Add `SUPABASE_URL` and `SUPABASE_KEY` to "
        "secrets to use the cloud database.",
        icon=":material/database:",
    )


def ist(ts) -> str:
    """Format an ISO string / Timestamp in the configured timezone."""
    import pandas as pd

    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(config.TIMEZONE).strftime("%d %b %Y, %I:%M %p")
