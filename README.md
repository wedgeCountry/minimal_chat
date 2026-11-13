# LeanChat

A lean chat UI for OpenAI-compatible endpoints — now with a **FastAPI backend** and **encrypted per-user SQLite storage**.

Born as a minimalist alternative to OpenWebUI: only the features you actually need, an elegant light/dark theme, and nothing else.

## Architecture

```
app/                  FastAPI backend (uvicorn)
  main.py             App-Factory, Router, StaticFiles + Middleware
                      (Request-Size-Limit fuer /api/*, Security-Header/CSP, HSTS bei TLS)
  config.py           Konfiguration (Env: LEANCHAT_DATA_DIR, LEANCHAT_SECRET, LEANCHAT_API_KEY, LEANCHAT_LLM_HOST, LEANCHAT_LLM_PORT)
  auth.py             user_registry-Integration: Registry-DB, mount_auth (/auth-Seiten), Session-Cookies
  models.py           Pydantic-Schemas
  deps.py             FastAPI-Dependencies (Auth via signiertem Session-Cookie)
  db/
    schema.sql        SQL-Schema der pro-User-DB (eigene Datei, inkl. user_settings)
    crypto.py         Fernet-Ver-/Entschluesselung
    database.py       Einziger Zugriff auf die lokalen SQLite-Datenbanken
  routers/            auth.py, sessions.py, settings.py, chat.py (serverseitige Generierung)
  services/llm.py     LLM-Client (LlmClient: stream_completion mit Abort-Race, check_llm_connection)
  services/sse.py     SSE-Parsing/-Filter (parse_sse_data, parse_sse_buffer, SseParser, sse_filter)
  services/ssrf.py    LlmUrlValidator / validate_llm_base_url (SSRF-Schutz fuer user-gesteuerte LLM-URLs)
  services/files.py   Upload-Verarbeitung (gestreamtes Lesen mit Byte-Cap, Kontingent, Expansion)
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
- **Message bubbles** – Rolle/Typ (message, tool-call, reasoning), kollabierbar, kopieren, vorlesen, Kontext-Checkbox, löschen; die letzte Nutzernachricht hat zusätzlich **Bearbeiten** (Stift, Inline-Edit direkt in der Bubble: Textarea in den Bubble-Farben mit X-Button rechts daneben, Enter sendet, Esc bricht ab) und **Erneut senden** (Refresh) – beide nutzen denselben Pfad: die Nachricht wird per `PATCH` übernommen, alle Nachrichten danach (Assistenten-Antworten) gelöscht (`DELETE /api/sessions/{id}/messages/after/{mid}`) und die Antwort neu generiert
- **Attachments** – Dateien, Kamera (mobil), Spracheingabe (Mikrofon-Button nutzt STT des Voice Companion); Datei-Uploads gehen als Multipart (`POST /api/sessions/{id}/attachments`) an den Server und werden serverseitig verarbeitet (Tabelle `attachments`)
- **Voice** – Vorlesen (Lautsprecher-Button) und Spracheingabe (Mikrofon-Button) ueber **Voice Companion** (vendored Wheel in `vendors/`, eigener Server, Base-URL via `LEANCHAT_VOICE_BASE`, Default `http://127.0.0.1:8001`) oder die Browser-System-API. Modus per User-Setting `speech_mode` (Radio-Buttons in den Einstellungen: *System-API* / *Server* / *Aus*); die Einstellungen zeigen die Verfuegbarkeit des gewaehlten Modus gruen/rot an, bei *Aus* oder nicht verfuegbarem Modus werden Mikrofon-/Speaker-Controls ausgeblendet, sonst erscheint beim Klick eine Fehlermeldung ("Sprachdienst nicht verfügbar"). Funktionspruefung des Servers per `GET /api/voice/status`. Zusammenspiel: Laeuft die Wiedergabe (Speaker-Button), wird die Aufnahme unterdrueckt; startet die Wiedergabe waehrend einer Aufnahme, stoppt diese (Puffer wird verworfen); Senden stoppt die Aufnahme und leert Chat-Zeile + Aufnahme-Puffer; erneuter Klick auf den Speaker stoppt die Wiedergabe
- **Settings** – Base-URL, Modell, Theme; API-Schlüssel serverseitig (write-only, Env-Fallback) sowie sechs Darstellungsschalter im Settings-Overlay: *Bubbles Deletable* (X-Button), *Bubbles Checkable* (Kontext-Checkbox) und *Bubbles Speaker* (Vorlesen) gelten fuer alle Bubbles (User + Assistant), dazu *Show System Prompt*, *Show Tool Output*, *Show Reasoning*. Diese steuern clientseitig das Bubble-Rendering und werden serverseitig als Filter auf Request (System-Prompt) und LLM-SSE-Response (Reasoning, Tool-Calls) angewendet
- **Theme** – hell/dunkel via CSS Custom Properties

