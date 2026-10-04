"""Passwords, join codes, input validation and login throttling."""

from __future__ import annotations

import re
import secrets
import time

import bcrypt

from src import config

# No 0/O or 1/I/L: join codes are read aloud and typed from a projector.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")
_ROLL_RE = re.compile(r"^[A-Za-z0-9/_-]{2,30}$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:  # malformed hash
        return False


def password_problem(password: str) -> str | None:
    """Why a password is too weak, or None if it is acceptable."""
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one letter and one digit."
    return None


def normalise_username(username: str) -> str:
    return username.strip().lower()


def username_problem(username: str) -> str | None:
    if not _USERNAME_RE.match(username):
        return "Username: 3-30 characters, lowercase letters, digits, '_' or '.'."
    return None


def normalise_roll(roll_no: str) -> str:
    return roll_no.strip().upper()


def roll_problem(roll_no: str) -> str | None:
    if not _ROLL_RE.match(roll_no):
        return "Roll number: 2-30 characters, letters, digits, '/', '-' or '_'."
    return None


def new_join_code(length: int = config.JOIN_CODE_LENGTH) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def normalise_join_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


class LoginThrottle:
    """Lock a login form for a while after too many failures.

    State is a plain dict so it can live in st.session_state.
    """

    def __init__(self, state: dict, key: str) -> None:
        self.state = state.setdefault(f"_throttle_{key}", {"fails": 0, "until": 0.0})

    def locked_for(self) -> int:
        return max(0, int(self.state["until"] - time.time()))

    def fail(self) -> None:
        self.state["fails"] += 1
        if self.state["fails"] >= config.MAX_LOGIN_ATTEMPTS:
            self.state["until"] = time.time() + config.LOGIN_LOCKOUT_SECONDS
            self.state["fails"] = 0

    def succeed(self) -> None:
        self.state.update(fails=0, until=0.0)
