# LeanChat – Spezifikation

Eine schlanke, eigenständige Chat-Oberfläche für OpenAI-kompatible Endpunkte. Alternative zu OpenWebUI, bewusst minimalistisch gehalten.

## 1. Ziele und Nicht-Ziele

**Ziele**

- Schlankes Chat-Frontend (statische ES-Module ohne Build-Schritt) mit FastAPI-Backend und verschlüsselten per-user SQLite-Dateien (siehe README.md)
- Serverseitige Generierung von OpenAI-kompatiblen Endpunkten (`/v1/chat/completions`, SSE); der Client pollt den persistierten Stand
- Elegantes, minimalistisches Design mit hellem und dunklem Theme (Standard: hell)
- Sessions mit klaren, minimalen Interaktionsmöglichkeiten

**Nicht-Ziele**

- Multi-User-Verwaltung, Admin-Oberflächen, Modell-Browsing, Prompt-Bibliotheken, RAG, Plugins

## 2. Layout

### 2.1 Header (schmal)

- Links: Symbol zum Ein-/Ausklappen des Side-Panels (Hamburger/Panel-Icon)
- Mitte: Titel der App / Name der aktiven Session (optional)
- Rechts: Burger-Menü mit:
  - **Einstellungen** – öffnet den Settings-Dialog
  - **Logout** – leert lokalen Zustand (API-Schlüssel, Sessions) und bestätigt

### 2.2 Side-Panel (einklappbar)

- Beim App-Start (erstmalig und nach Refresh) ist das Side-Panel eingeklappt; existiert noch keine Session, wird automatisch eine neue Session angelegt und geoeffnet
- Liste von Sessions als chronologisch sortierte Tiles (neueste zuerst)
  - **Plus-Symbol**: Datei anhaengen (Datei-Dialog; die Rohdatei wird an den Server hochgeladen, serverseitig gelesen/dekodiert und als Text-/Bildinhalt in den LLM-Request eingebettet)
- Jedes Session-Tile enthält:
  - Session-Name (Klick: Session öffnen)
  - Stift-Symbol: Namen inline editieren (Enter bestätigt, Esc bricht ab)
  - Mülleimer-Symbol: Session löschen (mit Bestätigung)
- Am unteren Rand bzw. im Panel: **X-Symbol** zum Abbrechen eines laufenden Generierungsprozesses (nur aktiv, wenn Streaming läuft)

### 2.3 Hauptpanel (Chat)

- Schmale, auf den Chat fokussierte Oberfläche
- Nachrichten-Bubbles: Assistent links, Nutzer rechts (System-Nachrichten neutral/mittig oder links mit Label)
- Unten: Eingabefenster (Chat-Composer) mit:
  - Mehrzeiligem Textfeld (Enter sendet, Shift+Enter = Zeilenumbruch)
  - **Senden-Button** (Pfeil-Symbol)
  - **Plus-Symbol**: Datei anhaengen (Datei-Dialog; die Rohdatei wird an den Server hochgeladen, serverseitig gelesen/dekodiert und als Text-/Bildinhalt in den LLM-Request eingebettet)
  - **Kamera-Symbol**: Foto aufnehmen (`<input type="file" accept="image/*" capture="environment">`, primär für Mobilgeräte)
  - **Mikro-Symbol**: Nachricht diktieren (Web Speech API `SpeechRecognition`, falls verfügbar; sonst ausgeblendet/deaktiviert)
  - **X-Symbol** (ersetzt Senden-Button während des Streamings): aktuelle Generierung abbrechen
- Zusammenspiel Sprache (STT/TTS): Läuft die Wiedergabe (Speaker-Button einer Bubble), wird eine Aufnahme unterdrückt; startet die Wiedergabe während einer Aufnahme, stoppt die Aufnahme (Puffer wird verworfen); **Senden** stoppt die Aufnahme, leert die Chat-Zeile und verwirft den Aufnahme-Puffer; erneuter Klick auf den Speaker-Button stoppt die Wiedergabe

## 3. Message-Bubbles

Eigenschaften je Bubble:

