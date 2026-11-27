const states = {
  connected: '已关联',
  pending: '对端待核',
  free: '空闲',
  unknown: '未核实',
};

const kinds = { copper: '电口', fiber: '光口', other: '其他' };
const normalize = (value) => String(value ?? '').normalize('NFKC').trim().toLowerCase();
const matchesId = (left, right) => String(left) === String(right);

function element(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? '' : value);
  }
  node.append(...children.flat(Infinity).filter((child) => child != null));
  return node;
}

function button(text, action, style = '', attrs = {}) {
  return element('button', { class: `button small ${style}`, type: 'button', onclick: action, ...attrs }, text);
}

function field(label, control) {
  return element('label', {}, label, control);
}

function input(name, value = '', attrs = {}) {
  return element('input', { name, value, ...attrs });
}

function select(name, options, value) {
  const control = element('select', { name },
    options.map(([key, label]) => element('option', { value: key }, label)));
  control.value = String(value);
  return control;
}

function stateBadge(port) {
  return element('span', { class: 'port-state', 'data-state': port.state }, states[port.state] ?? states.unknown);
}

function knownPeer(cable) {
  return cable?.peer ? [cable.peer.device_name, cable.peer.port_name].filter(Boolean).join(' · ') : '';
}

function peerText(cable) {
  if (cable?.restricted) return '对端超出可见范围';
  return knownPeer(cable) || cable?.peer_label || '';
}

function errorMessage(error) {
  return error?.message || '请求失败，请重试。';
}

function portLocation(peer) {
  const side = { front: '正面', rear: '背面' }[peer.face];
  const end = Number(peer.u_start) + Number(peer.u_height) - 1;
  const units = peer.u_start ? (end > peer.u_start ? `U${peer.u_start}–U${end}` : `U${peer.u_start}`) : '';
  return [peer.rack_name, side, units, peer.device_code].filter(Boolean).join(' · ');
}

function reveal(node, { focus = false, force = false } = {}) {
  if (!node?.isConnected) return;
  if (focus) node.focus({ preventScroll: true });
  const drawer = node.closest('.drawer');
  if (!drawer) {
    node.scrollIntoView({ block: force ? 'center' : 'nearest' });
    return;
  }
  const bounds = drawer.getBoundingClientRect();
  const target = node.getBoundingClientRect();
  const header = drawer.querySelector('.dialog-head')?.getBoundingClientRect().height ?? 0;
  const top = bounds.top + header + 12;
  if (force || target.top < top || target.bottom > bounds.bottom - 12) {
    drawer.scrollTop += target.top - top;
  }
}

function portSearch(port, terms) {
  const cable = port.cable;
  const peer = cable?.peer;
  const fields = [port.name, port.group, kinds[port.kind], cable?.label, cable?.peer_label,
    peer?.device_name, peer?.device_code, peer?.port_name, peer?.rack_name].map(normalize);
  return terms.every((term) => fields.some((value) => value.includes(term)));
}

function portTile(port, view, active, onSelect) {
  const description = [port.name, kinds[port.kind], states[port.state], port.cable?.label, peerText(port.cable)]
    .filter(Boolean).join(' · ');
  const position = port.position ? String(port.position).padStart(2, '0') : '';
  const label = view === 'grid' && position ? position : port.name;
  return button([
    element('span', { class: 'port-tile-symbol', 'aria-hidden': 'true' }),
    element('span', { class: 'port-tile-name' }, label),
    view === 'list' ? element('span', { class: 'port-tile-meta' },
      element('span', {}, port.cable?.label || ''),
      element('span', {}, peerText(port.cable))) : null,
    view === 'list' ? stateBadge(port) : null,
  ], onSelect, 'port-tile', {
    title: description, 'aria-label': description, 'aria-pressed': active ? 'true' : 'false',
    'data-port-id': port.id, 'data-kind': port.kind, 'data-state': port.state,
  });
}

function counts(ports) {
  const total = { connected: 0, pending: 0, free: 0, unknown: 0 };
  for (const port of ports) total[port.state in total ? port.state : 'unknown']++;
  return total;
}

