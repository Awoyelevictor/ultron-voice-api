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
  await loadUsage();
  await loadApiKeys();
}
function lockWorkspace() {
  currentSession = null;
  voices = [];
  location.replace("/signin");
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
      remove.className = "text-button voice-delete-button";
      remove.type = "button";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label","Delete voice profile " + voice.name);
      remove.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        deleteVoice(voice);
      });
      card.append(details.firstChild,copy,remove);
      empty.append(card);
    });
  }
}
async function loadUsage() {
  try {
    const {data:{session}} = await supabase.auth.getSession();
    const response = await fetch("/api/usage", {
      headers: {"Authorization":"Bearer " + session.access_token}
    });
    const usage = await response.json();
    if (!response.ok) throw new Error(usage.detail || "Could not load usage");
    document.getElementById("monthly-used").textContent = usage.used.toLocaleString();
    document.getElementById("usage-remaining").textContent = usage.remaining.toLocaleString();
    document.getElementById("usage-used-label").textContent = usage.used.toLocaleString();
    document.getElementById("usage-meter-fill").style.width =
      Math.min(100, usage.used / usage.monthly_limit * 100) + "%";
    const generate = document.getElementById("generate-button");
    generate.disabled = usage.remaining <= 0;
    if (usage.remaining <= 0) generate.title = "Your free monthly allowance is used up.";
    else generate.removeAttribute("title");
  } catch (error) {
    notify(error.message || "Could not load usage balance.");
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
fileInput.accept = "audio/*,.wav,.mp3,.m4a,.aac,.ogg,.oga,.opus,.flac,.aiff,.aif,.wma,.amr";
fileInput.hidden = true;
document.body.appendChild(fileInput);

const AUDIO_EXTENSIONS = new Set([
  "wav","mp3","m4a","aac","ogg","oga","opus","flac","aiff","aif","wma","amr"
]);
function isAudioFile(file) {
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  return !file.type.startsWith("video/") &&
    (file.type.startsWith("audio/") || (!["webm","3gp","mp4"].includes(extension) && AUDIO_EXTENSIONS.has(extension)));
}
function chooseVoiceFile() { fileInput.click(); }
document.getElementById("add-voice-button").onclick = chooseVoiceFile;
document.getElementById("empty-add-button").onclick = chooseVoiceFile;
document.getElementById("upload-info-button").onclick = () => notify("Choose an audio file such as WAV, MP3, M4A, AAC, OGG, FLAC or OPUS. SONIVOX converts supported audio to WAV before saving. Video files are not accepted.");
function formatAudioTime(seconds) {
  const total = Math.max(0,Math.floor(Number(seconds) || 0));
  return Math.floor(total / 60) + ":" + String(total % 60).padStart(2,"0");
}
function showAudioTrimDialog(file) {
  return new Promise((resolve,reject) => {
    const url = URL.createObjectURL(file);
    const probe = new Audio();
    probe.preload = "metadata";
    probe.src = url;
    probe.addEventListener("error",() => {
      URL.revokeObjectURL(url);
      reject(new Error("This audio file could not be opened for trimming. Try WAV, MP3 or M4A."));
    },{once:true});
    probe.addEventListener("loadedmetadata",() => {
      const duration = Number(probe.duration);
      if (!Number.isFinite(duration) || duration <= 0) {
        URL.revokeObjectURL(url);
        return reject(new Error("Could not read the audio duration."));
      }
      const minimum = 3;
      if (duration < minimum) {
        URL.revokeObjectURL(url);
        return reject(new Error("Use a recording with at least 3 seconds of clear speech."));
      }
      const maximum = 600;
      let start = 0;
      let end = Math.min(duration,maximum);
      const overlay = document.createElement("div");
      overlay.className = "sonivox-trim-overlay";
      const bars = Array.from({length:72},(_,i) => {
        const h = 12 + Math.abs(Math.sin(i * 1.73) * Math.cos(i * .37)) * 58;
        return '<i style="height:' + h.toFixed(0) + '%"></i>';
      }).join("");
      overlay.innerHTML = `
        <section class="sonivox-trim-dialog" role="dialog" aria-modal="true" aria-labelledby="sonivox-trim-title">
          <button class="sonivox-trim-close" type="button" aria-label="Cancel">×</button>
          <div class="eyebrow">VOICE SAMPLE EDITOR</div>
          <h2 id="sonivox-trim-title">Choose your audio segment</h2>
          <p class="sonivox-trim-description">Select at least 3 seconds of clear speech. The Africa TTS engine uses up to 8 seconds from your sample.</p>
          <div class="sonivox-trim-file"><span>♫</span><div><strong></strong><small></small></div></div>
          <div class="sonivox-trim-timeline">
            <div class="sonivox-trim-wave">${bars}</div>
            <div class="sonivox-trim-selection"></div>
            <input class="sonivox-trim-range sonivox-trim-start" type="range" min="0" max="${duration}" step="0.1" value="0" aria-label="Selection start">
            <input class="sonivox-trim-range sonivox-trim-end" type="range" min="0" max="${duration}" step="0.1" value="${end}" aria-label="Selection end">
          </div>
          <div class="sonivox-trim-times"><span>Start <strong class="sonivox-start-label">0:00</strong></span><span>End <strong class="sonivox-end-label"></strong></span></div>
          <div class="sonivox-trim-summary"><span>Selected duration</span><strong class="sonivox-duration-label"></strong><small>Minimum: 0:03 · Maximum: 10:00</small></div>
          <audio class="sonivox-trim-preview-audio" controls preload="none"></audio>
          <div class="sonivox-trim-actions"><button class="secondary-button sonivox-trim-preview" type="button">▶ Preview selection</button><button class="primary-button sonivox-trim-use" type="button">Use this audio →</button></div>
          <p class="sonivox-trim-hint">Original file: ${formatAudioTime(duration)} · Only the selected segment will be uploaded.</p>
        </section>`;
      document.body.appendChild(overlay);
      const dialog = overlay.querySelector(".sonivox-trim-dialog");
      const startInput = overlay.querySelector(".sonivox-trim-start");
      const endInput = overlay.querySelector(".sonivox-trim-end");
      const selection = overlay.querySelector(".sonivox-trim-selection");
      const startLabel = overlay.querySelector(".sonivox-start-label");
      const endLabel = overlay.querySelector(".sonivox-end-label");
      const durationLabel = overlay.querySelector(".sonivox-duration-label");
      const preview = overlay.querySelector(".sonivox-trim-preview-audio");
      const fileCopy = overlay.querySelector(".sonivox-trim-file");
      fileCopy.querySelector("strong").textContent = file.name;
      fileCopy.querySelector("small").textContent = formatAudioTime(duration) + " · " + (file.size / 1024 / 1024).toFixed(1) + " MB";
      preview.src = url;
      const cleanup = value => {
        preview.pause();
        URL.revokeObjectURL(url);
        overlay.remove();
        resolve(value);
      };
      const update = () => {
        startInput.value = String(start);
        endInput.value = String(end);
        const left = start / duration * 100;
        const right = end / duration * 100;
        selection.style.left = left + "%";
        selection.style.width = (right - left) + "%";
        startLabel.textContent = formatAudioTime(start);
        endLabel.textContent = formatAudioTime(end);
        durationLabel.textContent = formatAudioTime(end - start);
      };
      startInput.addEventListener("input",() => {
        start = Math.max(0,Math.min(Number(startInput.value),duration - minimum));
        if (end - start > maximum) end = start + maximum;
        if (end > duration) { end = duration; start = Math.max(0,end - maximum); }
        if (end - start < minimum) end = Math.min(duration,start + minimum);
        preview.pause();
        update();
      });
      endInput.addEventListener("input",() => {
        end = Math.max(minimum,Math.min(Number(endInput.value),duration));
        if (end - start > maximum) start = end - maximum;
        if (end - start < minimum) start = Math.max(0,end - minimum);
        preview.pause();
        update();
      });
      overlay.querySelector(".sonivox-trim-preview").onclick = async () => {
        preview.currentTime = start;
        try { await preview.play(); } catch { notify("Tap the audio player to start preview."); }
      };
      preview.addEventListener("timeupdate",() => {
        if (preview.currentTime >= end) preview.pause();
      });
      overlay.querySelector(".sonivox-trim-use").onclick = () => cleanup({start,end});
      overlay.querySelector(".sonivox-trim-close").onclick = () => cleanup(null);
      overlay.addEventListener("click",event => { if (event.target === overlay) cleanup(null); });
      const escapeHandler = event => {
        if (event.key === "Escape" && document.body.contains(overlay)) {
          cleanup(null);
          document.removeEventListener("keydown",escapeHandler);
        }
      };
      document.addEventListener("keydown",escapeHandler);
      update();
    },{once:true});
  });
}
fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;
  if (!isAudioFile(file)) return notify("Please choose an audio file. Video and non-audio files are not supported.");
  if (file.size > 500 * 1024 * 1024) return notify("This recording is larger than the 500 MB upload limit.");
  if (!currentSession?.user?.id) return notify("Your session expired. Please sign in again.");
  let selection;
  try {
    notify("Reading audio duration…");
    selection = await showAudioTrimDialog(file);
  } catch (error) {
    return notify(error.message || "Could not open this audio file.");
  }
  if (!selection) return;
  const name = prompt("Give this voice profile a name:");
  if (!name?.trim()) return;
  if (!confirm("Confirm that this is your voice or you have explicit permission from the speaker to use and generate speech with it.")) return;
  const userId = currentSession.user.id;
  let uploadedPath = null;
  try {
    notify("Uploading recording for server-side trimming…");
    const {data:{session}} = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error("Your session expired. Please sign in again.");
    const trimForm = new FormData();
    trimForm.append("audio",file,file.name);
    trimForm.append("start_seconds",String(selection.start));
    trimForm.append("end_seconds",String(selection.end));
    const trimResponse = await fetch("/api/voice/trim",{
      method:"POST",
      headers:{"Authorization":"Bearer " + session.access_token},
      body:trimForm
    });
    const trimResult = await trimResponse.json().catch(() => ({}));
    if (!trimResponse.ok) throw new Error(trimResult.detail || "The server could not trim this recording.");
    uploadedPath = trimResult.sample_path;
    if (!uploadedPath) throw new Error("The server trimmed the recording but did not return a saved audio path.");
    const {error:insertError} = await supabase.from("sonivox_voices").insert({
      user_id:userId,name:name.trim().slice(0,80),sample_path:uploadedPath,consent_confirmed:true
    });
    if (insertError) {
      await supabase.storage.from("sonivox-voices").remove([uploadedPath]);
      uploadedPath = null;
      throw new Error("The audio uploaded, but the voice profile could not be saved: " + insertError.message);
    }
    uploadedPath = null;
    notify("Trimmed audio converted and voice profile saved.");
    await loadVoices();
    await loadStats();
    showPage("voices");
  } catch (error) {
    const message = error?.message || String(error) || "Unknown upload error.";
    console.error("SONIVOX voice upload failed:", error);
    notify(message.startsWith("Upload failed:") || message.startsWith("The audio uploaded,") || message.startsWith("This browser") || message.startsWith("Select no more")
      ? message
      : "Could not add this voice: " + message);
  }
});

