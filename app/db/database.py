"""Einzige Stelle mit Zugriff auf die SQLite-Datenbanken.

Zwei Daten:

- **User Registry** (``<data_dir>/user_registry.db``): Login-Credentials
  aller User; wird von der externen ``user_registry``-Bibliothek verwaltet
  (siehe app/auth.py) und liegt bewusst getrennt von den App-Daten.
- **Pro-User-Datenbank** (``<data_dir>/users/<uid>.db.enc``): Sessions,
  Messages und ``user_settings`` (Schema: ``schema.sql``), verschluesselt
  mit einem Schluessel, der aus dem Server-Secret und der E-Mail abgeleitet
  wird (``app/auth.py:user_identity``) - es gibt keine lokale User-Tabelle.

Zum Zugriff auf eine per-user DB wird die jeweilige Datei entschluesselt,
in eine In-Memory-Datenbank geladen und nach dem Schreiben wieder
verschluesselt persistiert.
"""

from __future__ import annotations

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


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_uid() -> str:
    return secrets.token_hex(8)


def _row_to_message(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "type": row["type"],
        "text": row["text"],
        "in_context": bool(row["in_context"]),
        "attachments": json.loads(row["attachments"] or "[]"),
        # created_at hat Sekundenaufloesung; als ms-Ts fuer die clientseitige Sortierung
        "ts": row["created_at"] * 1000,
    }


def _row_to_session(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "ts": row["ts"], "generating": bool(row["generating"])}


class Database:
    """Die verschluesselten per-user Datenbanken.

    Die Login-Credentials liegen nicht hier, sondern in der externen User
    Registry (app/auth.py); die User-Identitaet (uid + Schluessel der
    per-user DB) wird aus Server-Secret und E-Mail abgeleitet.
    """

    def __init__(
        self,
        data_dir: Path,
        users_dir: Path | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir = Path(users_dir) if users_dir else self.data_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock_for(self, user: dict) -> threading.RLock:
        """Pro-User-Sperre: gleichzeitige Zugriffe verschiedener User blockieren sich nicht."""
        key = str(self._db_path(user))
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    def _db_path(self, user: dict) -> Path:
        return self.users_dir / f"{user['uid']}.db.enc"

    def _write_encrypted(self, user: dict, plain: bytes) -> None:
        key = crypto.normalize_key(user["key"])
        token = crypto.encrypt(key, plain)
        path = self._db_path(user)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(token)
        tmp.replace(path)

    @contextmanager
    def user_db(self, user: dict) -> Iterator[sqlite3.Connection]:
        """Entschluesselte In-Memory-Sicht auf die SQLite-Datei eines Users.

        Zurueckgeschrieben (verschluesselt persistiert) wird nur, wenn sich
        tatsaechlich etwas geaendert hat (``total_changes``); reine
        Lesezugriffe erzeugen kein Datei-I/O.
        """
        with self._lock_for(user):
            path = self._db_path(user)
            con = sqlite3.connect(":memory:")
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            try:
                if path.exists():
                    token = path.read_bytes()
                    plain = None
                    last_error: ValueError | None = None
                    # Primaeren (Argon2id-)Schluessel versuchen, bei Bedarf den
                    # Legacy-Schluessel (alte SHA-256-Ableitung): erfolgreiche
                    # Migration wird beim naechsten Schreibzugriff mit dem
                    # neuen Schluessel persistiert.
                    for key_b64 in (user.get("key"), user.get("legacy_key")):
                        if not key_b64:
                            continue
                        try:
                            plain = crypto.decrypt(crypto.normalize_key(key_b64), token)
                            break
                        except ValueError as exc:
                            last_error = exc
                    if plain is None:
                        raise last_error or ValueError("Entschluesselung fehlgeschlagen")
                    con.deserialize(plain)
                con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                # Migration fuer bestehende DBs: generating-Spalte nachziehen
                cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)").fetchall()}
                if "generating" not in cols:
                    con.execute("ALTER TABLE sessions ADD COLUMN generating INTEGER NOT NULL DEFAULT 0")
                changes_before = con.total_changes
                yield con
                if con.total_changes > changes_before:
                    con.commit()
                    self._write_encrypted(user, con.serialize())
            finally:
                con.close()


# --- Sessions ---


def q_list_sessions(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("SELECT id, name, ts, generating FROM sessions ORDER BY ts DESC").fetchall()
    return [_row_to_session(r) for r in rows]


def q_create_session(con: sqlite3.Connection, name: str) -> dict:
    sid = _new_uid()
    ts = _now_ms()
    con.execute("INSERT INTO sessions (id, name, ts) VALUES (?, ?, ?)", (sid, name, ts))
    return {"id": sid, "name": name, "ts": ts}


def q_get_session(con: sqlite3.Connection, sid: str) -> dict | None:
    row = con.execute("SELECT id, name, ts, generating FROM sessions WHERE id = ?", (sid,)).fetchone()
    return _row_to_session(row) if row else None


def q_rename_session(con: sqlite3.Connection, sid: str, name: str) -> None:
    con.execute("UPDATE sessions SET name = ? WHERE id = ?", (name, sid))


def q_delete_session(con: sqlite3.Connection, sid: str) -> None:
    con.execute("DELETE FROM sessions WHERE id = ?", (sid,))


def q_set_generating(con: sqlite3.Connection, sid: str, on: bool) -> None:
    con.execute("UPDATE sessions SET generating = ? WHERE id = ?", (1 if on else 0, sid))


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
    if patch.get("attachments") is not None:
        con.execute("UPDATE messages SET attachments = ? WHERE id = ?", (json.dumps(patch["attachments"]), mid))
    return q_get_message(con, mid)


def q_delete_message(con: sqlite3.Connection, mid: int) -> None:
    con.execute("DELETE FROM messages WHERE id = ?", (mid,))


def q_delete_messages_after(con: sqlite3.Connection, sid: str, mid: int) -> int:
    # ids sind autoincrement -> id > mid ist die chronologische Reihenfolge der Session
    cur = con.execute("DELETE FROM messages WHERE session_id = ? AND id > ?", (sid, mid))
    return cur.rowcount


# --- Attachments ---


def _row_to_attachment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "name": row["name"],
        "mime": row["mime"],
        "kind": row["kind"],
        "size": row["size"],
        "content": row["content"],
    }


def q_add_attachment(con: sqlite3.Connection, sid: str, att: dict) -> dict:
    cur = con.execute(
        "INSERT INTO attachments (session_id, name, mime, kind, size, content) VALUES (?, ?, ?, ?, ?, ?)",
        (sid, att["name"], att["mime"], att["kind"], att["size"], att["content"]),
    )
    row = con.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_attachment(row)


def q_get_session_attachments(con: sqlite3.Connection, sid: str) -> list[dict]:
    rows = con.execute("SELECT * FROM attachments WHERE session_id = ? ORDER BY id ASC", (sid,)).fetchall()
    return [_row_to_attachment(r) for r in rows]


# --- User Settings ---


def q_get_user_settings(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT key, value FROM user_settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def q_set_user_setting(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO user_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
