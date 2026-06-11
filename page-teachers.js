// ── TEACHERS ─────────────────────────────────────────────────
async function loadTeachers(){
  const teachers = await api("/teachers");
  const tb = document.getElementById("teachers-tbody");
  if(!teachers.length){
    tb.innerHTML=`<tr><td colspan="4"><div class="empty-state">${emptySVG()}<p>No teachers yet. Create one above.</p></div></td></tr>`;
  } else {
    tb.innerHTML=teachers.map(t=>`
      <tr>
        <td>
          <span style="font-weight:600">${t.username}</span>
          ${t.must_change_password
            ? `<span class="badge badge-orange" style="margin-left:6px;font-size:.68rem">⏳ Pending</span>`
            : `<span class="badge badge-green" style="margin-left:6px;font-size:.68rem">✓ Active</span>`}
        </td>
        <td>${t.is_class_teacher
          ? `<span class="badge badge-green">${t.class_name}${t.stream_name?" "+t.stream_name:""}</span>`
          : `<span class="badge badge-grey">No</span>`}</td>
        <td style="font-size:.78rem;color:var(--muted)">${
          t.assignments.length
            ? t.assignments.map(a=>`${cap(a.subject)} (${a.class_name}${a.stream_name?" "+a.stream_name:" – All"})`).join(", ")
            : "—"
        }</td>
        <td>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn btn-sm btn-outline" onclick="openSetClassTeacher('${t.username}',${t.class_id||"null"},${t.stream_id||"null"},${t.is_class_teacher})">
              ${t.is_class_teacher?"Edit CT":"Set as CT"}
            </button>
            <button class="btn btn-sm btn-red btn-icon" onclick="deleteTeacher('${t.username}')">
              <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
            </button>
          </div>
        </td>
      </tr>`).join("");
  }
  const userSel = document.getElementById("assign-teacher-user");
  userSel.innerHTML=teachers.map(t=>`<option value="${t.username}">${t.username}</option>`).join("");
  populateSelect(document.getElementById("assign-teacher-subject"), config.allowed_subjects, s=>s, s=>cap(s));
  populateClassSelect(document.getElementById("assign-teacher-class"), true, true);
}
async function deleteTeacher(username){
  if(!confirm(`Delete teacher "${username}"? All their assignments will be removed.`))return;
  const r=await api(`/teachers/${username}`,"DELETE");
  if(r.ok){toast("Teacher removed","success");loadTeachers();}
  else toast(r.error||"Failed","error");
}
function openSetClassTeacher(username, class_id, stream_id, isCT){
  document.getElementById("ct-username").value=username;
  document.getElementById("ct-is-ct").checked=isCT;
  const sel=document.getElementById("ct-class");
  populateClassSelect(sel, true, true);
  if(class_id){ const val=`${class_id}:${stream_id||0}`; if([...sel.options].some(o=>o.value===val)) sel.value=val; }
  toggleCTClass();
  openModal("modal-set-ct");
}
function toggleCTClass(){
  const isCT=document.getElementById("ct-is-ct").checked;
  document.getElementById("ct-class-group").style.display=isCT?"block":"none";
}
document.getElementById("btn-assign-teacher").addEventListener("click",()=>openModal("modal-assign-teacher"));
document.getElementById("confirm-assign-teacher").addEventListener("click", async()=>{
  const u  = document.getElementById("assign-teacher-user").value;
  const s  = document.getElementById("assign-teacher-subject").value;
  const {class_id, stream_id} = parseClassStream(document.getElementById("assign-teacher-class").value);
  const r  = await api("/assign_teacher","POST",{username:u,subject:s,class_id,stream_id});
  if(r.ok){toast("Teacher assigned!","success");closeModal("modal-assign-teacher");loadTeachers();}
  else toast(r.error||"Failed","error");
});
document.getElementById("btn-create-teacher").addEventListener("click", async()=>{
  const username=document.getElementById("new-teacher-user").value.trim();
  const password=document.getElementById("new-teacher-pass").value.trim();
  if(!username||!password){toast("Fill in both fields","error");return;}
  const r=await api("/teachers","POST",{username,password});
  if(r.ok){
    toast(`Account created for ${username}!`,"success");
    document.getElementById("new-teacher-user").value="";
    document.getElementById("new-teacher-pass").value="";
    loadTeachers();
  } else toast(r.error||"Failed","error");
});
document.getElementById("confirm-set-ct").addEventListener("click", async()=>{
  const username=document.getElementById("ct-username").value;
  const is_class_teacher=document.getElementById("ct-is-ct").checked;
  const {class_id, stream_id} = parseClassStream(document.getElementById("ct-class").value);
  const r=await api(`/teachers/${username}/class_teacher`,"POST",{is_class_teacher,class_id,stream_id});
  if(r.ok){toast("Updated!","success");closeModal("modal-set-ct");loadTeachers();}
  else toast(r.error||"Failed","error");
});
async function unassign(u,s,class_id,stream_id){
  if(!confirm(`Remove this assignment?`))return;
  const r=await api("/unassign_teacher","POST",{username:u,subject:s,class_id,stream_id});
  if(r.ok){toast("Removed","success");loadTeachers();}
  else toast(r.error||"Failed","error");
}

