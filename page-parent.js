// ── PARENT DASHBOARD ─────────────────────────────────────────
async function loadParentDashboard(){
  const conf = await api("/config");
  const schoolName = conf.school_name || "our school";
  const raw = currentUser.username.replace(/_/g," ");
  const studentName = raw.charAt(0).toUpperCase() + raw.slice(1);
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  document.getElementById("parent-greeting-text").textContent = greeting + ", " + studentName + "!";
  document.getElementById("parent-greeting-sub").textContent  = "Welcome to " + schoolName + " Student Portal";
  checkAnnouncementDot();
}

// ── PARENT REPORTS ────────────────────────────────────────────
let parentPublishedTerms = [];

function showParentSection(section){
  document.getElementById("parent-reports-choice").style.display = section ? "none" : "grid";
  document.getElementById("parent-section-report-card").style.display = section==="report-card" ? "block" : "none";
  document.getElementById("parent-section-results").style.display    = section==="results"      ? "block" : "none";
  if(section==="report-card") populateParentTermSel("parent-rc-term-sel");
  if(section==="results")     populateParentTermSel("parent-res-term-sel", true);
}
function populateParentTermSel(selId, loadAssessments=false){
  const sel = document.getElementById(selId);
  if(!parentPublishedTerms.length){ sel.innerHTML="<option value=''>No published results yet</option>"; return; }
  sel.innerHTML = parentPublishedTerms.map(t=>`<option value="${t.id}">${t.label}</option>`).join("");
  if(loadAssessments) loadResAssessments();
}
async function loadParentReports(){
  const terms = await api("/parent/terms");
  parentPublishedTerms = terms;
  loadAnalyticsData();
}
async function loadResAssessments(){
  const term_id = document.getElementById("parent-res-term-sel").value;
  if(!term_id) return;
  const assessSel = document.getElementById("parent-res-assess-sel");
  assessSel.innerHTML="";
  const pub = await api(`/results/assessments?term_id=${term_id}`);
  if(!pub.ok) return;
  pub.assessments.filter(a=>a.published).forEach(a=>{
    const o=document.createElement("option"); o.value=a.assess_key; o.textContent=a.label; assessSel.appendChild(o);
  });
  if(!assessSel.options.length){ const o=document.createElement("option"); o.value=""; o.textContent="No published assessments yet"; assessSel.appendChild(o); }
}
document.getElementById("parent-view-rc-btn").addEventListener("click", async()=>{
  const term_id = document.getElementById("parent-rc-term-sel").value;
  if(!term_id){toast("Select a term","error");return;}
  const sid = currentUser.student_id;
  if(!sid){toast("No student linked to this account","error");return;}
  const out = document.getElementById("parent-rc-output");
  out.innerHTML=`<div class="spinner"></div>`;
  const d = await api(`/report/${sid}?term_id=${term_id}`);
  if(!d.ok){ out.innerHTML=`<div class="section-card"><p style="color:var(--red);text-align:center;padding:20px">${d.error}</p></div>`; return; }
  renderReportCard(out, d, true);
});
document.getElementById("parent-view-res-btn").addEventListener("click", async()=>{
  const term_id = document.getElementById("parent-res-term-sel").value;
  const assessSel = document.getElementById("parent-res-assess-sel");
  const assess  = assessSel.value;
  const assessLabel = assessSel.options[assessSel.selectedIndex] ? assessSel.options[assessSel.selectedIndex].textContent : assess;
  if(!term_id||!assess){toast("Select term and assessment","error");return;}
  const sid = currentUser.student_id;
  if(!sid){toast("No student linked to this account","error");return;}
  const out = document.getElementById("parent-res-output");
  out.innerHTML=`<div class="spinner"></div>`;
  const d = await api(`/parent/results?student_id=${sid}&term_id=${term_id}&assess=${assess}`);
  if(!d.ok){ out.innerHTML=`<div class="section-card"><p style="color:var(--red);text-align:center;padding:20px">${d.error}</p></div>`; return; }
  renderParentSingleResults(out, d, assess, assessLabel);
});
function renderParentSingleResults(out, d, assess, assessLabel){
  assessLabel = assessLabel || (assess==="exam" ? "Final Exam" : assess);
  const streamPos = d.stream_position!=null ? `<div class="summary-cell"><div class="val">${d.stream_position}/${d.stream_total}</div><div class="lbl">Stream Pos</div></div>` : "";
  const divisionCell = d.division ? `<div class="summary-cell"><div class="val">${d.division}</div><div class="lbl">Division</div></div>` : "";
  const pointsCell = d.division_points!=null ? `<div class="summary-cell"><div class="val">${d.division_points}</div><div class="lbl">Points</div></div>` : "";
  const sorted = [...d.results].filter(r=>{ const score = r.score; return score!==null && score!==undefined; })
    .sort((a,b)=>{ const pa = typeof a.position==="number" ? a.position : 9999; const pb = typeof b.position==="number" ? b.position : 9999; return pa - pb; });
  const rows = sorted.map(r=>{
    const score = r.score;
    const isFail= score!==null && score!==undefined && score<50;
    return `<tr>
      <td style="font-weight:500;text-transform:capitalize">${r.subject}</td>
      <td style="font-weight:700;color:${isFail?"var(--red)":"var(--text)"}">${score}</td>
      <td class="${r.grade!=="-"?gradeClass(r.grade):""}">${get_grade_js(score)}</td>
      <td style="font-weight:600;color:var(--blue)">${r.position}</td>
    </tr>`;
  }).join("");
  out.innerHTML=`<div class="report-card">
    <div style="margin-bottom:14px">
      <div style="font-family:'Syne',sans-serif;font-size:1.1rem;font-weight:800;color:var(--navy)">${d.student.name}</div>
      <div style="font-size:.82rem;color:var(--muted)">${d.student.class_name}${d.student.stream_name?" "+d.student.stream_name:""} · ${d.term.label} · ${assessLabel}</div>
    </div>
    <div class="summary-band" style="margin-bottom:16px">
      <div class="summary-cell"><div class="val">${d.average.toFixed(1)}</div><div class="lbl">Average</div></div>
      <div class="summary-cell"><div class="val">${get_grade_js(d.average)}</div><div class="lbl">Grade</div></div>
      <div class="summary-cell"><div class="val">${d.class_position}/${d.class_total}</div><div class="lbl">Class Pos</div></div>
      ${streamPos}
      ${divisionCell}
      ${pointsCell}
    </div>
    <div class="table-wrap">
      <table><thead><tr><th>Subject</th><th>Score</th><th>Grade</th><th>Position</th></tr></thead>
      <tbody>${rows||'<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:20px">No marks entered yet for this assessment</td></tr>'}</tbody></table>
    </div>
  </div>`;
}

