from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import init_auth
from .config import LOOPBACK_HOSTS, AppConfig, bootstrap_env, is_auto_login_enabled, load_config
from .db.database import Database
from .deps import get_session_email
from .routers import auth, chat, log, meta, sessions, settings, voice

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

bootstrap_env()

logger = logging.getLogger("leanchat")

# /auth-Seiten der user_registry brauchen 'unsafe-inline' (Inline-CSRF-Token)
CSP_APP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
    "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)
CSP_AUTH = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)


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

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            length = request.headers.get("content-length")
            if length:
                try:
                    too_big = int(length) > cfg.max_request_bytes
                except ValueError:
                    return JSONResponse({"detail": "Ungueltiger Content-Length-Header"}, status_code=400)
                if too_big:
                    return JSONResponse(
                        {"detail": f"Request zu gross (Limit {cfg.max_request_bytes} Bytes)"}, status_code=413
                    )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # ueberschreibt die CSP der user_registry (frame-ancestors 'none') bewusst
        response.headers["Content-Security-Policy"] = CSP_AUTH if request.url.path.startswith("/auth") else CSP_APP
        if cfg.ssl_certfile:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(settings.router)
    app.include_router(chat.router)
    app.include_router(log.router)
    app.include_router(meta.router)
    app.include_router(voice.router)

    @app.get("/", include_in_schema=False)
    def root(request: Request) -> Response:
        if get_session_email(request) is None:
            return RedirectResponse("/auth/login", status_code=303)
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
