(() => {
  const byId = id => document.getElementById(id);
  const cache = new Map(), pending = new Map();
  let epoch = 0, current = null, selected = '', adminRevision = 0, busy = false, budgetRevision = 0, budgetBusy = false;
  const isOfficial = model => Boolean(model?.uses_openai_egress);
  function paint() {
    document.querySelectorAll('[data-openai-health]').forEach(dot => {
      const entry = cache.get(dot.dataset.openaiHealth);
      const fresh = entry && entry.localExpires > Date.now();
      const status = pending.has(dot.dataset.openaiHealth) ? 'checking' : fresh ? entry.status : 'unknown';
      const message = status === 'checking' ? '正在检查接口连接' : fresh ? entry.message : '尚未检查；选中或使用时检查';
      dot.dataset.health = status;
      dot.title = 'OpenAI · ' + message;
      dot.setAttribute('aria-label', dot.title);
    });
  }
  async function check(model = current) {
    if (!isOfficial(model) || pending.has(model.id)) return;
    const entry = cache.get(model.id);
    if (entry && entry.localExpires > Date.now()) { paint(); return; }
    const ticket = epoch, id = model.id, abort = new AbortController();
    pending.set(id, abort); paint();
    const timeout = setTimeout(() => abort.abort(), 12000);
    try {
      const res = await api('/api/models/' + encodeURIComponent(id) + '/availability', { signal: abort.signal });
      if (!res.ok) throw new Error('检查失败，请稍后重试');
      const data = await res.json();
      if (ticket !== epoch) return;
      cache.set(id, { ...data, localExpires: Date.now() + Math.max(0, Math.min(90, (data.expires_at || 0) - (data.checked_at || Date.now() / 1000))) * 1000 });
    } catch (_) {
      if (ticket === epoch) cache.set(id, { status: 'unknown', message: '检查暂未完成；不代表模型不可用', localExpires: Date.now() + 15000 });
    } finally {
      clearTimeout(timeout);
      if (ticket === epoch) { pending.delete(id); paint(); }
    }
  }
  function sync(model) {
    current = model;
    const button = byId('modelPickerButton');
    let dot = byId('openaiCurrentHealth');
    if (isOfficial(model)) {
      if (!dot) {
        dot = document.createElement('span'); dot.id = 'openaiCurrentHealth'; dot.className = 'openai-health';
        dot.setAttribute('role', 'img'); button?.append(dot);
      }
      dot.hidden = false; dot.dataset.openaiHealth = model.id;
    } else if (dot) { dot.hidden = true; delete dot.dataset.openaiHealth; }
    paint();
    const id = model?.id || '';
    if (id !== selected) { selected = id; check(model); }
  }
  function accountChanged() {
    epoch++; adminRevision++; budgetRevision++; current = null; selected = '';
    for (const abort of pending.values()) abort.abort();
    pending.clear(); cache.clear();
    if (byId('openaiSubscription')) byId('openaiSubscription').value = '';
    if (byId('openaiBudgetSave')) byId('openaiBudgetSave').disabled = true;
    paint();
  }
  function message(value, error = false) {
    const node = byId('openaiEgressStatus');
    if (node) { node.textContent = value; node.classList.toggle('err', error); }
  }
  function render(data) {
    const cfg = data.egress || {}, select = byId('openaiEgressNode');
    byId('openaiEgressEnabled').checked = Boolean(cfg.enabled);
    byId('openaiSubscription').placeholder = cfg.subscription_configured ? '订阅已保存，留空保持原值' : 'HTTPS Clash / Mihomo 订阅链接';
    select.replaceChildren(new Option('选择节点', ''));
    for (const name of data.nodes || []) select.add(new Option(name, name));
    select.value = cfg.selected_node || '';
    byId('openaiEgressSummary').textContent = !cfg.installed ? '代理服务未安装' : cfg.enabled ? '已启用 · 仅官方 OpenAI API' : '已关闭 · 官方 OpenAI 请求不会回落直连';
    if (data.notice) message(data.notice, true);
  }
  async function readResponse(res) {
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '请求失败，请稍后重试');
    return data;
  }
  async function open() {
    loadBudget();
    const ticket = ++adminRevision;
    message('读取代理配置…');
    try {
      const data = await readResponse(await adminApi('/api/admin/openai-egress'));
      if (ticket !== adminRevision) return;
      render(data); message(data.notice || '');
      const models = await readResponse(await adminApi('/api/admin/models'));
      if (ticket !== adminRevision) return;
      const picker = byId('openaiTestModel'); picker.replaceChildren(new Option('选择官方 OpenAI 模型', ''));
      for (const model of models.models || []) if (isOfficial(model)) picker.add(new Option(model.name + ' · ' + model.model, model.id));
    } catch (error) { if (ticket === adminRevision) message(error.message, true); }
  }
  function budgetMessage(value, error = false) {
    const node = byId('openaiBudgetStatus');
    if (node) { node.textContent = value; node.classList.toggle('err', error); }
  }
  function renderBudget(cfg) {
    const usd = value => '$' + Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
    byId('openaiBudgetEnabled').checked = Boolean(cfg.enabled);
    byId('openaiBudgetLimit').value = cfg.limit_usd;
    byId('openaiBudgetRate').value = cfg.cny_per_usd;
    byId('openaiBudgetSpent').textContent = usd(cfg.spent_usd);
    byId('openaiBudgetCap').textContent = usd(cfg.limit_usd);
    byId('openaiBudgetRemaining').textContent = usd(cfg.remaining_usd);
    const progress = byId('openaiBudgetProgress');
    progress.value = cfg.limit_usd > 0 ? Math.min(100, cfg.spent_usd / cfg.limit_usd * 100) : 0;
    progress.dataset.exhausted = String(Boolean(cfg.exhausted));
    const status = !cfg.enabled ? '额度保护已关闭' : cfg.exhausted ? '本月额度已用完，OpenAI 新请求已暂停' : cfg.pending_limit ? '剩余额度已预留，等待当前请求结算' : cfg.warning ? '本月已使用超过 80% 的额度' : '额度正常';
    const pending = cfg.reserved_usd ? ' · 进行中预留 ' + usd(cfg.reserved_usd) : '';
    const uncertain = cfg.uncertain_requests ? ' · ' + cfg.uncertain_requests + ' 次缺少完整用量，已按预留保守计入' : '';
    const unpriced = cfg.unpriced_requests ? ' · ' + cfg.unpriced_requests + ' 次未配置单价，费用未计入' : '';
    byId('openaiBudgetSummary').textContent = cfg.period + ' · ' + status + pending + uncertain + unpriced + ' · 次月 1 日 00:00（北京时间）重置';
    byId('openaiBudgetSave').disabled = false;
  }
  async function loadBudget() {
    if (!byId('openaiBudgetSave') || budgetBusy) return;
    const ticket = ++budgetRevision;
    byId('openaiBudgetSave').disabled = true;
    budgetMessage('读取本月额度…');
    try {
      const data = await readResponse(await adminApi('/api/admin/openai-budget'));
      if (ticket !== budgetRevision) return;
      renderBudget(data.budget); budgetMessage('');
    } catch (error) { if (ticket === budgetRevision) budgetMessage(error.message, true); }
  }
  async function saveBudget() {
    if (budgetBusy || byId('openaiBudgetSave').disabled) return;
    const limit = Number(byId('openaiBudgetLimit').value), rate = Number(byId('openaiBudgetRate').value);
    if (!Number.isFinite(limit) || limit < .01 || limit > 1000000 || !Number.isFinite(rate) || rate < .01 || rate > 1000) {
      budgetMessage('请检查月度额度和美元折算汇率', true); return;
    }
    budgetBusy = true;
    const ticket = ++budgetRevision, button = byId('openaiBudgetSave');
    button.disabled = true; button.setAttribute('aria-busy', 'true'); budgetMessage('正在保存额度…');
    try {
      const data = await readResponse(await adminApi('/api/admin/openai-budget', { method: 'POST', body: JSON.stringify({
        enabled: byId('openaiBudgetEnabled').checked, limit_usd: limit, cny_per_usd: rate
      }) }));
      if (ticket !== budgetRevision) return;
      renderBudget(data.budget); cache.clear(); paint(); budgetMessage('额度已保存，后续 OpenAI 请求立即生效');
    } catch (error) {
      if (ticket === budgetRevision) { button.disabled = false; budgetMessage(error.message, true); }
    } finally { budgetBusy = false; button.removeAttribute('aria-busy'); }
  }
  byId('openaiBudgetSave')?.addEventListener('click', saveBudget);
  byId('openaiBudgetRefresh')?.addEventListener('click', loadBudget);
  async function action(button, fn) {
    if (busy) return;
    busy = true; const ticket = epoch;
    const buttons = [...document.querySelectorAll('[data-egress-action]')];
    buttons.forEach(node => { node.disabled = true; });
    button?.setAttribute('aria-busy', 'true');
    try { await fn(ticket); }
    catch (error) { if (ticket === epoch) message(error.message || '请求失败，请稍后重试', true); }
    finally {
      busy = false; buttons.forEach(node => { node.disabled = false; }); button?.removeAttribute('aria-busy');
    }
  }
  async function save(button, reload) {
    await action(button, async ticket => {
      message(reload ? '正在获取订阅并加载节点…' : '正在保存…');
      const data = await readResponse(await adminApi('/api/admin/openai-egress', { method: 'POST', body: JSON.stringify({
        enabled: byId('openaiEgressEnabled').checked, subscription_url: byId('openaiSubscription').value.trim(),
        selected_node: byId('openaiEgressNode').value, reload_subscription: reload
      }) }));
      if (ticket !== epoch) return;
      render(data); byId('openaiSubscription').value = ''; cache.clear(); paint();
      message(data.notice || (reload ? '订阅已更新，请选择节点并保存开关。' : '已保存'));
    });
  }
  async function test(button, payload, statusNode) {
    if (statusNode) statusNode.textContent = '正在检查连接…';
    await action(button, async ticket => {
      message(payload.kind === 'proxy' ? '正在检查代理 HTTPS 通道…' : '正在检查 API Key 与模型访问权限…');
      const data = await readResponse(await adminApi('/api/admin/openai-egress/test', { method: 'POST', body: JSON.stringify(payload) }));
      if (ticket !== epoch) return;
      message(data.message, data.status !== 'reachable');
      if (statusNode) statusNode.textContent = data.message;
      cache.clear(); paint();
    });
    if (statusNode?.textContent === '正在检查连接…') statusNode.textContent = '检查未完成，请在 OpenAI 代理中查看配置';
  }
  byId('openaiEgressSave')?.addEventListener('click', event => save(event.currentTarget, false));
  byId('openaiEgressReload')?.addEventListener('click', event => save(event.currentTarget, true));
  byId('openaiEgressRefresh')?.addEventListener('click', event => action(event.currentTarget, () => open()));
  byId('openaiProxyTest')?.addEventListener('click', event => test(event.currentTarget, { kind: 'proxy' }));
  byId('openaiModelTest')?.addEventListener('click', event => {
    const id = byId('openaiTestModel').value;
    if (!id) { message('请先在模型管理新增官方模型，并在密钥管理保存 API Key。', true); return; }
    test(event.currentTarget, { kind: 'model', model_id: id });
  });
  byId('prompt')?.addEventListener('focus', () => check());
  globalThis.MeimeiOpenAIEgress = { open, sync, paint, check, accountChanged, test };
})();
