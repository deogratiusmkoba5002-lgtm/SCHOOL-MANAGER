// ── REPORT CARDS ─────────────────────────────────────────────
document.getElementById("report-view-btn").addEventListener("click",()=>{
  const sid=parseInt(document.getElementById("report-student-id").value);
  if(!sid){toast("Enter a student ID","error");return;}
  viewReport(sid);
});
async function viewReport(sid){
  const out = document.getElementById("report-output");
  out.innerHTML=`<div class="spinner"></div>`;
  const d = await api(`/report/${sid}`);
  if(!d.ok){out.innerHTML=`<div class="section-card"><p style="color:var(--red)">${d.error||"Not found"}</p></div>`;return;}
  renderReportCard(out, d, false);
}

// ── REMARK TEMPLATES ─────────────────────────────────────────
const REMARK_TEMPLATES = {
  excellent:["Shows outstanding academic performance with consistent excellence across all subjects. Keep up the high discipline and focus.","A highly motivated learner who demonstrates excellent understanding and application of concepts.","Consistently performs at a very high level. Maintain this strong academic discipline and continue striving for excellence.","Excellent work. The learner shows maturity, confidence, and strong grasp of all subject content.","Outstanding performance. Keep maintaining this level of commitment and effort in all academic areas."],
  very_good:["Demonstrates strong understanding of most subjects. Keep working on consistency to reach excellence.","A hardworking learner with good academic performance and positive progress.","Shows good effort and understanding. A little more consistency will lead to excellent results.","Good performance overall. Continue practicing and revising regularly for improvement.","A promising learner with solid performance. Can achieve higher results with more focus."],
  average:["Shows average understanding of subject content. More revision and practice is recommended.","Performance is fair but inconsistent. The learner should increase effort and concentration.","Has potential but needs to improve study habits and class participation.","Satisfactory performance. Focus on weak areas is necessary for improvement.","Average achievement. Regular revision and attention in class will improve results."],
  below_average:["Performance is below expectation. The learner needs to improve effort and discipline.","Struggles with understanding key concepts. Extra support and revision are strongly recommended.","Requires consistent study habits and more attention in class.","Weak performance observed. Immediate improvement in study approach is needed.","Needs to improve focus and complete assigned tasks regularly."],
  poor:["Very low academic performance. Immediate intervention and consistent support required.","Demonstrates serious difficulty in understanding subject content. Urgent improvement needed.","Performance is unsatisfactory. Increased effort and discipline are necessary.","Struggling significantly in most areas. Close monitoring is recommended.","Needs strong academic support and commitment to improve."]
};
function remarkTemplateHTML(textareaId){
  const cats = {excellent:"🌟 Excellent",very_good:"👍 Very Good",average:"📊 Average",below_average:"⚠️ Below Average",poor:"❌ Poor"};
  const opts = Object.entries(cats).map(([k,label])=>`
    <optgroup label="${label}">${REMARK_TEMPLATES[k].map((t,i)=>`<option value="${t}">${label} – Option ${i+1}</option>`).join("")}</optgroup>`).join("");
  return `<div style="margin-bottom:8px">
    <label style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Quick Template</label>
    <select onchange="if(this.value){document.getElementById('${textareaId}').value=this.value;this.selectedIndex=0;}"
            style="width:100%;padding:8px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.82rem;margin-top:4px;background:var(--bg)">
      <option value="">— Pick a template or type below —</option>${opts}
    </select>
  </div>`;
}
function renderReportCard(out, d, readOnly){
  const sid     = d.student.id;
  const term_id = d.term ? d.term.id : "";
  const isAdmin = currentUser.role==="admin";
  const isCT    = currentUser.is_class_teacher;
  const canEditCT   = !readOnly && isCT && d.student.class_id == currentUser.class_id;
  const canEditHead = !readOnly && isAdmin;
  const caHeaders = Array.from({length:d.ca_count},(_,i)=>`<th>CA${i+1}</th>`).join("");
  const rows = d.rows.map(r=>{
    const caVals = Array.from({length:d.ca_count},(_,i)=>`<td>${r.ca[`CA${i+1}`]??"-"}</td>`).join("");
    const isFail = r.final!==null&&r.final<50;
    return `<tr class="${isFail?"fail-row":""}"><td style="font-weight:500;text-transform:capitalize">${r.subject}</td>${caVals}<td>${r.exam??"-"}</td><td>${r.final??"-"}</td><td>${r.position}</td><td class="${r.grade!=="-"?gradeClass(r.grade):""}">${r.grade}</td></tr>`;
  }).join("");
  const termLabel = d.term ? d.term.label : "—";
  const pdfUrl    = `${API}/pdf/report/${sid}${term_id?"?term_id="+term_id:""}`;
  const ctBox = canEditCT ? `
    ${remarkTemplateHTML("remark-ct-"+sid)}
    <textarea id="remark-ct-${sid}" rows="3" style="width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;resize:vertical;font-family:inherit" placeholder="Write class teacher remark…">${d.class_teacher_remark||""}</textarea>
    <button class="btn btn-green btn-sm" style="margin-top:8px;width:100%" onclick="saveRemark(${sid},'class_teacher','remark-ct-${sid}')">💾 Save Class Teacher Remark</button>` :
    `<div style="font-size:.9rem;color:${d.class_teacher_remark?'var(--text)':'var(--muted)'}">${d.class_teacher_remark||"—"}</div>`;
  const headBox = canEditHead ? `
    ${remarkTemplateHTML("remark-head-"+sid)}
    <textarea id="remark-head-${sid}" rows="3" style="width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:.85rem;resize:vertical;font-family:inherit" placeholder="Write head of school remark…">${d.head_remark||""}</textarea>
    <button class="btn btn-green btn-sm" style="margin-top:8px;width:100%" onclick="saveRemark(${sid},'head','remark-head-${sid}')">💾 Save Head of School Remark</button>` :
    `<div style="font-size:.9rem;color:${d.head_remark?'var(--text)':'var(--muted)'}">${d.head_remark||"—"}</div>`;
  out.innerHTML=`
  <div class="report-card">
    <div class="report-header-grid">
      <div>
        <div style="font-family:'Syne',sans-serif;font-size:1.2rem;font-weight:800;color:var(--navy)">${d.student.name}</div>
        <div style="font-size:.85rem;color:var(--muted);margin-top:4px">Student Report Card${readOnly?' <span style="color:var(--orange);font-size:.75rem">(Read-only – closed term)</span>':''}</div>
      </div>
      <a href="${pdfUrl}" target="_blank" class="btn btn-pdf btn-sm">
        <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
        Download PDF
      </a>
    </div>
    <div class="report-info-row">
      <div class="report-info-item"><strong>Class</strong>${cap(d.student.class_name)}</div>
      <div class="report-info-item"><strong>Term</strong>${termLabel}</div>
      <div class="report-info-item"><strong>Weights</strong>CA ${d.ca_weight||30}% / Exam ${d.exam_weight||70}%</div>
    </div>
    <div class="summary-band">
      <div class="summary-cell"><div class="val">${d.average}</div><div class="lbl">Average</div></div>
      <div class="summary-cell"><div class="val">${d.grade}</div><div class="lbl">Grade</div></div>
      <div class="summary-cell"><div class="val">${d.class_position}/${d.class_total}</div><div class="lbl">Class Position</div></div>
      ${d.stream_position!=null?`<div class="summary-cell"><div class="val">${d.stream_position}/${d.stream_total}</div><div class="lbl">Stream Position</div></div>`:""}
    </div>
    <div class="table-wrap">
      <table><thead><tr><th>Subject</th>${caHeaders}<th>Exam</th><th>Final</th><th>Pos</th><th>Grade</th></tr></thead><tbody>${rows}</tbody></table>
    </div>
    <div style="margin-top:18px;display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div style="background:var(--pale);border-radius:9px;padding:14px">
        <div style="font-size:.7rem;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Class Teacher Remark</div>${ctBox}
      </div>
      <div style="background:var(--pale);border-radius:9px;padding:14px">
        <div style="font-size:.7rem;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Head of School Remark</div>${headBox}
      </div>
    </div>
  </div>`;
}
async function saveRemark(sid, type, textareaId){
  const remark = document.getElementById(textareaId).value.trim();
  const r = await api("/remarks","POST",{username:currentUser.username,role:currentUser.role,is_class_teacher:currentUser.is_class_teacher,student_id:sid,remark});
  if(r.ok) toast("Remark saved!","success");
  else toast(r.error||"Failed","error");
}

