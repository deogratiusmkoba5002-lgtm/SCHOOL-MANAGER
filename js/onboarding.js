// ── ONBOARDING TOUR (first-time admin guidance) ─────────────────
// Server-tracked via school_config.onboarding_complete — survives logout,
// device changes, cleared browser storage. Not our problem if the admin
// still ignores it; we can guide the horse to water.
window.onboardingActive = false;

let _dd_onb_hole = null, _dd_onb_tip = null, _dd_onb_resizeHandler = null;

function _dd_onb_unionRect(els){
  const rects = els.filter(Boolean).map(e=>e.getBoundingClientRect());
  if(!rects.length) return null;
  const top = Math.min(...rects.map(r=>r.top));
  const left = Math.min(...rects.map(r=>r.left));
  const right = Math.max(...rects.map(r=>r.right));
  const bottom = Math.max(...rects.map(r=>r.bottom));
  return {top, left, right, bottom, width: right-left, height: bottom-top};
}

function _dd_onb_buildDom(){
  if(_dd_onb_hole) return;
  _dd_onb_hole = document.createElement("div");
  _dd_onb_hole.id = "dd-onb-hole";
  _dd_onb_hole.style.cssText = `
    position:fixed; z-index:9990; pointer-events:none;
    border-radius:12px; box-shadow:0 0 0 9999px rgba(6,10,20,.78);
    outline:3px solid #00E5FF; outline-offset:4px;
    transition: top .35s ease, left .35s ease, width .35s ease, height .35s ease;
  `;
  document.body.appendChild(_dd_onb_hole);

  _dd_onb_tip = document.createElement("div");
  _dd_onb_tip.id = "dd-onb-tip";
  _dd_onb_tip.style.cssText = `
    position:fixed; z-index:9995; pointer-events:auto;
    background:#fff; border-radius:14px; padding:18px 20px; max-width:290px;
    box-shadow:0 16px 48px rgba(0,0,0,.4); font-family:'DM Sans',sans-serif;
    transition: top .35s ease, left .35s ease;
  `;
  document.body.appendChild(_dd_onb_tip);
}

function _dd_onb_position(targetEls, placement){
  const rect = _dd_onb_unionRect(targetEls);
  if(!rect || !_dd_onb_hole) return;
  const pad = 8;
  _dd_onb_hole.style.top    = (rect.top - pad) + "px";
  _dd_onb_hole.style.left   = (rect.left - pad) + "px";
  _dd_onb_hole.style.width  = (rect.width + pad*2) + "px";
  _dd_onb_hole.style.height = (rect.height + pad*2) + "px";

  const tipW = 290;
  const left = Math.min(Math.max(rect.left, 12), window.innerWidth - tipW - 12);
  const top  = placement === "below" ? rect.bottom + 20 : Math.max(rect.top - 190, 12);
  _dd_onb_tip.style.top  = top + "px";
  _dd_onb_tip.style.left = left + "px";
}

function _dd_onb_teardown(){
  if(_dd_onb_hole){ _dd_onb_hole.remove(); _dd_onb_hole = null; }
  if(_dd_onb_tip){ _dd_onb_tip.remove(); _dd_onb_tip = null; }
  if(_dd_onb_resizeHandler){
    window.removeEventListener("resize", _dd_onb_resizeHandler);
    window.removeEventListener("scroll", _dd_onb_resizeHandler, true);
    _dd_onb_resizeHandler = null;
  }
  window.onboardingActive = false;
}

async function _dd_onb_markComplete(){
  try { await api("/config/onboarding_complete","POST",{}); } catch(e){ /* best-effort */ }
  config.onboarding_complete = true;
}

function startOnboarding(){
  window.onboardingActive = true;
  _dd_onb_buildDom();

  const showStudentsStep = ()=>{
    const addBtn    = document.getElementById("btn-add-student");
    const importBtn = document.getElementById("btn-import-excel");
    if(!addBtn){ setTimeout(showStudentsStep, 150); return; } // page still rendering
    const targets = [addBtn, importBtn];

    _dd_onb_tip.innerHTML = `
      <div style="font-weight:800;color:var(--navy);font-size:1rem;margin-bottom:8px;font-family:'Syne',sans-serif">
        👋 Welcome. Let's add your first student.
      </div>
      <div style="font-size:.85rem;color:var(--muted);line-height:1.5;margin-bottom:14px">
        Add one student manually with <strong>Add Student</strong>, or bring in a whole class at once
        with <strong>Import Excel</strong>. Either one moves you forward.
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
        <a href="javascript:void(0)" onclick="skipOnboarding()" style="font-size:.78rem;color:var(--muted);text-decoration:underline">Skip setup guide</a>
        <span style="font-size:.72rem;color:var(--blue);font-weight:700">Step 1 of 1</span>
      </div>`;

    _dd_onb_position(targets, "below");
    _dd_onb_resizeHandler = ()=>_dd_onb_position(targets, "below");
    window.addEventListener("resize", _dd_onb_resizeHandler);
    window.addEventListener("scroll", _dd_onb_resizeHandler, true);
  };
  setTimeout(showStudentsStep, 250);
}

function skipOnboarding(){
  _dd_onb_teardown();
  _dd_onb_markComplete();
  toast("Setup guide dismissed — you can add students anytime.","info");
}

function onboardingStudentAdded(){
  if(!window.onboardingActive) return;
  _dd_onb_teardown();
  _dd_onb_markComplete();
  _dd_onb_showCongrats();
}

function _dd_onb_showCongrats(){
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.style.zIndex = 9999;
  backdrop.innerHTML = `
    <div class="modal" style="text-align:center">
      <div style="font-size:2.4rem;margin-bottom:6px">🎉</div>
      <div class="modal-title">Nice work.</div>
      <p style="font-size:.9rem;color:var(--muted);margin-bottom:20px;line-height:1.6">
        Your first student is in the system. Next: head to <strong>Teachers</strong> to create teacher
        accounts and assign them to subjects and classes — that's what actually unlocks marks entry.
      </p>
      <div style="display:flex;gap:10px;justify-content:center">
        <button class="btn btn-outline" id="dd-onb-later-btn">I'll do it later</button>
        <button class="btn btn-blue" id="dd-onb-teachers-btn">Go to Teachers →</button>
      </div>
    </div>`;
  document.body.appendChild(backdrop);
  backdrop.querySelector("#dd-onb-later-btn").addEventListener("click", ()=>backdrop.remove());
  backdrop.querySelector("#dd-onb-teachers-btn").addEventListener("click", ()=>{
    backdrop.remove();
    showPage("teachers");
  });
}