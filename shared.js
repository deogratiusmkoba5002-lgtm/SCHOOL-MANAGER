"use strict";
const API = "/api";
let currentUser = null;
let config = {ca_count:2, allowed_subjects:[], classes:[]};
let allClasses = [];
let allTerms = [];
let teacherAssignments = [];

// ── CLASS HELPERS ────────────────────────────────────────────
function getClassById(id){ return allClasses.find(c=>c.id==id)||null; }
function getStreamById(class_id, stream_id){
  const c = getClassById(class_id);
  if(!c||!stream_id) return null;
  return c.streams.find(s=>s.id==stream_id)||null;
}
function classLabel(class_id, stream_id){
  const c = getClassById(class_id);
  if(!c) return "—";
  const s = stream_id ? getStreamById(class_id, stream_id) : null;
  return s ? `${c.class_name} ${s.stream_name}` : c.class_name;
}
function populateClassSelect(sel, includeStreams=false, includeOverall=false){
  sel.innerHTML="";
  allClasses.forEach(c=>{
    if(includeStreams && c.streams.length>0){
      const grp=document.createElement("optgroup");
      grp.label=c.class_name;
      if(includeOverall){
        const o=document.createElement("option");
        o.value=`${c.id}:0`; o.textContent=`${c.class_name} — Overall`;
        grp.appendChild(o);
      }
      c.streams.forEach(s=>{
        const o=document.createElement("option");
        o.value=`${c.id}:${s.id}`; o.textContent=`${c.class_name} ${s.stream_name}`;
        grp.appendChild(o);
      });
      sel.appendChild(grp);
    } else {
      const o=document.createElement("option");
      o.value=`${c.id}:0`; o.textContent=c.class_name;
      sel.appendChild(o);
    }
  });
}
function parseClassStream(val){
  const [cid,sid]=val.split(":").map(Number);
  return {class_id:cid, stream_id:sid||null};
}

