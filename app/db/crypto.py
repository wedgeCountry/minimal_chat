from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken

KEY_SIZE = 32


def new_key() -> str:
    """Neuer zufaelliger 32-Byte-Schluessel (base64-urlsafe), z. B. clientseitig generiert."""
    return base64.urlsafe_b64encode(os.urandom(KEY_SIZE)).decode("ascii")


def normalize_key(key_b64: str) -> bytes:
    raw = base64.urlsafe_b64decode(key_b64.encode("ascii"))
    if len(raw) != KEY_SIZE:
        raise ValueError("Der Verschluesselungsschluessel muss 32 Bytes haben")
    return base64.urlsafe_b64encode(raw)


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    return Fernet(key).encrypt(plaintext)


def decrypt(key: bytes, token: bytes) -> bytes:
    try:
        return Fernet(key).decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Entschluesselung fehlgeschlagen (falscher Schluessel oder beschaedigte Datei)") from exc
