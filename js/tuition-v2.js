/* DrDemic Tuition v2: courses (programs) > topics > sessions, notes, exams, Mini bridge. */
let BACKF=()=>loadHome(), PT=(location.pathname.match(/^\/tuition\/p\/([^/]+)/)||[])[1]||null, CURP=null, NSC=null;
const goBack=()=>BACKF();
const fld=(l,h)=>`<label class="fld"><span>${l}</span>${h}</label>`;
const toggle=id=>{const e=$(id);e.style.display=e.style.display==="block"?"none":"block"};
const kpi=(v,l)=>`<div class="kpi"><b>${v}</b><span>${l}</span></div>`;
const empty=t=>`<div class="empty">${t}</div>`;
const money=n=>n?tzs(n):"Free";
function copyIn(id){const u=$(id).value;(navigator.clipboard?navigator.clipboard.writeText(u).then(()=>toast("Copied")):Promise.reject()).catch(()=>prompt("Copy:",u));}

/* subject chips (teacher) + subject picker (student) */
const CHIPS={};
function chipsMount(id,list){
  CHIPS[id]=[...(list||[])];
  $("cs-"+id).innerHTML=`<div class="chips" id="cl-${id}"></div>
    <div class="row" style="margin:8px 0 0"><input id="ci-${id}" placeholder="Type a subject, press Enter to add" onkeydown="if(event.key==='Enter'||event.key===','){event.preventDefault();chipAdd('${id}')}"><button type="button" onclick="chipAdd('${id}')">Add</button></div>`;
  chipsDraw(id);}
function chipsDraw(id){
  $("cl-"+id).innerHTML=CHIPS[id].map((s,i)=>`<span class="chip">${esc(s)}<button type="button" aria-label="Remove ${esc(s)}" onclick="chipDel('${id}',${i})">×</button></span>`).join("")||'<span class="muted">No subjects added yet.</span>';}
function chipAdd(id){
  const el=$("ci-"+id);if(!el)return;
  el.value.split(",").forEach(x=>{x=x.replace(/\s+/g," ").trim().slice(0,60);if(x&&!CHIPS[id].some(y=>y.toLowerCase()===x.toLowerCase()))CHIPS[id].push(x);});
  el.value="";chipsDraw(id);}
function chipDel(id,i){CHIPS[id].splice(i,1);chipsDraw(id);}

function subjectPicker(list){
  if(!list.length)return fld("Subjects you want (comma separated)",'<input id="ap-sub" placeholder="Physics, Chemistry, Biology">');
  return `<div class="fld"><span>Subjects you want <b id="ap-cnt" class="muted"></b></span>
    <div class="pick">${list.map(s=>`<label class="pickitem"><input type="checkbox" class="ap-s" value="${esc(s)}" onchange="apCount()"><span>${esc(s)}</span></label>`).join("")}</div>
    <div class="row" style="margin:0"><button type="button" class="alt" onclick="apAll(true)">Select all</button><button type="button" class="alt" onclick="apAll(false)">Clear</button></div></div>`;}
function apCount(){const n=document.querySelectorAll(".ap-s:checked").length;if($("ap-cnt"))$("ap-cnt").textContent=n?`(${n} selected)`:"";}
function apAll(on){document.querySelectorAll(".ap-s").forEach(c=>c.checked=on);apCount();}

/* teacher invite code rides along on signup / role choice */
const _api0=window.api,_sm0=window.setMode,_boot0=window.boot;
window.api=function(p,m,b,f){
  if(b&&!f&&b.role==="teacher"&&(p==="/auth/signup"||p==="/auth/role"))
    b.teacher_code=(($("a-tcode")||{}).value||"")||(($("rl-tcode")||{}).value||"");
  return _api0(p,m,b,f);};
window.setMode=function(m){_sm0(m);$("a-tcode").style.display=(m==="signup"&&$("a-role").value==="teacher")?"block":"none";};

