'use strict';
(async()=>{
  const {$,esc,icon,fileIcon,refreshIcons,size,date,badge,actions,api,toast,dialog,close,copy,preview}=FS;
  const base='/api/file-share/admin';
  const sections=[['overview','概览','layout-dashboard','让每一次文件交付，简单而有序。'],['files','文件','files','管理文件，为它们创建安全的分享链接。'],['shares','分享','link','决定谁可以访问，以及何时结束。'],['logs','访问记录','activity','查看每一次访问、预览与下载请求。'],['trash','回收站','trash-2','误删的文件可以恢复，永久删除前会再次确认。'],['settings','设置','settings-2','分享中心的独立偏好设置。']];
  let section='overview',page=1,filters={search:'',type:'',sort:'newest'},currentFiles=[],selected=new Map(),renderId=0,captchaId='',uploading=false;

  let fileView='list',fileRefreshBusy=false,lastFileRefresh=0;
  try{fileView=localStorage.getItem('cloud-file-view')||'list';}catch{}
  if(!['list','small','large'].includes(fileView))fileView='list';
  let logRefreshTimer,logRefreshAttempts=0;
  const loadedBuild=document.querySelector('meta[name="file-share-build"]').content;
  let checkingVersion=false,pendingBuild='',snoozedBuild='',snoozedUntil=0;
  async function checkVersion(){
    if(checkingVersion||document.hidden||$('app').hidden)return;
    checkingVersion=true;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
    try{
      const response=await fetch(base+'/version',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if(!response.ok)return;
      const info=await response.json();
      if(!info.build_id||info.build_id===loadedBuild){$('updateNotice').hidden=true;pendingBuild='';return;}
      pendingBuild=info.build_id;
      if(snoozedBuild===pendingBuild&&Date.now()<snoozedUntil)return;
      $('updateMeta').textContent='v'+info.version+' · '+info.build_id;
      $('updateNotice').hidden=false;
    }catch{}finally{clearTimeout(timeout);checkingVersion=false;}
  }
  $('snoozeUpdate').onclick=()=>{snoozedBuild=pendingBuild;snoozedUntil=Date.now()+10*60*1000;$('updateNotice').hidden=true;};
  $('refreshUpdate').onclick=()=>{
    if(uploading){toast('文件正在上传，请等待上传完成后再刷新更新');return;}
    if($('dialog').open){toast('请先完成或关闭当前弹窗，再刷新更新');return;}
    location.reload();
  };
  setInterval(checkVersion,60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkVersion();});
  window.addEventListener('focus',checkVersion);

  async function captcha(){const data=await api('/api/captcha');captchaId=data.captcha_id;$('captchaImage').src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(data.image_svg);}
  async function authenticated(){const me=await api('/api/me');if(!me.authenticated||me.user.role!=='admin'){$('login').hidden=false;$('app').hidden=true;await Promise.all([captcha(),loadSmsConfig()]);refreshIcons();return false;}$('login').hidden=true;$('app').hidden=false;$('account').textContent=me.user.display_name||me.user.username;await navigate(location.hash.slice(1)||'overview');checkVersion();return true;}
  $('captchaRefresh').onclick=()=>captcha().catch(e=>toast(e.message));

  let loginMode='password',smsConfigured=false,smsChallenge='',smsPhone='',smsSending=false,loginBusy=false,smsUntil=0,smsTimer;
  const loginCaptcha=$('loginForm').elements.captcha;
  function setLoginMode(mode){
    if(loginBusy||smsSending)return;
    loginMode=mode==='sms'&&smsConfigured?'sms':'password';
    for(const [key,id] of [['password','passwordFields'],['sms','smsFields']]){
      const active=key===loginMode;$(id).hidden=!active;
      $(id).querySelectorAll('input').forEach(input=>input.disabled=!active);
      $(key+'LoginTab').setAttribute('aria-pressed',String(active));
    }
    const captchaField=$('captchaField');
    const passwordMode=loginMode==='password';
    captchaField.hidden=!passwordMode;
    loginCaptcha.disabled=!passwordMode;
    loginCaptcha.required=passwordMode;
    $('loginError').textContent='';
  }
  function smsCountdown(){
    const seconds=Math.max(0,Math.ceil((smsUntil-Date.now())/1000));
    $('sendSms').disabled=smsSending||loginBusy||seconds>0||!smsConfigured;
    $('sendSms').textContent=smsSending?'发送中…':seconds>0?seconds+' 秒后重发':'获取验证码';
    if(!seconds&&smsTimer){clearInterval(smsTimer);smsTimer=null;}
  }
  function startCountdown(seconds){smsUntil=Date.now()+Math.max(1,Math.min(600,Number(seconds)||60))*1000;clearInterval(smsTimer);smsTimer=setInterval(smsCountdown,500);smsCountdown();}
  async function loadSmsConfig(){
    try{smsConfigured=Boolean((await api('/api/sms-login/config')).sms_auth?.configured);}catch{smsConfigured=false;}
    $('smsLoginTab').disabled=!smsConfigured;
    $('smsAvailability').textContent=smsConfigured?'短信登录仅支持已绑定并启用的管理员手机号。':'短信登录暂不可用，请使用账号密码登录。';
    setLoginMode(loginMode);smsCountdown();
  }
  $('passwordLoginTab').onclick=()=>setLoginMode('password');
  $('smsLoginTab').onclick=()=>setLoginMode('sms');
  $('smsPhone').oninput=()=>{smsChallenge='';smsPhone='';$('smsCode').value='';};
  $('smsCode').oninput=()=>{$('smsCode').value=$('smsCode').value.replace(/\D/g,'').slice(0,6);};
  const normalizedPhone=()=> $('smsPhone').value.trim().replace(/^\+?86/,'');
  $('sendSms').onclick=async()=>{
    if(smsSending||loginBusy||Date.now()<smsUntil||!smsConfigured)return;
    const phone=normalizedPhone();
    if(!/^1[3-9]\d{9}$/.test(phone)){$('loginError').textContent='请输入正确的中国大陆手机号';$('smsPhone').focus();return;}
    smsSending=true;smsCountdown();$('smsPhone').disabled=true;$('loginSubmit').disabled=true;$('loginError').textContent='';
    try{
      const result=await api('/api/sms-login/send',{phone});
      smsChallenge=result.challenge_id;smsPhone=phone;$('smsCode').value='';
      startCountdown(result.resend_after);$('smsNotice').textContent=result.message||'验证码已发送，请查看手机短信。';$('smsCode').focus();
    }catch(error){$('loginError').textContent=error.message;if(error.status===429)startCountdown(60);}
    finally{smsSending=false;$('smsPhone').disabled=false;$('loginSubmit').disabled=false;smsCountdown();}
  };
  $('loginForm').onsubmit=async event=>{
    event.preventDefault();if(loginBusy||smsSending)return;
    const mode=loginMode,button=$('loginSubmit');loginBusy=true;button.disabled=true;smsCountdown();$('loginError').textContent='';
    try{
      let result;
      if(mode==='sms'){
        const phone=normalizedPhone();
        if(!smsChallenge||phone!==smsPhone)throw new Error('请先获取当前手机号的短信验证码');
        if(!/^\d{6}$/.test($('smsCode').value))throw new Error('请输入6位短信验证码');
        result=await api('/api/sms-login/verify',{phone,code:$('smsCode').value,challenge_id:smsChallenge});
      }else{
        const data=Object.fromEntries(new FormData(event.target));data.captcha_id=captchaId;
        result=await api('/api/login',data);
      }
      if(result.user?.role!=='admin')throw new Error('该账号没有管理员权限，请使用管理员账号登录');
      clearInterval(smsTimer);smsChallenge='';$('smsCode').value='';$('loginForm').elements.password.value='';
      await authenticated();
    }catch(error){$('loginError').textContent=error.message;if(mode==='password'){loginCaptcha.value='';try{await captcha();}catch{}}}
    finally{loginBusy=false;button.disabled=false;smsCountdown();}
  };

  $('logout').onclick=async()=>{await api('/api/logout',{});location.reload();};
  $('nav').innerHTML=sections.map(([key,label,image])=>`<button data-section="${key}">${icon(image)}${label}</button>`).join('');
  $('nav').onclick=e=>{const b=e.target.closest('[data-section]');if(b)navigate(b.dataset.section).catch(error=>toast(error.message));};
  async function navigate(next){clearTimeout(logRefreshTimer);logRefreshAttempts=0;section=sections.some(s=>s[0]===next)?next:'overview';page=1;history.replaceState(null,'','#'+section);await render();}
  function empty(message='这里还没有内容',image='inbox'){return `<div class="empty">${icon(image)}<p>${esc(message)}</p></div>`;}
  function pagination(total){return `<div class="pagination"><span>共 ${total} 条 · 第 ${page} / ${Math.max(1,Math.ceil(total/20))} 页</span><button data-page="${page-1}" ${page<=1?'disabled':''}>上一页</button><button data-page="${page+1}" ${page*20>=total?'disabled':''}>下一页</button></div>`;}
  function logTable(logs){if(!logs.length)return empty('暂无访问记录','activity');return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>访问者 IP</th><th>IP 归属地</th><th>浏览器 / 系统</th><th>行为</th><th>文件 / 分享</th><th>结果</th></tr></thead><tbody>${logs.map(l=>`<tr><td>${date(l.created_at)}</td><td>${esc(l.ip)}</td><td>${esc([...new Set([l.country,l.province,l.city].filter(Boolean))].join(' / ')||(l.geolocation_status==='pending'?'查询中…':'—'))}</td><td>${esc(l.browser)} / ${esc(l.os)}<br><small>${esc(l.device)}</small></td><td>${esc(actions[l.action]||l.action)}</td><td>${esc(l.filename||l.title)}</td><td>${l.success?'成功':'<span class="error">未通过</span>'}</td></tr>`).join('')}</tbody></table></div><p class="geo-attribution muted">IP geolocation by <a href="https://www.ip2location.io" target="_blank" rel="noopener noreferrer">IP2Location.io</a></p>`;}
  function sharesTable(rows){if(!rows.length)return empty('还没有分享，先上传文件再创建链接','link');return `<div class="table-wrap"><table><thead><tr><th>分享标题</th><th>状态</th><th>访问</th><th>下载</th><th>有效期</th><th>操作</th></tr></thead><tbody>${rows.map(s=>`<tr><td><strong>${esc(s.title)}</strong>${s.password_required?' '+icon('lock-keyhole'):''}<br><small>${date(s.created_at)}</small></td><td>${badge(s.status)}</td><td>${s.view_count}${s.max_views?' / '+s.max_views:''}</td><td>${s.download_count}${s.max_downloads?' / '+s.max_downloads:''}</td><td>${date(s.expires_at)}</td><td><div class="table-actions"><button data-detail="${s.id}">详情</button><button data-copy="${esc(s.url)}">复制链接</button></div></td></tr>`).join('')}</tbody></table></div>`;}
  async function render(quiet=false){
    closeFileMenu();
    clearTimeout(logRefreshTimer);
    const requestId=++renderId;const def=sections.find(s=>s[0]===section);$('breadcrumb').textContent=def[1];$('pageTitle').textContent=def[1];$('pageDescription').textContent=def[3];document.querySelectorAll('[data-section]').forEach(b=>b.classList.toggle('active',b.dataset.section===section));if(!quiet)$('content').innerHTML=empty('正在加载…','loader-circle');refreshIcons();
    let html='',pendingLocations=false;
    if(section==='overview'){
      const d=await api(base+'/overview');html=`<div class="stats">${[['文件总数',d.file_count,'files'],['总存储量',size(d.total_size),'hard-drive'],['有效分享',d.active_shares,'link'],['今日访问',d.today_views,'eye'],['今日下载',d.today_downloads,'download']].map(([label,value,image])=>`<div class="stat"><div class="stat-label">${icon(image)}${label}</div><div class="stat-value">${value}</div></div>`).join('')}</div><div class="grid-two"><section class="panel"><div class="panel-header"><h3>最近分享</h3><button data-go="shares" class="quiet">查看全部 ${icon('arrow-up-right')}</button></div>${d.recent_shares.length?d.recent_shares.map(s=>`<div class="list-row"><span class="file-icon">${icon('link')}</span><div class="list-main"><strong>${esc(s.title)}</strong><small>${s.view_count} 次访问 · ${date(s.created_at)}</small></div>${badge(s.status)}<button class="icon-button quiet" data-detail="${s.id}" aria-label="查看分享详情">${icon('chevron-right')}</button></div>`).join(''):empty('上传第一份文件，开始分享','folder-output')}</section><section class="panel"><div class="panel-header"><h3>最近访问</h3><button data-go="logs" class="quiet">查看全部 ${icon('arrow-up-right')}</button></div>${d.recent_logs.length?d.recent_logs.map(l=>`<div class="list-row"><span class="file-icon">${icon(l.action==='DOWNLOAD_FILE'?'download':'eye')}</span><div class="list-main"><strong>${esc(actions[l.action])} · ${esc(l.filename||l.title)}</strong><small>${esc(l.ip)} · ${esc(l.browser)} · ${date(l.created_at)}</small></div>${l.success?'':'<span class="error">失败</span>'}</div>`).join(''):empty('分享后的访问足迹会出现在这里','activity')}</section></div>`;
    }else if(section==='files'||section==='trash'){
      const params=new URLSearchParams({...filters,page,trash:section==='trash'?'1':'0'});const d=await api(base+'/files?'+params);if(requestId!==renderId)return;currentFiles=d.items;lastFileRefresh=Date.now();d.items.forEach(f=>{if(selected.has(f.id))selected.set(f.id,f);});
      html=(section==='files'?`<div id="dropzone" class="dropzone" role="button" tabindex="0">${icon('cloud-upload')} 拖拽文件到这里，或点击选择文件 <small>· 单文件最大 500 MB</small></div>`:'')+`<div class="toolbar"><input id="searchFiles" placeholder="搜索文件名" aria-label="搜索文件名" value="${esc(filters.search)}"><select id="typeFilter" aria-label="文件类型"><option value="">全部类型</option>${['IMAGE','VIDEO','AUDIO','PDF','WORD','EXCEL','PPT','ARCHIVE','TEXT','OTHER'].map(t=>`<option ${filters.type===t?'selected':''}>${t}</option>`).join('')}</select><select id="sortFilter" aria-label="上传时间排序"><option value="newest" ${filters.sort==='newest'?'selected':''}>最新上传</option><option value="oldest" ${filters.sort==='oldest'?'selected':''}>最早上传</option></select><button id="searchButton">搜索</button><button id="refreshFiles" aria-label="刷新文件">${icon('refresh-cw')}刷新</button>${section==='files'?`<div class="view-switch" role="group" aria-label="文件展示方式">${[['list','列表','list'],['small','小图标','grid-2x2'],['large','大图标','layout-grid']].map(([key,label,img])=>`<button data-view="${key}" aria-pressed="${fileView===key}" title="${label}">${icon(img)}<span>${label}</span></button>`).join('')}</div>`:''}</div>`;
      html+=section==='files'&&fileView!=='list'?iconFiles(d.items):d.items.length?`<div class="table-wrap"><table><thead><tr>${section==='files'?'<th><input type="checkbox" id="selectAll" aria-label="选择本页全部文件"></th>':''}<th>文件名</th><th>大小</th><th>上传时间</th><th>分享</th><th>访问 / 下载</th><th>操作</th></tr></thead><tbody>${d.items.map(f=>`<tr>${section==='files'?`<td><input type="checkbox" data-select="${f.id}" aria-label="选择 ${esc(f.filename)}" ${selected.has(f.id)?'checked':''}></td>`:''}<td><div class="file-cell">${fileIcon(f)}<span class="filename">${esc(f.filename)}<br><small>${f.file_type}</small></span></div></td><td>${size(f.size)}</td><td>${date(f.created_at)}</td><td>${f.active_share_count?'分享中':'未分享'}<br><small>累计 ${f.share_count} 次</small></td><td>${f.view_count} / ${f.download_count}</td><td><div class="table-actions">${section==='trash'?`<button data-file="${f.id}" data-action="restore">恢复</button><button data-file="${f.id}" data-action="purge" class="danger">永久删除</button>`:`<button data-file="${f.id}" data-action="preview">预览</button><button data-single-share="${f.id}">分享</button><button data-file="${f.id}" data-action="rename">重命名</button><button data-file="${f.id}" data-action="trash">回收站</button>`}</div></td></tr>`).join('')}</tbody></table></div>`:empty(section==='trash'?'回收站是空的':'暂无匹配文件','files');html+=pagination(d.total);if(section==='files')html='<div id="fileWorkspace">'+html+'</div>';
    }else if(section==='shares'){const d=await api(base+'/shares?page='+page);html=sharesTable(d.items)+pagination(d.total);
    }else if(section==='logs'){const d=await api(base+'/logs?page='+page);pendingLocations=d.items.some(l=>l.geolocation_status==='pending');html='<div class="toolbar"><button id="refreshLogs">'+icon('refresh-cw')+'刷新记录</button></div>'+logTable(d.items)+pagination(d.total);
    }else if(section==='settings'){
      const d=await api(base+'/settings');const pending=await api(base+'/uploads');html=`<section class="panel settings-form"><h3>分享设置</h3><form id="settingsForm"><label>分享者名称（可选）<input name="display_name" maxlength="80" value="${esc(d.display_name)}"></label><label>单文件最大体积（MB，最大 500）<input type="number" name="max_mb" min="0.01" max="500" step="0.01" value="${d.max_upload_bytes/1024**2}" required></label><button class="primary">保存设置</button></form><h3 class="section-title">对象存储</h3><p>${d.oss_configured?'<span class="badge">已连接现有 OSS</span>':'<span class="badge off">尚未配置 OSS</span>'}</p><p class="muted">Bucket：${esc(d.bucket||'—')}</p><div class="notice">复用现有存储配置，无需重复填写密钥。文件使用私有访问，预览与下载链接有效期为 5 分钟。上传采用分片直传。</div><h3 class="section-title">未完成上传</h3>${pending.items.length?pending.items.map(f=>`<div class="list-row"><div class="list-main"><strong>${esc(f.filename)}</strong><small>${size(f.size)} · ${date(f.created_at)}</small></div><button data-abort="${f.id}">清理</button></div>`).join(''):'<p class="muted">没有未完成的上传。</p>'}<p class="muted"><button type="button" class="quiet version-button" data-version>版本 ${esc(d.version)} · 更新记录</button></p></section>`;
    }
    if(requestId!==renderId)return;$('content').innerHTML=html;refreshIcons();bindContent();
    if(section==='logs'&&pendingLocations&&logRefreshAttempts<20){logRefreshAttempts++;logRefreshTimer=setTimeout(()=>render(true).catch(()=>{}),2000);}
  }
  function bindContent(){
    if($('refreshLogs'))$('refreshLogs').onclick=()=>{logRefreshAttempts=0;render(true).catch(e=>toast(e.message));};
    if($('refreshFiles'))$('refreshFiles').onclick=()=>refreshFiles(false);
    if($('dropzone')){const zone=$('dropzone');zone.onclick=()=>$('fileInput').click();zone.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('fileInput').click();}};}
    const workspace=$('fileWorkspace');
    if(workspace){
      workspace.ondragover=e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';workspace.classList.add('drag');}};
      workspace.ondragleave=e=>{if(!workspace.contains(e.relatedTarget))workspace.classList.remove('drag');};
      workspace.ondrop=e=>{e.preventDefault();workspace.classList.remove('drag');closeFileMenu();uploadFiles([...e.dataTransfer.files]).catch(error=>toast(error.message));};
      workspace.oncontextmenu=e=>{const tile=e.target.closest('[data-tile]');if(tile){e.preventDefault();openFileMenu(tile.dataset.tile,e.clientX,e.clientY,tile);}};
      workspace.onkeydown=e=>{const tile=e.target.closest('[data-tile]');if(tile&&(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10'))){e.preventDefault();const r=tile.getBoundingClientRect();openFileMenu(tile.dataset.tile,r.left,r.top,tile);}};
    }
    function search(){filters={search:$('searchFiles').value,type:$('typeFilter').value,sort:$('sortFilter').value};page=1;render().catch(e=>toast(e.message));}
    if($('searchButton')){$('searchButton').onclick=search;$('searchFiles').onkeydown=e=>{if(e.key==='Enter')search();};$('typeFilter').onchange=search;$('sortFilter').onchange=search;}
    if($('selectAll'))$('selectAll').onchange=e=>{currentFiles.forEach(f=>{if(e.target.checked)selected.set(f.id,f);else selected.delete(f.id);});document.querySelectorAll('[data-select]').forEach(box=>box.checked=e.target.checked);};
    if($('settingsForm'))$('settingsForm').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));try{await api(base+'/settings',{display_name:data.display_name,max_upload_bytes:Math.round(Number(data.max_mb)*1024**2)});toast('设置已保存');}catch(error){toast(error.message);}};
  }
  $('content').onchange=e=>{if(e.target.dataset.select){const file=currentFiles.find(f=>f.id===e.target.dataset.select);if(e.target.checked)selected.set(file.id,file);else selected.delete(file.id);}};
  $('content').onclick=async e=>{const b=e.target.closest('button');if(!b)return;try{
    if(b.dataset.view){fileView=b.dataset.view;try{localStorage.setItem('cloud-file-view',fileView);}catch{}return await render(true);}
    if(b.dataset.menu){const r=b.getBoundingClientRect();return openFileMenu(b.dataset.menu,r.left,r.bottom,b);}
    if(b.hasAttribute('data-version'))return await showVersion();
    if(b.dataset.abort)return confirmAction('清理未完成上传？','会清理该上传任务的 OSS 分片和未登记文件。',async()=>{await api(base+'/uploads/'+b.dataset.abort+'/abort',{});await render();});
    if(b.dataset.go)return await navigate(b.dataset.go);
    if(b.dataset.page){page=Number(b.dataset.page);return await render();}
    if(b.dataset.copy)return await copy(b.dataset.copy);
    if(b.dataset.detail)return await detail(b.dataset.detail);
    if(b.dataset.singleShare)return await shareForm(null,[currentFiles.find(f=>f.id===b.dataset.singleShare)]);
    if(b.dataset.file){const file=currentFiles.find(f=>f.id===b.dataset.file),action=b.dataset.action;
      if(action==='rename')return renameFile(file);
      if(action==='preview'){const d=await api(base+'/files/'+file.id+'/preview',{});return await preview(file,d.url);}
      return confirmAction(action==='purge'?'永久删除文件？':action==='trash'?'移入回收站？':'恢复文件？',action==='purge'?'OSS 原文件将永久删除，无法恢复。':action==='trash'?'已有分享将立即无法访问此文件。':'恢复后，仍有效的原分享可以再次访问此文件。',async()=>{await api(base+'/files/'+file.id+'/'+action,{});selected.delete(file.id);await render();toast('操作成功');});
    }
  }catch(error){toast(error.message);}};

  function iconFiles(files){
    return `<div class="file-grid ${fileView}" aria-label="文件图标区域">${files.length?files.map(f=>`<article class="file-tile" data-tile="${f.id}" tabindex="0" aria-label="${esc(f.filename)}"><input type="checkbox" data-select="${f.id}" aria-label="选择 ${esc(f.filename)}" ${selected.has(f.id)?'checked':''}>${fileIcon(f)}<span class="tile-name" title="${esc(f.filename)}">${esc(f.filename)}</span><button class="tile-menu icon-button quiet" data-menu="${f.id}" aria-label="${esc(f.filename)}的更多操作">${icon('ellipsis')}</button></article>`).join(''):empty('暂无匹配文件，可直接拖入文件上传','cloud-upload')}</div><p class="muted file-hint">右键文件或点击 ··· 查看详情与操作；拖入文件即可上传。</p>`;
  }
  let menuAnchor=null;
  function closeFileMenu(restore=false){$('fileContextMenu')?.remove();if(restore&&menuAnchor?.isConnected)menuAnchor.focus();menuAnchor=null;}
  function openFileMenu(id,x,y,anchor){
    closeFileMenu();const f=currentFiles.find(f=>f.id===id);if(!f)return;menuAnchor=anchor;
    const menu=document.createElement('div');menu.id='fileContextMenu';menu.className='file-context-menu';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','文件详情与操作');
    menu.innerHTML=`<strong>${esc(f.filename)}</strong><dl><dt>大小</dt><dd>${size(f.size)}</dd><dt>上传时间</dt><dd>${date(f.created_at)}</dd><dt>分享</dt><dd>${f.active_share_count?'分享中':'未分享'} · 累计 ${f.share_count} 次</dd><dt>访问 / 下载</dt><dd>${f.view_count} / ${f.download_count}</dd></dl><div class="context-actions"><button data-file="${f.id}" data-action="preview">${icon('eye')}预览</button><button data-single-share="${f.id}">${icon('link')}创建分享</button><button data-file="${f.id}" data-action="rename">${icon('pencil')}重命名</button><button data-file="${f.id}" data-action="trash" class="danger">${icon('trash-2')}移入回收站</button></div>`;
    document.body.append(menu);refreshIcons();const r=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(x,innerWidth-r.width-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-r.height-8))+'px';menu.querySelector('button').focus({preventScroll:true});
    menu.onclick=e=>{if(e.target.closest('button')){const handler=$('content').onclick;closeFileMenu();handler(e);}};
    menu.onkeydown=e=>{const buttons=[...menu.querySelectorAll('button')],index=buttons.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Tab'].includes(e.key)){e.preventDefault();buttons[(index+(e.key==='ArrowUp'||e.shiftKey?-1:1)+buttons.length)%buttons.length].focus();}};
  }
  document.addEventListener('pointerdown',e=>{if(!e.target.closest('#fileContextMenu'))closeFileMenu();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeFileMenu(true);});
  window.addEventListener('resize',()=>closeFileMenu());
  async function refreshFiles(automatic){
    if(!['files','trash'].includes(section)||document.hidden||$('app').hidden||fileRefreshBusy||!$('refreshFiles'))return;
    if(uploading||$('dialog').open||$('fileContextMenu')){if(!automatic)toast('请先完成当前上传或操作');return;}
    if(automatic&&(Date.now()-lastFileRefresh<5000||document.activeElement?.matches('#searchFiles, #typeFilter, #sortFilter')))return;
    fileRefreshBusy=true;const button=$('refreshFiles');if(button){button.disabled=true;button.setAttribute('aria-busy','true');}
    // Preserve filter text that has not yet been submitted, too.
    filters={search:$('searchFiles').value,type:$('typeFilter').value,sort:$('sortFilter').value};
    try{await render(true);if(!automatic)toast('文件已刷新');}catch(error){toast(error.message);}finally{fileRefreshBusy=false;if(button?.isConnected){button.disabled=false;button.removeAttribute('aria-busy');}}
  }
  window.addEventListener('focus',()=>refreshFiles(true));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshFiles(true);});

  async function showVersion(){
    const d=await api(base+'/version');
    const entries=d.changelog.split(/^## /m).slice(1).map(entry=>{
      const [heading,...lines]=entry.trim().split('\n');
      return '<section class="release-entry"><h3>'+esc(heading)+'</h3><ul>'+lines.filter(line=>line.startsWith('- ')).map(line=>'<li>'+esc(line.slice(2))+'</li>').join('')+'</ul></section>';
    }).join('');
    dialog('版本信息', '<div class="release-summary">'+icon('history')+'<div><strong>槑槑云 v'+esc(d.version)+'</strong><p class="muted">构建 '+esc(d.build_id)+'</p></div></div><div class="release-history">'+entries+'</div>');
  }
  $('versionButton').onclick=()=>showVersion().catch(e=>toast(e.message));
  function renameFile(file){
    const dot=file.filename.lastIndexOf('.'),ext=dot>0?file.filename.slice(dot):'',stem=ext?file.filename.slice(0,-ext.length):file.filename;
    dialog('重命名文件', '<form id="renameForm"><label>文件名称<div class="rename-input"><input id="renameName" name="name" maxlength="'+(240-ext.length)+'" value="'+esc(stem)+'" required autocomplete="off">'+(ext?'<span>'+esc(ext)+'</span>':'')+'</div></label><p class="muted">已有分享同步显示新名称，分享链接保持有效。</p><p id="renameError" class="inline-error" role="alert"></p><div class="form-footer"><button type="button" id="cancelRename">取消</button><button class="primary" type="submit">保存名称</button></div></form>');
    $('cancelRename').onclick=close;$('renameName').focus();$('renameName').select();
    $('renameForm').onsubmit=async e=>{
      e.preventDefault();const button=e.submitter;button.disabled=true;
      try{const stem=$('renameName').value.trim();if(!stem)throw new Error('请输入文件名称');const filename=stem+ext;
        await api(base+'/files/'+file.id+'/rename',{filename});
        if(selected.has(file.id))selected.set(file.id,{...file,filename});
        close();await render();toast('文件已重命名');
      }catch(error){if($('renameError'))$('renameError').textContent=error.message;else toast(error.message);button.disabled=false;}
    };
  }

  function confirmAction(title,message,fn){dialog(title,`<p>${esc(message)}</p><div class="form-footer"><button id="cancelAction">取消</button><button id="confirmAction" class="primary">确认</button></div>`);$('cancelAction').onclick=close;$('confirmAction').onclick=async()=>{const button=$('confirmAction');button.disabled=true;try{await fn();close();}catch(e){toast(e.message);button.disabled=false;}};}
  $('createShare').onclick=()=>shareForm(null,[...selected.values()]).catch(e=>toast(e.message));
  async function shareForm(existing=null,chosen=[]){
    let files=existing?existing.files.filter(f=>f.status==='READY'):chosen;
    if(!existing&&!files.length)files=(await api(base+'/files')).items;
    if(!files.length)return toast('请先上传文件');
    const s=existing||{};const initialTitle=s.title||(chosen.length===1?chosen[0].filename:'');
    dialog(existing?'编辑分享':'创建分享',`<form id="shareForm"><label>分享标题<input name="title" maxlength="120" value="${esc(initialTitle)}" required></label><label>分享说明<textarea name="description" maxlength="2000" placeholder="告诉对方这份文件的用途…">${esc(s.description||'')}</textarea></label>${existing?'':`<label>选择文件 <small>（${chosen.length?'已选文件':'最近 20 个文件；更多文件可在文件列表勾选'}）</small></label><div class="form-files">${files.map(f=>`<label><input type="checkbox" name="file_ids" value="${f.id}" ${chosen.length?'checked':''}>${esc(f.filename)} <small>${size(f.size)}</small></label>`).join('')}</div>`}<div class="form-grid"><label>有效期<select name="expiry" id="expiry"><option value="3600">1 小时</option><option value="86400">24 小时</option><option value="604800" ${existing?'':'selected'}>7 天</option><option value="2592000">30 天</option><option value="forever" ${existing&&!s.expires_at?'selected':''}>永久</option><option value="custom" ${existing&&s.expires_at?'selected':''}>自定义时间</option></select></label><label id="customExpiryLabel" ${existing&&s.expires_at?'':'hidden'}>到期时间<input type="datetime-local" id="customExpiry" value="${s.expires_at?localTime(s.expires_at):''}"></label><label>访问密码<select name="password_mode" id="passwordMode">${existing?'<option value="keep">保持现有设置</option>':''}<option value="off">关闭</option><option value="set" ${existing?'':'selected'}>开启 / 重设</option></select></label><label id="passwordLabel" ${existing?'hidden':''}>设置密码<input name="password" maxlength="128" minlength="4" autocomplete="new-password" placeholder="留空则自动生成"></label><label>最大访问次数<input name="max_views" type="number" min="1" max="1000000000" placeholder="不限" value="${s.max_views||''}"></label><label>最大下载次数<input name="max_downloads" type="number" min="1" max="1000000000" placeholder="不限" value="${s.max_downloads||''}"></label><label><input name="allow_preview" type="checkbox" ${s.allow_preview===0?'':'checked'}>允许在线预览</label><label><input name="allow_download" type="checkbox" ${s.allow_download===0?'':'checked'}>允许下载</label></div><div class="notice">预览也会向浏览器传输文件内容。关闭下载按钮无法阻止接收者保存已预览的内容。</div><p id="shareError" class="inline-error" role="alert"></p><div class="form-footer"><button type="button" id="cancelShare">取消</button><button class="primary" type="submit">${existing?'保存设置':'生成分享链接'}</button></div></form>`);
    $('expiry').onchange=()=>$('customExpiryLabel').hidden=$('expiry').value!=='custom';$('passwordMode').onchange=()=>$('passwordLabel').hidden=$('passwordMode').value!=='set';$('cancelShare').onclick=close;
    $('shareForm').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;const f=new FormData(e.target),expiry=f.get('expiry');const expires=expiry==='forever'?null:expiry==='custom'?Math.floor(new Date($('customExpiry').value).getTime()/1000):Math.floor(Date.now()/1000)+Number(expiry);if(expiry==='custom'&&!Number.isFinite(expires)){$('shareError').textContent='请选择有效的到期时间';button.disabled=false;return;}
      const data={title:f.get('title'),description:f.get('description'),expires_at:expires,password_mode:f.get('password_mode'),password:f.get('password'),max_views:f.get('max_views')||null,max_downloads:f.get('max_downloads')||null,allow_preview:f.has('allow_preview'),allow_download:f.has('allow_download'),file_ids:f.getAll('file_ids')};
      try{const result=await api(base+'/shares'+(existing?'/'+existing.id+'/edit':''),data);await render();await detail(existing?existing.id:result.id,result.generated_password);if(existing&&data.password_mode==='set'&&data.password)toast('密码已更新，请将新密码告知接收者');}catch(error){$('shareError').textContent=error.message;button.disabled=false;}
    };
  }
  function localTime(ts){const d=new Date(ts*1000);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
  async function detail(id,password){const s=await api(base+'/shares/'+id);dialog('分享详情',`<div class="actions">${badge(s.status)}${s.password_required?'<span class="muted">已开启密码</span>':''}</div><h2 style="margin-top:18px">${esc(s.title)}</h2><p class="muted">${esc(s.description)}</p><div class="share-link">${esc(s.url)}</div>${password?`<div class="notice">本次分享密码：<strong>${esc(password)}</strong><br>仅本次显示，请保存并发给接收者。</div>`:''}<div class="qr-row"><canvas id="qrCanvas" aria-label="分享二维码"></canvas><div class="actions"><button id="copyLink">${icon('copy')}复制链接</button><button id="downloadQR">${icon('qr-code')}下载二维码</button><a href="${esc(s.url)}" target="_blank" rel="noopener">打开分享页 ↗</a></div></div><p class="muted">创建于 ${date(s.created_at)}<br>有效期：${date(s.expires_at)}</p><div class="detail-stats">${[['访问 PV',s.view_count],['估算 UV',s.stats.uv],['独立 IP',s.stats.unique_ips],['预览',s.stats.previews],['下载请求',s.download_count]].map(([k,v])=>`<div><strong>${v}</strong><small>${k}</small></div>`).join('')}</div><div class="actions">${s.stored_status==='REVOKED'?'':`<button id="editShare">编辑设置</button><button id="toggleShare">${s.stored_status==='PAUSED'?'恢复':'暂停'}</button><button id="revokeShare" class="danger">立即撤回</button>`}</div><h3 class="section-title">文件列表</h3>${s.files.map(f=>`<div class="list-row">${fileIcon(f)}<div class="list-main"><strong>${esc(f.filename)}</strong><small>${size(f.size)} · ${esc(({READY:'可访问',TRASHED:'回收站',DELETED:'已删除'}[f.status]||f.status))}</small></div></div>`).join('')}<h3 class="section-title">最近访问记录</h3>${logTable(s.logs)}`);
    const qr=qrcode(0,'M');qr.addData(s.url);qr.make();const count=qr.getModuleCount(),scale=6,canvas=$('qrCanvas');canvas.width=canvas.height=(count+8)*scale;const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#283321';for(let y=0;y<count;y++)for(let x=0;x<count;x++)if(qr.isDark(y,x))ctx.fillRect((x+4)*scale,(y+4)*scale,scale,scale);
    $('copyLink').onclick=()=>copy(s.url);$('downloadQR').onclick=()=>{const a=document.createElement('a');a.href=canvas.toDataURL('image/png');a.download='share-'+s.share_code+'.png';a.click();};
    if($('editShare'))$('editShare').onclick=()=>shareForm(s).catch(e=>toast(e.message));
    if($('toggleShare'))$('toggleShare').onclick=async()=>{try{await api(base+'/shares/'+id+'/'+(s.stored_status==='PAUSED'?'resume':'pause'),{});await render();await detail(id);}catch(e){toast(e.message);}};
    if($('revokeShare'))$('revokeShare').onclick=()=>confirmAction('立即撤回分享？','原链接将失效，OSS 文件会保留。已发出的短期访问链接最多还可使用 5 分钟。',async()=>{await api(base+'/shares/'+id+'/revoke',{});await render();toast('分享已撤回');});refreshIcons();
  }
  $('uploadButton').onclick=()=>$('fileInput').click();$('fileInput').onchange=()=>{uploadFiles([...$('fileInput').files]);$('fileInput').value='';};
  async function uploadFiles(files){
    if(uploading)return toast('请等待当前上传队列完成');if(!files.length)return;uploading=true;let maximum;try{maximum=Math.min(500*1024**2,(await api(base+'/settings')).max_upload_bytes);}catch(error){uploading=false;toast(error.message);return;}$('uploads').hidden=false;
    for(const file of files){
      const row=document.createElement('div');row.className='upload-row';row.innerHTML=`<div class="upload-label"><span>${esc(file.name)} <small>${size(file.size)}</small></span><span class="upload-status">计算 SHA256…</span></div><progress max="100" value="0"></progress>`;$('uploadRows').append(row);const status=row.querySelector('.upload-status'),progress=row.querySelector('progress');let id;
      try{
        if(file.size>maximum)throw new Error('文件超过上传上限（'+size(maximum)+'）');
        const hasher=await hashwasm.createSHA256();hasher.init();for(let start=0;start<file.size;start+=8*1024*1024){hasher.update(new Uint8Array(await file.slice(start,start+8*1024*1024).arrayBuffer()));progress.value=10*(start/file.size);}
        const upload=await api(base+'/uploads',{filename:file.name,size:file.size,mime_type:file.type,sha256:hasher.digest()});id=upload.id;const parts=[];
        for(let n=1;n<=upload.part_count;n++){
          status.textContent=`上传 ${n} / ${upload.part_count}`;const start=(n-1)*upload.part_size,blob=file.slice(start,Math.min(file.size,start+upload.part_size));const bytes=new Uint8Array(await blob.arrayBuffer());const digest=await hashwasm.md5(bytes);const contentMd5=btoa(String.fromCharCode(...digest.match(/../g).map(h=>parseInt(h,16))));let etag;
          for(let retry=0;retry<3;retry++){try{const permit=await api(base+'/uploads/'+id+'/part',{part_number:n,content_md5:contentMd5});etag=await putPart(permit,blob,loaded=>progress.value=10+85*((start+loaded)/file.size));break;}catch(error){if(retry===2)throw error;status.textContent='网络波动，重试分片…';}}
          parts.push({part_number:n,etag});
        }
        status.textContent='校验文件…';await api(base+'/uploads/'+id+'/complete',{parts});progress.value=100;status.textContent='上传成功';
      }catch(error){status.textContent='失败：'+error.message;status.classList.add('error');if(id){try{await api(base+'/uploads/'+id+'/abort',{});}catch{const cleanup=document.createElement('button');cleanup.textContent='清理未完成上传';cleanup.onclick=async()=>{try{await api(base+'/uploads/'+id+'/abort',{});cleanup.remove();toast('上传已清理');}catch(e){toast(e.message);}};row.append(cleanup);}}}
    }
    uploading=false;await render();
  }
  function putPart(permit,blob,onProgress){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('PUT',permit.url);xhr.timeout=600000;for(const [k,v] of Object.entries(permit.headers))xhr.setRequestHeader(k,v);xhr.upload.onprogress=e=>onProgress(e.loaded);xhr.onerror=()=>reject(new Error('OSS 直传失败，请检查网络和 CORS'));xhr.ontimeout=()=>reject(new Error('分片上传超时'));xhr.onload=()=>{const etag=xhr.getResponseHeader('ETag');if(xhr.status>=200&&xhr.status<300&&etag)resolve(etag);else reject(new Error('分片上传失败或 OSS 未暴露 ETag 响应头'));};xhr.send(blob);});}
  window.addEventListener('beforeunload',event=>{if(uploading){event.preventDefault();event.returnValue='';}});
  try{await authenticated();}catch(error){toast(error.message);$('content').innerHTML=empty('加载失败，请刷新重试');}refreshIcons();
})();
