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
  "outstanding-performers": { en: "No Outstanding Performers identified.", sw: "Hakuna Ufaulu wa Kipekee"},
  "student-to-support":  { en: "No Students Needing Support identified.", sw: "Hakuna Mwanafunzi Anaehitaji Uangalizi wa Karibu"},
  "no-impr-student":     { en: "No improved students yet.", sw: "Hakuna wanafunzi waliopanda"},
  "no-decl-student":     { en: "No declining students.", sw: "Hakuna wanafunzi walioshuka"},
  "student-at-risk":     { en: "No students at risk.", sw: "Hakuna wanafunzi walio katika hatari"},
  "analytics-no-data":   { en: "No data", sw: "Hakuna taarifa"},
  "mark-as-read-btn":    { en: "Mark as read", sw: "Weka alama kuwa imesomwa"},  
  "plan":                { en: "Plan", sw:"Mpango"},
  "pend-verif":          { en: "Pending Verification", sw: "Inasubiri kuhakikiwa"},
  "no-sub":              { en: "No active subscription", sw: "Hakuna usajili unaotumika"},
  "sub-now-btn":         { en: "Subscribe Now", sw: "Lipia Sasa"},
  "no-studs":            { en: "No students yet", sw: "Hakuna wanafunzi bado"},
  "best-perf-class":     { en: "Best Performing Class", sw: "Darasa linalofanya vizuri zaidi"},
  "weakest-perf-class":  { en: "Weakest Performing Class", sw: "Darasa lenye ufaulu duni zaidi"},
  // ── parent portal ──
  "our-school":      { en: "our school", sw: "shule yetu" },
  "greet-morning":   { en: "Good morning", sw: "Habari za asubuhi" },
  "greet-afternoon": { en: "Good afternoon", sw: "Habari za mchana" },
  "greet-evening":   { en: "Good evening", sw: "Habari za jioni" },
  "welcome-portal":  { en: "Welcome to {school} Student Portal", sw: "Karibu kwenye Tovuti ya Wanafunzi ya {school}" },
  "no-pub-results":  { en: "No published results yet", sw: "Bado hakuna matokeo yaliyochapishwa" },
  "no-pub-assess":   { en: "No published assessments yet", sw: "Bado hakuna mitihani iliyochapishwa" },
  "select-term":     { en: "Select a term", sw: "Chagua muhula" },
  "select-term-assess": { en: "Select term and assessment", sw: "Chagua muhula na mtihani" },
  "no-student-linked": { en: "No student linked to this account", sw: "Hakuna mwanafunzi aliyeunganishwa na akaunti hii" },
  "final-exam":      { en: "Final Exam", sw: "Mtihani wa Mwisho" },
  "avg-lbl":         { en: "Average", sw: "Wastani" },
  "grade-lbl":       { en: "Grade", sw: "Daraja" },
  "class-pos":       { en: "Class Pos", sw: "Nafasi ya Darasa" },
  "stream-pos":      { en: "Stream Pos", sw: "Nafasi ya Mkondo" },
  "th-subject":      { en: "Subject", sw: "Somo" },
  "th-score":        { en: "Score", sw: "Alama" },
  "th-position":     { en: "Position", sw: "Nafasi" },
  "no-marks-yet":    { en: "No marks entered yet for this assessment", sw: "Bado hakuna alama zilizoingizwa kwa mtihani huu" },
  "no-ann":          { en: "No announcements yet", sw: "Bado hakuna matangazo" },
  "sub-to-see":      { en: "Subscribe to see this", sw: "Jiunge ili kuona hili" },
  "no-pub-short":    { en: "No published results yet.", sw: "Bado hakuna matokeo yaliyochapishwa." },
  "no-pub-long":     { en: "No published results yet. Results will appear here once published by the school.", sw: "Bado hakuna matokeo yaliyochapishwa. Matokeo yataonekana hapa shule itakapoyachapisha." },
  "not-enough-data": { en: "Not enough data", sw: "Taarifa hazitoshi" },
  "need-two":        { en: "Need at least 2 published results to generate insights.", sw: "Inahitajika angalau matokeo 2 yaliyochapishwa ili kutoa uchambuzi." },
  "no-insights":     { en: "No insights available yet.", sw: "Bado hakuna uchambuzi." },
  "ins-outstanding": { en: "Outstanding performance in {subject}! {student} consistently excels here — keep maintaining this exceptional standard.", sw: "Ufaulu wa kipekee katika {subject}! {student} anafanya vizuri mara kwa mara hapa — endelea kudumisha kiwango hiki cha juu." },
  "ins-urgent":      { en: "{subject} requires urgent attention. {student} is scoring below expectations — increased focus, revision and support are strongly recommended.", sw: "{subject} inahitaji uangalizi wa haraka. {student} anapata alama chini ya matarajio — umakini zaidi, marudio na msaada vinashauriwa sana." },
  "ins-improved":    { en: "Excellent improvement in {subject}! {student} has made significant progress — keep up this momentum.", sw: "Maendeleo mazuri sana katika {subject}! {student} ameonyesha hatua kubwa — endelea na kasi hii." },
  "ins-declined":    { en: "A noticeable decline has been observed in {subject}. {student} is encouraged to dedicate more time to revision.", sw: "Kushuka kumeonekana katika {subject}. {student} anahimizwa kutumia muda zaidi kwa marudio." },
  "ins-steady":      { en: "{student} is maintaining consistent performance in {subject}. Steady progress — a little extra push could move results to the next grade.", sw: "{student} anadumisha ufaulu thabiti katika {subject}. Maendeleo ya taratibu — juhudi kidogo zaidi zinaweza kupandisha matokeo hadi daraja linalofuata." },
  "ins-avg-up":      { en: "📈 Overall average improved from {prev} to {cur}. Great work, {student}!", sw: "📈 Wastani wa jumla umepanda kutoka {prev} hadi {cur}. Kazi nzuri, {student}!" },
  "ins-avg-down":    { en: "📉 Overall average dropped from {prev} to {cur}. {student} should focus on weaker areas.", sw: "📉 Wastani wa jumla umeshuka kutoka {prev} hadi {cur}. {student} anapaswa kuzingatia maeneo dhaifu." },
  "ins-top-class":   { en: "🏆 {student} is among the top 25% of students in the class — an outstanding achievement!", sw: "🏆 {student} yuko miongoni mwa 25% bora ya wanafunzi darasani — mafanikio ya kipekee!" },
  "ins-top-stream":  { en: "⭐ {student} is among the top 25% performers in the class stream. Aim for the top of the whole class!", sw: "⭐ {student} yuko miongoni mwa 25% bora katika mkondo wa darasa. Lenga kuwa wa kwanza darasa zima!" },
  // ── analytics (admin / teachers) ──
  "an-avg":          { en: "📊 Average", sw: "📊 Wastani" },
  "current-avg":     { en: "Current average: <strong>{v}</strong>", sw: "Wastani wa sasa: <strong>{v}</strong>" },
  "an-outstanding":  { en: "🌟 Outstanding Performers", sw: "🌟 Wanafunzi Bora Kipekee" },
  "an-support":      { en: "📉 Students Needing Support", sw: "📉 Wanafunzi Wanaohitaji Msaada" },
  "an-improved":     { en: "📈 Improved Students", sw: "📈 Wanafunzi Waliopanda" },
  "an-declining":    { en: "📉 Declining Students", sw: "📉 Wanafunzi Walioshuka" },
  "an-best":         { en: "📚 Best Subject", sw: "📚 Somo Bora Zaidi" },
  "an-weak":         { en: "📚 Weakest Subject", sw: "📚 Somo Dhaifu Zaidi" },
  "an-risk":         { en: "⚠ Students At Risk", sw: "⚠ Wanafunzi Walio Hatarini" },
  "subj-avg":        { en: "{s} — average <strong>{v}</strong>", sw: "{s} — wastani <strong>{v}</strong>" },
  "risk-reason":     { en: "Lowest grade in two consecutive examinations.", sw: "Daraja la chini kabisa katika mitihani miwili mfululizo." },
  "pos-short":       { en: "Pos", sw: "Nafasi" },
  "no-trend-data":   { en: "Not enough data yet", sw: "Taarifa hazitoshi bado" },
  "overall-school":  { en: "Overall School", sw: "Shule Nzima" },
  "all-streams":     { en: "All Streams", sw: "Mikondo Yote" },
  "no-assign":       { en: "No subject assignments yet.", sw: "Bado hujapewa masomo." },
  "an-load-fail":    { en: "Failed to load analytics", sw: "Imeshindwa kupakia uchambuzi" },
  // ── dashboard fixes ──
  "expires-on":      { en: "Expires {d} ({n} days left)", sw: "Unaisha {d} (siku {n} zimebaki)" },
  "renew-soon":      { en: "Renew soon", sw: "Upyaisha hivi karibuni" },
  "active-badge":    { en: "Active", sw: "Inatumika" },
  "avg-pct":         { en: "{v}% average", sw: "Wastani wa {v}%" },
};

let currentLang = localStorage.getItem("dd_lang") || "en";

function t(key, vars){
  const e = I18N_STRINGS[key];
  let s = e ? (e[currentLang] || e.en) : key;
  if(vars) Object.keys(vars).forEach(k=>{ s = s.split("{"+k+"}").join(vars[k]); });
  return s;
}

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