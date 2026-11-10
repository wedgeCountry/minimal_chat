# LeanChat

A lean, single-file chat UI for OpenAI-compatible endpoints. No build tools, no dependencies, no backend: one `index.html` you can open directly in your browser.

Born as a minimalist alternative to OpenWebUI: only the features you actually need, an elegant light/dark theme, and nothing else.

## Features

- **Sessions** – collapsible side panel with chronologically sorted session tiles; create, rename (inline), delete
- **Streaming** – SSE chunk streaming from any OpenAI-compatible endpoint, rendered live, with an animated progress bar
- **Cancel** – abort a running generation via the X button (Send button or side panel); partial output is kept
- **Message bubbles** – role (user/assistant/system) and type (message, tool-call, reasoning/thinking), collapsible, minimum height, copy-to-clipboard, text-to-speech
- **Context control** – per-message checkbox decides whether it is included in the next request
- **Attachments** – attach files via the + button, capture photos via camera (mobile), dictate messages via microphone (Web Speech API)
- **Settings** – base URL, API key, model, theme (light by default)
- **Logout** – wipes the local key, settings and sessions
- **Persistence** – sessions and settings are stored in `localStorage`

## Getting started

1. Download `index.html` (or clone this repository)
2. Open it in your browser
3. Open the burger menu → **Einstellungen**, enter your **Base-URL**, **API key** and **model** (e.g. `https://api.openai.com/v1` and `gpt-4o-mini`)
4. Start chatting

> **Note:** the endpoint must allow CORS for requests from your browser origin. When in doubt, serve the file from the same origin as your API or use a small proxy.

## Specification

See [SPEC.md](SPEC.md) for the full design specification (German).

## Tech

- Single file: inline CSS and vanilla JavaScript
- OpenAI-compatible protocol: `POST {baseURL}/chat/completions`, `Authorization: Bearer {key}`, `stream: true`
- Supports `delta.content`, `delta.reasoning_content` (thinking bubbles) and `delta.tool_calls`
- Light/dark theme via CSS custom properties, default light, follows system preference until configured

## License

MIT
