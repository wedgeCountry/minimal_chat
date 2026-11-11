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
