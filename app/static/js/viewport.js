// Soft-Tastatur auf Mobilgeraeten: ohne interactive-widget=resizes-content
// (siehe index.html) schrumpft beim Oeffnen der Tastatur nur der Visual
// Viewport, das 100%-Layout bleibt an der vollen Layout-Hoehe haengen - der
// Composer wird verdeckt bzw. loest sich nach einem Pan des Windows vom
// unteren Rand. Deshalb wird hier die Root-Hoehe an den Visual Viewport
// gekoppelt und ein bestehender Pan zurueckgesetzt (sonst schwebt der
// Composer mit leerem Streifen ueber der Tastatur).

export function applyVisualViewport(root, win) {
  const vv = win.visualViewport;
  // scale != 1 ist Pinch-Zoom: Layout-Hoehe nicht anfassen
  if (!vv || vv.scale !== 1) return false;
  root.style.height = `${vv.height}px`;
  win.scrollTo(0, 0);
  return true;
}

export function initViewportSync(win, doc) {
  const root = doc.documentElement;
  const vv = win.visualViewport;
  if (vv) {
    const apply = () => applyVisualViewport(root, win);
    vv.addEventListener("resize", apply);
    vv.addEventListener("scroll", apply);
    apply();
  }
  const input = doc.getElementById("input");
  if (input) input.addEventListener("focus", () => input.scrollIntoView({ block: "nearest" }));
}
