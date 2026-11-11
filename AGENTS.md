# AGENTS.md

## Projekt

LeanChat — schlanker Chat für OpenAI-kompatible Endpunkte (FastAPI-Backend,
verschlüsselte per-user SQLite-Dateien, statisches ES-Module-Frontend ohne Build-Schritt).

## Wichtige Dokumente

- [README.md](README.md) — Architektur, Features, Speicherlayout
- [SPEC.md](SPEC.md) — fachliche Spezifikation
- [docs/rootless_install.md](docs/rootless_install.md) — Playwright/Chromium rootless installieren und die e2e-GUI-Tests (`pytest -m e2e tests/e2e`) ohne root ausführen

## Tests

- `npm test` — JS-Unit-Tests (node:test)
- `python3 -m pytest` — Python-Unit-Tests (e2e per Marker deselektiert)
- `python3 -m pytest -m e2e tests/e2e` — GUI-Tests mit Playwright (braucht Chromium, siehe docs/rootless_install.md)

## UI-Testbarkeit

Alle UI-Elemente tragen ein eindeutiges `data-testid` (dynamische Elemente mit
id-suffix, z. B. `session-tile-<id>`, `bubble-msg-<id>`). e2e-Tests sollen
ausschließlich diese Selektoren verwenden.
