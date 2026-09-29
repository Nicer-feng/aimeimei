'use strict';
/* Local Markdown rendering. No document contents leave the existing storage flow. */
window.CloudMarkdown = (() => {
  let loading,parser;
  function script(src,ready) {
    if(ready())return Promise.resolve();
    return new Promise((resolve,reject)=>{
      const element=document.createElement('script');element.src=src;
      const timeout=setTimeout(()=>finish(new Error('Markdown 组件加载超时')),12000);
      function finish(error){clearTimeout(timeout);element.onload=element.onerror=null;if(error){element.remove();reject(error);}else resolve();}
      element.onload=()=>finish(ready()?null:new Error('Markdown 组件不可用'));
      element.onerror=()=>finish(new Error('Markdown 组件加载失败'));
      document.head.append(element);
    });
  }
  function load() {
    if(!loading)loading=(async()=>{
      await Promise.all([
        script('/res/vendor/markdown-it-14.3.0.min.js',()=>Boolean(window.markdownit)),
        script('/res/vendor/dompurify-3.4.12.min.js',()=>Boolean(window.DOMPurify?.sanitize)),
        script('/res/vendor/highlight-11.11.1.min.js',()=>Boolean(window.hljs))
      ]);
      await script('/res/vendor/markdown-it-task-lists-2.1.1.min.js',()=>Boolean(window.markdownitTaskLists));
      parser=window.markdownit({html:false,linkify:false,breaks:false,maxNesting:20,highlight:(code,language)=>{
        if(code.length<=50000&&language&&window.hljs.getLanguage(language)){
          try{return window.hljs.highlight(code,{language,ignoreIllegals:true}).value;}catch{}
        }
        return '';
      }}).use(window.markdownitTaskLists,{enabled:false,label:false});
      // External images are explicit links: opening a document never fetches trackers.
      parser.renderer.rules.image=(tokens,index)=>{
        const token=tokens[index],src=token.attrGet('src')||'',alt=parser.utils.escapeHtml(token.content||'图片');
        return safeLink(src)?'<a class="cloud-md-image-link" href="'+parser.utils.escapeHtml(src)+'">查看图片：'+alt+'</a>':'<span class="cloud-md-image-note">图片：'+alt+'（相对路径图片暂不支持）</span>';
      };
    })().catch(error=>{loading=null;throw error;});
    return loading;
  }
  function safeLink(raw) {
    if(!/^https?:\/\//i.test(raw))return false;
    try{const url=new URL(raw);return !url.username&&!url.password;}catch{return false;}
  }
  const anchor=text=>'cloud-md-'+text.trim().toLowerCase().replace(/[^\p{L}\p{N}_ -]/gu,'').replace(/\s+/g,'-');
  async function render(text) {
    await load();
    const fragment=window.DOMPurify.sanitize(parser.render(text),{
      RETURN_DOM_FRAGMENT:true,
      ALLOWED_TAGS:['p','br','hr','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','pre','code','em','strong','s','del','a','span','table','thead','tbody','tr','th','td','input'],
      ALLOWED_ATTR:['href','title','class','start','type','checked','disabled'],
      ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false
    });
    const used=new Map();
    fragment.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(heading=>{
      const base=anchor(heading.textContent),count=used.get(base)||0;used.set(base,count+1);heading.id=base+(count?'-'+count:'');
    });
    fragment.querySelectorAll('a').forEach(link=>{
      const href=link.getAttribute('href')||'';
      if(href.startsWith('#')){
        let target;try{target=anchor(decodeURIComponent(href.slice(1)));}catch{target='';}
        link.setAttribute('href','#'+target);link.onclick=event=>{event.preventDefault();const article=link.closest('.cloud-markdown');const heading=article&&[...article.querySelectorAll('[id]')].find(node=>node.id===target);heading?.scrollIntoView({block:'start'});};
      }else if(safeLink(href)){link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';}
      else{link.removeAttribute('href');link.title='相对路径或不支持的链接';}
    });
    fragment.querySelectorAll('input').forEach(input=>{input.type='checkbox';input.disabled=true;input.tabIndex=-1;});
    fragment.querySelectorAll('table').forEach(table=>{const wrap=document.createElement('div');wrap.className='cloud-md-table';wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Markdown 表格，可横向滚动');table.replaceWith(wrap);wrap.append(table);});
    fragment.querySelectorAll('pre').forEach(pre=>{pre.tabIndex=0;pre.classList.add('cloud-md-code');});
    return fragment;
  }
  return {render};
})();
