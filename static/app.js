const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = v => v ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(v)) : '—';
const states = {CONFIRMED:'待领取',CANCELLED:'已取消',EXPIRED:'已过期',BORROWED:'借用中',RETURNED:'已归还'};
let user, page='devices', devices=[], filter='', category='', overdueOnly=false;
const retryKeys = new Map();
async function api(path, method='GET', body) {
  const fingerprint=JSON.stringify([path,method,body]);
  let key=retryKeys.get(fingerprint);
  if(method!=='GET'&&!key){key=crypto.randomUUID();retryKeys.set(fingerprint,key);}
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':user?.csrf||'','Idempotency-Key':key||''},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(response.status<500)retryKeys.delete(fingerprint);
  if(!response.ok){if(response.status===401&&path!=='/api/session'){user=null;showAuth();}throw new Error(`${data.message}（${data.code}）`);}
  return data;
}
function toast(message,error=false){$('#toast').textContent=message;$('#toast').className=error?'error':'';$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,4500);}
function showAuth(){ $('#login').hidden=!!user;$('#app').hidden=!user;if(user){$('#userName').textContent=user.username;$('#userRole').textContent=user.role==='ADMIN'?'设备管理员':'普通用户';document.querySelectorAll('.admin-only').forEach(e=>e.hidden=user.role!=='ADMIN');}}
$('#loginForm').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{user=(await api('/api/session','POST',{username:$('#username').value,password:$('#password').value})).user;$('#password').value='';$('#loginError').textContent='';page='devices';showAuth();await render();}catch(error){$('#loginError').textContent=error.message;}finally{button.disabled=false;}});
$('#logout').onclick=async()=>{try{await api('/api/session','DELETE');user=null;showAuth();}catch(e){toast(e.message,true);}};
document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>{page=button.dataset.page;render().catch(e=>toast(e.message,true));});
$('#closeDetail').onclick=()=>$('#detail').close();
const titles={devices:'设备中心',mine:'我的预约',admin:'借还管理',audit:'操作记录'};
const head=(title,subtitle)=>`<div class="page-head"><div><p class="eyebrow">EQUIPRESERVE / 工作台</p><h1>${title}</h1><p class="muted">${subtitle}</p></div><button id="refresh">↻ 刷新</button></div>`;
async function render(){
  document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('#breadcrumb').textContent=titles[page];
  if(page==='devices'){
    devices=(await api('/api/devices?size=100')).items;
    $('#content').innerHTML=head('找到适合你的设备','查看设备与开放时段，为下一次创作做好准备。')+`<div class="stats"><div class="stat"><span>设备总数</span><strong>${devices.length.toString().padStart(2,'0')}</strong></div><div class="stat"><span>启用设备</span><strong>${devices.filter(d=>d.enabled).length.toString().padStart(2,'0')}</strong></div><div class="stat"><span>正在借出</span><strong>${devices.filter(d=>d.current_loan_id).length.toString().padStart(2,'0')}</strong></div></div><div class="filters"><input id="search" aria-label="搜索设备" placeholder="搜索设备名称或资产编号…" value="${esc(filter)}"><select id="category" aria-label="设备分类"><option value="">全部分类</option>${[...new Set(devices.map(d=>d.category))].map(c=>`<option ${category===c?'selected':''}>${esc(c)}</option>`).join('')}</select></div><div id="cards" class="grid"></div><div class="notice">预约须知 · 开放今天起 14 个自然日；每日 09:00–12:00 / 14:00–18:00。请在开始后的 15 分钟内由管理员办理领取，时间均为北京时间。</div>`;
    $('#search').oninput=e=>{filter=e.target.value;cards();};$('#category').onchange=e=>{category=e.target.value;cards();};cards();
  }else if(page==='audit'){
    const rows=(await api('/api/admin/audit')).items;
    $('#content').innerHTML=head('操作记录','最近 200 条关键业务操作与失败原因。')+table(['时间','操作者','操作 / 对象','状态变化','原因 / 请求编号'],rows.map(r=>`<tr><td>${fmt(r.created_at)}</td><td>${esc(r.username||'系统')}</td><td>${esc(r.action)} #${r.target_id||'—'}</td><td>${esc(r.before_state||'—')} → ${esc(r.after_state||'—')}</td><td>${esc(r.reason||'成功')}<small>${esc(r.request_id)}</small></td></tr>`));
  }else{
    let rows=(await api(page==='mine'?'/api/me/reservations':'/api/admin/reservations')).items;
    const overdue=rows.filter(r=>r.overdue).length;
    if(page==='admin'&&overdueOnly)rows=rows.filter(r=>r.overdue);
    $('#content').innerHTML=head(titles[page],page==='mine'?'每一次预约，都有迹可循。最多显示最近 500 条记录。':'确认实物交接后再办理借还。最多显示最近 500 条记录。')+(page==='admin'?`<div class="filters"><button id="overdue">${overdueOnly?'查看全部':'仅看逾期'} · ${overdue}</button></div>`:'')+table(['设备','使用时段','状态','借还时间','操作'],rows.map(r=>`<tr><td><b>${esc(r.name)}</b><small>${esc(r.asset_code)} · #${r.id}${page==='admin'?' · '+esc(r.username):''}</small></td><td>${fmt(r.slot_start)}<small>至 ${fmt(r.slot_end)}</small></td><td><span class="badge ${r.overdue?'warn':''}">${r.overdue?'逾期未归还':states[r.status]}</span>${r.exception?`<small class="warning">${esc(r.exception)}</small>`:''}</td><td>领 ${fmt(r.borrowed_at)}<small>还 ${fmt(r.returned_at)}</small></td><td>${r.status==='CONFIRMED'?`<button data-action="cancel" data-id="${r.id}">取消</button>`:''}${page==='admin'&&r.status==='CONFIRMED'?`<button data-action="checkout" data-id="${r.id}">办理领取</button>`:''}${page==='admin'&&r.status==='BORROWED'?`<button data-action="return" data-id="${r.id}">确认归还</button>`:''}</td></tr>`));
    if($('#overdue'))$('#overdue').onclick=()=>{overdueOnly=!overdueOnly;render().catch(e=>toast(e.message,true));};
    document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const action=b.dataset.action;if(!confirm(`确定${b.textContent}预约 #${b.dataset.id}？`))return;await api(`/api/${action==='cancel'?'':'admin/'}reservations/${b.dataset.id}/${action}`,'POST',{});toast('操作成功');await render();}catch(e){toast(e.message,true);}finally{b.disabled=false;}});
  }
  $('#refresh').onclick=()=>render().catch(e=>toast(e.message,true));
}
function table(headers,rows){return rows.length?`<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:'<div class="table-wrap empty">暂无记录。预约设备后，可以在这里查看进度。</div>';}
function cards(){const list=devices.filter(d=>(!category||category===d.category)&&`${d.name} ${d.asset_code}`.toLowerCase().includes(filter.toLowerCase()));$('#cards').innerHTML=list.length?list.map(d=>`<article class="card"><div class="device-art" aria-hidden="true">${{'影像设备':'◎','开发硬件':'▦','音频设备':'♬','演示设备':'▣'}[d.category]||'▦'}</div><div class="card-body"><div class="card-top"><span>${esc(d.category)} / ${esc(d.asset_code)}</span><span class="badge ${!d.enabled?'off':d.current_loan_id?'warn':''}">${!d.enabled?'已停用':d.current_loan_id?'借出中':'已启用'}</span></div><h3>${esc(d.name)}</h3><p>${esc(d.description)}</p><button data-device="${d.id}">查看可预约时段 →</button>${user.role==='ADMIN'?`<button data-toggle="${d.id}">${d.enabled?'停用设备':'启用设备'}</button>`:''}</div></article>`).join(''):'<p class="muted">没有符合条件的设备。</p>';
document.querySelectorAll('[data-device]').forEach(b=>b.onclick=()=>detail(Number(b.dataset.device)).catch(e=>toast(e.message,true)));
document.querySelectorAll('[data-toggle]').forEach(b=>b.onclick=async()=>{const d=devices.find(d=>d.id===Number(b.dataset.toggle));if(!confirm(`${d.enabled?'停用':'启用'} ${d.name}？已有预约将保留。`))return;b.disabled=true;try{await api('/api/admin/devices/'+d.id,'PATCH',{enabled:!d.enabled});await render();toast('设备状态已更新');}catch(e){toast(e.message,true);b.disabled=false;}});}
async function detail(id){const data=await api(`/api/devices/${id}/slots`);$('#detailBody').innerHTML=`<p class="eyebrow">${esc(data.device.asset_code)} / ${esc(data.device.category)}</p><h2>${esc(data.device.name)}</h2><p class="muted">${esc(data.device.description)}</p>${data.device.current_loan_id?'<p class="warning">当前实物尚未归还。可预约后续时段，领取需等待上一笔归还。</p>':''}<div class="slot-grid">${data.slots.map(s=>`<button class="slot" data-slot="${esc(s.slotStart)}" ${s.available?'':'disabled'}><span>${fmt(s.slotStart)} — ${fmt(s.slotEnd).split(' ').pop()}</span><small>${esc(s.reason||'可预约 · 点击确认')}</small></button>`).join('')}</div>`;if(!$('#detail').open)$('#detail').showModal();document.querySelectorAll('[data-slot]').forEach(b=>b.onclick=async()=>{if(!confirm(`预约 ${data.device.name}，${fmt(b.dataset.slot)}？`))return;b.disabled=true;try{const result=await api('/api/reservations','POST',{deviceId:id,slotStart:b.dataset.slot});toast(`预约成功，编号 #${result.id}`);await detail(id);}catch(e){toast(e.message,true);b.disabled=false;}});}
api('/api/session').then(data=>{user=data.user;showAuth();return render();}).catch(()=>showAuth());
