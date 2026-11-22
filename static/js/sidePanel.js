import { $ } from "./util.js";

// Beim Oeffnen des Side-Panels wird ein eigener History-Eintrag gepusht, damit
// die Zurueck-Taste des Browsers das Panel schliesst statt die Seite zu verlassen.
// updateHistory=false nur, wenn im selben Event gleich ein pushState folgt
// (z. B. Session-Wechsel): history.back() ist asynchron und wuerde mit dem
// pushState racen und die URL wieder zuruecksetzen.
export function setSideHidden(hidden, updateHistory = true) {
  const side = $("side");
  const wasHidden = side.classList.contains("hidden");
  side.classList.toggle("hidden", hidden);
  if (!updateHistory) return;
  if (!hidden && wasHidden) {
    history.pushState({ sidePanelOpen: true }, "", location.pathname + location.search + location.hash);
  } else if (hidden && !wasHidden && history.state?.sidePanelOpen) {
    history.back(); // per UI geschlossen: gepushten Eintrag wieder entfernen
  }
}

export function initSidePanelHistory() {
  window.addEventListener("popstate", () => {
    // Panel offen -> Zurueck schliesst es. Klasse direkt toggeln (nicht ueber
    // setSideHidden), sonst wuerde der popstate erneut history.back() ausloesen.
    if (!$("side").classList.contains("hidden")) {
      $("side").classList.add("hidden");
    }
  });
}
