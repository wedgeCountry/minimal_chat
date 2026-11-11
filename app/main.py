from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import load_config
from .db.database import Database
from .routers import auth, chat, sessions, settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(data_dir: str | os.PathLike | None = None, secret: str | None = None) -> FastAPI:
    config = load_config(data_dir=data_dir, secret=secret)
    app = FastAPI(title="LeanChat")
    app.state.config = config
    app.state.db = Database(config.data_dir, config.secret)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(settings.router)
    app.include_router(chat.router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
