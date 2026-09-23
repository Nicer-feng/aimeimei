'use strict';
window.CloudPlatform=(()=>{
  const {esc,icon,size,date,api,toast}=FS;
  let days=7,search='',userId='';
  const base='/api/file-share/admin/platform';
  const time=t=>t?date(t):'尚无记录';
  const cards=items=>'<div class="stats platform-stats">'+items.map(([label,value])=>`<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`).join('')+'</div>';
  async function render(page){
    const d=await api(base+'/report?'+new URLSearchParams({days,page,search,user_id:userId}));
    const t=d.totals,p=d.period;
    return `<div class="toolbar platform-filter"><select id="platformDays" aria-label="统计时间">${[7,30,90].map(n=>`<option value="${n}" ${n===days?'selected':''}>最近 ${n} 天</option>`).join('')}</select><button id="platformRefresh">${icon('refresh-cw')}刷新统计</button>${userId?'<button id="platformAll">返回全平台统计</button><span class="badge">当前统计：选定用户</span>':''}</div>`+
    cards([['已启用云用户',t.user_count],['正常文件',t.file_count],['存储占用（含回收站）',size(t.storage_bytes)],['有效分享',t.active_shares],['今日成功上传',size(d.today.upload_bytes)],['今日下载请求',d.today.downloads]])+
    `<div class="notice platform-note">下载申请量（估算）按成功签发下载链接的文件大小累计，不代表实际传输或下载完成；预览、视频 Range、重试等实际流量需 OSS 日志。上传量为成功完成上传的文件大小，不含失败分片和重试。日期按北京时间。登录/访问时间从本版本开始记录，历史未知不补填。</div>`+
    cards([['期间成功上传',size(p.upload_bytes)],['期间下载申请量（估算）',size(p.download_bytes)],['期间下载请求',p.downloads],['期间预览请求',p.previews],['回收站占用',size(t.trash_bytes)],['未完成上传任务',t.pending_uploads]])+
    `<h3>按日统计</h3><div class="table-wrap"><table><thead><tr><th>日期</th><th>上传数 / 上传量</th><th>下载请求 / 申请量（估算）</th><th>预览</th><th>页面访问</th><th>未通过请求</th></tr></thead><tbody>${d.daily.map(r=>`<tr><td>${esc(r.day)}</td><td>${r.uploads} / ${size(r.upload_bytes)}</td><td>${r.downloads} / ${size(r.download_bytes)}</td><td>${r.previews}</td><td>${r.views}</td><td>${r.failures}</td></tr>`).join('')}</tbody></table></div>
    <h3 class="section-title">用户管理</h3><p class="muted">复用现有账号；开通云权限不会授予 AI 管理权限。停用云权限仅禁止进入云工作空间，已有分享仍按原规则有效。账号整体停用状态由统一账号体系管理。</p><div class="toolbar"><input id="platformSearch" value="${esc(search)}" placeholder="搜索账号或名称" aria-label="搜索用户"><button id="platformSearchButton">搜索用户</button></div>
    <div class="table-wrap"><table><thead><tr><th>用户 / 权限</th><th>账号 / 云状态</th><th>最后云登录</th><th>最近进入云</th><th>文件 / 存储（含回收站）</th><th>分享数</th><th>期间上传量</th><th>期间下载请求 / 申请量（估算）</th><th>操作</th></tr></thead><tbody>${d.users.map(u=>`<tr><td>${esc(u.display_name||u.username)}<br><small>${esc(u.username)} · ${u.role==='admin'?'平台管理员':'普通用户'}</small></td><td>${u.is_active?'账号正常':'账号停用'} / ${u.cloud_enabled?'已开通云':'未开通云'}</td><td>${time(u.last_login_at)}</td><td>${time(u.last_visit_at)}</td><td>${u.file_count} / ${size(u.storage_bytes)}</td><td>${u.share_count}</td><td>${size(u.upload_bytes)}</td><td>${u.downloads} / ${size(u.download_bytes)}</td><td><div class="table-actions"><button data-platform-user="${esc(u.id)}">查看统计</button>${u.role==='admin'?'':`<button data-cloud-access="${esc(u.id)}" data-enabled="${!u.cloud_enabled}">${u.cloud_enabled?'停用云权限':'开通云权限'}</button>`}</div></td></tr>`).join('')}</tbody></table></div><div class="pagination"><span>共 ${d.total} 个账号 · 第 ${page} 页</span><button data-page="${page-1}" ${page<=1?'disabled':''}>上一页</button><button data-page="${page+1}" ${page*20>=d.total?'disabled':''}>下一页</button></div>`;
  }
  function bind(reset,refresh){
    const run=fn=>()=>Promise.resolve(fn()).catch(e=>toast(e.message));
    document.getElementById('platformDays').onchange=run(()=>{days=Number(document.getElementById('platformDays').value);return reset();});
    document.getElementById('platformRefresh').onclick=run(refresh);
    const searchFn=()=>{search=document.getElementById('platformSearch').value;return reset();};
    document.getElementById('platformSearchButton').onclick=run(searchFn);
    document.getElementById('platformSearch').onkeydown=e=>{if(e.key==='Enter')run(searchFn)();};
    const all=document.getElementById('platformAll');if(all)all.onclick=run(()=>{userId='';return reset();});
    document.querySelectorAll('[data-platform-user]').forEach(b=>b.onclick=run(()=>{userId=b.dataset.platformUser;return reset();}));
    document.querySelectorAll('[data-cloud-access]').forEach(b=>b.onclick=()=>{
      const enabled=b.dataset.enabled==='true';
      FS.dialog(enabled?'开通云权限？':'停用云权限？',`<p>${enabled?'该账号将可以登录槑槑云并管理自己的文件。':'该账号将不能进入云工作空间，已有分享继续有效。'}</p><div class="form-footer"><button id="cancelCloudAccess">取消</button><button id="confirmCloudAccess" class="primary">确认</button></div>`);
      document.getElementById('cancelCloudAccess').onclick=FS.close;
      document.getElementById('confirmCloudAccess').onclick=async e=>{e.target.disabled=true;try{await api(base+'/access',{user_id:b.dataset.cloudAccess,enabled});FS.close();await refresh();toast('云权限已更新');}catch(error){toast(error.message);e.target.disabled=false;}};
    });
  }
  return {render,bind};
})();
