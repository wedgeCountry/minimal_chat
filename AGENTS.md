# AGENTS.md

## Projekt

LeanChat — schlanker Chat für OpenAI-kompatible Endpunkte (FastAPI-Backend,
verschlüsselte per-user SQLite-Dateien, statisches ES-Module-Frontend ohne Build-Schritt).

## Wichtige Dokumente

- [README.md](README.md) — Architektur, Features, Speicherlayout
- [SPEC.md](SPEC.md) — fachliche Spezifikation
- [docs/rootless_install.md](docs/rootless_install.md) — Playwright/Chromium rootless installieren und die e2e-GUI-Tests (`pytest -m e2e tests/e2e`) ohne root ausführen
- [docs/e2e_real_llm.md](docs/e2e_real_llm.md) — denselben User-Journey-e2e-Test manuell gegen ein echtes LLM laufen lassen (Opt-in via `LEANCHAT_E2E_REAL_LLM=1`, nie automatisch)

## Tests

- `npm test` — JS-Unit-Tests (node:test)
- `python3 -m pytest` — Python-Unit-Tests (e2e per Marker deselektiert)
- `python3 -m pytest -m e2e tests/e2e` — GUI-Tests mit Playwright gegen Mock-LLM (braucht Chromium, siehe docs/rootless_install.md); gegen echtes LLM siehe docs/e2e_real_llm.md

## UI-Testbarkeit

Alle UI-Elemente tragen ein eindeutiges `data-testid` (dynamische Elemente mit
id-suffix, z. B. `session-tile-<id>`, `bubble-msg-<id>`). e2e-Tests sollen
ausschließlich diese Selektoren verwenden.


## Testing

- Every interactive element carries a unique `data-testid` (kebab-case, `<element>-<context>[-<id>]`, unique per rendered page); test changes ship in the same commit. The Python GUI tests (`tests/test_gui_*.py`) address elements only via their `data-testid`.
- Run `python -m pytest tests` (API tests plus the Python GUI tests, which spawn a uvicorn testing instance via `tests/conftest.py`) and `npm test`. `tests/conftest.py` sets `NICEWAND_SECRET_KEY` — the app refuses to start without a secret; do not remove that wiring.

## Rules for contributors

1. **Render server-side; JS stays a bridge.** All new content comes as a Jinja fragment from a `/views/...` endpoint; the JS only swaps `innerHTML`. No client-side rendering, no moving logic into the JS.
2. **Keep the layering strictly one-directional** (see above). View modules never import each other; shared render logic belongs in `fragments.py`.
3. **Add new forms by entry, not by handler.** In `app.js`, one new entry in `FORM_HANDLERS` (selector, URL/base, target host, error box, modal, after-hook) is enough — never attach another `submit` listener. Entity IDs come from the existing `data-*-id` attributes.
4. **Add new modals by table + macro.** One entry in `MODALS` (close-button ID is derived as `<name>-close`) plus one `m.overlay_modal(...)` call in `base.html`. Never hand-copy overlay markup.
5. **Every interactive element needs a unique `data-testid`**, and test changes (`tests/js`, `tests/test_gui_*.py`) ship in the same commit.
6. **Validate only server-side in Python**, using the helpers from `app/validators.py` (`get_or_404`, `require_nonempty`, `require_date`, `parse_stars`, `optional_int`). Convention: 400 for invalid form values (including FK references), 404 for missing top-level entities; messages in German.
7. **Database access only via `database.py`** (`query_one`/`query_all`/`execute`/`transaction`). Table/column names in f-strings only from internal constants (as in `get_or_404`/`IMAGE_OWNERS`), never from user input.
8. **Bind image entities via `IMAGE_OWNERS`** — one entry is enough. Uploads stay validated (whitelist, magic bytes, 10 MB, no SVG because of XSS), writes stay failure-safe (temp file → transaction → rename), delivery only via `/media/...` with the traversal guard.
9. **Build CRUD pairs uniformly:** `get_or_404` for 404s, a validator function for 400s, then re-render the list/detail fragment; on create, set the `X-*-Id` header if the JS needs the new ID.
10. **Templates use the macros** in `macros.html` (`overlay_modal`, `select_field`, `image_section`, `item_list`, `stat_grid`, `star_rating`, ...). Form rows stay `.form-row`; no new overlay/modal CSS patterns — use the tokens from `base.css` (`--z-modal`, `--overlay-bg`, ...).
11. **Keep names consumed by `app.js` stable** (`.tab`, `.route-form`, fragment hosts, `data-fragment-url`). When renaming, update `app.js` and `tests/js/app.test.js` in the same commit.
12. **Run both test suites before every push:** `python -m pytest tests` (incl. the Python GUI tests) and `npm test`.
13. **Respect the modes:** `NICEWAND_AUTO_LOGIN=1` only in testing, never in production; the secret only via `NICEWAND_SECRET_KEY`/secret file and never committed (`mockdata/`, `productiondata/` are gitignored); don't weaken the HTTPS/HSTS middleware in `core.py`.
14. **Always escape user input, then render** (pattern from `wiki_format.py`). Raw HTML from the DB or from forms is never output unchecked.
15. **Update documentation in the same commit.** Whenever the architecture, endpoints, or start commands change, update `AGENTS.md`/`README.md` alongside — doc drift is the most expensive maintenance error.
16. **Keep the separation between AGENTS.md and README.md clear.** AGENTS.md is for coding agents and cotains technical information and guidelines. README.md shall contain human readable information about the project, about setting up the environment and how to use the app.