| Eigenschaft | Beschreibung |
| --- | --- |
| Text | Nachrichteninhalt, bei Markdown einfache Formatierung optional |
| Rolle | `user`, `assistant`, `system` |
| Typ | `message`, `toolcall`, `reasoning` (Thinking), `toolresult` (Tool-Ergebnis) |
| Sortierung | chronologisch nach Zeitstempel (ms-Aufloesung: jeder Stream-Block erhaelt beim Typwechsel im LLM-Stream seinen Abschluss-Zeitstempel als `created_at`); bei Gleichstand nach Turn (jede User-Message eroeffnet einen neuen Turn); innerhalb eines Turns: Reasoning/Toolcall/Toolresult vor der finalen Assistant-Message, Toolcall vor Toolresult, sonst Einfuegereihenfolge (id) |
| Dreistufig ausklappbar | Toggle in der Kopfzeile wechselt zyklisch: `normal` (max. 10 **gerenderte GUI-Zeilen** via CSS line-clamp, Rest hinter `[...]`), `full` (kompletter Text), `collapsed` (genau **1 gerenderte GUI-Zeile**, auch bei langer umgebrochener Zeile); Standard: `message` = normal, alle anderen Typen (`reasoning`, `toolcall`, Tool-Ergebnisse) = collapsed; im Modus `full` sitzt unten rechts in der Bubble ein Einklapp-Button, der direkt auf `collapsed` wechselt. Ist die Bubble in `normal` nicht gekuerzt (weder per CSS line-clamp abgeschnitten noch mit `[...]`), ist `full` identisch mit `normal` — Toggle und Tap springen dann direkt von `normal` auf `collapsed`; von `collapsed` geht es immer auf `normal`. Im Minimalismus auf Touch-Geraeten wechselt stattdessen ein **einfacher Tap** auf die Bubble zyklisch (`normal` → `full` → `collapsed` → `normal` bzw. bei ungekuerzter Bubble `normal` → `collapsed` → `normal`, Scroll-Gesten nicht); der **Doppel-Tap** oeffnet das Kontextmenue als eigene Aktion (ohne Modus-Wechsel) |
| Mindestzeilenanzahl | Bubbles behalten eine Mindesthöhe, damit kurze Nachrichten das Layout nicht springen lassen |
| Kopieren | Kopier-Symbol kopiert den Inhalt in die Zwischenablage (`navigator.clipboard`; bei Fehler Fehlermeldung) |
| Bearbeiten | Stift-Symbol nur auf der letzten Nutzernachricht: Inline-Edit direkt in der Bubble (Textarea in den Bubble-Farben mit X-Button rechts daneben, Enter sendet, Esc bricht ab); beim Senden wird die Nachricht per `PATCH` aktualisiert, alle Nachrichten danach per `DELETE /api/sessions/{id}/messages/after/{mid}` gelöscht und die Antwort neu generiert |
| Erneut senden | Refresh-Symbol nur auf der letzten Nutzernachricht: dasselbe wie **Bearbeiten ohne Textänderung** – die Nachricht wird per `PATCH` unverändert übernommen, alle Nachrichten danach gelöscht und die Antwort neu generiert |
| Vorlesen | Audio-Symbol: Vorlesen per `speechSynthesis`/Voice Companion, erneuter Klick stoppt die Wiedergabe (ohne Fehlermeldung); Wiedergabe stoppt eine laufende Aufnahme und unterdrückt den Aufnahme-Start. Im Minimalismus stoppt stattdessen ein **Doppel-Tap/Doppelklick** auf eine Bubble bzw. die **Esc-Taste** die laufende Wiedergabe (dann kein Kontextmenue, kein Expand-Wechsel); der einfache Tap/Klick bleibt reiner Expand-Wechsel, der Doppel-Tap oeffnet ohne laufende Wiedergabe weiterhin nur das Kontextmenue |
| Kontext-Checkbox | Rechts oben auf allen Bubble-Typen außer `reasoning` (also auch `toolcall`/`toolresult`); legt fest, ob die Nachricht beim nächsten Request im `messages`-Array mitgesendet wird |
| Löschen | Mülleimer-Symbol entfernt die Nachricht aus der Session |

Darstellung nach Typ:

- **message**: normale Bubble mit Text
- **reasoning/thinking**: schlichter, gedämpfter Stil, Label „Thinking", mitkimmt optional ins `reasoning`-Feld bzw. wird nicht gesendet
- **toolcall**: monospace, zeigt Werkzeugnamen und Argumente (falls vom Endpunkt geliefert)
- **toolresult**: monospace, zeigt das Tool-Ergebnis (`name: result`, falls Name geliefert), startet eingeklappt
- bei `toolcall`/`toolresult` werden literale `\n` (aus JSON-String-Literalen) als echte Zeilenumbrueche angezeigt und zaehlen bei der Kuerzung (`collapsed` = 1 Zeile + `[...]`)