// ── SCORE SHEETS ─────────────────────────────────────────────
const SUBJECT_ABBR = {"historia ya tanzania na maadili":"HTM","mathematics":"MATH","physics":"PHY","chemistry":"CHEM","biology":"BIO","geography":"GEO","history":"HIST","civics":"CIV","english":"ENG","literature":"LIT","kiswahili":"KIS","bible knowledge":"BK","book keeping":"BKP","commerce":"COM","business studies":"BS"};
function subAbbr(s){ return SUBJECT_ABBR[s.toLowerCase()] || s.substring(0,5).toUpperCase(); }

function setupSheets(){
  const buildSheetSel=(sel)=>{
    if(currentUser.is_class_teacher && currentUser.class_id){
      const c=getClassById(currentUser.class_id);
      if(!c){sel.innerHTML="<option>—</option>";return;}
      sel.innerHTML="";
      const addOpt=(val,txt)=>{const o=document.createElement("option");o.value=val;o.textContent=txt;sel.appendChild(o);};
      if(currentUser.stream_id){ const s=getStreamById(currentUser.class_id,currentUser.stream_id); addOpt(`${c.id}:${currentUser.stream_id}`,`${c.class_name} ${s?s.stream_name:""}`); }
      else { addOpt(`${c.id}:0`,`${c.class_name} — Overall`); c.streams.forEach(s=>addOpt(`${c.id}:${s.id}`,`${c.class_name} ${s.stream_name}`)); }
    } else { populateClassSelect(sel,true,true); }
  };
  buildSheetSel(document.getElementById("ca-sheet-class"));
  buildSheetSel(document.getElementById("exam-sheet-class"));
  buildSheetSel(document.getElementById("term-sheet-class"));
  const asSel = document.getElementById("ca-sheet-assess");
  asSel.innerHTML="";
  const ca_count = config.ca_count || 2;
  for(let i=1;i<=ca_count;i++){ const o=document.createElement("option");o.value=`CA${i}`;o.textContent=`CA ${i}`;asSel.appendChild(o); }
  document.querySelectorAll("#sheets-tabs .tab").forEach(t=>{
    t.addEventListener("click",()=>{
      document.querySelectorAll("#sheets-tabs .tab").forEach(x=>x.classList.remove("active")); t.classList.add("active");
      document.getElementById("sheets-tab-ca").style.display       = t.dataset.tab==="ca"      ?"block":"none";
      document.getElementById("sheets-tab-exam").style.display     = t.dataset.tab==="exam"    ?"block":"none";
      document.getElementById("sheets-tab-terminal").style.display = t.dataset.tab==="terminal"?"block":"none";
    });
  });
}
document.getElementById("ca-sheet-view-btn").addEventListener("click", async()=>{
  const {class_id,stream_id}=parseClassStream(document.getElementById("ca-sheet-class").value);
  const ca=document.getElementById("ca-sheet-assess").value;
  const sp=stream_id?`&stream_id=${stream_id}`:"";
  const d=await api(`/scoresheet?mode=ca&class_id=${class_id}${sp}&ca_name=${ca}`);
  renderScoreSheet(document.getElementById("ca-sheet-output"),d,ca);
});
document.getElementById("ca-sheet-pdf-btn").addEventListener("click",()=>{
  const {class_id:cc,stream_id:cs}=parseClassStream(document.getElementById("ca-sheet-class").value);
  const ca=document.getElementById("ca-sheet-assess").value;
  window.open(`${API}/pdf/ca_sheet?class_id=${cc}${cs?`&stream_id=${cs}`:`""`}&ca_name=${ca}`,"_blank");
});
document.getElementById("term-sheet-view-btn").addEventListener("click", async()=>{
  const {class_id,stream_id}=parseClassStream(document.getElementById("term-sheet-class").value);
  const sp=stream_id?`&stream_id=${stream_id}`:"";
  const d=await api(`/scoresheet?mode=terminal&class_id=${class_id}${sp}`);
  renderScoreSheet(document.getElementById("term-sheet-output"),d,"Terminal");
});
document.getElementById("term-sheet-pdf-btn").addEventListener("click",()=>{
  const {class_id:tc,stream_id:ts}=parseClassStream(document.getElementById("term-sheet-class").value);
  window.open(`${API}/pdf/terminal_sheet?class_id=${tc}${ts?`&stream_id=${ts}`:"" }`,"_blank");
});
document.getElementById("exam-sheet-view-btn").addEventListener("click", async()=>{
  const {class_id,stream_id}=parseClassStream(document.getElementById("exam-sheet-class").value);
  const sp=stream_id?`&stream_id=${stream_id}`:"";
  const d=await api(`/scoresheet?mode=exam&class_id=${class_id}${sp}`);
  renderScoreSheet(document.getElementById("exam-sheet-output"),d,"Exam");
});
document.getElementById("exam-sheet-pdf-btn").addEventListener("click",()=>{
  const {class_id,stream_id}=parseClassStream(document.getElementById("exam-sheet-class").value);
  window.open(`${API}/pdf/ca_sheet?class_id=${class_id}${stream_id?`&stream_id=${stream_id}`:"" }&ca_name=exam`,"_blank");
});
function renderScoreSheet(container, d, label){
  if(!d.results||!d.results.length){ container.innerHTML=`<div class="empty-state">${emptySVG()}<p>No data found</p></div>`;return; }
  const subs = d.subjects;
  const hdr  = `<tr><th>#</th><th>Student</th>${subs.map(s=>`<th title="${s}">${subAbbr(s)}</th>`).join("")}<th>Total</th><th>Avg</th><th>Pos</th><th>Grd</th></tr>`;
  const rows = d.results.map((r,i)=>{
    const cells=subs.map(s=>{ const v=r.scores[s]; const fail=v!==null&&v!==undefined&&v<50; return `<td style="${fail?"color:var(--red)":""}">${v!==null&&v!==undefined?v:"-"}</td>`; }).join("");
    const avgFail=r.average>0&&r.average<50;
    return `<tr><td style="color:var(--muted)">${r.position}</td><td style="font-weight:600">${r.name}</td>${cells}<td style="font-weight:600">${r.count>0?r.total.toFixed(1):"-"}</td><td style="font-weight:600;color:${avgFail?"var(--red)":"var(--blue)"}">${r.average>0?r.average:"-"}</td><td>${r.position}</td><td class="${r.grade?gradeClass(r.grade):""}">${r.grade||"-"}</td></tr>`;
  }).join("");
  container.innerHTML=`<div class="table-card"><div class="table-toolbar"><span class="table-toolbar-title">${label} – ${d.results.length} students</span></div><div class="table-wrap"><table class="scoresheet-table"><thead>${hdr}</thead><tbody>${rows}</tbody></table></div></div>`;
}

