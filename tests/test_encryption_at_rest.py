"""Integrations-Tests: Verschluesselung at rest der per-user Datenbanken.

Die per-user DB (<users_dir>/<uid>.db.enc) darf ausschliesslich als Fernet-Token auf
der Platte liegen: kein Klartext (Session-Namen, Nachrichten, API-Key, Attachment-Inhalt)
darf in den Rohbytes auffindbar sein, und Entschluesseln darf nur mit dem aus Server-Secret
+ E-Mail abgeleiteten Schluessel (app/auth.py:user_identity) gelingen. Damit schuetzt
diese Suite die Persistenzschicht, waehrend die e2e-Tests nur noch die API pruefen.
"""

from __future__ import annotations

import base64
import stat

from app.auth import user_identity
from app.config import load_config
from app.db import crypto

SECRET_SESSION = "TopSecret-Session-Name-9f3e"
SECRET_MESSAGE = "TopSecret-Message-Text-7a1b"
SECRET_API_KEY = "sk-live-test-4c8d"
SECRET_ATTACHMENT = "TopSecret-Anhang-Inhalt-2e5f\n" * 3


def _seed_user_data(client, auth_headers) -> str:
    res = client.post("/api/sessions", json={"name": SECRET_SESSION}, headers=auth_headers)
    assert res.status_code == 201, res.text
    sid = res.json()["id"]
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "text": SECRET_MESSAGE},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    res = client.post("/api/settings/models", json={"api_key": SECRET_API_KEY, "model": "m"}, headers=auth_headers)
    assert res.status_code == 201, res.text
    res = client.post(
        f"/api/sessions/{sid}/attachments",
        files={"file": ("geheim.txt", SECRET_ATTACHMENT.encode(), "text/plain")},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    return sid


def _db_file(config, email: str):
    uid = user_identity(config.secret, email)["uid"]
    return config.users_dir / f"{uid}.db.enc"


def test_per_user_db_is_fernet_token_without_plaintext(client, auth_headers, config):
    _seed_user_data(client, auth_headers)
    raw = _db_file(config, "alice@example.com").read_bytes()
    # Fernet-Tokens beginnen mit Version-Byte 0x80 -> base64 "gAAAAA"
    assert raw.startswith(b"gAAAAA"), "Datei muss ein Fernet-Token sein"
    for secret in (SECRET_SESSION, SECRET_MESSAGE, SECRET_API_KEY, SECRET_ATTACHMENT, "alice@example.com"):
        assert secret.encode() not in raw, f"Klartext im DB-File: {secret!r}"
        # auch base64-kodierte Formen (z. B. Data-URLs von Bildern) duerfen nicht vorkommen
        assert base64.b64encode(secret.encode()) not in raw
        assert base64.urlsafe_b64encode(secret.encode()) not in raw


def test_per_user_db_decryptable_only_with_derived_key(client, auth_headers, config):
    _seed_user_data(client, auth_headers)
    token = _db_file(config, "alice@example.com").read_bytes()

    # korrekter Schluessel (Server-Secret + E-Mail) entschluesselt und enthaelt die Daten
    key = user_identity(config.secret, "alice@example.com")["key"]
    plain = crypto.decrypt(crypto.normalize_key(key), token)
    assert plain.startswith(b"SQLite format 3")
    assert SECRET_MESSAGE.encode() in plain
    assert SECRET_SESSION.encode() in plain
    assert SECRET_API_KEY.encode() in plain
    assert SECRET_ATTACHMENT.encode() in plain

    # falsches Server-Secret -> anderer Schluessel -> Entschluesselung schlaegt fehl
    wrong_secret = user_identity("anderes-secret", "alice@example.com")["key"]
    try:
        crypto.decrypt(crypto.normalize_key(wrong_secret), token)
        raise AssertionError("Entschluesselung mit falschem Secret darf nicht gelingen")
    except ValueError:
        pass

    # andere E-Mail -> anderer pro-User-Salt -> anderer Schluessel -> fehlschlag
    wrong_user = user_identity(config.secret, "mallory@example.com")["key"]
    try:
        crypto.decrypt(crypto.normalize_key(wrong_user), token)
        raise AssertionError("Entschluesselung mit fremdem User-Key darf nicht gelingen")
    except ValueError:
        pass


def test_per_user_db_files_are_per_user(client, auth_headers, app, config):
    """Jeder User bekommt eine eigene Datei; fremde Keys oeffnen sie nicht (siehe oben)."""
    _seed_user_data(client, auth_headers)
    from tests.conftest import login_client

    with login_client(app, "bob@example.com") as bob_client:
        res = bob_client.post("/api/sessions", json={"name": "Bobs Session"}, headers={})
        assert res.status_code == 201, res.text
    alice_file = _db_file(config, "alice@example.com")
    bob_file = _db_file(config, "bob@example.com")
    assert alice_file.exists() and bob_file.exists()
    assert alice_file != bob_file
    assert alice_file.read_bytes() != bob_file.read_bytes()


def test_server_secret_file_is_created_with_0600(tmp_path, monkeypatch):
    """Das Server-Secret (.secret, Quelle aller per-user Schluessel) darf nicht
    world-readable sein und landet nie in der persistierten app_config.json."""
    monkeypatch.delenv("LEANCHAT_SECRET", raising=False)
    monkeypatch.setenv("LEANCHAT_DATA_DIR", str(tmp_path / "data"))
    cfg = load_config()
    assert cfg.secret
    secret_file = tmp_path / "data" / ".secret"
    assert secret_file.exists()
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    assert "secret" not in cfg.to_dict(), "to_dict filtert Secrets heraus (keine Secrets at rest)"
