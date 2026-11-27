# LeanChat

A lean chat UI for OpenAI-compatible endpoints — now with a **FastAPI backend** and **encrypted per-user SQLite storage**.

Born as a minimalist alternative to OpenWebUI: only the features you actually need, an elegant light/dark theme, and nothing else.

## Architecture

```
app/                  FastAPI backend (uvicorn)
  main.py             App-Factory, Router, StaticFiles + Middleware
                      (Request-Size-Limit fuer /api/*, Security-Header/CSP, HSTS bei TLS)
  config.py           Konfiguration (Pydantic-Model mit Validierung; Env: LEANCHAT_DATA_DIR, LEANCHAT_SECRET, LEANCHAT_API_KEY, LEANCHAT_LLM_HOST, LEANCHAT_LLM_PORT, LEANCHAT_AUTO_LOGIN)
  types.py            TypedDicts fuer interne dict-Daten (DB-Zeilen, User-Identitaet, Stream-Bloecke)
  auth.py             user_registry-Integration: Registry-DB, mount_auth (/auth-Seiten), Session-Cookies
  domain.py           Kanonische Domain-Models (Message/Session/Attachment) fuer Memory, SSE, API und Store-Mapping
  models.py           Pydantic-API-Models (Request/Response), abgeleitet von domain.py
  deps.py             FastAPI-Dependencies (Auth via signiertem Session-Cookie)
  db/
    schema.sql        SQL-Schema der pro-User-DB (eigene Datei, inkl. user_settings, session_settings und llm_models)
    crypto.py         Fernet-Ver-/Entschluesselung
    database.py       Low-Level-Persistenz: verschluesselte per-user SQLite-Dateien (einzige Stelle mit SQLite/Crypto)
  routers/            auth.py, sessions.py, settings.py, models.py (LLM-Modell-Tiles), chat.py (serverseitige Generierung)
  services/chat.py    MessageService: Single Write Funnel — haelt pro heisser Session das volle In-Memory-Message-Memory,
                      SSE-Live-Stream an den Client (GET /api/chat/stream/{sid}), persistiert write-through ueber den Store
  services/store.py   UserStoreProtocol (Persistenz-Gateway): einziger DB-Zugriff fuer Router/Service
                      (SqliteUserStore = verschluesselte per-user SQLite-Dateien, kapselt asyncio.to_thread)
  services/memory_store.py  InMemoryUserStore (Test-Double)
  services/llm.py     LLM-Client (LlmClient: stream_completion mit Abort-Race, check_llm_connection)
  services/context.py LLM-Kontext aus der Session-DB via trixie_ai.LlmContext (vendored Wheel,
                      inkl. Tool-Calls als assistant/tool-Messages)
  services/sse.py     SSE-Parsing/-Serialisierung (parse_sse_data, parse_sse_buffer, SseParser, sse_event); der LLM-Stream wird nicht gefiltert, alle Bloecke werden persistiert (Anzeige-Settings wirken clientseitig)
  services/ssrf.py    LlmUrlValidator / validate_llm_base_url (SSRF-Schutz fuer user-gesteuerte LLM-URLs)
  services/files.py   Upload-Verarbeitung (gestreamtes Lesen mit Byte-Cap, Kontingent, Expansion)
static/               Frontend (statisch, ohne Build-Schritt)
  index.html          schlanke Shell mit Partial-Platzhaltern
  partials/           eigene HTML-Dateien: side-panel, chat-window,
                      settings-overlay, model-overlay, session-settings-overlay,
                      edit-overlay (werden per js/html.js geladen)
  css/                base.css, components.css, bubbles.css (variables-gesteuertes
                      Bubble-Styling: Rolle + collapsed/expanded/selected),
                      responsive.css
  js/                 ES-Module: main, html, api, auth, state, sessions, chat,
                      bubbles, attachments, settings, models, sessionSettings, theme, payload, util, icons
tests/
  test_*.py           Python-Unit-Tests (pytest + httpx TestClient)
  js/*.test.js        JS-Unit-Tests (node:test, ohne npm-Abhaengigkeiten)
  e2e/                Playwright-GUI-Tests der User Journey (+ Mock-LLM)
```

## Data storage

