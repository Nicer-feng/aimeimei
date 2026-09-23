'use strict';
window.CloudOffice=(()=>{
  const sdkUrl='https://g.alicdn.com/IMM/office-js/1.1.19/aliyun-web-office-sdk.min.js';
  const $=id=>document.getElementById(id);
  let deps=null,config={enabled:false,maxBytes:0,formats:new Set()};
  let sdkPromise=null,starting=false,busy=false,session=null,tokenInfo=null,instance=null,file=null,opener=null;
  let refreshPromise=null,pendingCloseVersionSaved=false,recoveredDraft=false,recoveryLost=false;
  let versionsFile=null,versionItems=[];

  function configure(options){deps=options;bind();}
  function setConfig(data){
    config={
      enabled:data?.enabled===true,
      maxBytes:Number(data?.max_bytes)||0,
      formats:new Set((Array.isArray(data?.formats)?data.formats:[]).map(value=>String(value).toLowerCase().replace(/^\./,'')))
    };
  }
  function canEdit(candidate){
    if(!config.enabled||!candidate||candidate.status!=='READY'||!Number.isFinite(Number(candidate.size))||Number(candidate.size)<=0||Number(candidate.size)>config.maxBytes)return false;
    const name=String(candidate.filename||''),dot=name.lastIndexOf('.');
    return dot>0&&config.formats.has(name.slice(dot+1).toLowerCase());
  }
  function isOpen(){return starting||$('officeEditor').open;}
  function hint(){return config.enabled?'在线编辑试用支持 '+[...config.formats].map(value=>value.toUpperCase()).join(' / ')+'，单文件不超过 '+deps.size(config.maxBytes)+'。保存版本后可选择发布。':'';}
  function endpoint(path){return deps.base+'/office/'+path;}
  function setStatus(state,message,error=''){
    const status=$('officeStatus');status.dataset.state=state;status.textContent=message;
    const alert=$('officeError');alert.textContent=error;alert.hidden=!error;
  }
  function setBusy(value){
    busy=value;
    $('officeSaveVersion').disabled=value||!session;
    $('officeShowVersions').disabled=value||!session;
    $('officeClose').disabled=value||starting;
    $('officeCloseDraft').disabled=value;
    $('officeCloseSaved').disabled=value;
  }
  function loadSdk(){
    if(window.aliyun?.config)return Promise.resolve();
    if(!sdkPromise)sdkPromise=new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src=sdkUrl;script.referrerPolicy='no-referrer';script.async=true;
      let settled=false;
      const timeout=setTimeout(()=>finish(new Error('阿里云编辑器加载超时，请检查网络后重试')),20000);
      function finish(error){
        if(settled)return;settled=true;clearTimeout(timeout);
        if(error){script.remove();sdkPromise=null;reject(error);}else resolve();
      }
      script.onload=()=>window.aliyun?.config?finish():finish(new Error('阿里云编辑器未正确加载'));
      script.onerror=()=>finish(new Error('阿里云编辑器加载失败，请检查网络或页面脚本权限'));
      document.head.append(script);
    });
    return sdkPromise;
  }
  function tokenTimeout(expiresAt){
    let expires=typeof expiresAt==='number'?expiresAt:typeof expiresAt==='string'&&/^\d+$/.test(expiresAt)?Number(expiresAt):Date.parse(expiresAt);
    if(Number.isFinite(expires)&&expires<1e12)expires*=1000;
    if(!Number.isFinite(expires))return 25*60*1000;
    const remaining=expires-Date.now();
    if(remaining<=60000)throw new Error('编辑凭证已过期，请重新打开文件');
    return Math.min(25*60*1000,remaining-60000);
  }
  function waitUntilReady(){
    return new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(new Error('编辑器打开超时，请检查 IMM 授权和 OSS 跨域设置')),30000);
      let ready;
      try{ready=instance.ready();}catch(error){clearTimeout(timeout);reject(error);return;}
      Promise.resolve(ready).then(value=>{clearTimeout(timeout);resolve(value);},error=>{clearTimeout(timeout);reject(error);});
    });
  }
  function refreshToken(){
    if(!session||!tokenInfo)return Promise.reject(new Error('编辑会话已结束'));
    if(refreshPromise)return refreshPromise;
    const activeSession=session;
    refreshPromise=deps.api(endpoint('sessions/'+encodeURIComponent(activeSession.id)+'/refresh'),{
      access_token:tokenInfo.access_token,
      refresh_token:tokenInfo.refresh_token
    }).then(data=>{
      if(session!==activeSession)throw new Error('编辑会话已结束');
      if(!data.access_token||!data.refresh_token)throw new Error('新凭证不完整');
      tokenInfo={...tokenInfo,...data,url:tokenInfo.url};
      return {token:tokenInfo.access_token,timeout:tokenTimeout(tokenInfo.access_expires_at)};
    }).catch(()=>{
      if(session===activeSession)setStatus('failed','连接中断','编辑凭证刷新失败，请检查网络；如无法继续，请先尝试保存。');
      throw new Error('编辑凭证刷新失败');
    }).finally(()=>{refreshPromise=null;});
    return refreshPromise;
  }
  function handleFileStatus(data){
    if(!session)return;
    const status=Number(data?.status);
    if(status===6)setStatus('syncing','正在同步草稿…');
    else if(status===1||status===7)setStatus('synced','草稿已同步云端');
    else if(status===2)setStatus('failed','草稿同步失败','空文件暂不支持保存，请检查文档内容。');
    else if(status===3)setStatus('failed','草稿同步失败','云端空间不足，请稍后重试。');
    else if(status===4)setStatus('failed','保存队列繁忙','请稍后重试保存版本。');
    else if(status===5)setStatus('failed','草稿同步失败','编辑器保存失败，请重试。');
  }
  function listen(name,callback){
    if(instance.ApiEvent?.AddApiEventListener)instance.ApiEvent.AddApiEventListener(name,callback);
    else if(instance.on)instance.on(name,callback);
  }
  function destroy(){
    try{instance?.destroy();}catch{}
    instance=null;session=null;tokenInfo=null;file=null;refreshPromise=null;starting=false;busy=false;
    pendingCloseVersionSaved=false;recoveredDraft=false;recoveryLost=false;
    $('officeMount').replaceChildren();
    $('officeClosePrompt').hidden=true;
    $('officeCloseError').textContent='';
    $('officeCloseDraft').textContent='仅同步草稿并关闭';
    $('officeCloseDraft').dataset.force='';
    if($('officeVersions').open)$('officeVersions').close();
    if($('officeEditor').open)$('officeEditor').close();
    if(opener?.isConnected)opener.focus({preventScroll:true});
    opener=null;
  }
  async function open(candidate){
    if(!canEdit(candidate))throw new Error('该文件暂不支持在线编辑');
    if(isOpen())throw new Error('请先完成当前在线编辑');
    if($('dialog').open)throw new Error('请先关闭当前弹窗');
    opener=document.activeElement;file=candidate;starting=true;
    $('officeTitle').textContent=candidate.filename;
    $('officeNote').textContent='编辑器会自动同步草稿；下次打开同一文件可恢复已同步内容。保存版本后才会进入版本记录，发布前分享链接不变。';
    $('officeClosePrompt').hidden=true;
    $('officeEditor').showModal();
    setStatus('loading','正在连接阿里云编辑器…');setBusy(true);
    try{
      await loadSdk();
      const data=await deps.api(endpoint('files/'+encodeURIComponent(candidate.id)+'/start'),{});
      if(data.session_id)session={id:data.session_id,fileId:candidate.id};
      recoveredDraft=data.recovered===true;
      recoveryLost=data.recovery_lost===true;
      if(recoveredDraft)$('officeNote').textContent='已恢复上次同步的草稿。编辑器会继续自动同步；保存版本并发布后，分享链接才会切换。';
      if(recoveryLost)$('officeNote').textContent='上次同步的草稿已过期或丢失，本次从已发布版本开始。未保存为版本的改动无法恢复。';
      if(!data.session_id||!data.url||!data.access_token||!data.refresh_token)throw new Error('服务器返回的编辑凭证不完整');
      const url=new URL(data.url);
      if(url.protocol!=='https:'||url.username||url.password)throw new Error('编辑地址无效');
      tokenInfo={url:data.url,access_token:data.access_token,refresh_token:data.refresh_token,access_expires_at:data.access_expires_at};
      instance=window.aliyun.config({mount:$('officeMount'),url:tokenInfo.url,refreshToken});
      listen('fileOpen',event=>{
        if(!session)return;
        if(event?.success===false||event?.result==='Fail')setStatus('failed','打开失败','文档未能打开，请检查 IMM 授权、OSS 跨域和文件格式。');
        else if($('officeStatus').dataset.state==='loading')setStatus('draft',recoveredDraft?'已恢复上次同步的草稿':'正在编辑草稿 · 自动同步');
      });
      listen('fileStatus',handleFileStatus);
      listen('error',()=>{if(session)setStatus('failed','编辑器出现错误','请检查 IMM 授权、OSS 跨域或网络连接后重试。');});
      instance.setToken({token:tokenInfo.access_token,timeout:tokenTimeout(tokenInfo.access_expires_at)});
      await waitUntilReady();
      starting=false;setBusy(false);
      if(recoveryLost)deps.toast('上次草稿已过期或丢失，已从发布版本重新开始');
      if(session&&$('officeStatus').dataset.state==='loading')setStatus('draft',recoveredDraft?'已恢复上次同步的草稿':'正在编辑草稿 · 自动同步');
    }catch(error){
      if(session){try{await deps.api(endpoint('sessions/'+encodeURIComponent(session.id)+'/close'),{});}catch{}}
      destroy();
      throw error;
    }
  }
  async function flushDraft(){
    if(!instance||!session)throw new Error('编辑会话尚未就绪');
    setStatus('syncing','正在同步草稿…');
    let result;
    try{result=await instance.save();}catch{setStatus('failed','草稿同步失败','编辑器未能保存，请检查连接后重试。');throw new Error('编辑器未能保存草稿');}
    if(!result||!['ok','nochange'].includes(result.result)){
      setStatus('failed','草稿同步失败','编辑器保存未成功，请稍后重试。');
      throw new Error('编辑器保存未成功，请稍后重试');
    }
    setStatus('synced','草稿已同步云端');
  }
  async function snapshot(){
    if(busy||!session)return;
    setBusy(true);
    try{
      await flushDraft();
      const data=await deps.api(endpoint('sessions/'+encodeURIComponent(session.id)+'/snapshot'),{});
      const number=data.version?.number;
      setStatus('saved',number!=null?'已保存版本 v'+number+' · 尚未发布':'版本已保存 · 尚未发布');
      deps.toast('版本已保存，分享链接尚未切换');
      return data.version;
    }catch(error){
      if($('officeStatus').dataset.state!=='failed')setStatus('failed','保存版本失败',error.message);
      throw error;
    }finally{setBusy(false);}
  }
  function askClose(){
    if(starting){$('officeError').textContent='编辑器正在连接，请稍候。';$('officeError').hidden=false;return;}
    if(!session){destroy();return;}
    if(busy)return;
    $('officeCloseError').textContent='';
    $('officeClosePrompt').hidden=false;
    $('officeCancelClose').focus();
  }
  async function closeSession(withVersion,force=false){
    if(!session||busy)return;
    setBusy(true);
    const activeSession=session;
    try{
      if(!force){
        if(withVersion&&!pendingCloseVersionSaved){await flushDraft();const data=await deps.api(endpoint('sessions/'+encodeURIComponent(activeSession.id)+'/snapshot'),{});pendingCloseVersionSaved=true;deps.toast(data.version?.number!=null?'版本 v'+data.version.number+' 已保存，尚未发布':'版本已保存，尚未发布');}
        else await flushDraft();
      }
      await deps.api(endpoint('sessions/'+encodeURIComponent(activeSession.id)+'/close'),{});
      destroy();
    }catch(error){
      $('officeCloseError').textContent=error.message;
      if(!force){$('officeCloseDraft').dataset.force='1';$('officeCloseDraft').textContent='仍要关闭（可能丢失未同步内容）';}
      if($('officeStatus').dataset.state!=='failed')setStatus('failed','关闭前同步失败',error.message);
    }finally{if(session)setBusy(false);}
  }
  function displayDate(value){
    if(value==null||value==='')return '—';
    const numeric=typeof value==='number'||/^\d+$/.test(String(value));
    const time=numeric?Number(value):NaN;
    const parsed=numeric?new Date(time<1e12?time*1000:time):new Date(value);
    return Number.isNaN(parsed.getTime())?'—':parsed.toLocaleString('zh-CN',{hour12:false});
  }
  function renderVersions(){
    const body=$('officeVersionsBody');
    if(!versionItems.length){body.innerHTML='<p class="muted">暂无保存版本。打开文档编辑后，点击“保存版本”。</p>';return;}
    body.innerHTML=versionItems.map(item=>{
      const number=deps.esc(item.number),id=deps.esc(item.id),published=Boolean(item.published);
      return `<div class="office-version-row"><div><strong>版本 v${number}</strong><small>${deps.esc(displayDate(item.created_at))} · ${deps.esc(deps.size(item.size))}</small></div>${published?'<span class="badge">当前已发布</span>':`<button type="button" data-publish="${id}">发布此版本</button>`}</div>`;
    }).join('');
  }
  async function reloadVersions(){
    const body=$('officeVersionsBody'),target=versionsFile;body.textContent='正在加载版本…';
    try{
      const result=await deps.api(endpoint('files/'+encodeURIComponent(target.id)+'/versions'));
      if(versionsFile!==target)return;
      versionItems=Array.isArray(result.items)?result.items:[];
      renderVersions();
    }catch(error){if(versionsFile===target)body.textContent='读取版本失败：'+error.message;}
  }
  async function showVersions(candidate){
    if(!canEdit(candidate))throw new Error('该文件暂不支持在线编辑');
    versionsFile=candidate;versionItems=[];
    $('officeVersionsMessage').textContent='';
    $('officeVersionsMessage').dataset.state='';
    $('officeVersionsTitle').textContent=candidate.filename+' · 版本记录';
    if(!$('officeVersions').open)$('officeVersions').showModal();
    deps.refreshIcons();
    await reloadVersions();
  }
  function bind(){
    $('officeSaveVersion').onclick=()=>snapshot().catch(error=>deps.toast(error.message));
    $('officeShowVersions').onclick=()=>showVersions(file).catch(error=>deps.toast(error.message));
    $('officeClose').onclick=askClose;
    $('officeEditor').addEventListener('cancel',event=>{event.preventDefault();askClose();});
    $('officeCancelClose').onclick=()=>{$('officeClosePrompt').hidden=true;};
    $('officeCloseDraft').onclick=()=>closeSession(false,$('officeCloseDraft').dataset.force==='1');
    $('officeCloseSaved').onclick=()=>closeSession(true);
    $('officeVersionsClose').onclick=()=>$('officeVersions').close();
    $('officeVersionsBody').onclick=async event=>{
      const button=event.target.closest('[data-publish]');if(!button||!versionsFile)return;
      const item=versionItems.find(value=>String(value.id)===button.dataset.publish);if(!item||item.published)return;
      if(button.dataset.confirm!=='1'){
        $('officeVersionsBody').querySelectorAll('[data-publish]').forEach(other=>{other.dataset.confirm='';other.textContent='发布此版本';});
        button.dataset.confirm='1';button.textContent='确认发布 v'+item.number;return;
      }
      button.disabled=true;
      try{
        await deps.api(endpoint('files/'+encodeURIComponent(versionsFile.id)+'/publish'),{version_id:item.id});
        const publishedMessage='版本 v'+item.number+' 已发布，分享链接已切换。再次打开将从该发布版本开始，旧草稿不再自动恢复。';
        if(session?.fileId===versionsFile.id){
          setStatus('published','版本 v'+item.number+' 已发布');
          $('officeNote').textContent=publishedMessage;
        }
        $('officeVersionsMessage').dataset.state='success';
        $('officeVersionsMessage').textContent=publishedMessage;
        await reloadVersions();
        await deps.onChanged?.();
      }catch(error){$('officeVersionsMessage').dataset.state='error';$('officeVersionsMessage').textContent='发布失败：'+error.message;button.disabled=false;}
    };
    window.addEventListener('beforeunload',event=>{if(isOpen()){event.preventDefault();event.returnValue='';}});
  }
  return {configure,setConfig,canEdit,isOpen,hint,open,showVersions};
})();
