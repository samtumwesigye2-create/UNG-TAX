const modules={
  taxpayers:{title:'Taxpayer Management',sub:'Search, edit, suspend/reactivate and document taxpayer accounts.'},
  returns:{title:'Return Review',sub:'Review submitted returns and move them through controlled review states.'},
  assessments:{title:'Assessments',sub:'Create and manage tax assessments, penalties, interest and adjustments.'},
  compliance:{title:'Compliance',sub:'Track filing/payment compliance, risk flags and follow-up actions.'},
  payments:{title:'Payments & Liabilities',sub:'Review balances, allocate payments, reverse allocations and create installment plans.'},
  notices:{title:'Notices',sub:'Prepare, approve, issue, cancel and archive taxpayer notices.'},
  cases:{title:'Cases & Audits',sub:'Create, assign and manage controlled review and audit cases.'},
  reports:{title:'Revenue Reports',sub:'Operational counts and totals across filings, assessments, liabilities and cases.'}
};
let token=localStorage.getItem('promet_access_token')||'';
let role=localStorage.getItem('promet_role')||'';
let mfaSession='';
let currentModule=new URLSearchParams(location.search).get('module')||'taxpayers';
if(!modules[currentModule]) currentModule='taxpayers';
const $=id=>document.getElementById(id);

function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function money(v){return new Intl.NumberFormat('en-UG',{maximumFractionDigits:2}).format(Number(v||0));}
function msg(text,ok=true){$('message').innerHTML=`<div class="msg ${ok?'ok':'err'}">${esc(text)}</div>`;}
function authMsg(text,ok=false){$('authMsg').innerHTML=`<div class="msg ${ok?'ok':'err'}">${esc(text)}</div>`;}