- Pro User genau eine **verschluesselte SQLite-Datei** (`data/users/<uid>.db.enc`, Fernet) mit Sessions, Messages, der Tabelle **`user_settings`** (globale serverseitige Einstellungen inkl. `default_model_id`), der Tabelle **`session_settings`** (Einstellungen pro Session inkl. `model_id`) und der Tabelle **`llm_models`** (LLM-Modell-Tiles mit Verbindungsdaten; `api_key` ist ein Secret und wird nie per API ausgeliefert). Alte flache LLM-Keys (`base`/`host`/`port`/`model`/`api_key`) werden beim Oeffnen der DB einmalig in ein Tile migriert (`q_migrate_legacy_llm_settings`).
- uid und Verschluesselungsschluessel der per-user DB werden aus dem **Server-Secret und der E-Mail** abgeleitet (`user_identity` in `app/auth.py`) — es gibt keine lokale User-Tabelle.
- **Login/Registrierung** laufen ueber die Bibliothek [`user_registry`](docs/user_registry_implementation_guidelines.md) (vendored Wheel in `vendors/`, Argon2id-Passwort-Hashing, Passwort-Policy, AGB-Akzeptanz): Credentials liegen in der eigenen Registry-DB (`data/user_registry.db`), Sessions sind itsdangerous-signierte `auth_session`-Cookies, und unter `/auth` stehen professionelle Seiten (Login, Registrieren, Passwort aendern/loeschen, AGB, Impressum). Die Zuordnung zu den per-user App-Daten erfolgt credential-frei per E-Mail.
- Das SQL-Schema der pro-User-DB liegt in [`app/db/schema.sql`](app/db/schema.sql); Low-Level-Zugriff (SQLite/Crypto) nur in [`app/db/database.py`](app/db/database.py), alle Aufrufe darueber laufen ueber das Repository [`app/services/store.py`](app/services/store.py).

## Features