// ── ADMIN PARENTS PAGE ────────────────────────────────────────
async function loadParentsPage(){
  const status = await api("/results/status");
  const statusEl = document.getElementById("results-status-display");
  if(status.term){
    const pubColor = status.published ? "var(--green)" : "var(--orange)";
    const pubText  = status.published ? "✅ Results are VISIBLE to parents" : "🔒 Results are HIDDEN from parents";
    statusEl.innerHTML = `<div style="font-weight:600;color:${pubColor};margin-bottom:4px">${pubText}</div>
      <div style="font-size:.82rem;color:var(--muted)">Active term: <strong>${status.term.label}</strong>
      (CA ${status.term.ca_weight}% + Exam ${status.term.exam_weight}%)</div>`;
  } else {
    statusEl.innerHTML = `<span style="color:var(--muted)">No active term. Open a term first.</span>`;
  }
  const annTarget = document.getElementById("ann-target");
  annTarget.innerHTML = `<option value="all">All Classes</option>` +
    allClasses.map(c=>`<option value="${c.class_name}">${c.class_name}</option>`).join("");
  annTarget.value = "all";
  const anns = await api("/announcements");
  const annList = document.getElementById("announcements-admin-list");
  if(!anns.length){
    annList.innerHTML=`<p style="color:var(--muted);text-align:center;padding:20px">No announcements yet.</p>`;
  } else {
    annList.innerHTML = anns.map(a=>`
      <div style="border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <div>
            <div style="font-weight:700;color:var(--navy);margin-bottom:4px">${escHtml(a.title)}</div>
            <div style="font-size:.82rem;color:var(--muted);margin-bottom:6px">To: <strong>${a.target_classes==="all"?"All Classes":escHtml(a.target_classes)}</strong> &nbsp;·&nbsp; ${a.posted_at ? a.posted_at.substring(0,16).replace("T"," ") : ""}</div>
            <div style="font-size:.88rem;color:var(--text)">${escHtml(a.body)}</div> 
          </div>
          <button class="btn btn-sm btn-red btn-icon" onclick="deleteAnnouncement(${a.id})" style="flex-shrink:0">
            <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
          </button>
        </div>
      </div>`).join("");
  }
}
document.getElementById("btn-publish-results").addEventListener("click", ()=>{ if(requireSub()) openPublishModal(); });

