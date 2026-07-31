// ── STUDENTS ─────────────────────────────────────────────────
let allStudents=[];
let selectedStudentIds = new Set();
let studentFilter = { class_id:"", stream_id:"" };
let _importUnmatchedClasses = [];
let _importUnmatchedStreams = [];
let _importMapping = {classes:{}, streams:{}};
let _importPreviewData = null;


async function loadStudents(){
  const tb = document.getElementById("students-tbody");
  if(allStudents.length){
    renderStudents(getFilteredStudents());
  } else if(tb) {
    tb.innerHTML = `<tr><td colspan="6"><div class="spinner"></div><p style="text-align:center;color:var(--muted);font-size:.85rem;margin-top:-8px">Loading students…</p></td></tr>`;
  }
  const fresh = await api("/students");
  allStudents = scopeStudentsForUser(fresh);
  selectedStudentIds.clear();
  updateBulkBar();
  renderStudents(getFilteredStudents());
}

// Class teachers only see the students in the class (and, if set, the
// stream) they are class teacher of — everyone else (admin) sees all.
function scopeStudentsForUser(students){
  if(currentUser && currentUser.role==="teacher" && currentUser.is_class_teacher && currentUser.class_id){
    return students.filter(s=>{
      if(String(s.class_id) !== String(currentUser.class_id)) return false;
      if(currentUser.stream_id) return String(s.stream_id) === String(currentUser.stream_id);
      return true;
    });
  }
  return students;
}

function getFilteredStudents(){
  const q = (document.getElementById("student-search")||{}).value?.toLowerCase() || "";
  return allStudents.filter(s=>{
    if(studentFilter.class_id && String(s.class_id) !== String(studentFilter.class_id)) return false;
    if(studentFilter.stream_id && String(s.stream_id) !== String(studentFilter.stream_id)) return false;
    if(q && !(s.name.toLowerCase().includes(q) || s.class_name.toLowerCase().includes(q))) return false;
    return true;
  });
}

function renderStudents(list){
  const tb = document.getElementById("students-tbody");
  if(!list.length){
    tb.innerHTML=`<tr><td colspan="6"><div class="empty-state">${emptySVG()}<p>No students found</p></div></td></tr>`;
    return;
  }
  tb.innerHTML=list.map(s=>`
    <tr>
      <td><input type="checkbox" class="student-row-check" data-id="${s.id}" ${selectedStudentIds.has(s.id)?"checked":""} onchange="toggleStudentSelect(${s.id},this)"></td>
      <td style="color:var(--muted);font-size:.8rem" title="Internal ID: ${s.id}">${s.display_id || s.id}</td>
      <td style="font-weight:600">${s.name}</td>
      <td><span class="badge badge-blue">${s.class_name}</span></td>
      <td>${s.stream_name ? `<span class="badge badge-grey">${s.stream_name}</span>` : '<span style="color:var(--muted);font-size:.8rem">—</span>'}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-outline" onclick="quickReport(${s.id},'${(s.display_id||s.id)}')">${reportSVG()} Report</button>
          <button class="btn btn-sm btn-red btn-icon" onclick="deleteStudent(${s.id},'${s.name}')">
            <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      </td>
    </tr>`).join("");
  syncSelectAllCheckbox();
}

// ── Selection & bulk delete ─────────────────────────────────
function toggleStudentSelect(id, el){
  if(el.checked) selectedStudentIds.add(id); else selectedStudentIds.delete(id);
  updateBulkBar(); syncSelectAllCheckbox();
}
function toggleSelectAllStudents(el){
  const visible = getFilteredStudents();
  if(el.checked) visible.forEach(s=>selectedStudentIds.add(s.id));
  else visible.forEach(s=>selectedStudentIds.delete(s.id));
  renderStudents(visible);
  updateBulkBar();
}
function syncSelectAllCheckbox(){
  const master = document.getElementById("select-all-students");
  if(!master) return;
  const visible = getFilteredStudents();
  const allChecked = visible.length>0 && visible.every(s=>selectedStudentIds.has(s.id));
  master.checked = allChecked;
  master.indeterminate = !allChecked && visible.some(s=>selectedStudentIds.has(s.id));
}
function updateBulkBar(){
  const bar = document.getElementById("student-bulk-bar");
  const count = document.getElementById("student-bulk-count");
  if(!bar) return;
  if(selectedStudentIds.size>0){
    bar.style.display="flex";
    count.textContent = selectedStudentIds.size+" selected";
  } else {
    bar.style.display="none";
  }
}
function clearStudentSelection(){
  selectedStudentIds.clear();
  renderStudents(getFilteredStudents());
  updateBulkBar();
}
async function bulkDeleteStudents(btn){
  const ids = [...selectedStudentIds];
  if(!ids.length) return;
  if(!confirm(`Delete ${ids.length} selected student(s)? This also removes their marks and parent logins. This can't be undone.`)) return;
  if(btn){ btn.disabled = true; btn.textContent = "Deleting..."; }
  try {
    const r = await api("/students/bulk_delete","POST",{ids});
    if(r.ok){
      toast(`${r.deleted} student(s) deleted`,"success");
      allStudents = allStudents.filter(s=>!selectedStudentIds.has(s.id));
      selectedStudentIds.clear();
      updateBulkBar();
      renderStudents(getFilteredStudents());
    } else {
      toast(r.error||"Failed to delete students","error");
    }
  } catch(e) {
    toast("Failed to delete students","error");
  } finally {
    if(btn){ btn.disabled=false; btn.innerHTML = "Delete Selected"; }
  }
}