// ── UTILS ────────────────────────────────────────────────────
function toast(msg, type="info"){
  const el = document.createElement("div");
  const icons = {
    success:`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>`,
    error:  `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
    info:   `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`,
  };
  el.className = `toast ${type}`;
  el.innerHTML = `${icons[type]||icons.info}<span>${msg}</span>`;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(()=>el.remove(),3800);
}
function closeModal(id){document.getElementById(id).style.display="none"}
function openModal(id){document.getElementById(id).style.display="flex"}
let _schoolId = null;

async function api(path, method="GET", body=null){
  const headers = {"Content-Type":"application/json"};
  if(_schoolId) headers["X-School-ID"] = String(_schoolId);
  const opts = {method, headers};
  if(body) opts.body = JSON.stringify(body);
  const r = await fetch(API+path, opts);
  return r.json();
}
function gradeClass(g){return `grade-${g}`}
function escHtml(s){ return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function cap(s){return s?s.charAt(0).toUpperCase()+s.slice(1):s}
function populateSelect(sel, items, valFn, labelFn){
  sel.innerHTML="";
  items.forEach(i=>{
    const o=document.createElement("option");
    o.value=valFn(i); o.textContent=labelFn(i);
    sel.appendChild(o);
  });
}

// ── SVG HELPERS ──────────────────────────────────────────────
function homeSVG()    {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>`}
function peopleSVG()  {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>`}
function teacherSVG() {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z"/></svg>`}
function editSVG()    {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`}
function reportSVG()  {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>`}
function tableSVG()   {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 10.02h5V21h-5zM17 21h3c1.1 0 2-.9 2-2v-9h-5v11zm3-18H5c-1.1 0-2 .9-2 2v3h19V5c0-1.1-.9-2-2-2zM3 19c0 1.1.9 2 2 2h3V10H3v9z"/></svg>`}
function starSVG()    {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/></svg>`}
function chatSVG()    {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>`}
function gearSVG()    {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>`}
function schoolSVG()  {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z"/></svg>`}
function calSVG()     {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 12h-5v5h5v-5zM16 1v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-1V1h-2zm3 18H5V8h14v11z"/></svg>`}
function historySVG() {return`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>`}
function emptySVG()   {return`<svg viewBox="0 0 24 24" fill="currentColor" style="width:48px;height:48px;color:var(--border)"><path d="M20 6h-2.18c.07-.44.18-.88.18-1.35C18 2.53 15.88.5 13.5.5c-1.35 0-2.56.6-3.4 1.53L9 3.15 7.9 2.03C7.06 1.1 5.85.5 4.5.5 2.12.5 0 2.53 0 4.65 0 5.12.11 5.56.18 6H0l2 14h20l2-14h-4zm-6.5-4c1.13 0 2 .87 2 1.65 0 .79-.87 1.6-2 2.35-1.13-.75-2-1.56-2-2.35C11.5 2.87 12.37 2 13.5 2zM4.5 2c1.13 0 2 .87 2 1.65 0 .79-.87 1.6-2 2.35C3.37 5.25 2.5 4.44 2.5 3.65 2.5 2.87 3.37 2 4.5 2zM4 18l-1.5-10h15L16 18H4z"/></svg>`}

// ── DYNAMIC GRADES ───────────────────────────────────────────
let GRADE_RULES = [
  {min_score:80,grade:"A"},{min_score:70,grade:"B"},
  {min_score:60,grade:"C"},{min_score:50,grade:"D"},{min_score:0,grade:"F"}
];
function get_grade_js(score){
  if(score===null||score===undefined||score==="") return "-";
  const n = parseFloat(score);
  const sorted = [...GRADE_RULES].sort((a,b)=>b.min_score-a.min_score);
  for(const r of sorted){ if(n >= r.min_score) return r.grade; }
  return sorted[sorted.length-1]?.grade || "F";
}

// ── LOGIN ────────────────────────────────────────────────────
document.getElementById("login-btn").addEventListener("click", doLogin);
document.getElementById("login-pass").addEventListener("keydown", e=>e.key==="Enter"&&doLogin());

(async function preloadSchoolBranding(){
  try{
    const urlSid = new URLSearchParams(window.location.search).get("school_id") || "";
    const res = await fetch("/api/school/info" + (urlSid ? "?school_id="+urlSid : "?school_id=1"));
    if(!res.ok) return;
    const info = await res.json();
    if(info.school_name){
      const el = document.getElementById("login-school-name");
      if(el) el.textContent = info.school_name;
      const sn = document.getElementById("sidebar-school-name");
      if(sn) sn.textContent = info.school_name;
    }
    if(info.motto){
      const el = document.getElementById("login-school-sub");
      if(el) el.textContent = info.motto;
    }
    if(info.logo_path){
      const img1 = document.getElementById("login-school-logo");
      const ico1 = document.getElementById("login-default-icon");
      if(img1){ img1.src="/"+info.logo_path; img1.style.display="block"; }
      if(ico1) ico1.style.display="none";
      const img2 = document.getElementById("sidebar-school-logo");
      const ico2 = document.getElementById("sidebar-default-icon");
      if(img2){ img2.src="/"+info.logo_path; img2.style.display="block"; }
      if(ico2) ico2.style.display="none";
    }
    if(info.registration_complete !== "1"){
      const errEl = document.getElementById("login-error");
      if(errEl){ errEl.textContent="⚠ School setup incomplete. Log in as admin to complete registration."; errEl.style.display="block"; }
    }
  } catch(e){}
})();

async function doLogin(){
  const u = document.getElementById("login-user").value.trim();
  const p = document.getElementById("login-pass").value;
  const errEl = document.getElementById("login-error");
  errEl.style.display="none";
  if(!u||!p){errEl.textContent="Please enter username and password";errEl.style.display="block";return;}
  try{
    const res = await api("/login","POST",{username:u,password:p});
    if(res.ok){
      if(res.user.role==="admin" && !res.registration_complete){
        window.location.href="/register"; return;
      }
      currentUser = res.user;
      _schoolId = res.user.school_id;
      await loadConfig();
      bootApp();
    } else {
      errEl.textContent = res.error||"Invalid credentials";
      errEl.style.display="block";
    }
  }catch(e){
    errEl.textContent="Cannot connect to server.";
    errEl.style.display="block";
  }
}

// ── CONFIG ───────────────────────────────────────────────────
async function loadConfig(){
  const c = await api("/config");
  config = {...config, ...c};
  if(c.allowed_subjects && c.allowed_subjects.length) config.allowed_subjects = c.allowed_subjects;
  if(c.grade_rules && c.grade_rules.length) GRADE_RULES = c.grade_rules;
  const logoPath = c.school_info && c.school_info.logo_path;
  if(logoPath){
    const loginLogoImg = document.getElementById("login-school-logo");
    const loginDefaultIcon = document.getElementById("login-default-icon");
    if(loginLogoImg){ loginLogoImg.src="/"+logoPath; loginLogoImg.style.display="block"; }
    if(loginDefaultIcon) loginDefaultIcon.style.display="none";
    const sidebarLogoImg = document.getElementById("sidebar-school-logo");
    const sidebarDefaultIcon = document.getElementById("sidebar-default-icon");
    if(sidebarLogoImg){ sidebarLogoImg.src="/"+logoPath; sidebarLogoImg.style.display="block"; }
    if(sidebarDefaultIcon) sidebarDefaultIcon.style.display="none";
  }
  if(c.school_name){
    const loginName = document.getElementById("login-school-name");
    if(loginName) loginName.textContent = c.school_name;
    const sidebarName = document.getElementById("sidebar-school-name");
    if(sidebarName) sidebarName.textContent = c.school_name;
    const motto = c.school_info && c.school_info.motto;
    const loginSub = document.getElementById("login-school-sub");
    if(loginSub && motto) loginSub.textContent = motto;
  }
  // Config page fields
  const nameInput = document.getElementById("config-school-name");
  if(nameInput && c.school_name) nameInput.value = c.school_name;
  const infoEl = document.getElementById("config-term-info");
  if(infoEl){
    if(c.active_term){
      infoEl.innerHTML=`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-top:8px">
        <div style="background:var(--pale);border-radius:8px;padding:12px"><div style="font-size:.7rem;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:4px">Term</div><div style="font-weight:600">${c.active_term.label}</div></div>
        <div style="background:var(--pale);border-radius:8px;padding:12px"><div style="font-size:.7rem;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:4px">CAs</div><div style="font-weight:600">${c.active_term.ca_count}</div></div>
        <div style="background:var(--pale);border-radius:8px;padding:12px"><div style="font-size:.7rem;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:4px">CA Weight</div><div style="font-weight:600">${c.active_term.ca_weight}%</div></div>
        <div style="background:var(--pale);border-radius:8px;padding:12px"><div style="font-size:.7rem;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:4px">Exam Weight</div><div style="font-weight:600">${c.active_term.exam_weight}%</div></div>
      </div>`;
    } else {
      infoEl.innerHTML=`<p style="color:var(--orange);margin-top:8px">⚠ No active term. Go to <strong>Terms</strong> to open one.</p>`;
    }
  }
}

// ── BOOT APP ─────────────────────────────────────────────────
async function bootApp(){
  document.getElementById("login-page").style.display="none";
  document.getElementById("app").style.display="flex";
  document.getElementById("sidebar-username").textContent=currentUser.username;
  let roleLabel;
  if(currentUser.role==="parent") roleLabel="[Parent Portal]";
  else if(currentUser.is_class_teacher) roleLabel="[Class Teacher]";
  else roleLabel="["+currentUser.role+"]";
  document.getElementById("sidebar-role-badge").textContent=roleLabel;
  buildNav();
  if(currentUser.role==="parent"){
    await refreshTermBanner();
    showPage("parent-dashboard");
    loadParentDashboard();
    if(currentUser.must_change_password) openModal("modal-change-password");
    return;
  }
  const classData = await api("/classes");
  allClasses = classData;
  await refreshTermBanner();
  const defaultPage = currentUser.role==="admin" ? "dashboard" : "marks";
  showPage(defaultPage);
  loadDashboard();
  if(currentUser.must_change_password) openModal("modal-change-password");
}

// ── NAV ──────────────────────────────────────────────────────
const NAV_ADMIN = [
  {id:"dashboard", icon:homeSVG(),    label:"Dashboard"},
  {id:"students",  icon:peopleSVG(),  label:"Students"},
  {id:"classes",   icon:schoolSVG(),  label:"Classes"},
  {id:"teachers",  icon:teacherSVG(), label:"Teachers"},
  {id:"terms",     icon:calSVG(),     label:"Terms"},
  {id:"reports",   icon:reportSVG(),  label:"Report Cards"},
  {id:"sheets",    icon:tableSVG(),   label:"Score Sheets"},
  {id:"rankings",  icon:starSVG(),    label:"Rankings"},
  {id:"past",      icon:historySVG(), label:"Past Terms"},
  {id:"parents",   icon:peopleSVG(),  label:"Parents"},
  {id:"config",    icon:gearSVG(),    label:"Config"},
];
const NAV_PARENT = [
  {id:"parent-dashboard",    icon:homeSVG(),   label:"Dashboard"},
  {id:"parent-reports",      icon:reportSVG(), label:"View Reports"},
  {id:"parent-analytics",    icon:starSVG(),   label:"Academic Analytics"},
  {id:"parent-announcements",icon:chatSVG(),   label:"Announcements"},
];
function buildTeacherNav(user){
  const items = [
    {id:"marks",   icon:editSVG(),   label:"Enter Marks"},
    {id:"rankings",icon:starSVG(),   label:"Rankings"},
  ];
  if(user.is_class_teacher){
    items.push({id:"reports", icon:reportSVG(), label:"Report Cards"});
    items.push({id:"sheets",  icon:tableSVG(),  label:"Score Sheets"});
  }
  items.push({id:"past", icon:historySVG(), label:"Past Terms"});
  return items;
}
function buildNav(){
  const items = currentUser.role==="admin" ? NAV_ADMIN
    : currentUser.role==="parent" ? NAV_PARENT
    : buildTeacherNav(currentUser);
  const nav = document.getElementById("sidebar-nav");
  nav.innerHTML="";
  items.forEach(item=>{
    const el=document.createElement("div");
    el.className="nav-item"; el.dataset.page=item.id;
    el.innerHTML=`${item.icon}<span>${item.label}</span>`;
    el.addEventListener("click",()=>showPage(item.id));
    nav.appendChild(el);
  });
}

// ── PAGE ROUTING ─────────────────────────────────────────────
let pageHistory = [];
let currentPageId = null;
function goBack(){
  if(pageHistory.length > 0){ const prev = pageHistory.pop(); _showPage(prev); }
}
function showPage(id){
  if(currentPageId && currentPageId !== id){
    pageHistory.push(currentPageId);
    if(pageHistory.length > 20) pageHistory.shift();
  }
  _showPage(id);
}
function _showPage(id){
  currentPageId = id;
  document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n=>n.classList.remove("active"));
  const pg = document.getElementById("page-"+id);
  if(pg) pg.classList.add("active");
  const ni = document.querySelector(`.nav-item[data-page="${id}"]`);
  if(ni) ni.classList.add("active");
  const canGoBack = pageHistory.length > 0;
  document.querySelectorAll(".page-back-btn").forEach(btn=>{
    btn.style.display = canGoBack ? "inline-flex" : "none";
  });
  if(id==="parents")             loadParentsPage();
  if(id==="parent-dashboard")    loadParentDashboard();
  if(id==="parent-reports")      loadParentReports();
  if(id==="parent-analytics"){
    if(analyticsData && analyticsData.length){ renderAnalytics(); renderAnalyticsSummary(); renderAnalyticsInsights(); }
    loadAnalyticsData();
  }
  if(id==="parent-announcements") loadParentAnnouncements();
  if(id==="students")  loadStudents();
  if(id==="classes")   loadClasses();
  if(id==="teachers")  loadTeachers();
  if(id==="marks")     { setupMarks(); populateMarksSelects(); }
  if(id==="sheets")    setupSheets();
  if(id==="rankings")  setupRankings();
  if(id==="terms")     loadTerms();
  if(id==="past")      setupPastTerms();
  if(id==="config")    loadConfigPage();
}

// ── LOGOUT ───────────────────────────────────────────────────
document.getElementById("logout-btn").addEventListener("click",()=>{
  currentUser = null;
  _schoolId   = null;
  analyticsData = null;
  parentPublishedTerms = [];
  analyticsTab = "avg";
  analyticsSubject = null;
  allStudents = [];
  allClasses  = [];
  allTerms    = [];
  teacherAssignments = [];
  ["parent-rc-output","parent-res-output","parent-announcements-list"].forEach(id=>{
    const el = document.getElementById(id);
    if(el) el.innerHTML="";
  });
  pageHistory = [];
  currentPageId = null;
  document.getElementById("app").style.display="none";
  document.getElementById("login-page").style.display="flex";
  document.getElementById("login-user").value="";
  document.getElementById("login-pass").value="";
  document.getElementById("login-error").style.display="none";
});

// ── MOBILE SIDEBAR ───────────────────────────────────────────
function toggleSidebar(){
  const sidebar = document.getElementById("sidebar");
  sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
}
function openSidebar(){
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("overlay").classList.add("show");
}
function closeSidebar(){
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("overlay").classList.remove("show");
}
document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("sidebar-nav").addEventListener("click",()=>{ if(window.innerWidth<=768) closeSidebar(); });
  document.getElementById("logout-btn").addEventListener("click",()=>{ if(window.innerWidth<=768) closeSidebar(); });
  const btn = document.getElementById("config-school-save-btn");
  if(btn){
    btn.addEventListener("click", async()=>{
      const name = document.getElementById("config-school-name").value.trim();
      if(!name){toast("Enter a school name","error");return;}
      const payload = {
        school_name: name,
        motto:       (document.getElementById("config-school-motto")||{}).value || "",
        phone:       (document.getElementById("config-school-phone")||{}).value || "",
        email:       (document.getElementById("config-school-email")||{}).value || "",
        admin_phone: (document.getElementById("config-admin-phone")||{}).value || "",
      };
      btn.disabled = true;
      const r = await api("/config/school_info","POST",payload);
      btn.disabled = false;
      if(r.ok){
        config.school_name = name;
        config.school_info = {...(config.school_info||{}), ...payload};
        toast("School identity saved!","success");
        if(typeof renderDashSchoolHeader==="function") renderDashSchoolHeader();
        const loginName = document.getElementById("login-school-name");
        if(loginName) loginName.textContent = name;
        const sidebarName = document.getElementById("sidebar-school-name");
        if(sidebarName) sidebarName.textContent = name;
        const loginSub = document.getElementById("login-school-sub");
        if(loginSub && payload.motto) loginSub.textContent = payload.motto;
      }
      else toast(r.error||"Failed","error");
    });
  }
  // Password change modal backdrop block
  document.getElementById("modal-change-password").addEventListener("click", function(e){
    if(e.target === this && currentUser && currentUser.must_change_password) e.stopPropagation();
  });
});