async function openPublishModal(){
  const status = await api("/results/status");
  if(!status.term_id){ toast("No active term","error"); return; }
  const data = await api(`/results/assessments?term_id=${status.term_id}`);
  if(!data.ok) return;
  const unpublished = data.assessments.filter(a=>!a.published);
  if(!unpublished.length){ toast("Everything for this term is already published","info"); return; }
  const existing = document.getElementById("publish-picker"); if(existing) existing.remove();
  const panel = document.createElement("div");
  panel.className="section-card"; panel.id="publish-picker"; panel.style.marginTop="12px";
  panel.innerHTML = `<div style="font-weight:700;margin-bottom:8px">Select what to publish</div>
    ${unpublished.map(a=>`<label style="display:flex;align-items:center;gap:8px;padding:6px 0">
      <input type="checkbox" class="pub-assess-check" value="${a.assess_key}" checked/> ${escHtml(a.label)}</label>`).join("")}
    <div style="display:flex;gap:10px;margin-top:12px">
      <button class="btn btn-green btn-sm" id="confirm-publish-selected">Publish Selected</button>
      <button class="btn btn-outline btn-sm" onclick="this.closest('.section-card').remove()">Cancel</button>
    </div>`;
  document.getElementById("results-status-display").after(panel);
  panel.querySelector("#confirm-publish-selected").addEventListener("click", async()=>{
    const keys=[...panel.querySelectorAll(".pub-assess-check:checked")].map(c=>c.value);
    if(!keys.length){ toast("Select at least one","error"); return; }
    const r = await api("/results/publish_assessments","POST",{term_id:status.term_id, assess_keys:keys, publish:true});
    if(r.ok){ toast("Published!","success"); panel.remove(); loadParentsPage(); } else toast(r.error||"Failed","error");
  });
}
document.getElementById("btn-unpublish-results").addEventListener("click", async()=>{
  const status = await api("/results/status");
  if(!status.term_id){toast("No active term","error");return;}
  if(!confirm("Hide results from parents?"))return;
  const r = await api("/results/toggle","POST",{term_id:status.term_id,publish:false});
  if(r.ok){toast("Results hidden from parents.","success");loadParentsPage();}
  else toast(r.error||"Failed","error");
});
document.getElementById("btn-post-announcement").addEventListener("click", async()=>{
  if(!requireSub())return;
  const title = document.getElementById("ann-title").value.trim();
  const body  = document.getElementById("ann-body").value.trim();
  const sel   = document.getElementById("ann-target");
  const selected = [...sel.selectedOptions].map(o=>o.value);
  if(!title||!body){toast("Title and message required","error");return;}
  let target_classes;
  if(!selected.length){
    target_classes = "all";
    toast("No target classes were selected, so this was sent to All Classes.","info");
  } else {
    target_classes = selected.includes("all") ? "all" : selected.join(",");
  }
  const r = await api("/announcements","POST",{title,body,target_classes,posted_by:currentUser.username});
  if(r.ok){ toast("Announcement posted!","success"); document.getElementById("ann-title").value=""; document.getElementById("ann-body").value=""; loadParentsPage(); }
  else toast(r.error||"Failed","error");
});
async function deleteAnnouncement(id){
  if(!confirm("Delete this announcement?"))return;
  const r = await api(`/announcements/${id}`,"DELETE");
  if(r.ok){toast("Deleted","success");loadParentsPage();}
  else toast(r.error||"Failed","error");
}

