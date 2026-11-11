# e2e-User-Journey manuell gegen ein echtes LLM ausführen

Der GUI-Test `tests/e2e/test_user_journey.py` läuft standardmäßig gegen den
lokalen Mock-LLM (`tests/e2e/mock_llm.py`) — das ist der automatische Lauf
(`npm run test:e2e` bzw. `python3 -m pytest -m e2e tests/e2e`) und passiert
nie gegen ein echtes LLM.

Der gleiche Test lässt sich **manuell, eins zu eins identisch** gegen ein echtes
OpenAI-kompatibles LLM ausführen — nur über Umgebungsvariablen umgeschaltet,
keine Code-Änderung am Test:

```bash
export LEANCHAT_E2E_REAL_LLM=1                          # schaltet Mock-LLM ab (Opt-in, nie automatisch)
export LEANCHAT_E2E_LLM_BASE="https://api.openai.com/v1"  # echter Endpunkt (Pflicht im Real-Modus)
export LEANCHAT_E2E_API_KEY="sk-..."                       # echter API-Key (nicht committen!)
export LEANCHAT_MODEL="gpt-4o-mini"                        # optional, Default aus App-Config

python3 -m pytest -m e2e tests/e2e -q
```

## Verhalten im Real-LLM-Modus

- `tests/e2e/conftest.py` startet dann **keinen** Mock-LLM; die App bekommt
  `LEANCHAT_LLM_BASE`/`LEANCHAT_API_KEY` aus den dedizierten Variablen
  `LEANCHAT_E2E_LLM_BASE`/`LEANCHAT_E2E_API_KEY` (nicht aus der `.env`, damit
  der Lauf nie versehentlich mit Beispielwerten startet).
- Ohne `LEANCHAT_E2E_REAL_LLM=1` bleibt alles beim Mock — CI und lokale
  Standardläufe sind davon unberührt.
- Fehlt `LEANCHAT_E2E_LLM_BASE` trotz `LEANCHAT_E2E_REAL_LLM=1`, wird der Lauf
  mit klarer Skip-Meldung übersprungen.
- Erwartungen (Fixture `llm_expect`): Beim Mock antwortet das LLM exakt
  „Hallo Welt“; gegen ein echtes LLM wird auf eine beliebige nicht-leere
  Antwort gewartet (Timeout 120 s statt 30 s). Die Datei-Frage („Was steht in
  der Datei?“) muss in beiden Modi mit dem geheimen Wort **„Krokodil-Ledertasche“**
  beantwortet werden — so wird geprüft, dass das LLM den Anhang gelesen hat.

## Hinweise

- Der API-Key liegt nur in der lokalen Umgebung/Shell — nicht in `.env`
  committen (`.env` ist gitignored, aber Keys gehören nicht ins Repo).
- Rootless Playwright/Chromium siehe [rootless_install.md](rootless_install.md).
