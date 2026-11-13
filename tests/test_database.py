from __future__ import annotations

import base64
import time
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
    q_set_generating,
    q_set_user_setting,
    q_try_start_generating,
    q_update_message,
)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "data")


def _make_user(email="alice@example.com", key=None, uid="uid-alice"):
    return {"uid": uid, "email": email, "username": email, "key": key or crypto.new_key()}


def test_user_db_file_is_encrypted(db):
    user = _make_user()
    with db.user_db(user) as con:
        s = q_create_session(con, "Geheime Session")
        q_add_message(con, s["id"], {"role": "user", "text": "streng geheim"})
    raw = (db.users_dir / f"{user['uid']}.db.enc").read_bytes()
    assert b"streng geheim" not in raw
    assert b"Geheime Session" not in raw


def test_user_db_persists_across_reopen(db):
    user = _make_user()
    with db.user_db(user) as con:
        s = q_create_session(con, "Session A")
        q_add_message(con, s["id"], {"role": "user", "text": "Hallo"})
    with db.user_db(user) as con:
        assert q_get_session(con, s["id"])["name"] == "Session A"
        assert q_get_messages(con, s["id"])[0]["text"] == "Hallo"


def test_user_db_read_only_access_does_not_write_file(db):
    """Reine Lesezugriffe duerfen die verschluesselte Datei nicht neu schreiben."""
    user = _make_user()
    with db.user_db(user) as con:
        q_create_session(con, "Session A")
    path = db.users_dir / f"{user['uid']}.db.enc"
    content_after_write = path.read_bytes()
    with db.user_db(user) as con:
        q_get_session(con, "egal")
        q_get_messages(con, "egal")
        q_get_user_settings(con)
    assert path.read_bytes() == content_after_write


def test_user_db_read_on_missing_file_creates_no_file(db):
    """Lesezugriff auf eine nicht existente User-DB legt keine Datei an."""
    user = _make_user()
    with db.user_db(user) as con:
        assert q_get_user_settings(con) == {}
    assert not (db.users_dir / f"{user['uid']}.db.enc").exists()


def test_messages_sorted_by_timestamp_with_system_first(db):
    user = _make_user()
    with db.user_db(user) as con:
        s = q_create_session(con, "Sortierung")
        m1 = q_add_message(con, s["id"], {"role": "user", "text": "erste"})
        m2 = q_add_message(con, s["id"], {"role": "assistant", "text": "zweite"})
        m3 = q_add_message(con, s["id"], {"role": "system", "text": "system-prompt"})
        m4 = q_add_message(con, s["id"], {"role": "user", "text": "dritte"})
        # Zeitstempel explizit setzen (created_at hat ms-Aufloesung):
        # id-Reihenfolge != Zeitstempel-Reihenfolge, System-Prompt zuletzt angelegt.
        for mid, ts in ((m1["id"], 300), (m2["id"], 100), (m3["id"], 50), (m4["id"], 200)):
            con.execute("UPDATE messages SET created_at = ? WHERE id = ?", (ts, mid))
        ordered = [m["text"] for m in q_get_messages(con, s["id"])]
        assert ordered == ["system-prompt", "zweite", "dritte", "erste"]


def test_add_message_stores_ms_created_at_and_update_can_patch_it(db):
    """created_at ist ms seit Epoch (Basis fuer die chronologische Bubble-Sortierung)."""
    user = _make_user()
    with db.user_db(user) as con:
        s = q_create_session(con, "Ts")
        before = int(time.time() * 1000)
        m = q_add_message(con, s["id"], {"role": "user", "text": "hallo"})
        after = int(time.time() * 1000)
        assert before <= m["ts"] <= after, f"created_at muss ms-Aufloesung haben: {m['ts']}"
        patched = q_update_message(con, m["id"], {"text": "hi", "created_at": m["ts"] + 5})
        assert patched["ts"] == m["ts"] + 5
        assert patched["text"] == "hi"


def test_wrong_key_cannot_decrypt(db):
    user = _make_user()
    with db.user_db(user) as con:
        q_create_session(con, "x")
    wrong = {**user, "key": crypto.new_key()}
    with pytest.raises(ValueError):
        with db.user_db(wrong):
            pass


