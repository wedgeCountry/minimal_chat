# user_registry integration — setup guide for other FastAPI projects

`user_registry` (private repo `wedgeCountry/user_registry`, vendored as
`vendor/user_registry-0.1.0-py3-none-any.whl`) is a standalone
SQLite-backed registration library with an optional FastAPI web UI.
This document summarizes how nicewand wires it up (`app/auth.py`) and what
to watch out for when integrating it into another FastAPI app.

## How nicewand integrates it

- `init_auth(app)` (called from `create_app()` in `app/main.py`) creates
  `UserRegistry(registry_db)`, calls `init_db()`, then mounts the library UI:
  `mount_auth(app, registry, prefix="/auth", secret_key=..., login_redirect="/",
  terms={"version": "2025-01"}, imprint={"document": "docs/impressum.html"})`.
  This provides the pages `/auth/register`, `/auth/login`, `/auth/forgot-password`,
  `/auth/reset-password`, `/auth/change-password`, `/auth/delete`, `/auth/terms`,
  `/auth/impressum` plus a JSON API under `/auth/api/...`.
- Sessions are itsdangerous-signed `auth_session` cookies (plus an `auth_csrf`
  cookie), signed with the app secret; default max age 7 days.
- `current_user(request)` (`app/auth.py`) reads the cookie via
  `read_session(request, config, serializer)`, verifies the e-mail against the
  registry, and maps it to the **local** `users` table by e-mail
  (case-insensitive), provisioning the local row on first login. App data
  (ascents, comments, images) references that local row; the local table
  stores no credentials.
- Guards in `app/deps.py`: `require_login` (403 without a session) is applied
  to the whole `/views` router; `require_own_profile` restricts profile editing.
  `/` redirects anonymous users to `/auth/login`; `POST /logout` deletes the
  session cookie.

## Setup steps for another FastAPI project

1. **Install the package** — vendored wheel
   rom the private repo:
```bash
pip install -r requirements.txt
pip uninstall -y user-registry
pip install "user-registry[web] @ git+https://github.com/wedgeCountry/user_registry.git@main"
```
   The `[web]` extra is required for `user_registry.web`; the core needs
   `argon2-cffi`.
2. **Create the registry DB separately from the app DB**:
   `registry = UserRegistry(Path("data/user_registry.db")); registry.init_db()`.
   nicewand override: `NICEWAND_REGISTRY_DB` (default `<data dir>/user_registry.db`).
   Back up both DBs; the library also writes an operation log at `<db>.log`
   (e-mails only, never passwords).
3. **Configure a signing secret** — env var or secret file (nicewand:
   `NICEWAND_SECRET_KEY` or `NICEWAND_SECRET_FILE`, default
   `<data dir>/secret_key`). Refuse to start in production without one
   (pattern in `_load_secret_key`, `app/auth.py`).
4. **Mount the auth UI and keep the returned config**:
   `auth_root, config = mount_auth(app, registry, prefix="/auth", secret_key=secret, login_redirect="/", terms={"version": ..., "document": ...}, imprint={"document": ...})`,
   then `serializer = make_serializer(config)`.
5. **Read the session in your own dependency**:
   `email = read_session(request, config, serializer)`, then
   `registry.user_exists(email)`, then map/provision your local user row.
6. **Guard your endpoints** with a `require_login`-style dependency; redirect
   anonymous page requests to `/auth/login`; implement logout by deleting the
   `auth_session` cookie.
7. **Tests**: set the registry-DB and secret env vars in `conftest.py` *before*
   importing the app, and trigger DB init explicitly — `TestClient` does not
   run the ASGI lifespan (see `tests/conftest.py`).

## Pitfalls

- **Access**: the source repo is private — without GitHub access use the
  vendored wheel.
- **Secret handling**: never commit it (`mockdata/`, `productiondata/`,
  `secret_key` are gitignored); the app deliberately refuses to start in
  production without a secret. Rotating the secret invalidates all sessions.
  In testing mode an ephemeral random secret is used, so sessions do not
  survive a restart — fine locally, never in production.
- **Two databases**: credentials live only in the registry DB; the app DB has
  a credential-free `users` table. Losing the registry DB orphans local users.
- **E-mail is the join key**: the local lookup is case-insensitive on e-mail.
  If a registry e-mail changes, a new local user is provisioned and old
  content stays with the old row.
- **Never enable auto-login in production**: nicewand's `NICEWAND_AUTO_LOGIN=1`
  serves every visitor as the seed admin without a session; it defaults on
  only in `testing` mode (`app/paths.py`).
- **Cookie names must stay in sync**: `mount_auth` defaults to
  `auth_session` / `auth_csrf`; with a custom `session_cookie`, logout must
  delete that name.
- **HTTPS is assumed**: production runs behind a TLS-terminating reverse
  proxy with HTTP→HTTPS redirect + HSTS (`app/core.py`); the signed session
  cookie is only safe over HTTPS.
- **Terms/imprint**: `terms["version"]` is recorded at registration; with
  `require_reaccept=True`, bump the version when the terms change or existing
  sessions become invalid. `document` accepts a file path, raw HTML, or URL.
- **Invitation-only registration** exists (`require_invitation=True`) but is
  not enabled here; invite/reset links are single-use, e-mail-bound, expiring
  tokens generated offline via the `create-invitation` / `create-password-reset`
  console scripts (see also `scripts/invitation_link.py`, `scripts/reset_link.py`).
- **Init order**: `UserRegistry` raises `RuntimeError` if used before
  `init_db()` or after `close()`; run the auth init at app creation, before
  serving requests.
- **Pick a non-colliding prefix**: `/auth` is mounted on the root app — avoid
  clashes with your own routes and set `login_redirect` to your landing page.
