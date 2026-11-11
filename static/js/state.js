export const state = {
  token: sessionStorage.getItem("leanchat.token") || null,
  username: null,
  sessions: [],
  activeId: sessionStorage.getItem("leanchat.active") || null,
  settings: { base: "", model: "", theme: "light" },
  streaming: false,
  abortCtrl: null,
  pendingAttachments: [],
};

export const activeSession = () => state.sessions.find((s) => s.id === state.activeId) || null;

export function setActiveId(id) {
  state.activeId = id;
  if (id) sessionStorage.setItem("leanchat.active", id);
  else sessionStorage.removeItem("leanchat.active");
}
