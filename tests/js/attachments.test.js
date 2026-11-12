import test from "node:test";
import assert from "node:assert/strict";

const attBox = {
  innerHTML: "",
  children: [],
  appendChild(el) {
    this.children.push(el);
  },
};
globalThis.document = {
  getElementById: (id) => (id === "attachments" ? attBox : null),
  createElement: () => ({
    className: "",
    dataset: {},
    innerHTML: "",
    querySelector: () => ({ onclick: null }),
  }),
  dispatchEvent: () => {},
};

const { state } = await import("../../static/js/state.js");
const { addAttachments, renderAttachments, uploadPendingAttachments } = await import("../../static/js/attachments.js");

test("addAttachments pushes files to pendingAttachments and renders chips", () => {
  state.pendingAttachments = [];
  addAttachments([{ name: "a.txt", type: "text/plain" }, null, { name: "b.png", type: "image/png" }]);
  assert.deepEqual(
    state.pendingAttachments.map((a) => a.name),
    ["a.txt", "b.png"]
  );
  assert.equal(attBox.children.length, 2);
});

test("renderAttachments clears the box when nothing is pending", () => {
  state.pendingAttachments = [];
  attBox.children = [];
  renderAttachments();
  assert.equal(attBox.innerHTML, "");
  assert.equal(attBox.children.length, 0);
});

test("uploadPendingAttachments uploads file attachments and returns refs", async () => {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, body: JSON.parse(opts.body) });
    return { ok: true, status: 201, json: async () => ({ id: 7, name: "a.txt", mime: "text/plain", kind: "text", size: 2 }), text: async () => "" };
  };
  state.pendingAttachments = [
    { name: "a.txt", type: "text/plain", file: { arrayBuffer: async () => new TextEncoder().encode("hi").buffer } },
    { name: "shot.png", data: "data:image/png;base64,AAAA" },
  ];
  const refs = await uploadPendingAttachments("sid-1");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/sessions/sid-1/attachments");
  assert.equal(calls[0].body.name, "a.txt");
  assert.equal(atob(calls[0].body.data), "hi");
  assert.deepEqual(refs, [
    { id: 7, name: "a.txt", type: "text/plain" },
    { name: "shot.png", data: "data:image/png;base64,AAAA" },
  ]);
  assert.equal(state.pendingAttachments.length, 0);
});
