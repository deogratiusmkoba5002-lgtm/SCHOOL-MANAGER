// ── I18N (English / Swahili) ─────────────────────────────────
// Pattern: give any element you want translated a `data-i18n="key"`
// attribute for its text, or `data-i18n-placeholder="key"` for an input
// placeholder. Then add that key with its English + Swahili strings below.
// To translate more of the app yourself, just copy this shape.
const I18N_STRINGS = {
  "login.subtitle":      { en: "Sign in to your account to continue", sw: "Ingia kwenye akaunti yako ili kuendelea" },
  "login.regcode_label": { en: "School Registration Code", sw: "Namba ya Usajili wa Shule" },
  "login.user_label":    { en: "Username", sw: "Jina la Mtumiaji" },
  "login.pass_label":    { en: "Password", sw: "Nywila" },
  "login.signin_btn":    { en: "Sign In", sw: "Ingia" },
  "login.register_link": { en: "New school? Register here →", sw: "Shule mpya? Jisajili hapa →" },
  "login.regcode_ph":    { en: "e.g. S1234", sw: "mfano: S1234" },
  "login.user_ph":       { en: "Enter username", sw: "Weka jina la mtumiaji" },
  "login.pass_ph":       { en: "Enter password", sw: "Weka nywila" },
  "overview-avg":        { en: "Current average", sw: "Wastani wa sasa"},
  "outstanding-performers": { en: "No Outstanding Performers identified.", sw: "Hakuna Ufaulu wa Kipekee"},
  "student-to-support":  { en: "No Students Needing Support identified.", sw: "Hakuna Mwanafunzi Anaehitaji Uangalizi wa Karibu"},
  "no-impr-student":     { en: "No improved students yet.", sw: "Hakuna wanafunzi waliopanda"},
  "no-decl-student":     { en: "No declining students.", sw: "Hakuna wanafunzi walioshuka"},
  "student-at-risk":     { en: "No students at risk.", sw: "Hakuna wanafunzi walio katika hatari"},
  "analytics-no-data":   { en: "No data", sw: "Hakuna taarifa"},
  "analytics-best-subject": { en: "Average", sw: "Wastani"},
  "analytics-weakest-subject": { en: "Average", sw: "Wastani"},
  "mark-as-read-btn":    { en: "Mark as read", sw: "Weka alama kuwa imesomwa"},  
  "plan":                { en: "Plan", sw:"Mpango"},
  "pend-verif":          { en: "Pending Verification", sw: "Inasubiri kuhakikiwa"},
  "no-sub":              { en: "No active subscription", sw: "Hakuna usajili unaotumika"},
  "sub-now-btn":         { en: "Subscribe Now", sw: "Lipia Sasa"},
  "expires":             { en: "Expires", sw: "Muda wake unaisha"},
  "renew-soon":          { en: "'Renew soon':'Active'", sw: "'Upyaisha hivi karibuni':'Inayotumika'"},
  "no-studs":            { en: "No students yet", sw: "Hakuna wanafunzi bado"},
  "best-perf-class":     { en: "Best Performing Class", sw: "Darasa linalofanya vizuri zaidi"},
  "weakest-perf-class":  { en: "Weakest Performing Class", sw: "Darasa lenye ufaulu duni zaidi"},
  "average":             { en: "Average", sw: "Wastani"},
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