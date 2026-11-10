# LeanChat – Spezifikation

Eine schlanke, eigenständige Chat-Oberfläche für OpenAI-kompatible Endpunkte. Alternative zu OpenWebUI, bewusst minimalistisch gehalten.

## 1. Ziele und Nicht-Ziele

**Ziele**

- Eine einzige, self-contained HTML-Datei (HTML + CSS + JavaScript, keine externen Abhängigkeiten)
- Streaming von OpenAI-kompatiblen Endpunkten (`/v1/chat/completions`, SSE)
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

- Liste von Sessions als chronologisch sortierte Tiles (neueste zuerst)
- Erstes Tile: **„Neue Session"** mit Plus-Symbol – legt eine neue Session an und öffnet sie
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
  - **Plus-Symbol**: Datei anhängen (Auswahl über Datei-Dialog; Dateien werden als Anhang angezeigt und als Text-/Bildinhalt in die Nachricht eingebettet)
  - **Kamera-Symbol**: Foto aufnehmen (`<input type="file" accept="image/*" capture="environment">`, primär für Mobilgeräte)
  - **Mikro-Symbol**: Nachricht diktieren (Web Speech API `SpeechRecognition`, falls verfügbar; sonst ausgeblendet/deaktiviert)
  - **X-Symbol** (ersetzt Senden-Button während des Streamings): aktuelle Generierung abbrechen

## 3. Message-Bubbles

Eigenschaften je Bubble:

| Eigenschaft | Beschreibung |
| --- | --- |
| Text | Nachrichteninhalt, bei Markdown einfache Formatierung optional |
| Rolle | `user`, `assistant`, `system` |
| Typ | `message`, `toolcall`, `reasoning` (Thinking) |
| Ein-/Ausklappbar | Kopfzeile bleibt sichtbar, Körper kollabierbar; Standard: `message`/`user`/`assistant` offen, `reasoning`/`toolcall` eingeklappt |
| Mindestzeilenanzahl | Bubbles behalten eine Mindesthöhe, damit kurze Nachrichten das Layout nicht springen lassen |
| Kopieren | Kopier-Symbol kopiert den Inhalt in die Zwischenablage (`navigator.clipboard`, Fallback `execCommand`) |
| Vorlesen | Audio-Symbol: Vorlesen per `speechSynthesis`, erneuter Klick stoppt |
| Kontext-Checkbox | Rechts oben; legt fest, ob die Nachricht beim nächsten Request im `messages`-Array mitgesendet wird |
| Löschen | Mülleimer-Symbol entfernt die Nachricht aus der Session |

Darstellung nach Typ:

- **message**: normale Bubble mit Text
- **reasoning/thinking**: schlichter, gedämpfter Stil, Label „Thinking", mitkimmt optional ins `reasoning`-Feld bzw. wird nicht gesendet
- **toolcall**: monospace, zeigt Werkzeugnamen und Argumente (falls vom Endpunkt geliefert)

## 4. Streaming und Fortschritt

- Requests per `fetch` mit `stream: true`, Auswertung von SSE-Zeilen (`data: {...}`, `data: [DONE]`)
- `delta.content` wird Chunk-weise angehängt und live gerendert
- `delta.reasoning_content` / `reasoning` (falls geliefert) landet in einer separaten Thinking-Bubble
- Während der Generierung: dezente **Progress-Anzeige** (Ladebalken/indikator im Composer-Bereich, z. B. animierter Balken oder pulsierender Punkt)
- Abbrechen per X-Symbol (sowohl im Header/Side-Panel als auch im Composer) via `AbortController`; die bis dahin gestreamte Antwort bleibt in der Session erhalten

## 5. Einstellungen

Dialog (Modal) mit Feldern:

- **Base-URL** (z. B. `https://api.openai.com/v1`)
- **API-Schlüssel** (Passwortfeld, lokal gespeichert)
- **Modell** (freie Texteingabe oder Auswahl aus `/v1/models`, wenn erreichbar)
- **Theme**: hell / dunkel (Standard hell), umgeschaltet per CSS-Klasse und `prefers-color-scheme` als Initial-Fallback

Speicherung: `localStorage` für Einstellungen und Sessions (Key `leanchat.*`).

## 6. Design

- Elegant-minimalistisch: viel Weißraum, dezente Grautöne, ein Akzentton
- Helles Theme: weiß/hellgrau Hintergründe, dunkler Text; dunkles Theme: entsättigt-dunkle Flächen, heller Text
- Schmale Typografie (system-ui), kleine Icons (inline SVG), abgerundete Ecken, dezente Schatten
- Voll responsiv; auf Mobilgeräten überlagert das Side-Panel den Chat

## 7. Technische Rahmenbedingungen

- Single-File: `index.html` mit inline `<style>` und `<script>`
- Keine externen Ressourcen, keine Build-Tools
- OpenAI-kompatibles Protokoll: `POST {baseURL}/chat/completions`, `Authorization: Bearer {key}`
- Fehlerbehandlung: Netzwerk-/Auth-Fehler als System-Bubble im Chat
- Alle Zustandsmutationen sofort in `localStorage` persistiert