def test_user_identity_is_derived_from_secret_and_email():
    from app.auth import user_identity

    a = user_identity("secret-1", "Alice@Example.com")
    b = user_identity("secret-1", "alice@example.com")
    c = user_identity("secret-2", "alice@example.com")
    assert a["uid"] == b["uid"] and a["key"] == b["key"]  # E-Mail case-insensitive, Ableitung deterministisch
    assert a["uid"] == c["uid"] and a["key"] != c["key"]  # uid aus E-Mail, Schluessel aus Secret + E-Mail
    assert a["email"] == "alice@example.com"
    assert a["username"] == "alice"
    assert len(base64.urlsafe_b64decode(a["key"])) == 32


def test_user_db_migrates_legacy_key_on_write(db):
    """Mit der alten SHA-256-Ableitung verschluesselte DBs werden per Legacy-Fallback
    gelesen und beim naechsten Schreibzugriff mit dem neuen Argon2id-Schluessel persistiert."""
    from app.auth import legacy_key, user_identity

    secret = "migrations-secret"
    email = "migrate@example.com"
    identity = user_identity(secret, email)
    legacy_user = {"uid": identity["uid"], "email": email, "username": email, "key": legacy_key(secret, email)}
    with db.user_db(legacy_user) as con:
        s = q_create_session(con, "Alt")
    with db.user_db(identity) as con:
        assert q_get_session(con, s["id"])["name"] == "Alt"
        q_set_user_setting(con, "theme", "dark")
    token = (db.users_dir / f"{identity['uid']}.db.enc").read_bytes()
    plain = crypto.decrypt(crypto.normalize_key(identity["key"]), token)
    assert b"dark" in plain


def test_user_db_migrates_messages_type_check_for_toolresult(db):
    """Bestehende DBs (alter CHECK ohne 'toolresult') werden per Tabellen-Rebuild migriert."""
    import sqlite3

    user = _make_user()
    old_schema = """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, ts INTEGER NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
            type TEXT NOT NULL DEFAULT 'message' CHECK (type IN ('message', 'toolcall', 'reasoning')),
            text TEXT NOT NULL DEFAULT '',
            in_context INTEGER NOT NULL DEFAULT 1,
            attachments TEXT NOT NULL DEFAULT '[]',
            created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );
    """
    con = sqlite3.connect(":memory:")
    con.executescript(old_schema)
    con.execute("INSERT INTO sessions (id, name, ts) VALUES ('s1', 'Alt', 1)")
    con.execute("INSERT INTO messages (session_id, role, type, text) VALUES ('s1', 'user', 'message', 'hallo')")
    con.commit()
    token = crypto.encrypt(crypto.normalize_key(user["key"]), con.serialize())
    con.close()
    db.users_dir.mkdir(parents=True, exist_ok=True)
    (db.users_dir / f"{user['uid']}.db.enc").write_bytes(token)

    with db.user_db(user) as con:
        msgs = q_get_messages(con, "s1")
        assert [m["text"] for m in msgs] == ["hallo"]
        q_add_message(con, "s1", {"role": "assistant", "type": "toolresult", "text": "f: 42", "in_context": False})
    with db.user_db(user) as con:
        types = [m["type"] for m in q_get_messages(con, "s1")]
        assert types == ["message", "toolresult"]


def test_user_settings_table_roundtrip(db):
    user = _make_user()
    with db.user_db(user) as con:
        q_set_user_setting(con, "theme", "dark")
        q_set_user_setting(con, "api_key", "sk-xyz")
        stored = q_get_user_settings(con)
    assert stored == {"theme": "dark", "api_key": "sk-xyz"}


def test_try_start_generating_is_atomic_check_and_set(db):
    user = _make_user()
    with db.user_db(user) as con:
        s = q_create_session(con, "S")
        assert q_try_start_generating(con, s["id"]) == "ok"
        assert q_try_start_generating(con, s["id"]) == "busy"
        assert q_try_start_generating(con, "unbekannt") == "missing"
        q_set_generating(con, s["id"], False)
        assert q_try_start_generating(con, s["id"]) == "ok"


def test_schema_file_exists():
    assert Path(SCHEMA_PATH).exists()
    content = Path(SCHEMA_PATH).read_text()
    assert "CREATE TABLE IF NOT EXISTS sessions" in content
    assert "CREATE TABLE IF NOT EXISTS messages" in content
    assert "CREATE TABLE IF NOT EXISTS user_settings" in content
