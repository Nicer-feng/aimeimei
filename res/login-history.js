(() => {
  const $ = id => document.getElementById(id);
  const platform = { ios: 'iOS App', android: '安卓 App', web_desktop: 'PC Web', web_mobile: '手机浏览器', unknown: '未识别' };
  const session = { valid: '会话有效', logged_out: '已退出', expired: '已过期', invalid: '已失效', account_disabled: '账号停用', unknown: '未记录' };
  const permission = { authorized: '已允许', denied: '已拒绝', not_determined: '未询问', provisional: '临时允许', ephemeral: '临时授权', not_supported: '不支持', unknown: '未知/未上报' };
  const formatter = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const stamp = value => value ? formatter.format(new Date(value * 1000)) : '未记录';
  let mode = 'records', before = 0, next = null, previous = [], revision = 0;
  function text(value) { return value || '未上报'; }
  function app(client) { return client.app_version ? client.app_version + (client.app_build ? ' (' + client.app_build + ')' : '') : '未上报'; }
  function lines(values) {
    const box = document.createElement('div');
    for (const value of values) { const line = document.createElement('div'); line.textContent = value; box.append(line); }
    return box;
  }
  function clear() {
    revision++; before = 0; next = null; previous = [];
    $('loginHistoryRows')?.replaceChildren();
    if ($('loginHistoryUser')) $('loginHistoryUser').replaceChildren(new Option('全部账号', ''));
    if ($('loginHistoryStatus')) $('loginHistoryStatus').textContent = '';
  }
  function controls() {
    document.querySelectorAll('[data-history-mode]').forEach(n => {
      n.classList.toggle('active', n.dataset.historyMode === mode);
      n.setAttribute('aria-selected', String(n.dataset.historyMode === mode));
    });
    $('loginHistoryEventFilters').hidden = mode !== 'records';
    $('loginHistoryEventFilters').style.display = mode === 'records' ? '' : 'none';
    $('loginHistoryPrev').disabled = previous.length === 0;
    $('loginHistoryNext').disabled = !next;
  }
  function header(titles) {
    const tr = document.createElement('tr');
    const widths = mode === 'records' ? [9,16,13,10,11,14,12,8,7] : [24,18,18,14,26];
    $('loginHistoryTable').style.minWidth = mode === 'records' ? '1120px' : '1000px';
    titles.forEach((title,index) => { const th = document.createElement('th'); th.textContent = title; th.style.cssText = 'padding:10px 12px;overflow-wrap:anywhere;width:' + (widths[index] || 100) + '%'; tr.append(th); });
    $('loginHistoryHead').replaceChildren(tr);
  }
  function render(items) {
    header(mode === 'records' ? ['账号', '登录时间（北京）', '来源 IP', '客户端', '操作系统', '浏览器', '设备型号', 'App 版本', '会话状态'] :
      ['设备资料（客户端声明）', '登录时间（北京）', '最近活跃（北京）', '会话记录', '通知状态（分别核对）']);
    const body = $('loginHistoryRows'); body.replaceChildren();
    for (const item of items) {
      const c = item.client || {}, native = ['ios', 'android'].includes(c.platform), row = document.createElement('tr');
      let values;
      if (mode === 'records') {
        values = [item.username, stamp(item.logged_at), item.source_ip || '未记录', platform[c.platform] || '未识别',
          text([c.os_name,c.os_version].filter(Boolean).join(' ')), native ? '不适用' : text([c.browser,c.browser_version].filter(Boolean).join(' ')),
          native ? text([c.manufacturer,c.model].filter(Boolean).join(' ')) : '不适用', native ? app(c) : '不适用', session[item.session_state] || '未记录'];
      } else {
        const n = item.notification || {};
        const notifications = [
          '授权上报：' + (permission[n.authorization] || '未知/未上报') + ' · ' + stamp(n.reported_at),
          n.capability === 'apns' ? ('APNs：' + ({ registered:'已注册', invalid:'注册已失效', not_registered:'未注册' }[n.registration] || '未知')) : '推送能力：未接入',
          n.capability === 'apns' ? '绑定会话：' + (n.binding_session_valid ? '有效' : '无有效绑定') : '绑定会话：不适用',
          '后台策略：' + (n.policy_enabled ? '允许通知' : '不发送通知')
        ];
        if (n.last_apns_state === 'accepted') notifications.push('苹果已接受（非送达确认）');
        else if (n.last_apns_state) notifications.push('投递记录：' + ({ pending:'待重试', sending:'投递中', invalid:'无效设备', cancelled:'已取消' }[n.last_apns_state] || '未确认'));
        values = [lines([platform[c.platform] || '未识别', native ? text([c.manufacturer,c.model].filter(Boolean).join(' ')) : '硬件型号：不适用',
          text([c.os_name,c.os_version].filter(Boolean).join(' ')), native ? 'App：' + app(c) : text([c.browser,c.browser_version].filter(Boolean).join(' ')),
          '资料上报：' + stamp(item.reported_at), item.installation_known ? '随机安装实例' : '安装实例未上报']),
          lines(['首次：' + stamp(item.first_login_at), '最近：' + stamp(item.last_login_at)]),
          lines([stamp(item.last_active_at), '活跃 IP：' + (item.last_active_ip || '未记录')]),
          lines(Object.entries(item.sessions || {}).map(([key,count]) => (session[key] || key) + '：' + count).concat(Object.keys(item.sessions || {}).length ? [] : ['未关联会话'])), lines(notifications)];
      }
      for (const value of values) {
        const td = document.createElement('td'); td.style.cssText = 'padding:12px;vertical-align:top;border-top:1px solid var(--line);overflow-wrap:anywhere';
        if (value instanceof Node) td.append(value); else td.textContent = value;
        row.append(td);
      }
      body.append(row);
    }
    $('loginHistoryStatus').textContent = items.length ? '本页 ' + items.length + ' 条 · 北京时间 · 90天保留期' : '暂无记录';
    controls();
  }
  async function load(reset = false) {
    if (reset) { before = 0; previous = []; }
    const ticket = ++revision, user = $('loginHistoryUser').value;
    $('loginHistoryRows').replaceChildren(); $('loginHistoryStatus').textContent = '读取中'; next = null; controls();
    if (!hasAdminAccess()) { clear(); return; }
    if (mode === 'devices' && !user) { header(['设备记录']); $('loginHistoryStatus').textContent = '未选择账号'; return; }
    const params = new URLSearchParams({ limit: '50', before: String(before) });
    if (mode === 'records') {
      if (user) params.set('user_id',user);
      for (const [id,key] of [['loginHistoryPlatform','platform'],['loginHistoryFrom','from'],['loginHistoryTo','to']]) {
        if ($(id).value) params.set(key,$(id).value);
      }
    }
    const path = mode === 'records' ? '/api/admin/login-records' : '/api/admin/users/' + encodeURIComponent(user) + '/devices';
    try {
      const res = await adminApi(path + '?' + params);
      if (!res.ok) throw new Error('read failed');
      const data = await res.json();
      if (ticket !== revision || !hasAdminAccess()) return;
      next = data.next_before; render(mode === 'records' ? data.records || [] : data.devices || []);
    } catch (_) { if (ticket === revision) { $('loginHistoryRows').replaceChildren(); $('loginHistoryStatus').textContent = '读取失败或管理员权限已变化'; } }
  }
  async function open(user = '', selectedMode = 'records') {
    clear(); mode = selectedMode; const ticket = revision;
    controls();
    try {
      const res = await adminApi('/api/admin/users');
      if (!res.ok) throw new Error('read failed');
      const data = await res.json(); if (ticket !== revision) return;
      $('loginHistoryUser').replaceChildren(new Option('全部账号', ''));
      for (const item of data.users || []) $('loginHistoryUser').add(new Option(item.username, item.id));
      $('loginHistoryUser').value = user; await load(true);
    } catch (_) { if (ticket === revision) $('loginHistoryStatus').textContent = '账号列表读取失败'; }
  }
  for (const id of ['loginHistoryUser','loginHistoryPlatform','loginHistoryFrom','loginHistoryTo']) $(id)?.addEventListener('change', () => load(true));
  $('loginHistoryRefresh')?.addEventListener('click', () => load(true));
  $('loginHistoryNext')?.addEventListener('click', () => { if (next) { previous.push(before); before = next; load(); } });
  $('loginHistoryPrev')?.addEventListener('click', () => { if (previous.length) { before = previous.pop(); load(); } });
  document.querySelectorAll('[data-history-mode]').forEach(n => n.addEventListener('click', () => { mode = n.dataset.historyMode; load(true); }));
  globalThis.MeimeiLoginHistory = { open, clear };
})();
