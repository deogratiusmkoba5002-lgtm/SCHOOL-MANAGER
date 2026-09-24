// ── PARENT ACCESS (per-student paid entitlement) ─────────────
const _accessCtx = {};
let _accessPollTimer = null;

function fmtTZS(n){ return Number(n).toLocaleString("en-US") + " TZS"; }
function fmtDate(iso){ return iso ? new Date(iso).toLocaleDateString(undefined,{day:"numeric",month:"long",year:"numeric"}) : "—"; }

async function loadParentAccess(){
  window.parentAccess = null;
  if(!currentUser || currentUser.role!=="parent") return null;
  const r = await api("/access/status");
  window.parentAccess = r.ok ? r : {active:false, plans:[]};
  return window.parentAccess;
}

async function loadParentSubscription(){
  const body = document.getElementById("parent-subscription-body");
  body.innerHTML = `<div class="spinner"></div>`;
  const st = await api("/access/status");
  if(!st.ok){ body.innerHTML = `<div class="section-card"><p style="color:var(--red)">${escHtml(st.error||"Could not load subscription")}</p></div>`; return; }
  window.parentAccess = st;
  renderAccessPanel(body, st, "psub", {
    studentId:null, canPay:true, showHistory:true,
    onChange: async()=>{ await loadParentAccess(); loadParentSubscription(); }
  });
}

// Shared by the parent Subscription page and the admin "activate for this student" modal.
function renderAccessPanel(container, st, uid, ctx){
  _accessCtx[uid] = ctx;
  const statusBox = st.active
    ? `<div style="background:#E8F5E9;border-left:4px solid var(--green);border-radius:10px;padding:16px;margin-bottom:16px">
         <div style="font-weight:700;color:#2E7D32;font-size:1.05rem">✅ Access active — ${escHtml(st.plan_label||"")}</div>
         <div style="margin-top:6px;font-size:.9rem">Expires on <strong>${fmtDate(st.expires_at)}</strong></div>
         <div style="margin-top:4px;font-size:.9rem"><strong>${st.days_left}</strong> day${st.days_left===1?"":"s"} left</div>
       </div>`
    : `<div style="background:#FFF8E1;border-left:4px solid #FFB300;border-radius:10px;padding:16px;margin-bottom:16px">
         <div style="font-weight:700;color:#5D4037">🔒 No active access</div>
         <div style="margin-top:6px;font-size:.85rem;color:#5D4037">${st.expires_at ? "Previous access expired on <strong>"+fmtDate(st.expires_at)+"</strong>. " : ""}Unlocks full results history, detailed analytics and report-card PDFs.</div>
       </div>`;

  const planBtns = (st.plans||[]).map(p=>`
    <button class="btn btn-blue" style="flex:1;min-width:160px;justify-content:center;flex-direction:column;padding:16px 12px;gap:2px"
            onclick="payAccessPlan('${uid}','${p.key}')">
      <span style="font-size:.95rem">${escHtml(p.label)} - ${fmtTZS(p.amount)}</span>
      ${st.active ? `<span style="font-size:.7rem;opacity:.85;font-weight:500">Adds to current expiry</span>` : ""}
    </button>`).join("");

  const payBlock = ctx.canPay ? `
    <div class="section-card" style="margin-bottom:16px">
      <div class="section-card-title">${st.active ? "Extend access" : "Choose a plan"}</div>
      <div class="form-group" style="margin-bottom:14px">
        <label class="form-label">Mobile-money number that will pay</label>
        <input type="tel" class="form-input" id="${uid}-phone" placeholder="e.g. 0712345678"/>
        <p style="font-size:.72rem;color:var(--muted);margin-top:4px">A payment prompt is sent to this phone. Any mobile-money phone works — no smartphone needed.</p>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap" id="${uid}-plans">${planBtns}</div>
      <div id="${uid}-status" style="margin-top:14px;font-size:.88rem"></div>
    </div>`
    : `<p style="color:var(--muted);font-size:.85rem;margin-bottom:14px">Only the school admin can activate access for a student.</p>`;

  const hist = (ctx.showHistory && st.history && st.history.length) ? `
    <div class="table-card"><div class="table-toolbar"><span class="table-toolbar-title">Payment history</span></div>
    <div class="table-wrap"><table><thead><tr><th>Date</th><th>Plan</th><th>Amount</th><th>Status</th><th>Expires</th></tr></thead><tbody>
      ${st.history.map(h=>`<tr>
        <td>${fmtDate(h.paid_at||h.created_at)}</td>
        <td>${escHtml(h.plan==="6m"?"6 Months":h.plan==="12m"?"12 Months":h.plan)}</td>
        <td>${fmtTZS(h.amount)}</td>
        <td><span class="badge ${h.status==="completed"?"badge-green":h.status==="pending"?"badge-orange":"badge-red"}">${escHtml(h.status)}</span></td>
        <td>${h.status==="completed"?fmtDate(h.expires_at):"—"}</td></tr>`).join("")}
    </tbody></table></div></div>` : "";

  container.innerHTML = statusBox + payBlock + hist;
  if(ctx.canPay && st.pending){
    pollAccessPayment(st.pending.id, document.getElementById(uid+"-status"), ctx.onChange);
  }
}

