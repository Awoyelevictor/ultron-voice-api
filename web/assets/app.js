const pages = ["dashboard", "voices", "keys"];
const labels = { dashboard: "Overview", voices: "My voices", keys: "API keys" };
const toast = document.getElementById("toast");
let toastTimer;
function notify(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}
function showPage(page) {
  if (page === "home") page = "dashboard";
  if (!pages.includes(page)) return;
  pages.forEach(name => document.getElementById("page-" + name).classList.toggle("hidden", name !== page));
  document.querySelectorAll(".nav-link").forEach(link => link.classList.toggle("active", link.dataset.page === page));
  document.getElementById("crumb").textContent = labels[page];
  document.getElementById("sidebar").classList.remove("open");
  window.scrollTo({ top: 0, behavior: "smooth" });
}
document.querySelectorAll("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
document.getElementById("menu-toggle").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
const script = document.getElementById("speech-text");
script.addEventListener("input", () => {
  document.getElementById("char-count").textContent = script.value.length + " / 1,000";
});
["add-voice-button", "empty-add-button"].forEach(id => document.getElementById(id).addEventListener("click", () => notify("Voice uploads will unlock when private storage and account access are connected.")));
document.getElementById("upload-info-button").addEventListener("click", () => notify("Upload an MP3 or WAV sample, confirm permission to use the voice, then save your private profile."));
document.getElementById("create-key-button").addEventListener("click", () => notify("API key creation will unlock after secure sign-in is connected."));
document.getElementById("help-button")?.addEventListener("click", () => notify("SONIVOX MVP preview — account and provider setup is the next integration step."));
document.querySelector(".help-button").addEventListener("click", () => notify("SONIVOX MVP preview — account and provider setup is the next integration step."));
document.getElementById("generate-button").addEventListener("click", () => notify("Speech generation is not connected yet."));
