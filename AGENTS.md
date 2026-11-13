# AGENTS.md

## Projekt

LeanChat — schlanker Chat für OpenAI-kompatible Endpunkte (FastAPI-Backend,
verschlüsselte per-user SQLite-Dateien, statisches ES-Module-Frontend ohne Build-Schritt).

## Wichtige Dokumente

- [README.md](README.md) — Architektur, Features, Speicherlayout
- [SPEC.md](SPEC.md) — fachliche Spezifikation
- [docs/rootless_install.md](docs/rootless_install.md) — Playwright/Chromium rootless installieren und die e2e-GUI-Tests (`pytest -m e2e tests/e2e`) ohne root ausführen
- [docs/e2e_real_llm.md](docs/e2e_real_llm.md) — denselben User-Journey-e2e-Test manuell gegen ein echtes LLM laufen lassen (Opt-in via `LEANCHAT_E2E_REAL_LLM=1`, nie automatisch)

## UI-Testbarkeit

Alle UI-Elemente tragen ein eindeutiges `data-testid` (dynamische Elemente mit
id-suffix, z. B. `session-tile-<id>`, `bubble-msg-<id>`). e2e-Tests sollen
ausschließlich diese Selektoren verwenden.


## Testing

- `npm test` — JS-Unit-Tests (node:test)
- `python3 -m pytest` — Python-Unit-Tests (e2e per Marker deselektiert)
- `python3 -m pytest -m e2e tests/e2e` — GUI-Tests mit Playwright gegen Mock-LLM (braucht Chromium, siehe docs/rootless_install.md); gegen echtes LLM siehe docs/e2e_real_llm.md
- `python3 -m ruff check app tests` — Lint (Regel-Set in pyproject.toml, CI-Job `lint`)
- Alle Suiten vor jedem Push laufen lassen: `python3 -m pytest`, `npm test` und `python3 -m ruff check app tests`.

## Rules for contributors

1. **DB-Zugriff nur ueber `app/db/database.py`** (`Database.user_db` + die `q_*`-Helper). `user_db` persistiert nur bei tatsaechlichen Aenderungen; blockierende Aufrufe aus async-Kontexten gehoeren nach `asyncio.to_thread`.
2. **Jeder `/api/*`-Endpunkt braucht `Depends(get_current_user)`** (Ausnahmen: `/api/meta`, `/api/auth/config`). Auto-Login (`LEANCHAT_AUTO_LOGIN=1`) ist nur mit Loopback-Host erlaubt — nie in Produktion.
3. **Serverseitige Generierung:** `POST /api/chat` startet eine Hintergrund-Task (`run_generation`), die den LLM-SSE-Stream in die per-user DB persistiert; der Client pollt `GET /api/sessions/{id}`. Starke Referenzen auf Tasks halten (`_background_tasks`), damit der GC sie nicht killt.
4. **SSE-Parsing nur ueber `parse_sse_data`/`parse_sse_buffer` in `app/services/chat.py`** — keine eigene `data:`-Logik duplizieren.
5. **Datei-Uploads per Multipart** (`UploadFile` in `app/routers/sessions.py`, `FormData` via `api.postForm` im Client); Verarbeitung serverseitig in `app/services/files.py`.
6. **Jedes interaktive UI-Element traegt ein eindeutiges `data-testid`** (kebab-case, `<element>-<context>[-<id>]`); e2e-Tests Adressieren Elemente ausschliesslich ueber diese Selektoren. Test-Aenderungen landen im selben Commit.
7. **Frontend ohne Build-Schritt:** vanilla ES-Module in `static/js/`. Vor dem Einfuegen in `innerHTML` immer `esc()` aus `util.js` verwenden; clientseitig gerenderte Inhalte nur als Diff/Keyed-Update (siehe `renderChat` in `chat.js`).
8. **Secrets nie committen und nicht at rest persistieren:** Server-Secret nur via `LEANCHAT_SECRET`/`.secret`-Datei; die `app_config.json` enthaelt keine Secrets (`AppConfig.to_dict` filtert sie heraus). Per-user DB-Schluessel werden per Argon2id mit pro-User-Salt aus `app/auth.py:user_identity` abgeleitet; bestehende DBs migrieren ueber `legacy_key` automatisch.
9. **Dokumentation im selben Commit aktualisieren:** Aenderungen an Architektur, Endpunkten oder Startbefehlen ziehen Updates in `AGENTS.md`/`README.md`/`SPEC.md` nach — Doc-Drift ist der teuerste Wartungsfehler.
10. **Keep the separation between AGENTS.md and README.md clear.** AGENTS.md is for coding agents and contains technical information and guidelines. README.md shall contain human readable information about the project, about setting up the environment and how to use the app.
11. **SSRF-Schutz:** User-gesteuerte LLM-URLs (Settings + Chat) werden vor jedem Upstream-Request per `validate_llm_base_url` (`app/services/chat.py`) geprueft: nur http/https ohne Credentials; private/Loopback-/Link-Local-/reservierte Ziele sind blockiert, sofern der Server nicht auf Loopback bindet oder `LEANCHAT_ALLOW_PRIVATE_LLM=1` gesetzt ist (`AppConfig.allow_private_llm`). Upstream-Fehler-Bodies werden nie an den Client weitergereicht (nur Statuscode).
12. **DoS-Limits:** Uploads werden gestreamt mit Byte-Cap gelesen (`read_upload_capped` in `app/services/files.py`, 413 bei Ueberschreitung), dazu per-user Attachment-Kontingent (`q_total_attachment_bytes`) und globales Request-Size-Limit fuer `/api/*` (Middleware in `app/main.py`). Alle Limits sind Env-Variablen in der `AppConfig` und in `.env.example` dokumentiert. Security-Header (CSP, nosniff, DENY, HSTS bei TLS) setzt die Middleware in `app/main.py`; das Session-Cookie bekommt `Secure` nur bei TLS (`app/auth.py`).
