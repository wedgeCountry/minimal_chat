# LeanChat

A lean chat UI for OpenAI-compatible endpoints — now with a **FastAPI backend** and **encrypted per-user SQLite storage**.

Born as a minimalist alternative to OpenWebUI: only the features you actually need, an elegant light/dark theme, and nothing else.

## Architecture

```
app/                  FastAPI backend (uvicorn)
  main.py             App-Factory, Router, StaticFiles
  config.py           Konfiguration (Env: LEANCHAT_DATA_DIR, LEANCHAT_SECRET, LEANCHAT_API_KEY, LEANCHAT_LLM_HOST, LEANCHAT_LLM_PORT)
  auth.py             user_registry-Integration: Registry-DB, mount_auth (/auth-Seiten), Session-Cookies
  models.py           Pydantic-Schemas
  deps.py             FastAPI-Dependencies (Auth via signiertem Session-Cookie)
  db/
    schema.sql        SQL-Schema der pro-User-DB (eigene Datei, inkl. user_settings)
    crypto.py         Fernet-Ver-/Entschluesselung
    database.py       Einziger Zugriff auf die lokalen SQLite-Datenbanken
  routers/            auth.py, sessions.py, settings.py, chat.py (serverseitige Generierung)
  services/chat.py    SSE-Client zum LLM-Endpunkt (stream_completion, SSE-Parsing/ -Filter)
static/               Frontend (statisch, ohne Build-Schritt)
  index.html          schlanke Shell mit Partial-Platzhaltern
  partials/           eigene HTML-Dateien: side-panel, chat-window,
                      settings-overlay (werden per js/html.js geladen)
  css/                base.css, components.css, bubbles.css (variables-gesteuertes
                      Bubble-Styling: Rolle + collapsed/expanded/compact/selected),
                      responsive.css
  js/                 ES-Module: main, html, api, auth, state, sessions, chat,
                      bubbles, attachments, settings, theme, payload, util, icons
tests/
  test_*.py           Python-Unit-Tests (pytest + httpx TestClient)
  js/*.test.js        JS-Unit-Tests (node:test, ohne npm-Abhaengigkeiten)
  e2e/                Playwright-GUI-Tests der User Journey (+ Mock-LLM)
```

## Data storage

- Pro User genau eine **verschluesselte SQLite-Datei** (`data/users/<uid>.db.enc`, Fernet) mit Sessions, Messages und der Tabelle **`user_settings`** (serverseitige Einstellungen).
- uid und Verschluesselungsschluessel der per-user DB werden aus dem **Server-Secret und der E-Mail** abgeleitet (`user_identity` in `app/auth.py`) — es gibt keine lokale User-Tabelle.
- **Login/Registrierung** laufen ueber die Bibliothek [`user_registry`](docs/user_registry_implementation_guidelines.md) (vendored Wheel in `vendors/`, Argon2id-Passwort-Hashing, Passwort-Policy, AGB-Akzeptanz): Credentials liegen in der eigenen Registry-DB (`data/user_registry.db`), Sessions sind itsdangerous-signierte `auth_session`-Cookies, und unter `/auth` stehen professionelle Seiten (Login, Registrieren, Passwort aendern/loeschen, AGB, Impressum). Die Zuordnung zu den per-user App-Daten erfolgt credential-frei per E-Mail.
- Das SQL-Schema der pro-User-DB liegt in [`app/db/schema.sql`](app/db/schema.sql); der gesamte DB-Zugriff in [`app/db/database.py`](app/db/database.py).

## Features

