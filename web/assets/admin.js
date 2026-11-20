import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/+esm";

const stateEl = document.getElementById("state");
const dashboard = document.getElementById("dashboard");
let supabase;
let session;

function showState(message, kind = "") {
  stateEl.textContent = message;
  stateEl.className = "state " + kind;
  stateEl.classList.remove("hidden");
}
async function initialize() {
  try {
    const configResponse = await fetch("/api/config", {cache:"no-store"});
    const config = await configResponse.json();
    if (!config.configured) throw new Error("Authentication service is not configured.");
    supabase = createClient(config.supabase_url, config.publishable_key, {
      auth: {persistSession:true, autoRefreshToken:true, detectSessionInUrl:true}
    });
    const {data,error} = await supabase.auth.getSession();
    if (error) throw error;
    session = data.session;
    if (!session) { location.replace("/signin"); return; }
    await loadOverview();
    supabase.auth.onAuthStateChange((_event,nextSession) => {
      session = nextSession;
      if (!session) location.replace("/signin");
    });
  } catch (error) {
    showState(error.message || "Could not initialize the admin console.", "error");
  }
}
async function loadOverview() {
  if (!session?.access_token) { location.replace("/signin"); return; }
  showState("Verifying administrator access and loading platform statistics…");
  dashboard.classList.add("hidden");
  const response = await fetch("/api/admin/overview", {
    headers: {Authorization: "Bearer " + session.access_token},
    cache: "no-store"
  });
  const result = await response.json().catch(() => ({}));
  if (response.status === 401) { await supabase.auth.signOut(); location.replace("/signin"); return; }
  if (response.status === 403) { showState("Access denied. This account is not authorized to administer SONIVOX.", "error"); return; }
  if (!response.ok) throw new Error(result.detail || "Could not load platform statistics.");
  document.getElementById("users").textContent = Number(result.counts.users).toLocaleString();
  document.getElementById("voices").textContent = Number(result.counts.voices).toLocaleString();
  document.getElementById("generations").textContent = Number(result.counts.generations).toLocaleString();
  document.getElementById("keys").textContent = Number(result.counts.api_keys).toLocaleString();
  document.getElementById("limit").textContent = Number(result.free_monthly_character_limit).toLocaleString();
  dashboard.classList.remove("hidden");
  await loadAdminKeys();
  showState("Administrator verified · Live platform counts and API key inventory loaded.", "success");
}
document.getElementById("refresh").addEventListener("click", () => loadOverview().catch(e => showState(e.message, "error")));
document.getElementById("signout").addEventListener("click", async () => {
  if (supabase) await supabase.auth.signOut();
  location.replace("/signin");
});
initialize();

async function loadAdminKeys() {
  const state = document.getElementById("admin-key-state");
  const rows = document.getElementById("admin-key-rows");
  state.textContent = "Loading API keys…";
  rows.innerHTML = "";
  const response = await fetch("/api/admin/keys", {
    headers: {Authorization: "Bearer " + session.access_token},
    cache: "no-store"
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Could not load API key inventory.");
  const keys = result.keys || [];
  if (!keys.length) { state.textContent = "No API keys have been created."; return; }
  state.textContent = keys.length + " key records · secrets are never shown";
  for (const key of keys) {
    const tr = document.createElement("tr");
    const values = [
      key.name + " · " + (key.key_prefix || ""),
      key.user_id,
      key.created_at ? new Date(key.created_at).toLocaleString() : "—",
      key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "Never",
      key.revoked_at ? "REVOKED" : "ACTIVE"
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    tr.lastChild.className = key.revoked_at ? "revoked" : "active";
    rows.append(tr);
  }
}