export function renderDevicePortsSummary({ device, request, onOpen, ports }) {
  const summary = element('span', { class: 'port-summary-count' });
  const trigger = element('button', { type: 'button', class: 'port-quick-link', onclick: onOpen },
    element('span', {}, '端口和接线'), summary);
  const summarize = (items) => {
    if (!items.length) {
      summary.textContent = '未登记';
      return;
    }
    const total = counts(items);
    summary.textContent = [`${items.length} 口`, `${total.connected} 已关联`,
      total.pending ? `${total.pending} 待核` : ''].filter(Boolean).join(' · ');
  };
  if (ports) summarize(ports);
  else request(`devices/${device.id}/ports`).then((result) => summarize(result.ports ?? [])).catch(() => {});
  return trigger;
}

function editorLayout(title, submitLabel, onSubmit, onCancel, fields) {
  const error = element('p', { class: 'form-error', role: 'alert', hidden: true });
  const cancel = button('取消', onCancel);
  const submit = element('button', { type: 'submit', class: 'button small primary' }, submitLabel);
  const form = element('form', { class: 'port-editor', onsubmit: async (event) => {
    event.preventDefault();
    submit.disabled = cancel.disabled = true;
    error.hidden = true;
    try {
      await onSubmit(new FormData(event.currentTarget));
    } catch (failure) {
      error.textContent = errorMessage(failure);
      error.hidden = false;
    } finally {
      submit.disabled = cancel.disabled = false;
    }
  } }, element('h3', {}, title), ...fields, error, element('div', { class: 'port-actions' }, cancel, submit));
  return form;
}

function metadataEditor(port, onSave, onCancel) {
  const name = input('name', port?.name, { required: true, maxlength: 80, placeholder: '例如 GE1/0/1' });
  const group = input('group', port?.group, { maxlength: 80, placeholder: '例如 RJ45' });
  const position = input('position', port?.position || '', { type: 'number', min: 1, max: 4096, step: 1, placeholder: '可选' });
  const kind = select('kind', Object.entries(kinds), port?.kind ?? 'copper');
  const state = !port?.cable && select('state', [['unknown', '未核实'], ['free', '已确认空闲']], port?.state ?? 'unknown');
  return editorLayout(port ? '编辑端口' : '新增端口', '保存端口', (form) => onSave({
    name: form.get('name').trim(),
    kind: form.get('kind'),
    group: form.get('group').trim(),
    ...(form.get('position') ? { position: Number(form.get('position')) } : { position: null }),
    ...(state ? { state: form.get('state') } : {}),
  }), onCancel, [
    element('div', { class: 'port-fields' },
      field('端口名称', name), field('类型', kind), field('分组', group),
      field('面板顺序', position), state ? field('核实状态', state) : null),
  ]);
}