## 4. Generierung und Fortschritt

- Die Generierung läuft **serverseitig** in einer Hintergrund-Task (`POST /api/chat` → `202`); das Session-Feld `generating` signalisiert den laufenden Stand. Persistiert wird **blockweise, nicht chunk-weise**: die per-user DB wird nicht pro Chunk entschlüsselt — ein Block wird erst als eigene Message-Zeile geschrieben, wenn er im Stream abgeschlossen ist (Typwechsel bzw. Stream-Ende; ein DB-Öffnen pro Block plus ein finales); der offene Block bleibt im Speicher und wird bei Abort/Fehler verworfen
- Der Client erhaelt die Live-Daten **ausschliesslich ueber die Service-Layer**: SSE-Stream `GET /api/chat/stream/{sid}` aus dem In-Memory-Zustand des MessageService — versionierte `state`-Events (seq + volle Message-Liste, Live-Messages mit `id: null`), dann `done`/`idle`; als Live-Overlay gerendert. Alle Mutationen laufen serverseitig als Schreib-Funnel ueber den Service (erst In-Memory, dann persistiert — write-through). Zusaetzlich pollt der Client `GET /api/sessions/{id}` und rendert die persistierten Nachrichten — der Poll bleibt Quelle der Wahrheit und ueberschreibt das Overlay (live im Vordergrund, nach App-Wechsel/Re-Attach per `visibilitychange`/`pageshow` sofort)
- Client-seitige Mutationen (Senden, Bearbeiten/Erneut senden, Löschen, Kontext-Checkbox) werden nach erfolgreicher Endpoint-Antwort lokal auf die gecachte History der aktiven Session angewendet (keyed by message id, `state.messages` in `state.js`); das Session-Detail wird nur noch bei Session-Wechsel und per Poll geladen — der Poll bleibt Quelle der Wahrheit und überschreibt den lokalen Stand
- `delta.content` landet in der Assistant-Message, `delta.reasoning_content` / `reasoning` in einer separaten Thinking-Bubble, `tool_calls` als Toolcall-Bubbles, `tool_results` als Toolresult-Bubbles — serverseitig persistiert; **jeder Block-Folge im Stream (z. B. Reasoning → Toolcall → Toolresult → Message → Reasoning → …) wird eine eigene Message-Zeile** zugewiesen (keine Akkumulation ueber den Stream), mit Abschluss-Zeitstempel (ms) beim Typwechsel bzw. am Stream-Ende; ein `tool_results`-Item mit `signal`-Feld (z. B. `"toolcall_done"`) ist ein reines Signal des LLM-Servers: es schliesst den offenen Block (Toolcall-Bubble wird vor dem Tool-Ergebnis sichtbar), erzeugt aber keine eigene Toolresult-Zeile
- Anzeige-Settings (`show_reasoning`, `show_tool_output`) sind reine Render-Einstellungen des Clients (`visibility.js`): der LLM-Response-Stream wird serverseitig nie gefiltert und Reasoning/Toolcalls/Toolresults werden immer persistiert — abgewählte Anzeige löscht nichts aus der DB, Wiedereinblenden zeigt die persistierten Bubbles sofort wieder
- Die Chat-History wird **serverseitig aus der Session-DB** gebaut (`build_llm_context`, trixie `LlmContext`): System-Prompt zuerst, dann Nachrichten in Reihenfolge; Toolcalls als `assistant`-Message mit `tool_calls`, Tool-Ergebnisse als gepaarte `tool`-Message (`tool_call_id`) — das Modell kann so Tool-Calls von normalem Text unterscheiden; Nachrichten mit `in_context=false` (z. B. Reasoning, Fehler) werden nicht gesendet. **Alle Toolcalls einer Gruppe (z. B. parallele Toolcalls eines Deep-Research-Schritts) landen in einem einzigen `assistant`-Message, direkt gefolgt von ihren `tool`-Messages; unvollstaendige Paare (Toolcall ohne Toolresult, z. B. per Kontext-Checkbox abgewahlt) werden ganz verworfen**, damit das Request gegenueber strikten LLM-Servern gueltig bleibt (sonst 422 bzw. das Modell sieht die Tool-Ergebnisse nicht). Zwei weitere 422-Fallen strikter Server werden vermieden: reine tool_call-Messages senden `content: ""` (leerer String statt null/fehlendem Feld — passiert jedes Pydantic-Modell), und die tool_calls werden in eine unmittelbar vorausgehende assistant-Content-Message gemergt (keine zwei `assistant`-Messages hintereinander)
- Leerer System-Prompt: keine System-Bubble im Chat und keine leere `system`-Message im LLM-Request (sonst HTTP 422 vom LLM) — gilt auch für Whitespace-only; eine Session-System-Message mit identischem Text wie der Settings-Prompt wird weder doppelt gerendert noch doppelt gesendet
- Während der Generierung: dezente **Progress-Anzeige** (Ladebalken), angesteuert über das serverseitige `generating`-Flag
- Abbrechen per X-Symbol (Header/Side-Panel und Composer) via `POST /api/chat/abort`: das Abort-Event wird in der Generierungs-Task gegen den Upstream-Read geracet, die LLM-Verbindung wird sofort geschlossen (auch wenn keine Chunks mehr eintreffen); die bis dahin generierte Antwort bleibt in der Session erhalten
- Abbrechen setzt `generating` serverseitig auf 0 — sofort im Endpoint, wenn keine Generierungs-Task läuft (verwaistes Flag, z. B. nach Server-Neustart mitten im Stream), sonst beim finalen Flush der Task; ein verwaistes `generating`-Flag wird außerdem beim nächsten `POST /api/chat` im Service unter dem Session-Lock geheilt (dort läuft sicher keine Task) — der nächste Start liefert dann nicht endlos 409, und der Client persistiert für 409 kein Fehler-Bubble, sondern hängt sich an den laufenden Stream; der Client zeigt den Abbrechen-Button statt des Senden-Buttons, solange die aktive Session `generating=1` meldet (auch nach Reload)