/* ── home ── */
async function loadMine(){
  BACKF=loadHome;show("home");const T=me.role==="teacher";
  const [pr,cr]=await Promise.all([api("/programs"),api("/courses")]);
  COURSES={};(cr.courses||[]).forEach(c=>COURSES[c.id]=c);
  const P=pr.programs||[],C=Object.values(COURSES);
  const pcards=P.map(p=>`<div class="panel card-h" onclick="openProgram(${p.id})">
    <div class="row"><b>${esc(p.name)}</b><span class="sp"></span>${T?(p.status==="open"?'<span class="badge on">Open</span>':'<span class="badge end">Closed</span>')
      :`<span class="badge ${p.my_status==="registered"?"on":"warn"}">${p.my_status==="registered"?"Registered":"Payment due"}</span>`}</div>
    <div class="muted">${T?`${p.registered} registered · ${p.applied} awaiting advance · ${p.topics} topics`:`by ${esc(p.teacher)}`}</div>
    <div class="muted" style="margin-top:4px">${money(p.fee)}${p.installments>1?` · up to ${p.installments} instalments`:""}</div></div>`).join("");
  const ccards=C.map(c=>T?`<div class="panel"><b>${esc(c.subject)}</b>
      <div class="muted" style="margin:6px 0 10px">${c.students}/${c.max_students} students · ${c.sessions} sessions · ${c.charge_mode==="session"?"Per session":(c.price?tzs(c.price)+" / "+c.access_days+" days":"Free (set price inside)")}</div>
      <button class="pri" onclick="openCourse(${c.id})">Open</button></div>`
    :`<div class="panel"><b>${esc(c.subject)}</b><div class="muted" style="margin:6px 0 10px">Teacher: ${esc(c.teacher)}</div>
      ${c.active?`<span class="badge on">Access active${c.expires_at?" until "+new Date(c.expires_at).toLocaleDateString():""}</span>`:`<span class="badge warn">${tzs(c.price)} for ${c.access_days} days</span>`}
      <div style="margin-top:10px"><button class="pri" onclick="openCourse(${c.id})">${c.active?"Open":"Open & unlock"}</button></div></div>`).join("");
  let h=`<div id="due"></div>`;
  if(T){
    h+=`<div class="hero"><div><h1>Welcome${me.full_name?", "+esc(me.full_name.split(" ")[0]):""}</h1><p>Courses, topics, sessions, notes and exams in one place.</p></div>
      <div class="row" style="margin:0"><button class="pri" onclick="toggle('np-panel')">+ New course</button><button class="ghost" onclick="toggle('nt-panel')">+ Single topic</button></div></div>
    <div class="panel" id="np-panel" style="display:none"><h3>Create a course</h3><p class="muted" style="margin-bottom:12px">A course is the big programme (e.g. Pre-Form Five). Inside it you add topics, and inside topics, sessions.</p>
      <div class="grid2">${fld("Course name",'<input id="np-name" placeholder="e.g. Pre-Form Five 2027">')}${fld("Total fee (TZS)",'<input id="np-fee" type="number" min="0">')}
      ${fld("Advance to complete registration (TZS)",'<input id="np-adv" type="number" min="0" value="0">')}${fld("Instalments allowed (including advance)",'<input id="np-inst" type="number" min="1" max="12" value="1">')}</div>
      ${fld("Description (what students get)",'<textarea id="np-desc" rows="3"></textarea>')}<div style="margin-top:12px"><button class="pri" onclick="newProgram()">Create course</button></div></div>
      ${fld("Subjects taught in this course", '<div id="cs-np"></div>')}
    <div class="panel" id="nt-panel" style="display:none;max-width:460px"><h3>Create a single topic</h3><p class="muted" style="margin-bottom:10px">A stand-alone topic that students find in search and pay for directly.</p>
      ${fld("Topic name",'<input id="nt-name" placeholder="e.g. Physics: Newton\'s laws">')}<div style="height:10px"></div>
      ${fld("How do you charge?",'<select id="nt-mode" style="width:100%"><option value="session">Per session</option><option value="course">Per topic (whole topic)</option></select>')}
      <div style="margin-top:12px"><button class="pri" onclick="newTopic()">Create topic</button></div></div>`;
    if(!P.length&&!C.length) h+=`<div class="panel steps"><h3>Get started</h3><ol><li><b>Create a course</b> and set its fee, advance and instalments.</li><li><b>Add topics</b> inside it, then schedule <b>sessions</b> and upload videos.</li><li><b>Share the application link</b>. Students register and pay the advance.</li><li>Add <b>notes</b>, <b>assignments</b> and <b>exams</b>, then send results to DrDemic Mini.</li></ol></div>`;
  }else h+=`<div class="hero"><div><h1>My learning</h1><p>Your courses and topics.</p></div><button class="pri" onclick="loadSearch()">Find lessons</button></div>`;
  if(P.length) h+=`<h3 style="margin:6px 0 10px">Courses</h3><div class="cards">${pcards}</div>`;
  if(C.length||!T) h+=`<h3 style="margin:6px 0 10px">${T?"Single topics":"Topics"}</h3><div class="cards">${ccards||empty("Nothing here yet. Search for a lesson or open a link from your teacher.")}</div>`;
  $("v-home").innerHTML=h;
  if(T) chipsMount("np",[]);
  if(T){checkDue();timers.push(setInterval(checkDue,30000));}
}
async function newProgram(){
  chipAdd("np");
  const r=await api("/programs","POST",{name:$("np-name").value,fee:$("np-fee").value,advance:$("np-adv").value,installments:$("np-inst").value,description:$("np-desc").value,subjects:CHIPS.np});
  if(!r.ok)return toast(r.error);toast("Course created");openProgram(r.id);}