// ── MARKS ────────────────────────────────────────────────────
function is_teacher_allowed_local(subject, class_id, stream_id=null){
  if(currentUser.role==="admin") return true;
  return teacherAssignments.some(a=>
    a.subject===subject && a.class_id==class_id &&
    (a.stream_id==stream_id || a.stream_id==null)
  );
}
async function populateMarksSelects(){
  const subjSel = document.getElementById("marks-subject");
  const clsSel  = document.getElementById("marks-class");
  if(currentUser.role==="teacher"){
    const teachers = await api("/teachers");
    const me = teachers.find(t=>t.username===currentUser.username);
    teacherAssignments = me ? me.assignments : [];
    if(!teacherAssignments.length){ toast("You have no subject assignments yet. Contact admin.","error"); return; }
    const mySubjects = [...new Set(teacherAssignments.map(a=>a.subject))];
    populateSelect(subjSel, mySubjects, s=>s, s=>cap(s));
    clsSel.innerHTML="";
    const seen = new Set();
    teacherAssignments.forEach(a=>{
      const key = `${a.class_id}:${a.stream_id||0}`;
      if(!seen.has(key)){
        seen.add(key);
        const o=document.createElement("option");
        o.value=key; o.textContent=a.class_name+(a.stream_name?" "+a.stream_name:" – All streams");
        clsSel.appendChild(o);
      }
    });
  } else {
    populateSelect(subjSel, config.allowed_subjects, s=>s, s=>cap(s));
    populateClassSelect(clsSel, true, true);
  }
  rebuildMarksTypeSelect();
}
function rebuildMarksTypeSelect(){
  const typeSel=document.getElementById("marks-type");
  typeSel.innerHTML="";
  const ca_count = (config.active_term ? config.active_term.ca_count : null) || config.ca_count || 2;
  for(let i=1;i<=ca_count;i++){
    const o=document.createElement("option");o.value=`CA${i}`;o.textContent=`CA ${i}`;typeSel.appendChild(o);
  }
  const ex=document.createElement("option");ex.value="exam";ex.textContent="Exam";typeSel.appendChild(ex);
}
function setupMarks(){populateMarksSelects();}

let marksStudents=[], marksSubject="", marksClass=null, marksStream=null, marksType="";
let autoSaveTimers={};

