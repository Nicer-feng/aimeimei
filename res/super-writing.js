/* 超能模式和客户终稿按对话保存，不继承到下一个任务。 */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  let pendingMode = false;
  let activeKey = '';
  let workspace = null;
  let editor = null;
  let controller = null;
  let loading = false;
  let changing = false;
  let uploadBusy = false;
  let uploadSequence = 0;
  let lastUserId = null;
  const eligible = () => state.authed && state.user?.id === 'default';
  const currentKey = () => `${state.user?.id || ''}:${state.conversationEpoch}:${state.currentConversation?.id || 'new'}`;
  const enabled = () => Boolean(state.currentConversation ? state.currentConversation.super_mode : pendingMode);

  function message(text, error = false) {
    const box = byId('finalDeliveryStatus');
    box.textContent = text || '';
    box.classList.toggle('is-error', error);
  }

  function close() {
    uploadSequence++;
    uploadBusy = false;
    if (byId('finalDeliveryDialog').open) byId('finalDeliveryDialog').close();
    setDialogOpenState();
    render();
  }

  function reset() {
    controller?.abort();
    controller = null;
    loading = false;
    changing = false;
    workspace = null;
    editor = null;
    activeKey = '';
    pendingMode = false;
    close();
    byId('finalDeliveryContent').value = '';
    byId('finalDeliveryLabel').value = '最终交付';
    byId('finalDeliveryVersions').replaceChildren(new Option('当前版本', ''));
    byId('finalDeliveryMessages').replaceChildren(new Option('选择一条消息', ''));
    byId('finalDeliveryFile').value = '';
    byId('finalDeliveryReferenceNote').textContent = '';
    setSource('');
    message('');
  }

  function render() {
    const allowed = eligible();
    const mode = byId('superModeToggle');
    const final = byId('openFinalDelivery');
    mode.hidden = !allowed;
    final.hidden = !allowed;
    byId('composerBox').classList.toggle('has-super-controls', allowed);
    mode.setAttribute('aria-pressed', String(allowed && enabled()));
    const label = enabled() ? '超能槑槑模式：开启' : '超能槑槑模式：关闭，当前使用原流程';
    mode.setAttribute('aria-label', label);
    mode.title = enabled() ? '本单已开启；点击恢复原流程。校验会增加等待，全部用量计入当前对话。' : '当前使用原流程；点击仅为本单开启超能槑槑模式。';
    byId('superModeState').textContent = enabled() ? '已开启' : '原流程';
    mode.disabled = !allowed || state.sending || state.conversationLoading || loading || changing;
    final.disabled = !allowed || !state.currentConversation || state.sending || state.conversationLoading || loading || changing;
    final.title = state.currentConversation ? '回传或更新本单最终交付' : '开始对话后可回传本单最终交付';
    const busy = state.sending || changing || uploadBusy;
    ['saveFinalDelivery', 'uploadFinalDelivery', 'finalDeliveryVersions', 'finalDeliveryMessages', 'finalDeliveryLabel', 'finalDeliveryContent'].forEach(id => { byId(id).disabled = busy; });
    byId('saveFinalDelivery').disabled = busy || !editor || (!byId('finalDeliveryContent').value.trim() && !editor.documentId);
  }

  async function fetchWorkspace(id, signal) {
    const response = await api(`/api/conversations/${encodeURIComponent(id)}/super-writing`, { signal });
    if (!response.ok) throw new Error(await readError(response, '本单超能模式暂时无法读取。'));
    return response.json();
  }

  function applyWorkspace(data, id) {
    workspace = data;
    if (state.currentConversation?.id === id) {
      state.currentConversation.super_mode = Boolean(data.enabled);
      const item = state.conversations.find(item => item.id === id);
      if (item) item.super_mode = Boolean(data.enabled);
    }
  }

  function sync() {
    const key = currentKey();
    if (!eligible()) {
      if (activeKey || workspace || editor || pendingMode) reset();
      render();
      return;
    }
    if (key === activeKey) { render(); return; }
    controller?.abort();
    controller = new AbortController();
    workspace = null;
    editor = null;
    loading = false;
    changing = false;
    activeKey = key;
    const id = state.currentConversation?.id;
    if (!id) { render(); return; }
    pendingMode = false;
    loading = true;
    render();
    fetchWorkspace(id, controller.signal).then(data => {
      if (currentKey() !== key || !eligible()) return;
      applyWorkspace(data, id);
    }).catch(error => {
      if (currentKey() === key && error?.name !== 'AbortError') {
        // 读取失败不改变服务器已保存的开关，也不阻断普通聊天。
        workspace = null;
      }
    }).finally(() => {
      if (currentKey() === key) { loading = false; render(); }
    });
  }

  async function toggle() {
    if (!eligible() || state.sending || changing || loading || state.conversationLoading) return;
    const next = !enabled();
    const id = state.currentConversation?.id;
    if (!id) {
      pendingMode = next;
      render();
      setStatus('chatStatus', next ? '本单将使用超能槑槑模式，校验会增加等待，全部用量计入本单。' : '本单恢复原流程。', 'ok');
      return;
    }
    const key = currentKey();
    changing = true;
    render();
    try {
      const latest = await fetchWorkspace(id, controller?.signal);
      if (currentKey() !== key || !eligible()) return;
      const response = await api(`/api/conversations/${encodeURIComponent(id)}/super-writing`, {
        method: 'PATCH', signal: controller?.signal,
        body: JSON.stringify({ revision: latest.revision, enabled: next })
      });
      if (!response.ok) throw new Error(await readError(response, '本单模式保存失败。'));
      const data = await response.json();
      if (currentKey() !== key || !eligible()) return;
      applyWorkspace(data, id);
      setStatus('chatStatus', next ? '本单已开启超能槑槑模式，全部新增用量计入当前对话。' : '本单已恢复原流程，已保存的交付稿保留。', 'ok');
    } catch (error) {
      if (currentKey() === key && error?.name !== 'AbortError') setStatus('chatStatus', friendlyError(error, '模式保存失败，当前开关未改变。'), 'err');
    } finally {
      if (currentKey() === key) { changing = false; render(); }
    }
  }

  function setSource(source, filename = '') {
    const badge = byId('finalDeliverySource');
    badge.textContent = source === 'customer' ? '客户确认稿' : source === 'inferred' ? '历史推定稿 · 待核对' : '尚未回传';
    badge.dataset.source = source || '';
    byId('finalDeliveryFileName').textContent = filename;
  }

  function renderVersions(data) {
    const select = byId('finalDeliveryVersions');
    select.replaceChildren(new Option('选择历史版本查看', ''));
    for (const version of data.versions || []) {
      const source = version.source === 'customer' ? '客户确认' : '历史推定';
      select.add(new Option(`${version.label || '最终交付'} · ${source} · ${formatMessageTime(version.updated_at || version.created_at)}`, String(version.id)));
    }
    select.value = data.delivery?.id ? String(data.delivery.id) : '';
    byId('finalDeliveryReferenceNote').textContent = '交付稿用于本单版本管理与复盘，暂不自动参考其他任务。';
  }

  function fillEditor(data) {
    const delivery = data.delivery;
    editor = { key: currentKey(), id: state.currentConversation.id, revision: data.revision, documentId: null, filename: delivery?.filename || '', dirty: false };
    byId('finalDeliveryContent').value = delivery?.content || '';
    byId('finalDeliveryLabel').value = delivery?.source === 'customer' ? (delivery.label || '最终交付') : '最终交付';
    setSource(delivery?.source, delivery?.filename || '');
    renderVersions(data);
    const select = byId('finalDeliveryMessages');
    select.replaceChildren(new Option('选择一条消息', ''));
    state.messages.forEach((item, index) => {
      if (item.content && !item.thinking && ['assistant', 'user'].includes(item.role)) {
        select.add(new Option(`${item.role === 'user' ? '我' : '槑槑'}：${item.content.replace(/\s+/g, ' ').slice(0, 55)}`, String(index)));
      }
    });
    message(delivery?.source === 'inferred' ? '这是根据历史交流提取的推定稿，尚不代表客户已接受；请核对后保存。' : delivery ? '可以直接修改并保存，旧版本会保留。' : '粘贴、上传或从本单聊天载入客户已接受的稿件。');
  }

  async function open() {
    if (!eligible() || !state.currentConversation || state.sending || changing) return;
    const key = currentKey(), id = state.currentConversation.id;
    loading = true;
    render();
    try {
      const data = await fetchWorkspace(id, controller?.signal);
      if (currentKey() !== key || !eligible()) return;
      applyWorkspace(data, id);
      if (!editor || editor.key !== key || !editor.dirty) fillEditor(data);
      else {
        editor.revision = data.revision;
        renderVersions(data);
        message('已保留尚未保存的内容；保存会创建新的客户确认版本。');
      }
      if (!byId('finalDeliveryDialog').open) byId('finalDeliveryDialog').showModal();
      setDialogOpenState();
      queueLucideRefresh();
    } catch (error) {
      if (currentKey() === key && error?.name !== 'AbortError') setStatus('chatStatus', friendlyError(error, '最终交付加载失败。'), 'err');
    } finally {
      if (currentKey() === key) { loading = false; render(); }
    }
  }

  async function save() {
    if (!editor || editor.key !== currentKey() || !eligible() || state.sending || changing || uploadBusy) return;
    const snapshot = editor, key = currentKey();
    const body = { revision: snapshot.revision, label: byId('finalDeliveryLabel').value.trim() || '最终交付', filename: snapshot.filename };
    if (snapshot.documentId) body.document_id = snapshot.documentId;
    else body.content = byId('finalDeliveryContent').value;
    if (!body.document_id && !body.content.trim()) return message('请先粘贴稿件或上传文件。', true);
    changing = true;
    render();
    message('正在保存最终交付…');
    try {
      const response = await api(`/api/conversations/${encodeURIComponent(snapshot.id)}/final-deliveries`, {
        method: 'POST', signal: controller?.signal, body: JSON.stringify(body)
      });
      if (!response.ok) {
        const detail = await readError(response, '最终交付保存失败。');
        if (response.status === 409) {
          const latest = await fetchWorkspace(snapshot.id, controller?.signal);
          if (key === currentKey() && editor === snapshot) {
            applyWorkspace(latest, snapshot.id);
            snapshot.revision = latest.revision;
            renderVersions(latest);
          }
          throw new Error('本单已在其他页面更新。你的内容已保留，请核对后再次保存。');
        }
        throw new Error(detail);
      }
      const data = await response.json();
      if (key !== currentKey() || editor !== snapshot || !eligible()) return;
      applyWorkspace(data, snapshot.id);
      fillEditor(data);
      message('客户确认稿已保存，原聊天和旧版本保留。');
      byId('finalDeliveryFile').value = '';
    } catch (error) {
      if (key === currentKey() && error?.name !== 'AbortError') message(friendlyError(error, '最终交付保存失败，编辑内容已保留。'), true);
    } finally {
      if (key === currentKey()) { changing = false; render(); }
    }
  }

  async function upload(file) {
    if (!file || !editor || editor.key !== currentKey() || uploadBusy || state.sending || changing) return;
    const snapshot = editor, key = currentKey(), sequence = ++uploadSequence;
    const current = () => currentKey() === key && editor === snapshot && uploadSequence === sequence && eligible() && byId('finalDeliveryDialog').open;
    const ensure = () => { if (!current()) throw new DOMException('当前任务已切换', 'AbortError'); };
    uploadBusy = true;
    render();
    message('正在读取文件…');
    try {
      const extension = '.' + file.name.split('.').pop().toLowerCase();
      if (!['.txt', '.md', '.markdown', '.doc', '.docx', '.pdf'].includes(extension)) throw new Error('请上传 TXT、Markdown、Word 或 PDF。');
      if (['.txt', '.md', '.markdown'].includes(extension)) {
        if (file.size > 2 * 1024 * 1024) throw new Error('文本文件请控制在 2MB 以内。');
        const text = await file.text();
        ensure();
        if (!text.trim() || text.length > 100000) throw new Error('交付稿须为 1 至 100000 字；请检查文件是否完整。');
        byId('finalDeliveryContent').value = text.replace(/^\uFEFF/, '');
        snapshot.documentId = null;
        snapshot.filename = file.name;
        snapshot.dirty = true;
        setSource('', file.name);
        message('文件已载入，核对正文后点击保存。');
        return;
      }
      const policyResponse = await api('/api/documents/upload-policy', { method: 'POST', signal: controller?.signal });
      if (!policyResponse.ok) throw new Error(await readError(policyResponse, '文件上传配置不可用。'));
      const { policy } = await policyResponse.json();
      ensure();
      if (!policy.allowed_extensions.includes(extension) || file.size > policy.max_size) throw new Error('文件格式或大小超出上传限制。');
      const ossKey = policy.key_prefix + Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '-' + safeDocumentFilename(file.name);
      const form = new FormData();
      form.append('key', ossKey); form.append('OSSAccessKeyId', policy.access_key_id); form.append('policy', policy.policy); form.append('Signature', policy.signature); form.append('success_action_status', '200'); form.append('Content-Type', file.type || 'application/octet-stream'); form.append('file', file);
      message('正在上传文件；Word、PDF 将进行文档解析…');
      await uploadFormWithProgress(policy.host, form, () => {});
      ensure();
      const created = await api('/api/documents', { method: 'POST', signal: controller?.signal, body: JSON.stringify({ filename: file.name, mime_type: file.type || '', file_size: file.size, oss_key: ossKey }) });
      if (!created.ok) throw new Error(await readError(created, '文件解析任务创建失败。'));
      let document = (await created.json()).document;
      ensure();
      for (let attempt = 0; document?.status !== 'completed'; attempt++) {
        if (!document?.id || document.status === 'failed') throw new Error(document?.error_message || '文件解析失败，请改为粘贴正文。');
        if (attempt >= 30) throw new Error('文件仍在解析，请稍后重试或直接粘贴正文。');
        message('文件正在解析，完成后可保存；文件不会加入普通聊天材料。');
        await new Promise(resolve => setTimeout(resolve, 2000));
        ensure();
        const refreshed = await api(`/api/documents/${encodeURIComponent(document.id)}/refresh`, { method: 'POST', signal: controller?.signal });
        if (!refreshed.ok) throw new Error(await readError(refreshed, '文件解析状态读取失败。'));
        document = (await refreshed.json()).document;
        ensure();
      }
      snapshot.documentId = document.id;
      snapshot.filename = file.name;
      snapshot.dirty = true;
      byId('finalDeliveryContent').value = '';
      setSource('', file.name);
      message('文件已解析，保存后载入完整交付稿。');
    } catch (error) {
      if (current() && error?.name !== 'AbortError') message(friendlyError(error, '文件读取失败，原编辑内容已保留。'), true);
    } finally {
      if (key === currentKey() && uploadSequence === sequence) { uploadBusy = false; render(); }
      byId('finalDeliveryFile').value = '';
    }
  }

  function renderCheck(wrap, item) {
    let box = wrap.querySelector('.super-writing-check');
    const check = item.super_check;
    if (!check || item.thinking) { box?.remove(); return; }
    if (!box) {
      box = document.createElement('details');
      box.className = 'super-writing-check';
      wrap.querySelector('.bubble-shell')?.append(box);
    }
    box.replaceChildren();
    const issues = [], seen = new Set();
    for (const [kind, values] of [['rule', check.deterministic_issues], ['model', check.issues]]) {
      for (const issue of Array.isArray(values) ? values : []) {
        const text = (typeof issue === 'string' ? issue : issue && typeof issue === 'object'
          ? [issue.quote, issue.reason, issue.evidence_status === 'not_in_material'
            ? [(issue.evidence || issue.source_quote) ? `相关材料：${issue.evidence || issue.source_quote}` : '', '模型未在本单材料中找到该主张的依据，需确认；这不等于事实虚假。'].filter(Boolean).join('；')
            : (issue.evidence || issue.source_quote) ? `依据：${issue.evidence || issue.source_quote}` : ''].filter(Boolean).join('；')
          : '').trim();
        if (text && !seen.has(text)) { issues.push({ kind, text }); seen.add(text); }
      }
    }
    const summary = document.createElement('summary');
    const singleReview = check.review_method === 'single_pass';
    const labels = { passed: '本轮有限检查已完成', reviewed: singleReview ? '本次复检已返回' : '本轮有限检查已完成', issues: '有待确认内容', skipped: '本轮未做深度检查', failed: '本轮未完成检查', unrecognized: '正文计数未完成' };
    let status = issues.length && ['passed', 'reviewed'].includes(check.status) ? 'issues' : check.status;
    if (check.body_status === 'unrecognized' && ['passed', 'reviewed'].includes(status)) status = 'unrecognized';
    summary.textContent = `超能槑槑 · ${check.repaired ? (issues.length ? '已作局部修复，仍有待确认内容' : '已作局部修复') : labels[status] || '查看检查记录'}`;
    box.append(summary);
    const note = document.createElement('p'); note.textContent = check.notice || '检查范围有限，请以客户要求和原始材料为准。'; box.append(note);
    if (check.body_status) {
      const count = document.createElement('p'); count.className = 'super-writing-count';
      const counts = Array.isArray(check.body_chars) ? check.body_chars.filter(value => Number.isInteger(value) && value >= 0) : [];
      const length = check.length_requirement || {};
      let target = '';
      if (length.mode === 'approx' && length.min_chars > 0 && length.max_chars > 0) {
        target = `本单参考约${length.min_chars}–${length.max_chars}字，不按固定上下限判定。`;
      } else if (['approx', 'target'].includes(length.mode) && length.target_chars > 0) {
        target = `本单目标${length.mode === 'approx' ? '约' : ''}${length.target_chars}字，仅作参考，不按固定上下限判定。`;
      } else if (length.mode === 'range') {
        target = length.min_chars && length.max_chars ? `本单要求${length.min_chars}–${length.max_chars}字。`
          : length.max_chars ? `本单要求最多${length.max_chars}字。` : length.min_chars ? `本单要求至少${length.min_chars}字。` : '';
      }
      count.textContent = check.body_status === 'unrecognized'
        ? (check.count_notice || '正文边界不明确，本轮未检查正文字数。')
        : `${check.body_scope === 'dialogue' ? '分镜台词' : '正文'}：${counts.map((value, index) => `第${index + 1}${check.body_scope === 'dialogue' ? '表' : '篇'} ${value} 字`).join('；')}。${target}${check.count_notice || ''}`;
      box.append(count);
      const sections = Array.isArray(check.sections) ? check.sections : [];
      const names = { cover: '封面/标题', publication: '发布文案', body: '正文', dialogue: '分镜台词', captions: '花字/字幕', production: '制作说明' };
      const identified = Object.entries(names).map(([kind, name]) => {
        const size = sections.filter(section => section?.kind === kind).length;
        return size ? `${name} ${size} 项` : '';
      }).filter(Boolean);
      if (identified.length) {
        const parts = document.createElement('p'); parts.className = 'super-writing-sections';
        parts.textContent = `已识别分区：${identified.join(' · ')}。`;
        box.append(parts);
      }
      const countNote = document.createElement('p'); countNote.textContent = check.count_note || '仅计正文或分镜台词，不含封面/标题、发布文案和已识别花字；不计空白，含标点。'; box.append(countNote);
    }
    const scope = document.createElement('p'); scope.className = 'super-writing-scope';
    scope.textContent = '规则检查针对明确字数范围和本单逐字词项；模型意见仍待核对。自然度、观点和广告感不作代码判定，检查完成不等于客户验收。';
    box.append(scope);
    if (singleReview) {
      const method = document.createElement('p'); method.className = 'super-writing-single';
      method.textContent = '本次采用一次 Flash 复检，原稿保留。检查完成仅表示返回格式和材料范围满足本次协议，不代表逐句覆盖或事实全部正确。已返回的模型用量计入当前对话。';
      box.append(method);
    }
    const coverage = check.coverage;
    if (!singleReview && coverage && Number.isInteger(coverage.covered_units) && Number.isInteger(coverage.total_units)) {
      const progress = document.createElement('p'); progress.className = 'super-writing-coverage';
      progress.textContent = `稿件单元覆盖记录：${coverage.covered_units}/${coverage.total_units}。覆盖只表示模型处理过该位置，不代表判断正确。`;
      box.append(progress);
    }
    if (!singleReview && check.secondary_review?.attempted) {
      const second = document.createElement('p'); second.className = 'super-writing-secondary';
      second.textContent = (check.secondary_review.status === 'completed'
        ? '二次事实复核已结束，模型判断仍待核对。'
        : '二次事实复核未完整完成，未确认的首轮疑点不会作为复核结果展示。')
        + '两阶段已返回的模型用量均计入当前对话，未返回的用量会标记未知。';
      box.append(second);
    }
    if (issues.length) {
      const list = document.createElement('ul');
      issues.forEach(issue => {
        const line = document.createElement('li');
        line.textContent = `${issue.kind === 'rule' ? '规则检查' : '模型待核对'}：${issue.text}`;
        list.append(line);
      });
      box.append(list);
    }
    const usage = document.createElement('p');
    usage.textContent = check.usage_unknown
      ? '部分调用未返回用量，已记录已知用量，实际账单可能有差异。'
      : '本轮新增模型用量已计入当前对话统计。';
    box.append(usage);
  }

  byId('superModeToggle').addEventListener('click', toggle);
  byId('openFinalDelivery').addEventListener('click', open);
  byId('closeFinalDelivery').addEventListener('click', close);
  byId('finalDeliveryDialog').addEventListener('cancel', close);
  byId('finalDeliveryDialog').addEventListener('close', () => { uploadSequence++; uploadBusy = false; setDialogOpenState(); render(); });
  byId('saveFinalDelivery').addEventListener('click', save);
  byId('uploadFinalDelivery').addEventListener('click', () => byId('finalDeliveryFile').click());
  byId('finalDeliveryFile').addEventListener('change', event => upload(event.target.files?.[0]));
  for (const id of ['finalDeliveryContent', 'finalDeliveryLabel']) byId(id).addEventListener('input', () => {
    if (editor) { editor.dirty = true; if (id === 'finalDeliveryContent') editor.documentId = null; }
    render();
  });
  byId('finalDeliveryMessages').addEventListener('change', event => {
    if (event.target.value === '' || !editor) return;
    const item = state.messages[Number(event.target.value)];
    if (!item?.content) return;
    byId('finalDeliveryContent').value = item.content;
    editor.documentId = null; editor.filename = ''; editor.dirty = true;
    setSource(''); message('消息已载入，请核对客户接受的版本后保存。'); render();
  });
  byId('finalDeliveryVersions').addEventListener('change', event => {
    const version = workspace?.versions?.find(version => String(version.id) === event.target.value);
    if (!version || typeof version.content !== 'string' || !editor) return;
    byId('finalDeliveryContent').value = version.content;
    byId('finalDeliveryLabel').value = version.source === 'customer' ? (version.label || '最终交付') : '最终交付';
    editor.documentId = null; editor.filename = version.filename || ''; editor.dirty = true;
    setSource(version.source, version.filename || '');
    message('历史版本已载入；保存后才更新当前最终交付。'); render();
  });

  globalThis.MeimeiSuper = {
    sync, renderCheck,
    isBusy: () => changing,
    newConversationMode: () => eligible() && !state.currentConversation && pendingMode,
    transition: reset,
    accountChanged() {
      if (lastUserId !== state.user?.id) { reset(); lastUserId = state.user?.id || null; }
      sync();
    }
  };
  sync();
})();
