from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.db import crypto
from app.db.database import (
    SCHEMA_PATH,
    Database,
    q_add_message,
    q_create_session,
    q_get_messages,
    q_get_session,
    q_get_user_settings,
    q_set_user_setting,
)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "data", secret="unit-secret")


def _make_user(db, name="alice", key=None):
    return db.create_user(name, "geheim123", key or crypto.new_key())


def test_user_db_file_is_encrypted(db):
    user = _make_user(db)
    with db.user_db(user) as con:
        s = q_create_session(con, "Geheime Session")
        q_add_message(con, s["id"], {"role": "user", "text": "streng geheim"})
    raw = (db.users_dir / f"{user['uid']}.db.enc").read_bytes()
    assert b"streng geheim" not in raw
    assert b"Geheime Session" not in raw


def test_user_db_persists_across_reopen(db):
    user = _make_user(db)
    with db.user_db(user) as con:
        s = q_create_session(con, "Session A")
        q_add_message(con, s["id"], {"role": "user", "text": "Hallo"})
    with db.user_db(user) as con:
        assert q_get_session(con, s["id"])["name"] == "Session A"
        assert q_get_messages(con, s["id"])[0]["text"] == "Hallo"


def test_wrong_key_cannot_decrypt(db):
    user = _make_user(db)
    with db.user_db(user) as con:
        q_create_session(con, "x")
    wrong = {**user, "key": crypto.new_key()}
    with pytest.raises(ValueError):
        with db.user_db(wrong):
            pass


def test_credentials_live_in_separate_user_registry_db(db):
    user = _make_user(db, "alice")
    registry_path = db.data_dir / "user_registry.db.enc"
    assert registry_path.exists()
    raw = registry_path.read_bytes()
    assert b"alice" not in raw
    assert base64.b64decode(user["salt"])
    assert db.registry.get_by_name("alice")["uid"] == user["uid"]
    assert db.registry.get_by_id(user["uid"])["username"] == "alice"
    assert db.registry.verify_login("alice", "geheim123")["uid"] == user["uid"]
    assert db.registry.verify_login("alice", "falsch") is None
    with pytest.raises(ValueError):
        db.create_user("alice", "geheim123")


def test_user_settings_table_roundtrip(db):
    user = _make_user(db)
    with db.user_db(user) as con:
        q_set_user_setting(con, "theme", "dark")
        q_set_user_setting(con, "api_key", "sk-xyz")
        stored = q_get_user_settings(con)
    assert stored == {"theme": "dark", "api_key": "sk-xyz"}


def test_schema_file_exists():
    assert Path(SCHEMA_PATH).exists()
    content = Path(SCHEMA_PATH).read_text()
    assert "CREATE TABLE IF NOT EXISTS sessions" in content
    assert "CREATE TABLE IF NOT EXISTS messages" in content
    assert "CREATE TABLE IF NOT EXISTS user_settings" in content
