import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/+esm";

const status = document.getElementById("callback-status");

async function finishOAuth() {
  try {
    status.textContent = "Securing your session…";
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load SONIVOX configuration.");
    const config = await response.json();
    if (!config.configured) throw new Error("Account service is not configured.");

    const supabase = createClient(config.supabase_url, config.publishable_key, {
      auth: {
        flowType: "pkce",
        detectSessionInUrl: true,
        persistSession: true,
        autoRefreshToken: true
      }
    });

    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    if (code) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (error) throw error;
    } else if (params.has("error")) {
      throw new Error(params.get("error_description") || params.get("error"));
    }

    const { data, error } = await supabase.auth.getSession();
    if (error) throw error;
    if (!data.session) throw new Error("Google sign-in finished, but no session was saved. Please try again.");

    status.textContent = "Signed in. Opening your workspace…";
    location.replace("/");
  } catch (error) {
    console.error("SONIVOX OAuth callback error:", error);
    status.textContent = error?.message || "Sign-in could not be completed.";
    const retry = document.getElementById("callback-retry");
    retry.hidden = false;
  }
}

finishOAuth();
