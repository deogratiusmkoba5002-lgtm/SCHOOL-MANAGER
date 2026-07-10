// ── STUDENTS ─────────────────────────────────────────────────
let allStudents=[];
async function loadStudents(){
  if(allStudents.length) renderStudents(allStudents);
  const fresh = await api("/students");
  allStudents = fresh;
  renderStudents(allStudents);
}
function renderStudents(list){
  const tb = document.getElementById("students-tbody");
  if(!list.length){
    tb.innerHTML=`<tr><td colspan="5"><div class="empty-state">${emptySVG()}<p>No students found</p></div></td></tr>`;
    return;
  }
  tb.innerHTML=list.map(s=>`
    <tr>
      <td style="color:var(--muted);font-size:.8rem">${s.id}</td>
      <td style="font-weight:600">${s.name}</td>
      <td><span class="badge badge-blue">${s.class_name}</span></td>
      <td>${s.stream_name ? `<span class="badge badge-grey">${s.stream_name}</span>` : '<span style="color:var(--muted);font-size:.8rem">—</span>'}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-outline" onclick="quickReport(${s.id})">${reportSVG()} Report</button>
          <button class="btn btn-sm btn-red btn-icon" onclick="deleteStudent(${s.id},'${s.name}')">
            <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      </td>
    </tr>`).join("");
}
document.getElementById("student-search").addEventListener("input",function(){
  const q=this.value.toLowerCase();
  renderStudents(allStudents.filter(s=>s.name.toLowerCase().includes(q)||s.class_name.includes(q)));
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
  renderStudents(allStudents);
  const r = await api(`/students/${id}`,"DELETE");
  if(r.ok){ toast("Student removed","success"); }
  else { toast(r.error||"Failed","error"); loadStudents(); }
}
function quickReport(sid){
  document.getElementById("report-student-id").value=sid;
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
  document.getElementById("import-step-preview").style.display="none";
  document.getElementById("import-file-input").value="";
  document.getElementById("import-preview-body").innerHTML="";
  document.getElementById("import-status").innerHTML="";
  document.getElementById("import-status").style.display="none";
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
    document.getElementById("import-step-upload").style.display="none";
    document.getElementById("import-step-preview").style.display="block";
    const tbody = document.getElementById("import-preview-body");
    tbody.innerHTML = data.preview.map(r => `
      <tr style="${r.errors.length?"background:#FFF3F3":""}">
        <td style="color:var(--muted);font-size:.78rem">${r.row}</td>
        <td style="font-weight:600">${r.name||"<span style=color:var(--red)>—</span>"}</td>
        <td>${r.class_name||"—"}</td>
        <td>${r.stream_name||"—"}</td>
        <td style="font-size:.82rem">${r.parent_phone||"—"}</td>
        <td>${r.errors.length
          ? "<span style=color:var(--red);font-size:.78rem>⚠ "+r.errors.join(", ")+"</span>"
          : "<span style=color:var(--green)>✓</span>"}</td>
      </tr>`).join("");
    const warn = data.preview.filter(r=>r.errors.length).length;
    document.getElementById("import-total-label").textContent =
      data.total_rows+" total rows — showing first 10. "+(warn ? warn+" have issues." : "All looking good!");
  } catch(e){ toast("Preview failed: "+e,"error"); }
  btn.textContent="Preview File"; btn.disabled=false;
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
  try {
    const res = await fetch("/api/students/import", {
      method:"POST", body:formData,
      headers: _schoolId ? {"X-School-ID": String(_schoolId)} : {}
    });
    const data = await res.json();
    if(!data.ok){ toast(data.error,"error"); btn.textContent="Confirm Import"; btn.disabled=false; return; }
    const statusEl = document.getElementById("import-status");
    statusEl.style.display="block";
    const bgColor = data.inserted > 0 ? "#E8F5E9" : "#FFF3E0";
    const titleColor = data.inserted > 0 ? "#2E7D32" : "#E65100";
    const titleText = data.inserted > 0 ? "Import Complete" : "Import Finished — Check Issues Below";
    statusEl.innerHTML = "<div style=background:"+bgColor+";border-radius:10px;padding:16px;margin-bottom:12px>"
      +"<div style=font-weight:700;font-size:1rem;color:"+titleColor+";margin-bottom:8px>"+titleText+"</div>"
      +"<div style=display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center>"
      +"<div style=background:white;border-radius:8px;padding:10px><div style=font-size:1.4rem;font-weight:800;color:var(--green)>"+data.inserted+"</div><div style=font-size:.75rem;color:var(--muted)>Inserted</div></div>"
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
        : "");
    toast(data.inserted+" students imported!","success");
    loadStudents();
  } catch(e){ toast("Import failed","error"); }
  btn.textContent="Confirm Import"; btn.disabled=false;
}
