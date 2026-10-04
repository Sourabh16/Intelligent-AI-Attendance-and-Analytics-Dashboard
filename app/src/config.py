"""Central settings.

Secrets (Supabase URL/key, public app URL) come from Streamlit secrets first,
then environment variables. Everything else is a plain constant so that every
tunable number in the project lives in exactly one place.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

APP_NAME = "AttendSense"
APP_TAGLINE = "AI attendance from one classroom photo or one voice recording"

APP_DIR = Path(__file__).resolve().parent.parent

TIMEZONE = ZoneInfo("Asia/Kolkata")

# ---- Face recognition -------------------------------------------------------
# dlib's 128-d embeddings: two photos of the same person are usually < 0.6 apart.
# We are stricter than the dlib default because a false "present" is worse
# than a false "absent" (the teacher can tick a missed student in review).
FACE_MATCH_THRESHOLD = 0.50
# If the second-best student is almost as close as the best, flag for review.
FACE_AMBIGUITY_MARGIN = 0.04
# Refuse a new registration whose face is this close to an existing student.
FACE_DUPLICATE_THRESHOLD = 0.42
# Enrollment shots must all be the same person.
FACE_ENROLL_CONSISTENCY = 0.55
FACE_ENROLL_SHOTS = 3
# Detector upsampling: 1 is fine for selfies; classroom photos need 2 to find
# small faces at the back of the room (slower).
FACE_UPSAMPLE_SELFIE = 1
FACE_UPSAMPLE_CLASSROOM = 2
# Large phone photos are downscaled to this longest side before detection.
MAX_IMAGE_SIDE = 2000

# ---- Liveness (head-turn challenge) ----------------------------------------
# Nose position across the face width: 0.5 is frontal.
LIVENESS_FRONTAL_MAX_OFFSET = 0.12
LIVENESS_TURN_MIN_OFFSET = 0.15

# ---- Voice recognition ------------------------------------------------------
VOICE_MATCH_THRESHOLD = 0.72
VOICE_AMBIGUITY_MARGIN = 0.03
VOICE_SAMPLE_RATE = 16_000
VOICE_MIN_SEGMENT_SECONDS = 0.6
VOICE_SILENCE_TOP_DB = 30

# ---- Attendance policy ------------------------------------------------------
DEFAULT_TARGET_PCT = 75.0
JOIN_CODE_LENGTH = 6

# ---- Auth -------------------------------------------------------------------
MIN_PASSWORD_LENGTH = 8
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 60


def _secret(name: str, default: str | None = None) -> str | None:
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets.toml, or running outside Streamlit
        pass
    return os.environ.get(name, default)


def supabase_url() -> str | None:
    return _secret("SUPABASE_URL")


def supabase_key() -> str | None:
    return _secret("SUPABASE_KEY")


def app_url() -> str:
    """Public URL of the deployed app, used in share links and QR codes."""
    return (_secret("APP_URL", "http://localhost:8501") or "").rstrip("/")


def local_db_path() -> Path:
    """SQLite file used when Supabase is not configured (ATTENDSENSE_DB overrides)."""
    return Path(os.environ.get("ATTENDSENSE_DB", APP_DIR / "local_data" / "attendsense.db"))


def use_supabase() -> bool:
    return bool(supabase_url() and supabase_key())