async function api(path,options={}){
  options.headers={...(options.headers||{}),'Content-Type':'application/json'};
  if(token) options.headers.Authorization=`Bearer ${token}`;
  const r=await fetch(path,options);
  let data={}; try{data=await r.json();}catch(_){data={detail:await r.text()};}
  if(r.status===401){localStorage.removeItem('promet_access_token');token='';showAuth();throw new Error(data.detail||'Session expired');}
  if(!r.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
  return data;
}

function showAuth(){$('workspace').classList.add('hidden');$('authPanel').classList.remove('hidden');}
function showWorkspace(){$('authPanel').classList.add('hidden');$('workspace').classList.remove('hidden');$('roleBadge').textContent=role==='revenue_admin'?'Revenue Admin':'Revenue Staff';renderNav();loadModule();}

async function validateSession(){
  if(!token){showAuth();return;}
  try{
    const me=await api('/auth/me');
    role=me.role;
    if(!['revenue_staff','revenue_admin'].includes(role)) throw new Error('Revenue role required');
    localStorage.setItem('promet_role',role);showWorkspace();
  }catch(e){token='';localStorage.removeItem('promet_access_token');showAuth();authMsg(e.message);}
}

async function login(){
  try{
    const data=await api('/auth/login',{method:'POST',body:JSON.stringify({email:$('loginEmail').value.trim(),password:$('loginPassword').value})});
    mfaSession=data.session_token;$('mfaBox').classList.remove('hidden');
    $('mfaHelp').textContent=data.mfa_method==='email_otp'?'Enter the verification code sent to your email.':`Enter the authenticator code. ${data.provisioning_uri?'If needed, add this URI to your authenticator: '+data.provisioning_uri:''}`;
    authMsg('Password accepted. Complete MFA.',true);
  }catch(e){authMsg(e.message);}
}
async function verifyMfa(){
  try{
    const data=await fetch('/auth/mfa/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_token:mfaSession,code:$('mfaCode').value.trim()})}).then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.detail||'Verification failed');return d;});
    if(!['revenue_staff','revenue_admin'].includes(data.role)) throw new Error('This account is not authorized for revenue operations.');
    token=data.access_token;role=data.role;localStorage.setItem('promet_access_token',token);localStorage.setItem('promet_role',role);showWorkspace();
  }catch(e){authMsg(e.message);}
}
function signOut(){token='';role='';localStorage.removeItem('promet_access_token');localStorage.removeItem('promet_role');showAuth();}

function renderNav(){
  $('moduleNav').innerHTML=Object.entries(modules).map(([k,v])=>`<button data-module="${k}" class="${k===currentModule?'active':''}">${esc(v.title)}</button>`).join('');
  $('moduleNav').querySelectorAll('button').forEach(b=>b.onclick=()=>{currentModule=b.dataset.module;history.replaceState({},'',`/operations?module=${currentModule}`);renderNav();loadModule();});
}
async function loadModule(){
  const meta=modules[currentModule];$('moduleTitle').textContent=meta.title;$('moduleSub').textContent=meta.sub;$('message').innerHTML='';
  try{await ({taxpayers:loadTaxpayers,returns:loadReturns,assessments:loadAssessments,compliance:loadCompliance,payments:loadPayments,notices:loadNotices,cases:loadCases,reports:loadReports}[currentModule])();}
  catch(e){msg(e.message,false);}
}

async function loadTaxpayers(){
  $('controls').innerHTML=`<div class="toolbar"><div class="field"><label>Search name, email, TIN or account</label><input id="tpQ" placeholder="Search taxpayers"></div><div class="field"><label>Status</label><select id="tpStatus"><option value="">All</option><option>active</option><option>suspended</option><option>inactive</option></select></div><button class="btn primary" id="tpSearch">Search</button></div>`;
  $('tpSearch').onclick=loadTaxpayers;
  const priorQ=$('tpQ')?.value||''; const priorS=$('tpStatus')?.value||'';
  const p=new URLSearchParams();if(priorQ)p.set('q',priorQ);if(priorS)p.set('status',priorS);
  const data=await api('/ops/taxpayers?'+p.toString());
  $('results').innerHTML=data.items.length?`<table class="data"><thead><tr><th>Name</th><th>TIN</th><th>Contact</th><th>Status</th><th>Actions</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.name)}<div class="muted">${esc(x.account_id)}</div></td><td>${esc(x.tin)}</td><td>${esc(x.email)}<br>${esc(x.phone)}</td><td><span class="status">${esc(x.status)}</span></td><td><div class="quick-actions"><button class="btn secondary" onclick="editTaxpayer('${x.id}','${esc(x.phone||'')}','${esc(x.status)}')">Edit</button><button class="btn secondary" onclick="addTaxpayerNote('${x.id}')">Add note</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No taxpayer records found.</div>';
}
async function editTaxpayer(id,phone,status){
  const newPhone=prompt('Phone number',phone);if(newPhone===null)return;const newStatus=prompt('Status: active, suspended or inactive',status);if(newStatus===null)return;const reason=prompt('Reason for this change')||'';
  try{await api(`/ops/taxpayers/${id}`,{method:'PATCH',body:JSON.stringify({phone:newPhone,status:newStatus,reason})});msg('Taxpayer record updated.');await loadTaxpayers();}catch(e){msg(e.message,false);}
}
async function addTaxpayerNote(id){const note=prompt('Operational note');if(!note)return;try{await api(`/ops/taxpayers/${id}/notes`,{method:'POST',body:JSON.stringify({note})});msg('Note added.');}catch(e){msg(e.message,false);}}

async function loadReturns(){
  $('controls').innerHTML=`<div class="toolbar"><div class="field"><label>State</label><select id="returnState"><option value="">All</option>${['draft','submitted','under_review','needs_correction','accepted','rejected','voided','archived'].map(s=>`<option>${s}</option>`).join('')}</select></div><button class="btn primary" id="returnLoad">Load queue</button></div>`;
  $('returnLoad').onclick=loadReturns;const s=$('returnState').value;const data=await api('/ops/returns'+(s?'?state='+encodeURIComponent(s):''));
  $('results').innerHTML=data.items.length?`<table class="data"><thead><tr><th>Return</th><th>Taxpayer</th><th>Type / Period</th><th>State</th><th>Review</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.taxpayer_id)}</td><td>${esc(x.return_type||'—')} / ${esc(x.period||'—')}</td><td><span class="status">${esc(x.state)}</span></td><td><button class="btn secondary" onclick="reviewReturn('${x.id}','${x.state}')">Change state</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No returns in this queue.</div>';
}
async function reviewReturn(id,current){const state=prompt(`Current: ${current}. New state?`);if(!state)return;const reason=['rejected','voided'].includes(state)?prompt('Reason (required)'):prompt('Reviewer note / reason (optional)');try{await api(`/ops/returns/${id}/review`,{method:'PATCH',body:JSON.stringify({state,reviewer_notes:reason||null,reason:reason||null})});msg('Return review state updated.');await loadReturns();}catch(e){msg(e.message,false);}}