async function newTopic(pid){
  const name=pid?$("pt-name").value:$("nt-name").value;
  const r=await api("/courses","POST",{name,charge_mode:pid?"course":$("nt-mode").value,program_id:pid||null});
  if(!r.ok)return toast(r.error);toast("Topic created");
  if(pid)return openProgram(pid,"top");
  await loadMine();openCourse(r.id);}

function loadSearch(){
  BACKF=loadHome;show("home");
  $("v-home").innerHTML=`<div class="hero center"><h1>Learn from teachers you can trust</h1><p>Search a topic or a teacher's name.</p>
    <div class="searchbox"><input id="sq" placeholder="e.g. Physics, Newton's laws, Mr Deo" oninput="searchSoon()" onkeydown="if(event.key==='Enter')runSearch()"><button onclick="runSearch()" title="Search">🔍</button></div>
    <p style="margin-top:16px"><a href="#" style="color:var(--sand)" onclick="loadMine();return false">My courses &amp; topics →</a></p></div><div id="sres"></div>`;
  runSearch();}

/* ── course (program) ── */
async function openProgram(id,k){
  const r=await api("/programs/"+id);if(!r.ok)return toast(r.error);
  CURP=r;show("course");BACKF=loadHome;
  const p=r.program,T=me.role==="teacher",reg=T||(r.mine&&r.mine.status==="registered");
  $("v-course").innerHTML=`<div class="row"><button onclick="loadHome()">← Back</button></div>
    <div class="hero"><div><h1>${esc(p.name)}</h1><p>${money(p.fee)}${p.installments>1?` · up to ${p.installments} instalments`:""}${p.advance?` · advance ${tzs(p.advance)}`:""}</p></div>
    ${T?`<span class="badge ${p.status==="open"?"on":"end"}">${p.status==="open"?"Applications open":"Closed"}</span>`:`<span class="badge ${reg?"on":"warn"}">${reg?"Registered":"Payment due"}</span>`}</div>
    <div class="tabs" id="tabs"></div><div id="tab"></div>`;
  const tabs=T?[["ov","Overview"],["top","Topics"],["ap","Applicants"],["nt","Notes"],["ex","Exams & results"],["tt","Timetable"]]
    :reg?[["top","Topics"],["nt","Notes"],["tt","Timetable"],["pay","Payments"],["res","My results"]]:[["pay","Payments"]];
  $("tabs").innerHTML=tabs.map(([x,l])=>`<button id="tb-${x}" onclick="ptab('${x}')">${l}</button>`).join("");
  ptab(k||tabs[0][0]);
}
function ptab(k){clearTimers();document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b.id==="tb-"+k));
  ({ov:pOv,top:pTop,ap:pAp,nt:()=>{NSC={program_id:CURP.program.id};tabNotes()},ex:pEx,tt:pTt,pay:pPay,res:pRes})[k]();}

