// ── DASHBOARD ────────────────────────────────────────────────
async function loadPlatformNotices(){
  if(!currentUser || currentUser.role !== "admin") return;
  try {
    const notices = await api("/platform_announcements");
    const card  = document.getElementById("platform-notices-card");
    const list  = document.getElementById("platform-notices-list");
    const badge = document.getElementById("platform-notices-badge");
    if(!notices || notices.length === 0){ card.style.display="none"; return; }
    card.style.display = "";
    const unread = notices.filter(n => !n.is_read).length;
    if(unread > 0){ badge.textContent = unread + " new"; badge.style.display = ""; }
    else { badge.style.display = "none"; }
    list.innerHTML = notices.map(n => `
      <div style="padding:12px 0;border-bottom:1px solid #EDE7F6;${n.is_read?'opacity:.7':''}" id="pn-${n.id}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap">
          <div style="font-weight:600;font-size:.93rem;color:#4A148C">${n.title}
            ${!n.is_read ? '<span style="background:#7B1FA2;color:#fff;border-radius:4px;padding:1px 7px;font-size:.7rem;margin-left:6px">NEW</span>' : ''}
          </div>
          <div style="font-size:.76rem;color:#9E9E9E">${n.posted_at ? n.posted_at.slice(0,16) : ''}</div>
        </div>
        <div style="margin-top:6px;font-size:.87rem;color:#37474F;white-space:pre-wrap">${n.body}</div>
        ${!n.is_read ? `<button onclick="markPlatformNoticeRead(${n.id})" style="margin-top:8px;background:none;border:1px solid #7B1FA2;color:#7B1FA2;border-radius:6px;padding:4px 12px;font-size:.78rem;cursor:pointer">Mark as read</button>` : ''}
      </div>`).join("");
  } catch(e){}
}

async function markPlatformNoticeRead(aid){
  await api("/platform_announcements/"+aid+"/read","POST",{});
  await loadPlatformNotices();
}

function renderDashSchoolHeader(){
  const nameEl = document.getElementById("dash-school-name");
  if(nameEl) nameEl.textContent = config.school_name || "";
  const badgeEl = document.getElementById("dash-school-badge");
  const motto = config.school_info && config.school_info.motto;
  if(badgeEl){
    if(motto){ badgeEl.textContent = motto; badgeEl.style.display="inline-flex"; }
    else { badgeEl.style.display="none"; }
  }
}

async function loadDashboard(){
  renderDashSchoolHeader();
  loadPlatformNotices();
  loadClassAnalyticsCard();
  const studs = await api("/students");
  const stats = document.getElementById("dash-stats");
  const byClass = {};
  studs.forEach(s=>{byClass[s.class_name]=(byClass[s.class_name]||0)+1});
  const entries = [
    {val:studs.length,                    label:"Total Students",  col:"#1565C0", bg:"#E3F2FD"},
    {val:Object.keys(byClass).length,     label:"Active Classes",  col:"#00B0FF", bg:"#E1F5FE"},
  ];
  stats.innerHTML = entries.map(e=>`
    <div class="stat-card" style="border-color:${e.col}">
      <div class="stat-icon" style="background:${e.bg}">
        <svg viewBox="0 0 24 24" fill="${e.col}" width="22" height="22"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
      </div>
      <div><div class="stat-val" style="color:${e.col}">${e.val}</div><div class="stat-label">${e.label}</div></div>
    </div>`).join("");
  const recent = studs.slice(-8).reverse();
  document.getElementById("dash-recent-students").innerHTML = recent.length
    ? `<div class="table-wrap"><table><thead><tr><th>ID</th><th>Name</th><th>Class</th></tr></thead><tbody>
       ${recent.map(s=>`<tr><td>${s.id}</td><td>${s.name}</td><td><span class="badge badge-blue">${cap(s.class_name)}</span></td></tr>`).join("")}
       </tbody></table></div>`
    : `<div class="empty-state">${emptySVG()}<p>No students yet</p></div>`;
}

async function loadClassAnalyticsCard(){
  if(!currentUser || currentUser.role!=="admin") return;
  const d = await api("/analytics/dashboard_classes");
  const card = document.getElementById("dash-class-analytics-card");
  const body = document.getElementById("dash-class-analytics-body");
  if(!card || !body) return;
  if(!d.ok || (!d.best && !d.weakest)){ card.style.display="none"; return; }
  card.style.display="block";
  body.innerHTML = `
    <div style="background:#E8F5E9;border-radius:10px;padding:14px">
      <div style="font-size:.75rem;font-weight:700;color:#2E7D32;text-transform:uppercase">🏆 Best Performing Class</div>
      <div style="font-size:1.1rem;font-weight:800;color:var(--navy);margin-top:4px">${d.best?d.best.class_name:"—"}</div>
      <div style="font-size:.85rem;color:var(--muted)">${d.best?d.best.average+"% average":""}</div>
    </div>
    <div style="background:#FFEBEE;border-radius:10px;padding:14px">
      <div style="font-size:.75rem;font-weight:700;color:#C62828;text-transform:uppercase">⚠ Weakest Performing Class</div>
      <div style="font-size:1.1rem;font-weight:800;color:var(--navy);margin-top:4px">${d.weakest?d.weakest.class_name:"—"}</div>
      <div style="font-size:.85rem;color:var(--muted)">${d.weakest?d.weakest.average+"% average":""}</div>
    </div>`;
}
