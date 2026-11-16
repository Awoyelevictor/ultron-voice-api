import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/+esm";

const form = document.getElementById("auth-form");
const button = document.getElementById("auth-submit");
const message = document.getElementById("auth-message");
const mode = location.pathname === "/signup" ? "signup" : "signin";

function showMessage(text, kind = "error") {
  message.textContent = text;
  message.dataset.kind = kind;
}

async function start() {
  try {
    const configResponse = await fetch("/api/config", {cache:"no-store"});
    if (!configResponse.ok) throw new Error("Could not load SONIVOX configuration. Please refresh.");
    const config = await configResponse.json();
    if (!config.configured || !config.supabase_url || !config.publishable_key) {
      throw new Error("Account service is not configured. Please contact the SONIVOX administrator.");
    }
    const supabase = createClient(config.supabase_url, config.publishable_key);
    const {data:{session}, error:sessionError} = await supabase.auth.getSession();
    if (sessionError) throw sessionError;
    if (session) { location.replace("/"); return; }

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const email = document.getElementById("auth-email").value.trim();
      const password = document.getElementById("auth-password").value;
      if (!email || !password) return showMessage("Enter your email and password.");
      if (mode === "signup") {
        const confirmation = document.getElementById("auth-confirm").value;
        if (password.length < 8) return showMessage("Your password must contain at least 8 characters.");
        if (password !== confirmation) return showMessage("The passwords do not match.");
      }
      button.disabled = true;
      button.textContent = mode === "signup" ? "Creating account…" : "Signing in…";
      showMessage("");
      try {
        const result = mode === "signup"
          ? await supabase.auth.signUp({email,password,options:{emailRedirectTo:location.origin + "/signin"}})
          : await supabase.auth.signInWithPassword({email,password});
        if (result.error) throw result.error;
        if (mode === "signup" && !result.data.session) {
          showMessage("Your account request was accepted. Check your inbox (and spam folder) for the confirmation email, then sign in here.", "success");
          form.reset();
          return;
        }
        if (!result.data.session) throw new Error("Authentication succeeded but no session was returned. Try signing in again.");
        showMessage("Signed in. Opening your workspace…", "success");
        location.replace("/");
      } catch (error) {
        console.error("SONIVOX authentication error:", error);
        const raw = error?.message || "Authentication failed. Please try again.";
        showMessage(raw);
      } finally {
        button.disabled = false;
        button.textContent = mode === "signup" ? "Create account" : "Sign in";
      }
    });
  } catch (error) {
    console.error("SONIVOX auth setup error:", error);
    showMessage(error?.message || "Could not initialize account service.");
  }
}
start();