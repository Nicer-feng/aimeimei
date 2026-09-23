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
  let previewSerial=0,previewURLs=[];
  function clearPreview(){previewSerial++;previewURLs.forEach(url=>URL.revokeObjectURL(url));previewURLs=[];$('dialog').classList.remove('document-preview','preview-full');}
  function dialog(title,html){clearPreview();$('dialogTitle').textContent=title;$('dialogBody').innerHTML=html;if(!$('dialog').open)$('dialog').showModal();refreshIcons();}
  function close(){const media=$('dialogBody').querySelectorAll('video,audio');media.forEach(m=>{m.pause();m.removeAttribute('src');m.load();});clearPreview();$('dialog').close();$('dialogBody').replaceChildren();}
  $('dialogClose').onclick=close;$('dialog').addEventListener('cancel',event=>{event.preventDefault();close();});
  async function copy(value){try{await navigator.clipboard.writeText(value);toast('分享链接已复制');}catch{dialog('复制链接',`<p class="muted">请长按或选中下方链接复制</p><input readonly value="${esc(value)}">`);$('dialogBody').querySelector('input').select();}}
  async function preview(file,source,download){
    dialog(file.filename,'<div class="preview-tools" id="previewTools"></div><div class="preview-stage" id="previewStage"><p>正在准备预览，首次转换可能需要几十秒…</p></div><p class="muted preview-note" id="previewNote">仅供预览，原文件保持不变。</p>');
    $('dialog').classList.add('document-preview');
    const serial=previewSerial,stage=$('previewStage'),tools=$('previewTools');
    const full=document.createElement('button');full.textContent='全屏';full.onclick=()=>{const active=$('dialog').classList.toggle('preview-full');full.textContent=active?'恢复窗口':'全屏';};tools.append(full);
    if(download){const button=document.createElement('button');button.textContent='下载原文件';button.onclick=async()=>{button.disabled=true;try{await download();}catch(error){toast(error.message);}finally{button.disabled=false;}};tools.append(button);}
    let info,url;
    try{info=typeof source==='function'?await source():{url:source};if(serial!==previewSerial)return;url=info.url;stage.replaceChildren();}
    catch(error){if(serial===previewSerial)stage.textContent=error.message;return;}
    if(info.kind==='pdf'){
      const bytes=Uint8Array.from(atob(info.data),c=>c.charCodeAt(0));url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));previewURLs.push(url);
    }
    if(info.kind==='sheets'){
      $('previewNote').textContent='表格为只读数据预览，不执行宏、不更新公式或外部链接；公式显示文件保存时的计算结果。图表、图片、样式和隐藏工作表不展示。'+(info.truncated?' 内容已截断：最多20个工作表、每表200行50列，并有总内容限制。':'');
      const select=document.createElement('select');select.setAttribute('aria-label','工作表');info.sheets.forEach((sheet,i)=>select.add(new Option(sheet.name,i)));tools.append(select);
      let zoom=14;for(const [text,delta] of [['缩小',-2],['放大',2]]){const button=document.createElement('button');button.textContent=text;button.onclick=()=>{zoom=Math.max(10,Math.min(28,zoom+delta));stage.style.setProperty('--sheet-font',zoom+'px');};tools.append(button);}
      stage.classList.add('spreadsheet-stage');
      function show(){const sheet=info.sheets[Number(select.value)];if(!sheet){stage.textContent='没有可显示的工作表';return;}
        const columns=Math.max(0,...sheet.rows.map(r=>r.length));const heading=n=>{let text='';for(n++;n;n=Math.floor((n-1)/26))text=String.fromCharCode(65+(n-1)%26)+text;return text;};
        stage.innerHTML='<table class="spreadsheet"><thead><tr><th>#</th>'+Array.from({length:columns},(_,i)=>'<th>'+esc(heading(i))+'</th>').join('')+'</tr></thead><tbody>'+sheet.rows.map((row,i)=>'<tr><th>'+(i+1)+'</th>'+Array.from({length:columns},(_,j)=>'<td>'+esc(row[j]||'')+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
      }
      select.onchange=show;show();return;
    }
    $('previewNote').textContent=info.kind==='pdf'?'Word 已转换为 PDF 预览，复杂排版可能与原文件略有差异。':'预览链接有效期 5 分钟；过期后请关闭并重新打开。';
    if(file.file_type==='IMAGE'){
      const img=document.createElement('img');img.src=url;img.alt=file.filename;stage.append(img);let zoom=1;
      for(const [text,delta] of [['缩小',-.25],['放大',.25]]){const b=document.createElement('button');b.textContent=text;b.onclick=()=>{zoom=Math.max(.25,Math.min(4,zoom+delta));img.style.maxWidth='none';img.style.width=`${zoom*100}%`;};tools.append(b);}
      const a=document.createElement('a');a.textContent='查看原图';a.href=url;a.target='_blank';a.rel='noopener noreferrer';tools.append(a);
    }else if(file.file_type==='VIDEO'||file.file_type==='AUDIO'){
      const media=document.createElement(file.file_type==='VIDEO'?'video':'audio');media.src=url;media.controls=true;media.preload='metadata';media.setAttribute('playsinline','');stage.append(media);
      if(file.file_type==='VIDEO'){const select=document.createElement('select');select.setAttribute('aria-label','播放倍速');for(const speed of [.5,1,1.25,1.5,2]){const option=new Option(speed+'×',speed,false,speed===1);select.add(option);}select.onchange=()=>media.playbackRate=Number(select.value);tools.append(select);}
      media.onerror=()=>toast('当前浏览器无法播放该格式，或链接已过期，请重新预览');
    }else if(file.file_type==='PDF'||info.kind==='pdf'){
      const frame=document.createElement('iframe');frame.title=file.filename;frame.src=url+'#view=FitH';stage.append(frame);const a=document.createElement('a');a.textContent='在浏览器中打开 PDF';a.href=url;a.target='_blank';a.rel='noopener noreferrer';tools.append(a);
    }else if(file.file_type==='TEXT'){
      const pre=document.createElement('pre');pre.textContent='正在读取文本…';stage.append(pre);
      try{const response=await fetch(url,{headers:{Range:'bytes=0-1048575'},referrerPolicy:'no-referrer'});if(!response.ok)throw new Error('文本预览失败');const reader=response.body.getReader();let length=0,chunks=[];while(length<1048576){const {done,value}=await reader.read();if(done)break;const chunk=value.subarray(0,1048576-length);chunks.push(chunk);length+=chunk.length;}await reader.cancel();const joined=new Uint8Array(length);let pos=0;for(const chunk of chunks){joined.set(chunk,pos);pos+=chunk.length;}pre.textContent=new TextDecoder().decode(joined)+(file.size>1048576?'\n\n仅预览前 1 MB，请下载查看完整内容。':'');}catch{pre.textContent='文本预览失败，请检查存储跨域设置，或下载查看。';}
    }else stage.textContent='暂不支持在线预览，请下载查看';
  }
  return {$,esc,icon,fileIcon,refreshIcons,size,date,badge,actions,api,toast,dialog,close,copy,preview};
})();