function pOv(){
  const r=CURP,p=r.program,s=r.stats,link=location.origin+"/tuition/p/"+p.join_token;
  $("tab").innerHTML=`<div class="kpis">${kpi(s.registered,"Registered")}${kpi(s.applied,"Awaiting advance")}${kpi(tzs(s.collected),"Collected")}${kpi(r.topics.length,"Topics")}</div>
  <div class="panel"><h3>Application link</h3><p class="muted" style="margin-bottom:10px">Students open it, create an account, fill the form and pay the advance to be registered.</p>
    <div class="row"><input id="pl" readonly value="${esc(link)}"><button class="pri" onclick="copyIn('pl')">Copy</button></div></div>
  <div class="panel"><h3>Course settings</h3><div class="grid2">
    ${fld("Name",`<input id="pf-name" value="${esc(p.name)}">`)}${fld("Total fee (TZS)",`<input id="pf-fee" type="number" value="${p.fee}">`)}
    ${fld("Advance (TZS)",`<input id="pf-adv" type="number" value="${p.advance}">`)}${fld("Instalments allowed",`<input id="pf-inst" type="number" value="${p.installments}">`)}
    ${fld("Maximum students",`<input id="pf-max" type="number" value="${p.max_students}">`)}
    ${fld("Applications",`<select id="pf-st" style="width:100%"><option value="open" ${p.status==="open"?"selected":""}>Open</option><option value="closed" ${p.status==="closed"?"selected":""}>Closed</option></select>`)}</div>
    ${fld("Subjects taught in this course", '<div id="cs-pf"></div>')}
    ${fld("Description",`<textarea id="pf-desc" rows="3">${esc(p.description)}</textarea>`)}
    <p class="muted" style="margin:10px 0">Changing the fee affects what each student still owes.</p><button class="pri" onclick="saveProg()">Save changes</button></div>`;}
    chipsMount("pf" ,p.subjects||[]);

async function saveProg(){
  chipAdd("pf");
  const r=await api("/programs/"+CURP.program.id,"POST",{name:$("pf-name").value,fee:$("pf-fee").value,advance:$("pf-adv").value,installments:$("pf-inst").value,max_students:$("pf-max").value,status:$("pf-st").value,description:$("pf-desc").value,subjects:CHIPS.pf});
  if(!r.ok)return toast(r.error);toast("Saved");openProgram(CURP.program.id,"ov");}

function pTop(){
  const T=me.role==="teacher",id=CURP.program.id;
  const rows=CURP.topics.map(c=>`<div class="panel row-card"><div><b>${esc(c.subject)}</b><div class="muted">${c.sessions} sessions${T?` · ${c.students} students`:""}</div></div><button class="pri" onclick="openTopic(${c.id})">Open</button></div>`).join("");
  $("tab").innerHTML=(T?`<div class="panel"><h3>Add a topic</h3><div class="row"><input id="pt-name" placeholder="e.g. Mechanics"><button class="pri" onclick="newTopic(${id})">Add topic</button></div>
    <p class="muted">Registered students are enrolled automatically and never pay per topic.</p></div>`:"")+(rows||empty("No topics yet."));}
function openTopic(cid){
  const pid=CURP.program.id,t=CURP.topics.find(x=>x.id===cid);
  COURSES[cid]=CUR={id:cid,subject:t.subject,title:"",price:0,access_days:30,charge_mode:"course",program_id:pid};
  BACKF=()=>openProgram(pid,"top");openCourse(cid,true);}

