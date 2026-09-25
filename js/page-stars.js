// ── STAR SYSTEM (admin) ─────────────────────────────────────
async function loadStarSystemPage(){
  const el = document.getElementById("star-system-body");
  if(!el) return;
  el.innerHTML = `<div class="spinner"></div>`;
  const d = await api("/stars/dashboard");
  if(!d.ok){ el.innerHTML = `<p style="color:var(--red)">Could not load Star System data.</p>`; return; }
  const p = d.cycle_progress;
  const pct = p && p.required ? Math.min(100, Math.round((p.qualifying_parent_count/p.required)*100)) : 0;
  el.innerHTML = `
    <div class="stats-grid" style="margin-bottom:20px">
      <div class="stat-card" style="border-color:var(--gold)">
        <div class="stat-icon" style="background:#FFF8E1">⭐</div>
        <div><div class="stat-val" style="color:var(--orange)">${d.balance.stars}</div><div class="stat-label">Stars</div></div>
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
    <div class="table-card">
      <div class="table-toolbar"><span class="table-toolbar-title">Reward History</span></div>
      <div id="star-history-body" style="padding:16px"><div class="spinner"></div></div>
    </div>`;
  loadStarHistory();
}
async function loadStarHistory(){
  const el = document.getElementById("star-history-body");
  if(!el) return;
  const d = await api("/stars/history");
  if(!d.ok || !d.history.length){ el.innerHTML = `<p style="color:var(--muted);font-size:.85rem">No reward activity yet.</p>`; return; }
  el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Stars</th><th>Amount</th><th>Status</th></tr></thead><tbody>
    ${d.history.map(h=>`<tr>
      <td style="font-size:.8rem;color:var(--muted)">${h.cast||""}</td>
      <td>${cap((h.type||"").toLowerCase().replace(/_/g," "))}</td>
      <td style="font-weight:600">${h.type==="WITHDRAWAL"?"-":"+"}${h.stars}</td>
      <td>${h.amount.toLocaleString()} TZS</td>
      <td><span class="badge ${h.status==='AVAILABLE'?'badge-green':h.status==='WITHDRAWN'?'badge-blue':'badge-grey'}">${h.status}</span></td>
    </tr>`).join("")}
  </tbody></table></div>`;
}