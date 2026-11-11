from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, ensure_env_file, load_config, load_env_file, parse_env_text
from app.main import create_app


def _make_config(tmp_path) -> AppConfig:
    data = tmp_path / "data"
    return AppConfig(
        data_dir=data,
        secret="cfg-secret",
        registry_path=data / "user_registry.db.enc",
        users_dir=data / "users",
        default_llm_base="http://llm.test/v1",
        default_api_key="cfg-key",
        port=9001,
    )


def test_app_config_file_roundtrip(tmp_path):
    cfg = _make_config(tmp_path)
    path = cfg.save(tmp_path / "out" / "app_config.json")
    loaded = AppConfig.load(path)
    assert loaded.to_dict() == cfg.to_dict()
    assert loaded.data_dir == cfg.data_dir
    assert loaded.port == 9001


def test_create_app_generates_config_file_and_ignores_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANCHAT_API_KEY", "env-key-wins-nicht")
    monkeypatch.setenv("LEANCHAT_MODEL", "env-model")
    cfg = _make_config(tmp_path)
    app = create_app(config=cfg)
    assert app.state.config.default_api_key == "cfg-key"
    assert app.state.config.default_model == "gpt-4o-mini"
    generated = cfg.data_dir / "app_config.json"
    assert generated.exists()
    assert AppConfig.load(generated).secret == "cfg-secret"


def test_parse_env_text_skips_comments_and_quotes():
    values = parse_env_text(
        "# Kommentar\n"
        "\n"
        "LEANCHAT_DATA_DIR=data\n"
        'LEANCHAT_SECRET="abc123"\n'
        "LEANCHAT_PORT=8000\n"
        "kein-schluessel\n"
    )
    assert values == {
        "LEANCHAT_DATA_DIR": "data",
        "LEANCHAT_SECRET": "abc123",
        "LEANCHAT_PORT": "8000",
    }


def test_load_env_file_does_not_override_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("LEANCHAT_PORT", "9999")
    monkeypatch.delenv("LEANCHAT_MODEL", raising=False)
    env = tmp_path / ".env"
    env.write_text("LEANCHAT_PORT=8000\nLEANCHAT_MODEL=gpt-x\n")
    loaded = load_env_file(env)
    assert loaded["LEANCHAT_PORT"] == "8000"
    import os

    assert os.environ["LEANCHAT_PORT"] == "9999"
    assert os.environ["LEANCHAT_MODEL"] == "gpt-x"


def test_ensure_env_file_copies_example_once(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("A=1\n")
    env = tmp_path / ".env"
    ensure_env_file(env, example)
    assert env.read_text() == "A=1\n"
    env.write_text("A=geaendert\n")
    ensure_env_file(env, example)
    assert env.read_text() == "A=geaendert\n"


def test_load_config_uses_env_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANCHAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LEANCHAT_SECRET", "cfg-secret")
    monkeypatch.setenv("LEANCHAT_REGISTRY_PATH", str(tmp_path / "custom" / "registry.db.enc"))
    monkeypatch.setenv("LEANCHAT_USERS_DIR", str(tmp_path / "custom" / "users"))
    monkeypatch.setenv("LEANCHAT_PORT", "9001")
    config = load_config()
    assert config.data_dir == (tmp_path / "data").resolve()
    assert config.secret == "cfg-secret"
    assert config.registry_path == (tmp_path / "custom" / "registry.db.enc").resolve()
    assert config.users_dir == (tmp_path / "custom" / "users").resolve()
    assert config.port == 9001


def test_load_config_defaults_derive_db_paths_from_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANCHAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LEANCHAT_SECRET", "cfg-secret")
    for var in ("LEANCHAT_REGISTRY_PATH", "LEANCHAT_USERS_DIR"):
        monkeypatch.delenv(var, raising=False)
    config = load_config()
    assert config.registry_path == config.data_dir / "user_registry.db.enc"
    assert config.users_dir == config.data_dir / "users"