function pAp(){
  const A=CURP.applicants,p=CURP.program,tally={};
  A.forEach(a=>(a.subjects||"").split(/[,;\n]/).map(x=>x.trim()).filter(Boolean).forEach(s=>{const k=s.toLowerCase();tally[k]=(tally[k]||0)+1}));
  const chips=Object.entries(tally).sort((a,b)=>b[1]-a[1]).map(([s,n])=>`<span class="badge">${esc(s)} · ${n}</span>`).join(" ");
  $("tab").innerHTML=`<div class="panel"><h3>Subjects requested</h3><div class="row">${chips||'<span class="muted">No subjects listed yet.</span>'}</div></div>
  <div class="panel" style="overflow-x:auto"><table><tr><th>Student</th><th>Phone</th><th>Subjects</th><th>Status</th><th>Paid</th></tr>
  ${A.map(a=>`<tr><td><b>${esc(a.name)}</b>${a.note?`<div class="muted">${esc(a.note)}</div>`:""}</td><td>${esc(a.phone)}</td><td>${esc(a.subjects||"-")}</td>
    <td><span class="badge ${a.status==="registered"?"on":"warn"}">${a.status==="registered"?"Registered":"Applied"}</span></td>
    <td style="min-width:130px">${tzs(a.paid)}<div class="bar"><i style="width:${p.fee?Math.min(100,Math.round(a.paid*100/p.fee)):100}%"></i></div></td></tr>`).join("")||'<tr><td colspan="5" class="muted">No applications yet.</td></tr>'}</table></div>`;}

function pTt(){
  const p=CURP.program,T=me.role==="teacher";
  $("tab").innerHTML=T?`<div class="panel"><h3>Timetable</h3><p class="muted" style="margin-bottom:10px">Students see this text. Write it the way you would pin it on a notice board.</p>
    <textarea id="tt" rows="12" placeholder="Mon 4pm: Physics&#10;Tue 4pm: Chemistry">${esc(p.timetable)}</textarea><div style="margin-top:12px"><button class="pri" onclick="saveTT()">Save timetable</button></div></div>`
  :`<div class="panel"><h3>Timetable</h3>${p.timetable?`<pre style="white-space:pre-wrap;font:inherit">${esc(p.timetable)}</pre>`:'<p class="muted">Your teacher has not published a timetable yet.</p>'}</div>`;}
async function saveTT(){const r=await api("/programs/"+CURP.program.id,"POST",{timetable:$("tt").value});if(!r.ok)return toast(r.error);toast("Timetable saved");CURP.program.timetable=$("tt").value;}

function pPay(){
  const r=CURP,p=r.program,m=r.mine,must=m.count+1>=p.installments,min=m.count===0?Math.max(p.advance,500):500;
  const hist=r.history.map(h=>`<tr><td>${fdt(h.at)}</td><td>${h.kind==="advance"?"Advance":"Instalment"}</td><td>${tzs(h.amount)}</td><td><span class="badge ${h.status==="completed"?"on":"warn"}">${esc(h.status)}</span></td></tr>`).join("");
  $("tab").innerHTML=`<div class="kpis">${kpi(tzs(m.paid),"Paid")}${kpi(tzs(m.balance),"Balance")}${kpi(Math.max(p.installments-m.count,0),"Instalments left")}</div>
  ${m.status!=="registered"?`<div class="alert">Pay at least <b>${tzs(p.advance||500)}</b> to complete your registration.</div>`:""}
  ${m.balance>0?`<div class="panel"><h3>Make a payment</h3>${must&&m.count>0?'<p class="muted" style="margin-bottom:8px">This is your last instalment: the full balance is due.</p>':""}
    <div class="grid2">${fld("Amount (TZS)",`<input id="pg-amt" type="number" min="${min}" max="${m.balance}" value="${must?m.balance:Math.min(m.balance,Math.max(min,m.count===0?p.advance:min))}" ${must?"readonly":""}>`)}
    ${fld("Mobile-money number that will pay",'<input id="pg-ph" type="tel" placeholder="0712345678">')}</div>
    <button class="pri" onclick="payProg()">Pay now</button><div id="pg-st" class="muted" style="margin-top:10px"></div></div>`
   :'<div class="alert ok">Fully paid. Thank you!</div>'}
  ${hist?`<div class="panel" style="overflow-x:auto"><h3>History</h3><table><tr><th>Date</th><th>Type</th><th>Amount</th><th>Status</th></tr>${hist}</table></div>`:""}`;}
