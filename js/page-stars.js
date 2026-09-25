// ── STAR SYSTEM (admin) ─────────────────────────────────────
function _starIdemKey(){
  return (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
    : "wd-"+Date.now()+"-"+Math.random().toString(36).slice(2);
}

async function loadStarSystemPage(){
  const el = document.getElementById("star-system-body");
  if(!el) return;
  el.innerHTML = `<div class="spinner"></div>`;
  const d = await api("/stars/dashboard");
  if(!d.ok){ el.innerHTML = `<p style="color:var(--red)">Could not load Star System data.</p>`; return; }
  const p = d.cycle_progress;
  const pct = p && p.required ? Math.min(100, Math.round((p.qualifying_parent_count/p.required)*100)) : 0;
  const payout = d.payout_account;
  el.innerHTML = `
    <div class="section-card" style="margin-bottom:20px" id="star-notif-card">
      <div class="section-card-title" style="justify-content:space-between;display:flex;align-items:center">
        <span>🔔 Notifications ${d.unread_notifications>0?`<span class="badge badge-orange">${d.unread_notifications} new</span>`:""}</span>
        ${d.unread_notifications>0?`<button class="btn btn-outline btn-sm" onclick="markAllStarNotifsRead()">Mark all read</button>`:""}
      </div>
      <div id="star-notif-list"><div class="spinner" style="margin:20px auto"></div></div>
    </div>
    <div class="stats-grid" style="margin-bottom:20px">
      <div class="stat-card" style="border-color:var(--gold)">
        <div class="stat-icon" style="background:#FFF8E1">⭐</div>
        <div><div class="stat-val" style="color:var(--orange)">${d.balance.stars}</div><div class="stat-label">Stars (Available)</div></div>
      </div>
      <div class="stat-card" style="border-color:var(--green)">
        <div class="stat-icon" style="background:#E8F5E9">💰</div>
        <div><div class="stat-val" style="color:var(--green)">${d.balance.amount.toLocaleString()}</div><div class="stat-label">TZS Available</div></div>
      </div>
    </div>
    <div class="section-card" style="margin-bottom:20px">
      <div class="section-card-title">Next Star</div>
      ${p ? `
        <div style="font-size:.9rem;margin-bottom:8px">${p.qualifying_parent_count} / ${p.required} parents</div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
        <div style="font-size:.82rem;color:var(--muted);margin-top:8px">${p.remaining} more qualifying parent(s) needed</div>
      ` : `<p style="color:var(--muted);font-size:.85rem">No active cycle yet — complete registration, add students, teachers and publish results to start one.</p>`}
    </div>
    <div class="section-card" style="margin-bottom:20px">
      <div class="section-card-title">Your Referral Link</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <input class="form-input" id="star-referral-link" readonly value="${escHtml(d.referral_link)}" style="flex:1;min-width:220px">
        <button class="btn btn-outline btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('star-referral-link').value);toast('Copied!','success')">Copy</button>
      </div>
      <p style="font-size:.8rem;color:var(--muted);margin-top:10px">Share this link with other schools. When a school you refer becomes fully active, you earn a bonus Star.</p>
      <div style="margin-top:14px;font-size:.85rem;color:var(--muted)">
        Schools Referred: <strong>${d.referral_stats.schools_referred}</strong> &nbsp;|&nbsp;
        Successful Referrals: <strong>${d.referral_stats.successful_referrals}</strong>
      </div>
    </div>
    <div class="section-card" style="margin-bottom:20px">
      <div class="section-card-title">Payout Mobile-Money Number</div>
      ${payout ? `
        <div style="font-size:.88rem;margin-bottom:10px">Current: <strong>${escHtml(payout.account_identifier)}</strong>
          ${payout.verified ? '<span class="badge badge-green" style="margin-left:8px">Verified</span>' : '<span class="badge badge-orange" style="margin-left:8px">Unverified</span>'}
        </div>` : `<p style="font-size:.85rem;color:var(--muted);margin-bottom:10px">No payout number on file yet — add one before requesting a withdrawal.</p>`}
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <input class="form-input" id="star-payout-phone" placeholder="e.g. 0712345678" style="flex:1;min-width:200px">
        <button class="btn btn-outline btn-sm" onclick="savePayoutAccount()">${payout ? "Update Number" : "Save Number"}</button>
      </div>
    </div>
    <div class="section-card" style="margin-bottom:20px">
      <div class="section-card-title">Request Withdrawal</div>
      <p style="font-size:.8rem;color:var(--muted);margin-bottom:12px">Withdrawals are reviewed and paid out manually for now. Requesting reserves the stars from your available balance immediately.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <input class="form-input" type="number" min="1" id="star-withdraw-amount" placeholder="Stars to withdraw" style="flex:1;min-width:160px">
        <button class="btn btn-blue btn-sm" id="star-withdraw-btn" onclick="requestStarWithdrawal()">Request Withdrawal</button>
      </div>
    </div>
    <div class="table-card">
      <div class="table-toolbar"><span class="table-toolbar-title">Reward &amp; Withdrawal History</span></div>
      <div id="star-history-body" style="padding:16px"><div class="spinner"></div></div>
    </div>`;
  loadStarHistory();
  loadStarNotifList();
}

async function loadStarNotifList(){
  const el = document.getElementById("star-notif-list");
  if(!el) return;
  const d = await api("/stars/notifications");
  if(!d.ok || !d.notifications.length){
    el.innerHTML = `<p style="color:var(--muted);font-size:.85rem;padding:8px 0">No notifications yet.</p>`;
    return;
  }
  el.innerHTML = d.notifications.map(n=>`
    <div style="padding:10px 0;border-bottom:1px solid var(--pale);${n.is_read?'opacity:.65':''}">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
        <div style="font-weight:600;font-size:.88rem">${!n.is_read?'<span style="color:var(--blue)">●</span> ':''}${escHtml(n.title)}</div>
        <div style="font-size:.72rem;color:var(--muted);white-space:nowrap">${(n.created_at||"").slice(0,16).replace("T"," ")}</div>
      </div>
      <div style="font-size:.82rem;color:var(--muted);margin-top:3px">${escHtml(n.body)}</div>
      ${!n.is_read?`<button class="btn btn-outline btn-sm" style="margin-top:6px;padding:3px 10px;font-size:.72rem" onclick="markStarNotifRead(${n.id})">Mark read</button>`:""}
    </div>`).join("");
}
async function markStarNotifRead(id){
  await api(`/stars/notifications/${id}/read`,"POST",{});
  loadStarSystemPage();
  refreshStarNotifBadge();
}
async function markAllStarNotifsRead(){
  await api("/stars/notifications/read_all","POST",{});
  loadStarSystemPage();
  refreshStarNotifBadge();
}

async function savePayoutAccount(){
  const val = document.getElementById("star-payout-phone").value.trim();
  if(!val){ toast("Enter a mobile-money number","error"); return; }
  const r = await api("/stars/payout_account","POST",{account_identifier:val});
  if(r.ok){ toast("Payout number saved","success"); loadStarSystemPage(); }
  else toast(r.error||"Failed","error");
}

async function requestStarWithdrawal(){
  const stars = document.getElementById("star-withdraw-amount").value;
  if(!stars || parseInt(stars) < 1){ toast("Enter how many stars to withdraw","error"); return; }
  const btn = document.getElementById("star-withdraw-btn");
  btn.disabled = true; btn.textContent = "Requesting...";
  const r = await api("/stars/withdraw","POST",{stars:parseInt(stars), idempotency_key:_starIdemKey()});
  btn.disabled = false; btn.textContent = "Request Withdrawal";
  if(r.ok){
    toast(r.already_existed ? "Request already submitted" : "Withdrawal requested — pending review","success");
    loadStarSystemPage();
  } else toast(r.error||"Failed","error");
}

async function loadStarHistory(){
  const el = document.getElementById("star-history-body");
  if(!el) return;
  const d = await api("/stars/history");
  if(!d.ok || !d.history.length){ el.innerHTML = `<p style="color:var(--muted);font-size:.85rem">No reward activity yet.</p>`; return; }
  el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Stars</th><th>Amount</th><th>Status</th></tr></thead><tbody>
    ${d.history.map(h=>`<tr>
      <td style="font-size:.8rem;color:var(--muted)">${(h.created_at||"").slice(0,16).replace("T"," ")}</td>
      <td>${cap((h.type||"").toLowerCase().replace(/_/g," "))}</td>
      <td style="font-weight:600">${h.type==="WITHDRAWAL"?"-":"+"}${h.stars}</td>
      <td>${h.amount.toLocaleString()} TZS</td>
      <td><span class="badge ${h.status==='AVAILABLE'||h.status==='WITHDRAWN'?'badge-green':h.status==='REVERSED'?'badge-red':'badge-grey'}">${h.status}</span></td>
    </tr>`).join("")}
  </tbody></table></div>`;
}

// ── Sidebar badge, shown without opening the page ─────────────
async function refreshStarNotifBadge(){
  if(!currentUser || currentUser.role!=="admin") return;
  const d = await api("/stars/dashboard");
  const navItem = document.querySelector('.nav-item[data-page="star-system"]');
  if(!navItem || !d.ok) return;
  const existing = navItem.querySelector(".star-notif-dot");
  const count = d.unread_notifications || 0;
  if(count>0 && !existing){
    const dot = document.createElement("span");
    dot.className = "star-notif-dot";
    dot.style.cssText = "background:var(--orange);color:white;border-radius:10px;padding:1px 7px;font-size:.68rem;font-weight:700;margin-left:auto;flex-shrink:0";
    dot.textContent = count;
    navItem.appendChild(dot);
  } else if(existing){
    if(count>0) existing.textContent = count;
    else existing.remove();
  }
}