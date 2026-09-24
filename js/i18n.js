// ── I18N (English / Swahili) ─────────────────────────────────
// Pattern: give any element you want translated a `data-i18n="key"`
// attribute for its text, or `data-i18n-placeholder="key"` for an input
// placeholder. Then add that key with its English + Swahili strings below.
// To translate more of the app yourself, just copy this shape.
const I18N_STRINGS = {
  "login.title":         { en: "DrDemic School Manager", sw: "Msimamizi wa Shule DrDemic" },
  "login.subtitle":      { en: "Sign in to your account to continue", sw: "Ingia kwenye akaunti yako ili kuendelea" },
  "login.regcode_label": { en: "School Registration Code", sw: "Namba ya Usajili wa Shule" },
  "login.user_label":    { en: "Username", sw: "Jina la Mtumiaji" },
  "login.pass_label":    { en: "Password", sw: "Nywila" },
  "login.signin_btn":    { en: "Sign In", sw: "Ingia" },
  "login.register_link": { en: "New school? Register here →", sw: "Shule mpya? Jisajili hapa →" },
  "login.regcode_ph":    { en: "e.g. S1234", sw: "mfano: S1234" },
  "login.user_ph":       { en: "Enter username", sw: "Weka jina la mtumiaji" },
  "login.pass_ph":       { en: "Enter password", sw: "Weka nywila" },
};

let currentLang = localStorage.getItem("dd_lang") || "en";

function applyI18n(){
  document.querySelectorAll("[data-i18n]").forEach(el=>{
    const entry = I18N_STRINGS[el.getAttribute("data-i18n")];
    if(entry && entry[currentLang]) el.textContent = entry[currentLang];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el=>{
    const entry = I18N_STRINGS[el.getAttribute("data-i18n-placeholder")];
    if(entry && entry[currentLang]) el.placeholder = entry[currentLang];
  });
  const toggleBtn = document.getElementById("lang-toggle-btn");
  if(toggleBtn) toggleBtn.textContent = currentLang === "en" ? "🇹🇿 Kiswahili" : "🇬🇧 English";
}

function toggleLang(){
  currentLang = currentLang === "en" ? "sw" : "en";
  localStorage.setItem("dd_lang", currentLang);
  applyI18n();
}

document.addEventListener("DOMContentLoaded", applyI18n);