async function loadAssessments(){
  $('controls').innerHTML=`<div class="editor"><div><label>Taxpayer ID</label><input id="assTp"></div><div><label>Return ID (optional)</label><input id="assRet"></div><div><label>Principal</label><input id="assPrincipal" type="number" value="0"></div><div><label>Penalty</label><input id="assPenalty" type="number" value="0"></div><div><label>Interest</label><input id="assInterest" type="number" value="0"></div><div style="align-self:end"><button class="btn primary" id="assCreate">Create assessment</button></div></div>`;
  $('assCreate').onclick=async()=>{try{await api('/ops/assessments',{method:'POST',body:JSON.stringify({taxpayer_id:$('assTp').value.trim(),return_id:$('assRet').value.trim()||null,principal:Number($('assPrincipal').value||0),penalty:Number($('assPenalty').value||0),interest:Number($('assInterest').value||0),adjustments:[]})});msg('Assessment created.');await loadAssessments();}catch(e){msg(e.message,false);}};
  const data=await api('/ops/assessments');$('results').innerHTML=data.items.length?`<table class="data"><thead><tr><th>ID</th><th>Taxpayer</th><th>Principal</th><th>Total</th><th>Status</th><th>Actions</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.taxpayer_id)}</td><td class="money">${money(x.principal)}</td><td class="money">${money(x.total)}</td><td><span class="status">${esc(x.status)}</span></td><td><button class="btn secondary" onclick="updateAssessment('${x.id}','${x.status}')">Update status</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No assessments yet.</div>';
}
async function updateAssessment(id,current){const status=prompt(`Current: ${current}. New status?`);if(!status)return;try{await api(`/ops/assessments/${id}`,{method:'PATCH',body:JSON.stringify({status})});msg('Assessment updated.');await loadAssessments();}catch(e){msg(e.message,false);}}

async function loadCompliance(){
  $('controls').innerHTML=`<div class="toolbar"><div class="field"><label>Taxpayer ID</label><input id="compTp" placeholder="Taxpayer ID"></div><button class="btn primary" id="compOpen">Open compliance record</button></div><div id="compEditor" style="margin-top:12px"></div>`;
  $('compOpen').onclick=openCompliance;$('results').innerHTML='<div class="empty">Enter a taxpayer ID to open the compliance record.</div>';
}
async function openCompliance(){try{const id=$('compTp').value.trim();if(!id)return;const x=await api(`/ops/compliance/${encodeURIComponent(id)}`);$('compEditor').innerHTML=`<div class="editor"><div><label>Filing compliance</label><input id="cf" value="${esc(x.filing_compliance)}"></div><div><label>Payment compliance</label><input id="cp" value="${esc(x.payment_compliance)}"></div><div><label>Risk flags (comma separated)</label><input id="cr" value="${esc((x.risk_flags||[]).join(','))}"></div><div><label>Next action date</label><input id="cn" type="date" value="${esc(x.next_action_date||'')}"></div><div class="wide"><label>Notes</label><textarea id="cnotes">${esc(x.notes||'')}</textarea></div><div class="wide"><button class="btn primary" onclick="saveCompliance('${esc(id)}')">Save compliance</button></div></div>`;$('results').innerHTML=`<div class="muted">Current record loaded for ${esc(id)}.</div>`;}catch(e){msg(e.message,false);}}
async function saveCompliance(id){try{await api(`/ops/compliance/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({filing_compliance:$('cf').value,payment_compliance:$('cp').value,risk_flags:$('cr').value.split(',').map(x=>x.trim()).filter(Boolean),next_action_date:$('cn').value||null,notes:$('cnotes').value})});msg('Compliance record updated.');await openCompliance();}catch(e){msg(e.message,false);}}