- **Auth** – Registrieren/Anmelden per user_registry (signiertes Session-Cookie), Logout; Daten sind pro User getrennt
- **Sessions** – Side-Panel mit chronologisch sortierten Tiles; anlegen, inline umbenennen, löschen. Der ungesendete Composer-Text (**Entwurf**) ist pro Session und wird im Browser persistiert: Session-Wechsel lädt den Entwurf der Ziel-Session, Rückkehr stellt den eigenen wieder her, Senden löscht ihn
- **Session-Einstellungen** – Zahnrad-Button oben links im Chat-Panel öffnet ein Modal pro Session (System-Prompt, der den globalen Prompt überschreibt; Modell-Select, der das Standard-Modell dieser Session überschreibt); Speichern per `PUT /api/sessions/{id}/settings`, Laden per `GET /api/sessions/{id}/settings` (im Session-Detail `GET /api/sessions/{id}` enthalten); Abbrechen verwirft ohne API-Aufruf
- **Streaming** – die Generierung laeuft serverseitig als Hintergrund-Task (`POST /api/chat` -> `202`); der LLM-SSE-Stream wird chunk-weise in der per-user DB persistiert, der Client pollt `GET /api/sessions/{id}`
- **Cancel** – laufende Generierung per X abbrechen, Teilausgabe bleibt erhalten
- **Message bubbles** – Rolle/Typ (message, tool-call, reasoning), kollabierbar, kopieren, vorlesen, Kontext-Checkbox (auch auf Tool-Call-/Tool-Result-Bubbles), löschen; Select-All innerhalb einer Bubble selektiert nur den Bubble-Text, nicht die ganze App – auch das native „Alles auswählen“ des Systemmenüs (Android-Browser/WebView) bleibt auf die Bubble begrenzt (Touch: Langdruck = natives Systemmenü, Doppel-Tap = App-Kontextmenü); die letzte Nutzernachricht hat zusätzlich **Bearbeiten** (Stift öffnet ein Overlay-Modal im Bubble-Stil mit Textarea sowie Senden-/Abbrechen-Buttons; Enter sendet, Esc bricht ab) und **Erneut senden** (Refresh) – beide nutzen denselben Pfad: die Nachricht wird per `PATCH` übernommen, alle Nachrichten danach (Assistenten-Antworten) gelöscht (`DELETE /api/sessions/{id}/messages/after/{mid}`) und die Antwort neu generiert
- **Attachments** – Dateien, Kamera (mobil), Spracheingabe (Mikrofon-Button nutzt STT des Voice Companion); Datei-Uploads gehen als Multipart (`POST /api/sessions/{id}/attachments`) an den Server und werden serverseitig verarbeitet (Tabelle `attachments`)
- **Voice** – Vorlesen (Lautsprecher-Button) und Spracheingabe (Mikrofon-Button) ueber **Voice Companion** (vendored Wheel in `vendors/`, eigener Server, Base-URL via `LEANCHAT_VOICE_BASE`, Default `http://127.0.0.1:8001`) oder die Browser-System-API. Modus per User-Setting `speech_mode` (Radio-Buttons in den Einstellungen: *System-API* / *Server* / *Aus*); die Einstellungen zeigen die Verfuegbarkeit des gewaehlten Modus pro Richtung (STT/TTS) gruen/rot an ("Verfuegbar" / "Nur STT bzw. TTS verfuegbar" / "Nicht verfuegbar"); die Radio-Auswahl wirkt sofort, auch vor dem Speichern (beim Abbrechen wird der gespeicherte Modus wiederhergestellt); bei *Aus* oder nicht verfuegbarem Modus wird das jeweilige Mikrofon-/Speaker-Control ausgeblendet, sonst erscheint beim Klick eine Fehlermeldung ("Sprachdienst nicht verfügbar"). Funktionspruefung des Servers per `GET /api/voice/status`. Zusammenspiel: Laeuft die Wiedergabe (Speaker-Button), wird die Aufnahme unterdrueckt; startet die Wiedergabe waehrend einer Aufnahme, stoppt diese (Puffer wird verworfen); Senden stoppt die Aufnahme und leert Chat-Zeile + Aufnahme-Puffer; erneuter Klick auf den Speaker stoppt die Wiedergabe
- **LLM-Modelle (Tiles)** – der LLM-Tab in den Einstellungen zeigt alle Modell-Setups als Tiles nebeneinander plus ein *Neues Modell*-Tile; Klick auf ein Tile setzt es als Standard-Modell, das Stift-Icon öffnet ein Modal mit Anbieter, Host, Port, berechneter Base-URL, API-Schlüssel (write-only, serverseitig in `llm_models` gespeichert), Modell, *Verbindung testen* (unterscheidet „nicht erreichbar“ / „API-Schlüssel ungültig“ (401/403) / „Modell nicht verfügbar“; bei leerem Modell-Feld wird es zum Dropdown mit den vom Server gemeldeten Modellen) und *Löschen*. CRUD unter `/api/settings/models` (`GET`/`POST`/`PUT`/`DELETE`/`POST /test`, api_key nie in Antworten). Pro Tile ein *Standard-Modell*-Radio: das Standard-Tile steht in `user_settings.default_model_id` und wird von neuen Sessions ohne eigenes `model_id` genutzt. Effektive Verbindung beim Chat: Session-`model_id` > `default_model_id` > Server-Defaults (`LEANCHAT_LLM_HOST/PORT/MODEL/API_KEY`) – `resolve_llm_connection` in `app/services/settings.py`
- **Settings** – Theme, globaler System-Prompt sowie Darstellungsschalter im Allgemein-Tab des Settings-Overlays: *Bubbles Deletable* (Mülleimer-Button), *Bubbles Checkable* (Kontext-Checkbox) und *Bubbles Speaker* (Vorlesen) gelten fuer alle Bubbles (User + Assistant), dazu *Show System Prompt*, *Show Tool Output*, *Show Reasoning*. Diese steuern clientseitig das Bubble-Rendering und werden serverseitig als Filter auf Request (System-Prompt) und LLM-SSE-Response (Reasoning, Tool-Calls) angewendet
- **Theme** – hell/dunkel via CSS Custom Properties
- **Mobile** – auf Smartphones bleibt der Composer bei geoeffneter Tastatur sichtbar und am unteren Rand: `interactive-widget=resizes-content` im Viewport-Meta (Android/Chrome) plus Visual-Viewport-Fallback in `static/js/viewport.js` (iOS/aeltere Browser), dazu `env(safe-area-inset-bottom)`-Padding fuer Geraete mit Notch/Home-Indicator
- **Embed-Modus** – `?embed=1` an `/` oder `/s/<id>` blendet Header (Panel-Button, Burger-Menü) und Side-Panel per Klasse `embed` auf `<html>` aus (`static/js/embed.js` + `static/css/base.css`); sichtbar bleiben nur Chat-Panel (inkl. Session-Zahnrad) und Composer – z. B. fuer die Einbettung in eine andere App per WebView/iframe. Serverseitig entfaellt fuer diese App-Seiten `X-Frame-Options: DENY` und die CSP erlaubt `frame-ancestors *` (`app/main.py`); `/api/*` und `/auth/*` bleiben DENY