## 5. Einstellungen

Zwei Tabs im Settings-Overlay:

- **Allgemein**: **Theme** (hell/dunkel, Standard hell, umgeschaltet per CSS-Klasse und `prefers-color-scheme` als Initial-Fallback), globaler **System-Prompt**, Darstellungsschalter (Bubbles Deletable/Checkable/Speaker, Show System Prompt/Tool Output/Reasoning, Datei-/Bild-Button), Sprache (STT/TTS)
- **LLM**: Raster aus **Modell-Tiles** (`model-tile-<id>`) nebeneinander plus ein **Neues Modell**-Tile (`model-add-tile`). Klick/Tap auf ein Tile setzt es als **Standard** (Radio + Klick tun dasselbe); das Stift-Icon (`model-edit-btn-<id>`) bzw. das Add-Tile oeffnet ein Modal mit: **Anbieter** (freies Label, optional), **Host**, **Port**, **Base-URL** (berechnet, readonly), **Verbindung testen**, **API-Schlüssel** (Passwortfeld, serverseitig gespeichert, write-only), **Modell**, sowie **Löschen** (nur beim Bearbeiten), **Abbrechen**, **Speichern**. Das Standard-Tile steht in `user_settings.default_model_id` und wird von neuen Sessions genutzt, solange die Session kein eigenes `model_id` setzt.

Speicherung: serverseitig in der verschlüsselten per-user SQLite (`user_settings`, `session_settings`, `llm_models`; `api_key` nur in `llm_models` und nie in API-Antworten); nur UI-Zustand (aktives Panel) liegt im `localStorage`/`sessionStorage` (Key `leanchat.*`).

LLM-Modell-Endpunkte (`app/routers/models.py`, alle hinter Auth): `GET/POST /api/settings/models`, `GET/PUT/DELETE /api/settings/models/{id}`, `POST /api/settings/models/test` (optionale `model_id`-Referenz; explizite `base`/`api_key` im Body gewinnen sonst gegen das Tile bzw. die Server-Defaults; `model` nur aus dem Body – fehlt es, wird nur die Erreichbarkeit geprueft und kein Modell-Fehler gemeldet; SSRF-Validierung wie bisher). Der Test (`GET {base}/models`) unterscheidet in `detail`: nicht erreichbar (Connect/Timeout), `HTTP 401` = API-Schlüssel ungültig, `HTTP 403` = Zugriff verweigert, sonst `HTTP <code>` (Upstream-Body wird nie durchgereicht), sowie „Modell nicht verfügbar“ samt der angebotenen Modellliste, wenn das Modell nicht in `/models` gelistet ist. Die Antwort enthaelt ausserdem `models`: die Liste der angebotenen Modell-IDs – ist das Modell-Feld im Modal leer und der Test erfolgreich, wird das Feld dadurch zum Dropdown (`model-model-select`) mit genau diesen Optionen. Das erste angelegte Tile wird automatisch zum Standard; beim Löschen des Standard-Tiles wird `default_model_id` auf ein verbleibendes Tile neu gesetzt (oder geleert). Beim Oeffnen einer bestehenden per-user DB werden alte flache LLM-Keys (`base`/`host`/`port`/`model`/`api_key` aus `user_settings`) einmalig in ein Tile migriert und entfernt (`q_migrate_legacy_llm_settings`).

