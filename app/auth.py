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

import hashlib
import json
from http.cookies import SimpleCookie

from fastapi import FastAPI, Request, Response

from user_registry import UserRegistry
from user_registry.web import AuthConfig, mount_auth
from user_registry.web.security import make_serializer, read_session

from .config import REPO_ROOT, AppConfig

TERMS_VERSION = "2025-01"

# Passwort des Auto-Login-Testusers (nur Loopback, LEANCHAT_AUTO_LOGIN=1)
AUTO_LOGIN_PASSWORD = "Test-1234"


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
        cookie_secure=cfg.ssl_certfile is not None,
    )
    app.state.registry = registry
    app.state.auth_config = config
    app.state.auth_serializer = make_serializer(config)
    install_session_key_store(app)
    return config


def clear_auth_cookie(response: Response, app: FastAPI) -> None:
    config: AuthConfig = app.state.auth_config
    response.delete_cookie(config.session_cookie)


def display_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0].strip()
    return local or email


_identity_cache: dict[tuple[str, str], dict] = {}


def user_identity(email: str, password: str, keystore) -> dict:
    """User-Identitaet (uid + Schluessel der per-user DB) aus E-Mail und Passwort.

    Der DB-Schluessel (DEK) ist zufaellig pro User und liegt nur gewrappt im Keystore
    (KEK = Argon2id(password, salt)); er wird ausschliesslich beim Login/Registrieren
    ausgepackt und serverseitig pro Session-Cookie gehalten (``install_session_key_store``)
    - nie im Cookie, nie at rest. Ohne das Passwort des Users ist die DB nicht
    entschluesselbar (auch nicht fuer den Admin). Beim ersten Login ohne Keystore-Eintrag
    wird ein neuer DEK angelegt. Falsches Passwort bei vorhandenem Eintrag -> ValueError.
    """
    email = email.strip().lower()
    # Cache-Schluessel ueber Passwort-Digest, damit das Klartext-Passwort nicht im Cache landet
    cache_key = (email, hashlib.sha256(password.encode("utf-8")).hexdigest())
    cached = _identity_cache.get(cache_key)
    if cached is not None:
        return dict(cached)
    uid = hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
    dek = keystore.unwrap(email, password)
    if dek is None:
        if keystore.get(email) is not None:
            raise ValueError("Falsches Passwort oder beschaedigter Keystore-Eintrag")
        dek = keystore.create(email, uid, password)
    identity = {"uid": uid, "email": email, "username": display_name_from_email(email), "key": dek}
    if len(_identity_cache) > 256:
        _identity_cache.clear()
    _identity_cache[cache_key] = identity
    return dict(identity)


def _session_token_from_response(app: FastAPI, response: Response) -> str | None:
    config: AuthConfig = app.state.auth_config
    for header in response.headers.getlist("set-cookie"):
        jar = SimpleCookie()
        try:
            jar.load(header)
        except Exception:
            continue
        morsel = jar.get(config.session_cookie)
        if morsel:
            return morsel.value
    return None


def install_session_key_store(app: FastAPI) -> None:
    """Hält die beim Login ausgepackten DEKs serverseitig pro Session-Cookie im Speicher.

    Login/Registrierung/Passwort-Aenderung laufen über die user_registry-Endpunkte (die
    Bibliothek bietet keine Hooks); dieses Middleware liest die Passwoerter aus deren
    Request-Bodies und reagiert auf erfolgreiche Antworten (200):
    - login/register: DEK per Passwort aus dem Keystore auspacken (bzw. anlegen) und die
      Identität unter dem gesetzten Session-Cookie ablegen
    - change-password: DEK unter dem neuen Passwort re-wrappen (DB bleibt lesbar), alte
      Session verwerfen
    - reset-password (Token, ohne altes Passwort): Keystore-Eintrag löschen - nächster Login
      legt einen frischen DEK an (alte DB bleibt orphaned; ohne altes Passwort nicht anders
      moeglich, absichtlich kein Admin-Escrow)
    - delete: Keystore-Eintrag und per-user DB-Datei löschen
    - logout: Session-Schlüssel verwerfen
    Ohne serverseitig hinterlegten Schlüssel (z. B. nach Server-Neustart) gibt es keinen
    DB-Zugriff (401 in ``deps.get_current_user``).
    """
    app.state.session_keys = {}

    async def _read_json(request: Request) -> dict:
        try:
            return json.loads(await request.body())
        except Exception:
            return {}

    def _session_email(request: Request) -> str | None:
        # Ohne Epoch-Pruefung: nach change-password/delete ist die Session serverseitig
        # bereits ungueltig (Epoch gebumpt), das Cookie traegt die E-Mail aber noch
        return read_session(request, app.state.auth_config, app.state.auth_serializer)

    def _session_email_unchecked(request: Request) -> str | None:
        raw = request.cookies.get(app.state.auth_config.session_cookie)
        if not raw:
            return None
        try:
            data = app.state.auth_serializer.loads(raw, max_age=app.state.auth_config.session_max_age)
        except Exception:
            return None
        email = data.get("email") if isinstance(data, dict) else None
        return email if isinstance(email, str) else None

    @app.middleware("http")
    async def _capture_session_key(request: Request, call_next):
        path = request.url.path
        if request.method == "POST" and path in ("/auth/api/login", "/auth/api/register"):
            payload = await _read_json(request)
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            response = await call_next(request)
            token = _session_token_from_response(app, response) if response.status_code == 200 else None
            if token and email and password:
                app.state.session_keys[token] = user_identity(email, password, app.state.keystore)
            return response
        if request.method == "POST" and path == "/auth/api/change-password":
            payload = await _read_json(request)
            old_password = str(payload.get("old_password", ""))
            new_password = str(payload.get("new_password", ""))
            response = await call_next(request)
            if response.status_code == 200:
                email = _session_email_unchecked(request)
                if email and old_password and new_password:
                    app.state.keystore.rewrap(email, old_password, new_password)
                token = request.cookies.get(app.state.auth_config.session_cookie)
                if token:
                    app.state.session_keys.pop(token, None)  # Endpoint loescht die Session
            return response
        if request.method == "POST" and path == "/auth/api/reset-password":
            payload = await _read_json(request)
            email = str(payload.get("email", "")).strip().lower()
            response = await call_next(request)
            if response.status_code == 200 and email:
                app.state.keystore.delete(email)
            return response
        if request.method == "POST" and path == "/auth/api/delete":
            response = await call_next(request)
            if response.status_code == 200:
                email = _session_email_unchecked(request)
                if email:
                    app.state.keystore.delete(email)
                    uid = hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
                    try:
                        (app.state.db.users_dir / f"{uid}.db.enc").unlink(missing_ok=True)
                    except OSError:
                        pass
            return response
        if request.method == "POST" and path in ("/auth/api/logout", "/api/auth/logout"):
            response = await call_next(request)
            token = request.cookies.get(app.state.auth_config.session_cookie)
            if token:
                app.state.session_keys.pop(token, None)
            return response
        return await call_next(request)
