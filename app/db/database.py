"""Einzige Stelle mit Zugriff auf die SQLite-Datenbanken.

Zwei Datenbanken:

- **User Registry** (``<data_dir>/user_registry.db.enc``): Login-Credentials
  aller User (Schema: ``user_registry.sql``), mit dem Server-Secret
  verschluesselt. Dient als austauschbares Login-System.
- **Pro-User-Datenbank** (``<data_dir>/users/<uid>.db.enc``): Sessions,
  Messages und ``user_settings`` (Schema: ``schema.sql``), verschluesselt
  mit dem einmalig clientseitig generierten Schluessel des Users.

Zum Zugriff wird die jeweilige Datei entschluesselt, in eine
In-Memory-Datenbank geladen und nach dem Schreiben wieder
verschluesselt persistiert.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .. import security
from . import crypto

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
REGISTRY_SCHEMA_PATH = Path(__file__).with_name("user_registry.sql")

_lock = threading.RLock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_uid() -> str:
    return secrets.token_hex(8)


def _row_to_message(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "type": row["type"],
        "text": row["text"],
        "in_context": bool(row["in_context"]),
        "attachments": json.loads(row["attachments"] or "[]"),
    }


def _row_to_session(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "ts": row["ts"]}


def _row_to_user(row: sqlite3.Row) -> dict:
    return {
        "uid": row["uid"],
        "username": row["username"],
        "salt": row["salt"],
        "verifier": row["verifier"],
        "key": row["key"],
    }


class UserRegistry:
    """Login-Credentials in eigener, server-seitig verschluesselter Datenbank."""

    def __init__(self, path: Path, secret: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._key = base64.urlsafe_b64encode(digest)

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            con = sqlite3.connect(":memory:")
            con.row_factory = sqlite3.Row
            try:
                if self.path.exists():
                    con.deserialize(crypto.decrypt(self._key, self.path.read_bytes()))
                con.executescript(REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
                yield con
                con.commit()
                tmp = self.path.with_suffix(".tmp")
                tmp.write_bytes(crypto.encrypt(self._key, con.serialize()))
                tmp.replace(self.path)
            finally:
                con.close()

    def create(self, username: str, password: str, key_b64: str) -> dict:
        salt = security.new_salt()
        user = {
            "uid": _new_uid(),
            "username": username,
            "salt": base64.b64encode(salt).decode("ascii"),
            "verifier": security.hash_password(password, salt),
            "key": crypto.normalize_key(key_b64).decode("ascii"),
        }
        with self._con() as con:
            if con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ValueError("Benutzername bereits vergeben")
            con.execute(
                "INSERT INTO users (uid, username, salt, verifier, key) VALUES (?, ?, ?, ?, ?)",
                (user["uid"], user["username"], user["salt"], user["verifier"], user["key"]),
            )
        return user

    def get_by_name(self, username: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return _row_to_user(row) if row else None

    def get_by_id(self, uid: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM users WHERE uid = ?", (uid,)).fetchone()
            return _row_to_user(row) if row else None

    def verify_login(self, username: str, password: str) -> dict | None:
        user = self.get_by_name(username)
        if not user:
            return None
        if not security.verify_password(password, user["salt"], user["verifier"]):
            return None
        return user


class Database:
    """Verwaltet die User Registry und die verschluesselten per-user Datenbanken."""

    def __init__(
        self,
        data_dir: Path,
        secret: str,
        registry_path: Path | None = None,
        users_dir: Path | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.secret = secret
        self.users_dir = Path(users_dir) if users_dir else self.data_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        registry_path = Path(registry_path) if registry_path else self.data_dir / "user_registry.db.enc"
        self.registry = UserRegistry(registry_path, secret)

    def create_user(self, username: str, password: str, key_b64: str | None = None) -> dict:
        user = self.registry.create(username, password, key_b64 or crypto.new_key())
        self._init_user_db(user)
        return user

    def verify_login(self, username: str, password: str) -> dict | None:
        return self.registry.verify_login(username, password)

    def get_user(self, username: str) -> dict | None:
        return self.registry.get_by_name(username)

    def get_user_by_id(self, uid: str) -> dict | None:
        return self.registry.get_by_id(uid)

    def _db_path(self, user: dict) -> Path:
        return self.users_dir / f"{user['uid']}.db.enc"

    def _init_user_db(self, user: dict) -> None:
        con = sqlite3.connect(":memory:")
        try:
            con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            con.commit()
            self._write_encrypted(user, con.serialize())
        finally:
            con.close()

    def _write_encrypted(self, user: dict, plain: bytes) -> None:
        key = crypto.normalize_key(user["key"])
        token = crypto.encrypt(key, plain)
        path = self._db_path(user)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(token)
        tmp.replace(path)

    @contextmanager
    def user_db(self, user: dict) -> Iterator[sqlite3.Connection]:
        """Entschluesselte In-Memory-Sicht auf die SQLite-Datei eines Users."""
        with _lock:
            key = crypto.normalize_key(user["key"])
            path = self._db_path(user)
            con = sqlite3.connect(":memory:")
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            try:
                if path.exists():
                    con.deserialize(crypto.decrypt(key, path.read_bytes()))
                con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                yield con
                con.commit()
                self._write_encrypted(user, con.serialize())
            finally:
                con.close()


# --- Sessions ---


def q_list_sessions(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("SELECT id, name, ts FROM sessions ORDER BY ts DESC").fetchall()
    return [_row_to_session(r) for r in rows]


def q_create_session(con: sqlite3.Connection, name: str) -> dict:
    sid = _new_uid()
    ts = _now_ms()
    con.execute("INSERT INTO sessions (id, name, ts) VALUES (?, ?, ?)", (sid, name, ts))
    return {"id": sid, "name": name, "ts": ts}


def q_get_session(con: sqlite3.Connection, sid: str) -> dict | None:
    row = con.execute("SELECT id, name, ts FROM sessions WHERE id = ?", (sid,)).fetchone()
    return _row_to_session(row) if row else None


def q_rename_session(con: sqlite3.Connection, sid: str, name: str) -> None:
    con.execute("UPDATE sessions SET name = ? WHERE id = ?", (name, sid))


def q_delete_session(con: sqlite3.Connection, sid: str) -> None:
    con.execute("DELETE FROM sessions WHERE id = ?", (sid,))


# --- Messages ---


def q_get_messages(con: sqlite3.Connection, sid: str) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (sid,)
    ).fetchall()
    return [_row_to_message(r) for r in rows]


def q_get_message(con: sqlite3.Connection, mid: int) -> dict | None:
    row = con.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
    return _row_to_message(row) if row else None


def q_add_message(con: sqlite3.Connection, sid: str, msg: dict) -> dict:
    cur = con.execute(
        "INSERT INTO messages (session_id, role, type, text, in_context, attachments) VALUES (?, ?, ?, ?, ?, ?)",
        (
            sid,
            msg["role"],
            msg.get("type", "message"),
            msg.get("text", ""),
            1 if msg.get("in_context", True) else 0,
            json.dumps(msg.get("attachments", [])),
        ),
    )
    con.execute("UPDATE sessions SET ts = ? WHERE id = ?", (_now_ms(), sid))
    return q_get_message(con, cur.lastrowid)


def q_update_message(con: sqlite3.Connection, mid: int, patch: dict) -> dict | None:
    msg = q_get_message(con, mid)
    if not msg:
        return None
    if patch.get("in_context") is not None:
        con.execute("UPDATE messages SET in_context = ? WHERE id = ?", (1 if patch["in_context"] else 0, mid))
    if patch.get("text") is not None:
        con.execute("UPDATE messages SET text = ? WHERE id = ?", (patch["text"], mid))
    return q_get_message(con, mid)


def q_delete_message(con: sqlite3.Connection, mid: int) -> None:
    con.execute("DELETE FROM messages WHERE id = ?", (mid,))


# --- User Settings ---


def q_get_user_settings(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT key, value FROM user_settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def q_set_user_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO user_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
