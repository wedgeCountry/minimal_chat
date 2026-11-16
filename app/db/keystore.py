"""Keystore: pro User ein zufaelliger DB-Schluessel (DEK), gespeichert als unter einem
passwort-abgeleiteten Schluessel (KEK) gewrapptes Blob (Envelope-Verschluesselung).

At rest genuegt weder das Server-Secret noch Registry/Keystore/DB-Dateien zum
Entschluesseln der per-user DBs - nur das Passwort des Users:
``KEK = Argon2id(password, salt)`` mit zufaelligem pro-User-Salt, ``wrapped = Fernet(KEK)
(DEK)``. Es gibt bewusst keinen Admin-Escrow (keinen serverseitigen Zweitschluessel).

Passwort-Wechsel (``change-password`` mit altem Passwort) re-wrappen den DEK verlustfrei
(``rewrap``); ein Token-Reset hat das alte Passwort nicht und loescht daher den Eintrag
(naechster Login legt einen frischen DEK an - die alte DB bleibt orphaned).
"""

from __future__ import annotations

import base64
import os
import sqlite3
import threading
import time
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.fernet import Fernet, InvalidToken

from . import crypto


class KeyStore:
    """Kleine SQLite-Tabelle (email -> salt + gewrapptes DEK), getrennt von den
    verschluesselten per-user DBs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_keys (
                    email      TEXT PRIMARY KEY,
                    uid        TEXT NOT NULL,
                    salt       TEXT NOT NULL,
                    wrapped    TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _kek(password: str, salt_b64: str) -> bytes:
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        raw = hash_secret_raw(
            password.encode("utf-8"), salt,
            time_cost=2, memory_cost=8192, parallelism=1, hash_len=32, type=Type.ID,
        )
        return base64.urlsafe_b64encode(raw)

    def get(self, email: str) -> dict | None:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT * FROM user_keys WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def create(self, email: str, uid: str, password: str) -> str:
        """Neuen DEK anlegen, gewrappt speichern und den DEK (base64-urlsafe) liefern."""
        salt = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
        dek = crypto.new_key()
        wrapped = Fernet(self._kek(password, salt)).encrypt(crypto.normalize_key(dek))
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO user_keys (email, uid, salt, wrapped, updated_at) VALUES (?, ?, ?, ?, ?)",
                (email, uid, salt, wrapped.hex(), time.time()),
            )
        return dek

    def unwrap(self, email: str, password: str) -> str | None:
        """DEK per Passwort auspacken; ``None`` bei unbekanntem User oder falschem Passwort."""
        entry = self.get(email)
        if entry is None:
            return None
        try:
            dek_b64 = Fernet(self._kek(password, entry["salt"])).decrypt(bytes.fromhex(entry["wrapped"]))
        except InvalidToken:
            return None
        return dek_b64.decode("ascii")

    def rewrap(self, email: str, old_password: str, new_password: str) -> bool:
        """DEK unter dem neuen Passwort neu wrappen (DEK bleibt gleich -> DB bleibt lesbar)."""
        entry = self.get(email)
        if entry is None:
            return False
        dek = self.unwrap(email, old_password)
        if dek is None:
            return False
        salt = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
        wrapped = Fernet(self._kek(new_password, salt)).encrypt(crypto.normalize_key(dek))
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE user_keys SET salt = ?, wrapped = ?, updated_at = ? WHERE email = ?",
                (salt, wrapped.hex(), time.time(), email),
            )
        return True

    def delete(self, email: str) -> None:
        with self._lock, self._connect() as con:
            con.execute("DELETE FROM user_keys WHERE email = ?", (email,))
