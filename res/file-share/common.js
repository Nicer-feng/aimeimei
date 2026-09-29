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
  let previewSerial=0,previewURLs=[],pdfPreviewTask=null,pdfRenderTask=null,pdfResizeObserver=null,textPreviewController=null;
  function clearPreview(){previewSerial++;textPreviewController?.abort();textPreviewController=null;pdfResizeObserver?.disconnect();pdfResizeObserver=null;pdfRenderTask?.cancel();pdfRenderTask=null;if(pdfPreviewTask){pdfPreviewTask.destroy().catch(()=>{});pdfPreviewTask=null;}previewURLs.forEach(url=>URL.revokeObjectURL(url));previewURLs=[];$('dialog').classList.remove('document-preview','preview-full');}
  function dialog(title,html){window.CloudMotion?.captureOrigin();clearPreview();$('dialogTitle').textContent=title;$('dialogBody').innerHTML=html;$('dialogBody').scrollTop=0;if(!$('dialog').open)$('dialog').showModal();refreshIcons();window.CloudMotion?.open($('dialog'));}
  function close(){const media=$('dialogBody').querySelectorAll('video,audio');media.forEach(m=>{m.pause();m.removeAttribute('src');m.load();});clearPreview();$('dialog').close();$('dialogBody').replaceChildren();}
  $('dialogClose').onclick=close;$('dialog').addEventListener('cancel',event=>{event.preventDefault();close();});
  // Dismiss only the surface where the gesture began; dragging out never closes it.
  function dismissOutside(surface,content,dismiss){
    let start=null;
    const outside=event=>{const r=content.getBoundingClientRect();return event.target===surface&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom);};
    surface.addEventListener('pointerdown',event=>{start=event.button===0&&!event.cloudSelectDismissed&&outside(event)?{x:event.clientX,y:event.clientY}:null;});
    surface.addEventListener('pointercancel',()=>{start=null;});
    surface.addEventListener('click',event=>{const began=start;start=null;if(began&&outside(event)&&Math.hypot(event.clientX-began.x,event.clientY-began.y)<8){event.preventDefault();event.stopPropagation();dismiss();}});
  }
  document.querySelectorAll('dialog').forEach(panel=>dismissOutside(panel,panel,()=>{
    // Reuse cancel handlers so previews clean up and editors retain save checks.
    if(panel.dispatchEvent(new Event('cancel',{cancelable:true})))panel.close();
  }));
  for(const [id,cancelId] of [['officeClosePrompt','officeCancelClose'],['pdfPageClosePrompt','pdfPageKeepEditing']]){
    const prompt=$(id);if(!prompt)continue;
    const dismiss=()=>$(cancelId).click();dismissOutside(prompt,prompt.querySelector('.office-close-card'),dismiss);
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!prompt.hidden&&prompt.closest('dialog')?.open){event.preventDefault();event.stopPropagation();dismiss();}},true);
  }
  async function copy(value){try{await navigator.clipboard.writeText(value);toast('分享链接已复制');}catch{dialog('复制链接',`<p class="muted">请长按或选中下方链接复制</p><input readonly value="${esc(value)}">`);$('dialogBody').querySelector('input').select();}}
  async function preview(file,source,download){
    dialog(file.filename,'<div class="preview-tools" id="previewTools"></div><div class="preview-stage" id="previewStage"><p>正在准备预览，首次转换可能需要几十秒…</p></div><p class="muted preview-note" id="previewNote">仅供预览，原文件保持不变。</p>');
    $('dialog').classList.add('document-preview');window.CloudMotion?.open($('dialog'),true);
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
      const openLink=document.createElement('a');openLink.textContent='在浏览器中打开 PDF';openLink.href=url;openLink.target='_blank';openLink.rel='noopener noreferrer';tools.append(openLink);
      const fallback=()=>{pdfResizeObserver?.disconnect();pdfResizeObserver=null;stage.classList.remove('pdf-preview-stage');stage.replaceChildren();const frame=document.createElement('iframe');frame.title=file.filename;frame.src=url+'#view=FitH';stage.append(frame);};
      // Keep large/unsupported documents available in the browser's own viewer.
      if(file.size>20*1024*1024){fallback();return;}
      stage.classList.add('pdf-preview-stage');
      stage.textContent='正在加载文档…';
      let controls;
      try{
        const base='/res/file-share/vendor/pdfjs-6.3.289/';
        const pdfjs=await import(base+'pdf.min.mjs');if(serial!==previewSerial)return;
        pdfjs.GlobalWorkerOptions.workerSrc=base+'pdf.worker.min.mjs';
        const task=pdfjs.getDocument({url,cMapUrl:base+'cmaps/',cMapPacked:true,standardFontDataUrl:base+'standard_fonts/',wasmUrl:base+'wasm/',iccUrl:base+'iccs/',withCredentials:false});
        pdfPreviewTask=task;const doc=await task.promise;if(serial!==previewSerial)return;
        controls=document.createElement('div');controls.className='pdf-preview-controls';controls.setAttribute('role','group');controls.setAttribute('aria-label','PDF 翻页与缩放');
        const button=(label,handler)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=handler;controls.append(b);return b;};
        let number=1,zoom=1,drawing=0;
        const previous=button('上一页',()=>{number--;draw();});
        const count=document.createElement('span');count.setAttribute('aria-live','polite');controls.append(count);
        const next=button('下一页',()=>{number++;draw();});
        const smaller=button('缩小',()=>{zoom=Math.max(.5,zoom-.25);draw();});
        const larger=button('放大',()=>{zoom=Math.min(2,zoom+.25);draw();});
        tools.append(controls);
        const canvas=document.createElement('canvas');canvas.setAttribute('role','img');stage.replaceChildren(canvas);
        async function draw(){
          const current=++drawing;const pending=pdfRenderTask;
          if(pending){pending.cancel();try{await pending.promise;}catch{}}
          if(serial!==previewSerial||current!==drawing)return;
          previous.disabled=number<=1;next.disabled=number>=doc.numPages;smaller.disabled=zoom<=.5;larger.disabled=zoom>=2;
          count.textContent=number+' / '+doc.numPages;canvas.setAttribute('aria-label',file.filename+'，第 '+number+' 页');
          try{
            const page=await doc.getPage(number);if(serial!==previewSerial||current!==drawing)return;
            const natural=page.getViewport({scale:1}),fit=Math.min((stage.clientWidth-32)/natural.width,(stage.clientHeight-32)/natural.height);
            const viewport=page.getViewport({scale:Math.max(.1,fit)*zoom}),ratio=Math.min(devicePixelRatio||1,2);
            canvas.width=Math.ceil(viewport.width*ratio);canvas.height=Math.ceil(viewport.height*ratio);canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';
            const render=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:ratio===1?null:[ratio,0,0,ratio,0,0],background:'#ffffff'});pdfRenderTask=render;await render.promise;
            if(pdfRenderTask===render)pdfRenderTask=null;
          }catch(error){if(serial!==previewSerial||current!==drawing||error.name==='RenderingCancelledException')return;controls.remove();fallback();}
        }
        await draw();
        if(serial===previewSerial&&stage.classList.contains('pdf-preview-stage')&&window.ResizeObserver){
          let width=stage.clientWidth,height=stage.clientHeight;
          pdfResizeObserver=new ResizeObserver(()=>{
            if(width===stage.clientWidth&&height===stage.clientHeight)return;
            width=stage.clientWidth;height=stage.clientHeight;draw();
          });
          pdfResizeObserver.observe(stage);
        }
      }catch{if(serial!==previewSerial)return;controls?.remove();fallback();}
    }else if(file.file_type==='TEXT'){
      const markdown=/\.md$/i.test(file.filename||'');
      const pre=document.createElement('pre');pre.className='cloud-text-source';pre.textContent='正在读取文本…';stage.append(pre);
      const controller=new AbortController();textPreviewController=controller;
      const timeout=setTimeout(()=>controller.abort(),15000),limit=1024*1024;
      try{
        const response=await fetch(url,{headers:{Range:'bytes=0-'+limit},referrerPolicy:'no-referrer',credentials:'omit',signal:controller.signal});
        if(!response.ok||!response.body)throw new Error('文本预览失败');
        const reader=response.body.getReader();let length=0;const chunks=[];
        try{
          while(length<=limit){const {done,value}=await reader.read();if(done)break;const chunk=value.subarray(0,limit+1-length);chunks.push(chunk);length+=chunk.length;}
        }finally{await reader.cancel();reader.releaseLock();}
        if(serial!==previewSerial)return;
        const joined=new Uint8Array(length);let pos=0;for(const chunk of chunks){joined.set(chunk,pos);pos+=chunk.length;}
        const truncated=length>limit||Number(file.size)>limit;
        const text=new TextDecoder().decode(joined.subarray(0,limit),{stream:truncated});
        pre.textContent=text;clearTimeout(timeout);
        $('previewNote').textContent=(truncated?'仅预览前 1 MB，超出部分请下载查看。':'')+(markdown?'Markdown 在当前浏览器本地渲染；原文件不变，外部图片点击链接查看。':'UTF-8 文本预览；原文件不变。');
        if(markdown){
          stage.classList.add('markdown-preview-stage');
          const article=document.createElement('article');article.className='cloud-markdown';article.setAttribute('aria-label','Markdown 文档预览');
          try{
            const content=await window.CloudMarkdown.render(text);if(serial!==previewSerial)return;article.append(content);
            if(!text.trim())article.textContent='这是一个空 Markdown 文件。';
            const group=document.createElement('div');group.className='markdown-view-switch';group.setAttribute('role','group');group.setAttribute('aria-label','Markdown 显示方式');
            for(const [label,sourceMode] of [['预览',false],['源码',true]]){
              const button=document.createElement('button');button.type='button';button.textContent=label;button.setAttribute('aria-pressed',String(!sourceMode));
              button.onclick=()=>{pre.hidden=!sourceMode;article.hidden=sourceMode;stage.scrollTop=0;group.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));};group.append(button);
            }
            tools.append(group);pre.hidden=true;stage.replaceChildren(article,pre);
          }catch{if(serial===previewSerial)$('previewNote').textContent='Markdown 排版组件暂不可用，已显示源码。'+(truncated?'仅显示前 1 MB。':'');}
        }
      }catch(error){if(serial===previewSerial)pre.textContent=error.name==='AbortError'?'读取超时，请关闭后重试。':'文本预览失败，请重试或下载查看。';}
      finally{clearTimeout(timeout);if(textPreviewController===controller)textPreviewController=null;}
    }else stage.textContent='暂不支持在线预览，请下载查看';
  }
  return {$,esc,icon,fileIcon,refreshIcons,size,date,badge,actions,api,toast,dialog,close,copy,preview};
})();
