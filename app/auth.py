"""Login/Registrierung ueber die externe user_registry-Bibliothek.

Integration wie in docs/user_registry_implementation_guidelines.md beschrieben:
eigene Registry-DB (plain SQLite, von der Bibliothek verwaltet), signierte
Session-Cookies (``auth_session``) ueber ``mount_auth`` sowie die
professionellen Auth-Seiten unter ``/auth`` (Login, Registrieren,
Passwort aendern/loeschen, AGB, Impressum). Die lokalen User-Daten
(verschluesselte per-user DBs) werden pro E-Mail ueber ``user_identity``
zugeordnet - es gibt keine lokale User-Tabelle (siehe db/database.py).
"""

from __future__ import annotations

import base64
import hashlib

from argon2.low_level import Type, hash_secret_raw
from fastapi import FastAPI, Response

from user_registry import UserRegistry
from user_registry.web import AuthConfig, mount_auth
from user_registry.web.security import make_serializer

from .config import REPO_ROOT, AppConfig

TERMS_VERSION = "2025-01"


def init_auth(app: FastAPI, cfg: AppConfig) -> AuthConfig:
    registry = UserRegistry(cfg.registry_path)
    registry.init_db()
    _, config = mount_auth(
        app,
        registry,
        prefix="/auth",
        secret_key=cfg.secret,
        terms={"version": TERMS_VERSION},
        imprint={"document": str(REPO_ROOT / "docs" / "impressum.html")},
        login_redirect="/",
        # Session-Cookie nur mit Secure-Flag, sobald der Server selbst per TLS laeuft
        cookie_secure=cfg.ssl_certfile is not None,
    )
    app.state.registry = registry
    app.state.auth_config = config
    app.state.auth_serializer = make_serializer(config)
    return config


def clear_auth_cookie(response: Response, app: FastAPI) -> None:
    config: AuthConfig = app.state.auth_config
    response.delete_cookie(config.session_cookie)


def display_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0].strip()
    return local or email


def _derive_key(secret: str, email: str) -> str:
    """Argon2id mit pro-User-Salt (deterministisch aus der E-Mail abgeleitet)."""
    salt = hashlib.sha256(email.encode("utf-8")).digest()[:16]
    raw = hash_secret_raw(
        secret.encode("utf-8"), salt,
        time_cost=2, memory_cost=8192, parallelism=1, hash_len=32, type=Type.ID,
    )
    return base64.urlsafe_b64encode(raw).decode("ascii")


def legacy_key(secret: str, email: str) -> str:
    """Vorgaenger-Ableitung (unsalted SHA-256) - nur fuer die Migration bestehender DBs."""
    digest = hashlib.sha256(f"{secret}:{email.strip().lower()}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


_identity_cache: dict[tuple[str, str], dict] = {}


def user_identity(secret: str, email: str) -> dict:
    """Leitet die lokale User-Identitaet (uid + Schluessel der per-user DB)
    aus dem Server-Secret und der E-Mail ab. Deterministisch und stateless:
    gleiche E-Mail + gleiches Secret => gleiche per-user DB, ohne dass eine
    lokale User-Tabelle gefuehrt werden muss. Der Schluessel wird per Argon2id
    mit pro-User-Salt abgeleitet (teuer, daher pro (secret, email) gecacht);
    ``legacy_key`` traegt die alte SHA-256-Ableitung fuer die Re-Verschluesselung
    bestehender DBs (siehe db/database.py)."""
    email = email.strip().lower()
    cache_key = (secret, email)
    cached = _identity_cache.get(cache_key)
    if cached is not None:
        return dict(cached)
    uid = hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
    identity = {
        "uid": uid,
        "email": email,
        "username": display_name_from_email(email),
        "key": _derive_key(secret, email),
        "legacy_key": legacy_key(secret, email),
    }
    if len(_identity_cache) > 256:
        _identity_cache.clear()
    _identity_cache[cache_key] = identity
    return dict(identity)
