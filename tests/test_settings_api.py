from __future__ import annotations

import re

from app.config import REPO_ROOT
from app.services.settings import BOOL_SETTINGS

DEFAULTS = {
    "default_model_id": "",
    "system_prompt": "",
    "theme": "light",
    **BOOL_SETTINGS,
    "speech_mode": "server",
}


def test_default_settings(client, auth_headers):
    res = client.get("/api/settings", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == DEFAULTS


def test_default_model_id_roundtrip_and_validation(client, auth_headers):
    """default_model_id zeigt auf ein llm_models-Tile; ungueltige IDs werden abgelehnt."""
    created = client.post(
        "/api/settings/models",
        json={"provider": "Lokal", "host": "192.168.1.10", "port": "8000", "model": "gpt-x"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    mid = created.json()["id"]
    # erstes Tile wird automatisch zum Standard
    assert client.get("/api/settings", headers=auth_headers).json()["default_model_id"] == str(mid)

    res = client.put("/api/settings", json={"theme": "dark", "default_model_id": str(mid)}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["default_model_id"] == str(mid)
    assert res.json()["theme"] == "dark"
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["default_model_id"] == str(mid)
    assert "api_key" not in got

    assert client.put("/api/settings", json={"default_model_id": "999"}, headers=auth_headers).status_code == 422
    assert client.put("/api/settings", json={"default_model_id": "abc"}, headers=auth_headers).status_code == 422
    assert client.get("/api/settings", headers=auth_headers).json()["default_model_id"] == str(mid)


def test_boolean_display_settings_roundtrip(client, auth_headers):
    res = client.put(
        "/api/settings",
        json={
            "bubbles_deletable": False,
            "bubbles_checkable": False,
            "bubbles_speaker": False,
            "bubbles_minimal": True,
            "show_system_prompt": False,
            "show_tool_output": False,
            "show_reasoning": False,
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["bubbles_deletable"] is False
    assert body["bubbles_checkable"] is False
    assert body["bubbles_speaker"] is False
    assert body["bubbles_minimal"] is True
    assert body["show_reasoning"] is False
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["bubbles_deletable"] is False
    assert got["bubbles_checkable"] is False
    assert got["bubbles_speaker"] is False
    assert got["bubbles_minimal"] is True
    assert got["show_system_prompt"] is False
    assert got["show_tool_output"] is False
    assert got["show_reasoning"] is False


def test_legacy_user_setting_keys_fall_back_to_default(client, auth_headers, app):
    """Umbenannte alte Schluessel (bubbles_user_*) werden nicht mehr gelesen:
    Default greift (bubbles_checkable/bubbles_deletable default False)."""
    from app.auth import user_identity
    from app.db import database as dbq

    db = app.state.db
    user = user_identity(app.state.config.secret, "alice@example.com")
    with db.user_db(user) as con:
        dbq.q_set_user_setting(con, "bubbles_user_checkable", "0")
        dbq.q_set_user_setting(con, "bubbles_user_deletable", "0")
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["bubbles_checkable"] is False
    assert got["bubbles_deletable"] is False


def test_system_prompt_roundtrip_and_clear(client, auth_headers):
    res = client.put("/api/settings", json={"system_prompt": "Sei freundlich."}, headers=auth_headers)
    assert res.json()["system_prompt"] == "Sei freundlich."
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["system_prompt"] == "Sei freundlich."
    client.put("/api/settings", json={"system_prompt": ""}, headers=auth_headers)
    assert client.get("/api/settings", headers=auth_headers).json()["system_prompt"] == ""


def test_speech_mode_roundtrip(client, auth_headers):
    for mode in ("system", "server", "none"):
        res = client.put("/api/settings", json={"speech_mode": mode}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["speech_mode"] == mode
        got = client.get("/api/settings", headers=auth_headers).json()
        assert got["speech_mode"] == mode


def test_speech_mode_rejects_invalid_value(client, auth_headers):
    res = client.put("/api/settings", json={"speech_mode": "telepathy"}, headers=auth_headers)
    assert res.status_code == 422
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["speech_mode"] == "server"


def test_settings_require_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings", json={}).status_code == 401
    assert client.get("/api/settings/models").status_code == 401
    assert client.post("/api/settings/models", json={}).status_code == 401
    assert client.post("/api/settings/models/test", json={}).status_code == 401


def test_frontend_bool_setting_keys_match_backend():
    """static/js/settingsKeys.js muss zu BOOL_SETTINGS passen (Single Source of Truth)."""
    js = (REPO_ROOT / "static" / "js" / "settingsKeys.js").read_text(encoding="utf-8")
    keys_block, defaults_block = js.split("export const BOOL_SETTING_DEFAULTS")
    keys = re.findall(r'"([a-z_]+)"', keys_block)
    assert keys == list(BOOL_SETTINGS)
    for key, default in BOOL_SETTINGS.items():
        assert re.search(rf"{re.escape(key)}:\s*{'true' if default else 'false'}\b", defaults_block), key


def test_frontend_session_setting_keys_match_backend():
    """static/js/settingsKeys.js: SESSION_SETTING_KEYS muss zu SESSION_SETTING_KEYS im Backend passen."""
    from app.services.settings import SESSION_SETTING_KEYS

    js = (REPO_ROOT / "static" / "js" / "settingsKeys.js").read_text(encoding="utf-8")
    block = js.split("export const SESSION_SETTING_KEYS")[1].split("]")[0]
    keys = re.findall(r'"([a-z_]+)"', block)
    assert keys == list(SESSION_SETTING_KEYS)
