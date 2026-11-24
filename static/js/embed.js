// ?embed=1: App als reines Chat-Panel (ohne Header/Side-Panel) rendern, z. B.
// fuer die Einbettung in eine andere App per WebView/iframe. Das Ausblenden
// passiert per CSS-Klasse auf <html>, damit das bestehende Event-Wiring in
// main.js unveraendert bleibt.
export function isEmbedMode(search) {
  return new URLSearchParams(search).has("embed");
}

export function applyEmbedMode(search = location.search, doc = document) {
  if (isEmbedMode(search)) doc.documentElement.classList.add("embed");
}
