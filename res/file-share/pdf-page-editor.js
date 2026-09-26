'use strict';
window.CloudPdfEditor=(()=>{
  const $=id=>document.getElementById(id);
  const vendor='/res/file-share/vendor/';
  const pdfjsBase=vendor+'pdfjs-6.3.289/';
  const maxBytes=20*1024*1024,maxPages=100;
  let deps,pdfjsPromise,pdfLibPromise,previewTask,previewDoc,sourceBytes,sourceRevision,file;
  let pages=[],history=[],historyIndex=0,baseline='',selectedKey='',sequence=0,sourcePageCount=0;
  let cards=new Map(),observer,opening=false,busy=false,cancelRequested=false,activeXhr=null,pendingUploadId=null;
  let generatedBlob=null,versionFile=null,versionItems=[];

  const endpoint=path=>deps.base+'/pdf/'+path;
  const isOpen=()=>opening||$('pdfPageEditor').open;
  function canEdit(candidate){
    return !!candidate&&candidate.status==='READY'&&candidate.file_type==='PDF'&&/\.pdf$/i.test(candidate.filename||'')&&
      Number(candidate.size)>0&&Number(candidate.size)<=maxBytes;
  }
  function configure(options){deps=options;bind();}
  function setStatus(message,error=''){
    $('pdfPageStatus').textContent=message;
    $('pdfPageError').textContent=error;
    $('pdfPageError').hidden=!error;
  }
  function clonePages(items){return items.map(item=>({...item}));}
  function signature(items){return JSON.stringify(items.map(({sourceIndex,width,height,rotation,key})=>[sourceIndex??null,width,height,rotation,key]));}
  function dirty(){return signature(pages)!==baseline;}
  function checkCancel(){if(cancelRequested)throw new Error('已取消保存，生成的 PDF 可在下方下载');}
  function updateControls(){
    const ready=!!sourceBytes&&!opening;
    $('pdfPageSave').disabled=!ready||busy||!dirty();
    $('pdfPageUndo').disabled=!ready||busy||historyIndex===0;
    $('pdfPageRedo').disabled=!ready||busy||historyIndex>=history.length-1;
    for(const id of ['pdfPageLeft','pdfPageRight','pdfPageDelete','pdfPageBefore','pdfPageAfter'])$(id).disabled=!ready||busy||!pages.some(p=>p.key===selectedKey)||(id==='pdfPageDelete'&&pages.length<=1)||(id==='pdfPageBefore'||id==='pdfPageAfter')&&pages.length>=maxPages;
    $('pdfPageCancelUpload').hidden=!busy;
    $('pdfPageClose').disabled=opening;
    $('pdfPageDownload').hidden=!generatedBlob;
    $('pdfPageCount').textContent=pages.length+' 页'+(dirty()?' · 有未保存修改':' · 无未保存修改');
  }
  function remember(){
    history=history.slice(0,historyIndex+1);
    history.push(clonePages(pages));
    if(history.length>101)history.shift();
    historyIndex=history.length-1;
    renderPages();
  }
  function changeSelection(key){if(!pages.some(p=>p.key===key))return;selectedKey=key;renderPages();}
  function move(key,to){
    if(busy)return;
    const from=pages.findIndex(p=>p.key===key);
    if(from<0||to<0||to>=pages.length||from===to)return;
    const [item]=pages.splice(from,1);pages.splice(to,0,item);selectedKey=key;remember();
  }
  function rotate(delta){
    const page=pages.find(p=>p.key===selectedKey);if(!page||busy)return;
    page.rotation=((page.rotation+delta)%360+360)%360;remember();
    const card=cards.get(page.key);if(card){card.dataset.drawn='';scheduleThumb(card,page);}
  }
  function removeSelected(){
    if(busy||pages.length<=1)return;
    const index=pages.findIndex(p=>p.key===selectedKey);if(index<0)return;
    pages.splice(index,1);selectedKey=pages[Math.min(index,pages.length-1)].key;remember();
  }
  function insertBlank(after){
    if(busy||pages.length>=maxPages)return;
    const index=pages.findIndex(p=>p.key===selectedKey);if(index<0)return;
    const neighbor=pages[index],landscape=((neighbor.nativeRotation||0)+neighbor.rotation)%180!==0;
    const width=landscape?neighbor.height:neighbor.width,height=landscape?neighbor.width:neighbor.height;
    const item={key:'blank-'+(++sequence),sourceIndex:null,width,height,nativeRotation:0,rotation:0};
    pages.splice(index+(after?1:0),0,item);selectedKey=item.key;remember();
  }
  function undoRedo(step){
    const next=historyIndex+step;if(busy||next<0||next>=history.length)return;
    historyIndex=next;pages=clonePages(history[next]);
    if(!pages.some(p=>p.key===selectedKey))selectedKey=pages[0].key;
    renderPages();
  }
  function renderPages(){
    const grid=$('pdfPageGrid'),nodes=[];
    pages.forEach((page,index)=>{
      let card=cards.get(page.key);
      if(!card){
        card=document.createElement('article');card.className='pdf-page-card';card.dataset.key=page.key;card.tabIndex=0;card.draggable=true;
        card.innerHTML='<div class="pdf-page-thumb"><canvas hidden></canvas><span class="pdf-thumb-placeholder">滚动到此处加载预览</span></div><div class="pdf-page-label"><strong></strong><span></span></div><div class="pdf-page-arrows"><button type="button" data-pdf-action="up" aria-label="上移一页">↑ 上移</button><button type="button" data-pdf-action="down" aria-label="下移一页">↓ 下移</button></div>';
        cards.set(page.key,card);
      }
      card.classList.toggle('selected',page.key===selectedKey);
      card.setAttribute('aria-selected',String(page.key===selectedKey));
      card.setAttribute('aria-label','第 '+(index+1)+' 页'+(page.sourceIndex===null?'，空白页':''));
      card.querySelector('.pdf-page-label strong').textContent='第 '+(index+1)+' 页';
      card.querySelector('.pdf-page-label span').textContent=page.sourceIndex===null?'空白页':page.rotation?'已旋转 '+page.rotation+'°':'原第 '+(page.sourceIndex+1)+' 页';
      card.querySelector('[data-pdf-action=up]').disabled=busy||index===0;
      card.querySelector('[data-pdf-action=down]').disabled=busy||index===pages.length-1;
      if(page.sourceIndex===null){card.classList.add('blank');card.querySelector('canvas').hidden=true;card.querySelector('.pdf-thumb-placeholder').textContent='空白页';}
      else{card.classList.remove('blank');observer?.observe(card);}
      nodes.push(card);
    });
    grid.replaceChildren(...nodes);
    updateControls();
  }
  async function scheduleThumb(card,page){
    if(!previewDoc||page.sourceIndex===null||!card.isConnected)return;
    const drawn=page.sourceIndex+':'+page.rotation;
    if(card.dataset.drawn===drawn)return;
    card._pdfRenderTask?.cancel();card._pdfRenderTask=null;
    const stamp=String(Number(card.dataset.stamp||0)+1);card.dataset.stamp=stamp;
    const placeholder=card.querySelector('.pdf-thumb-placeholder');placeholder.textContent='正在绘制…';placeholder.hidden=false;
    try{
      const pdfPage=await previewDoc.getPage(page.sourceIndex+1);
      if(card.dataset.stamp!==stamp||!card.isConnected)return;
      const unscaled=pdfPage.getViewport({scale:1,rotation:pdfPage.rotate+page.rotation});
      const scale=Math.min(0.5,178/Math.max(unscaled.width,unscaled.height));
      const viewport=pdfPage.getViewport({scale,rotation:pdfPage.rotate+page.rotation});
      const canvas=document.createElement('canvas'),ratio=Math.min(devicePixelRatio||1,2);
      card.querySelector('canvas').replaceWith(canvas);canvas.hidden=true;
      canvas.width=Math.ceil(viewport.width*ratio);canvas.height=Math.ceil(viewport.height*ratio);
      canvas.style.width=Math.ceil(viewport.width)+'px';canvas.style.height=Math.ceil(viewport.height)+'px';
      const context=canvas.getContext('2d',{alpha:false});
      const task=pdfPage.render({canvasContext:context,canvas,viewport,transform:ratio===1?null:[ratio,0,0,ratio,0,0],background:'#ffffff'});
      card._pdfRenderTask=task;await task.promise;if(card._pdfRenderTask===task)card._pdfRenderTask=null;
      if(card.dataset.stamp!==stamp||!card.isConnected)return;
      canvas.hidden=false;placeholder.hidden=true;card.dataset.drawn=drawn;
    }catch(error){if(card.dataset.stamp===stamp)placeholder.textContent='预览失败';}
  }
  function ensureObserver(){
    observer?.disconnect();
    observer=new IntersectionObserver(entries=>{
      for(const entry of entries){if(!entry.isIntersecting)continue;const page=pages.find(p=>p.key===entry.target.dataset.key);if(page)scheduleThumb(entry.target,page);}
    },{root:$('pdfPageBody'),rootMargin:'220px'});
  }
  function secureUrl(raw){
    const url=new URL(raw,location.href);
    if(url.protocol!=='https:'||url.username||url.password)throw new Error('文件下载地址无效');
    return url.toString();
  }
  async function fetchSource(url,size){
    const response=await fetch(secureUrl(url),{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer'});
    if(!response.ok)throw new Error('下载 PDF 失败，请重试或检查 OSS 跨域 GET 设置');
    const reader=response.body?.getReader();
    if(!reader){const data=new Uint8Array(await response.arrayBuffer());if(data.length>maxBytes)throw new Error('PDF 超过 20 MB');return data;}
    let length=0;const chunks=[];
    try{
      for(;;){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>maxBytes||length>size+1024)throw new Error('PDF 实际大小超出允许范围');chunks.push(value);}
    }finally{reader.releaseLock();}
    const data=new Uint8Array(length);let offset=0;for(const chunk of chunks){data.set(chunk,offset);offset+=chunk.length;}
    return data;
  }
  async function loadLibraries(){
    if(!pdfjsPromise)pdfjsPromise=import(pdfjsBase+'pdf.min.mjs').then(lib=>{lib.GlobalWorkerOptions.workerSrc=pdfjsBase+'pdf.worker.min.mjs';return lib;}).catch(error=>{pdfjsPromise=null;throw error;});
    if(!pdfLibPromise)pdfLibPromise=new Promise((resolve,reject)=>{
      if(window.PDFLib?.PDFDocument){resolve(window.PDFLib);return;}
      const script=document.createElement('script');script.src=vendor+'pdf-lib-1.17.1.min.js';script.async=true;
      script.onload=()=>window.PDFLib?.PDFDocument?resolve(window.PDFLib):reject(new Error('PDF 编辑组件加载失败'));
      script.onerror=()=>reject(new Error('PDF 编辑组件加载失败，请检查网络'));
      document.head.append(script);
    }).catch(error=>{pdfLibPromise=null;throw error;});
    return Promise.all([pdfjsPromise,pdfLibPromise]);
  }
  async function prepareDocument(bytes,lib){
    previewTask=lib.getDocument({data:bytes.slice(),cMapUrl:pdfjsBase+'cmaps/',cMapPacked:true,standardFontDataUrl:pdfjsBase+'standard_fonts/',wasmUrl:pdfjsBase+'wasm/',iccUrl:pdfjsBase+'iccs/'});
    previewDoc=await previewTask.promise;
    if(previewDoc.numPages<1||previewDoc.numPages>maxPages)throw new Error('仅支持 1–100 页的 PDF');
    const [signatures,fields,outline,hasJs]=await Promise.all([previewDoc.getSignatures(),previewDoc.getFieldObjects(),previewDoc.getOutline(),previewDoc.hasJSActions()]);
    if(Array.isArray(signatures)&&signatures.length)throw new Error('已签名 PDF 不支持页面整理');
    if(fields&&Object.keys(fields).length)throw new Error('含表单的 PDF 暂不支持页面整理');
    if(outline?.length)throw new Error('含书签的 PDF 暂不支持页面整理');
    if(hasJs)throw new Error('含脚本的 PDF 暂不支持页面整理');
    pages=[];
    for(let index=0;index<previewDoc.numPages;index++){
      const page=await previewDoc.getPage(index+1),viewport=page.getViewport({scale:1,rotation:0});
      pages.push({key:'page-'+index,sourceIndex:index,width:viewport.width,height:viewport.height,nativeRotation:page.rotate,rotation:0});
    }
    selectedKey=pages[0].key;sequence=0;sourcePageCount=pages.length;baseline=signature(pages);history=[clonePages(pages)];historyIndex=0;
  }
  async function open(candidate){
    if(!canEdit(candidate))throw new Error('仅支持 20 MB 以内的 PDF 页面整理');
    if(isOpen())throw new Error('请先完成当前 PDF 整理');
    opening=true;file=candidate;generatedBlob=null;pendingUploadId=null;cards=new Map();sourceBytes=null;pages=[];baseline='';
    ensureObserver();$('pdfPageTitle').textContent=candidate.filename;$('pdfPageGrid').replaceChildren();$('pdfPageClosePrompt').hidden=true;
    $('pdfPageEditor').showModal();setStatus('正在读取 PDF…');updateControls();
    try{
      const context=await deps.api(endpoint('files/'+encodeURIComponent(file.id)+'/context'));
      if(!context.url||!context.revision)throw new Error('服务器返回的 PDF 编辑信息不完整');
      sourceRevision=context.revision;
      const [lib]=await loadLibraries();
      const bytes=await fetchSource(context.url,Number(context.size)||candidate.size);
      await prepareDocument(bytes,lib);
      sourceBytes=bytes;renderPages();setStatus('请选择页面，拖动或用上移、下移调整顺序');
    }catch(error){setStatus('无法打开 PDF',error.message||'请稍后重试');}
    finally{opening=false;updateControls();}
  }
  function makePdf(){
    return (async()=>{
      const lib=window.PDFLib;
      const document=await lib.PDFDocument.load(sourceBytes);
      const originals=document.getPages();
      if(originals.length!==sourcePageCount)throw new Error('源 PDF 页数已变化，请重新打开');
      // Materialize inherited entries before moving pages between PageTree nodes.
      for(const page of originals){
        for(const name of ['Resources','MediaBox','CropBox','Rotate']){
          const key=lib.PDFName.of(name),node=page.node,value=node.getInheritableAttribute(key);
          if(value&&!node.get(key))node.set(key,value);
        }
      }
      for(let index=originals.length-1;index>=0;index--)document.removePage(index);
      pages.forEach((entry,index)=>{
        const page=entry.sourceIndex===null?document.insertPage(index,[entry.width,entry.height]):document.insertPage(index,originals[entry.sourceIndex]);
        if(entry.rotation)page.setRotation(lib.degrees((page.getRotation().angle+entry.rotation)%360));
      });
      return document.save({updateFieldAppearances:false});
    })();
  }
  async function sha256(bytes){
    const hasher=await hashwasm.createSHA256();hasher.init();
    for(let offset=0;offset<bytes.length;offset+=4*1024*1024)hasher.update(bytes.subarray(offset,offset+4*1024*1024));
    return hasher.digest();
  }
  function putPart(permit,blob,onProgress){return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();activeXhr=xhr;xhr.open('PUT',secureUrl(permit.url));xhr.timeout=600000;
    for(const [key,value] of Object.entries(permit.headers||{}))xhr.setRequestHeader(key,value);
    xhr.upload.onprogress=event=>onProgress(event.loaded);
    xhr.onerror=()=>reject(new Error('OSS 直传失败，请检查网络和跨域设置'));
    xhr.onabort=()=>reject(new Error('已取消上传'));
    xhr.ontimeout=()=>reject(new Error('分片上传超时'));
    xhr.onload=()=>{const etag=xhr.getResponseHeader('ETag');if(xhr.status>=200&&xhr.status<300&&etag)resolve(etag);else reject(new Error('OSS 分片上传失败或未暴露 ETag 响应头'));};
    xhr.onloadend=()=>{if(activeXhr===xhr)activeXhr=null;};
    xhr.send(blob);
  });}
  async function save(){
    if(busy||!sourceBytes||!dirty())return;
    busy=true;cancelRequested=false;generatedBlob=null;updateControls();setStatus('正在生成 PDF…');
    let uploadId=null,completed=false;
    try{
      const bytes=await makePdf();generatedBlob=new Blob([bytes],{type:'application/pdf'});updateControls();checkCancel();
      if(bytes.length>maxBytes)throw new Error('整理后的 PDF 超过 20 MB；可先下载到本地');
      setStatus('正在计算校验值…');const digest=await sha256(bytes);checkCancel();
      const upload=await deps.api(endpoint('files/'+encodeURIComponent(file.id)+'/start'),{size:bytes.length,sha256:digest,revision:sourceRevision});
      uploadId=upload.id;pendingUploadId=uploadId;checkCancel();
      const parts=[];
      for(let number=1;number<=upload.part_count;number++){
        checkCancel();setStatus('正在上传分片 '+number+' / '+upload.part_count+'…');
        const start=(number-1)*upload.part_size,blob=generatedBlob.slice(start,Math.min(bytes.length,start+upload.part_size));
        const md5=await hashwasm.md5(new Uint8Array(await blob.arrayBuffer()));
        const contentMd5=btoa(String.fromCharCode(...md5.match(/../g).map(h=>parseInt(h,16))));
        let etag;
        for(let attempt=0;attempt<3;attempt++){
          checkCancel();
          try{const permit=await deps.api(endpoint('uploads/'+uploadId+'/part'),{part_number:number,content_md5:contentMd5});checkCancel();etag=await putPart(permit,blob,()=>{});break;}
          catch(error){if(cancelRequested||attempt===2)throw error;setStatus('分片网络波动，正在重试…');}
        }
        parts.push({part_number:number,etag});
      }
      checkCancel();setStatus('正在校验并保存版本…');$('pdfPageCancelUpload').disabled=true;
      const result=await deps.api(endpoint('uploads/'+uploadId+'/complete'),{parts});
      completed=true;pendingUploadId=null;generatedBlob=null;
      deps.toast('PDF 版本 v'+result.version.number+' 已保存，发布后分享链接才会切换');
      const savedFile=file;closeNow();
      try{await deps.onChanged?.();}catch{}
      await showVersions(savedFile);
    }catch(error){
      if(uploadId&&!completed){
        try{await deps.api(endpoint('uploads/'+uploadId+'/abort'),{});pendingUploadId=null;}
        catch{pendingUploadId=uploadId;$('pdfPageCleanup').hidden=false;}
      }
      const message=error.status===409?'文件已在其他标签页或设备上变化，请下载当前整理结果，再重新打开文件。':error.message;
      setStatus('保存版本失败',message+(generatedBlob?' 生成结果仍可下载到本地。':''));
    }finally{busy=false;cancelRequested=false;$('pdfPageCancelUpload').disabled=false;updateControls();}
  }
  function downloadGenerated(){
    if(!generatedBlob)return;
    const url=URL.createObjectURL(generatedBlob),link=document.createElement('a');
    link.href=url;link.download=(file?.filename||'document.pdf').replace(/\.pdf$/i,'')+'-页面整理.pdf';document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  function closeNow(){
    observer?.disconnect();observer=null;
    const task=previewTask;previewTask=null;previewDoc=null;if(task)task.destroy().catch(()=>{});
    sourceBytes=null;sourcePageCount=0;pages=[];history=[];cards.clear();generatedBlob=null;file=null;
    $('pdfPageClosePrompt').hidden=true;$('pdfPageCleanup').hidden=true;
    if($('pdfPageEditor').open)$('pdfPageEditor').close();
  }
  function askClose(){
    if(opening)return;
    if(busy){setStatus('请先完成或取消当前保存');return;}
    if(!dirty()&&!pendingUploadId){closeNow();return;}
    $('pdfPageClosePrompt').querySelector('p').textContent=pendingUploadId?
      '页面调整尚未保存；未完成上传暂未清理成功，可先返回重试。后续 PDF 操作会重试清理。':
      '这些调整尚未保存为版本。关闭后，本次页面顺序、旋转、删除和空白页操作会丢失。';
    $('pdfPageClosePrompt').hidden=false;$('pdfPageKeepEditing').focus();
  }
  async function cleanupPending(){
    if(!pendingUploadId)return;
    try{await deps.api(endpoint('uploads/'+pendingUploadId+'/abort'),{});pendingUploadId=null;$('pdfPageCleanup').hidden=true;deps.toast('未完成上传已清理');}
    catch(error){setStatus('清理失败',error.message);}
  }
  function displayDate(value){
    const numeric=typeof value==='number'||/^\d+$/.test(String(value));const time=numeric?Number(value):NaN;
    const parsed=numeric?new Date(time<1e12?time*1000:time):new Date(value);
    return Number.isNaN(parsed.getTime())?'—':parsed.toLocaleString('zh-CN',{hour12:false});
  }
  async function showVersions(candidate){
    if(!canEdit(candidate))throw new Error('该文件暂不支持 PDF 页面整理');
    versionFile=candidate;versionItems=[];
    $('pdfVersionsTitle').textContent=candidate.filename+' · 版本记录';$('pdfVersionsMessage').textContent='';
    if(!$('pdfVersions').open)$('pdfVersions').showModal();
    await reloadVersions();
  }
  async function reloadVersions(){
    const target=versionFile,body=$('pdfVersionsBody');body.textContent='正在加载版本…';
    try{
      const result=await deps.api(endpoint('files/'+encodeURIComponent(target.id)+'/versions'));
      if(target!==versionFile)return;
      versionItems=Array.isArray(result.items)?result.items:[];
      body.innerHTML=versionItems.length?versionItems.map(item=>`<div class="office-version-row"><div><strong>版本 v${deps.esc(item.number)}</strong><small>${deps.esc(displayDate(item.created_at))} · ${deps.esc(deps.size(item.size))}</small></div>${item.published?'<span class="badge">当前已发布</span>':`<button type="button" data-pdf-publish="${deps.esc(item.id)}">发布此版本</button>`}</div>`).join(''):'<p class="muted">暂无保存版本。整理页面后点击“保存版本”。</p>';
    }catch(error){if(target===versionFile)body.textContent='读取版本失败：'+error.message;}
  }
  function bind(){
    ensureObserver();observer.disconnect();
    $('pdfPageGrid').onclick=event=>{
      const card=event.target.closest('[data-key]');if(!card)return;
      const action=event.target.closest('[data-pdf-action]')?.dataset.pdfAction;
      if(action){const index=pages.findIndex(p=>p.key===card.dataset.key);move(card.dataset.key,index+(action==='up'?-1:1));}
      else changeSelection(card.dataset.key);
    };
    $('pdfPageGrid').onkeydown=event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('.pdf-page-card')){event.preventDefault();changeSelection(event.target.dataset.key);}};
    let dragged='';
    $('pdfPageGrid').ondragstart=event=>{const card=event.target.closest('[data-key]');if(!card||busy)return event.preventDefault();dragged=card.dataset.key;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',dragged);card.classList.add('dragging');};
    $('pdfPageGrid').ondragover=event=>{if(!dragged)return;const card=event.target.closest('[data-key]');if(!card||card.dataset.key===dragged)return;event.preventDefault();event.dataTransfer.dropEffect='move';};
    $('pdfPageGrid').ondrop=event=>{const card=event.target.closest('[data-key]');if(!dragged||!card)return;event.preventDefault();const to=pages.findIndex(p=>p.key===card.dataset.key);move(dragged,to);dragged='';document.querySelectorAll('.pdf-page-card.dragging').forEach(node=>node.classList.remove('dragging'));};
    $('pdfPageGrid').ondragend=()=>{dragged='';document.querySelectorAll('.pdf-page-card.dragging').forEach(node=>node.classList.remove('dragging'));};
    $('pdfPageUndo').onclick=()=>undoRedo(-1);$('pdfPageRedo').onclick=()=>undoRedo(1);
    $('pdfPageLeft').onclick=()=>rotate(-90);$('pdfPageRight').onclick=()=>rotate(90);
    $('pdfPageDelete').onclick=removeSelected;$('pdfPageBefore').onclick=()=>insertBlank(false);$('pdfPageAfter').onclick=()=>insertBlank(true);
    $('pdfPageSave').onclick=save;$('pdfPageClose').onclick=askClose;
    $('pdfPageCancelUpload').onclick=()=>{cancelRequested=true;activeXhr?.abort();setStatus('正在取消保存并清理上传…');};
    $('pdfPageDownload').onclick=downloadGenerated;$('pdfPageCleanup').onclick=cleanupPending;
    $('pdfPageEditor').addEventListener('cancel',event=>{event.preventDefault();askClose();});
    $('pdfPageKeepEditing').onclick=()=>{$('pdfPageClosePrompt').hidden=true;};
    $('pdfPageDiscard').onclick=closeNow;
    $('pdfPageShowVersions').onclick=()=>showVersions(file).catch(error=>deps.toast(error.message));
    $('pdfVersionsClose').onclick=()=>$('pdfVersions').close();
    $('pdfVersionsBody').onclick=async event=>{
      const button=event.target.closest('[data-pdf-publish]');if(!button||!versionFile)return;
      const item=versionItems.find(value=>String(value.id)===button.dataset.pdfPublish);if(!item||item.published)return;
      if(button.dataset.confirm!=='1'){
        $('pdfVersionsBody').querySelectorAll('[data-pdf-publish]').forEach(other=>{other.dataset.confirm='';other.textContent='发布此版本';});
        button.dataset.confirm='1';button.textContent='确认发布 v'+item.number;return;
      }
      button.disabled=true;
      try{
        await deps.api(endpoint('files/'+encodeURIComponent(versionFile.id)+'/publish'),{version_id:item.id});
        $('pdfVersionsMessage').textContent='版本 v'+item.number+' 已发布，分享链接已切换。';
        await reloadVersions();await deps.onChanged?.();
      }catch(error){$('pdfVersionsMessage').textContent='发布失败：'+error.message;button.disabled=false;}
    };
    window.addEventListener('beforeunload',event=>{if(isOpen()&&(busy||dirty())){event.preventDefault();event.returnValue='';}});
  }
  return {configure,canEdit,isOpen,open,showVersions};
})();
