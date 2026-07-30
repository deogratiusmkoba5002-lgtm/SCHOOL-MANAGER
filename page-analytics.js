// ── ANALYTICS (Admin / Class Teacher / Subject Teacher) ───────
// Shared rendering for the accordion-card + trend-graph layout used by
// all three analytics pages. Card data always comes pre-computed from
// the backend (/api/analytics/overview or /api/analytics/subject).

function toggleAnalyticsCard(id){
  const el = document.getElementById(id);
  if(el) el.style.display = el.style.display==="none" ? "block" : "none";
}

function analyticsAccordionHTML(prefix, sections){
  return sections.map(s=>`
    <div class="section-card" style="margin-bottom:12px;padding:0;overflow:hidden">
      <div onclick="toggleAnalyticsCard('${prefix}-${s.key}')" style="cursor:pointer;padding:16px 20px;display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:700;color:var(--navy)">${s.title}</span>
        <span class="badge badge-blue">${s.count}</span>
      </div>
      <div id="${prefix}-${s.key}" style="display:none;padding:0 20px 16px 20px;border-top:1px solid var(--pale)">${s.bodyHtml}</div>
    </div>`).join("");
}

function drawTrendChart(canvasId, labels, values){
  const canvas = document.getElementById(canvasId);
  if(!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth || canvas.parentElement.offsetWidth || 500;
  const H = 240;
  canvas.width = W*dpr; canvas.height = H*dpr;
  canvas.style.width = W+"px"; canvas.style.height = H+"px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  const PAD = {top:20,right:20,bottom:70,left:44};
  const cW = W - PAD.left - PAD.right, cH = H - PAD.top - PAD.bottom;
  ctx.clearRect(0,0,W,H);

  const grid = [0,25,50,75,100];
  ctx.strokeStyle="#E3F2FD"; ctx.lineWidth=1; ctx.fillStyle="#546E7A"; ctx.font="11px Arial";
  grid.forEach(v=>{
    const y = PAD.top + cH - (v/100)*cH;
    ctx.beginPath(); ctx.moveTo(PAD.left,y); ctx.lineTo(PAD.left+cW,y); ctx.stroke();
    ctx.textAlign="right"; ctx.fillText(v, PAD.left-6, y+4);
  });

  if(!values.length){
    ctx.fillStyle="#546E7A"; ctx.textAlign="center"; ctx.font="13px Arial";
    ctx.fillText("Not enough data yet", PAD.left+cW/2, PAD.top+cH/2);
    return;
  }

  const step = values.length>1 ? cW/(values.length-1) : cW;
  ctx.fillStyle="#546E7A"; ctx.font="9px Arial";
  labels.forEach((lbl,i)=>{
    const x = PAD.left + (values.length>1 ? i*step : cW/2);
    const y = PAD.top+cH+14;
    ctx.save(); ctx.translate(x,y); ctx.rotate(-Math.PI/4);
    ctx.textAlign="right"; ctx.fillText(lbl,0,0); ctx.restore();
  });

  const pts = values.map((v,i)=> v!=null ? {x:PAD.left+(values.length>1?i*step:cW/2), y:PAD.top+cH-(v/100)*cH, v} : null);
  ctx.strokeStyle="#1565C0"; ctx.lineWidth=2.5; ctx.lineJoin="round"; ctx.lineCap="round";
  ctx.beginPath(); let first=true;
  pts.forEach(p=>{ if(!p) return; if(first){ctx.moveTo(p.x,p.y);first=false;} else ctx.lineTo(p.x,p.y); });
  ctx.stroke();
  pts.forEach(p=>{
    if(!p) return;
    ctx.beginPath(); ctx.arc(p.x,p.y,5,0,Math.PI*2);
    ctx.fillStyle="#1565C0"; ctx.fill(); ctx.strokeStyle="white"; ctx.lineWidth=2; ctx.stroke();
    ctx.fillStyle="#0A1628"; ctx.font="bold 11px Arial"; ctx.textAlign="center";
    ctx.fillText(p.v, p.x, p.y-10);
  });
}

function renderStudentRows(list, valKey, posKey){
  return list.map(r=>`
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--pale)">
      <span>${r.name}</span>
      <span>${r[valKey]} <span style="color:var(--muted);font-size:.8rem">(#${r[posKey]})</span></span>
    </div>`).join("");
}
function renderTrendRows(list){
  return list.map(r=>`
    <div style="padding:8px 0;border-bottom:1px solid var(--pale)">
      <strong>${r.name}</strong>
      <div style="font-size:.85rem;color:var(--muted)">${r.prev_value} → ${r.current_value} &nbsp;|&nbsp; Pos ${r.prev_position} → ${r.current_position}</div>
    </div>`).join("");
}

function renderOverviewAnalytics(prefix, d){
  drawTrendChart(prefix+"-chart", d.graph.map(g=>g.label), d.graph.map(g=>g.value));
  const lblEl = document.getElementById(prefix+"-current-label");
  if(lblEl) lblEl.textContent = d.current_label || "—";

  const sections = [];
  sections.push({key:"avg", title:"📊 Average", count: d.average!=null ? d.average+"%" : "—",
    bodyHtml:`<p style="padding:12px 0;color:var(--muted)">Current average: <strong>${d.average!=null?d.average:"—"}</strong></p>`});
  sections.push({key:"out", title:"🌟 Outstanding Performers", count:d.outstanding.length,
    bodyHtml: d.outstanding.length ? renderStudentRows(d.outstanding,"value","position")
      : `<p style="padding:12px 0;color:var(--muted)">No Outstanding Performers identified.</p>`});
  sections.push({key:"support", title:"📉 Students Needing Support", count:d.needs_support.length,
    bodyHtml: d.needs_support.length ? renderStudentRows(d.needs_support,"value","position")
      : `<p style="padding:12px 0;color:var(--muted)">No Students Needing Support identified.</p>`});
  sections.push({key:"improved", title:"📈 Improved Students", count:d.improved.length,
    bodyHtml: d.improved.length ? renderTrendRows(d.improved)
      : `<p style="padding:12px 0;color:var(--muted)">No improved students yet.</p>`});
  sections.push({key:"declining", title:"📉 Declining Students", count:d.declining.length,
    bodyHtml: d.declining.length ? renderTrendRows(d.declining)
      : `<p style="padding:12px 0;color:var(--muted)">No declining students.</p>`});
  if(d.best_subject !== undefined){
    sections.push({key:"best", title:"📚 Best Subject", count: d.best_subject ? cap(d.best_subject.subject) : "—",
      bodyHtml: d.best_subject ? `<p style="padding:12px 0">${cap(d.best_subject.subject)} — average <strong>${d.best_subject.average}</strong></p>` : `<p style="padding:12px 0;color:var(--muted)">No data</p>`});
    sections.push({key:"weak", title:"📚 Weakest Subject", count: d.weakest_subject ? cap(d.weakest_subject.subject) : "—",
      bodyHtml: d.weakest_subject ? `<p style="padding:12px 0">${cap(d.weakest_subject.subject)} — average <strong>${d.weakest_subject.average}</strong></p>` : `<p style="padding:12px 0;color:var(--muted)">No data</p>`});
  }
  sections.push({key:"risk", title:"⚠ Students At Risk", count:d.at_risk.length,
    bodyHtml: d.at_risk.length
      ? d.at_risk.map(r=>`<div style="padding:8px 0;border-bottom:1px solid var(--pale)"><strong>${r.name}</strong> — ${r.value}<div style="font-size:.78rem;color:var(--red)">${r.reason}</div></div>`).join("")
      : `<p style="padding:12px 0;color:var(--muted)">No students at risk.</p>`});

  const cardsEl = document.getElementById(prefix+"-cards");
  if(cardsEl) cardsEl.innerHTML = analyticsAccordionHTML(prefix, sections);
}

// ── ADMIN ANALYTICS ────────────────────────────────────────────
async function loadAdminAnalytics(){
  const classSel = document.getElementById("admin-an-class-sel");
  const streamSel = document.getElementById("admin-an-stream-sel");
  const prevVal = classSel.value;
  // Always rebuild the options — allClasses may have changed (new class added
  // in Config) since the last time this page was opened.
  classSel.innerHTML = `<option value="">Overall School</option>` +
    allClasses.map(c=>`<option value="${c.id}">${c.class_name}</option>`).join("");
  if([...classSel.options].some(o=>o.value===prevVal)) classSel.value = prevVal;
  if(!classSel._boundChange){
    classSel.addEventListener("change", onAdminAnalyticsClassChange);
    classSel._boundChange = true;
  }
  if(!streamSel._boundChange){
    // Previously nothing listened for stream changes, so picking a stream
    // never refreshed the graph/cards at all.
    streamSel.addEventListener("change", fetchAndRenderAdminAnalytics);
    streamSel._boundChange = true;
  }
  onAdminAnalyticsClassChange();
}
function onAdminAnalyticsClassChange(){
  const classId = document.getElementById("admin-an-class-sel").value;
  const streamSel = document.getElementById("admin-an-stream-sel");
  const c = classId ? getClassById(parseInt(classId)) : null;
  if(c && c.streams.length){
    streamSel.style.display="inline-block";
    streamSel.innerHTML = `<option value="">All Streams</option>` +
      c.streams.map(s=>`<option value="${s.id}">${s.stream_name}</option>`).join("");
  } else { streamSel.style.display="none"; streamSel.innerHTML=""; }
  fetchAndRenderAdminAnalytics();
}
async function fetchAndRenderAdminAnalytics(){
  if(!requireSub()) return;
  const classId  = document.getElementById("admin-an-class-sel").value;
  const streamId = document.getElementById("admin-an-stream-sel").value;
  let url = "/analytics/overview?role=admin";
  if(classId) url += "&class_id="+classId;
  if(streamId) url += "&stream_id="+streamId;
  const d = await api(url);
  if(!d.ok){ toast(d.error||"Failed to load analytics","error"); return; }
  renderOverviewAnalytics("admin-an", d);
}

// ── CLASS TEACHER ANALYTICS ────────────────────────────────────
async function loadCTAnalytics(){
  if(!requireSub()) return;
  const d = await api(`/analytics/overview?role=teacher&username=${encodeURIComponent(currentUser.username)}`);
  if(!d.ok){
    const el = document.getElementById("ct-an-cards");
    if(el) el.innerHTML = `<p style="color:var(--red)">${d.error}</p>`;
    return;
  }
  renderOverviewAnalytics("ct-an", d);
}

// ── SUBJECT TEACHER ANALYTICS ──────────────────────────────────
async function loadTeacherAnalytics(){
  const teachers = await api("/teachers");
  const me = teachers.find(t=>t.username===currentUser.username);
  teacherAssignments = me ? me.assignments : [];
  const sel = document.getElementById("teacher-an-assign-sel");
  if(!teacherAssignments.length){
    sel.innerHTML = "";
    const cardsEl = document.getElementById("teacher-an-cards");
    if(cardsEl) cardsEl.innerHTML = `<p style="color:var(--muted)">No subject assignments yet.</p>`;
    return;
  }
  sel.innerHTML = teacherAssignments.map((a,i)=>
    `<option value="${i}">${cap(a.subject)} — ${a.class_name}${a.stream_name?" "+a.stream_name:""}</option>`).join("");
  sel.onchange = fetchAndRenderTeacherAnalytics;
  fetchAndRenderTeacherAnalytics();
}
async function fetchAndRenderTeacherAnalytics(){
  if(!requireSub()) return;
  const idx = document.getElementById("teacher-an-assign-sel").value;
  const a = teacherAssignments[idx];
  if(!a) return;
  let url = `/analytics/subject?role=teacher&username=${encodeURIComponent(currentUser.username)}&subject=${encodeURIComponent(a.subject)}&class_id=${a.class_id}`;
  if(a.stream_id) url += "&stream_id="+a.stream_id;
  const d = await api(url);
  if(!d.ok){ toast(d.error||"Failed to load analytics","error"); return; }
  renderOverviewAnalytics("teacher-an", d);
}