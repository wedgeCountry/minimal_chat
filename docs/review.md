# LeanChat — Project Review

Review of the `main` branch (base: merge of PR #42), with a focus on typing and
validation. The remediation described in the last section is part of the same change.

## Overview

LeanChat is a lean chat UI for OpenAI-compatible endpoints:

- **Backend**: FastAPI (`app/`), uvicorn, per-user **encrypted SQLite** files
  (Fernet, key derived from the server secret + e-mail via Argon2id with a
  per-user salt; legacy SHA-256 keys migrate automatically on next write).
- **Auth**: vendored `user_registry` wheel — registry DB, signed session cookies,
  `/auth` pages (login/register/password/terms/imprint).
- **Generation**: `POST /api/chat` starts a background task (`run_generation`)
  that persists each completed LLM stream block into the per-user DB; the client
  polls `GET /api/sessions/{id}`. Abort races against response-open and every
  chunk read.
- **Frontend**: static vanilla ES modules, no build step, `data-testid` selectors
  for e2e (Playwright).

## Strengths

- **Security posture is solid for the scope**: SSRF protection for user-controlled
  LLM URLs (`LlmUrlValidator`, DNS-resolved, private/loopback/CGNAT blocked unless
  loopback bind or `LEANCHAT_ALLOW_PRIVATE_LLM=1`), CSP/security headers with a
  relaxed CSP only for the `/auth` pages, request-size limits (global + per-upload
  byte cap + per-user storage quota), rate-limited client-log endpoint, upstream
  error bodies never leaked to the client, secrets never persisted at rest
  (`AppConfig.to_dict` filters them, `.secret` file is `0600`).
- **Clean layering**: DB access only via `app/db/database.py`, SSE parsing only via
  `app/services/sse.py`, one place for LLM HTTP (`services/llm.py`), blocking calls
  consistently off the event loop (`asyncio.to_thread`).
- **Good test coverage**: 215 Python unit/integration tests + JS unit tests + e2e;
  CI runs lint, JS tests and pytest on every PR.
- **Docs discipline**: AGENTS.md rules (e.g. env vars documented in `env-example`,
  docs updated in the same commit) are actually followed.

## Findings

### Typing (fixed in this change)

`mypy --strict` was not part of CI and the code had real gaps:

- Internal payloads were plain `dict`: `user: dict` (identity), all DB row helpers
  (`q_*` returned `list[dict]` / `dict | None`), `msg`/`att`/`patch` params,
  `attachments: list[dict[str, Any]]` in the API models.
- Several functions had no annotations at all: all router handlers in
  `sessions.py`, the two middlewares in `main.py` (`call_next`), `read_upload_capped`,
  `resolve_base_url`'s `config` param.
- mypy also surfaced **latent type bugs**: `llm.py` used `res` after `race_abort`
  without narrowing the `Response | None`; `q_add_message` passed
  `cur.lastrowid` (`int | None`) unchecked; `resolve_base_url` had a `str | None`
  return path; `update_message` unpacked a possibly-`None` row into `MessageOut`.

### Validation (fixed in this change)

- `AppConfig` was a plain `@dataclass`: no range checks (port, byte limits), and
  `from_dict` silently ignored unknown keys in a hand-edited `app_config.json`.
- API models were already Pydantic, but `attachments` accepted arbitrary dicts and
  `ChatAbortRequest.session_id` / `SessionIn.name` had no length limits.

### Remaining / out of scope

- `tests/` is not under `mypy --strict` (fixtures/helpers are untyped by style);
  mypy covers `app/`, `scripts/` and the root `main.py`.
- The vendored wheels (`user_registry`, `trixie_ai`, `voice_companion`) ship no
  `py.typed`; they are `Any` for mypy via per-module overrides.
- `ChatMessage.content` stays `Any` — it mirrors the LLM wire format (string or
  content-part list).

## Changes in this PR

1. **`app/types.py` (new)**: TypedDicts for the internal dict data —
   `UserIdentity`, `SessionRow`, `MessageRow`, `MessageInput`, `AttachmentContent`,
   `AttachmentRow`, `StreamBlock`. Dict access (`user["uid"]`) is unchanged, but keys
   and value types are now checked.
2. **Full typing of `app/`**: every function signature annotated (routers,
   middlewares, services, db helpers); the latent bugs above fixed
   (`race_abort` results narrowed, `lastrowid` checked, `resolve_base_url` fallback
   asserted non-`None`, `update_message` guards the `None` row).
3. **Pydantic at the boundaries**:
   - `AppConfig` is now a `BaseModel` (`extra="forbid"`) with constraints
     (`port` 1–65535, byte limits ≥ 1, non-empty host/app name); the loopback →
     `allow_private_llm` rule moved to a `model_validator`. Env reading stays
     explicit in `load_config` (a passed config object is never overridden by env).
   - `attachments` in `MessageIn`/`MessagePatch` are now `AttachmentRef` models
     (`id` required, extra keys like `type` preserved); `SessionIn.name` and
     `ChatAbortRequest.session_id` got length limits; DB rows are re-validated via
     `MessageOut.model_validate(...)` on the way out.
4. **mypy in CI + docs**: `[tool.mypy]` strict config in `pyproject.toml`
   (`files = ["app", "scripts", "main.py"]`, overrides for the untyped vendored
   wheels), `mypy` added to the dev extras, new CI job `typecheck`, testing
   commands documented in `AGENTS.md`/`README.md`.

## Verification

- `python3 -m pytest` — 215 passed (+ new validation tests), 33 e2e deselected
- `python3 -m ruff check app tests` — clean
- `python3 -m mypy` — `Success: no issues found in 30 source files` (strict)
- `npm test` — JS unit tests pass
