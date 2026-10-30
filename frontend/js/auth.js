/* MkulimaBridge farmer account access. Sessions use an HttpOnly server cookie. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const API_BASE = window.location.port === "5500" ? `http://${window.location.hostname}:8000` : "";
  const credentialsMode = API_BASE ? "include" : "same-origin";
  const endpoint = (path) => `${API_BASE}${path}`;
  const authScreen = $("auth-screen");
  const appShell = document.querySelector(".app-shell");
  const loginForm = $("login-form");
  const registerForm = $("register-form");
  const loginMessage = $("login-message");
  const registerMessage = $("register-message");

  function showMessage(target, message, success = false) {
    target.textContent = message;
    target.classList.toggle("success", success);
    target.classList.toggle("error", !success && Boolean(message));
  }

  function showTab(tab) {
    const loginActive = tab === "login";
    loginForm.hidden = !loginActive;
    registerForm.hidden = loginActive;
    $("show-login-tab").classList.toggle("active", loginActive);
    $("show-register-tab").classList.toggle("active", !loginActive);
    $("show-login-tab").setAttribute("aria-selected", String(loginActive));
    $("show-register-tab").setAttribute("aria-selected", String(!loginActive));
    $("auth-title").textContent = loginActive ? "Welcome back to your farm workspace" : "Create your farmer account";
    showMessage(loginMessage, "");
    showMessage(registerMessage, "");
  }

  function displayAccount(user) {
    const fullName = user.full_name || "Farmer";
    $("account-name").textContent = fullName;
    $("account-email").textContent = user.email || "";
    $("account-avatar").textContent = fullName.trim().charAt(0).toUpperCase() || "F";
    authScreen.hidden = true;
    appShell.hidden = false;
    document.body.classList.add("is-authenticated");
  }

  $("show-login-tab")?.addEventListener("click", () => showTab("login"));
  $("show-register-tab")?.addEventListener("click", () => showTab("register"));

  loginForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("login-button");
    button.disabled = true;
    button.textContent = "Signing in…";
    showMessage(loginMessage, "");
    try {
      const response = await fetch(endpoint("/auth/login"), {
        method: "POST", credentials: credentialsMode,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: $("login-email").value.trim(), password: $("login-password").value })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Sign in failed (${response.status}).`);
      showMessage(loginMessage, "Signed in successfully. Opening your farm workspace…", true);
      window.location.reload();
    } catch (error) {
      showMessage(loginMessage, error.message || "Could not sign in. Please try again.");
    } finally {
      button.disabled = false;
      button.textContent = "Sign in to MkulimaBridge";
    }
  });

  registerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("register-button");
    const password = $("register-password").value;
    const confirmation = $("register-confirm-password").value;
    if (password !== confirmation) {
      showMessage(registerMessage, "The passwords do not match. Please check them.");
      return;
    }
    if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
      showMessage(registerMessage, "Use at least one letter and one number in your password.");
      return;
    }
    button.disabled = true;
    button.textContent = "Creating account…";
    showMessage(registerMessage, "");
    try {
      const response = await fetch(endpoint("/auth/register"), {
        method: "POST", credentials: credentialsMode,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: $("register-name").value.trim(),
          email: $("register-email").value.trim(),
          password
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Account creation failed (${response.status}).`);
      showMessage(registerMessage, "Your account has been created. Opening your farm workspace…", true);
      window.location.reload();
    } catch (error) {
      showMessage(registerMessage, error.message || "Could not create your account. Please try again.");
    } finally {
      button.disabled = false;
      button.textContent = "Create farmer account";
    }
  });

  $("sign-out-button")?.addEventListener("click", async () => {
    const button = $("sign-out-button");
    button.disabled = true;
    try {
      await fetch(endpoint("/auth/logout"), { method: "POST", credentials: credentialsMode });
    } finally {
      window.location.reload();
    }
  });

  window.MKULIMA_AUTH_READY = (async () => {
    try {
      const response = await fetch(endpoint("/auth/me"), { credentials: credentialsMode, headers: { "Accept": "application/json" } });
      if (!response.ok) {
        authScreen.hidden = false;
        appShell.hidden = true;
        showTab("login");
        return false;
      }
      const data = await response.json();
      displayAccount(data.user || {});
      return true;
    } catch (_) {
      authScreen.hidden = false;
      appShell.hidden = true;
      showTab("login");
      showMessage(loginMessage, "Could not reach the application server. Start the backend and refresh.");
      return false;
    }
  })();
})();