async function loadPayments(){
  $('controls').innerHTML=`<div class="toolbar"><div class="field"><label>Taxpayer ID filter</label><input id="payTp"></div><button class="btn primary" id="payLoad">Load liabilities</button></div>`;$('payLoad').onclick=loadPayments;const q=$('payTp').value.trim();const data=await api('/ops/liabilities'+(q?'?taxpayer_id='+encodeURIComponent(q):''));
  $('results').innerHTML=data.items.length?`<table class="data"><thead><tr><th>Liability</th><th>Taxpayer</th><th>Original</th><th>Allocated</th><th>Open balance</th><th>Actions</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.description||x.id)}</td><td>${esc(x.taxpayer_id)}</td><td class="money">${money(x.original_amount)}</td><td class="money">${money(x.allocated_amount)}</td><td class="money">${money(x.open_balance)}</td><td><div class="quick-actions"><button class="btn secondary" onclick="allocatePayment('${x.id}','${x.taxpayer_id}',${x.open_balance})">Allocate</button><button class="btn secondary" onclick="createInstallment('${x.id}','${x.taxpayer_id}',${x.open_balance})">Installments</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No liabilities found.</div>';
}
async function allocatePayment(lid,tp,balance){const amount=Number(prompt(`Allocation amount (open balance ${balance})`)||0);if(!amount)return;const ref=prompt('Payment/reference number')||'';try{const r=await api('/ops/payments/allocations',{method:'POST',body:JSON.stringify({taxpayer_id:tp,liability_id:lid,amount,payment_reference:ref})});msg(`Payment allocation ${r.id} recorded.`);await loadPayments();}catch(e){msg(e.message,false);}}
async function createInstallment(lid,tp,balance){const total=Number(prompt(`Total to schedule (max ${balance})`)||0);const count=Number(prompt('Number of installments')||0);if(!total||!count)return;try{await api('/ops/installments',{method:'POST',body:JSON.stringify({taxpayer_id:tp,liability_id:lid,total_amount:total,installment_count:count,frequency:'monthly',start_date:new Date().toISOString().slice(0,10)})});msg('Installment plan created.');}catch(e){msg(e.message,false);}}

async function loadNotices(){
  $('controls').innerHTML=`<div class="editor"><div><label>Taxpayer ID</label><input id="noticeTp"></div><div><label>Notice type</label><input id="noticeType" value="general"></div><div class="wide"><label>Subject</label><input id="noticeSubject"></div><div class="wide"><label>Content</label><textarea id="noticeContent" rows="4"></textarea></div><div class="wide"><button class="btn primary" id="noticeCreate">Create draft notice</button></div></div>`;
  $('noticeCreate').onclick=async()=>{try{await api('/ops/notices',{method:'POST',body:JSON.stringify({taxpayer_id:$('noticeTp').value.trim(),notice_type:$('noticeType').value.trim(),subject:$('noticeSubject').value,content:$('noticeContent').value})});msg('Notice draft created.');await loadNotices();}catch(e){msg(e.message,false);}};
  const data=await api('/ops/notices');$('results').innerHTML=data.items.length?`<table class="data"><thead><tr><th>Subject</th><th>Taxpayer</th><th>Type</th><th>Status</th><th>Actions</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.subject)}</td><td>${esc(x.taxpayer_id)}</td><td>${esc(x.notice_type)}</td><td><span class="status">${esc(x.status)}</span></td><td><button class="btn secondary" onclick="updateNotice('${x.id}','${x.status}')">Change status</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No notices yet.</div>';
}
async function updateNotice(id,current){const status=prompt(`Current: ${current}. New status? approved, issued, cancelled, archived`);if(!status)return;const reason=prompt('Reason / note')||null;try{await api(`/ops/notices/${id}`,{method:'PATCH',body:JSON.stringify({status,reason})});msg('Notice updated.');await loadNotices();}catch(e){msg(e.message,false);}}

