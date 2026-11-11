"""Einzige Stelle mit Zugriff auf die SQLite-Datenbanken.

Pro User existiert genau eine verschluesselte SQLite-Datei unter
``<data_dir>/users/<uid>.db.enc``. Der Inhalt wird mit dem einmalig
clientseitig generierten Schluessel des Users (Fernet) verschluesselt.
Der Benutzerindex (``users.index.enc``) liegt mit dem Server-Secret
verschluesselt vor und enthaelt u. a. den Schluessel jedes Users.

Zum Zugriff wird die Datei entschluesselt, in eine In-Memory-Datenbank
 geladen (Schema aus ``schema.sql``), und nach dem Schreiben wieder
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
from typing import Any, Iterator

from .. import security
from . import crypto

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

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


class Database:
    """Verwaltet den Benutzerindex und die verschluesselten per-user Datenbanken."""

    def __init__(self, data_dir: Path, secret: str):
        self.data_dir = Path(data_dir)
        self.secret = secret
        self.users_dir = self.data_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "users.index.enc"
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._index_key = base64.urlsafe_b64encode(digest)

    def _index_key_bytes(self) -> bytes:
        return self._index_key

    def _load_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        raw = crypto.decrypt(self._index_key_bytes(), self.index_path.read_bytes())
        return json.loads(raw.decode("utf-8"))

    def _save_index(self, users: list[dict]) -> None:
        token = crypto.encrypt(self._index_key_bytes(), json.dumps(users).encode("utf-8"))
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_bytes(token)
        tmp.replace(self.index_path)

    def create_user(self, username: str, password: str, key_b64: str | None = None) -> dict:
        with _lock:
            users = self._load_index()
            if any(u["username"] == username for u in users):
                raise ValueError("Benutzername bereits vergeben")
            salt = security.new_salt()
            user = {
                "uid": _new_uid(),
                "username": username,
                "salt": base64.b64encode(salt).decode("ascii"),
                "verifier": security.hash_password(password, salt),
                "key": key_b64 or crypto.new_key(),
            }
            crypto.normalize_key(user["key"])
            users.append(user)
            self._save_index(users)
            self._init_user_db(user)
            return user

    def verify_login(self, username: str, password: str) -> dict | None:
        user = self.get_user(username)
        if not user:
            return None
        if not security.verify_password(password, user["salt"], user["verifier"]):
            return None
        return user

    def get_user(self, username: str) -> dict | None:
        with _lock:
            return next((u for u in self._load_index() if u["username"] == username), None)

    def get_user_by_id(self, uid: str) -> dict | None:
        with _lock:
            return next((u for u in self._load_index() if u["uid"] == uid), None)

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


# --- Settings ---


def q_get_settings(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def q_set_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
