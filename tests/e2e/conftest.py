from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = Path(__file__).resolve().parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return
        except urllib.error.HTTPError:
            return  # Server antwortet (z. B. 404 beim Mock-LLM) -> erreichbar
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Server auf Port {port} nicht erreichbar")


def real_llm_requested() -> bool:
    """Manueller Lauf gegen ein echtes LLM (Opt-in, nie automatisch)."""
    return os.environ.get("LEANCHAT_E2E_REAL_LLM", "").lower() in ("1", "true", "yes")


@pytest.fixture(scope="session")
def mock_llm_port():
    if real_llm_requested():
        yield None  # kein Mock: LEANCHAT_LLM_BASE kommt aus der Umgebung
        return
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mock_llm:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=E2E_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture(scope="session")
def llm_expect(mock_llm_port):
    """Erwartete LLM-Antworten je nach Modus (Mock vs. echtes LLM)."""
    if mock_llm_port is None:
        return {
            "default": None,  # echtes LLM: beliebige nicht-leere Antwort
            "file": "Krokodil-Ledertasche",  # Dateiinhalt muss in der Antwort stehen
            "timeout_ms": 120000,
        }
    return {"default": "Hallo Welt", "file": "Krokodil-Ledertasche", "timeout_ms": 30000}


@pytest.fixture(scope="session")
def server_port(tmp_path_factory, mock_llm_port):
    data_dir = tmp_path_factory.mktemp("leanchat-e2e-data")
    port = _free_port()
    if mock_llm_port is not None:
        llm_base = f"http://127.0.0.1:{mock_llm_port}/v1"
        api_key = "e2e-api-key"
    else:
        # Dedizierte Variablen, damit der Lauf nie versehentlich aus der .env
        # uebernommen wird: explizites Opt-in fuer den manuellen Real-LLM-Lauf.
        llm_base = os.environ.get("LEANCHAT_E2E_LLM_BASE", "")
        api_key = os.environ.get("LEANCHAT_E2E_API_KEY", "")
        if not llm_base:
            pytest.skip("LEANCHAT_E2E_REAL_LLM=1 gesetzt, aber LEANCHAT_E2E_LLM_BASE fehlt in der Umgebung")
    env = dict(
        os.environ,
        LEANCHAT_DATA_DIR=str(data_dir),
        LEANCHAT_SECRET="e2e-secret",
        LEANCHAT_API_KEY=api_key,
        LEANCHAT_LLM_BASE=llm_base,
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture()
def page(server_port):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        pg = context.new_page()
        yield pg
        context.close()
        browser.close()


@pytest.fixture()
def base_url(server_port):
    return f"http://127.0.0.1:{server_port}"
