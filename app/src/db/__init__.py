"""Picks the database backend from the configured secrets."""

from __future__ import annotations

import streamlit as st

from src import config
from src.db.base import DuplicateError, Repository

__all__ = ["DuplicateError", "Repository", "get_repo"]


@st.cache_resource(show_spinner=False)
def get_repo() -> Repository:
    if config.use_supabase():
        from src.db.supabase_repo import SupabaseRepository

        return SupabaseRepository(config.supabase_url(), config.supabase_key())
    from src.db.sqlite_repo import SqliteRepository

    return SqliteRepository(config.local_db_path())
