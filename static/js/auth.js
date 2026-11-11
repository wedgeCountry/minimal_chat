import { api, setToken } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";

// Einmalig clientseitig generierter 32-Byte-Schluessel (base64) fuer die
// serverseitige Verschluesselung der per-user SQLite-Datei.
export function generateKey() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

export function showAuth() {
  $("authOverlay").classList.add("open");
  $("authErr").textContent = "";
  $("authUser").focus();
}

export function hideAuth() {
  $("authOverlay").classList.remove("open");
}

export function initAuth(onSuccess) {
  let mode = "login";
  const submit = $("authSubmit");
  const sw = $("authSwitch");
  const setMode = (m) => {
    mode = m;
    submit.textContent = m === "login" ? "Anmelden" : "Registrieren";
    sw.textContent = m === "login" ? "Registrieren" : "Anmelden";
    $("authHint").textContent =
      m === "login" ? "Anmelden oder registrieren" : "Neuen Account anlegen (Schlüssel wird einmalig im Browser erzeugt)";
    $("authErr").textContent = "";
  };
  sw.onclick = () => setMode(mode === "login" ? "register" : "login");

  const doAuth = async () => {
    const username = $("authUser").value.trim();
    const password = $("authPass").value;
    $("authErr").textContent = "";
    if (!username || password.length < 6) {
      $("authErr").textContent = "Benutzername (min. 3 Zeichen) und Passwort (min. 6 Zeichen) eingeben.";
      return;
    }
    try {
      const body =
        mode === "register"
          ? { username, password, key: generateKey() }
          : { username, password };
      const res = await api.post("/auth/" + mode, body);
      setToken(res.token);
      state.username = res.username;
      hideAuth();
      onSuccess();
    } catch (err) {
      $("authErr").textContent = "Fehler: " + err.message;
    }
  };
  submit.onclick = doAuth;
  $("authPass").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doAuth();
  });
}