// ── Filter by class/stream ───────────────────────────────────
function toggleStudentFilter(){
  const dd = document.getElementById("student-filter-dropdown");
  const willOpen = dd.style.display === "none";
  dd.style.display = willOpen ? "block" : "none";
  if(willOpen){
    const classSel = document.getElementById("filter-class");
    if(classSel.options.length<=1){
      classSel.innerHTML = `<option value="">All Classes</option>` +
        (allClasses||[]).map(c=>`<option value="${c.id}">${c.class_name}</option>`).join("");
      classSel.value = studentFilter.class_id || "";
      onFilterClassChange();
      document.getElementById("filter-stream").value = studentFilter.stream_id || "";
    }
    document.addEventListener("click", closeFilterOnOutsideClick);
  } else {
    document.removeEventListener("click", closeFilterOnOutsideClick);
  }
}
function closeFilterOnOutsideClick(e){
  const dd = document.getElementById("student-filter-dropdown");
  const btn = document.getElementById("student-filter-btn");
  if(dd && !dd.contains(e.target) && e.target!==btn && !btn.contains(e.target)){
    dd.style.display="none";
    document.removeEventListener("click", closeFilterOnOutsideClick);
  }
}
function onFilterClassChange(){
  const classId = document.getElementById("filter-class").value;
  const streamSel = document.getElementById("filter-stream");
  const c = classId ? getClassById(parseInt(classId)) : null;
  if(c && c.streams.length){
    streamSel.innerHTML = `<option value="">All Streams</option>` +
      c.streams.map(s=>`<option value="${s.id}">${s.stream_name}</option>`).join("");
  } else {
    streamSel.innerHTML = `<option value="">All Streams</option>`;
  }
}
function applyStudentFilter(){
  studentFilter.class_id  = document.getElementById("filter-class").value;
  studentFilter.stream_id = document.getElementById("filter-stream").value;
  document.getElementById("student-filter-dropdown").style.display="none";
  const badge = document.getElementById("student-filter-badge");
  const activeCount = (studentFilter.class_id?1:0) + (studentFilter.stream_id?1:0);
  if(activeCount){ badge.style.display="inline"; badge.textContent=activeCount; }
  else badge.style.display="none";
  renderStudents(getFilteredStudents());
}
function clearStudentFilter(){
  studentFilter = { class_id:"", stream_id:"" };
  document.getElementById("filter-class").value="";
  document.getElementById("filter-stream").innerHTML = `<option value="">All Streams</option>`;
  document.getElementById("student-filter-badge").style.display="none";
  document.getElementById("student-filter-dropdown").style.display="none";
  renderStudents(getFilteredStudents());
}