// ── PARENT ANNOUNCEMENTS ──────────────────────────────────────
async function loadParentAnnouncements(){
  const sid = currentUser.student_id;
  const anns = sid ? await api(`/announcements?student_id=${sid}`) : [];
  const list = document.getElementById("parent-announcements-list");
  if(!anns.length){
    list.innerHTML=`<div style="text-align:center;padding:40px;color:var(--muted)">
      <svg viewBox="0 0 24 24" fill="var(--border)" width="48" height="48" style="margin-bottom:12px"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
      <div>No announcements yet</div></div>`;
    return;
  }
  const unread = anns.filter(a=>!a.is_read);
  unread.forEach(a=>api(`/announcements/${a.id}/read`,"POST",{student_id:sid}));
  list.innerHTML = anns.map(a=>`
    <div style="background:var(--card);border-radius:12px;padding:18px 20px;margin-bottom:12px;box-shadow:var(--shadow);border-left:4px solid ${a.is_read?"var(--border)":"var(--blue)"}">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        ${!a.is_read?`<span style="width:8px;height:8px;border-radius:50%;background:var(--blue);flex-shrink:0"></span>`:""}
        <div style="font-weight:700;color:var(--navy);font-size:.95rem">${escHtml(a.title)}</div>
      </div>
      <div style="font-size:.88rem;color:var(--text);margin-bottom:8px">${escHtml(a.body)}</div>
      <div style="font-size:.75rem;color:var(--muted)">${a.posted_at?a.posted_at.substring(0,16).replace("T"," "):""}</div>
    </div>`).join("");
  updateAnnouncementDot(0);
}
function updateAnnouncementDot(unreadCount){
  const navItem = document.querySelector('.nav-item[data-page="parent-announcements"]');
  if(!navItem) return;
  const existing = navItem.querySelector(".ann-dot");
  if(unreadCount>0 && !existing){ const dot=document.createElement("span"); dot.className="ann-dot"; dot.style.cssText="width:8px;height:8px;border-radius:50%;background:#FF6D00;margin-left:auto;flex-shrink:0"; navItem.appendChild(dot); }
  else if(unreadCount===0 && existing){ existing.remove(); }
}
async function checkAnnouncementDot(){
  if(currentUser.role!=="parent") return;
  const sid = currentUser.student_id; if(!sid) return;
  const anns = await api(`/announcements?student_id=${sid}`);
  updateAnnouncementDot(anns.filter(a=>!a.is_read).length);
}

// ── ANALYTICS ────────────────────────────────────────────────
let analyticsData    = null;
let analyticsTab     = "avg";
let analyticsSubject = null;
let ALLOWED_SUBJECTS = ["mathematics","physics","chemistry","biology","geography","history","civics","english","literature","kiswahili","bible knowledge","book keeping","commerce","business studies","historia ya tanzania na maadili"];