async function payAccessPlan(uid, planKey){
  const ctx = _accessCtx[uid];
  const phone = document.getElementById(uid+"-phone").value.trim();
  if(!phone){ toast("Enter the mobile-money number that will pay","error"); return; }
  const statusEl = document.getElementById(uid+"-status");
  const btns = document.querySelectorAll(`#${uid}-plans button`);
  btns.forEach(b=>b.disabled=true);
  const body = {plan:planKey, phone};
  if(ctx.studentId) body.student_id = ctx.studentId;
  const r = await api("/access/pay","POST",body);
  if(!r.ok){
    toast(r.error||"Could not start payment","error");
    btns.forEach(b=>b.disabled=false);
    return;
  }
  toast("Payment prompt sent — approve it on the phone","success");
  pollAccessPayment(r.payment_id, statusEl, ()=>{ btns.forEach(b=>b.disabled=false); ctx.onChange && ctx.onChange(); });
}

function pollAccessPayment(paymentId, statusEl, onDone){
  clearInterval(_accessPollTimer);
  let tries = 0;
  if(statusEl) statusEl.innerHTML = `⏳ Waiting for approval on the phone… <button class="btn btn-outline btn-sm" style="margin-left:8px" onclick="pollAccessPayment(${paymentId}, this.parentElement, null)">Check now</button>`;
  const tick = async()=>{
    tries++;
    const r = await api(`/access/check/${paymentId}`,"POST",{});
    if(!r.ok) return;
    if(r.status==="completed"){
      clearInterval(_accessPollTimer);
      toast("Payment confirmed — access activated!","success");
      onDone && onDone(r);
    } else if(["failed","voided","expired","amount_mismatch"].includes(r.status)){
      clearInterval(_accessPollTimer);
      toast(r.status==="amount_mismatch" ? "Payment amount didn't match — contact support" : "Payment "+r.status+". You can try again.","error");
      onDone && onDone(r);
    } else if(tries>=36){
      clearInterval(_accessPollTimer);
      if(statusEl) statusEl.innerHTML = "Still waiting. If you approved it, reopen this page in a minute — access will activate automatically.";
    }
  };
  _accessPollTimer = setInterval(tick, 5000);
  tick();
}

// ── Admin: activate access for one student (parents without smartphones) ──
async function openAccessModal(studentId){
  const body = document.getElementById("access-modal-body");
  body.innerHTML = `<div class="spinner"></div>`;
  openModal("modal-access");
  const st = await api(`/access/status?student_id=${studentId}`);
  if(!st.ok){ body.innerHTML = `<p style="color:var(--red)">${escHtml(st.error||"Failed")}</p>`; return; }
  body.innerHTML = `<p style="font-size:.9rem;color:var(--muted);margin-bottom:14px">Student: <strong style="color:var(--navy)">${escHtml(st.student_name)}</strong></p><div id="access-modal-panel"></div>`;
  renderAccessPanel(document.getElementById("access-modal-panel"), st, "amod", {
    studentId, canPay: currentUser.role==="admin", showHistory:true,
    onChange: ()=>{
      openAccessModal(studentId);
      if(typeof loadStudents==="function") loadStudents();
      if(currentPageId==="reports") viewReport(studentId);
    }
  });
}
function closeAccessModal(){ clearInterval(_accessPollTimer); closeModal("modal-access"); }