async function payProg(){
  const amount=+$("pg-amt").value,phone=$("pg-ph").value.trim();if(!phone)return toast("Enter the mobile-money number that will pay");
  const r=await api(`/programs/${CURP.program.id}/pay`,"POST",{amount,phone});if(!r.ok)return toast(r.error);
  toast("Approve the payment on your phone");const el=$("pg-st");el.textContent="⏳ Waiting for approval…";let n=0;
  const t=setInterval(async()=>{n++;const c=await api("/program_pay/check/"+r.payment_id,"POST",{});
    if(c.status==="completed"){clearInterval(t);toast("Payment confirmed!");openProgram(CURP.program.id,"pay");}
    else if(["failed","voided","expired","amount_mismatch"].includes(c.status)){clearInterval(t);el.textContent="Payment "+c.status+". You can try again.";}
    else if(n>=36){clearInterval(t);el.textContent="Still waiting. Reopen this page in a minute.";}},5000);timers.push(t);}

/* ── exams → DrDemic Mini ── */
async function pEx(){
  const r=await api(`/programs/${CURP.program.id}/exams`),ex=r.exams||[];
  $("tab").innerHTML=`<div class="panel"><h3>Send exam results to DrDemic Mini</h3>
    <p class="muted" style="margin-bottom:12px">Tick the exams to include. Registered students see their marks, positions and analytics in DrDemic Mini with their normal account. Create exams inside each topic (Exams tab).</p>
    ${ex.map(e=>`<label class="chk"><input type="checkbox" class="exc" value="${e.id}"><span><b>${esc(e.subject)}: ${esc(e.title)}</b><small>${e.marked} marked · out of ${e.max_score}</small></span></label>`).join("")||empty("No exams yet. Open a topic → Exams to create one.")}
    <div class="row" style="margin-top:12px"><input id="ex-t" placeholder="Result title, e.g. Mid-course exam"><button class="pri" onclick="sendMini()">Publish to Mini</button></div><div id="ex-out"></div></div>`;}
async function sendMini(){
  const ids=[...document.querySelectorAll(".exc:checked")].map(x=>+x.value);
  const r=await api(`/programs/${CURP.program.id}/to_mini`,"POST",{title:$("ex-t").value,assignment_ids:ids});if(!r.ok)return toast(r.error);
  $("ex-out").innerHTML=`<div class="alert ok">Sent to ${r.students} students.<div class="row" style="margin:8px 0 0"><button class="pri" onclick="openMini('${r.key}')">Open in DrDemic Mini</button></div></div>`;}
function pRes(){$("tab").innerHTML=`<div class="panel"><h3>My results</h3><p class="muted" style="margin-bottom:12px">Exam results and analytics are in DrDemic Mini. You are signed in automatically.</p><button class="pri" onclick="openMini()">Open my results in DrDemic Mini</button></div>`;}
async function openMini(key){
  const r=await api("/mini/open","POST",{});if(!r.ok)return toast(r.error);
  localStorage.setItem("mini_token",r.token);localStorage.setItem("mini_me",JSON.stringify({username:r.username,role:r.role,must_change:false}));
  location.href=key?"/mini?s="+encodeURIComponent(key):"/mini";}

/* ── apply page (from the course link) ── */
async function openApply(token){
  const r=await api("/p/"+token);if(!r.ok){toast("This link is not valid");return loadHome();}
  show("course");BACKF=loadHome;
  $("v-course").innerHTML=`<div class="hero"><div><h1>${esc(r.name)}</h1><p>by ${esc(r.teacher)} · ${money(r.fee)}${r.installments>1?` · up to ${r.installments} instalments`:""}</p></div></div>
  <div class="panel"><p style="white-space:pre-wrap;margin-bottom:12px">${esc(r.description||"")}</p>
    ${r.advance?`<div class="alert">Your seat is confirmed after paying an advance of <b>${tzs(r.advance)}</b>.</div>`:""}
    ${r.status!=="open"?'<div class="alert">Applications are closed.</div>':`<h3>Application form</h3><div class="grid2">
      ${fld("Full name",`<input id="ap-name" value="${esc(me.full_name||"")}">`)}${fld("Phone number",'<input id="ap-ph" type="tel" placeholder="0712345678">')}</div>
      ${subjectPicker(r.subjects||[])}<div style="height:10px"></div>
      ${fld("Anything we should know? (optional)",'<textarea id="ap-note" rows="2"></textarea>')}
      <div style="margin-top:14px"><button class="pri" onclick="submitApply('${token}')">Submit application</button></div>`}</div>`;}