let _studentSearchDebounce=null;
document.getElementById("student-search").addEventListener("input",function(){
  clearTimeout(_studentSearchDebounce);
  _studentSearchDebounce = setTimeout(()=>renderStudents(getFilteredStudents()), 180);
});
document.getElementById("btn-add-student").addEventListener("click",()=>{
  const sel = document.getElementById("new-student-class");
  sel.innerHTML = allClasses.map(c=>`<option value="${c.id}">${c.class_name}</option>`).join("");
  onStudentClassChange();
  openModal("modal-add-student");
});
function onStudentClassChange(){
  const class_id = parseInt(document.getElementById("new-student-class").value);
  const c = getClassById(class_id);
  const grp = document.getElementById("new-student-stream-group");
  const streamSel = document.getElementById("new-student-stream");
  if(c && c.streams.length > 0){
    streamSel.innerHTML = `<option value="">— No stream / Overall —</option>` +
      c.streams.map(s=>`<option value="${s.id}">${s.stream_name}</option>`).join("");
    grp.style.display="block";
  } else { streamSel.innerHTML=""; grp.style.display="none"; }
}
document.getElementById("confirm-add-student").addEventListener("click", async()=>{
  const name         = document.getElementById("new-student-name").value.trim();
  const class_id     = parseInt(document.getElementById("new-student-class").value);
  const stream_id    = document.getElementById("new-student-stream").value || null;
  const phone_number = document.getElementById("new-student-phone").value.trim();
  if(!name){toast("Enter a student name","error");return;}
  if(!class_id){toast("Select a class","error");return;}
  if(!phone_number){toast("Enter parent phone number","error");return;}
  const r = await api("/students","POST",{name,class_id,stream_id:stream_id?parseInt(stream_id):null,phone_number});
  if(r.ok){
    document.getElementById("new-student-name").value="";
    document.getElementById("new-student-phone").value="";
    closeModal("modal-add-student");
    openCredentialsModal(name, r.parent_username, r.temp_password);
    loadStudents();
  } else toast(r.error||"Failed","error");
});
function openCredentialsModal(studentName, username, tempPassword){
  document.getElementById("cred-student-name").textContent = studentName;
  document.getElementById("cred-username").textContent     = username;
  document.getElementById("cred-password").textContent     = tempPassword;
  openModal("modal-credentials");
}
async function deleteStudent(id,name){
  if(!confirm(`Delete "${name}"? This also removes all their marks.`))return;
  allStudents = allStudents.filter(s=>s.id!==id);
  selectedStudentIds.delete(id);
  updateBulkBar();
  renderStudents(getFilteredStudents());
  const r = await api(`/students/${id}`,"DELETE");
  if(r.ok){ toast("Student removed","success"); }
  else { toast(r.error||"Failed","error"); loadStudents(); }
}
function quickReport(sid, displayId){
  document.getElementById("report-student-id").value = displayId || sid;
  showPage("reports");
  viewReport(sid);
}

// ── CLASSES ──────────────────────────────────────────────────
async function loadClasses(){
  const classes = await api("/classes");
  allClasses = classes;
  const container = document.getElementById("classes-list");
  if(!classes.length){
    container.innerHTML=`<div class="empty-state">${emptySVG()}<p>No classes yet. Add one above.</p></div>`;
    return;
  }
  container.innerHTML = classes.map(c=>`
    <div class="section-card" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px">
        <div style="font-weight:700;font-size:1rem;color:var(--navy)">${c.class_name}</div>
        <div style="display:flex;gap:8px;align-items:center">
          <span style="font-size:.78rem;color:var(--muted)">${c.streams.length} stream(s)</span>
          <button class="btn btn-sm btn-outline" onclick="openAddStream(${c.id},'${c.class_name}')">+ Add Stream</button>
          <button class="btn btn-sm btn-red btn-icon" onclick="deleteClass(${c.id},'${c.class_name}')">
            <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      </div>
      ${c.streams.length>0 ? `<div style="display:flex;flex-wrap:wrap;gap:8px">
        ${c.streams.map(s=>`<div style="display:flex;align-items:center;gap:6px;background:var(--pale);border-radius:8px;padding:6px 12px">
          <span style="font-size:.85rem;font-weight:600;color:var(--blue)">${s.stream_name}</span>
          <button onclick="deleteStream(${s.id},'${c.class_name} ${s.stream_name}')"
            style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:14px;line-height:1;padding:0">✕</button>
        </div>`).join("")}
      </div>` : `<p style="color:var(--muted);font-size:.85rem">No streams — all students in one group</p>`}
    </div>`).join("");
}
document.getElementById("btn-add-class").addEventListener("click", async()=>{
  const name = document.getElementById("new-class-name").value.trim();
  if(!name){toast("Enter a class name","error");return;}
  const r = await api("/classes","POST",{class_name:name});
  if(r.ok){ toast(`${name} added!`,"success"); document.getElementById("new-class-name").value=""; await loadClasses(); }
  else toast(r.error||"Failed","error");
});
let addStreamTargetId=null, addStreamTargetName="";
function openAddStream(class_id, class_name){
  addStreamTargetId=class_id; addStreamTargetName=class_name;
  document.getElementById("add-stream-class-label").textContent=class_name;
  document.getElementById("new-stream-name").value="";
  openModal("modal-add-stream");
}
document.getElementById("confirm-add-stream").addEventListener("click", async()=>{
  const name = document.getElementById("new-stream-name").value.trim();
  if(!name){toast("Enter a stream name","error");return;}
  const r = await api(`/classes/${addStreamTargetId}/streams`,"POST",{stream_name:name});
  if(r.ok){ toast(`Stream ${name} added!`,"success"); closeModal("modal-add-stream"); await loadClasses(); }
  else toast(r.error||"Failed","error");
});
async function deleteClass(id, name){
  if(!confirm(`Delete class "${name}"? All its streams will also be deleted.`))return;
  const r = await api(`/classes/${id}`,"DELETE");
  if(r.ok){toast("Class deleted","success"); loadClasses();}
  else toast(r.error||"Failed","error");
}
async function deleteStream(id, name){
  if(!confirm(`Delete stream "${name}"?`))return;
  const r = await api(`/streams/${id}`,"DELETE");
  if(r.ok){toast("Stream deleted","success"); loadClasses();}
  else toast(r.error||"Failed","error");
}

