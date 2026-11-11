"""Einzige Stelle mit Zugriff auf die SQLite-Datenbanken.

Drei Daten:

- **User Registry** (``<data_dir>/user_registry.db``): Login-Credentials
  aller User; wird von der externen ``user_registry``-Bibliothek verwaltet
  (siehe app/auth.py) und liegt bewusst getrennt von den App-Daten.
- **Lokale User-Tabelle** (``<data_dir>/users.db``): credential-freie
  Zuordnung E-Mail -> lokaler User (uid + Verschluesselungsschluessel der
  per-user DB, at rest mit dem Server-Secret verschluesselt).
- **Pro-User-Datenbank** (``<data_dir>/users/<uid>.db.enc``): Sessions,
  Messages und ``user_settings`` (Schema: ``schema.sql``), verschluesselt
  mit dem Schluessel aus der lokalen User-Tabelle.

Zum Zugriff auf eine per-user DB wird die jeweilige Datei entschluesselt,
in eine In-Memory-Datenbank geladen und nach dem Schreiben wieder
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

from . import crypto

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid        TEXT PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    key        TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

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
        # created_at hat Sekundenaufloesung; als ms-Ts fuer die clientseitige Sortierung
        "ts": row["created_at"] * 1000,
    }


def _row_to_session(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "ts": row["ts"]}


def _row_to_local_user(row: sqlite3.Row) -> dict:
    return {"uid": row["uid"], "username": row["email"], "email": row["email"]}


class Database:
    """Lokale User-Tabelle und die verschluesselten per-user Datenbanken.

    Die Login-Credentials liegen nicht hier, sondern in der externen User
    Registry (app/auth.py); die lokale Tabelle speichert nur die Zuordnung
    E-Mail -> uid und den (at rest mit dem Server-Secret verschluesselten)
    Schluessel der per-user DB.
    """

    def __init__(
        self,
        data_dir: Path,
        secret: str,
        users_dir: Path | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secret = secret
        self.users_dir = Path(users_dir) if users_dir else self.data_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.users_db_path = self.data_dir / "users.db"
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._store_key = base64.urlsafe_b64encode(digest)

    @contextmanager
    def _users_con(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            con = sqlite3.connect(self.users_db_path)
            con.row_factory = sqlite3.Row
            try:
                con.executescript(USERS_SCHEMA)
                yield con
                con.commit()
            finally:
                con.close()

    def _encrypt_key(self, key_b64: str) -> str:
        return base64.b64encode(crypto.encrypt(self._store_key, crypto.normalize_key(key_b64))).decode("ascii")

    def _decrypt_key(self, token_b64: str) -> str:
        return crypto.decrypt(self._store_key, base64.b64decode(token_b64)).decode("ascii")

    def create_local_user(self, uid: str, email: str, key_b64: str) -> dict:
        """Lokalen User anlegen (nach erfolgreicher Registrierung in der Registry)."""
        user = {"uid": str(uid), "username": email, "email": email, "key": crypto.normalize_key(key_b64).decode("ascii")}
        with self._users_con() as con:
            con.execute(
                "INSERT INTO users (uid, email, key) VALUES (?, ?, ?)",
                (user["uid"], email.lower(), self._encrypt_key(user["key"])),
            )
        self._init_user_db(user)
        return user

    def get_user_by_email(self, email: str) -> dict | None:
        with self._users_con() as con:
            row = con.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return self._with_key(row) if row else None

    def get_user_by_id(self, uid: str) -> dict | None:
        with self._users_con() as con:
            row = con.execute("SELECT * FROM users WHERE uid = ?", (str(uid),)).fetchone()
        return self._with_key(row) if row else None

    def _with_key(self, row: sqlite3.Row) -> dict:
        user = _row_to_local_user(row)
        user["key"] = self._decrypt_key(row["key"])
        return user

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
    # System-Prompts immer ganz oben, danach chronologisch nach Zeitstempel
    # (id als Tiebreaker, created_at hat nur Sekundenaufloesung).
    rows = con.execute(
        "SELECT * FROM messages WHERE session_id = ? "
        "ORDER BY (role = 'system') DESC, created_at ASC, id ASC",
        (sid,),
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