## Configuration (.env)

Beim ersten Programmstart wird automatisch eine **`.env`** aus der gecheckten **`.env.example`** erzeugt (die `.env` selbst ist gitignored). Dort liegen alle globalen Variablen: Data-Root (`LEANCHAT_DATA_DIR`), Datenbankpfade (`LEANCHAT_REGISTRY_PATH`, `LEANCHAT_USERS_DIR`), Server-Secret (`LEANCHAT_SECRET`), LLM-Endpunkt (`LEANCHAT_LLM_HOST`, `LEANCHAT_LLM_PORT`, `LEANCHAT_MODEL`, `LEANCHAT_API_KEY`) sowie Host/Port (`LEANCHAT_HOST`, `LEANCHAT_PORT`). Echte Systemumgebungsvariablen haben Vorrang vor der `.env`.

**Sicherheit/Limits** (ebenfalls in der `.env`, siehe `.env.example`):

- **SSRF-Schutz**: pro User einstellbare LLM-URLs werden serverseitig validiert (`validate_llm_base_url`): nur `http/https` ohne Credentials; private/Loopback-/Link-Local-/reservierte Ziele (z. B. Cloud-Metadata `169.254.169.254`) werden blockiert, sobald der Server nicht auf Loopback bindet — außer `LEANCHAT_ALLOW_PRIVATE_LLM=1`. Upstream-Fehlermeldungen enthalten nur den HTTP-Status, nie den Response-Body.
- **DoS-Limits**: Uploads werden gestreamt mit Byte-Cap gelesen (`LEANCHAT_MAX_UPLOAD_BYTES`, 413 bei Ueberschreitung), pro User gilt ein Attachment-Kontingent (`LEANCHAT_MAX_USER_STORAGE_BYTES`), und `/api/*`-Requests werden per Content-Length gedeckelt (`LEANCHAT_MAX_REQUEST_BYTES`, 413).
- **Header/Cookie**: jede Response traegt CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`; bei TLS (`LEANCHAT_SSL_CERTFILE`) zusaetzlich HSTS und das Session-Cookie mit `Secure`-Flag. Die `/auth`-Seiten der user_registry bekommen wegen ihres Inline-CSRF-Scripts ein entspanntes CSP (`script-src 'self' 'unsafe-inline'`).

## Getting started

```bash
pip install -e ".[dev]"   # fastapi, uvicorn, httpx, cryptography, pytest, playwright, argon2-cffi, itsdangerous
.venv/bin/python -m pip install vendors/user_registry-*.whl --force-reinstall
.venv/bin/python -m pip install vendors/voice_companion-*.whl --force-reinstall

python -m app              # startet uvicorn (Host/Port aus der .env), .env wird falls noetig erzeugt
# oder: uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dann `http://127.0.0.1:8000` im Browser öffnen, `.env` anpassen (z. B. `LEANCHAT_API_KEY`), registrieren und chatten. Ohne gueltige Session leitet `/` serverseitig auf `/auth/login` um; nach dem Login geht es zurueck auf `/`.

## Tests

```bash
python -m pytest                  # Python-Unit-Tests (API, DB, Krypto, Chat-Proxy, Security)
npm test                          # JS-Unit-Tests (node:test)
python -m ruff check app tests    # Lint (CI-Job `lint`)
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

