import test from "node:test";
import assert from "node:assert/strict";

function makeEl() {
  const classes = new Set();
  return {
    textContent: "",
    onclick: null,
    classes,
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    addEventListener() {},
  };
}

function stubDom() {
  const els = {};
  for (const id of ["confirmOverlay", "confirmCancel", "confirmOk", "confirmTitle", "confirmText", "errorOverlay", "errorOk", "errorTitle", "errorText"]) {
    els[id] = makeEl();
  }
  const docListeners = {};
  globalThis.document = {
    getElementById: (id) => els[id] || null,
    addEventListener: (type, fn) => {
      (docListeners[type] ||= []).push(fn);
    },
    dispatchEvent: () => {},
  };
  return { els, docListeners };
}

const { initConfirm, confirmModal, showError } = await import("../../static/js/confirm.js");

test("confirmModal resolves true on OK and closes the overlay", async () => {
  const { els } = stubDom();
  initConfirm();
  const p = confirmModal({ title: "Session loeschen", text: "Wirklich?", okLabel: "Ja" });
  assert.equal(els.confirmTitle.textContent, "Session loeschen");
  assert.equal(els.confirmOk.textContent, "Ja");
  assert.ok(els.confirmOverlay.classList.contains("open"));
  els.confirmOk.onclick();
  assert.equal(await p, true);
  assert.equal(els.confirmOverlay.classList.contains("open"), false);
});

test("confirmModal resolves false on cancel and on Escape", async () => {
  const { els, docListeners } = stubDom();
  initConfirm();
  const p1 = confirmModal({ title: "t", text: "x" });
  els.confirmCancel.onclick();
  assert.equal(await p1, false);

  const p2 = confirmModal({ title: "t", text: "x" });
  assert.ok(els.confirmOverlay.classList.contains("open"));
  for (const fn of docListeners.keydown || []) fn({ key: "Escape" });
  assert.equal(await p2, false);
});

test("showError opens the error overlay and resolves on OK", async () => {
  const { els } = stubDom();
  initConfirm();
  const p = showError("kaputt");
  assert.equal(els.errorText.textContent, "kaputt");
  assert.ok(els.errorOverlay.classList.contains("open"));
  els.errorOk.onclick();
  await p;
  assert.equal(els.errorOverlay.classList.contains("open"), false);
});

test("showError auto-closes after the given timeout", async () => {
  const { els } = stubDom();
  initConfirm();
  const p = showError("kurz", 20);
  assert.ok(els.errorOverlay.classList.contains("open"));
  await p;
  assert.equal(els.errorOverlay.classList.contains("open"), false);
});
