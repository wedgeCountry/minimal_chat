import test from "node:test";
import assert from "node:assert/strict";

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const { state, setActiveId } = await import("../../static/js/state.js");
const { getDraft, saveDraft, clearDraft, syncDraftInput } = await import("../../static/js/drafts.js");

function stubInput() {
  const input = {
    value: "",
    dispatched: [],
    dispatchEvent(e) {
      this.dispatched.push(e.type);
    },
  };
  globalThis.document = { getElementById: (id) => (id === "input" ? input : null) };
  return input;
}

test("saveDraft/getDraft: Entwurf pro Session im localStorage (Key leanchat.drafts)", () => {
  saveDraft("s1", "Hallo A");
  saveDraft("s2", "Hallo B");
  assert.equal(getDraft("s1"), "Hallo A");
  assert.equal(getDraft("s2"), "Hallo B");
  assert.deepEqual(JSON.parse(store.get("leanchat.drafts")), { s1: "Hallo A", s2: "Hallo B" });
  assert.equal(getDraft("unbekannt"), "");
  assert.equal(getDraft(null), "");
});

test("saveDraft mit leerem Text entfernt den Key (Map waechst nicht)", () => {
  store.clear();
  saveDraft("s1", "Hallo A");
  saveDraft("s1", "");
  assert.equal(getDraft("s1"), "");
  assert.deepEqual(JSON.parse(store.get("leanchat.drafts")), {});
});

test("clearDraft entfernt genau die uebergebene Session", () => {
  store.clear();
  saveDraft("s1", "A");
  saveDraft("s2", "B");
  clearDraft("s1");
  assert.equal(getDraft("s1"), "");
  assert.equal(getDraft("s2"), "B");
  clearDraft("s1"); // nochmal: kein Fehler, kein Schreibzugriff noetig
  assert.equal(getDraft("s2"), "B");
});

test("syncDraftInput: Session-Wechsel laedt den Entwurf der neuen Session in den Composer", () => {
  const input = stubInput();
  store.clear();

  // Session A aktiv, Entwurf wird per input-Event gespeichert (wie in main.js)
  setActiveId("a");
  syncDraftInput();
  assert.equal(input.value, "", "neue Session ohne Entwurf: Composer leer");
  assert.deepEqual(input.dispatched, ["input"]);

  input.value = "Entwurf A";
  saveDraft(state.activeId, input.value); // main.js: input-Event -> saveDraft
  input.dispatched.length = 0;

  // Wechsel zu Session B (ohne eigenen Entwurf)
  setActiveId("b");
  syncDraftInput();
  assert.equal(input.value, "", "Draft wird nicht in die andere Session uebernommen");
  assert.deepEqual(input.dispatched, ["input"]);

  input.value = "Entwurf B";
  saveDraft(state.activeId, input.value);
  input.dispatched.length = 0;

  // Zurueck zu Session A: Entwurf ist wieder da
  setActiveId("a");
  syncDraftInput();
  assert.equal(input.value, "Entwurf A");

  // Erneutes Rendern ohne Session-Wechsel darf den Composer nicht ueberschreiben
  input.value = "Entwurf A editiert";
  syncDraftInput();
  assert.equal(input.value, "Entwurf A editiert");

  // Keine aktive Session: Composer leer
  setActiveId(null);
  syncDraftInput();
  assert.equal(input.value, "");
});

test("syncDraftInput: nach Reload (frischer Modulzustand) wird der Entwurf der aktiven Session geladen", async () => {
  store.clear();
  store.set("leanchat.drafts", JSON.stringify({ s9: "persistierter Entwurf" }));
  const input = stubInput();
  // Frischer Modulzustand wie nach Reload: eigener Import per Query-Parameter
  // (teilt sich aber state.js, daher die originale setActiveId)
  const fresh = await import("../../static/js/drafts.js?reload=1");
  setActiveId("s9");
  fresh.syncDraftInput();
  assert.equal(input.value, "persistierter Entwurf");
});