async function submitApply(t){
  const boxes=document.querySelectorAll(".ap-s");let subjects;
  if(boxes.length){subjects=[...document.querySelectorAll(".ap-s:checked")].map(c=>c.value);if(!subjects.length)return toast("Pick at least one subject");}
  else subjects=$("ap-sub").value;
  const r=await api(`/p/${t}/apply`,"POST",{full_name:$("ap-name").value,phone:$("ap-ph").value,subjects,note:$("ap-note").value});
  if(!r.ok)return toast(r.error);toast("Application received");openProgram(r.program_id,"pay");}

window.boot=async function(){
  if(PT&&(!token||!me)){
    const r=await api("/p/"+PT);show("auth");
    if(r.ok){$("a-join").style.display="block";$("a-join").innerHTML=`You are applying to <b>${esc(r.name)}</b> by ${esc(r.teacher)}. Create a student account or sign in to continue.`;$("a-role").value="student";setMode("signup");}
    else{toast("This link is not valid");PT=null;setMode("login");}
    return;}
  if(PT&&token&&me&&!me.must_change&&me.role){
    const t=PT;PT=null;history.replaceState(null,"","/tuition");
    if(me.role!=="student"){await loadHome();return toast("Application links are for student accounts.");}
    return openApply(t);}
  return _boot0();};

/* ── topic (old "course") screens ── */
function openCourse(id,keep){
  if(!keep&&!(CUR&&CUR.id===id))BACKF=loadHome;
  CUR=COURSES[id]||CUR;show("course");const T=me.role==="teacher",inProg=!!CUR.program_id;
  const link=T&&!inProg?location.origin+"/tuition/c/"+CUR.join_token:"";
  const top=T&&!inProg?`<div class="panel"><h3>Topic link</h3><p class="muted" style="margin-bottom:8px">Send this to students who should join this topic.</p>
    <div class="row"><input id="cl" readonly value="${esc(link)}"><button class="pri" onclick="copyCL()">Copy</button></div>
    ${CUR.charge_mode==="course"?`<div class="grid2">${fld("Price (TZS, 0 = free)",`<input id="cp-price" type="number" value="${CUR.price}">`)}${fld("Access days",`<input id="cp-days" type="number" value="${CUR.access_days}">`)}</div><button onclick="savePricing()">Save price</button>`
    :'<p class="muted">Charging per session: set each session\'s price when you schedule it.</p>'}</div>`:"";
  $("v-course").innerHTML=`<div class="row"><button onclick="goBack()">← Back</button><h2>${esc(CUR.subject)}</h2></div>${top}<div class="tabs" id="tabs"></div><div id="tab"></div>`;
  const names=[["sessions","Sessions"],...(T?[["students","Students"]]:[]),["notes","Notes"],["assign","Assignments"],["exam","Exams"],["progress","Progress"]];
  $("tabs").innerHTML=names.map(([k,l])=>`<button id="tb-${k}" onclick="tab('${k}')">${l}</button>`).join("");tab("sessions");}
function tab(k){clearTimers();document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b.id==="tb-"+k));
  ({sessions:tabSessions,students:tabStudents,notes:()=>{NSC={course_id:CUR.id};tabNotes()},assign:()=>tabAssign("assignment"),exam:()=>tabAssign("exam"),progress:tabProgress})[k]();}

async function tabNotes(){
  const T=me.role==="teacher",q=Object.entries(NSC)[0].join("=");
  const r=await api("/notes?"+q);if(!r.ok)return($("tab").innerHTML=empty(esc(r.error||"Not available")));
  const form=T?`<div class="panel"><h3>Add notes</h3>${fld("Title",'<input id="nn-t">')}<div style="height:10px"></div>${fld("Text (optional)",'<textarea id="nn-b" rows="3"></textarea>')}
    <div class="row" style="margin-top:10px"><input id="nn-f" type="file"><button class="pri" onclick="addNote()">Publish</button></div></div>`:"";
  const rows=(r.notes||[]).map(n=>`<div class="panel row-card"><div><b>${esc(n.title)}</b><div class="muted">${fdt(n.at)}</div>${n.body?`<p style="margin-top:6px;white-space:pre-wrap">${esc(n.body)}</p>`:""}</div>
    <div class="row" style="margin:0">${n.file_name?`<a class="btn" href="${U(`/notes/${n.id}/file`)}" target="_blank">📎 ${esc(n.file_name)}</a>`:""}${T?`<button class="red" onclick="delNote(${n.id})">Delete</button>`:""}</div></div>`).join("");
  $("tab").innerHTML=form+(rows||empty("No notes yet."));}
