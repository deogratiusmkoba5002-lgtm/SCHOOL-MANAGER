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

  await Promise.all([configLoadClasses(), configLoadSubjects(), configLoadGrades(), configLoadRegCode(), loadSubscriptionCard()]);
  await loadGradingSystemCard();
}



// ── SCHOOL REGISTRATION CODE (used alongside username/password to log in) ──
async function configLoadRegCode(){
  const r = await api("/config/reg_code");
  const el = document.getElementById("config-reg-code");
  if(el) el.value = r.reg_code || "";
}

let _subPlansCache = null;
let _subPaymentInfoCache = null;
async function configSaveRegCode(){
  const el = document.getElementById("config-reg-code");
  if(!el) return;
  const val = el.value.trim();
  if(!val){ toast("Enter a registration code","error"); return; }
  const btn = document.getElementById("config-reg-code-save-btn");
  if(btn) btn.disabled = true;
  try{
    const r = await api("/config/reg_code","POST",{reg_code:val});
    if(r.ok){toast("Registration code saved!","success"); el.value = r.reg_code;}
    else toast(r.error||"Failed to save registration code","error");
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function loadSubscriptionCard(){
  const s = await api("/subscription/status");
  const statusEl = document.getElementById("sub-status-display");
  const plansEl  = document.getElementById("sub-plans-area");
  if(!s.ok){ statusEl.textContent = "Could not load subscription status."; return; }
  _subPlansCache = s.plans;
  _subPaymentInfoCache = s.payment_info;

  if(s.exempt){
    statusEl.innerHTML = `<span style="color:var(--green);font-weight:600">✓ Demo / grandfathered school — all features unlocked.</span>`;
    plansEl.innerHTML = "";
    return;
  }

  if(s.pending_request){
    const r = s.pending_request;
    statusEl.innerHTML = `
      <div style="color:var(--orange);font-weight:700;margin-bottom:6px">🟡 Pending Verification</div>
      <div style="font-size:.85rem;margin-bottom:10px">Your payment has been received for verification. This is normally completed within business hours — your subscription activates automatically once approved.</div>
      <div style="background:white;border-radius:8px;padding:10px;font-size:.8rem;color:var(--muted);display:grid;gap:4px">
        <div><strong>Plan:</strong> ${cap(r.plan)}</div>
        <div><strong>Transaction ID:</strong> ${escHtml(r.transaction_id)}</div>
        <div><strong>Amount Paid:</strong> ${r.claimed_amount}</div>
        <div><strong>Phone Used:</strong> ${escHtml(r.phone_used)}</div>
        <div><strong>Payment Date:</strong> ${r.payment_date}</div>
        <div><strong>Submitted:</strong> ${r.submitted_at ? r.submitted_at.slice(0,16).replace("T"," ") : ""}</div>
      </div>
      <button class="btn btn-outline btn-sm" style="margin-top:10px" onclick="cancelPaymentRequest()">Cancel This Request</button>`;
    plansEl.innerHTML = "";
    return;
  }

  if(s.last_decision && s.last_decision.status==="expired"){
    statusEl.innerHTML = `<span style="color:var(--orange);font-weight:600">🟠 Expired (Awaiting Resubmission)</span>
      <div style="color:var(--muted);margin-top:4px;font-size:.85rem">${escHtml(s.last_decision.note)}</div>`;
  } 

  else if (s.active){
    statusEl.innerHTML = `<span style="color:var(--green);font-weight:600">✓ Active — ${cap(s.plan||"")} plan</span>
      <div style="color:var(--muted);margin-top:4px">Expires: ${new Date(s.expires_at).toLocaleDateString()}</div>`;
  } else if(s.last_decision && s.last_decision.status==="rejected"){
    statusEl.innerHTML = `<span style="color:var(--red);font-weight:600">✗ Your last payment request was rejected</span>
      <div style="color:var(--muted);margin-top:4px">Reason: ${escHtml(s.last_decision.note||"—")}</div>
      <div style="color:var(--muted);margin-top:4px">You can submit a new request below.</div>`;
  } else {
    statusEl.innerHTML = `<span style="color:var(--red);font-weight:600">🔒 No active subscription — analytics, PDFs, announcements and results publishing are locked.</span>`;
  }

  plansEl.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:14px">
      ${Object.entries(s.plans).map(([key,p])=>`
        <div style="border:1.5px solid var(--border);border-radius:10px;padding:16px">
          <div style="font-weight:700;color:var(--navy);margin-bottom:4px">${cap(key)}</div>
          <div style="font-size:.85rem;color:var(--muted);margin-bottom:8px">${p.label}</div>
          ${p.features?`<ul style="font-size:.78rem;color:var(--muted);margin:0 0 12px 16px;padding:0">${p.features.map(f=>`<li>${f}</li>`).join("")}</ul>`:""}
          <button class="btn btn-blue btn-sm" style="width:100%" onclick="${key==='free'?'selectFreePlan()':`openPaymentInstructions('${key}')`}">${key==='free'?'Use Free Plan':'Subscribe'}</button>
        </div>`).join("")}
    </div>
    <div id="sub-payment-flow"></div>`;
}

// ── GRADING SYSTEM (O-Level/A-Level, School/NECTA divisions) ──────
async function loadGradingSystemCard(){
  const s = await api("/config/grading_system");
  const levelSel  = document.getElementById("gs-level");
  const sourceSel = document.getElementById("gs-source");
  if(!levelSel || !sourceSel) return;
  levelSel.value  = s.grading_system  || "o_level";
  sourceSel.value = s.division_source || "school";

  // Populate principal-subjects multi-select from configSubjects (already
  // loaded by configLoadSubjects earlier in the same Promise.all)
  const principalSel = document.getElementById("gs-principal-subjects");
  if(principalSel){
    principalSel.innerHTML = configSubjects.map(sub=>{
      const selected = (s.principal_subjects||[]).includes((sub.name||"").toLowerCase().trim());
      return `<option value="${escHtml(sub.name)}" ${selected?"selected":""}>${cap(sub.name)}</option>`;
    }).join("");
  }
  const noncreditSel = document.getElementById("gs-noncredit-subjects");
  if(noncreditSel){
    noncreditSel.innerHTML = configSubjects.map(sub=>{
      const selected = (s.non_credit_subjects||[]).includes((sub.name||"").toLowerCase().trim());
      return `<option value="${escHtml(sub.name)}" ${selected?"selected":""}>${cap(sub.name)}</option>`;
    }).join("");
  }
  onGradingLevelChange();
}

function onGradingLevelChange(){
  const level = document.getElementById("gs-level").value;
  const wrap  = document.getElementById("gs-principal-wrap");
  if(wrap) wrap.style.display = level==="a_level" ? "block" : "none";
}

async function saveGradingSystem(){
  const grading_system  = document.getElementById("gs-level").value;
  const division_source = document.getElementById("gs-source").value;
  let principal_subjects = [];
  if(grading_system === "a_level"){
    const sel = document.getElementById("gs-principal-subjects");
    principal_subjects = [...sel.selectedOptions].map(o=>o.value.toLowerCase().trim());
    if(!principal_subjects.length){
      toast("Select at least one principal subject for A-Level","error");
      return;
    }
  }
  const noncreditSel = document.getElementById("gs-noncredit-subjects");
  const non_credit_subjects = noncreditSel ? [...noncreditSel.selectedOptions].map(o=>o.value.toLowerCase().trim()) : [];
  const btn = document.getElementById("gs-save-btn");
  if(btn) btn.disabled = true;
  try{
    const r = await api("/config/grading_system","POST",{grading_system,division_source,principal_subjects,non_credit_subjects});
    if(r.ok) toast("Grading system saved!","success");
    else toast(r.error||"Failed to save grading system","error");
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function selectFreePlan(){
  if(!confirm("Switch to the Free plan?")) return;
  const r = await api("/subscription/select_free","POST",{});
  if(r.ok){ toast("Free plan activated","success"); window.subActive = true; loadSubscriptionCard(); }
  else toast(r.error||"Failed","error");
}

function openPaymentInstructions(planKey){
  const plan = _subPlansCache[planKey];
  const pay  = _subPaymentInfoCache;
  const flow = document.getElementById("sub-payment-flow");
  if(!plan || !pay){ toast("Could not load payment details","error"); return; }
  flow.innerHTML = `
    <div class="section-card" style="background:var(--pale);margin-top:8px">
      <div style="font-weight:700;color:var(--navy);margin-bottom:10px">Step 1 — Pay via Mobile Money</div>
      <div style="background:white;border-radius:8px;padding:14px;font-size:.9rem;display:grid;gap:6px;margin-bottom:14px">
        <div><strong>Pay To:</strong> ${escHtml(pay.business_name)}</div>
        <div><strong>Payment Number:</strong> ${escHtml(pay.payment_number)}</div>
        <div><strong>Supported Networks:</strong> ${pay.networks.map(escHtml).join(", ")}</div>
        <div><strong>Amount:</strong> ${plan.amount.toLocaleString()} TZS</div>
      </div>
      <div style="background:#FFF8E1;border-left:3px solid #FFD600;border-radius:8px;padding:10px 12px;font-size:.8rem;color:#5D4037;margin-bottom:16px">
        ⚠ Use the exact amount shown. Keep the transaction message for verification.
      </div>
      <div style="font-weight:700;color:var(--navy);margin-bottom:10px">Step 2 — Submit Payment Details</div>
      <div class="form-grid">
        <div class="form-group"><label class="form-label">Transaction ID</label><input class="form-input" id="pr-txn-id" placeholder="e.g. QWE123XYZ"/></div>
        <div class="form-group"><label class="form-label">Phone Number Used</label><input class="form-input" id="pr-phone" placeholder="e.g. 0712345678"/></div>
        <div class="form-group"><label class="form-label">Amount Paid</label><input class="form-input" type="number" id="pr-amount" value="${plan.amount}"/></div>
        <div class="form-group"><label class="form-label">Payment Date</label><input class="form-input" type="date" id="pr-date" value="${new Date().toISOString().slice(0,10)}"/></div>
        <div class="form-group full"><label class="form-label">Note (optional)</label><input class="form-input" id="pr-note" placeholder="Anything else we should know"/></div>
      </div>
      <button class="btn btn-blue" style="margin-top:14px" onclick="submitPaymentRequest('${planKey}')">Submit Payment</button>
    </div>`;
  flow.scrollIntoView({behavior:"smooth", block:"center"});
}

async function submitPaymentRequest(planKey){
  const transaction_id = (document.getElementById("pr-txn-id").value||"").trim();
  const phone_used     = (document.getElementById("pr-phone").value||"").trim();
  const claimed_amount = document.getElementById("pr-amount").value;
  const payment_date   = document.getElementById("pr-date").value;
  const note           = (document.getElementById("pr-note").value||"").trim();
  if(!transaction_id){ toast("Enter the transaction ID","error"); return; }
  if(!phone_used){ toast("Enter the phone number used","error"); return; }
  if(!claimed_amount || parseFloat(claimed_amount)<=0){ toast("Enter the amount paid","error"); return; }
  if(!payment_date){ toast("Enter the payment date","error"); return; }
  const r = await api("/subscription/request","POST",{plan:planKey,transaction_id,phone_used,claimed_amount:parseFloat(claimed_amount),payment_date,note,username:currentUser.username});
  if(r.ok){ toast("Payment submitted for verification!","success"); loadSubscriptionCard(); }
  else toast(r.error||"Failed to submit payment","error");
}

async function cancelPaymentRequest(){
  if(!confirm("Are you sure?\n\nThis does not cancel your payment. It only removes this verification request. You can submit a new one afterward.")) return;
  const r = await api("/subscription/request/cancel","POST",{});
  if(r.ok){ toast("Request cancelled","success"); loadSubscriptionCard(); }
  else toast(r.error||"Failed","error");
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
