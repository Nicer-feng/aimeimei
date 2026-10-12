(() => {
  let clock = null, owner = '', serial = 0, syncing = false, sending = false;
  let nextSync = 0, lastSend = 0, lastEvent = 0;
  let focused = document.hasFocus();
  let clearViews = () => {};
  const userId = () => String(state.user?.id || '');
  const visible = () => state.authed && focused && document.visibilityState === 'visible' && document.hasFocus();
  const mode = () => window.MeimeiReader?.active && !document.body.matches('.dialog-open, .admin-open, .full-composer-open') && !document.querySelector('dialog[open], #tokenActivityDialog.show') ? 'reading' : 'work';
  function pauseTracking() {
    clock = null; nextSync = performance.now() + 30000;
    console.warn('Usage time tracking paused; it will retry in 30 seconds.');
  }
  function accountChanged() {
    if (owner === userId()) return;
    owner = userId(); serial++;
    clock = null; syncing = false; sending = false; nextSync = 0;
    try { clearViews(); } catch { pauseTracking(); }
  }
  async function sync() {
    accountChanged();
    if (!owner || clock || syncing || performance.now() < nextSync) return;
    syncing = true;
    const ticket = serial, started = performance.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      // Telemetry errors must not invoke the chat API's login/state transitions.
      const res = await fetch('/api/usage-time/config', { credentials: 'same-origin', signal: controller.signal });
      if (!res.ok) throw new Error();
      const data = await res.json(), ended = performance.now();
      if (ticket !== serial || owner !== userId()) return;
      if (ended-started > 10000) throw new Error();
      clock = new UsageClock(data.server_now_ms + (ended-started)/2, ended, data.idle_ms);
      lastSend = ended;
    } catch { if (ticket === serial) nextSync = performance.now() + 30000; }
    finally { clearTimeout(timeout); if (ticket === serial) syncing = false; }
  }
  function tick(activity = false) {
    try {
      accountChanged();
      if (!clock) { void sync().catch(pauseTracking); return; }
      clock.step(performance.now(), visible(), mode(), activity);
    } catch { pauseTracking(); }
  }
  async function flush(keepalive = false) {
    try { await flushPending(keepalive); } catch { pauseTracking(); }
  }
  async function flushPending(keepalive) {
    tick();
    if (!clock || sending || !owner) return;
    const batch = clock.take(performance.now());
    if (!batch.length) return;
    const ticket = serial, current = clock;
    sending = true; lastSend = performance.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch('/api/usage-time/heartbeat', { method: 'POST', credentials: 'same-origin', keepalive,
        headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ account_id: owner, segments: batch }) });
      if (ticket !== serial || owner !== userId()) return;
      if (res.status === 400) { clock = null; nextSync = 0; }
      else if (!res.ok) throw new Error();
    } catch {
      if (ticket === serial && clock === current) {
        current.pending.unshift(...batch);
        current.pending = current.pending.filter(p => p.start_ms >= performance.now()+current.origin-110000).slice(-32);
      }
    } finally { clearTimeout(timeout); if (ticket === serial) sending = false; }
  }
  function activity(event) {
    if (!event.isTrusted || performance.now()-lastEvent < 250) return;
    lastEvent = performance.now(); tick(true);
  }
  // Intent events, not mousemove or programmatic scrolling/stream animations.
  for (const name of ['pointerdown','keydown','wheel','touchstart','touchmove']) document.addEventListener(name, activity, { passive: true, capture: true });
  document.addEventListener('visibilitychange', () => { tick(); if (document.hidden) void flush(true); });
  window.addEventListener('blur', () => { focused=false; tick(); void flush(true); });
  window.addEventListener('focus', () => { focused=true; tick(); });
  window.addEventListener('pageshow', () => { focused=document.hasFocus(); tick(); });
  window.addEventListener('pagehide', () => { tick(); void flush(true); if (clock) clock.visible = false; });
  window.addEventListener('online', () => { tick(); void flush(); });
  setInterval(() => { tick(); if (performance.now()-lastSend >= 30000) void flush(); }, 5000);
  window.MeimeiUsage = { accountChanged, modeChanged() { tick(); void flush(); }, flush };
  window.addEventListener('meimei:reading-mode-change', () => window.MeimeiUsage.modeChanged());
  const modeObserver = new MutationObserver(() => { if (clock && mode() !== clock.mode) window.MeimeiUsage.modeChanged(); });
  modeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  modeObserver.observe(document.getElementById('tokenActivityDialog'), { attributes: true, attributeFilter: ['class'] });
  document.querySelectorAll('dialog').forEach(dialog => modeObserver.observe(dialog, { attributes: true, attributeFilter: ['open'] }));
  void sync();

  const el = (tag, text, className) => {
    const node = document.createElement(tag); if (text != null) node.textContent = text;
    if (className) node.className = className; return node;
  };
  const duration = ms => {
    const minutes = Math.floor(ms/60000);
    return minutes >= 60 ? `${Math.floor(minutes/60)}小时${minutes%60}分` : minutes ? `${minutes}分` : ms ? '不足1分钟' : '0分';
  };
  const date = d => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  const percent = row => row.work_ms+row.reading_ms ? `${(100*row.reading_ms/(row.work_ms+row.reading_ms)).toFixed(1)}%` : '—';
  const views = new Map();
  clearViews = () => { for (const view of views.values()) { view.request++; clearTimeout(view.timer); view.root.replaceChildren(); } views.clear(); };
  function makeView(root, admin) {
    const view = { root, admin, request: 0, timer: 0 };
    root.classList.add('usage-time-view');
    const filter = el('div', null, 'usage-time-filter');
    function input(label, node) { const wrap = el('label',label); wrap.append(node); filter.append(wrap); return node; }
    view.range = input('时间范围',el('select'));
    for (const [value,label] of [['1','今天'],['7','近7天'],['30','近30天'],['custom','自定义']]) {
      const option = el('option',label);option.value=value;view.range.append(option);
    }
    view.start = input('开始日期',el('input'));view.start.type='date';
    view.end = input('结束日期',el('input'));view.end.type='date';
    view.start.max = view.end.max = date(new Date());
    const preset = () => {
      const custom = view.range.value === 'custom';
      view.start.disabled = view.end.disabled = !custom;
      if (!custom) {
        view.end.value = date(new Date());
        view.start.value = date(new Date(Date.now()-(Number(view.range.value)-1)*86400000));
      }
    };
    preset();
    if (admin) {
      view.search = input('账号',el('input'));view.search.placeholder='用户名或昵称';view.search.maxLength=80;
      view.sort = input('排序',el('select'));
      for (const [value,label] of [['total','总时长'],['work','工作时长'],['reading','摸鱼时长'],['last','最后活跃']]) {
        const option = el('option',label);option.value=value;view.sort.append(option);
      }
      view.search.addEventListener('input', () => { clearTimeout(view.timer); view.request++; view.timer=setTimeout(() => load(view),250); });
      view.sort.addEventListener('change',() => load(view));
    }
    const refresh = el('button','刷新','ui-btn ui-btn-secondary');refresh.type='button';filter.append(refresh);
    refresh.addEventListener('click',() => load(view));
    view.range.addEventListener('change',() => { preset(); load(view); });
    for (const node of [view.start,view.end]) node.addEventListener('change',() => load(view));
    view.summary = el('div',null,'usage-time-summary');
    view.status = el('p',null,'usage-time-status');view.status.setAttribute('role','status');
    view.rows = el('div',null,'usage-time-results');
    root.append(filter,view.summary,el('p','仅统计前台有焦点的有效使用时间；连续2分钟无操作暂停。工作指普通模式，不代表实际工作产出。按北京时间统计，自本功能上线后开始。','usage-time-note'),view.status,view.rows);
    views.set(root.id,view);return view;
  }
  async function get(path) {
    const response = await api(path); const data = await response.json();
    if (!response.ok) throw new Error(data.error || '加载失败，请重试');
    return data;
  }
  function dailyTable(rows) {
    const scroll = el('div',null,'usage-time-table-scroll'), table = el('table');
    const head = el('thead'), hr = el('tr');
    ['日期','工作','摸鱼','总时长','摸鱼占比'].forEach(t => hr.append(el('th',t)));head.append(hr);table.append(head);
    const body = el('tbody');
    rows.forEach(row => { const tr = el('tr'); [row.date,duration(row.work_ms),duration(row.reading_ms),duration(row.work_ms+row.reading_ms),percent(row)].forEach(t=>tr.append(el('td',t)));body.append(tr); });
    table.append(body);scroll.append(table);
    return rows.length ? scroll : el('p','这段时间暂无使用记录','usage-time-note');
  }
  async function load(view) {
    const request = ++view.request, uid=userId();
    view.status.textContent='正在加载…';view.rows.replaceChildren();view.summary.replaceChildren();
    const params = new URLSearchParams({ start:view.start.value,end:view.end.value });
    if (view.admin) {params.set('q',view.search.value);params.set('sort',view.sort.value);}
    try {
      await flush();
      const data = await get('/api/usage-time/'+(view.admin?'admin':'self')+'?'+params);
      if (request !== view.request || uid !== userId()) return;
      const s=data.summary;
      for (const [label,value] of [['工作时长',duration(s.work_ms)],['摸鱼时长',duration(s.reading_ms)],['总有效时长',duration(s.total_ms)],...(view.admin?[['活跃账号',String(s.active_users)]]:[])]) {
        const item=el('div',null,'usage-time-metric');item.append(el('span',label),el('strong',value));view.summary.append(item);
      }
      view.status.textContent='';
      if (!view.admin) {view.rows.append(dailyTable(data.days));return;}
      if (!data.users.length) {view.rows.append(el('p','没有找到相关账号','usage-time-note'));return;}
      data.users.forEach(row => {
        const item=el('div',null,'usage-time-account'), heading=el('div',null,'usage-time-account-head');
        const identity=el('div');identity.append(el('strong',row.display_name?`${row.display_name} · ${row.username}`:row.username));
        identity.append(el('small',row.last_active?'最后活跃 '+new Date(row.last_active).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚无记录'));
        const button=el('button','每日明细','ui-btn ui-btn-secondary');button.type='button';button.setAttribute('aria-expanded','false');
        heading.append(identity,button);
        const numbers=el('div',null,'usage-time-account-numbers');
        for (const [label,value] of [['工作',duration(row.work_ms)],['摸鱼',duration(row.reading_ms)],['总计',duration(row.total_ms)],['摸鱼占比',percent(row)]]) {
          const part=el('span',label+' ');part.append(el('strong',value));numbers.append(part);
        }
        const detail=el('div',null,'usage-time-detail');detail.hidden=true;
        let loaded=false, busy=false;
        button.addEventListener('click',async () => {
          detail.hidden=!detail.hidden;button.setAttribute('aria-expanded',String(!detail.hidden));
          if (detail.hidden || loaded || busy) return;
          busy=true;detail.textContent='正在查询每日明细…';
          try {
            const details=new URLSearchParams(params);details.set('user_id',row.id);
            const result=await get('/api/usage-time/admin/user?'+details);
            if (request!==view.request || uid!==userId()) return;
            detail.replaceChildren(dailyTable(result.days));loaded=true;
          } catch(err) { if(uid===userId()) detail.textContent=err.message+'；收起后重试。'; }
          finally {busy=false;}
        });
        item.append(heading,numbers,detail);view.rows.append(item);
      });
    } catch(err) { if(request===view.request && uid===userId()) view.status.textContent=err.message; }
  }
  function open(id,admin) {
    const root=document.getElementById(id);
    if (!root || !state.user || (admin && state.user.role!=='admin')) return;
    void load(views.get(id)||makeView(root,admin));
  }
  window.MeimeiUsage.openAdmin = () => open('adminUsageTime',true);
  window.MeimeiUsage.openPersonal = () => open('personalUsageTime',false);
  document.querySelectorAll('[data-activity-tab]').forEach(button => button.addEventListener('click',() => {
    const usage=button.dataset.activityTab==='usage';
    document.querySelectorAll('[data-activity-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===button)));
    document.getElementById('tokenActivityContent').hidden=usage;
    document.getElementById('personalUsageTime').hidden=!usage;
    if(usage) window.MeimeiUsage.openPersonal(); else void loadTokenActivity();
  }));
})();