async function loadCases(){
  $('controls').innerHTML=`<div class="editor"><div><label>Taxpayer ID</label><input id="caseTp"></div><div><label>Case type</label><input id="caseType" value="compliance"></div><div><label>Priority</label><select id="casePriority"><option>normal</option><option>high</option><option>urgent</option><option>low</option></select></div><div><label>Assigned to</label><input id="caseAssigned"></div><div class="wide"><label>Title</label><input id="caseTitle"></div><div class="wide"><label>Description</label><textarea id="caseDesc"></textarea></div><div class="wide"><button class="btn primary" id="caseCreate">Create case</button></div></div>`;
  $('caseCreate').onclick=async()=>{try{await api('/ops/cases',{method:'POST',body:JSON.stringify({taxpayer_id:$('caseTp').value.trim(),case_type:$('caseType').value.trim(),title:$('caseTitle').value,description:$('caseDesc').value,priority:$('casePriority').value,assigned_to:$('caseAssigned').value||null})});msg('Case created.');await loadCases();}catch(e){msg(e.message,false);}};
  const data=await api('/ops/cases');$('results').innerHTML=data.items.length?`<table class="data"><thead><tr><th>Case</th><th>Taxpayer</th><th>Priority</th><th>Status</th><th>Assigned</th><th>Actions</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.title)}<div class="muted">${esc(x.case_type)}</div></td><td>${esc(x.taxpayer_id)}</td><td>${esc(x.priority)}</td><td><span class="status">${esc(x.status)}</span></td><td>${esc(x.assigned_to||'—')}</td><td><div class="quick-actions"><button class="btn secondary" onclick="updateCase('${x.id}','${x.status}')">Status</button><button class="btn secondary" onclick="addCaseEvent('${x.id}')">Timeline event</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No cases yet.</div>';
}
async function updateCase(id,current){const status=prompt(`Current: ${current}. New status? suspended, reopened, closed, voided, archived`);if(!status)return;const reason=prompt('Reason (required)')||'';try{await api(`/ops/cases/${id}`,{method:'PATCH',body:JSON.stringify({status,reason})});msg('Case updated.');await loadCases();}catch(e){msg(e.message,false);}}
async function addCaseEvent(id){const type=prompt('Event type');if(!type)return;const note=prompt('Event note')||'';try{await api(`/ops/cases/${id}/events`,{method:'POST',body:JSON.stringify({event_type:type,note,metadata:{}})});msg('Case timeline event added.');}catch(e){msg(e.message,false);}}

async function loadReports(){
  $('controls').innerHTML=`<div class="toolbar"><div class="field"><label>Start date</label><input id="repStart" type="date"></div><div class="field"><label>End date</label><input id="repEnd" type="date"></div><div class="field"><label>Status filter</label><input id="repStatus" placeholder="Optional"></div><button class="btn primary" id="repRun">Run report</button></div>`;$('repRun').onclick=runReport;await runReport();
}
async function runReport(){const p=new URLSearchParams();if($('repStart')?.value)p.set('start',$('repStart').value);if($('repEnd')?.value)p.set('end',$('repEnd').value);if($('repStatus')?.value)p.set('status',$('repStatus').value);const d=await api('/ops/reports/summary?'+p.toString());const rows=[['Returns',d.returns.count,'—'],['Assessments',d.assessments.count,money(d.assessments.total)],['Liabilities',d.liabilities.count,money(d.liabilities.total)],['Payments',d.payments.count,money(d.payments.total)],['Compliance records',d.compliance.count,'—'],['Cases',d.cases.count,'—'],['Notices',d.notices.count,'—']];$('results').innerHTML=`<table class="data"><thead><tr><th>Category</th><th>Count</th><th>Total</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td class="money">${r[2]}</td></tr>`).join('')}</tbody></table>`;}

$('loginBtn').onclick=login;$('verifyBtn').onclick=verifyMfa;$('signOutBtn').onclick=signOut;$('refreshBtn').onclick=loadModule;
validateSession();
