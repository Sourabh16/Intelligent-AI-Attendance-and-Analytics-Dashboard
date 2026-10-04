from src.core import security


def test_password_hash_roundtrip():
    h = security.hash_password("s3cretpass")
    assert h != "s3cretpass"
    assert security.check_password("s3cretpass", h)
    assert not security.check_password("wrong", h)
    assert not security.check_password("x", "not-a-hash")


def test_password_rules():
    assert security.password_problem("short1")
    assert security.password_problem("longbutnodigits")
    assert security.password_problem("12345678")
    assert security.password_problem("goodpass1") is None


def test_username_and_roll_rules():
    assert security.username_problem("ananya.roy") is None
    assert security.username_problem("Ananya Roy")
    assert security.normalise_roll(" 21bcs042 ") == "21BCS042"
    assert security.roll_problem("21BCS042") is None
    assert security.roll_problem("21 BCS")


def test_join_codes_avoid_confusable_characters():
    codes = {security.new_join_code() for _ in range(500)}
    assert len(codes) > 490
    assert all(len(c) == 6 and not set(c) & set("0O1IL") for c in codes)
    assert security.normalise_join_code(" k7q 2mx ") == "K7Q2MX"


def test_login_throttle(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "time", lambda: now[0])
    state = {}
    t = security.LoginThrottle(state, "x")
    for _ in range(security.config.MAX_LOGIN_ATTEMPTS):
        assert t.locked_for() == 0
        t.fail()
    assert t.locked_for() == security.config.LOGIN_LOCKOUT_SECONDS
    now[0] += security.config.LOGIN_LOCKOUT_SECONDS + 1
    assert t.locked_for() == 0