## Configuration (.env)

Beim ersten Programmstart wird automatisch eine **`.env`** aus der gecheckten **`env-example`** erzeugt (die `.env` selbst ist gitignored; die Example-Datei heisst ohne fuehrenden Punkt, damit `.env*`-Ignore-Regeln sie nicht aus Versehen ausschliessen). Dort liegen alle globalen Variablen: Data-Root (`LEANCHAT_DATA_DIR`), Datenbankpfade (`LEANCHAT_REGISTRY_PATH`, `LEANCHAT_USERS_DIR`), Server-Secret (`LEANCHAT_SECRET`), LLM-Endpunkt (`LEANCHAT_LLM_HOST`, `LEANCHAT_LLM_PORT`, `LEANCHAT_MODEL`, `LEANCHAT_API_KEY`), Host/Port (`LEANCHAT_HOST`, `LEANCHAT_PORT`) und Auto-Login-Testmodus (`LEANCHAT_AUTO_LOGIN`). Alle Variablen werden in `app/config.py` (`AppConfig`) gelesen und liegen in der `.env`. Echte Systemumgebungsvariablen haben Vorrang vor der `.env`.

**Sicherheit/Limits** (ebenfalls in der `.env`, siehe `env-example`):

- **SSRF-Schutz**: pro User einstellbare LLM-URLs werden serverseitig validiert (`validate_llm_base_url`): nur `http/https` ohne Credentials; private/Loopback-/Link-Local-/reservierte Ziele (z. B. Cloud-Metadata `169.254.169.254`) werden blockiert, sobald der Server nicht auf Loopback bindet — außer `LEANCHAT_ALLOW_PRIVATE_LLM=1`. Upstream-Fehlermeldungen enthalten nur den HTTP-Status, nie den Response-Body.
- **DoS-Limits**: Uploads werden gestreamt mit Byte-Cap gelesen (`LEANCHAT_MAX_UPLOAD_BYTES`, 413 bei Ueberschreitung), pro User gilt ein Attachment-Kontingent (`LEANCHAT_MAX_USER_STORAGE_BYTES`), und `/api/*`-Requests werden per Content-Length gedeckelt (`LEANCHAT_MAX_REQUEST_BYTES`, 413).
- **Header/Cookie**: jede Response traegt CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` (Ausnahme: App-Seiten mit `?embed=1` erlauben Framing, siehe **Embed-Modus**); bei TLS (`LEANCHAT_SSL_CERTFILE`) zusaetzlich HSTS und das Session-Cookie mit `Secure`-Flag. Die `/auth`-Seiten der user_registry bekommen wegen ihres Inline-CSRF-Scripts ein entspanntes CSP (`script-src 'self' 'unsafe-inline'`).
- **Page-Visit-Stack**: pro User und Session fuehrt der Server einen Stack besuchter Seiten (`LEANCHAT_VISIT_STACK_SIZE`, Default 20). Navigiert ein eingeloggter User per Zurueck-Button auf eine Auth-Seite (z. B. `/auth/login`), wird statt des Login-Screens die zuletzt besuchte Seite angesteuert. Da die App eine SPA ist, bekommt jede In-App-View (Session) einen eigenen URL-Pfad (`/s/<id>`, serverseitig als SPA-Route bedient): Der Client setzt ihn per History-API (`pushState`/`popstate`) und meldet ihn zusaetzlich an `POST /api/visits` — die Zurueck-Taste wechselt so auch innerhalb der App die zuletzt besuchte Session, und die Session-ID steht sichtbar in der Browser-URL.

## Getting started

```bash
pip install -e ".[dev]"   # fastapi, uvicorn, httpx, cryptography, pytest, playwright, argon2-cffi, itsdangerous
.venv/bin/python -m pip install vendors/user_registry-*.whl --force-reinstall
.venv/bin/python -m pip install vendors/trixie_ai-0.1.0-py3-none-any.whl
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
python -m mypy                    # Typecheck, strict (CI-Job `typecheck`)
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

