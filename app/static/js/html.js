// Laedt HTML-Partials (eigene Dateien) in Platzhalter-Elemente.
export async function initPartials(root = document) {
  const placeholders = [...root.querySelectorAll("[data-partial]")];
  await Promise.all(
    placeholders.map(async (el) => {
      const res = await fetch(el.dataset.partial, { cache: "no-cache" });
      if (!res.ok) throw new Error("Partial nicht geladen: " + el.dataset.partial);
      const tpl = document.createElement("template");
      tpl.innerHTML = (await res.text()).trim();
      el.replaceWith(...tpl.content.childNodes);
    })
  );
}