// ── FORCE PASSWORD CHANGE ────────────────────────────────────
document.getElementById("cp-save-btn").addEventListener("click", async()=>{
  const oldPw  = document.getElementById("cp-old").value;
  const newPw  = document.getElementById("cp-new").value;
  const confirm= document.getElementById("cp-confirm").value;
  const errEl  = document.getElementById("cp-error");
  errEl.style.display="none";
  if(!oldPw||!newPw||!confirm){ errEl.textContent="Please fill in all fields."; errEl.style.display="block"; return; }
  if(newPw.length < 6){ errEl.textContent="New password must be at least 6 characters."; errEl.style.display="block"; return; }
  if(newPw !== confirm){ errEl.textContent="Passwords do not match."; errEl.style.display="block"; return; }
  if(newPw === oldPw){ errEl.textContent="New password must be different from current."; errEl.style.display="block"; return; }
  const btn = document.getElementById("cp-save-btn");
  btn.textContent="Saving..."; btn.disabled=true;
  const r = await api("/change_password","POST",{username:currentUser.username,school_id:currentUser.school_id,old_password:oldPw,new_password:newPw});
  btn.textContent="Set Password & Continue"; btn.disabled=false;
  if(r.ok){ currentUser.must_change_password = false; closeModal("modal-change-password"); toast("Password updated successfully!","success"); }
  else { errEl.textContent = r.error || "Failed. Try again."; errEl.style.display="block"; }
});

// ── TERM BANNER ──────────────────────────────────────────────
async function refreshTermBanner(){
  const r = await api("/terms/active");
  const banner = document.getElementById("term-banner");
  const bar    = document.getElementById("term-banner-bar");
  const label  = document.getElementById("term-badge-label");
  const detail = document.getElementById("term-banner-detail");
  banner.style.display="flex";
  if(r.ok && r.term){
    config.ca_count    = r.term.ca_count;
    config.active_term = r.term;
    bar.className="term-banner";
    label.textContent = "📅 " + r.term.label;
    detail.textContent= `CAs: ${r.term.ca_count}  |  CA Weight: ${r.term.ca_weight}%  |  Exam Weight: ${r.term.exam_weight}%  |  Status: OPEN`;
  } else {
    config.active_term = null;
    bar.className="term-banner none";
    label.textContent="⚠ No active term";
    detail.textContent="Admin must open a term before marks can be entered";
  }
}