// ── STUDENT IMPORT ────────────────────────────────────────────
function openImportModal(){
  document.getElementById("import-step-upload").style.display="block";
  document.getElementById("import-step-mapping").style.display="none";
  document.getElementById("import-step-preview").style.display="none";
  document.getElementById("import-file-input").value="";
  document.getElementById("import-preview-body").innerHTML="";
  document.getElementById("import-status").innerHTML="";
  document.getElementById("import-status").style.display="none";
  document.getElementById("import-back-btn").style.display="inline-flex";
  document.getElementById("import-confirm-btn").style.display="inline-flex";
  document.getElementById("import-done-btn").style.display="none";
  _importUnmatchedClasses = []; _importUnmatchedStreams = [];
  _importMapping = {classes:{}, streams:{}}; _importPreviewData = null;
  openModal("modal-import-students");
}

async function downloadTemplate(){
  const btn = document.getElementById("import-template-btn");
  btn.textContent="Downloading..."; btn.disabled=true;
  try {
    const res = await fetch("/api/students/import/template", {
      headers: _schoolId ? {"X-School-ID": String(_schoolId)} : {}
    });
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition")||"";
    const ext = cd.includes(".csv") ? "csv" : "xlsx";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href=url;
    a.download=`student_import_template.${ext}`; a.click();
    URL.revokeObjectURL(url);
  } catch(e){ toast("Download failed","error"); }
  btn.textContent="📥 Download Template"; btn.disabled=false;
}

async function previewImport(){
  const fileInput = document.getElementById("import-file-input");
  if(!fileInput.files.length){ toast("Select a file first","error"); return; }
  const btn = document.getElementById("import-preview-btn");
  btn.textContent="Reading..."; btn.disabled=true;
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  try {
    const res = await fetch("/api/students/import/preview", {
      method:"POST", body:formData,
      headers: _schoolId ? {"X-School-ID": String(_schoolId)} : {}
    });
    const data = await res.json();
    if(!data.ok){ toast(data.error,"error"); return; }
    _importUnmatchedClasses = data.unmatched_classes || [];
    _importUnmatchedStreams = data.unmatched_streams || [];
    _importMapping = {classes:{}, streams:{}};
    _importPreviewData = data;
    if(_importUnmatchedClasses.length || _importUnmatchedStreams.length) renderImportMappingStep();
    else renderImportPreviewTable(data);
  } catch(e){ toast("Preview failed: "+e,"error"); }
  finally { btn.textContent="Preview File →"; btn.disabled=false; }
}

function renderImportPreviewTable(data){
  document.getElementById("import-step-upload").style.display="none";
  document.getElementById("import-step-mapping").style.display="none";
  document.getElementById("import-step-preview").style.display="block";
  const tbody = document.getElementById("import-preview-body");
  tbody.innerHTML = data.preview.map(r => `
    <tr style="${r.issues.length?"background:#FFF3F3":""}">
      <td style="color:var(--muted);font-size:.78rem">${r.row}</td>
      <td style="font-weight:600">${r.name||"<span style=color:var(--red)>—</span>"}</td>
      <td>${r.class_name||"—"}</td>
      <td>${r.stream_name||"—"}</td>
      <td style="font-size:.82rem">${r.parent_phone||"—"}</td>
      <td>${r.issues.length
        ? "<span style=color:var(--orange);font-size:.78rem title='"+escHtml(r.issues.join('; '))+"'>⚠ "+r.issues.join(", ")+"</span>"
        : "<span style=color:var(--green)>✓</span>"}</td>
    </tr>`).join("");
  const warn = data.preview.filter(r=>r.issues.length).length;
  document.getElementById("import-total-label").textContent =
    data.total_rows+" total rows — showing first 10. "+(warn ? warn+" have notes (hover ⚠)." : "All looking good!");
}