async function addNote(){
  const fd=new FormData(),[k,v]=Object.entries(NSC)[0];fd.append(k,v);fd.append("title",$("nn-t").value);fd.append("body",$("nn-b").value);
  const f=$("nn-f").files[0];if(f)fd.append("file",f);
  const r=await api("/notes","POST",fd,true);if(!r.ok)return toast(r.error);toast("Notes published");tabNotes();}
async function delNote(id){if(!confirm("Delete these notes?"))return;await api("/notes/"+id,"DELETE");tabNotes();}

async function tabAssign(kind){
  const T=me.role==="teacher",X=kind==="exam",noun=X?"exam":"assignment";
  const r=await api(`/courses/${CUR.id}/assignments`),list=(r.assignments||[]).filter(a=>(a.kind||"assignment")===kind);
  const form=T?`<div class="panel"><h3>New ${noun}</h3>${fld("Title",'<input id="as-title">')}<div style="height:10px"></div>${fld("Instructions / questions",'<textarea id="as-ins" rows="3"></textarea>')}
    <div class="grid2" style="margin-top:10px">${fld("Due",'<input id="as-due" type="datetime-local">')}${fld("Maximum score",'<input id="as-max" type="number" value="100">')}</div>
    <div class="row"><input id="as-file" type="file"><button class="pri" onclick="addAssign('${kind}')">Create ${noun}</button></div></div>`:"";
  const rows=list.map(a=>{const link=a.file_name?`<a href="${U(`/assignments/${a.id}/file`)}" target="_blank">📎 ${esc(a.file_name)}</a>`:"";
    if(T)return `<div class="panel"><b>${esc(a.title)}</b> <span class="muted">due ${fdt(a.due_at)} · /${a.max_score}</span><p>${esc(a.instructions)}</p>${link}
      <div class="row" style="margin-top:8px"><span class="badge">${a.submitted} submitted · ${a.marked} marked</span><button onclick="viewSubs(${a.id})">View &amp; mark</button></div><div id="subs-${a.id}"></div></div>`;
    const m=a.mine;return `<div class="panel"><b>${esc(a.title)}</b> <span class="muted">due ${fdt(a.due_at)} · /${a.max_score}</span><p>${esc(a.instructions)}</p>${link}
      ${m&&m.score!=null?`<div class="alert ok">Score <b>${m.score}/${a.max_score}</b>${m.feedback?"<br>"+esc(m.feedback):""}</div>`
      :`${m?`<p class="muted">Submitted ${fdt(m.submitted_at)}. You can resubmit until it is marked.</p>`:""}
        <textarea id="sb-${a.id}" rows="3" placeholder="Your answer">${m?esc(m.body):""}</textarea>
        <div class="row" style="margin-top:8px"><input id="sf-${a.id}" type="file"><button class="pri" onclick="submitAssign(${a.id})">Submit</button></div>`}</div>`}).join("");
  $("tab").innerHTML=form+(rows||empty(`No ${noun}s yet.`));}
async function addAssign(kind){
  const fd=new FormData();fd.append("kind",kind||"assignment");fd.append("title",$("as-title").value);fd.append("instructions",$("as-ins").value);
  if($("as-due").value)fd.append("due_at",new Date($("as-due").value).toISOString());fd.append("max_score",$("as-max").value);
  const f=$("as-file").files[0];if(f)fd.append("file",f);
  const r=await api(`/courses/${CUR.id}/assignments`,"POST",fd,true);if(!r.ok)return toast(r.error);toast("Created");tabAssign(kind);}

initGoogle();
boot();