function cableEditor(port, devices, request, onSave, onCancel) {
  const cable = port.cable;
  const peer = cable?.peer;
  const label = input('label', cable?.label, { maxlength: 180, placeholder: '可选' });
  const peerLabel = input('peer_label', cable?.peer_label, { maxlength: 180, placeholder: '录入线缆标签上的对端信息' });
  const note = element('textarea', { name: 'note', maxlength: 500, rows: 2 }, cable?.note || '');
  const verifiedOn = input('verified_on', cable?.verified_on, { type: 'date' });
  const mode = select('mode', [['pending', '对端待核实'], ['linked', '关联台账中的对端']], peer ? 'linked' : 'pending');
  const peerFilter = input('peer-search', '', { type: 'search', placeholder: '名称 / 编号' });
  const targetDevice = select('peer-device', [], '');
  const targetPort = select('peer-port', [], '');
  const peerFields = element('div', { class: 'port-fields' },
    field('搜索对端设备', peerFilter), field('对端设备', targetDevice), field('对端端口', targetPort));
  const message = element('p', { class: 'small-text muted', role: 'status', hidden: true });
  const peerDevices = devices.filter((device) => !device.archived_at);
  let loadToken = 0;

  function setDeviceOptions(preferred = targetDevice.value) {
    const query = normalize(peerFilter.value);
    const matching = peerDevices.filter((device) => matchesId(device.id, preferred) ||
      [device.name, device.code].some((value) => normalize(value).includes(query)));
    const options = [['', matching.length ? '请选择设备' : '没有匹配的设备'], ...matching.map((device) => [
      device.id, [device.name, device.code].filter(Boolean).join(' · '),
    ])];
    targetDevice.replaceChildren(...options.map(([key, text]) => element('option', { value: key }, text)));
    targetDevice.value = preferred;
  }

  async function loadTargetPorts(preferred = '') {
    const token = ++loadToken;
    const deviceId = targetDevice.value;
    targetPort.disabled = true;
    targetPort.replaceChildren(element('option', { value: '' }, deviceId ? '读取端口中…' : '先选择设备'));
    message.hidden = true;
    if (!deviceId) return;
    try {
      const result = await request(`devices/${deviceId}/ports`);
      if (token !== loadToken) return;
      const available = (result.ports ?? []).filter((candidate) => !matchesId(candidate.id, port.id) &&
        (!candidate.cable || matchesId(cable?.id, candidate.cable.id)));
      const first = available.length ? '请选择端口' : '没有可用端口';
      targetPort.replaceChildren(element('option', { value: '' }, first), ...available.map((candidate) =>
        element('option', { value: candidate.id }, [candidate.name, candidate.group, kinds[candidate.kind]]
          .filter(Boolean).join(' · '))));
      targetPort.disabled = false;
      targetPort.value = preferred;
    } catch (failure) {
      if (token !== loadToken) return;
      targetPort.replaceChildren(element('option', { value: '' }, '读取失败'));
      message.textContent = errorMessage(failure);
      message.hidden = false;
    }
  }

  function updateMode() {
    const linked = mode.value === 'linked';
    peerFields.hidden = !linked;
    message.hidden = true;
    peerLabel.required = !linked;
    targetDevice.required = targetPort.required = linked;
    peerLabel.placeholder = linked ? '可选' : '例如 A08 交换机 GE1/0/8';
    if (linked && targetDevice.value) loadTargetPorts(peer?.port_id ?? '');
  }

  setDeviceOptions(peer?.device_id == null ? '' : String(peer.device_id));
  mode.addEventListener('change', updateMode);
  peerFilter.addEventListener('input', () => setDeviceOptions());
  targetDevice.addEventListener('change', () => loadTargetPorts());
  updateMode();

  return editorLayout(cable ? '编辑接线' : '登记接线', '保存接线', (form) => {
    if (mode.value === 'linked' && !targetPort.value) throw new Error('请选择可用的对端端口。');
    if (mode.value === 'pending' && !peerLabel.value.trim()) throw new Error('请填写对端标签。');
    return onSave({
      label: form.get('label').trim(),
      peer_label: form.get('peer_label').trim(),
      peer_port_id: mode.value === 'linked' ? Number(targetPort.value) : null,
      note: form.get('note').trim(),
      verified_on: form.get('verified_on') || '',
    });
  }, onCancel, [
    element('div', { class: 'port-fields' }, field('本端线缆标签', label), field('登记方式', mode)),
    peerFields, message, element('div', { class: 'port-fields' },
      field('对端标签', peerLabel), field('核实日期', verifiedOn)), field('接线备注', note),
  ]);
}

function parsePortRows(value, kind, group, ports) {
  const names = new Set(ports.map((port) => normalize(port.name)));
  const rows = [];
  for (const [index, line] of value.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    const [name, label = '', peerLabel = '', ...extra] = line.split('\t').map((value) => value.trim());
    if (!name || name.length > 80 || label.length > 180 || peerLabel.length > 180 || extra.length) {
      throw new Error(`第 ${index + 1} 行格式不正确。每行填写端口名称及可选的两侧标签，以制表符分隔。`);
    }
    if (label && !peerLabel) throw new Error(`第 ${index + 1} 行还需填写对端标签。`);
    if (names.has(normalize(name))) throw new Error(`第 ${index + 1} 行的端口 ${name} 已存在或重复。`);
    names.add(normalize(name));
    rows.push({ name, kind, group, state: 'unknown', ...(peerLabel ? { label, peer_label: peerLabel } : {}) });
  }
  if (!rows.length || rows.length > 128) throw new Error('一次可登记 1–128 个端口。');
  return rows;
}