// ── RANKINGS ─────────────────────────────────────────────────
function setupRankings(){
  populateClassSelect(document.getElementById("rank-class-sel"),true,true);
  const rankSubjSel = document.getElementById("rank-subj-sel");
  if(currentUser.role==="teacher"){ const mySubjs = [...new Set(teacherAssignments.map(a=>a.subject))]; populateSelect(rankSubjSel, mySubjs.length ? mySubjs : config.allowed_subjects, s=>s, s=>cap(s)); }
  else { populateSelect(rankSubjSel, config.allowed_subjects, s=>s, s=>cap(s)); }
  rebuildRankAssessSelect();
}
function rebuildRankAssessSelect(){
  const sel = document.getElementById("rank-assess-sel"); sel.innerHTML="";
  const ca_count = config.ca_count || 2;
  for(let i=1;i<=ca_count;i++){ const o=document.createElement("option");o.value=`CA${i}`;o.textContent=`CA ${i}`;sel.appendChild(o); }
  const ex=document.createElement("option");ex.value="exam";ex.textContent="Final Exam";sel.appendChild(ex);
}
document.getElementById("rank-show-btn").addEventListener("click", async()=>{
  const {class_id,stream_id}=parseClassStream(document.getElementById("rank-class-sel").value);
  const subj   = document.getElementById("rank-subj-sel").value;
  const assess = document.getElementById("rank-assess-sel").value;
  if(currentUser.role==="teacher" && !is_teacher_allowed_local(subj,class_id,stream_id)){ toast("You are not assigned to this subject/class","error"); return; }
  const sp=stream_id?`&stream_id=${stream_id}`:"";
  const d=await api(`/ranking/subject?subject=${encodeURIComponent(subj)}&class_id=${class_id}${sp}&assess=${assess}`);
  const out = document.getElementById("rank-output");
  if(!d.length){ out.innerHTML=`<div class="empty-state">${emptySVG()}<p>No marks entered yet for ${cap(subj)} – ${assess}</p></div>`; return; }
  renderRanking(out, d, "score", `${cap(subj)} – ${assess} – ${classLabel(class_id, stream_id)}`);
});
function renderRanking(container, rows, scoreKey, title=""){
  if(!rows.length){container.innerHTML=`<div class="empty-state">${emptySVG()}<p>No data</p></div>`;return;}
  container.innerHTML=`<div class="table-card"><div class="table-toolbar"><span class="table-toolbar-title">${title}</span></div>
    <div class="table-wrap"><table><thead><tr><th>Pos</th><th>Student</th><th>Score</th><th>Grade</th></tr></thead>
    <tbody>${rows.map(r=>`<tr>
      <td><span class="badge ${r.position<=3?"badge-orange":"badge-grey"}">${r.position===1?"🥇":r.position===2?"🥈":r.position===3?"🥉":r.position}</span></td>
      <td style="font-weight:600">${r.name}</td>
      <td><div style="font-weight:600">${r[scoreKey].toFixed(1)}</div><div class="progress-bar" style="width:120px"><div class="progress-fill" style="width:${Math.min(r[scoreKey],100)}%"></div></div></td>
      <td class="${gradeClass(r.grade)}">${r.grade}</td>
    </tr>`).join("")}</tbody></table></div></div>`;
}

