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


@pytest.fixture(scope="session")
def mock_llm_port():
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
def server_port(tmp_path_factory, mock_llm_port):
    data_dir = tmp_path_factory.mktemp("leanchat-e2e-data")
    port = _free_port()
    env = dict(
        os.environ,
        LEANCHAT_DATA_DIR=str(data_dir),
        LEANCHAT_SECRET="e2e-secret",
        LEANCHAT_API_KEY="e2e-api-key",
        LEANCHAT_LLM_BASE=f"http://127.0.0.1:{mock_llm_port}/v1",
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