function bulkEditor(ports, onSave, onCancel, portTemplates) {
  const raw = element('textarea', {
    name: 'rows', rows: 5, required: true,
    placeholder: 'GE1/0/01\t本端线标\tA02 对端线标\nGE1/0/02',
  });
  const kind = select('kind', Object.entries(kinds), 'copper');
  const group = input('group', '', { maxlength: 80, placeholder: '例如 RJ45' });
  const preview = element('div', { class: 'port-batch-preview', 'aria-live': 'polite' });
  let rows;
  let selectedTemplate = false;
  function resetPreview() {
    rows = undefined;
    preview.replaceChildren();
  }
  function returnToManualEntry() {
    selectedTemplate = false;
    resetPreview();
  }
  for (const control of [raw, kind, group]) control.addEventListener('input', returnToManualEntry);
  const fill = (size) => {
    raw.value = Array.from({ length: size }, (_, index) => `GE1/0/${String(index + 1).padStart(2, '0')}`).join('\n');
    returnToManualEntry();
    raw.focus({ preventScroll: true });
  };
  function prepare() {
    resetPreview();
    try {
      if (selectedTemplate) {
        const existing = new Set(ports.map((port) => normalize(port.name)));
        rows = portTemplates.filter((port) => !existing.has(normalize(port.name)));
        raw.value = rows.map((port) => port.name).join('\n');
        if (!rows.length) {
          rows = undefined;
          throw new Error('已登记此型号模板中的全部端口。');
        }
      } else {
        rows = parsePortRows(raw.value, kind.value, group.value.trim(), ports);
      }
      preview.append(element('p', { class: 'small-text' },
        `待新增 ${rows.length} 个端口，其中 ${rows.filter((row) => row.peer_label).length} 个对端待核。`),
      element('ul', { class: 'port-batch-rows' }, rows.map((row) => element('li', {},
        element('strong', { class: 'port-mono' }, row.name),
        [selectedTemplate && kinds[row.kind], selectedTemplate && row.group, row.label, row.peer_label].filter(Boolean).join(' · ')))));
    } catch (failure) {
      preview.append(element('p', { class: 'form-error' }, errorMessage(failure)));
    }
  }

  return editorLayout('批量登记端口', '确认登记', () => {
    if (!rows) throw new Error('请先预览并核对待登记的端口。');
    return onSave({ ports: rows });
  }, onCancel, [
    element('p', { class: 'muted small-text' }, '每行填一个端口名称。可从表格直接粘贴端口名、本端标签、对端标签三列。'),
    element('div', { class: 'port-actions' },
      button('填入 24 口模板', () => fill(24), 'quiet'), button('填入 48 口模板', () => fill(48), 'quiet'),
      portTemplates?.length ? button('预览型号端口', () => {
        selectedTemplate = true;
        prepare();
      }, 'quiet') : null),
    element('div', { class: 'port-fields' }, field('类型', kind), field('分组', group)),
    field('待登记端口', raw), button('预览', prepare), preview,
  ]);
}

