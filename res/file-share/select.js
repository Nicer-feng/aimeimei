'use strict';
// Preserve native select values and form submission; enhance only single-choice controls.
(()=>{
  let active=null,serial=0;
  const widgets=new WeakMap();
  function close(restore=false){
    if(!active)return;
    const {button,popup}=active;active=null;button.setAttribute('aria-expanded','false');popup.remove();
    if(restore&&button.isConnected)button.focus();
  }
  function enhance(select){
    if(select.multiple||widgets.has(select))return;
    const button=document.createElement('button');button.type='button';button.className='select-trigger';
    const text=document.createElement('span'),chevron=document.createElement('span');
    chevron.className='select-chevron';chevron.setAttribute('aria-hidden','true');chevron.textContent='⌄';
    button.append(text,chevron);select.after(button);select.hidden=true;
    button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
    button.setAttribute('aria-label',select.getAttribute('aria-label')||select.closest('label')?.childNodes[0]?.textContent.trim()||'选择选项');
    const sync=()=>{text.textContent=select.selectedOptions[0]?.textContent||'请选择';button.disabled=select.disabled;};
    widgets.set(select,{button,sync});sync();select.addEventListener('change',sync);
    button.onclick=()=>{if(active?.button===button){close();return;}open(select,button);};
    button.onkeydown=e=>{if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();open(select,button,e.key);}};
  }
  function open(select,button,key){
    close();
    const popup=document.createElement('div');popup.className='select-popup';popup.id='select-popup-'+(++serial);
    popup.setAttribute('role','listbox');popup.setAttribute('aria-label',button.getAttribute('aria-label'));
    button.setAttribute('aria-controls',popup.id);button.setAttribute('aria-expanded','true');
    const options=[...select.options],buttons=[];
    options.forEach((option,index)=>{
      const item=document.createElement('button');item.type='button';item.className='select-option';item.tabIndex=-1;
      item.setAttribute('role','option');item.setAttribute('aria-selected',String(option.selected));item.disabled=option.disabled;
      const label=document.createElement('span'),mark=document.createElement('span');label.textContent=option.textContent;mark.textContent=option.selected?'✓':'';mark.setAttribute('aria-hidden','true');item.append(label,mark);
      item.onclick=()=>{select.selectedIndex=index;widgets.get(select).sync();close(true);select.dispatchEvent(new Event('change',{bubbles:true}));};
      popup.append(item);buttons.push(item);
    });
    (button.closest('dialog[open]')||document.body).append(popup);
    active={button,popup};
    const rect=button.getBoundingClientRect(),height=window.innerHeight,width=window.innerWidth;
    popup.style.width=Math.min(Math.max(rect.width,150),width-24)+'px';
    const below=height-rect.bottom-16,above=rect.top-16,up=below<220&&above>below;
    popup.style.maxHeight=Math.max(60,Math.min(320,up?above:below))+'px';
    popup.style.left=Math.max(12,Math.min(rect.left,width-popup.offsetWidth-12))+'px';
    popup.style.top=(up?Math.max(12,rect.top-popup.offsetHeight-6):rect.bottom+6)+'px';
    const enabled=buttons.filter(b=>!b.disabled);
    const first=key==='End'?enabled.at(-1):key==='Home'?enabled[0]:buttons[select.selectedIndex]||enabled[0];
    first?.focus({preventScroll:true});first?.scrollIntoView({block:'nearest'});
    popup.onkeydown=e=>{
      const index=enabled.indexOf(document.activeElement);
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}
      else if(e.key==='Tab'){close(true);}
      else if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
        e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?enabled.length-1:(index+(e.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length;enabled[next]?.focus();
      }
    };
  }
  document.addEventListener('pointerdown',e=>{if(active&&!active.popup.contains(e.target)&&!active.button.contains(e.target))close();},true);
  document.addEventListener('scroll',e=>{if(active&&!active.popup.contains(e.target))close();},true);
  window.addEventListener('resize',()=>close());
  document.addEventListener('close',()=>close(),true);
  function scan(){if(active&&!active.button.isConnected)close();document.querySelectorAll('select').forEach(enhance);}
  new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true});
  scan();
})();
