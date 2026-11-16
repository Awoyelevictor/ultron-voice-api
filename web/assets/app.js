import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/+esm";

const toast = document.getElementById("toast");
let toastTimer;
let supabase;
let currentSession;
let voices = [];
let audioUrl;

function notify(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}
function showPage(page) {
  if (page === "home") page = "dashboard";
  ["dashboard", "voices", "keys"].forEach(name => {
    document.getElementById("page-" + name).classList.toggle("hidden", name !== page);
  });
  document.querySelectorAll(".nav-link").forEach(link => link.classList.toggle("active", link.dataset.page === page));
  document.getElementById("crumb").textContent = ({dashboard:"Overview",voices:"My voices",keys:"API keys"})[page];
  document.getElementById("sidebar").classList.remove("open");
  window.scrollTo({top:0,behavior:"smooth"});
}
document.querySelectorAll("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
document.getElementById("menu-toggle").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));

function mountAuth() {
  const overlay = document.createElement("div");
  overlay.id = "auth-gate";
  overlay.innerHTML = `
    <div class="auth-card">
      <div class="auth-brand"><span class="brand-mark">S</span><strong>SONI<span>VOX</span></strong></div>
      <div class="eyebrow">YOUR PRIVATE VOICE STUDIO</div>
      <h1>Welcome to <span>SONIVOX.</span></h1>
      <p>Sign in or create an account to access your voice workspace.</p>
      <form id="auth-form">
        <label for="auth-email">EMAIL ADDRESS</label>
        <input id="auth-email" type="email" autocomplete="email" required placeholder="you@example.com">
        <label for="auth-password">PASSWORD</label>
        <input id="auth-password" type="password" autocomplete="current-password" minlength="8" required placeholder="At least 8 characters">
        <button class="primary-button full-button" id="signin-button" type="submit">Sign in</button>
        <button class="secondary-button full-button" id="signup-button" type="button">Create an account</button>
      </form>
      <small id="auth-note">Your voice samples stay private to your account.</small>
    </div>`;
  document.body.appendChild(overlay);
  document.getElementById("auth-form").addEventListener("submit", async event => {
    event.preventDefault();
    await authenticate("signin");
  });
  document.getElementById("signup-button").addEventListener("click", () => authenticate("signup"));
}
async function authenticate(mode) {
  const email = document.getElementById("auth-email").value.trim();
  const password = document.getElementById("auth-password").value;
  if (!email || password.length < 8) return notify("Enter a valid email and a password with at least 8 characters.");
  const button = document.getElementById(mode === "signin" ? "signin-button" : "signup-button");
  button.disabled = true;
  button.textContent = mode === "signin" ? "Signing in…" : "Creating account…";
  const result = mode === "signin"
    ? await supabase.auth.signInWithPassword({email,password})
    : await supabase.auth.signUp({email,password});
  button.disabled = false;
  button.textContent = mode === "signin" ? "Sign in" : "Create an account";
  if (result.error) return notify(result.error.message);
  if (mode === "signup" && !result.data.session) {
    notify("Account created. Check your email to confirm, then sign in.");
    return;
  }
  currentSession = result.data.session;
  await enterWorkspace();
}
async function enterWorkspace() {
  document.getElementById("auth-gate")?.remove();
  document.getElementById("app").classList.remove("app-locked");
  const email = currentSession?.user?.email || "Signed in";
  document.querySelector(".profile-copy strong").textContent = email;
  document.querySelector(".profile-copy small").textContent = "Personal workspace";
  document.querySelector(".avatar").textContent = email.slice(0,1).toUpperCase();
  document.querySelector(".user-chip").textContent = email.slice(0,1).toUpperCase();
  document.querySelector(".user-chip").title = email;
  document.querySelector(".user-chip").onclick = async () => {
    if (confirm("Sign out of SONIVOX?")) await supabase.auth.signOut();
  };
  document.getElementById("generate-button").disabled = false;
  document.getElementById("add-voice-button").disabled = false;
  document.getElementById("create-key-button").disabled = false;
  await loadVoices();
  await loadStats();
}
function lockWorkspace() {
  currentSession = null;
  voices = [];
  document.getElementById("auth-gate")?.remove();
  document.getElementById("app").classList.add("app-locked");
  mountAuth();
}
async function loadVoices() {
  const {data,error} = await supabase.from("sonivox_voices").select("id,name,sample_path,created_at").order("created_at",{ascending:false});
  if (error) return notify("Could not load your voices: " + error.message);
  voices = data || [];
  const select = document.getElementById("voice-select");
  select.innerHTML = "";
  if (!voices.length) {
    select.add(new Option("Add a voice profile first",""));
  } else {
    voices.forEach(voice => select.add(new Option(voice.name,voice.id)));
  }
  const badge = document.querySelector("#page-voices .section-title-row .soft-tag");
  badge.textContent = voices.length + (voices.length === 1 ? " VOICE" : " VOICES");
  const empty = document.querySelector(".empty-library:not(.keys-empty)");
  empty.innerHTML = "";
  if (!voices.length) {
    empty.innerHTML = '<div class="empty-icon">◉</div><strong>No voices added yet</strong><p>Your saved voice profiles will show up here.</p><button class="text-button" id="empty-add-button">Add your first voice →</button>';
    document.getElementById("empty-add-button").onclick = chooseVoiceFile;
  } else {
    empty.classList.add("voice-list");
    voices.forEach(voice => {
      const card = document.createElement("div");
      card.className = "voice-card";
      const details = document.createElement("div");
      details.innerHTML = '<div class="voice-avatar">◉</div>';
      const copy = document.createElement("div");
      copy.className = "voice-card-copy";
      const title = document.createElement("strong");
      title.textContent = voice.name;
      const sub = document.createElement("small");
      sub.textContent = "Private voice profile";
      copy.append(title,sub);
      const remove = document.createElement("button");
      remove.className = "text-button";
      remove.textContent = "Delete";
      remove.onclick = () => deleteVoice(voice);
      card.append(details.firstChild,copy,remove);
      empty.append(card);
    });
  }
}
async function loadStats() {
  const {count:voiceCount} = await supabase.from("sonivox_voices").select("id",{count:"exact",head:true});
  const {count:generationCount} = await supabase.from("sonivox_generations").select("id",{count:"exact",head:true});
  const {data:generations} = await supabase.from("sonivox_generations").select("input_text").limit(1000);
  const characters = (generations || []).reduce((sum,item) => sum + (item.input_text || "").length,0);
  const values = document.querySelectorAll(".stat-value");
  values[0].textContent = voiceCount ?? 0;
  values[1].textContent = generationCount ?? 0;
  values[2].textContent = characters.toLocaleString();
}
const fileInput = document.createElement("input");
fileInput.type = "file";
fileInput.accept = ".wav,audio/wav,audio/x-wav";
fileInput.hidden = true;
document.body.appendChild(fileInput);
function chooseVoiceFile() { fileInput.click(); }
document.getElementById("add-voice-button").onclick = chooseVoiceFile;
document.getElementById("empty-add-button").onclick = chooseVoiceFile;
document.getElementById("upload-info-button").onclick = () => notify("Upload a WAV sample of a voice you own or have explicit permission to use. Consent is required.");
fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".wav") || file.type && !["audio/wav","audio/x-wav","audio/wave"].includes(file.type)) {
    return notify("For this first release, upload a WAV audio file.");
  }
  if (file.size > 50 * 1024 * 1024) return notify("The maximum upload size is 50 MB.");
  const name = prompt("Give this voice profile a name:");
  if (!name?.trim()) return;
  if (!confirm("Confirm that this is your voice or you have explicit permission from the speaker to use and generate speech with it.")) return;
  const userId = currentSession.user.id;
  const path = userId + "/" + crypto.randomUUID() + ".wav";
  notify("Uploading your private voice sample…");
  const {error:uploadError} = await supabase.storage.from("sonivox-voices").upload(path,file,{contentType:"audio/wav",upsert:false});
  if (uploadError) return notify("Upload failed: " + uploadError.message);
  const {error:insertError} = await supabase.from("sonivox_voices").insert({
    user_id:userId,name:name.trim().slice(0,80),sample_path:path,consent_confirmed:true
  });
  if (insertError) {
    await supabase.storage.from("sonivox-voices").remove([path]);
    return notify("Could not save voice profile: " + insertError.message);
  }
  notify("Voice profile saved.");
  await loadVoices();
  await loadStats();
  showPage("voices");
});
async function deleteVoice(voice) {
  if (!confirm("Delete “" + voice.name + "” and its uploaded sample?")) return;
  const {error} = await supabase.from("sonivox_voices").delete().eq("id",voice.id);
  if (error) return notify("Could not delete voice: " + error.message);
  await supabase.storage.from("sonivox-voices").remove([voice.sample_path]);
  notify("Voice profile deleted.");
  await loadVoices();
  await loadStats();
}
document.getElementById("speech-text").addEventListener("input", event => {
  document.getElementById("char-count").textContent = event.target.value.length + " / 1,000";
});
document.getElementById("generate-button").addEventListener("click", async () => {
  const text = document.getElementById("speech-text").value.trim();
  const voiceId = document.getElementById("voice-select").value;
  const lang = document.getElementById("language-select").value;
  if (!text) return notify("Write something to generate first.");
  if (!voiceId) return notify("Add and select a voice profile first.");
  const button = document.getElementById("generate-button");
  button.disabled = true;
  button.textContent = "Generating speech…";
  try {
    const {data:{session}} = await supabase.auth.getSession();
    const response = await fetch("/api/speech",{
      method:"POST",
      headers:{"Content-Type":"application/json","Authorization":"Bearer " + session.access_token},
      body:JSON.stringify({text,voice_id:voiceId,lang})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Speech generation failed");
    const {data:audioData,error} = await supabase.storage.from("sonivox-voices").download(result.audio_path);
    if (error) throw error;
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = URL.createObjectURL(audioData);
    const output = document.querySelector(".empty-audio");
    output.innerHTML = "";
    const heading = document.createElement("strong");
    heading.textContent = "Your speech is ready";
    const player = document.createElement("audio");
    player.controls = true;
    player.src = audioUrl;
    player.className = "audio-player";
    const download = document.createElement("a");
    download.href = audioUrl;
    download.download = "sonivox-" + result.id + ".wav";
    download.className = "secondary-button";
    download.textContent = "Download WAV ↓";
    output.append(heading,player,download);
    notify("Speech generated successfully.");
    await loadStats();
  } catch (error) {
    notify(error.message || "Speech generation failed.");
  } finally {
    button.disabled = false;
    button.innerHTML = '<span>✦</span> Generate speech <span class="button-arrow">→</span>';
  }
});
document.getElementById("create-key-button").onclick = () => notify("Personal API keys are the next integration milestone; speech playground is live first.");
document.querySelector(".help-button").onclick = () => notify("Need help? Upload a WAV voice sample, select it, type a script, and generate.");
async function init() {
  document.getElementById("app").classList.add("app-locked");
  const configResponse = await fetch("/api/config");
  const config = await configResponse.json();
  if (!config.configured) {
    notify("SONIVOX needs its Supabase public configuration on Render.");
    lockWorkspace();
    return;
  }
  supabase = createClient(config.supabase_url,config.publishable_key);
  const {data:{session}} = await supabase.auth.getSession();
  if (session) {
    currentSession = session;
    await enterWorkspace();
  } else {
    lockWorkspace();
  }
  supabase.auth.onAuthStateChange(async (_event,sessionNow) => {
    if (sessionNow) {
      currentSession = sessionNow;
      if (!document.getElementById("auth-gate")) await enterWorkspace();
    } else if (currentSession) {
      lockWorkspace();
    }
  });
}
init().catch(error => notify("Could not start SONIVOX: " + error.message));
