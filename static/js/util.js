export const $ = (id) => document.getElementById(id);

export const isMobileInput = () =>
  (window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches) ||
  "ontouchstart" in window;

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[c]));
