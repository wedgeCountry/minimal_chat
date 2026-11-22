import { api } from "./api.js";
import { state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";
import { confirmModal, showError } from "./confirm.js";

export function buildBaseUrl(host, port) {
  const h = (host || "").trim();
  if (!h) return "";
  const p = (port || "").trim();
  return `http://${h}${p ? ":" + p : ""}/v1`;
}

export async function loadModels() {
  state.llmModels = await api.get("/settings/models");
}

export function renderModelTiles() {
  const box = $("modelTiles");
  if (!box) return;
  box.innerHTML = "";
  const defaultId = state.settings.default_model_id || "";
  for (const m of state.llmModels) {
    const id = String(m.id);
    const t = document.createElement("div");
    t.className = "tile modelTile" + (id === defaultId ? " active" : "");
    t.dataset.testid = `model-tile-${m.id}`;
    t.dataset.modelId = id;
    const title = m.provider || m.model || "Modell";
    const sub = [m.model, m.host ? buildBaseUrl(m.host, m.port) : ""].filter(Boolean).join(" · ");
    t.innerHTML = `
      <div class="modelRow">
        <span class="modelTitle" data-testid="model-tile-title-${m.id}">${esc(title)}</span>
        <button class="iconBtn editBtn" data-testid="model-edit-btn-${m.id}" title="Bearbeiten">${ICONS.edit}</button>
      </div>
      <div class="modelSub" data-testid="model-tile-sub-${m.id}">${esc(sub)}</div>
      <label class="checkRow defaultRow" data-testid="model-default-row-${m.id}">
        <input type="radio" name="defaultModel" data-testid="model-default-radio-${m.id}"${id === defaultId ? " checked" : ""} /> Standard-Modell
      </label>`;
    t.querySelector(".editBtn").onclick = (e) => {
      e.stopPropagation();
      openModelModal(m);
    };
    t.querySelector('input[name="defaultModel"]').addEventListener("change", (e) => {
      e.stopPropagation();
      setDefaultModel(m.id);
    });
    // Klick/Tap auf das Tile setzt es als Standard; bearbeiten nur ueber den Stift-Button
    t.onclick = () => setDefaultModel(m.id);
    box.appendChild(t);
  }
  const add = document.createElement("div");
  add.className = "tile modelTile add";
  add.id = "modelAddTile";
  add.dataset.testid = "model-add-tile";
  add.innerHTML = `${ICONS.plus}<span data-testid="model-add-label">Neues Modell</span>`;
  add.onclick = () => openModelModal(null);
  box.appendChild(add);
}

// Optimistisch: Tile sofort als Standard markieren, Speichern seriell im Hintergrund;
// bei Fehler wird der serverseitige Stand neu geladen. (Jeder Settings-Write kostet ein
// komplettes Entschluesseln/Verschluesseln der per-user DB -> nicht auf den Tap warten.)
let defaultSaveChain = Promise.resolve();

export function setDefaultModel(id) {
  state.settings.default_model_id = String(id);
  renderModelTiles();
  defaultSaveChain = defaultSaveChain
    .then(async () => {
      const res = await api.put("/settings", { default_model_id: String(id) });
      state.settings = { ...state.settings, ...res };
    })
    .catch(async () => {
      showError("Standard-Modell konnte nicht gespeichert werden – Stand wird neu geladen");
      try {
        state.settings = { ...state.settings, ...(await api.get("/settings")) };
      } catch {}
    })
    .finally(() => renderModelTiles());
}

let editingId = null;

// Modell-Feld als Dropdown mit den vom Server gemeldeten Modellen (gleiche id -> Save/Test lesen unveraendert)
export function ensureModelSelect(options) {
  const cur = $("modelModel");
  const sel = document.createElement("select");
  sel.id = "modelModel";
  sel.dataset.testid = "model-model-select";
  for (const id of options) {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = id;
    sel.appendChild(o);
  }
  if (cur.value) sel.value = cur.value;
  cur.replaceWith(sel);
}

function ensureModelInput() {
  const cur = $("modelModel");
  if (cur.tagName === "SELECT") {
    const inp = document.createElement("input");
    inp.id = "modelModel";
    inp.dataset.testid = "model-model";
    inp.placeholder = "gpt-4o-mini";
    cur.replaceWith(inp);
  }
}

export function openModelModal(model) {
  editingId = model ? model.id : null;
  $("modelTitle").textContent = model ? "Modell bearbeiten" : "Neues Modell";
  $("modelProvider").value = model?.provider || "";
  $("modelHost").value = model?.host || "";
  $("modelPort").value = model?.port || "";
  $("modelBase").value = model ? buildBaseUrl(model.host, model.port) || model.base : "";
  // api_key ist write-only: Feld bleibt leer, nur ein neuer Eintrag wird gespeichert
  $("modelKey").value = "";
  ensureModelInput();
  $("modelModel").value = model?.model || "";
  $("modelDelete").hidden = !model;
  const status = $("modelConnStatus");
  status.textContent = "";
  status.className = "connStatus";
  $("modelOverlay").classList.add("open");
}

function closeModelModal() {
  $("modelOverlay").classList.remove("open");
}

async function saveModel() {
  const body = {
    provider: $("modelProvider").value.trim(),
    host: $("modelHost").value.trim(),
    port: $("modelPort").value.trim(),
    model: $("modelModel").value.trim(),
  };
  if ($("modelKey").value.trim()) body.api_key = $("modelKey").value.trim();
  if (editingId != null) await api.put(`/settings/models/${editingId}`, body);
  else await api.post("/settings/models", body);
  await loadModels();
  // erstes Tile wird serverseitig automatisch zum Standard -> Settings mitsynchronisieren
  state.settings = { ...state.settings, ...(await api.get("/settings")) };
  renderModelTiles();
  closeModelModal();
  document.dispatchEvent(new CustomEvent("leanchat:changed"));
}

async function deleteModel() {
  if (editingId == null) return;
  const ok = await confirmModal({
    title: "Modell löschen",
    text: "Dieses Modell-Setup wird entfernt. Sessions, die es nutzen, fallen auf das Standard-Modell zurück.",
  });
  if (!ok) return;
  await api.del(`/settings/models/${editingId}`);
  await loadModels();
  // default_model_id wurde serverseitig neu gesetzt (oder geleert)
  state.settings = { ...state.settings, ...(await api.get("/settings")) };
  renderModelTiles();
  closeModelModal();
  document.dispatchEvent(new CustomEvent("leanchat:changed"));
}

export function initModels() {
  $("modelCancel").onclick = closeModelModal;
  $("modelOverlay").addEventListener("click", (e) => {
    if (e.target === $("modelOverlay")) closeModelModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("modelOverlay").classList.contains("open")) closeModelModal();
  });
  const updateBasePreview = () => {
    $("modelBase").value = buildBaseUrl($("modelHost").value, $("modelPort").value);
  };
  $("modelHost").addEventListener("input", updateBasePreview);
  $("modelPort").addEventListener("input", updateBasePreview);
  $("modelTestConn").onclick = async () => {
    const btn = $("modelTestConn");
    const status = $("modelConnStatus");
    btn.disabled = true;
    status.textContent = "Teste Verbindung…";
    status.className = "connStatus";
    try {
      const res = await api.post("/settings/models/test", {
        model_id: editingId ?? undefined,
        base: $("modelBase").value.trim() || undefined,
        api_key: $("modelKey").value.trim() || undefined,
        model: $("modelModel").value.trim() || undefined,
      });
      if (res.ok) {
        // res.detail ist self-beschreibend (z. B. "Modell „x“ verfügbar")
        status.textContent = "Erreichbar ✓" + (res.detail ? " – " + res.detail : "");
        status.classList.add("ok");
        // leeres Modell-Feld + Server hat Modelle gemeldet -> Feld wird zum Dropdown
        if (!$("modelModel").value.trim() && Array.isArray(res.models) && res.models.length) ensureModelSelect(res.models);
      } else {
        status.textContent = res.detail || "Nicht erreichbar: unbekannter Fehler";
        status.classList.add("err");
      }
    } catch (err) {
      status.textContent = "Nicht erreichbar: " + err.message;
      status.classList.add("err");
    } finally {
      btn.disabled = false;
    }
  };
  $("modelSave").onclick = saveModel;
  $("modelDelete").onclick = deleteModel;
}