async function saveOneMark(sid, score){
  const badge = document.getElementById(`msaved-${sid}`);
  badge.textContent="⏳"; badge.style.color="var(--orange)";
  let r;
  if(marksType==="exam"){
    r=await api("/marks/exam","POST",{username:currentUser.username,subject:marksSubject,class_id:marksClass,stream_id:marksStream,student_id:sid,score});
  } else {
    r=await api("/marks/ca","POST",{username:currentUser.username,subject:marksSubject,class_id:marksClass,stream_id:marksStream,student_id:sid,ca_name:marksType,score});
  }
  if(r.ok){ badge.textContent="✓ saved"; badge.style.color="var(--green)"; }
  else { badge.textContent="✗ error"; badge.style.color="var(--red)"; toast(`${r.error}`,"error"); }
}
function attachAutosave(sid){
  const inp = document.getElementById(`mscore-${sid}`);
  if(!inp) return;
  inp.addEventListener("input", ()=>{
    const badge = document.getElementById(`msaved-${sid}`);
    badge.textContent="unsaved"; badge.style.color="var(--muted)";
    clearTimeout(autoSaveTimers[sid]);
    autoSaveTimers[sid] = setTimeout(async()=>{
      const raw = inp.value.trim();
      if(raw==="") return;
      const score = parseFloat(raw);
      if(isNaN(score)||score<0||score>100){ inp.classList.add("error"); badge.textContent="invalid"; badge.style.color="var(--red)"; return; }
      inp.classList.remove("error");
      await saveOneMark(sid, score);
    }, 1500);
  });
  inp.addEventListener("blur", async()=>{
    clearTimeout(autoSaveTimers[sid]);
    const raw = inp.value.trim();
    if(raw==="") return;
    const score = parseFloat(raw);
    if(isNaN(score)||score<0||score>100) return;
    inp.classList.remove("error");
    await saveOneMark(sid, score);
  });
}
document.getElementById("marks-load-btn").addEventListener("click", async()=>{
  const subject  = document.getElementById("marks-subject").value;
  const clsVal   = document.getElementById("marks-class").value;
  const type     = document.getElementById("marks-type").value;
  const {class_id, stream_id} = parseClassStream(clsVal);
  if(currentUser.role==="teacher" && !is_teacher_allowed_local(subject, class_id, stream_id)){
    toast("You are not assigned to this subject/class","error"); return;
  }
  const loadBtn = document.getElementById("marks-load-btn");
  loadBtn.textContent="Loading..."; loadBtn.disabled=true;
  try{
    marksSubject = subject; marksClass = class_id; marksStream = stream_id; marksType = type;
    autoSaveTimers = {};
    const sheetMode = type==="exam" ? "exam" : "ca";
    const caParam   = type!=="exam" ? `&ca_name=${type}` : "";
    const streamParam = stream_id ? `&stream_id=${stream_id}` : "";
    const sheet = await api(`/scoresheet?mode=${sheetMode}&class_id=${class_id}${streamParam}${caParam}`);
    const allStu = await api("/students");
    const studs = allStu.filter(s=>s.class_id==class_id && (stream_id ? s.stream_id==stream_id : true));
    if(!studs.length){toast("No students found in this class/stream","error");return;}
    const scoreMap={};
    if(sheet && sheet.results){ sheet.results.forEach(r=>{ const score = r.scores[subject]; if(score!==null && score!==undefined) scoreMap[r.id]=score; }); }
    marksStudents = studs;
    document.getElementById("marks-entry-section").style.display="block";
    const cls = getClassById(class_id);
    const clsLabel = cls ? cls.class_name : "";
    const streamLabel = stream_id ? (()=>{ const s = getStreamById(class_id, stream_id); return s ? " " + s.stream_name : ""; })() : "";
    document.getElementById("marks-entry-title").textContent=`${cap(subject)} – ${clsLabel}${streamLabel} – ${type==="exam"?"Exam":type}`;
    const list = document.getElementById("marks-students-list");
    list.innerHTML = studs.map(s=>{
      const existing = scoreMap[s.id] ?? null;
      return `<div class="marks-student-row">
        <div><div class="marks-student-name">${s.name}</div><div style="font-size:.75rem;color:var(--muted)">ID: ${s.id}</div></div>
        <input type="number" class="marks-score-input" id="mscore-${s.id}" min="0" max="100" step="0.5"
               value="${existing!==null?existing:""}" placeholder="—"/>
        <span class="marks-saved-badge" id="msaved-${s.id}"
              style="color:${existing!==null?'var(--green)':'var(--muted)'}">${existing!==null?"✓ saved":""}</span>
      </div>`;
    }).join("");
    studs.forEach(s=>attachAutosave(s.id));
  } finally {
    loadBtn.innerHTML=`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 12h-5v5h5v-5zM16 1v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-1V1h-2zm3 18H5V8h14v11z"/></svg> Load Students`;
    loadBtn.disabled=false;
  }
});
document.getElementById("marks-save-all-btn").addEventListener("click", async()=>{
  let saved=0, errors=0;
  const btn = document.getElementById("marks-save-all-btn");
  btn.textContent="Saving..."; btn.disabled=true;
  for(const s of marksStudents){
    const inp = document.getElementById(`mscore-${s.id}`);
    const raw = inp.value.trim();
    if(raw==="") continue;
    const score = parseFloat(raw);
    if(isNaN(score)||score<0||score>100){ inp.classList.add("error"); toast(`Invalid score for ${s.name}(must be 0–100)`,"error"); errors++; continue; }
    inp.classList.remove("error");
    let r;
    if(marksType==="exam"){
      r=await api("/marks/exam","POST",{username:currentUser.username,subject:marksSubject,class_id:marksClass,stream_id:marksStream,student_id:s.id,score});
    } else {
      r=await api("/marks/ca","POST",{username:currentUser.username,subject:marksSubject,class_id:marksClass,stream_id:marksStream,student_id:s.id,ca_name:marksType,score});
    }
    if(r.ok){ const badge=document.getElementById(`msaved-${s.id}`); badge.textContent="✓ saved"; badge.style.color="var(--green)"; saved++; }
    else { toast(`${s.name}: ${r.error}`,"error"); errors++; }
  }
  btn.innerHTML=`<svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 3H5c-1.11 0-2 .89-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z"/></svg> Save All Marks`;
  btn.disabled=false;
  if(saved>0) toast(`${saved} mark(s) saved!`,"success");
  if(errors===0&&saved===0) toast("All marks already saved","info");
});
