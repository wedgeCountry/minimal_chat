from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

PBKDF2_ROUNDS = 200_000
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def new_salt() -> bytes:
    return secrets.token_bytes(16)


def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return base64.b64encode(digest).decode("ascii")


def verify_password(password: str, salt_b64: str, expected_b64: str) -> bool:
    candidate = hash_password(password, base64.b64decode(salt_b64))
    return hmac.compare_digest(candidate, expected_b64)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def make_token(user_id: str, username: str, secret: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    payload = {"uid": user_id, "user": username, "exp": int(time.time()) + ttl}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str, secret: str) -> dict | None:
    try:
        body, sig = token.split(".")
        expected = _b64e(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None
