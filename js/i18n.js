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
  // ── nav + shared ──
  "back":            { en: "Back", sw: "Rudi" },
  "back-arrow":      { en: "← Back", sw: "← Rudi" },
  "nav-dashboard":   { en: "Dashboard", sw: "Dashibodi" },
  "nav-reports":     { en: "View Reports", sw: "Tazama Ripoti" },
  "nav-analytics":   { en: "Academic Analytics", sw: "Uchambuzi wa Masomo" },
  "nav-ann":         { en: "Announcements", sw: "Matangazo" },
  "nav-sub":         { en: "Subscription", sw: "Usajili" },
  "lbl-term":        { en: "Select Term", sw: "Chagua Muhula" },
  "lbl-assess":      { en: "Select Assessment", sw: "Chagua Mtihani" },
  // ── parent dashboard ──
  "p-dash-reports-sub":   { en: "See your child's report cards", sw: "Tazama ripoti za mtoto wako" },
  "p-dash-analytics-sub": { en: "Track academic performance", sw: "Fuatilia maendeleo ya kitaaluma" },
  "p-dash-ann-sub":       { en: "School news and notices", sw: "Habari na taarifa za shule" },
  // ── parent reports ──
  "rep-title":       { en: "View Results & Reports", sw: "Tazama Matokeo na Ripoti" },
  "rep-sub":         { en: "Choose what you would like to view", sw: "Chagua unachotaka kutazama" },
  "rep-cards":       { en: "Report Cards", sw: "Ripoti za Mwanafunzi" },
  "rep-cards-sub":   { en: "Full official report card with all marks, grades and remarks", sw: "Ripoti kamili rasmi yenye alama zote, madaraja na maoni" },
  "rep-results":     { en: "View Results", sw: "Tazama Matokeo" },
  "rep-results-sub": { en: "Marks for a specific CA or exam — see scores and position per subject", sw: "Alama za CA au mtihani maalum — tazama alama na nafasi kwa kila somo" },
  "btn-view-rc":     { en: "View Report Card", sw: "Tazama Ripoti" },
  // ── parent analytics ──
  "an-sub":          { en: "Performance trends, insights and recommendations", sw: "Mwelekeo wa ufaulu, uchambuzi na mapendekezo" },
  "an-tab-avg":      { en: "Overall Average Trend", sw: "Mwelekeo wa Wastani" },
  "an-tab-subj":     { en: "Subject Trend", sw: "Mwelekeo wa Somo" },
  "an-sel-subj":     { en: "Select Subject", sw: "Chagua Somo" },
  "pa-best":         { en: "💪 Best Subjects", sw: "💪 Masomo Bora" },
  "pa-needs":        { en: "📚 Needs Attention", sw: "📚 Yanahitaji Uangalizi" },
  "pa-insights":     { en: "💡 Insights & Recommendations", sw: "💡 Uchambuzi na Mapendekezo" },
  // ── parent announcements / subscription ──
  "ann-sub":         { en: "School news and important notices", sw: "Habari za shule na taarifa muhimu" },
  "sub-sub":         { en: "Unlock full results, detailed analytics and report-card PDFs", sw: "Fungua matokeo kamili, uchambuzi wa kina na PDF za ripoti" },
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
  ["lang-toggle-btn","lang-toggle-btn-app"].forEach(id=>{
    const b = document.getElementById(id);
    if(b) b.textContent = currentLang === "en" ? "🇹🇿 Kiswahili" : "🇬🇧 English";
  });
  translateDom();
}

function toggleLang(){
  currentLang = currentLang === "en" ? "sw" : "en";
  localStorage.setItem("dd_lang", currentLang);
  applyI18n();
  if(typeof currentUser !== "undefined" && currentUser){
    buildNav();
    if(currentPageId) _showPage(currentPageId);   // re-render dynamic content in the new language
    applyI18n();
  }
}

document.addEventListener("DOMContentLoaded", applyI18n);