- **Auth** – Registrieren/Anmelden per user_registry (signiertes Session-Cookie), Logout; Daten sind pro User getrennt
- **Sessions** – Side-Panel mit chronologisch sortierten Tiles; anlegen, inline umbenennen, löschen
- **Streaming** – die Generierung laeuft serverseitig als Hintergrund-Task (`POST /api/chat` -> `202`); der LLM-SSE-Stream wird chunk-weise in der per-user DB persistiert, der Client pollt `GET /api/sessions/{id}`
- **Cancel** – laufende Generierung per X abbrechen, Teilausgabe bleibt erhalten
- **Message bubbles** – Rolle/Typ (message, tool-call, reasoning), kollabierbar, kopieren, vorlesen, Kontext-Checkbox, löschen; die letzte Nutzernachricht hat zusätzlich **Bearbeiten** (Stift, Inline-Edit direkt in der Bubble: Textarea in den Bubble-Farben, Enter sendet, Esc bricht ab) und **Erneut senden** (Refresh) – beide nutzen denselben Pfad: die Nachricht wird per `PATCH` übernommen, alle Nachrichten danach (Assistenten-Antworten) gelöscht (`DELETE /api/sessions/{id}/messages/after/{mid}`) und die Antwort neu generiert
- **Attachments** – Dateien, Kamera (mobil), Spracheingabe (Web Speech API); Datei-Uploads gehen als Multipart (`POST /api/sessions/{id}/attachments`) an den Server und werden serverseitig verarbeitet (Tabelle `attachments`)
- **Settings** – Base-URL, Modell, Theme; API-Schlüssel serverseitig (write-only, Env-Fallback) sowie sechs Darstellungsschalter im Settings-Overlay: *Bubbles Deletable* (X-Button), *Bubbles Checkable* (Kontext-Checkbox) und *Bubbles Speaker* (Vorlesen) gelten fuer alle Bubbles (User + Assistant), dazu *Show System Prompt*, *Show Tool Output*, *Show Reasoning*. Diese steuern clientseitig das Bubble-Rendering und werden serverseitig als Filter auf Request (System-Prompt) und LLM-SSE-Response (Reasoning, Tool-Calls) angewendet
- **Theme** – hell/dunkel via CSS Custom Properties

## Configuration (.env)

Beim ersten Programmstart wird automatisch eine **`.env`** aus der gecheckten **`.env.example`** erzeugt (die `.env` selbst ist gitignored). Dort liegen alle globalen Variablen: Data-Root (`LEANCHAT_DATA_DIR`), Datenbankpfade (`LEANCHAT_REGISTRY_PATH`, `LEANCHAT_USERS_DIR`), Server-Secret (`LEANCHAT_SECRET`), LLM-Endpunkt (`LEANCHAT_LLM_HOST`, `LEANCHAT_LLM_PORT`, `LEANCHAT_MODEL`, `LEANCHAT_API_KEY`) sowie Host/Port (`LEANCHAT_HOST`, `LEANCHAT_PORT`). Echte Systemumgebungsvariablen haben Vorrang vor der `.env`.

## Getting started

```bash
pip install -e ".[dev]"   # fastapi, uvicorn, httpx, cryptography, pytest, playwright, argon2-cffi, itsdangerous
pip install ./vendors/user_registry-0.1.0-py3-none-any.whl   # Login/Registrierung (user_registry)
python -m app              # startet uvicorn (Host/Port aus der .env), .env wird falls noetig erzeugt
# oder: uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dann `http://127.0.0.1:8000` im Browser öffnen, `.env` anpassen (z. B. `LEANCHAT_API_KEY`), registrieren und chatten.

## Tests

```bash
python -m pytest                  # Python-Unit-Tests (API, DB, Krypto, Chat-Proxy)
npm test                          # JS-Unit-Tests (node:test)
python -m pytest -m e2e tests/e2e # GUI-Tests mit Playwright (braucht `playwright install chromium`)
```


### User-Journey-GUI-Test manuell gegen ein echtes LLM

Der e2e-Test laeuft standardmaessig gegen den lokalen Mock-LLM. Der gleiche Test
laesst sich manuell eins zu eins gegen ein echtes OpenAI-kompatibles LLM
ausfuehren (Opt-in, nie automatisch):

```bash
export LEANCHAT_E2E_REAL_LLM=1
export LEANCHAT_E2E_LLM_BASE="https://api.openai.com/v1"
export LEANCHAT_E2E_API_KEY="sk-..."
python -m pytest -m e2e tests/e2e
```

Details siehe [docs/e2e_real_llm.md](docs/e2e_real_llm.md).

## Specification

See [SPEC.md](SPEC.md) for the original design specification (German).

## Tech

- Backend: FastAPI + uvicorn, httpx (SSE-Client zum LLM), cryptography (Fernet), argon2-cffi (Schluesselableitung), SQLite (stdlib)
- Frontend: statische HTML/CSS + vanilla JS als ES-Module, kein Build-Tool
- OpenAI-compatible protocol: `POST {baseURL}/chat/completions`, `Authorization: Bearer {key}`, `stream: true`
- Supports `delta.content`, `delta.reasoning_content` and `delta.tool_calls`

## License

MIT

