import numpy as np
import pytest

from src.db.sqlite_repo import SqliteRepository


@pytest.fixture
def repo():
    return SqliteRepository(":memory:")


@pytest.fixture
def rng():
    return np.random.default_rng(42)


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)