// ── AUTO-TRANSLATION: exact-text dictionary (covers static HTML, JS-rendered UI and toasts) ──
const SW_TEXT = {
  // common
  "Back":"Rudi","← Back":"← Rudi","Cancel":"Ghairi","Save":"Hifadhi","Close":"Funga","Delete":"Futa","Edit":"Hariri",
  "Add":"Ongeza","Done":"Imekamilika","Loading...":"Inapakia...","View":"Tazama","Actions":"Vitendo","Name":"Jina",
  "Class":"Darasa","Stream":"Mkondo","Status":"Hali","Student":"Mwanafunzi","Students":"Wanafunzi","Teacher":"Mwalimu",
  "Subject":"Somo","Subjects":"Masomo","Exam":"Mtihani","Term":"Muhula","Date":"Tarehe","Type":"Aina","Amount":"Kiasi",
  "Total":"Jumla","Avg":"Wastani","Pos":"Nafasi","Grd":"Daraja","Points":"Pointi","Division":"Divisheni","Score":"Alama",
  "Final":"Mwisho","Username":"Jina la Mtumiaji","Full Name":"Jina Kamili","Title":"Kichwa","Message":"Ujumbe",
  "Clear":"Futa Chaguo","Apply":"Tumia","Filter":"Chuja","Copy":"Nakili","Label":"Jina","Action":"Hatua",
  "Assessment":"Tathmini","Assignment":"Jukumu","Scope":"Wigo","Report":"Ripoti","Access":"Ufikiaji","PDF":"PDF",
  "All Classes":"Madarasa Yote","All Streams":"Mikondo Yote","Locked":"Imefungwa","OPEN":"WAZI","CLOSED":"IMEFUNGWA",
  // nav / sidebar
  "Dashboard":"Dashibodi","Teachers":"Walimu","Terms":"Muhula","Score Sheets":"Karatasi za Alama","Rankings":"Nafasi",
  "View Admin Analytics":"Uchambuzi wa Shule","Past Terms":"Muhula Zilizopita","Parents":"Wazazi",
  "⭐ Star System":"⭐ Mfumo wa Nyota","Config":"Mipangilio","Enter Marks":"Weka Alama",
  "Teacher Analytics":"Uchambuzi wa Mwalimu","Class Teacher Analytics":"Uchambuzi wa Mwalimu wa Darasa","Logout":"Toka",
  "Academic System":"Mfumo wa Taaluma","[Parent Portal]":"[Tovuti ya Mzazi]","[Class Teacher]":"[Mwalimu wa Darasa]",
  "[admin]":"[msimamizi]","[teacher]":"[mwalimu]","Academic Management System":"Mfumo wa Usimamizi wa Taaluma",
  "No active term":"Hakuna muhula unaoendelea","⚠ No active term":"⚠ Hakuna muhula unaoendelea",
  "Admin must open a term before marks can be entered":"Msimamizi lazima afungue muhula kabla ya kuweka alama",
  // dashboard
  "Welcome back — here's a quick overview":"Karibu tena — huu ni muhtasari wa haraka",
  "Total Students":"Jumla ya Wanafunzi","Active Classes":"Madarasa Yanayotumika","Subscription":"Usajili",
  "Class Performance":"Ufaulu wa Madarasa","Platform Notices":"Matangazo ya Jukwaa","Recent Students":"Wanafunzi wa Hivi Karibuni",
  "ID":"Namba",
  // parents page (admin)
  "Manage what parents can see and send announcements":"Simamia wanachoweza kuona wazazi na tuma matangazo",
  "Results Visibility":"Uonekanaji wa Matokeo","Update Results (Publish)":"Sasisha Matokeo (Chapisha)",
  "Hide Results":"Ficha Matokeo","Post Announcement":"Tuma Tangazo","Target Classes":"Madarasa Lengwa",
  "Posted Announcements":"Matangazo Yaliyotumwa","✅ Results are VISIBLE to parents":"✅ Matokeo YANAONEKANA kwa wazazi",
  "🔒 Results are HIDDEN from parents":"🔒 Matokeo YAMEFICHWA kwa wazazi","Select what to publish":"Chagua cha kuchapisha",
  "Publish Selected":"Chapisha Vilivyochaguliwa","No announcements yet.":"Bado hakuna matangazo.",
  // students
  "Manage all enrolled students":"Simamia wanafunzi wote waliosajiliwa","Import Excel":"Leta kutoka Excel",
  "Add Student":"Ongeza Mwanafunzi","All Students":"Wanafunzi Wote","Download Reports":"Pakua Ripoti",
  "Delete Selected":"Futa Waliochaguliwa","No students found":"Hakuna wanafunzi waliopatikana",
  "Search students…":"Tafuta wanafunzi…","Loading students…":"Inapakia wanafunzi…",
  "Add New Student":"Ongeza Mwanafunzi Mpya","Edit Student":"Hariri Mwanafunzi","Save Changes":"Hifadhi Mabadiliko",
  "Parent / Guardian Phone Number":"Namba ya Simu ya Mzazi / Mlezi","Stream (optional)":"Mkondo (si lazima)",
  "— No stream / Overall —":"— Hakuna mkondo / Wote —","Student Added Successfully!":"Mwanafunzi Ameongezwa Kikamilifu!",
  "Parent Access":"Ufikiaji wa Mzazi","Username":"Jina la Mtumiaji",
  // classes
  "Classes & Streams":"Madarasa na Mikondo","Add New Class":"Ongeza Darasa Jipya","Add Class":"Ongeza Darasa",
  "Add Stream":"Ongeza Mkondo","+ Add Stream":"+ Ongeza Mkondo","+ Add":"+ Ongeza","Streams:":"Mikondo:",
  "Create classes and optional streams under each class":"Unda madarasa na mikondo (si lazima) chini ya kila darasa",
  // teachers
  "Create accounts and manage assignments. Only admin can do this.":"Fungua akaunti na simamia majukumu. Msimamizi pekee anaweza.",
  "Create Teacher Account":"Fungua Akaunti ya Mwalimu","Create Account":"Fungua Akaunti","All Teachers":"Walimu Wote",
  "Assign Subject":"Mpe Somo","Class Teacher Of":"Mwalimu wa Darasa la","Assignments":"Majukumu",
  "Assign Teacher to Subject":"Mpe Mwalimu Somo","Add Another Subject / Class":"Ongeza Somo / Darasa Jingine",
  "Assign Another Teacher":"Mpe Mwalimu Mwingine","Class Teacher Assignment":"Ugawaji wa Mwalimu wa Darasa",
  "This teacher is a class teacher":"Mwalimu huyu ni mwalimu wa darasa",
  "Assigned Class / Stream":"Darasa / Mkondo Alilopangiwa","Edit CT":"Hariri Mwalimu wa Darasa",
  "Set as CT":"Mteue Mwalimu wa Darasa","teaches":"anafundisha","in":"katika","and":"na",
  "No teachers yet. Create one above.":"Bado hakuna walimu. Fungua akaunti hapo juu.","⏳ Pending":"⏳ Anasubiri","✓ Active":"✓ Hai",
  "Password (set with teacher present)":"Nywila (weka mwalimu akiwepo)",
  // marks
  "Enter CA and exam marks for your students":"Weka alama za CA na mtihani kwa wanafunzi wako",
  "Mark Entry Configuration":"Mpangilio wa Kuweka Alama","Assessment Type":"Aina ya Tathmini",
  "Load Students":"Pakia Wanafunzi","Save All Marks":"Hifadhi Alama Zote","✓ saved":"✓ imehifadhiwa",
  "unsaved":"haijahifadhiwa","invalid":"si sahihi","✗ error":"✗ hitilafu","Saving...":"Inahifadhi...",
  // reports
  "Report Cards":"Ripoti za Wanafunzi","View and download student report cards":"Tazama na pakua ripoti za wanafunzi",
  "Student ID":"Namba ya Mwanafunzi","View Report":"Tazama Ripoti","Student Report Card":"Ripoti ya Mwanafunzi",
  "Class Teacher Remark":"Maoni ya Mwalimu wa Darasa","Head of School Remark":"Maoni ya Mkuu wa Shule",
  "Weights":"Uzito","Average":"Wastani","Grade":"Daraja","Class Position":"Nafasi ya Darasa","Stream Position":"Nafasi ya Mkondo",
  "Quick Template":"Kiolezo cha Haraka","💾 Save Class Teacher Remark":"💾 Hifadhi Maoni ya Mwalimu wa Darasa",
  "💾 Save Head of School Remark":"💾 Hifadhi Maoni ya Mkuu wa Shule","Download Report PDF":"Pakua Ripoti (PDF)",
  "🔒 Report PDF - Parent access required":"🔒 PDF ya Ripoti - Inahitaji ufikiaji wa mzazi",
  "— Pick a template or type below —":"— Chagua kiolezo au andika hapa chini —",
  // terms
  "Manage academic terms — open, view, and close them":"Simamia muhula za masomo — fungua, tazama na funga",
  "Open New Term":"Fungua Muhula Mpya","Open Term":"Fungua Muhula","Number of CAs":"Idadi ya CA","CA Weight (%)":"Uzito wa CA (%)",
  "Exam Weight (%) — auto":"Uzito wa Mtihani (%) — otomatiki","Tests (Current Term)":"Majaribio (Muhula wa Sasa)",
  "Add Test":"Ongeza Jaribio","All Terms":"Muhula Zote","CAs":"CA","CA Weight":"Uzito wa CA","Exam Weight":"Uzito wa Mtihani",
  "Close Term":"Funga Muhula","Test Label":"Jina la Jaribio","No tests yet this term.":"Bado hakuna majaribio muhula huu.",
  "Published to parents":"Imechapishwa kwa wazazi","Not published":"Haijachapishwa",
  // sheets / past / rankings
  "Class-wide score sheets and PDF exports":"Karatasi za alama za darasa zima na PDF","Sheet Type":"Aina ya Karatasi",
  "Marks Score Sheet":"Karatasi ya Alama","Grade Score Sheet":"Karatasi ya Madaraja","Examination Level":"Ngazi ya Mtihani",
  "Grades Used for Division":"Madaraja Yanayotumika kwa Divisheni","My School's Grades":"Madaraja ya Shule Yangu",
  "NECTA Fixed Grades":"Madaraja Rasmi ya NECTA","Non-Credit Subjects":"Masomo Yasiyohesabiwa",
  "CA Score Sheet":"Karatasi ya Alama za CA","Exam Score Sheet":"Karatasi ya Alama za Mtihani",
  "Terminal Score Sheet":"Karatasi ya Alama za Muhula","No data found":"Hakuna taarifa zilizopatikana",
  "View marks from closed terms (read-only)":"Tazama alama za muhula zilizofungwa (kusoma tu)",
  "Subject Marks Table":"Jedwali la Alama za Somo","Show Marks":"Onyesha Alama",
  "Rank students by subject and assessment":"Panga wanafunzi kwa somo na tathmini","Show Ranking":"Onyesha Nafasi",
  "Final Exam":"Mtihani wa Mwisho","No data":"Hakuna taarifa",
  // analytics
  "Admin Analytics":"Uchambuzi wa Msimamizi","School-wide performance insights":"Uchambuzi wa ufaulu wa shule nzima",
  "Current examination:":"Mtihani wa sasa:","Performance insights for your class":"Uchambuzi wa ufaulu wa darasa lako",
  "Subject-level performance insights":"Uchambuzi wa ufaulu kwa somo",
  // star system
  "Earn rewards for activating your school and referring others":"Pata zawadi kwa kuamsha shule yako na kuwaleta wengine",
  "🔔 Notifications":"🔔 Arifa","Mark all read":"Weka zote zimesomwa","Mark read":"Weka imesomwa",
  "Stars (Available)":"Nyota (Zilizopo)","TZS Available":"TZS Zilizopo","Next Star":"Nyota Inayofuata",
  "Your Referral Link":"Kiungo Chako cha Rufaa","Payout Mobile-Money Number":"Namba ya Pesa za Simu ya Malipo",
  "Save Number":"Hifadhi Namba","Update Number":"Badilisha Namba","Request Withdrawal":"Omba Kutoa Fedha",
  "Reward & Withdrawal History":"Historia ya Zawadi na Utoaji","Stars":"Nyota","Verified":"Imehakikiwa","Unverified":"Haijahakikiwa",
  "No reward activity yet.":"Bado hakuna shughuli za zawadi.",
  // config
  "Configuration":"Mipangilio","Everything set during registration — editable any time":"Kila kitu kilichowekwa wakati wa usajili — kinaweza kubadilishwa wakati wowote",
  "School Identity":"Utambulisho wa Shule","Grading System & Divisions":"Mfumo wa Madaraja na Divisheni",
  "Principal Subjects":"Masomo Makuu","Save Grading System":"Hifadhi Mfumo wa Madaraja","School Logo":"Nembo ya Shule",
  "Choose File":"Chagua Faili","School Name":"Jina la Shule","Motto":"Kauli Mbiu","School Phone":"Simu ya Shule",
  "School Email":"Barua Pepe ya Shule","Admin / Support Contact Phone":"Simu ya Msimamizi / Msaada",
  "Save School Identity":"Hifadhi Utambulisho wa Shule","Registration Code":"Namba ya Usajili",
  "Save Registration Code":"Hifadhi Namba ya Usajili","School Registration Code":"Namba ya Usajili wa Shule",
  "Add Subject":"Ongeza Somo","Save Subjects":"Hifadhi Masomo","Grading System":"Mfumo wa Madaraja","Add Grade":"Ongeza Daraja",
  "Active Term":"Muhula Unaoendelea","Abbr:":"Kifupi:","From":"Kuanzia","= Grade:":"= Daraja:",
  "Use Free Plan":"Tumia Mpango wa Bure","Subscribe":"Lipia","Submit Payment":"Wasilisha Malipo",
  "Cancel This Request":"Ghairi Ombi Hili","Pending Verification":"Inasubiri Kuhakikiwa",
  // password / import modals
  "Set Your Password":"Weka Nywila Yako","Current Password (given by admin)":"Nywila ya Sasa (uliyopewa na msimamizi)",
  "New Password":"Nywila Mpya","Confirm New Password":"Thibitisha Nywila Mpya","Set Password & Continue":"Weka Nywila na Endelea",
  "Import Students from Excel / CSV":"Leta Wanafunzi kutoka Excel / CSV","Preview File →":"Hakiki Faili →",
  "Confirm Import":"Thibitisha Uingizaji","Continue →":"Endelea →","Inserted":"Zilizoingizwa","Duplicates":"Zilizojirudia",
  "Skipped":"Zilizorukwa","Errors":"Hitilafu","Import Complete":"Uingizaji Umekamilika",
  "📥 Download Template":"📥 Pakua Kiolezo",
  // toasts & server messages
  "Marks saved!":"Alama zimehifadhiwa!","Remark saved!":"Maoni yamehifadhiwa!","Term updated!":"Muhula umebadilishwa!",
  "Student updated!":"Mwanafunzi amebadilishwa!","Student removed":"Mwanafunzi ameondolewa","Subjects saved!":"Masomo yamehifadhiwa!",
  "Grading system saved!":"Mfumo wa madaraja umehifadhiwa!","School identity saved!":"Utambulisho wa shule umehifadhiwa!",
  "Logo updated!":"Nembo imebadilishwa!","Class added!":"Darasa limeongezwa!","Class removed":"Darasa limeondolewa",
  "Class renamed!":"Darasa limebadilishwa jina!","Stream added!":"Mkondo umeongezwa!","Stream removed":"Mkondo umeondolewa",
  "Teacher removed":"Mwalimu ameondolewa","Updated!":"Imebadilishwa!","Test added!":"Jaribio limeongezwa!","Deleted":"Imefutwa",
  "Published!":"Imechapishwa!","Announcement posted!":"Tangazo limetumwa!","Payout number saved":"Namba ya malipo imehifadhiwa",
  "Password updated successfully!":"Nywila imebadilishwa kikamilifu!","Failed":"Imeshindikana","Copied!":"Imenakiliwa!",
  "Enter a student name":"Weka jina la mwanafunzi","Select a class":"Chagua darasa","Enter parent phone number":"Weka namba ya simu ya mzazi",
  "Registration code saved!":"Namba ya usajili imehifadhiwa!","Request cancelled":"Ombi limeghairiwa",
  "Payment submitted for verification!":"Malipo yamewasilishwa kwa uhakiki!","Hide results from parents?":"Ficha matokeo kwa wazazi?",
  "Results hidden from parents.":"Matokeo yamefichwa kwa wazazi.","Select at least one":"Chagua angalau kimoja",
  "Network error — check your connection and try again":"Hitilafu ya mtandao — angalia muunganisho wako ujaribu tena",
  "Something went wrong on our side. Please try again.":"Hitilafu imetokea upande wetu. Tafadhali jaribu tena.",
  "Session expired, please log in again":"Muda wa kikao umekwisha, tafadhali ingia tena",
  "Authentication required":"Unahitaji kuingia kwanza","Access denied":"Huruhusiwi","Forbidden":"Hairuhusiwi",
  "Invalid registration code, username or password":"Namba ya usajili, jina la mtumiaji au nywila si sahihi",
  "School registration code not recognized":"Namba ya usajili wa shule haitambuliki",
  "Too many login attempts. Please try again in a few minutes.":"Majaribio mengi ya kuingia. Jaribu tena baada ya dakika chache.",
  "Please enter your school's registration code":"Tafadhali weka namba ya usajili wa shule yako",
  "Please enter username and password":"Tafadhali weka jina la mtumiaji na nywila",
  "Current password is incorrect":"Nywila ya sasa si sahihi","Password must be at least 6 characters":"Nywila lazima iwe na angalau herufi 6",
  "Passwords do not match.":"Nywila hazilingani.","Please fill in all fields.":"Tafadhali jaza sehemu zote.",
  "No active term":"Hakuna muhula unaoendelea","Score must be 0-100":"Alama lazima iwe kati ya 0 na 100",
  "Student not found":"Mwanafunzi hajapatikana","Not found":"Haijapatikana",
  "Students exist in this class":"Kuna wanafunzi katika darasa hili","Students exist in this stream":"Kuna wanafunzi katika mkondo huu",
  "Class already exists":"Darasa tayari lipo","Stream already exists":"Mkondo tayari upo","Already assigned":"Tayari amepangiwa",
  "Username already exists":"Jina la mtumiaji tayari lipo","Close current term first":"Funga muhula wa sasa kwanza",
  "Enter the parent's full phone number":"Weka namba kamili ya simu ya mzazi",
  "This feature needs an active subscription. Go to Config → Subscription.":"Huduma hii inahitaji usajili unaotumika. Nenda Mipangilio → Usajili.",
  // subjects (case-insensitive fallback handles lowercase)
  "Mathematics":"Hisabati","English":"Kiingereza","Biology":"Baiolojia","Chemistry":"Kemia","Physics":"Fizikia",
  "Geography":"Jiografia","History":"Historia","Civics":"Uraia","Literature":"Fasihi ya Kiingereza","Book keeping":"Uhasibu",
  "Commerce":"Biashara","Business studies":"Masomo ya Biashara","Bible knowledge":"Elimu ya Biblia",
  "Historia ya tanzania na maadili":"Historia ya Tanzania na Maadili"
};
const SW_PATTERNS = [
  [/^Form (\d+)$/i, n => `Kidato cha ${n}`],
  [/^Form (\d+) — Overall$/i, n => `Kidato cha ${n} — Wote`],
  [/^(\d+) selected$/, n => `${n} wamechaguliwa`],
  [/^(\d+) stream\(s\)$/, n => `Mikondo ${n}`],
  [/^(\d+) mark\(s\) saved!$/, n => `Alama ${n} zimehifadhiwa!`],
  [/^(\d+) students imported!$/, n => `Wanafunzi ${n} wameingizwa!`],
  [/^(\d+) student\(s\) deleted$/, n => `Wanafunzi ${n} wamefutwa`],
  [/^(\d+) new$/, n => `${n} mpya`],
  [/^(\d+) \/ (\d+) parents$/, (a, b) => `Wazazi ${a} / ${b}`],
  [/^(\d+) more qualifying parent\(s\) needed$/, n => `Wazazi ${n} zaidi wanahitajika`],
  [/^(.+) – (\d+) students$/, (l, n) => `${l} – wanafunzi ${n}`],
  [/^(.+) \(Grades\) – (\d+) students$/, (l, n) => `${l} (Madaraja) – wanafunzi ${n}`],
  [/^CAs: (\d+) \| CA Weight: (\d+)% \| Exam Weight: (\d+)% \| Status: OPEN$/,
    (a, b, c) => `CA: ${a} | Uzito wa CA: ${b}% | Uzito wa Mtihani: ${c}% | Hali: WAZI`],
  [/^Active term: (.+)$/, l => `Muhula unaoendelea: ${l}`],
  [/^(\d+) assignment\(s\) saved for (.+)!$/, (n, u) => `Majukumu ${n} yamehifadhiwa kwa ${u}!`],
  [/^Account created for (.+)!$/, u => `Akaunti imefunguliwa kwa ${u}!`],
  [/^(.+) opened!$/, l => `${l} umefunguliwa!`],
  [/^(.+) closed and locked\.$/, l => `${l} umefungwa na kufungiwa.`],
  [/^(.+) added!$/, l => `${l} imeongezwa!`],
];