// ── TERMS ────────────────────────────────────────────────────
async function loadTerms(){
  const terms = await api("/terms");
  allTerms = terms;
  const tb = document.getElementById("terms-tbody");
  if(!terms.length){ tb.innerHTML=`<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:20px">No terms yet. Create one above.</td></tr>`; return; }
  tb.innerHTML=terms.map(t=>`<tr>
    <td style="font-weight:600">${t.label}</td>
    <td>${t.ca_count}</td><td>${t.ca_weight}%</td><td>${t.exam_weight}%</td>
    <td><span class="badge ${t.status==='open'?'badge-green':'badge-grey'}">${t.status.toUpperCase()}</span></td>
    <td>${t.status==='open'?`<button class="btn btn-sm btn-red" onclick="closeTerm(${t.id},'${t.label}')">Close Term</button>`:'<span style="color:var(--muted);font-size:.8rem">Locked</span>'}</td>
  </tr>`).join("");
}
document.getElementById("btn-open-term").addEventListener("click", async()=>{
  const label     = document.getElementById("term-label").value.trim();
  const ca_count  = parseInt(document.getElementById("term-ca-count").value);
  const ca_weight = parseInt(document.getElementById("term-ca-weight").value);
  const exam_weight = 100 - ca_weight;
  if(!label){toast("Enter a term label","error");return;}
  const r = await api("/terms","POST",{label,ca_count,ca_weight,exam_weight});
  if(r.ok){ toast(`${label} opened!`,"success"); document.getElementById("term-label").value=""; await loadTerms(); await refreshTermBanner(); }
  else toast(r.error||"Failed","error");
});
async function closeTerm(id, label){
  if(!confirm(`Close "${label}"?\n\nAll marks for this term will be LOCKED and cannot be edited. This cannot be undone.`)) return;
  const r = await api(`/terms/${id}/close`,"POST",{});
  if(r.ok){ toast(`${label} closed and locked.`,"success"); await loadTerms(); await refreshTermBanner(); }
  else toast(r.error||"Failed","error");
}