export function renderDevicePorts({
  device, request, canWrite, devices = [], initialPortId, onLocate, onCopy, portTemplates,
}) {
  let ports = [];
  let selectedId = initialPortId;
  let view = 'grid';
  let editing = false;
  const path = `devices/${device.id}/ports`;
  const panel = element('section', { class: 'panel device-ports', 'data-device-ports': true, tabindex: -1 });
  const summary = element('p', { class: 'port-summary muted small-text', 'aria-live': 'polite' });
  const content = element('div', { class: 'port-content' });
  const editor = element('div', { class: 'port-editor-host' });
  const detail = element('div', { class: 'port-detail-host' });
  const status = element('p', { class: 'port-feedback small-text', role: 'status', hidden: true });
  const query = input('port-search', '', { type: 'search', 'aria-label': '搜索端口', placeholder: '搜索端口、线缆标签或对端' });
  const filter = select('port-state-filter', [['', '所有状态'], ...Object.entries(states)], '');
  filter.setAttribute('aria-label', '筛选端口状态');
  const roster = element('div', { class: 'port-roster', role: 'region', 'aria-label': '端口列表' });
  const gridView = button('面板', () => setView('grid'), 'quiet', { 'aria-pressed': 'true' });
  const listView = button('列表', () => setView('list'), 'quiet', { 'aria-pressed': 'false' });
  const tools = element('div', { class: 'port-toolbar' }, query, filter,
    element('div', { class: 'port-views', role: 'group', 'aria-label': '端口视图' }, gridView, listView));
  const add = button('新增端口', () => showForm(metadataEditor(null, create, hideForm)));
  const batch = button('批量登记', () => showForm(bulkEditor(ports, create, hideForm, portTemplates)), 'quiet');
  const management = canWrite ? element('div', { class: 'port-actions' }, add, batch) : null;

  function announce(message) {
    status.textContent = message;
    status.hidden = !message;
  }

  function showForm(form) {
    editing = true;
    editor.replaceChildren(form);
    announce('');
    const control = form.querySelector('input:not([type=hidden]), select, textarea, button');
    reveal(control, { focus: true });
  }

  function hideForm() {
    editing = false;
    editor.replaceChildren();
    detail.querySelector('button')?.focus({ preventScroll: true });
  }

  function updateRoster() {
    const terms = normalize(query.value).split(/\s+/).filter(Boolean);
    const visible = ports.filter((port) => (!filter.value || port.state === filter.value) && portSearch(port, terms));
    roster.dataset.view = view;
    const groups = new Map();
    for (const port of visible) {
      const group = port.group || kinds[port.kind] || kinds.other;
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(port);
    }
    roster.replaceChildren(...[...groups].map(([group, items]) => element('div', { class: 'port-group' },
      element('h3', { class: 'port-group-heading' }, group,
        element('span', { class: 'port-group-count' }, String(items.length))),
      element('div', { class: 'port-grid' }, items.map((port) =>
        portTile(port, view, matchesId(selectedId, port.id), () => selectPort(port)))))));
    if (!visible.length) roster.append(element('p', { class: 'port-empty muted small-text' }, '没有匹配的端口。'));
    const totals = counts(ports);
    summary.replaceChildren(element('span', {}, `${ports.length} 口`), ...Object.entries(states)
      .filter(([state]) => state !== 'unknown' || totals[state])
      .map(([state, label]) => element('span', { class: 'port-state', 'data-state': state }, `${totals[state]} ${label}`)),
    ...(visible.length !== ports.length ? [element('span', {}, `匹配 ${visible.length} 口`)] : []));
  }

  function selectPort(port) {
    if (!matchesId(selectedId, port.id)) {
      selectedId = port.id;
      if (editing) hideForm();
    }
    for (const tile of roster.querySelectorAll('[data-port-id]')) {
      tile.setAttribute('aria-pressed', matchesId(tile.dataset.portId, port.id) ? 'true' : 'false');
    }
    updateDetail();
    reveal(detail.firstElementChild);
  }

  function setView(next) {
    view = next;
    gridView.setAttribute('aria-pressed', view === 'grid' ? 'true' : 'false');
    listView.setAttribute('aria-pressed', view === 'list' ? 'true' : 'false');
    updateRoster();
  }

  function updateDetail() {
    const port = ports.find((item) => matchesId(item.id, selectedId));
    if (!port) {
      detail.replaceChildren();
      return;
    }
    const { cable } = port;
    const peer = cable?.peer;
    const facts = element('dl', { class: 'port-facts' });
    const fact = (title, value, hint) => {
      if (value) facts.append(element('div', {},
        element('dt', {}, title), element('dd', {}, value, hint ? element('small', {}, hint) : null)));
    };
    fact('本端标签', cable?.label);
    fact('对端', peerText(cable), peer ? [portLocation(peer), peer.archived_at ? '已归档' : ''].filter(Boolean).join(' · ') : '');
    fact('对端标签', peer && cable.peer_label);
    fact('核实日期', cable?.verified_on);
    fact('备注', cable?.note);

    const portURL = `ports/${port.id}`;
    const actions = [];
    if (peer && !peer.archived_at && onLocate) actions.push(button('定位对端', () => onLocate({
      deviceId: peer.device_id, portId: peer.port_id,
    }), 'primary'));
    if (!device.archived_at && onCopy) actions.push(button('复制定位链接', () => onCopy(port.id), 'quiet'));
    if (canWrite && !cable?.restricted) {
      actions.push(button(cable ? '编辑接线' : '登记接线',
        () => showForm(cableEditor(port, devices, request, (data) =>
          mutate(`${portURL}/cable`, 'PUT', data, '接线已保存。'), hideForm))));
      actions.push(button('端口资料', () => showForm(metadataEditor(port, (data) =>
        mutate(portURL, 'PATCH', data, '端口已保存。'), hideForm)), 'quiet'));
      actions.push(button(cable ? '解除接线' : '移除端口', () => showForm(editorLayout(
        cable ? '解除接线' : '移除端口', '确认', () => cable ?
          mutate(`${portURL}/cable`, 'DELETE', undefined, '两端的接线记录已解除。') :
          mutate(portURL, 'DELETE', undefined, '端口已移除。'), hideForm, [
          element('p', { class: 'small-text' }, cable ?
            '这会移除线缆两端的关联记录，保留两端的端口。' : `移除端口 ${port.name}？`),
        ])), 'quiet danger'));
    }

    detail.replaceChildren(element('section', { class: 'port-detail', tabindex: -1, 'data-selected-port-id': port.id },
      element('header', { class: 'port-detail-head' },
        element('div', {}, element('h3', { class: 'port-mono' }, port.name),
          element('p', { class: 'muted small-text' },
            [kinds[port.kind], port.group, port.demo ? '演示数据' : ''].filter(Boolean).join(' · '))),
        stateBadge(port)),
      facts.childElementCount ? facts : null,
      actions.length ? element('div', { class: 'port-actions' }, actions) : null));
  }

  function updateContent() {
    content.replaceChildren(...(ports.length ? [tools, roster, detail] : [
      element('p', { class: 'port-empty muted small-text' }, '此设备尚未登记端口。'),
    ]));
    if (ports.length) updateRoster();
    else summary.textContent = '';
    updateDetail();
  }

  async function mutate(url, method, data, message) {
    const payload = await request(url, { method, data });
    ports = payload.ports ?? [];
    if (method === 'POST' && data.name) selectedId = ports.find((port) => normalize(port.name) === normalize(data.name))?.id;
    if (!ports.some((port) => matchesId(port.id, selectedId))) selectedId = undefined;
    hideForm();
    updateContent();
    announce(message);
    reveal(detail.firstElementChild ?? status, { focus: Boolean(detail.firstElementChild) });
  }

  const create = (data) => mutate(path, 'POST', data, data.ports ? '端口已批量登记。' : '端口已登记。');

  async function load() {
    panel.setAttribute('aria-busy', 'true');
    content.replaceChildren(element('p', { class: 'port-empty muted small-text', role: 'status' }, '正在读取端口…'));
    if (management) management.hidden = true;
    try {
      const result = await request(path);
      ports = result.ports ?? [];
      updateContent();
      if (management) management.hidden = false;
      if (initialPortId) {
        if (detail.firstElementChild) requestAnimationFrame(() => reveal(detail.firstElementChild, { focus: true, force: true }));
        else announce('此设备没有该端口记录。');
      }
    } catch (failure) {
      content.replaceChildren(element('div', { class: 'port-actions' },
        element('p', { class: 'muted small-text' }, errorMessage(failure)), button('重新读取', load)));
    } finally {
      panel.removeAttribute('aria-busy');
    }
  }

  query.addEventListener('input', updateRoster);
  filter.addEventListener('change', updateRoster);
  panel.append(element('header', { class: 'port-heading' },
    element('div', {}, element('h2', {}, '端口和接线'), summary), management ?? ''),
  content, status, editor);
  load();
  return panel;
}