const _swNodes = new WeakMap();
function _swLookup(raw){
  const key = raw.replace(/\s+/g, " ").trim();
  if(!key) return null;
  if(SW_TEXT[key]) return SW_TEXT[key];
  const cap = key.charAt(0).toUpperCase() + key.slice(1);
  if(SW_TEXT[cap]) return SW_TEXT[cap];
  for(const [re, fn] of SW_PATTERNS){ const m = key.match(re); if(m) return fn(...m.slice(1)); }
  return null;
}
function translateDom(root){
  root = root || document.body; if(!root) return;
  const sw = currentLang === "sw";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n){ const p = n.parentNode && n.parentNode.nodeName;
      return (p==="SCRIPT"||p==="STYLE"||p==="TEXTAREA") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; }
  });
  const nodes = []; while(walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(n=>{
    const rec = _swNodes.get(n), val = n.nodeValue;
    if(!sw){ if(rec && val === rec.out){ n.nodeValue = rec.orig; } _swNodes.delete(n); return; }
    if(rec && val === rec.out) return;
    const tr = _swLookup(val); if(!tr) return;
    const out = val.match(/^\s*/)[0] + tr + val.match(/\s*$/)[0];
    _swNodes.set(n, {orig: val, out}); n.nodeValue = out;
  });
  root.querySelectorAll("[placeholder],[title]").forEach(el=>{
    ["placeholder","title"].forEach(a=>{
      const cur = el.getAttribute(a); if(cur === null) return;
      const store = el.__sw || (el.__sw = {});
      if(!sw){ if(store[a] && cur === store[a].out) el.setAttribute(a, store[a].orig); delete store[a]; return; }
      if(store[a] && cur === store[a].out) return;
      const tr = _swLookup(cur); if(tr){ store[a] = {orig: cur, out: tr}; el.setAttribute(a, tr); }
    });
  });
}
let _swTimer = null;
new MutationObserver(()=>{
  if(currentLang !== "sw") return;
  clearTimeout(_swTimer); _swTimer = setTimeout(()=>translateDom(), 60);
}).observe(document.documentElement, {childList:true, subtree:true, characterData:true});