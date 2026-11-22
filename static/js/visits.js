import { api } from "./api.js";
import { state } from "./state.js";
import { openSession } from "./sessions.js";

// In-App-Views der SPA (gleiche URL "/", anderer Zustand) werden als Hash kodiert
// ("/#s/<id>") und zusaetzlich serverseitig im Visit-Stack der Session gemeldet,
// damit die Zurueck-Taste auch innerhalb der App zur zuletzt besuchten Seite
// zurueckfuehrt (statt z. B. auf /auth/login zu landen).
let suppressViewPush = false;

export function viewPath() {
  return state.activeId ? `/#s/${state.activeId}` : "/";
}

export function sessionIdFromHash(hash) {
  const m = /^#\/s\/([^/]+)$/.exec(hash || "");
  return m ? decodeURIComponent(m[1]) : null;
}

function report(path) {
  api.post("/visits", { path }).catch(() => {});
}

export function pushView() {
  if (suppressViewPush) return;
  const path = viewPath();
  history.pushState({ lcView: path }, "", path);
  report(path);
}

export function replaceView() {
  const path = viewPath();
  history.replaceState({ lcView: path }, "", path);
  report(path);
}

export function initViewHistory() {
  window.addEventListener("popstate", () => {
    const id = sessionIdFromHash(location.hash);
    if (id && id !== state.activeId && state.sessions.some((s) => s.id === id)) {
      suppressViewPush = true;
      openSession(id);
      suppressViewPush = false;
    }
  });
}