// ── PAST TERMS ───────────────────────────────────────────────
async function setupPastTerms(){
  const terms  = await api("/terms");
  const closed = terms.filter(t=>t.status==="closed");
  ["past-term-sel","past-term-sel2"].forEach(id=>{
    const sel = document.getElementById(id); if(!sel) return;
    sel.innerHTML = closed.length ? closed.map(t=>`<option value="${t.id}">${t.label}</option>`).join("") : `<option disabled>No closed terms yet</option>`;
  });
  const subjSel  = document.getElementById("past-subject-sel");
  const classSel = document.getElementById("past-class-sel");
  if(currentUser.role==="teacher"){
    const mySubjs = [...new Set(teacherAssignments.map(a=>a.subject))];
    populateSelect(subjSel,mySubjs.length?mySubjs:config.allowed_subjects,s=>s,s=>cap(s));
    classSel.innerHTML=""; const seenPT=new Set();
    teacherAssignments.forEach(a=>{ const key=`${a.class_id}:${a.stream_id||0}`; if(!seenPT.has(key)){seenPT.add(key);const o=document.createElement("option");o.value=key;o.textContent=a.class_name+(a.stream_name?" "+a.stream_name:" – All");classSel.appendChild(o);} });
  } else { populateSelect(subjSel,config.allowed_subjects,s=>s,s=>cap(s)); populateClassSelect(classSel,true,true); }
  document.querySelectorAll("#past-tabs .tab").forEach(t=>{
    t.addEventListener("click",()=>{
      document.querySelectorAll("#past-tabs .tab").forEach(x=>x.classList.remove("active")); t.classList.add("active");
      document.getElementById("past-tab-marks").style.display  = t.dataset.ptab==="marks" ?"block":"none";
      document.getElementById("past-tab-report").style.display = t.dataset.ptab==="report"?"block":"none";
    });
  });
}
document.getElementById("past-marks-btn").addEventListener("click", async()=>{
  const term_id  = document.getElementById("past-term-sel").value;
  const subject  = document.getElementById("past-subject-sel").value;
  const {class_id, stream_id} = parseClassStream(document.getElementById("past-class-sel").value);
  if(!term_id){toast("Select a term","error");return;}
  if(currentUser.role==="teacher" && !is_teacher_allowed_local(subject,class_id,stream_id)){ toast("Access denied — not your assignment","error"); return; }
  const out = document.getElementById("past-marks-output");
  out.innerHTML=`<div class="spinner"></div>`;
  const terms  = await api("/terms");
  const term   = terms.find(t=>t.id==term_id);
  const ca_count = term ? term.ca_count : 2;
  const allStu = await api("/students");
  const studs = allStu.filter(s=>s.class_id==class_id&&(stream_id?s.stream_id==stream_id:true));
  if(!studs.length){ out.innerHTML=`<div class="empty-state">${emptySVG()}<p>No students in this class/stream</p></div>`;return; }
  const rows = await Promise.all(studs.map(async s=>{
    const r = await api(`/report/${s.id}?term_id=${term_id}`);
    if(!r.ok) return {name:s.name, cas:{}, exam:null};
    const row = r.rows.find(x=>x.subject===subject);
    return {name:s.name, cas: row ? row.ca : {}, exam: row ? row.exam : null, final: row ? row.final : null};
  }));
  const caHeaders = Array.from({length:ca_count},(_,i)=>`<th>CA${i+1}</th>`).join("");
  const bodyRows  = rows.map((r,i)=>{
    const caCells = Array.from({length:ca_count},(_,j)=>{ const v = r.cas[`CA${j+1}`]; const fail = v!==null&&v!==undefined&&v<50; return `<td style="${fail?"color:var(--red);font-weight:600":""}">${v!==null&&v!==undefined?v:"-"}</td>`; }).join("");
    const examFail = r.exam!==null&&r.exam<50; const finalFail = r.final!==null&&r.final<50;
    return `<tr><td style="color:var(--muted)">${i+1}</td><td style="font-weight:600">${r.name}</td>${caCells}<td style="${examFail?"color:var(--red);font-weight:600":""}">${r.exam!==null?r.exam:"-"}</td><td style="${finalFail?"color:var(--red);font-weight:600":"font-weight:600;color:var(--blue)"}">${r.final!==null?r.final:"-"}</td></tr>`;
  }).join("");
  out.innerHTML=`<div class="table-card"><div class="table-toolbar"><span class="table-toolbar-title">${cap(subject)} — ${classLabel(class_id,stream_id)} — ${term?term.label:""}</span></div>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>Student</th>${caHeaders}<th>Exam</th><th>Final</th></tr></thead><tbody>${bodyRows}</tbody></table></div></div>`;
});
document.getElementById("past-view-btn").addEventListener("click", async()=>{
  const term_id = document.getElementById("past-term-sel2").value;
  const sid     = parseInt(document.getElementById("past-student-id").value);
  if(!term_id){toast("Select a term","error");return;}
  if(!sid){toast("Enter a student ID","error");return;}
  if(currentUser.is_class_teacher){
    const studs = await api("/students");
    const s = studs.find(x=>x.id===sid);
    if(!s||s.class_id!=currentUser.class_id){ toast("Access denied — not your class","error"); return; }
  }
  const out = document.getElementById("past-report-output");
  out.innerHTML=`<div class="spinner"></div>`;
  const d = await api(`/report/${sid}?term_id=${term_id}`);
  if(!d.ok){out.innerHTML=`<div class="section-card"><p style="color:var(--red)">${d.error||"Not found"}</p></div>`;return;}
  renderReportCard(out, d, true);
});
