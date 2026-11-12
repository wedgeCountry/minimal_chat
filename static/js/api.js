import { state } from "./state.js";

async function request(path, { method = "GET", body, raw = false, signal } = {}) {
  const headers = {};
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch("/api" + path, {
    method,
    headers,
    body: body !== undefined ? (isForm ? body : JSON.stringify(body)) : undefined,
    signal,
  });
  if (res.status === 401) {
    document.dispatchEvent(new CustomEvent("leanchat:unauthorized"));
    throw new Error("Nicht authentifiziert");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let msg = text || res.statusText;
    try {
      const data = JSON.parse(text);
      if (data && data.detail) msg = data.detail;
    } catch {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return raw ? res : res.json();
}

export const api = {
  get: (path) => request(path),
  post: (path, body, opts) => request(path, { method: "POST", body, ...opts }),
  postForm: (path, form) => request(path, { method: "POST", body: form }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  del: (path) => request(path, { method: "DELETE" }),
};