async function deleteVoice(voice) {
  const confirmation = prompt(
    "This permanently deletes the voice profile and its sample.\n\nTo confirm, type the exact voice name:\n" + voice.name
  );
  if (confirmation !== voice.name) {
    if (confirmation !== null) notify("Voice deletion cancelled. The name did not match.");
    return;
  }
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
    if (!audioData || audioData.size < 44) {
      throw new Error("The generated audio file is empty or incomplete.");
    }
    const wavHeader = new Uint8Array(await audioData.slice(0,12).arrayBuffer());
    const validWav = String.fromCharCode(...wavHeader.slice(0,4)) === "RIFF"
      && String.fromCharCode(...wavHeader.slice(8,12)) === "WAVE";
    if (!validWav) {
      throw new Error("SONIVOX stored an invalid WAV file. This generation cannot be played.");
    }
    // Supabase can return a generic Blob MIME type; label validated WAV bytes
    // explicitly so Android/mobile browsers select the correct decoder.
    const playableWav = new Blob([audioData], {type:"audio/wav"});
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = URL.createObjectURL(playableWav);
    const output = document.querySelector(".empty-audio");
    output.innerHTML = "";
    const heading = document.createElement("strong");
    heading.textContent = "Your speech is ready";
    const player = document.createElement("audio");
    player.controls = true;
    player.preload = "metadata";
    player.src = audioUrl;
    player.className = "audio-player";
    player.addEventListener("error", () => {
      const mediaError = player.error;
      console.error("SONIVOX playback failed:", {
        code: mediaError?.code,
        message: mediaError?.message,
        mimeType: playableWav.type,
        bytes: playableWav.size
      });
      notify("Your browser could not decode this WAV file. Try downloading it to verify the audio.");
    }, {once:true});
    player.load();
    const download = document.createElement("a");
    download.href = audioUrl;
    download.download = "sonivox-" + result.id + ".wav";
    download.className = "secondary-button";
    download.textContent = "Download WAV ↓";
    output.append(heading,player,download);
    notify("Speech generated successfully.");
    await loadStats();
    await loadUsage();
  } catch (error) {
    notify(error.message || "Speech generation failed.");
  } finally {
    button.innerHTML = '<span>✦</span> Generate speech <span class="button-arrow">→</span>';
    await loadUsage();
  }
});
async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2,"0")).join("");
}
async function loadApiKeys() {
  const container = document.getElementById("api-key-list");
  if (!currentSession?.user?.id) {
    container.innerHTML = '<div class="empty-library keys-empty"><strong>Sign in to view your API keys</strong></div>';
    return;
  }
  container.innerHTML = '<div class="empty-library keys-empty"><p>Loading your saved API keys…</p></div>';
  const {data,error} = await supabase.from("sonivox_api_keys")
    .select("id,user_id,name,key_prefix,created_at,last_used_at,revoked_at,preset_id")
    .eq("user_id",currentSession.user.id)
    .order("created_at",{ascending:false});
  if (error) {
    console.error("SONIVOX API-key query failed:", error);
    container.innerHTML = '<div class="empty-library keys-empty"><strong>Could not load API keys</strong><p>' +
      String(error.message || "Database request failed").replace(/[&<>"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch])) +
      '</p></div>';
    notify("Could not load API keys: " + error.message);
    return;
  }
  const keys = data || [];
  const presetIds = [...new Set(keys.map(key => key.preset_id).filter(Boolean))];
  let presetById = {};
  if (presetIds.length) {
    const {data:presets,error:presetError} = await supabase.from("sonivox_voice_presets")
      .select("id,name,allow_overrides")
      .eq("user_id",currentSession.user.id)
      .in("id",presetIds);
    if (presetError) {
      console.error("SONIVOX preset metadata query failed:", presetError);
      notify("Keys loaded, but preset details could not be loaded: " + presetError.message);
    } else {
      presetById = Object.fromEntries((presets || []).map(preset => [preset.id,preset]));
    }
  }
  container.innerHTML = "";
  if (!keys.length) {
    container.innerHTML = '<div class="empty-library keys-empty"><div class="empty-icon">⌘</div><strong>No API keys yet</strong><p>No keys are currently saved under this signed-in account.</p></div>';
    return;
  }
  keys.forEach(key => {
    const preset = presetById[key.preset_id];
    const card = document.createElement("div");
    card.className = "api-key-row";
    const copy = document.createElement("div");
    copy.className = "api-key-copy";
    const name = document.createElement("strong");
    name.textContent = key.name;
    const prefix = document.createElement("code");
    prefix.textContent = key.key_prefix + "••••••••";
    const meta = document.createElement("small");
    meta.textContent = "Created " + new Date(key.created_at).toLocaleDateString() +
      (key.last_used_at ? " · Last used " + new Date(key.last_used_at).toLocaleString() : " · Never used") +
      (preset?.name ? " · Preset: " + preset.name + (preset.allow_overrides ? " · Overrides on" : " · Locked") : (key.preset_id ? " · Preset details unavailable" : " · Legacy voice selection"));
    copy.append(name,prefix,meta);
    const status = document.createElement("span");
    status.className = key.revoked_at ? "key-status revoked" : "key-status active";
    status.textContent = key.revoked_at ? "REVOKED" : "ACTIVE";
    card.append(copy,status);
    const actions = document.createElement("div");
    actions.className = "api-key-actions";
    const toggle = document.createElement("button");
    toggle.className = "text-button";
    toggle.textContent = key.revoked_at ? "Unrevoke" : "Revoke";
    toggle.onclick = async () => {
      const action = key.revoked_at ? "unrevoke" : "revoke";
      if (!confirm(action === "revoke"
        ? "Revoke this API key? All applications using it will stop authenticating immediately."
        : "Reactivate this API key? Applications holding the original secret will work again.")) return;
      const {error:updateError} = await supabase.from("sonivox_api_keys")
        .update({revoked_at:key.revoked_at ? null : new Date().toISOString()})
        .eq("id",key.id)
        .eq("user_id",currentSession.user.id);
      if (updateError) return notify("Could not " + action + " key: " + updateError.message);
      notify("API key " + (action === "revoke" ? "revoked." : "reactivated."));
      await loadApiKeys();
    };
    const remove = document.createElement("button");
    remove.className = "text-button danger";
    remove.textContent = "Delete";
    remove.onclick = async () => {
      if (!confirm("Permanently delete this API key? This cannot be undone. Create a new key if you need it again.")) return;
      const {error:deleteError} = await supabase.from("sonivox_api_keys").delete()
        .eq("id",key.id).eq("user_id",currentSession.user.id);
      if (deleteError) return notify("Could not delete key: " + deleteError.message);
      notify("API key permanently deleted.");
      await loadApiKeys();
    };
    actions.append(toggle,remove);
    card.append(actions);
    container.append(card);
  });
}
async function createApiKey() {
  if (!voices.length) return notify("Add a voice profile before creating a preset-bound API key.");
  const choices = voices.map((voice,index) => (index + 1) + ". " + voice.name).join("\n");
  const selected = Number(prompt("Choose the voice for this API preset:\n" + choices));
  if (!Number.isInteger(selected) || selected < 1 || selected > voices.length) return;
  const voice = voices[selected - 1];
  const presetName = prompt("Name this voice preset (for example, Warm Narrator):");
  if (!presetName?.trim()) return;
  const allowOverrides = confirm("Allow developers using this key to override the selected voice in individual requests?\n\nOK = Allow voice overrides\nCancel = Lock this key to the preset");
  const keyName = prompt("Name this API key (for example, My Node.js app):");
  if (!keyName?.trim()) return;
  const button = document.getElementById("create-key-button");
  button.disabled = true;
  try {
    const {data:preset,error:presetError} = await supabase.from("sonivox_voice_presets").insert({
      user_id:currentSession.user.id,
      voice_id:voice.id,
      name:presetName.trim().slice(0,80),
      settings:{},
      allow_overrides:allowOverrides
    }).select("id").single();
    if (presetError) throw presetError;
    const random = crypto.getRandomValues(new Uint8Array(32));
    const secret = "svx_live_" + Array.from(random, byte => byte.toString(16).padStart(2,"0")).join("");
    const hash = await sha256Hex(secret);
    const prefix = secret.slice(0,16);
    const {error} = await supabase.from("sonivox_api_keys").insert({
      user_id:currentSession.user.id,
      name:keyName.trim().slice(0,80),
      key_prefix:prefix,
      key_hash:hash,
      preset_id:preset.id
    });
    if (error) {
      await supabase.from("sonivox_voice_presets").delete().eq("id",preset.id);
      throw error;
    }
    document.getElementById("created-api-key").textContent = secret;
    document.getElementById("key-created").classList.remove("hidden");
    document.getElementById("copy-created-key").onclick = async () => {
      await navigator.clipboard.writeText(secret);
      notify("API key copied.");
    };
    notify("Preset-bound API key created. Copy it now; it will not be shown again.");
    await loadApiKeys();
    document.getElementById("key-created").scrollIntoView({behavior:"smooth",block:"center"});
  } catch (error) {
    notify("Could not create API key: " + (error.message || "Unknown error"));
  } finally {
    button.disabled = false;
  }
}
document.getElementById("create-key-button").onclick = createApiKey;
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
  supabase = createClient(config.supabase_url,config.publishable_key,{auth:{flowType:"pkce",detectSessionInUrl:true,persistSession:true,autoRefreshToken:true}});
  const {data:{session}} = await supabase.auth.getSession();
  if (session) {
    currentSession = session;
    await enterWorkspace();
  } else {
    location.replace("/signin");
    return;
  }
  supabase.auth.onAuthStateChange(async (_event,sessionNow) => {
    if (sessionNow) currentSession = sessionNow;
    else if (currentSession) lockWorkspace();
  });
}
init().catch(error => notify("Could not start SONIVOX: " + error.message));