Effektive LLM-Verbindung beim Chat (`resolve_llm_connection` in `app/services/settings.py`): Session-`model_id` > User-`default_model_id` > Server-Defaults (`LEANCHAT_LLM_HOST/PORT/MODEL/API_KEY`); Base-URL eines Tiles: aus Host/Port berechnet > gespeicherte `base` > Server-Default. Ungueltige Tile-Referenzen (z. B. nach dem Löschen) fallen auf die naechste Stufe zurueck.

### Session-Einstellungen (pro Session)

- Zahnrad-Button oben links im Chat-Panel (nur bei aktiver Session sichtbar) oeffnet ein Modal im App-Stil mit: **System-Prompt** (Textarea, ueberschreibt den globalen Settings-Prompt fuer diese Session, leer = globaler Prompt), **Modell** (Select aller Tiles; leer/"Standard" = Standard-Tile des Users), **Tool-Nutzung** (vorbereitet, vorerst leer/deaktiviert), sowie **Speichern** und **Abbrechen**
- Speichern: `PUT /api/sessions/{id}/settings` (Tabelle `session_settings`, key/value; leerer String loescht Session-Prompt/-Modell); Laden: `GET /api/sessions/{id}/settings` beim Oeffnen des Modals sowie ueber das Session-Detail `GET /api/sessions/{id}` (Feld `settings`) beim Session-Wechsel; Abbrechen/Overlay-Klick/Esc: Modal schliessen ohne API-Aufruf (keine Aenderungen); `model_id` muss auf ein bestehendes Tile zeigen (sonst 422)
- Der Session-System-Prompt wird beim naechsten `POST /api/chat` als effektiver System-Prompt an den LLM-Request gehaengt (Override-Regel siehe Abschnitt 4) und als System-Bubble oben im Chat gerendert (bei `show_system_prompt` an); das Session-`model_id` bestimmt zusammen mit `default_model_id` die effektive LLM-Verbindung des Requests

## 6. Design

- Elegant-minimalistisch: viel Weißraum, dezente Grautöne, ein Akzentton
- Helles Theme: weiß/hellgrau Hintergründe, dunkler Text; dunkles Theme: entsättigt-dunkle Flächen, heller Text
- Schmale Typografie (system-ui), kleine Icons (inline SVG), abgerundete Ecken, dezente Schatten
- Voll responsiv; auf Mobilgeräten überlagert das Side-Panel den Chat

## 7. Technische Rahmenbedingungen

- FastAPI-Backend (`app/`) + statisches Frontend (`static/`, ES-Module ohne Build-Tools)
- Datei-Uploads per Multipart (`POST /api/sessions/{id}/attachments`), serverseitige Verarbeitung
- OpenAI-kompatibles Protokoll: `POST {baseURL}/chat/completions`, `Authorization: Bearer {key}`
- Fehlerbehandlung: Netzwerk-/Auth-Fehler als System-Bubble im Chat; antwortet das LLM mit HTTP 422 (z. B. zu großer Request-Body), wird ein System-Bubble mit Hinweis auf die Kontext-Checkbox persistiert (ältere Nachrichten abwählbar, `in_context=false`); ein `toolresult` ohne passenden `toolcall` wird serverseitig verworfen, damit der Request gültig bleibt
- App-Zustand serverseitig in der verschlüsselten per-user DB persistiert
- SSRF-Schutz: LLM-Ziel-URLs werden serverseitig validiert (nur http/https ohne Credentials; private/Loopback-/reservierte Ziele nur bei Loopback-Server oder explizitem Opt-in `LEANCHAT_ALLOW_PRIVATE_LLM`); Upstream-Fehler-Bodies werden nicht an den Client weitergegeben
- DoS-Limits: Upload-Größe (gestreamtes Lesen), per-user Attachment-Kontingent und `/api/*`-Request-Größe sind serverseitig begrenzt (HTTP 413)