function switchAnalyticsTab(tab){
  analyticsTab = tab;
  document.querySelectorAll("#analytics-tabs .tab").forEach(t=>{ t.classList.toggle("active", t.dataset.atab===tab); });
  document.getElementById("analytics-subject-picker").style.display = tab==="subject" ? "block" : "none";
  renderAnalytics();
}
async function loadAnalyticsData(){
  const sid = currentUser.student_id; if(!sid) return;
  if(!parentPublishedTerms.length){ const terms = await api("/parent/terms"); parentPublishedTerms = terms; }
  if(!parentPublishedTerms.length){ showAnalyticsNoData(); return; }
  const sortedTerms = [...parentPublishedTerms].sort((a,b)=>a.id - b.id);
  const dataPoints = [];
  for(const term of sortedTerms){
    const assessments = [];
    for(let i=1;i<=term.ca_count;i++) assessments.push({key:`CA${i}`, label:`${term.label} CA${i}`});
    assessments.push({key:"exam", label:`${term.label} Exam`});
    // Tests weren't being fetched at all here, so any term whose only
    // published assessment was a test silently dropped off the graph.
    const tests = await api(`/tests?term_id=${term.id}`);
    (tests||[]).forEach(t=> assessments.push({key:`test:${t.id}`, label:`${term.label} ${t.label}`}));
    for(const a of assessments){
      const assess = a.key;
      const d = await api(`/parent/results?student_id=${sid}&term_id=${term.id}&assess=${assess}`);
      if(!d.ok || !d.results || !d.results.length) continue;
      const subjectScores = {};
      d.results.forEach(r=>{ const score = r.score; if(score!==null && score!==undefined) subjectScores[r.subject] = score; });
      if(!Object.keys(subjectScores).length) continue;
      const scores = Object.values(subjectScores);
      const avg = scores.reduce((x,y)=>x+y,0)/scores.length;
      dataPoints.push({ label:a.label, assess, term, subjectScores, avg: Math.round(avg*10)/10, class_position:d.class_position, class_total:d.class_total, stream_position:d.stream_position, stream_total:d.stream_total });
    }
  }
  analyticsData = dataPoints.length > 5 ? dataPoints.slice(-5) : dataPoints;
  if(!analyticsData.length){ showAnalyticsNoData(); return; }
  document.getElementById("analytics-chart").style.display="block";
  document.getElementById("analytics-no-data").style.display="none";
  document.getElementById("analytics-summary-grid").style.display="grid";
  document.getElementById("analytics-insights-card").style.display="block";
  const allSubjects = [...new Set(analyticsData.flatMap(d=>Object.keys(d.subjectScores)))];
  const subjSel = document.getElementById("analytics-subject-sel");
  subjSel.innerHTML = allSubjects.map(s=>`<option value="${s}">${s.charAt(0).toUpperCase()+s.slice(1)}</option>`).join("");
  analyticsSubject = allSubjects[0];
  renderAnalytics(); renderAnalyticsSummary(); renderAnalyticsInsights();
}
function showAnalyticsNoData(){
  document.getElementById("analytics-chart").style.display="none";
  document.getElementById("analytics-no-data").style.display="block";
  document.getElementById("analytics-summary-grid").style.display="grid";
  document.getElementById("analytics-insights-card").style.display="block";
  document.getElementById("analytics-best").innerHTML=`<p style="color:var(--muted);font-size:.85rem">No published results yet.</p>`;
  document.getElementById("analytics-weak").innerHTML=`<p style="color:var(--muted);font-size:.85rem">No published results yet.</p>`;
  document.getElementById("analytics-insights").innerHTML=`<p style="color:var(--muted);font-size:.85rem">No published results yet. Results will appear here once published by the school.</p>`;
}
function renderAnalytics(){
  if(!analyticsData||!analyticsData.length) return;
  const canvas = document.getElementById("analytics-chart");
  canvas.style.display="block";
  document.getElementById("analytics-no-data").style.display="none";
  let points = [];
  let labels = analyticsData.map(d=>d.label);
  if(analyticsTab==="avg"){ points = analyticsData.map(d=>d.avg); }
  else { analyticsSubject = document.getElementById("analytics-subject-sel").value; points = analyticsData.map(d=>d.subjectScores[analyticsSubject]??null); }
  const dpr = window.devicePixelRatio||1;
  const container = canvas.parentElement;
  const W = Math.max((container.clientWidth||500) - 4, 260);
  const isSmall = W < 420;
  const H = isSmall ? 220 : 260;
  canvas.width = Math.round(W*dpr); canvas.height = Math.round(H*dpr);
  canvas.style.width = "100%"; canvas.style.height = H+"px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0); // reset instead of compounding scale each render
  const PAD = isSmall ? {top:16, right:10, bottom:60, left:34} : {top:20, right:20, bottom:80, left:48};
  const cW  = W - PAD.left - PAD.right;
  const cH  = H - PAD.top  - PAD.bottom;
  ctx.clearRect(0,0,W,H);
  const gridLines = [0,25,50,75,100];
  ctx.strokeStyle="#E3F2FD"; ctx.lineWidth=1;
  ctx.fillStyle="#546E7A"; ctx.font= isSmall ? "9px Arial" : "11px Arial";
  gridLines.forEach(v=>{ const y = PAD.top + cH - (v/100)*cH; ctx.beginPath(); ctx.moveTo(PAD.left,y); ctx.lineTo(PAD.left+cW,y); ctx.stroke(); ctx.textAlign="right"; ctx.fillText(v, PAD.left-6, y+4); });
  const step = points.length>1 ? cW/(points.length-1) : cW;
  ctx.fillStyle="#546E7A"; ctx.font = isSmall ? "8px Arial" : "9px Arial";
  labels.forEach((lbl,i)=>{ const x = PAD.left + (points.length>1 ? i*step : cW/2); const y = PAD.top+cH+14; ctx.save(); ctx.translate(x,y); ctx.rotate(-Math.PI/4); ctx.textAlign="right"; ctx.fillText(lbl, 0, 0); ctx.restore(); });
  const validPoints = points.map((v,i)=>v!==null?{x:PAD.left+(points.length>1?i*step:cW/2), y:PAD.top+cH-(v/100)*cH, v}:null);
  ctx.strokeStyle="#1565C0"; ctx.lineWidth=2.5; ctx.lineJoin="round"; ctx.lineCap="round";
  ctx.beginPath(); let first=true;
  validPoints.forEach(p=>{ if(!p) return; if(first){ctx.moveTo(p.x,p.y);first=false;} else ctx.lineTo(p.x,p.y); }); ctx.stroke();
  const firstValid = validPoints.find(p=>p); const lastValid = [...validPoints].reverse().find(p=>p);
  if(firstValid&&lastValid){ ctx.beginPath(); ctx.moveTo(firstValid.x, PAD.top+cH); validPoints.forEach(p=>{ if(p) ctx.lineTo(p.x,p.y); }); ctx.lineTo(lastValid.x, PAD.top+cH); ctx.closePath(); const grad=ctx.createLinearGradient(0,PAD.top,0,PAD.top+cH); grad.addColorStop(0,"rgba(21,101,192,.18)"); grad.addColorStop(1,"rgba(21,101,192,.02)"); ctx.fillStyle=grad; ctx.fill(); }
  validPoints.forEach(p=>{ if(!p) return; const fail = p.v < 50; const r = isSmall?4:5; ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI*2); ctx.fillStyle= fail ? "#F44336" : "#1565C0"; ctx.fill(); ctx.strokeStyle="white"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle= fail ? "#C62828" : "#0A1628"; ctx.font=isSmall?"bold 9px Arial":"bold 11px Arial"; ctx.textAlign="center"; ctx.fillText(p.v, p.x, p.y-10); });
}
function renderAnalyticsSummary(){
  if(!analyticsData||analyticsData.length<1) return;
  const recent = analyticsData.slice(-3);
  const subjectAvgs = {};
  ALLOWED_SUBJECTS.forEach(s=>{ const scores = recent.map(d=>d.subjectScores[s]).filter(v=>v!==undefined&&v!==null); if(scores.length) subjectAvgs[s]=scores.reduce((a,b)=>a+b,0)/scores.length; });
  const sorted = Object.entries(subjectAvgs).sort((a,b)=>b[1]-a[1]);
  const best = sorted.slice(0,3); const weak = sorted.slice(-3).reverse();
  const capS = s=>s.charAt(0).toUpperCase()+s.slice(1);
  document.getElementById("analytics-best").innerHTML = best.length
    ? best.map(([s,v])=>`<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--pale)"><span style="font-size:.85rem">${capS(s)}</span><span style="font-weight:700;color:var(--green)">${v.toFixed(1)}</span></div>`).join("")
    : `<p style="color:var(--muted);font-size:.85rem">Not enough data</p>`;
  document.getElementById("analytics-weak").innerHTML = weak.length
    ? weak.map(([s,v])=>`<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--pale)"><span style="font-size:.85rem">${capS(s)}</span><span style="font-weight:700;color:var(--red)">${v.toFixed(1)}</span></div>`).join("")
    : `<p style="color:var(--muted);font-size:.85rem">Not enough data</p>`;
}
function renderAnalyticsInsights(){
  if(!analyticsData||analyticsData.length<2){ document.getElementById("analytics-insights").innerHTML=`<p style="color:var(--muted);font-size:.85rem">Need at least 2 published results to generate insights.</p>`; return; }
  const studentName = (currentUser.username||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());
  const last = analyticsData[analyticsData.length-1]; const prev = analyticsData[analyticsData.length-2];
  const capS = s=>s.charAt(0).toUpperCase()+s.slice(1);
  const insights = [];
  ALLOWED_SUBJECTS.forEach(s=>{
    const cur = last.subjectScores[s]; const pre = prev.subjectScores[s];
    if(cur===undefined||cur===null) return;
    const allScores = analyticsData.map(d=>d.subjectScores[s]).filter(v=>v!==undefined&&v!==null);
    const avg = allScores.reduce((a,b)=>a+b,0)/allScores.length;
    if(avg>=85){ insights.push({type:"success", text:`Outstanding performance in ${capS(s)}! ${studentName} consistently excels here — keep maintaining this exceptional standard.`}); }
    else if(avg<40){ insights.push({type:"danger", text:`${capS(s)} requires urgent attention. ${studentName} is scoring below expectations — increased focus, revision and support are strongly recommended.`}); }
    else if(pre!==undefined&&pre!==null){
      const diff = cur-pre;
      if(diff>=15){ insights.push({type:"success", text:`Excellent improvement in ${capS(s)}! ${studentName} has made significant progress — keep up this momentum.`}); }
      else if(diff<=-15){ insights.push({type:"warning", text:`A noticeable decline has been observed in ${capS(s)}. ${studentName} is encouraged to dedicate more time to revision.`}); }
      else { insights.push({type:"info", text:`${studentName} is maintaining consistent performance in ${capS(s)}. Steady progress — a little extra push could move results to the next grade.`}); }
    }
  });
  const curAvg = last.avg; const prevAvg = prev.avg;
  if(curAvg>prevAvg){ insights.unshift({type:"success", text:`📈 Overall average improved from ${prevAvg} to ${curAvg}. Great work, ${studentName}!`}); }
  else if(curAvg<prevAvg){ insights.unshift({type:"warning", text:`📉 Overall average dropped from ${prevAvg} to ${curAvg}. ${studentName} should focus on weaker areas.`}); }
  if(last.class_total>0){
    const pct = last.class_position/last.class_total;
    if(pct<=0.25){ insights.unshift({type:"success", text:`🏆 ${studentName} is among the top 25% of students in the class — an outstanding achievement!`}); }
    else if(last.stream_position&&last.stream_total&&last.stream_position/last.stream_total<=0.25){ insights.unshift({type:"success", text:`⭐ ${studentName} is among the top 25% performers in the class stream. Aim for the top of the whole class!`}); }
  }
  const colors={success:"var(--green)",warning:"var(--orange)",danger:"var(--red)",info:"var(--blue)"};
  const bgcol ={success:"#E8F5E9",warning:"#FFF3E0",danger:"#FFEBEE",info:"#E3F2FD"};
  const icons ={success:"✅",warning:"⚠️",danger:"🚨",info:"💡"};
  document.getElementById("analytics-insights").innerHTML = insights.length
    ? insights.map(ins=>`<div style="display:flex;gap:10px;padding:10px 12px;border-radius:8px;background:${bgcol[ins.type]};margin-bottom:8px;border-left:3px solid ${colors[ins.type]}"><span style="flex-shrink:0;font-size:1rem">${icons[ins.type]}</span><span style="font-size:.84rem;color:#333;line-height:1.5">${ins.text}</span></div>`).join("")
    : `<p style="color:var(--muted);font-size:.85rem">No insights available yet.</p>`;
}
