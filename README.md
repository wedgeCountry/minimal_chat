# LeanChat

A lean chat UI for OpenAI-compatible endpoints — now with a **FastAPI backend** and **encrypted per-user SQLite storage**.

Born as a minimalist alternative to OpenWebUI: only the features you actually need, an elegant light/dark theme, and nothing else.

## Architecture

```
app/                  FastAPI backend (uvicorn)
  main.py             App-Factory, Router, StaticFiles
  config.py           Konfiguration (Env: LEANCHAT_DATA_DIR, LEANCHAT_SECRET, LEANCHAT_API_KEY, LEANCHAT_LLM_BASE)
  security.py         Passwort-Hashing (PBKDF2) + signierte Tokens (HMAC)
  models.py           Pydantic-Schemas
  deps.py             FastAPI-Dependencies (Auth)
  db/
    schema.sql        SQL-Schema der pro-User-DB (eigene Datei, inkl. user_settings)
    user_registry.sql SQL-Schema der User Registry (eigene Datei)
    crypto.py         Fernet-Ver-/Entschluesselung
    database.py       Einziger Zugriff auf alle SQLite-Datenbanken
  routers/            auth.py, sessions.py, settings.py, chat.py (SSE-Proxy)
  services/chat.py    SSE-Streaming-Passthrough zum LLM-Endpunkt
static/               Frontend (statisch, ohne Build-Schritt)
  index.html          schlanke Shell mit Partial-Platzhaltern
  partials/           eigene HTML-Dateien: auth-overlay, side-panel,
                      chat-window, settings-overlay (werden per js/html.js geladen)
  css/                base.css, components.css, bubbles.css (variables-gesteuertes
                      Bubble-Styling: Rolle + collapsed/expanded/compact/selected),
                      responsive.css
  js/                 ES-Module: main, html, api, auth, state, sessions, chat,
                      bubbles, attachments, settings, theme, sse, payload, util, icons
tests/
  test_*.py           Python-Unit-Tests (pytest + httpx TestClient)
  js/*.test.js        JS-Unit-Tests (node:test, ohne npm-Abhaengigkeiten)
  e2e/                Playwright-GUI-Tests der User Journey (+ Mock-LLM)
```

## Data storage

- Pro User genau eine **verschluesselte SQLite-Datei** (`data/users/<uid>.db.enc`, Fernet) mit Sessions, Messages und der Tabelle **`user_settings`** (serverseitige Einstellungen).
- Der Verschluesselungsschluessel wird **einmalig clientseitig** (WebCrypto, 32 Bytes) bei der Registrierung erzeugt und mitgeschickt.
- Die **User-Credentials** liegen in einer eigenen Datenbank, der **User Registry** (`data/user_registry.db.enc`, mit Server-Secret verschluesselt) – das Login-System ist dadurch spaeter austauschbar.
- Die SQL-Schemas liegen in eigenen Dateien: [`app/db/schema.sql`](app/db/schema.sql) (pro User) und [`app/db/user_registry.sql`](app/db/user_registry.sql) (Registry); der gesamte DB-Zugriff in [`app/db/database.py`](app/db/database.py).

## Features

- **Auth** – Registrieren/Anmelden (Token), Logout; Daten sind pro User getrennt
- **Sessions** – Side-Panel mit chronologisch sortierten Tiles; anlegen, inline umbenennen, löschen
- **Streaming** – SSE vom OpenAI-kompatiblen Endpunkt wird ueber das FastAPI-Backend (`POST /api/chat`) live durchgereicht
- **Cancel** – laufende Generierung per X abbrechen, Teilausgabe bleibt erhalten
- **Message bubbles** – Rolle/Typ (message, tool-call, reasoning), kollabierbar, kopieren, vorlesen, Kontext-Checkbox, löschen
- **Attachments** – Dateien, Kamera (mobil), Spracheingabe (Web Speech API)
- **Settings** – Base-URL, Modell, Theme; API-Schlüssel serverseitig (write-only, Env-Fallback)
- **Theme** – hell/dunkel via CSS Custom Properties

## Getting started

```bash
pip install -e ".[dev]"          # fastapi, uvicorn, httpx, cryptography, pytest, playwright
export LEANCHAT_API_KEY="sk-..." # optional; auch pro User in den Einstellungen
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dann `http://127.0.0.1:8000` im Browser öffnen, registrieren und chatten.

## Tests

```bash
python -m pytest                  # Python-Unit-Tests (API, DB, Krypto, Chat-Proxy)
npm test                          # JS-Unit-Tests (node:test)
python -m pytest -m e2e tests/e2e # GUI-Tests mit Playwright (braucht `playwright install chromium`)
```

## Specification

See [SPEC.md](SPEC.md) for the original design specification (German).

## Tech

- Backend: FastAPI + uvicorn, httpx (SSE-Proxy), cryptography (Fernet), SQLite (stdlib)
- Frontend: statische HTML/CSS + vanilla JS als ES-Module, kein Build-Tool
- OpenAI-compatible protocol: `POST {baseURL}/chat/completions`, `Authorization: Bearer {key}`, `stream: true`
- Supports `delta.content`, `delta.reasoning_content` and `delta.tool_calls`

## License

MIT
