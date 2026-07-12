// ── CONFIG PAGE ───────────────────────────────────────────────
// School identity, classes/streams, subjects and grading system —
// everything captured during registration, editable any time here.

let configClasses  = [];   // [{id,class_name,streams:[{id,stream_name}]}]
let configSubjects = [];   // [{id?,name,abbreviation}]
let configGrades   = [];   // [{id?,min_score,max_score,grade}]

async function loadConfigPage(){
  await loadConfig(); // fills school-name, term info, logo (sidebar/login), config.school_info

  const info = config.school_info || {};
  const set = (id,val)=>{ const el=document.getElementById(id); if(el) el.value = val || ""; };
  set("config-school-name",  config.school_name);
  set("config-school-motto", info.motto);
  set("config-school-phone", info.phone);
  set("config-school-email", info.email);
  set("config-admin-phone",  info.admin_phone);

  const preview = document.getElementById("config-logo-preview");
  const icon    = document.getElementById("config-logo-upload-icon");
  const text    = document.getElementById("config-logo-upload-text");
  if(info.logo_path){
    if(preview){ preview.src = "/"+info.logo_path; preview.style.display="block"; }
    if(icon) icon.style.display="none";
    if(text) text.textContent = "Click to replace logo";
  } else if(preview){
    preview.style.display="none";
    if(icon) icon.style.display="block";
    if(text) text.textContent = "Drag & drop or click to upload a new logo";
  }

  await Promise.all([configLoadClasses(), configLoadSubjects(), configLoadGrades()]);
}

// ── LOGO UPLOAD ─────────────────────────────────────────────
async function handleConfigLogoSelect(e){
  const file = e.target.files[0];
  if(!file) return;
  const formData = new FormData();
  formData.append("logo", file);
  try{
    const res = await fetch("/api/config/logo", {
      method:"POST", body:formData,
      headers: _schoolId ? {"X-School-ID": String(_schoolId)} : {}
    });
    const data = await res.json();
    if(!data.ok){ toast(data.error||"Upload failed","error"); return; }
    config.school_info = {...(config.school_info||{}), logo_path:data.logo_path};
    const preview = document.getElementById("config-logo-preview");
    const icon    = document.getElementById("config-logo-upload-icon");
    const text    = document.getElementById("config-logo-upload-text");
    if(preview){ preview.src = "/"+data.logo_path+"?t="+Date.now(); preview.style.display="block"; }
    if(icon) icon.style.display="none";
    if(text) text.textContent = "Click to replace logo";
    const sidebarLogoImg = document.getElementById("sidebar-school-logo");
    const sidebarDefaultIcon = document.getElementById("sidebar-default-icon");
    if(sidebarLogoImg){ sidebarLogoImg.src = "/"+data.logo_path+"?t="+Date.now(); sidebarLogoImg.style.display="block"; }
    if(sidebarDefaultIcon) sidebarDefaultIcon.style.display="none";
    toast("Logo updated!","success");
  } catch(err){ toast("Upload failed","error"); }
}

