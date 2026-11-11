from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth import init_auth
from .config import AppConfig, bootstrap_env, load_config
from .db.database import Database
from .routers import auth, chat, sessions, settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

bootstrap_env()


def create_app(
    config: AppConfig | None = None,
    data_dir: str | os.PathLike | None = None,
    secret: str | None = None,
) -> FastAPI:
    cfg = config or load_config(data_dir=data_dir, secret=secret)
    cfg.save()
    app = FastAPI(title="LeanChat")
    app.state.config = cfg
    app.state.db = Database(cfg.data_dir, cfg.users_dir)
    init_auth(app, cfg)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(settings.router)
    app.include_router(chat.router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
