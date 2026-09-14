'use strict';
window.FS = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icons = {IMAGE:'image',VIDEO:'film',AUDIO:'music-2',PDF:'file-text',WORD:'file-text',EXCEL:'sheet',PPT:'presentation',ARCHIVE:'file-archive',TEXT:'file-text',OTHER:'file'};
  const labels = {ACTIVE:'分享中',PAUSED:'已暂停',EXPIRED:'已过期',REVOKED:'已撤回',LIMIT_REACHED:'已达上限',READY:'正常',TRASHED:'回收站',DELETED:'已删除'};
  const actions = {VIEW_SHARE:'访问分享',PREVIEW_FILE:'预览文件',DOWNLOAD_FILE:'请求下载',PASSWORD_SUCCESS:'密码验证成功',PASSWORD_FAIL:'密码验证失败'};
  const icon = name => `<i data-lucide="${name}"></i>`;
  const fileIcon = file => `<span class="file-icon ${esc(file.file_type.toLowerCase())}">${icon(icons[file.file_type] || 'file')}</span>`;
  function refreshIcons(){window.lucide?.createIcons();}
  function size(bytes){if(bytes < 1024)return bytes+' B'; const i=Math.min(3,Math.floor(Math.log(bytes)/Math.log(1024)));return (bytes/1024**i).toFixed(i>1?1:0)+' '+['B','KB','MB','GB'][i];}
  const date = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN',{hour12:false}) : '永久有效';
  const badge = value => `<span class="badge ${value==='ACTIVE'?'':'off'}">${esc(labels[value] || value)}</span>`;
  async function api(path,data){const response=await fetch(path,{credentials:'same-origin',cache:'no-store',method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-Share-Request':'1'},body:data===undefined?undefined:JSON.stringify(data)});let result;try{result=await response.json();}catch{throw new Error('服务器响应异常，请稍后重试');}if(!response.ok){const error=new Error(result.error||'请求失败');error.status=response.status;throw error;}return result;}
  let toastTimer;
  function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4000);}
  function dialog(title,html){$('dialogTitle').textContent=title;$('dialogBody').innerHTML=html;if(!$('dialog').open)$('dialog').showModal();refreshIcons();}
  function close(){const media=$('dialogBody').querySelectorAll('video,audio');media.forEach(m=>{m.pause();m.removeAttribute('src');m.load();});$('dialog').close();$('dialogBody').replaceChildren();}
  $('dialogClose').onclick=close;$('dialog').addEventListener('cancel',event=>{event.preventDefault();close();});
  async function copy(value){try{await navigator.clipboard.writeText(value);toast('分享链接已复制');}catch{dialog('复制链接',`<p class="muted">请长按或选中下方链接复制</p><input readonly value="${esc(value)}">`);$('dialogBody').querySelector('input').select();}}
  async function preview(file,url){
    dialog(file.filename,'<div class="preview-tools" id="previewTools"></div><div class="preview-stage" id="previewStage"></div><p class="muted">预览链接有效期 5 分钟；过期后请关闭并重新打开。</p>');
    const stage=$('previewStage'),tools=$('previewTools');
    if(file.file_type==='IMAGE'){
      const img=document.createElement('img');img.src=url;img.alt=file.filename;stage.append(img);let zoom=1;
      for(const [text,delta] of [['缩小',-.25],['放大',.25]]){const b=document.createElement('button');b.textContent=text;b.onclick=()=>{zoom=Math.max(.25,Math.min(4,zoom+delta));img.style.maxWidth='none';img.style.width=`${zoom*100}%`;};tools.append(b);}
      const a=document.createElement('a');a.textContent='查看原图';a.href=url;a.target='_blank';a.rel='noopener noreferrer';tools.append(a);
    }else if(file.file_type==='VIDEO'||file.file_type==='AUDIO'){
      const media=document.createElement(file.file_type==='VIDEO'?'video':'audio');media.src=url;media.controls=true;media.preload='metadata';media.setAttribute('playsinline','');stage.append(media);
      if(file.file_type==='VIDEO'){const select=document.createElement('select');select.setAttribute('aria-label','播放倍速');for(const speed of [.5,1,1.25,1.5,2]){const option=new Option(speed+'×',speed,false,speed===1);select.add(option);}select.onchange=()=>media.playbackRate=Number(select.value);tools.append(select);}
      media.onerror=()=>toast('当前浏览器无法播放该格式，或链接已过期，请重新预览');
    }else if(file.file_type==='PDF'){
      const frame=document.createElement('iframe');frame.title=file.filename;frame.src=url;stage.append(frame);const a=document.createElement('a');a.textContent='在浏览器中打开 PDF';a.href=url;a.target='_blank';a.rel='noopener noreferrer';tools.append(a);
    }else if(file.file_type==='TEXT'){
      const pre=document.createElement('pre');pre.textContent='正在读取文本…';stage.append(pre);
      try{const response=await fetch(url,{headers:{Range:'bytes=0-1048575'},referrerPolicy:'no-referrer'});if(!response.ok)throw new Error('文本预览失败');const reader=response.body.getReader();let length=0,chunks=[];while(length<1048576){const {done,value}=await reader.read();if(done)break;const chunk=value.subarray(0,1048576-length);chunks.push(chunk);length+=chunk.length;}await reader.cancel();const joined=new Uint8Array(length);let pos=0;for(const chunk of chunks){joined.set(chunk,pos);pos+=chunk.length;}pre.textContent=new TextDecoder().decode(joined)+(file.size>1048576?'\n\n仅预览前 1 MB，请下载查看完整内容。':'');}catch{pre.textContent='文本预览失败，请检查存储跨域设置，或下载查看。';}
    }else stage.textContent='暂不支持在线预览，请下载查看';
  }
  return {$,esc,icon,fileIcon,refreshIcons,size,date,badge,actions,api,toast,dialog,close,copy,preview};
})();