function renderImportMappingStep(){
  document.getElementById("import-step-upload").style.display="none";
  document.getElementById("import-step-preview").style.display="none";
  const step = document.getElementById("import-step-mapping");
  step.style.display="block";
  const classOptions = (allClasses||[]).map(c=>`<option value="${escHtml(c.class_name)}">${escHtml(c.class_name)}</option>`).join("");
  const classHtml = _importUnmatchedClasses.map(raw=>`
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--pale)">
      <div style="flex:1;font-size:.85rem"><strong>${escHtml(raw)}</strong> <span style="color:var(--muted)">(from Excel)</span></div>
      <span style="color:var(--muted)">→</span>
      <select class="form-select" style="flex:1" onchange="_importMapping.classes['${escHtml(raw).replace(/'/g,"\\'")}']=this.value">
        <option value="">— Select matching class —</option>${classOptions}
      </select>
    </div>`).join("");
  const streamHtml = _importUnmatchedStreams.map(s=>{
    const cls = (allClasses||[]).find(c=>c.class_name.toLowerCase()===s.class_raw.toLowerCase()
                  || (_importMapping.classes[s.class_raw] && c.class_name===_importMapping.classes[s.class_raw]));
    const streamOptions = cls ? cls.streams.map(st=>`<option value="${escHtml(st.stream_name)}">${escHtml(st.stream_name)}</option>`).join("") : "";
    const key = `${s.class_raw}::${s.stream_raw}`;
    return `
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--pale)">
      <div style="flex:1;font-size:.85rem"><strong>${escHtml(s.stream_raw)}</strong> <span style="color:var(--muted)">(${escHtml(s.class_raw)}, from Excel)</span></div>
      <span style="color:var(--muted)">→</span>
      <select class="form-select" style="flex:1" onchange="_importMapping.streams['${escHtml(key).replace(/'/g,"\\'")}']=this.value">
        <option value="">— Select matching stream —</option>${streamOptions}
      </select>
    </div>`;
  }).join("");
  step.innerHTML = `
    <div style="background:#FFF8E1;border-left:3px solid #FFD600;border-radius:8px;padding:12px;font-size:.83rem;color:#5D4037;margin-bottom:16px">
      ⚠ Some class/stream names in your file don't exactly match your system's classes and streams. Match each one below — no need to edit the Excel file.
    </div>
    ${_importUnmatchedClasses.length ? `<div style="font-weight:700;color:var(--navy);margin-bottom:6px">Classes</div>${classHtml}` : ""}
    ${_importUnmatchedStreams.length ? `<div style="font-weight:700;color:var(--navy);margin:16px 0 6px">Streams</div>${streamHtml}` : ""}
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:18px">
      <button class="btn btn-outline" onclick="document.getElementById('import-step-mapping').style.display='none';document.getElementById('import-step-upload').style.display='block'">← Back</button>
      <button class="btn btn-blue" onclick="applyImportMappingAndContinue()">Continue →</button>
    </div>`;
}

function applyImportMappingAndContinue(){
  const missing = _importUnmatchedClasses.filter(raw=>!_importMapping.classes[raw]);
  if(missing.length){ toast("Match every class before continuing","error"); return; }
  renderImportPreviewTable(_importPreviewData);
}

async function downloadImportCredentials(url){
  try {
    const res = await fetch(url, { headers: _schoolId ? {"X-School-ID": String(_schoolId)} : {} });
    if(!res.ok){ toast("Download failed","error"); return; }
    const blob = await res.blob();
    const dlUrl = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href=dlUrl;
    a.download="parent_login_credentials.xlsx"; a.click();
    URL.revokeObjectURL(dlUrl);
  } catch(e){ toast("Download failed","error"); }
}

