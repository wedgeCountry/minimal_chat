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
| Sortierung | chronologisch nach Zeitstempel; bei Gleichstand (Sekundenaufloesung) nach Turn (jede User-Message eroeffnet einen neuen Turn); innerhalb eines Turns: Reasoning/Toolcall/Toolresult vor der finalen Assistant-Message, Toolcall vor Toolresult, sonst Einfuegereihenfolge (id) |
| Dreistufig ausklappbar | Toggle in der Kopfzeile wechselt zyklisch: `normal` (max. 10 **gerenderte GUI-Zeilen** via CSS line-clamp, Rest hinter `[...]`), `full` (kompletter Text), `collapsed` (genau **1 gerenderte GUI-Zeile**, auch bei langer umgebrochener Zeile); Standard: `message` = normal, alle anderen Typen (`reasoning`, `toolcall`, Tool-Ergebnisse) = collapsed |
| Mindestzeilenanzahl | Bubbles behalten eine Mindesthöhe, damit kurze Nachrichten das Layout nicht springen lassen |
| Kopieren | Kopier-Symbol kopiert den Inhalt in die Zwischenablage (`navigator.clipboard`; bei Fehler Fehlermeldung) |
| Bearbeiten | Stift-Symbol nur auf der letzten Nutzernachricht: Inline-Edit direkt in der Bubble (Textarea in den Bubble-Farben mit X-Button rechts daneben, Enter sendet, Esc bricht ab); beim Senden wird die Nachricht per `PATCH` aktualisiert, alle Nachrichten danach per `DELETE /api/sessions/{id}/messages/after/{mid}` gelöscht und die Antwort neu generiert |
| Erneut senden | Refresh-Symbol nur auf der letzten Nutzernachricht: dasselbe wie **Bearbeiten ohne Textänderung** – die Nachricht wird per `PATCH` unverändert übernommen, alle Nachrichten danach gelöscht und die Antwort neu generiert |
| Vorlesen | Audio-Symbol: Vorlesen per `speechSynthesis`/Voice Companion, erneuter Klick stoppt die Wiedergabe (ohne Fehlermeldung); Wiedergabe stoppt eine laufende Aufnahme und unterdrückt den Aufnahme-Start |
| Kontext-Checkbox | Rechts oben; legt fest, ob die Nachricht beim nächsten Request im `messages`-Array mitgesendet wird |
| Löschen | Mülleimer-Symbol entfernt die Nachricht aus der Session |

Darstellung nach Typ:

- **message**: normale Bubble mit Text
- **reasoning/thinking**: schlichter, gedämpfter Stil, Label „Thinking", mitkimmt optional ins `reasoning`-Feld bzw. wird nicht gesendet
- **toolcall**: monospace, zeigt Werkzeugnamen und Argumente (falls vom Endpunkt geliefert)
- **toolresult**: monospace, zeigt das Tool-Ergebnis (`name: result`, falls Name geliefert), startet eingeklappt
- bei `toolcall`/`toolresult` werden literale `\n` (aus JSON-String-Literalen) als echte Zeilenumbrueche angezeigt und zaehlen bei der Kuerzung (`collapsed` = 1 Zeile + `[...]`)

## 4. Generierung und Fortschritt

- Die Generierung läuft **serverseitig** in einer Hintergrund-Task (`POST /api/chat` → `202`, Task persistiert den LLM-SSE-Stream chunk-weise in die Session-DB); das Session-Feld `generating` signalisiert den laufenden Stand
- Der Client hält **keinen** LLM-Stream mehr, sondern pollt `GET /api/sessions/{id}` und rendert die persistierten Nachrichten (live im Vordergrund, nach App-Wechsel/Re-Attach per `visibilitychange`/`pageshow` sofort)
- `delta.content` landet in der Assistant-Message, `delta.reasoning_content` / `reasoning` in einer separaten Thinking-Bubble, `tool_calls` als Toolcall-Bubbles, `tool_results` als Toolresult-Bubbles — serverseitig persistiert
- Die Chat-History wird **serverseitig aus der Session-DB** gebaut (`build_llm_context`, trixie `LlmContext`): System-Prompt zuerst, dann Nachrichten in Reihenfolge; Toolcalls als `assistant`-Message mit `tool_calls`, Tool-Ergebnisse als gepaarte `tool`-Message (`tool_call_id`) — das Modell kann so Tool-Calls von normalem Text unterscheiden; Nachrichten mit `in_context=false` (z. B. Reasoning, Fehler) werden nicht gesendet
- Leerer System-Prompt: keine System-Bubble im Chat und keine leere `system`-Message im LLM-Request (sonst HTTP 422 vom LLM)
- Während der Generierung: dezente **Progress-Anzeige** (Ladebalken), angesteuert über das serverseitige `generating`-Flag
- Abbrechen per X-Symbol (Header/Side-Panel und Composer) via `POST /api/chat/abort`: das Abort-Event wird in der Generierungs-Task gegen den Upstream-Read geracet, die LLM-Verbindung wird sofort geschlossen (auch wenn keine Chunks mehr eintreffen); die bis dahin generierte Antwort bleibt in der Session erhalten

## 5. Einstellungen

Dialog (Modal) mit Feldern:

- **Base-URL** (z. B. `https://api.openai.com/v1`)
- **API-Schlüssel** (Passwortfeld, lokal gespeichert)
- **Modell** (freie Texteingabe oder Auswahl aus `/v1/models`, wenn erreichbar)
- **Theme**: hell / dunkel (Standard hell), umgeschaltet per CSS-Klasse und `prefers-color-scheme` als Initial-Fallback

Speicherung: serverseitig in der verschlüsselten per-user SQLite (`user_settings`); nur UI-Zustand (aktives Panel, Bubble-Breiten) liegt im `localStorage`/`sessionStorage` (Key `leanchat.*`).

## 6. Design

- Elegant-minimalistisch: viel Weißraum, dezente Grautöne, ein Akzentton
- Helles Theme: weiß/hellgrau Hintergründe, dunkler Text; dunkles Theme: entsättigt-dunkle Flächen, heller Text
- Schmale Typografie (system-ui), kleine Icons (inline SVG), abgerundete Ecken, dezente Schatten
- Voll responsiv; auf Mobilgeräten überlagert das Side-Panel den Chat

## 7. Technische Rahmenbedingungen

- FastAPI-Backend (`app/`) + statisches Frontend (`static/`, ES-Module ohne Build-Tools)
- Datei-Uploads per Multipart (`POST /api/sessions/{id}/attachments`), serverseitige Verarbeitung
- OpenAI-kompatibles Protokoll: `POST {baseURL}/chat/completions`, `Authorization: Bearer {key}`
- Fehlerbehandlung: Netzwerk-/Auth-Fehler als System-Bubble im Chat
- App-Zustand serverseitig in der verschlüsselten per-user DB persistiert
- SSRF-Schutz: LLM-Ziel-URLs werden serverseitig validiert (nur http/https ohne Credentials; private/Loopback-/reservierte Ziele nur bei Loopback-Server oder explizitem Opt-in `LEANCHAT_ALLOW_PRIVATE_LLM`); Upstream-Fehler-Bodies werden nicht an den Client weitergegeben
- DoS-Limits: Upload-Größe (gestreamtes Lesen), per-user Attachment-Kontingent und `/api/*`-Request-Größe sind serverseitig begrenzt (HTTP 413)
