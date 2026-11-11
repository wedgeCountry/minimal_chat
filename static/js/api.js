import { state } from "./state.js";

export function setToken(token) {
  state.token = token;
  if (token) sessionStorage.setItem("leanchat.token", token);
  else sessionStorage.removeItem("leanchat.token");
}

async function request(path, { method = "GET", body, raw = false, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch("/api" + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  if (res.status === 401) {
    setToken(null);
    document.dispatchEvent(new CustomEvent("leanchat:unauthorized"));
    throw new Error("Nicht authentifiziert");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || res.statusText);
  }
  return raw ? res : res.json();
}

export const api = {
  get: (path) => request(path),
  post: (path, body, opts) => request(path, { method: "POST", body, ...opts }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  del: (path) => request(path, { method: "DELETE" }),
};

export function streamChat(payload, signal) {
  return request("/chat", { method: "POST", body: payload, raw: true, signal });
}
