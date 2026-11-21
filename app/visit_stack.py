from __future__ import annotations

import hashlib
from collections import deque
from typing import Optional

from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from user_registry.web.security import read_session

AUTH_ENTRY_PATHS = frozenset({"/auth/login", "/auth/register", "/auth/forgot-password"})
FALLBACK_TARGET = "/"


class VisitStackStore:
    """Page-visit stacks, keyed by session (SHA-256 of the signed session cookie).

    Top of a stack is the last visited page. Bounded by ``max_size``: when full,
    the oldest entry is dropped. In-memory only - a server restart empties all
    stacks; a session's entry is removed on logout.
    """

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._stacks: dict[str, deque[str]] = {}

    @staticmethod
    def key_for(cookie_value: str) -> str:
        return hashlib.sha256(cookie_value.encode("utf-8")).hexdigest()

    def push(self, key: str, path: str) -> None:
        stack = self._stacks.setdefault(key, deque(maxlen=self._max_size))
        if not stack or stack[-1] != path:
            stack.append(path)

    def top(self, key: str) -> Optional[str]:
        stack = self._stacks.get(key)
        return stack[-1] if stack else None

    def drop(self, key: str) -> None:
        self._stacks.pop(key, None)

    def __len__(self) -> int:
        return len(self._stacks)


def session_key(request: Request) -> Optional[str]:
    """Stack key of the request's session cookie, None without a cookie."""
    raw = request.cookies.get(request.app.state.auth_config.session_cookie)
    return VisitStackStore.key_for(raw) if raw else None


def _wants_html(request: Request) -> bool:
    """A browser navigation (not fetch()/XHR)."""
    return (
        request.method in ("GET", "HEAD")
        and "text/html" in request.headers.get("accept", "")
        and "x-requested-with" not in request.headers
    )


class VisitStackMiddleware:
    """Pure ASGI middleware (also sees WebSockets, passes them through untouched).

    For a valid session it records visited pages (GET, HTML response) on the
    session's stack and answers browser navigations to auth entry pages (e.g.
    the browser back button landing on /auth/login) with a 303 to the last
    visited page instead of rendering the login screen. Anonymous requests and
    non-navigation requests pass through unchanged.
    """

    def __init__(
        self,
        app: ASGIApp,
        non_page_prefixes: tuple[str, ...] = ("/auth", "/api", "/static"),
        record_fetches: bool = False,
    ) -> None:
        self.app = app
        self.non_page_prefixes = non_page_prefixes
        self.record_fetches = record_fetches

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        is_auth_entry = path in AUTH_ENTRY_PATHS
        is_page = not path.startswith(self.non_page_prefixes) and "." not in path.rsplit("/", 1)[-1]
        if not is_auth_entry and not is_page:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        state = scope["app"].state
        email = read_session(request, state.auth_config, state.auth_serializer)
        raw_cookie = request.cookies.get(state.auth_config.session_cookie)
        if email is None or raw_cookie is None or not state.registry.user_exists(email):
            await self.app(scope, receive, send)
            return
        store: VisitStackStore = state.visit_stacks
        key = VisitStackStore.key_for(raw_cookie)
        if is_auth_entry and _wants_html(request):
            target = store.top(key) or FALLBACK_TARGET
            await RedirectResponse(target, status_code=303)(scope, receive, send)
            return
        if not is_page or not (_wants_html(request) or self.record_fetches):
            await self.app(scope, receive, send)
            return
        query = scope.get("query_string", b"").decode("ascii")
        visited = path + (f"?{query}" if query else "")
        status = 0
        content_type = ""

        async def send_wrapper(message: Message) -> None:
            nonlocal status, content_type
            if message["type"] == "http.response.start":
                status = message["status"]
                for name, value in message["headers"]:
                    if name == b"content-type":
                        content_type = value.decode("latin-1")
            await send(message)

        await self.app(scope, receive, send_wrapper)
        if status == 200 and content_type.startswith("text/html"):
            store.push(key, visited)
