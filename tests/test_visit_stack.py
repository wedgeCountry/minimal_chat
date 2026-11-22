from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppConfig, load_config
from app.main import create_app
from app.visit_stack import VisitStackStore
from tests.conftest import login_client

HTML = {"Accept": "text/html,application/xhtml+xml"}


def _config(tmp_path, **kwargs) -> AppConfig:
    data = tmp_path / "data"
    return AppConfig(
        data_dir=data,
        secret="test-secret",
        registry_path=data / "user_registry.db",
        users_dir=data / "users",
        default_llm_host="llm.test",
        default_llm_port="",
        default_api_key="test-api-key",
        **kwargs,
    )


def _logged_in(tmp_path, **kwargs) -> tuple[TestClient, object]:
    app = create_app(config=_config(tmp_path, **kwargs))
    return login_client(app), app


def test_store_push_top_drop():
    store = VisitStackStore(max_size=3)
    assert store.top("k") is None
    store.push("k", "/a")
    store.push("k", "/b")
    assert store.top("k") == "/b"
    store.push("k", "/b")  # direkt aufeinanderfolgende Dublette wird nicht gepusht
    assert store.top("k") == "/b"
    store.drop("k")
    assert store.top("k") is None
    assert len(store) == 0


def test_store_cap_drops_oldest():
    store = VisitStackStore(max_size=3)
    for i in range(5):
        store.push("k", f"/p{i}")
    assert store.top("k") == "/p4"
    assert len(store) == 1
    key = VisitStackStore.key_for("cookie")
    store.push(key, "/x")
    assert len(store) == 2


def test_config_default_and_env(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    assert cfg.visit_stack_size == 20
    assert cfg.to_dict()["visit_stack_size"] == 20
    monkeypatch.setenv("LEANCHAT_VISIT_STACK_SIZE", "7")
    monkeypatch.setenv("LEANCHAT_DATA_DIR", str(tmp_path / "envdata"))
    monkeypatch.setenv("LEANCHAT_SECRET", "s")
    assert load_config().visit_stack_size == 7
    with pytest.raises(ValidationError):
        _config(tmp_path, visit_stack_size=0)


def test_anonymous_requests_unchanged(client):
    res = client.get("/auth/login", headers=HTML)
    assert res.status_code == 200
    res = client.get("/", headers=HTML, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/auth/login"


def test_logged_in_auth_entry_redirects_to_fallback_when_stack_empty(tmp_path):
    c, app = _logged_in(tmp_path)
    for page in ("/auth/login", "/auth/register", "/auth/forgot-password"):
        res = c.get(page, headers=HTML, follow_redirects=False)
        assert res.status_code == 303, page
        assert res.headers["location"] == "/"


def test_logged_in_back_to_login_redirects_to_last_visited(tmp_path):
    c, app = _logged_in(tmp_path)
    res = c.get("/", headers=HTML)
    assert res.status_code == 200
    res = c.get("/auth/login", headers=HTML, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/"


def test_visit_records_query_string(tmp_path):
    c, app = _logged_in(tmp_path)
    c.get("/?sid=42", headers=HTML)
    res = c.get("/auth/login", headers=HTML, follow_redirects=False)
    assert res.headers["location"] == "/?sid=42"


def test_fetches_and_api_calls_are_not_recorded(tmp_path):
    c, app = _logged_in(tmp_path)
    res = c.get("/", headers={**HTML, "X-Requested-With": "fetch"})
    assert res.status_code == 200
    assert len(app.state.visit_stacks) == 0
    res = c.get("/api/auth/me")
    assert res.status_code == 200
    assert len(app.state.visit_stacks) == 0


def test_invalid_cookie_gets_login_page_not_redirect(tmp_path):
    c, app = _logged_in(tmp_path)
    c.cookies.clear()
    c.cookies.set("auth_session", "forged-value")
    res = c.get("/auth/login", headers=HTML, follow_redirects=False)
    assert res.status_code == 200


def test_logout_drops_the_session_stack(tmp_path):
    c, app = _logged_in(tmp_path)
    c.get("/", headers=HTML)
    assert len(app.state.visit_stacks) == 1
    res = c.post("/api/auth/logout")
    assert res.status_code == 200
    assert len(app.state.visit_stacks) == 0


def test_stack_size_limit_from_config(tmp_path):
    c, app = _logged_in(tmp_path, visit_stack_size=2)
    assert app.state.config.visit_stack_size == 2
    c.get("/", headers=HTML)
    stack = next(iter(app.state.visit_stacks._stacks.values()))
    assert stack.maxlen == 2


def test_visits_api_requires_auth(client):
    assert client.post("/api/visits", json={"path": "/s/1"}).status_code == 401


def test_visits_api_records_in_app_view_and_redirect_uses_it(tmp_path):
    c, app = _logged_in(tmp_path)
    c.get("/", headers=HTML)
    res = c.post("/api/visits", json={"path": "/s/42"})
    assert res.status_code == 200
    res = c.get("/auth/login", headers=HTML, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/s/42"


def test_session_page_route_serves_spa_and_is_recorded(tmp_path):
    c, app = _logged_in(tmp_path)
    res = c.get("/s/42", headers=HTML)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    stack = next(iter(app.state.visit_stacks._stacks.values()))
    assert "/s/42" in list(stack)
    res = c.get("/auth/login", headers=HTML, follow_redirects=False)
    assert res.headers["location"] == "/s/42"


def test_session_page_route_anonymous_redirects_to_login(client):
    res = client.get("/s/42", headers=HTML, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/auth/login"


def test_session_page_route_serves_app_for_any_s_path(tmp_path):
    # Refresh darf nie 404 liefern ("Detail not found"): auch ungueltige IDs laden
    # die SPA, der Client faellt auf die gespeicherte aktive Session zurueck.
    c, app = _logged_in(tmp_path)
    for path in ("/s/", "/s/unknown-id", "/s/a/b", "/s/42/"):
        res = c.get(path, headers=HTML)
        assert res.status_code == 200, path
        assert "text/html" in res.headers["content-type"]


def test_visits_api_rejects_non_local_paths(tmp_path):
    c, app = _logged_in(tmp_path)
    for bad in ("//evil.example", "https://evil.example", "relativ", "\\\\evil"):
        res = c.post("/api/visits", json={"path": bad})
        assert res.status_code == 422, bad
    assert len(app.state.visit_stacks) == 0


def test_visits_api_respects_stack_limit(tmp_path):
    c, app = _logged_in(tmp_path, visit_stack_size=2)
    c.get("/", headers=HTML)
    for i in (1, 2, 3):
        assert c.post("/api/visits", json={"path": f"/s/{i}"}).status_code == 200
    stack = next(iter(app.state.visit_stacks._stacks.values()))
    assert list(stack) == ["/s/2", "/s/3"]
    res = c.get("/auth/login", headers=HTML, follow_redirects=False)
    assert res.headers["location"] == "/s/3"
