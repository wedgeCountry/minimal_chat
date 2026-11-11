import { api } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";

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
      m === "login" ? "Anmelden oder registrieren" : "Neuen Account anlegen (E-Mail + Passwort)";
    $("authErr").textContent = "";
  };
  sw.onclick = () => setMode(mode === "login" ? "register" : "login");

  const doAuth = async () => {
    const email = $("authUser").value.trim();
    const password = $("authPass").value;
    $("authErr").textContent = "";
    if (!email.includes("@") || password.length < 8) {
      $("authErr").textContent = "E-Mail eingeben und Passwort (min. 8 Zeichen) eingeben.";
      return;
    }
    try {
      const res = await api.post("/auth/" + mode, { email, password });
      state.username = res.email;
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