// ── CLASSES & STREAMS (each action saves immediately) ────────
async function configLoadClasses(){
  configClasses = await api("/classes");
  renderConfigClasses();
}
function renderConfigClasses(){
  const list = document.getElementById("config-classes-list");
  if(!list) return;
  list.innerHTML = configClasses.map((cls,i)=>`
    <div class="class-row">
      <div class="class-main">
        <div class="class-name-row">
          <input type="text" value="${escHtml(cls.class_name)}"
            onblur="configRenameClass(${cls.id},this.value,this)"
            onkeydown="if(event.key==='Enter')this.blur()">
          <span style="font-size:.75rem;color:var(--muted);flex-shrink:0;white-space:nowrap">Streams:</span>
        </div>
        <div class="streams-wrap">
          ${(cls.streams||[]).map(s=>`
            <span class="stream-tag">
              ${escHtml(s.stream_name)}
              <button onclick="configRemoveStream(${s.id},'${escHtml(s.stream_name).replace(/'/g,"\\'")}')" title="Remove stream">×</button>
            </span>`).join("")}
          <div class="add-stream-row">
            <input type="text" placeholder="Stream name" id="config-new-stream-${i}"
              onkeydown="if(event.key==='Enter'){configAddStream(${cls.id},${i});event.preventDefault()}">
            <button class="btn-add-stream" onclick="configAddStream(${cls.id},${i})">+ Add</button>
          </div>
        </div>
      </div>
      <button class="btn-del-class" onclick="configRemoveClass(${cls.id},'${escHtml(cls.class_name).replace(/'/g,"\\'")}')" title="Remove class">
        <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
      </button>
    </div>`).join("") || `<p style="color:var(--muted);font-size:.85rem">No classes yet — add one below.</p>`;
}
async function configRenameClass(id,newName,inputEl){
  const cls = configClasses.find(c=>c.id===id);
  const trimmed = (newName||"").trim();
  if(!trimmed || (cls && trimmed===cls.class_name)) { if(cls && inputEl) inputEl.value = cls.class_name; return; }
  const r = await api(`/classes/${id}`,"PATCH",{class_name:trimmed});
  if(r.ok){ toast("Class renamed!","success"); await configLoadClasses(); }
  else { toast(r.error||"Failed to rename class","error"); if(cls && inputEl) inputEl.value = cls.class_name; }
}
async function configAddClass(){
  const name = prompt("New class name (e.g. Form 1):");
  if(!name || !name.trim()) return;
  const r = await api("/classes","POST",{class_name:name.trim()});
  if(r.ok){ toast("Class added!","success"); await configLoadClasses(); }
  else toast(r.error||"Failed to add class","error");
}
async function configRemoveClass(id,name){
  if(!confirm(`Remove class "${name}"? This can't be undone.`)) return;
  const r = await api(`/classes/${id}`,"DELETE");
  if(r.ok){ toast("Class removed","success"); await configLoadClasses(); }
  else toast(r.error||"Failed to remove class","error");
}
async function configAddStream(classId,i){
  const inp = document.getElementById(`config-new-stream-${i}`);
  const val = inp.value.trim();
  if(!val){ toast("Enter a stream name","error"); inp.focus(); return; }
  const r = await api(`/classes/${classId}/streams`,"POST",{stream_name:val});
  if(r.ok){ toast("Stream added!","success"); await configLoadClasses(); }
  else toast(r.error||"Failed to add stream","error");
}
async function configRemoveStream(id,name){
  if(!confirm(`Remove stream "${name}"? This can't be undone.`)) return;
  const r = await api(`/streams/${id}`,"DELETE");
  if(r.ok){ toast("Stream removed","success"); await configLoadClasses(); }
  else toast(r.error||"Failed to remove stream","error");
}

// ── SUBJECTS (edited locally, one Save Subjects call replaces the list) ──
async function configLoadSubjects(){
  const rows = await api("/subjects");
  configSubjects = rows.map(s=>({name:s.name, abbreviation:s.abbreviation}));
  renderConfigSubjects();
}
function renderConfigSubjects(){
  const list = document.getElementById("config-subjects-list");
  if(!list) return;
  list.innerHTML = configSubjects.map((s,i)=>`
    <div class="subject-row">
      <input class="subj-name" type="text" placeholder="Subject name" value="${escHtml(s.name)}"
        oninput="configSubjects[${i}].name=this.value">
      <span class="abbr-label">Abbr:</span>
      <input class="subj-abbr" type="text" placeholder="e.g. MATH" maxlength="4" value="${escHtml(s.abbreviation)}"
        oninput="configSubjects[${i}].abbreviation=this.value.toUpperCase().slice(0,4);this.value=this.value.toUpperCase().slice(0,4)">
      <button class="btn-del-subj" onclick="configRemoveSubject(${i})" title="Remove subject">
        <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
      </button>
    </div>`).join("") || `<p style="color:var(--muted);font-size:.85rem">No subjects yet — add one below.</p>`;
}
function configAddSubject(){
  configSubjects.push({name:"",abbreviation:""});
  renderConfigSubjects();
  setTimeout(()=>{
    const inputs=document.querySelectorAll("#config-subjects-list .subj-name");
    if(inputs.length) inputs[inputs.length-1].focus();
  },50);
}
function configRemoveSubject(i){ configSubjects.splice(i,1); renderConfigSubjects(); }
async function configSaveSubjects(){
  const cleaned = configSubjects.filter(s=>s.name && s.name.trim());
  if(!cleaned.length){ toast("Add at least one subject","error"); return; }
  const btn = document.getElementById("config-subjects-save-btn");
  if(btn){ btn.disabled = true; }
  try {
    const r = await api("/subjects","POST",{subjects:cleaned});
    if(r.ok){ toast("Subjects saved!","success"); await configLoadSubjects(); }
    else toast(r.error||"Failed to save subjects","error");
  } finally {
    if(btn){ btn.disabled = false; }
  }
}

