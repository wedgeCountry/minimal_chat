from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth import init_auth
from .config import AppConfig, bootstrap_env, is_auto_login_enabled, load_config
from .db.database import Database
from .routers import auth, chat, log, meta, sessions, settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

bootstrap_env()

logger = logging.getLogger("leanchat")

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(
    config: AppConfig | None = None,
    data_dir: str | os.PathLike | None = None,
    secret: str | None = None,
) -> FastAPI:
    cfg = config or load_config(data_dir=data_dir, secret=secret)
    if is_auto_login_enabled():
        # Auto-Login ist ein Test-Hilfsmodus und darf nie auf einem oeffentlich
        # erreichbaren Host laufen.
        if cfg.host not in LOOPBACK_HOSTS:
            raise RuntimeError(
                "LEANCHAT_AUTO_LOGIN=1 ist nur mit Loopback-Host (127.0.0.1/localhost) erlaubt - nie in Produktion"
            )
        logger.warning("LEANCHAT_AUTO_LOGIN ist aktiv - nur fuer Test-/Entwicklungsinstanzen verwenden!")
    cfg.save()
    app = FastAPI(title="LeanChat")
    app.state.config = cfg
    app.state.db = Database(cfg.data_dir, cfg.users_dir)
    init_auth(app, cfg)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(settings.router)
    app.include_router(chat.router)
    app.include_router(log.router)
    app.include_router(meta.router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
