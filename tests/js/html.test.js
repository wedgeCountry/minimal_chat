import test from "node:test";
import assert from "node:assert/strict";

function fakeEl(partial) {
  return {
    dataset: { partial },
    replacedWith: null,
    replaceWith(...nodes) {
      this.replacedWith = nodes;
    },
  };
}

test("initPartials loads each placeholder and replaces it with the partial content", async () => {
  const el = fakeEl("/partials/side-panel.html");
  globalThis.document = {
    querySelectorAll: (sel) => (sel === "[data-partial]" ? [el] : []),
    createElement: (tag) => {
      assert.equal(tag, "template");
      const tpl = { content: { childNodes: [] } };
      Object.defineProperty(tpl, "innerHTML", {
        set(v) {
          this._html = v;
          this.content.childNodes = [{ node: v }];
        },
        get() {
          return this._html;
        },
      });
      return tpl;
    },
  };
  globalThis.fetch = async (url, opts) => {
    assert.equal(url, "/partials/side-panel.html");
    assert.equal(opts.cache, "no-cache");
    return { ok: true, text: async () => "<div>panel</div>" };
  };

  const { initPartials } = await import("../../static/js/html.js");
  await initPartials();
  assert.deepEqual(el.replacedWith, [{ node: "<div>panel</div>" }]);
});

test("initPartials throws when a partial cannot be loaded", async () => {
  const el = fakeEl("/partials/missing.html");
  globalThis.document = {
    querySelectorAll: () => [el],
    createElement: () => ({ content: { childNodes: [] } }),
  };
  globalThis.fetch = async () => ({ ok: false, status: 404 });

  const { initPartials } = await import("../../static/js/html.js");
  await assert.rejects(initPartials(), /Partial nicht geladen/);
});