// ── GRADING SYSTEM (edited locally, one Save call replaces the list) ────
async function configLoadGrades(){
  configGrades = (await api("/grades")).map(g=>({min_score:g.min_score,max_score:g.max_score,grade:g.grade}));
  renderConfigGrades();
}
function renderConfigGrades(){
  const list = document.getElementById("config-grades-list");
  if(!list) return;
  list.innerHTML = configGrades.map((g,i)=>`
    <div class="grade-row">
      <div class="gr-range">
        <span class="gr-lbl">From</span>
        <input class="gr-min" type="number" min="0" max="100" value="${g.min_score}"
          oninput="configGrades[${i}].min_score=parseFloat(this.value)||0;renderConfigGradePreview()">
        <span class="gr-lbl">–</span>
        <input class="gr-max" type="number" min="0" max="100" value="${g.max_score}"
          oninput="configGrades[${i}].max_score=parseFloat(this.value)||0;renderConfigGradePreview()">
        <span class="gr-lbl">= Grade:</span>
        <input class="gr-name" type="text" maxlength="3" placeholder="A" value="${escHtml(g.grade)}"
          oninput="configGrades[${i}].grade=this.value.slice(0,3);renderConfigGradePreview()">
      </div>
      <button class="btn-del-grade" onclick="configRemoveGrade(${i})" title="Remove grade">
        <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
      </button>
    </div>`).join("") || `<p style="color:var(--muted);font-size:.85rem">No grade rules yet — add one below.</p>`;
  renderConfigGradePreview();
}
function configAddGrade(){
  configGrades.push({min_score:0,max_score:0,grade:""});
  renderConfigGrades();
  setTimeout(()=>{
    const inputs=document.querySelectorAll("#config-grades-list .gr-min");
    if(inputs.length) inputs[inputs.length-1].focus();
  },50);
}
function configRemoveGrade(i){ configGrades.splice(i,1); renderConfigGrades(); }
function renderConfigGradePreview(){
  const prev = document.getElementById("config-grade-preview");
  if(!prev) return;
  const sorted = [...configGrades].sort((a,b)=>b.min_score-a.min_score);
  prev.innerHTML = sorted.filter(g=>g.grade).map(g=>
    `<div class="grade-badge">${escHtml(g.grade)}: ${g.min_score}–${g.max_score}</div>`
  ).join("");
}
async function configSaveGrades(){
  const cleaned = configGrades.filter(g=>g.grade && g.grade.trim());
  if(!cleaned.length){ toast("Add at least one grade rule","error"); return; }
  const btn = document.getElementById("config-grades-save-btn");
  if(btn){ btn.disabled = true; }
  try {
    const r = await api("/grades","POST",{grades:cleaned});
    if(r.ok){ toast("Grading system saved!","success"); await configLoadGrades(); }
    else toast(r.error||"Failed to save grading system","error");
  } finally {
    if(btn){ btn.disabled = false; }
  }
}