async function confirmImport(){
  const fileInput = document.getElementById("import-file-input");
  if(!fileInput.files.length){ toast("No file selected","error"); return; }
  const btn = document.getElementById("import-confirm-btn");
  btn.textContent="Importing..."; btn.disabled=true;
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("mapping", JSON.stringify(_importMapping));
  try {
    const res = await fetch("/api/students/import", {
      method:"POST", body:formData,
      headers: _schoolId ? {"X-School-ID": String(_schoolId)} : {}
    });
    const data = await res.json();
    if(!data.ok){ toast(data.error,"error"); return; }
    const statusEl = document.getElementById("import-status");
    statusEl.style.display="block";
    const bgColor = data.inserted > 0 ? "#E8F5E9" : "#FFF3E0";
    const titleColor = data.inserted > 0 ? "#2E7D32" : "#E65100";
    const titleText = data.inserted > 0 ? "Import Complete" : "Import Finished — Check Issues Below";
    statusEl.innerHTML = "<div style=background:"+bgColor+";border-radius:10px;padding:16px;margin-bottom:12px>"
      +"<div style=font-weight:700;font-size:1rem;color:"+titleColor+";margin-bottom:8px>"+titleText+"</div>"
      +"<div style=display:grid;grid-template-columns:repeat(4,1fr);gap:8px;text-align:center>"
      +"<div style=background:white;border-radius:8px;padding:10px><div style=font-size:1.4rem;font-weight:800;color:var(--green)>"+data.inserted+"</div><div style=font-size:.75rem;color:var(--muted)>Inserted</div></div>"
      +"<div style=background:white;border-radius:8px;padding:10px><div style=font-size:1.4rem;font-weight:800;color:var(--blue)>"+(data.duplicates||0)+"</div><div style=font-size:.75rem;color:var(--muted)>Duplicates</div></div>"
      +"<div style=background:white;border-radius:8px;padding:10px><div style=font-size:1.4rem;font-weight:800;color:var(--orange)>"+data.skipped+"</div><div style=font-size:.75rem;color:var(--muted)>Skipped</div></div>"
      +"<div style=background:white;border-radius:8px;padding:10px><div style=font-size:1.4rem;font-weight:800;color:var(--red)>"+data.errors+"</div><div style=font-size:.75rem;color:var(--muted)>Errors</div></div>"
      +"</div>"
      +(data.credentials_file
        ? "<button class=\"btn btn-sm btn-outline\" style=margin-top:12px;width:100% onclick=\"downloadImportCredentials('"+data.credentials_file+"')\">⬇ Download Login Credentials ("+data.credentials_count+")</button>"
        : "")
      +"</div>"
      +(data.skipped_details && data.skipped_details.length
        ? "<div style=font-weight:600;font-size:.82rem;color:var(--orange);margin-bottom:4px>Skipped ("+data.skipped+"):</div>"
          +data.skipped_details.map(s=>"<div style=font-size:.78rem;color:#555;padding:3px 0;border-bottom:1px solid var(--pale)>Row "+s.row+": "+s.reason+" — "+s.data+"</div>").join("")
        : "")
      +(data.error_details && data.error_details.length
        ? "<div style=font-weight:600;font-size:.82rem;color:var(--red);margin:8px 0 4px>Errors (showing first 20 of "+data.errors+"):</div>"
          +data.error_details.map(e=>"<div style=font-size:.78rem;color:#c00;padding:3px 0;border-bottom:1px solid #FEE>Row "+e.row+": "+e.error+" — "+e.data+"</div>").join("")
        : "")
      +(data.flagged_details && data.flagged_details.length
        ? "<div style=font-weight:600;font-size:.82rem;color:var(--orange);margin:8px 0 4px>⚠ Imported with notes ("+data.flagged_details.length+"):</div>"
          +data.flagged_details.map(f=>"<div style=font-size:.78rem;color:#E65100;padding:3px 0;border-bottom:1px solid #FFF3E0>Row "+f.row+" — "+f.name+": "+f.reason+"</div>").join("")
        : "");
    toast(data.inserted+" students imported!","success");
    loadStudents();
    // Lock out further clicks on this file — prevents the classic "clicked twice, got
    // duplicates" problem. User must explicitly re-open the modal to import again.
    document.getElementById("import-back-btn").style.display="none";
    btn.style.display="none";
    document.getElementById("import-done-btn").style.display="inline-flex";
    document.getElementById("import-file-input").value="";
  } catch(e){ toast("Import failed","error"); }
  finally { btn.textContent="Confirm Import"; btn.disabled=false; }
}
