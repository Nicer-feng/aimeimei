import { deviceKind, operatingStatus, operatingStatusLabel, OPERATING_STATUS_LABELS, renderRack, units } from './rack.js?v=operating-status';
import { renderRoomOverview } from './room-overview.js';

const byId = (id) => document.getElementById(id);
const page = byId('page');
const workspace = byId('workspace');
const login = byId('login');
const loginForm = byId('login-form');
const loginSubmit = loginForm.querySelector('button[type=submit]');
const auth = { mode: null, captchaId: '', refreshing: false, submitting: false };
const editor = byId('editor');
const drawer = byId('drawer');
const deviceQuick = element('dialog', {
  id: 'device-quick', class: 'device-quick', 'aria-labelledby': 'device-quick-title',
});
const deviceQuickGuide = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
const deviceQuickPath = document.createElementNS(deviceQuickGuide.namespaceURI, 'path');
const deviceQuickTarget = document.createElementNS(deviceQuickGuide.namespaceURI, 'circle');
deviceQuickGuide.setAttribute('class', 'device-quick-guide');
deviceQuickGuide.setAttribute('aria-hidden', 'true');
deviceQuickGuide.setAttribute('hidden', '');
deviceQuickPath.setAttribute('class', 'device-quick-guide-path');
deviceQuickTarget.setAttribute('class', 'device-quick-guide-target');
deviceQuickTarget.setAttribute('r', '4');
deviceQuickGuide.append(deviceQuickPath, deviceQuickTarget);
const preview = byId('pdf-preview');
const deviceClickModeKey = 'sroom-device-click-mode';
const deviceClickModes = [['quick', '就地快览'], ['detail', '直接开详情']];
const blankFilters = () => ({ unit: '', site: '', room: '', rack: '' });
const state = {
  user: null,
  catalog: null,
  deviceFilters: blankFilters(),
  rackFilters: blankFilters(),
  roomFilters: blankFilters(),
  deviceSearch: '',
  rackView: null,
  roomOverview: null,
  roomViews: new Map(),
  rackOverviewRoomId: null,
  deviceClickMode: savedDeviceClickMode(),
};
let deviceSelection = null;
let deviceOpenedByScenePointer = false;
let devicePageScroll = null;
const deviceSheetMedia = window.matchMedia('(max-width: 670px)');
drawer.before(deviceQuickGuide, deviceQuick);
const titles = { rooms: '机房总览', rack: '机柜视图', devices: '设备台账', systems: '业务系统', projects: '项目档案' };
const collectionRoutes = { device: 'devices', system: 'systems', project: 'projects' };
const mountDepthLabels = { unknown: '深度待核', half: '半深', full: '全深' };
const documentTypes = new Map([
  ['pdf', 'PDF'],
  ['png', '图片'], ['jpg', '图片'], ['jpeg', '图片'], ['gif', '图片'], ['webp', '图片'],
  ['doc', 'Word'], ['docx', 'Word'], ['xls', 'Excel'], ['xlsx', 'Excel'],
]);

function element(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === false || value == null) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child != null && child !== false) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function button(text, action, extra = '', attributes = {}) {
  return element('button', { type: 'button', class: `button ${extra}`, onclick: action, ...attributes }, text);
}

function internalLink(route, id, text, attrs = {}) {
  const href = id == null ? `#${route}` : `#${route}/${id}`;
  return element('a', { href, ...attrs }, text);
}

function userCanWrite() {
  return state.user.role === 'admin';
}

function lookup(list, id) {
  return state.catalog[list].find((item) => String(item.id) === String(id));
}

function apiUrl(path) {
  return new URL(`./api/${path}`, document.baseURI).href;
}

async function request(path, { method = 'GET', data, ai = false } = {}) {
  const result = await fetch(ai ? `/api/${path}` : apiUrl(path), {
    method,
    credentials: 'same-origin',
    headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (result.status === 204) return null;
  const payload = await result.json().catch(() => ({}));
  if (!result.ok) {
    const error = new Error(payload.error || `请求失败（${result.status}）`);
    error.status = result.status;
    if (!ai && state.user) {
      if (result.status === 401) showLogin('登录已过期，请重新登录。');
      if (result.status === 403 && payload.code === 'sroom_identity') showLogin(error.message);
    }
    throw error;
  }
  return payload;
}

function showError(target, message = '') {
  target.textContent = message;
  target.hidden = !message;
}

function closeDialogs() {
  for (const dialog of [preview, editor]) {
    if (dialog.open) dialog.close();
  }
  closeDevicePresentation();
}

function showLogin(message = '') {
  const wasAuthenticated = state.user !== null;
  closeDialogs();
  state.rackView?.();
  state.rackView = null;
  disposeRoomOverview();
  state.roomViews.clear();
  state.rackOverviewRoomId = null;
  state.user = null;
  state.catalog = null;
  state.deviceFilters = blankFilters();
  state.rackFilters = blankFilters();
  state.roomFilters = blankFilters();
  state.deviceSearch = '';
  page.replaceChildren();
  workspace.hidden = true;
  login.hidden = false;
  if (wasAuthenticated) loginForm.elements.password.value = '';
  showError(byId('login-error'), message);
  byId('drawer-content').replaceChildren();
  byId('editor-content').replaceChildren();
  if (auth.mode === 'ai' && !auth.captchaId && !auth.submitting) void refreshCaptcha();
}

async function openWorkspace(user) {
  state.catalog = await request('catalog');
  state.user = user;
  login.hidden = true;
  workspace.hidden = false;
  byId('scope').textContent = user.role === 'admin'
    ? `${user.username} · ${user.scope_name || '全辖区'} · 管理员`
    : `${user.username} · ${user.scope_name || '辖区'} · 只读`;
  renderPage();
}

let toastTimer;
function notify(message) {
  const toast = byId('status-message');
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 4200);
}

function empty(message) {
  return element('div', { class: 'empty' }, message);
}

function pageHeading(title, meta, actions = []) {
  return element('div', { class: 'page-head' },
    element('div', {}, element('h1', {}, title), meta && element('div', { class: 'title-meta' }, meta)),
    actions.length && element('div', { class: 'head-actions' }, actions) || null,
  );
}

function panel(title, content, actions = []) {
  return element('section', { class: 'panel' },
    element('div', { class: 'panel-heading' }, element('h2', {}, title), actions),
    content,
  );
}

function factList(pairs) {
  return element('dl', { class: 'facts' },
    pairs.map(([caption, value, wide]) =>
      element('div', { class: wide ? 'wide' : '' },
        element('dt', {}, caption), element('dd', {}, value === '' || value == null ? '—' : value))));
}

function table(headers, rows, message) {
  if (!rows.length) return empty(message);
  return element('div', { class: 'table-scroll', tabindex: 0, 'aria-label': headers.join('、') },
    element('table', { class: 'table' },
      element('thead', {}, element('tr', {}, headers.map((header) => element('th', { scope: 'col' }, header)))),
      element('tbody', {}, rows.map((row) => element('tr', {}, row.map((cell) => element('td', {}, cell))))),
    ),
  );
}

function roomContext(roomId) {
  const room = lookup('rooms', roomId);
  const site = room && lookup('sites', room.site_id);
  const unit = site && lookup('units', site.unit_id);
  return { room, site, unit };
}

function joinedPath(...parts) {
  return parts.filter(Boolean).join(' / ');
}

function faceLabel(face) {
  return face === 'rear' ? '背面' : '正面';
}

function mountDepth(device) {
  return Object.hasOwn(mountDepthLabels, device.mount_depth) ? device.mount_depth : 'unknown';
}

function rackSpan(device) {
  if (device.u_height === 1) return `U${device.u_start}`;
  return `U${device.u_start}–U${device.u_start + device.u_height - 1}`;
}

function deviceLocation(device, linkRack = false) {
  const { room, site } = roomContext(device.room_id);
  const rack = lookup('racks', device.rack_id);
  const where = joinedPath(site?.name, room?.name);
  if (!rack) return joinedPath(where, device.workstation || '非上架');
  const slot = `${rack.name} · ${faceLabel(device.face)} · ${rackSpan(device)}`;
  if (!linkRack) return joinedPath(where, slot);
  return element('span', {}, where && `${where} / `, internalLink('rack', rack.id, slot));
}

function labelInput(label, input, extra = '') {
  return element('label', { class: extra }, label, input);
}

function selectInput(name, options, selected = '', blank = null, attributes = {}) {
  const select = element('select', { name, ...attributes });
  if (blank != null) select.append(element('option', { value: '' }, blank));
  for (const [value, label] of options) select.append(element('option', { value }, label));
  if (selected !== '' || blank != null) select.value = selected ?? '';
  return select;
}

function isWithinUnit(unitId, ancestorId) {
  let current = lookup('units', unitId);
  const seen = new Set();
  while (current && !seen.has(current.id)) {
    if (String(current.id) === ancestorId) return true;
    seen.add(current.id);
    current = lookup('units', current.parent_id);
  }
  return false;
}

function filteredLocations(filters) {
  const { units } = state.catalog;
  const sites = state.catalog.sites.filter((site) => !filters.unit || isWithinUnit(site.unit_id, filters.unit));
  const rooms = state.catalog.rooms.filter((room) =>
    sites.some((site) => site.id === room.site_id && (!filters.site || String(site.id) === filters.site)));
  const racks = state.catalog.racks.filter((rack) =>
    rooms.some((room) => room.id === rack.room_id && (!filters.room || String(room.id) === filters.room)));
  return { units, sites, rooms, racks };
}

function filterControls(filters, options = {}) {
  const locations = filteredLocations(filters);
  const group = element('div', { class: 'filters' });
  if (options.search) {
    const input = element('input', {
      id: 'device-search', type: 'search', value: state.deviceSearch,
      placeholder: '设备编号、名称或系统名',
      oninput: (event) => {
        state.deviceSearch = event.currentTarget.value;
        options.search();
      },
    });
    group.append(labelInput('搜索设备', input, 'search-field'));
  }
  const choices = [
    ['unit', 'units', '单位', ['site', 'room', 'rack']],
    ['site', 'sites', '站点', ['room', 'rack']],
    ['room', 'rooms', '机房／房间', ['rack']],
  ];
  if (!options.overview) choices.push(['rack', 'racks', '机柜', []]);
  const idPrefix = options.overview ? 'room' : options.onlyRack ? 'rack' : 'device';
  for (const [field, source, caption, later] of choices) {
    const chosenLocation = (field === 'rack' && options.onlyRack) || (field === 'room' && options.overview);
    const blank = chosenLocation ? `选择${caption}` : `全部${caption}`;
    const selection = selectInput(field, locations[source].map((item) => [item.id, item.name]), filters[field], blank, {
      id: field === 'rack' && options.onlyRack ? 'rack-select' : `${idPrefix}-filter-${field}`,
      onchange: (event) => {
        const control = event.currentTarget;
        const restoreFocus = document.activeElement === control;
        filters[field] = control.value;
        for (const child of later) filters[child] = '';
        options.change(field);
        if (restoreFocus) byId(control.id)?.focus({ preventScroll: true });
      },
    });
    if (options.overview && field === 'room' && locations.rooms.length) selection.options[0].disabled = true;
    group.append(labelInput(caption, selection));
  }
  return group;
}

function selectOverviewRoom(filters) {
  const { rooms } = filteredLocations(filters);
  return rooms.find((room) => String(room.id) === filters.room) || rooms[0];
}

function disposeRoomOverview(remember = false) {
  const overview = state.roomOverview;
  if (!overview) return;
  if (remember) {
    state.roomViews.set(overview.roomId, {
      view: overview.controller.snapshot?.(),
      filters: overview.filters,
      scroll: overview.leavingScroll ?? window.scrollY,
    });
  }
  overview.controller();
  state.roomOverview = null;
}

function renderRoomPage(requestedId, filterChanged) {
  const filters = state.roomFilters;
  let roomId = requestedId;
  if (!roomId && !filterChanged && !filters.unit && !filters.site && !filters.room) {
    const populatedLayouts = (state.catalog.room_layouts ?? []).filter((layout) => layout.positions.length);
    const preferredLayout = populatedLayouts.find((layout) => !layout.illustrative) ?? populatedLayouts[0];
    roomId = preferredLayout?.room_id;
  }
  const room = roomId ? lookup('rooms', roomId) : selectOverviewRoom(filters);
  if (room && roomId && !filterChanged && filters.room !== String(room.id)) {
    const previous = state.roomViews.get(room.id);
    const { site, unit } = roomContext(room.id);
    Object.assign(filters, previous?.filters ?? { unit: String(unit?.id ?? ''), site: String(site?.id ?? '') });
  }
  filters.room = room ? String(room.id) : '';
  const filterPanel = element('section', { class: 'panel' }, filterControls(filters, {
    overview: true,
    change: () => {
      const selected = selectOverviewRoom(filters);
      history.replaceState(null, '', selected ? `#rooms/${selected.id}` : '#rooms');
      renderPage({ roomFilterChanged: true });
    },
  }));
  page.append(pageHeading(titles.rooms, null, room ? [deviceClickModeControl()] : []), filterPanel);
  if (!room) {
    page.append(empty('当前范围内没有可查看的机房。'));
    window.scrollTo(0, 0);
    return;
  }
  const { site, unit } = roomContext(room.id);
  filterPanel.append(element('div', { class: 'rack-context' }, joinedPath(unit?.name, site?.name, room.name)));
  const racks = state.catalog.racks.filter((rack) => rack.room_id === room.id);
  const devices = state.catalog.devices.filter((device) => device.room_id === room.id);
  const layout = (state.catalog.room_layouts ?? []).find((item) => item.room_id === room.id);
  const previous = state.roomViews.get(room.id);
  const host = element('section', { id: 'room-overview', 'aria-label': `${room.name}机柜总览` });
  page.append(host);
  const controller = renderRoomOverview(host, {
    room, layout, racks, devices, systems: state.catalog.systems, deviceKind, units, view: previous?.view,
    onDevice: openDevicePresentation,
    onSceneInteraction: dismissDeviceQuick,
    onRack: (rack) => {
      if (state.roomOverview) state.roomOverview.leavingScroll = window.scrollY;
      location.hash = `rack/${rack.id}`;
    },
    onEdit: userCanWrite() ? () => openRoomLayoutEditor(room, layout, racks) : undefined,
  });
  const overview = { roomId: room.id, filters: { ...filters }, controller };
  state.roomOverview = overview;
  const scroll = filterChanged ? 0 : (previous?.scroll ?? 0);
  return Promise.resolve(controller.ready).then(() => {
    if (state.roomOverview === overview) window.scrollTo(0, scroll);
  });
}

function renderRackPage(requestedId, view) {
  const filters = state.rackFilters;
  const requested = lookup('racks', requestedId);
  if (requested) {
    const { room, site, unit } = roomContext(requested.room_id);
    Object.assign(filters, { unit: String(unit.id), site: String(site.id), room: String(room.id), rack: String(requested.id) });
  }
  const available = filteredLocations(filters).racks;
  const rack = available.find((item) => String(item.id) === filters.rack) || available[0];
  filters.rack = rack ? String(rack.id) : '';
  const devices = rack ? state.catalog.devices.filter((device) => device.rack_id === rack.id) : [];
  const actions = rack ? [deviceClickModeControl()] : [];
  if (userCanWrite()) actions.push(button('新增设备', () => openDeviceEditor(null, rack), 'primary'));
  const overviewRoomId = state.rackOverviewRoomId ?? rack?.room_id;
  byId('breadcrumb').replaceChildren(
    internalLink('rooms', overviewRoomId, titles.rooms),
    ' / ', element('span', { 'aria-current': 'page' }, titles.rack),
  );
  page.append(internalLink('rooms', overviewRoomId, '返回机房总览', { class: 'back-link' }));
  page.append(pageHeading(titles.rack, null, actions));
  const filterPanel = element('section', { class: 'panel' }, filterControls(filters, {
    onlyRack: true,
    change: () => {
      if (location.hash !== '#rack') history.replaceState(null, '', '#rack');
      renderPage();
    },
  }));
  page.append(filterPanel);
  if (!rack) {
    page.append(empty('所选位置没有机柜。'));
    return;
  }
  const { room, site, unit } = roomContext(rack.room_id);
  filterPanel.append(element('div', { class: 'rack-context' },
    element('strong', {}, `${rack.name} · ${rack.height}U`),
    element('span', {}, joinedPath(unit?.name, site?.name, room?.name)),
  ));
  const rackHost = element('section', { id: 'rack-viewport', 'aria-label': `${rack.name} 机柜立面` });
  page.append(rackHost);
  state.rackView = renderRack(rackHost, {
    rack, devices, onDevice: openDevicePresentation, onSceneInteraction: dismissDeviceQuick,
    onEmpty: userCanWrite() ? (slot) => openDeviceEditor(null, rack, slot) : undefined,
    view: view?.rackId === rack.id ? view : undefined,
  });
}

function systemMatchIds(query) {
  if (!query) return new Set();
  const systems = state.catalog.systems.filter((system) => system.name.toLocaleLowerCase().includes(query));
  return new Set(systems.flatMap((system) => system.deployments.map((deployment) => deployment.device_id)));
}

function renderDevicesPage() {
  page.append(pageHeading(titles.devices, null,
    userCanWrite() ? [button('新增设备', () => openDeviceEditor(), 'primary')] : []));
  const filters = state.deviceFilters;
  const results = element('section', { class: 'panel', id: 'device-results', 'aria-labelledby': 'device-results-title' });
  function refreshResults() {
    const query = state.deviceSearch.trim().toLocaleLowerCase();
    const locations = filteredLocations(filters);
    const matchedSystems = systemMatchIds(query);
    const allowedRooms = new Set(locations.rooms.map((room) => String(room.id)));
    const matches = state.catalog.devices.filter((device) =>
      allowedRooms.has(String(device.room_id))
      && (!filters.room || String(device.room_id) === filters.room)
      && (!filters.rack || String(device.rack_id) === filters.rack)
      && (!query || device.code.toLocaleLowerCase().includes(query)
        || device.name.toLocaleLowerCase().includes(query) || matchedSystems.has(device.id)));
    results.replaceChildren(
      element('div', { class: 'results-head' },
        element('h2', { id: 'device-results-title' }, '设备列表'),
        element('span', { class: 'muted small-text', 'aria-live': 'polite' }, `${matches.length} 台设备`)),
      table(['设备', '类型', '位置', '运行状态', '维护人', '最近核实'],
        matches.map((device) => [
          element('div', {}, internalLink('device', device.id, device.name),
            element('div', { class: 'muted small-text code' }, device.code)),
          element('span', { class: 'tag' }, device.type),
          deviceLocation(device, true),
          operatingStatusLabel(device),
          device.maintainer || '责任人未确认',
          device.verified_on || '待核实',
        ]),
        '没有找到符合条件的设备。'),
    );
  }
  page.append(element('section', { class: 'panel' },
    filterControls(filters, { search: refreshResults, change: renderPage })), results);
  refreshResults();
}

function renderSystemsPage() {
  const { systems } = state.catalog;
  page.append(
    pageHeading(titles.systems, `${systems.length} 套系统`,
      userCanWrite() ? [button('新增系统', () => openSystemEditor(), 'primary')] : []),
    panel('系统列表', table(['系统名称', '用途说明', '部署设备', '服务入口'],
      systems.map((system) => [
        internalLink('system', system.id, system.name),
        system.description || '—',
        `${new Set(system.deployments.map((deployment) => deployment.device_id)).size} 台`,
        `${system.deployments.reduce((total, deployment) => total + deployment.entries.length, 0)} 个`,
      ]), '当前范围内没有系统。')),
  );
}

function renderProjectsPage() {
  const { projects, documents } = state.catalog;
  page.append(
    pageHeading(titles.projects, `${projects.length} 个项目`,
      userCanWrite() ? [button('新增项目', () => openProjectEditor(), 'primary')] : []),
    panel('项目列表', table(['项目', '归属站点', '关联设备', '项目档案'],
      projects.map((project) => [
        element('div', {}, internalLink('project', project.id, project.name),
          element('div', { class: 'muted small-text code' }, project.code)),
        lookup('sites', project.site_id)?.name || '—',
        `${project.device_ids.length} 台`,
        `${documents.filter((document) => document.project_id === project.id).length} 份`,
      ]), '当前范围内没有项目。')),
  );
}

function safeExternalURL(address) {
  if (!address) return null;
  try {
    const url = new URL(address);
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href;
  } catch {
    return null;
  }
  return null;
}

function serviceEntries(entries) {
  if (!entries.length) return element('p', { class: 'muted small-text' }, '暂无服务入口。');
  return element('div', { class: 'service-list' }, entries.map((entry) => {
    const address = entry.port ? `${entry.host} · 端口 ${entry.port}` : entry.host;
    const link = safeExternalURL(entry.url);
    return element('div', { class: 'service-item' },
      element('div', {}, element('span', { class: 'tag' }, entry.protocol), entry.purpose || null),
      element('div', { class: 'code muted' }, address),
      link && element('a', { href: link, target: '_blank', rel: 'noopener noreferrer', class: 'small-text' }, entry.url),
    );
  }));
}

function fileAddress(record, download = false) {
  return apiUrl(`documents/${record.id}/file${download ? '?download=1' : ''}`);
}

function documentType(filename) {
  const extension = /\.([a-z\d]+)$/i.exec(filename ?? '')?.[1].toLowerCase();
  return documentTypes.get(extension);
}

let disposePdfViewer;
function clearPdfViewer() {
  disposePdfViewer?.();
  disposePdfViewer = undefined;
}

async function loadReferencePreview(host, url, startPage) {
  try {
    const { mountPdfPreview } = await import('./pdf-preview.js');
    if (preview.open && host.isConnected) disposePdfViewer = mountPdfPreview(host, { url, startPage });
  } catch {
    if (preview.open && host.isConnected) {
      host.replaceChildren(element('p', { class: 'preview-message', role: 'alert' },
        'PDF 预览加载失败。可在新标签页打开原件。'));
    }
  }
}

function imagePreview(source, title) {
  const body = element('div', { class: 'document-image-preview' });
  const image = element('img', {
    src: source, alt: title, decoding: 'async',
    onerror: () => body.replaceChildren(element('p', { class: 'preview-message', role: 'alert' },
      '图片预览加载失败。可下载原件查看。')),
  });
  body.append(image);
  return body;
}

function openDocumentPreview(record, kind) {
  clearPdfViewer();
  const source = fileAddress(record);
  const startPage = kind === 'PDF' ? record.page : null;
  const originalUrl = startPage ? `${source}#page=${startPage}` : source;
  let body;
  if (kind === '图片') {
    body = imagePreview(source, record.title);
  } else if (startPage) {
    body = element('div', { class: 'document-reference-preview' },
      element('p', { class: 'preview-message', role: 'status' }, '正在加载 PDF 预览…'));
  } else {
    body = element('iframe', { src: source, title: `${record.title} PDF 预览`, class: 'pdf-frame', referrerpolicy: 'same-origin' });
  }
  byId('pdf-content').replaceChildren(
    dialogHeader('pdf-title', record.title, startPage ? `参考页码 · 第 ${startPage} 页` : record.category, preview),
    body,
    element('div', { class: 'pdf-fallback row-actions' },
      element('a', { href: originalUrl, target: '_blank', rel: 'noopener', class: 'button small' }, '在新标签页打开'),
      element('a', { href: fileAddress(record, true), class: 'button small' }, '下载原件')),
  );
  if (!preview.open) preview.showModal();
  if (startPage) void loadReferencePreview(body, source, startPage);
}

function documentList(documents, message = '暂无档案。') {
  if (!documents.length) return empty(message);
  return element('ul', { class: 'plain-list' }, documents.map((record) => {
    const kind = documentType(record.filename);
    const canPreview = kind === 'PDF' || kind === '图片';
    const reference = kind === 'PDF' && record.page ? `第 ${record.page} 页` : null;
    const meta = [record.category, kind, reference, record.note].filter(Boolean).join(' · ');
    return element('li', { class: 'list-row' },
      element('div', { class: 'description' },
        element('strong', {}, record.title),
        element('div', { class: 'muted small-text' }, meta)),
      element('div', { class: 'row-actions' },
        canPreview && button('预览', () => openDocumentPreview(record, kind), 'small', { 'aria-label': `预览 ${record.title}` }),
        element('a', { href: fileAddress(record, true), class: 'button small', 'aria-label': `下载 ${record.title}` }, '下载')),
    );
  }));
}

function systemAssociations(device) {
  const blocks = [];
  for (const system of state.catalog.systems) {
    const deployments = system.deployments.filter((deployment) => deployment.device_id === device.id);
    if (!deployments.length) continue;
    blocks.push(element('section', { class: 'subsection' },
      element('h3', {}, internalLink('system', system.id, system.name)),
      deployments.map((deployment) => element('div', { class: 'stack' },
        deployment.note && element('p', { class: 'muted small-text' }, deployment.note),
        serviceEntries(deployment.entries))),
    ));
  }
  return blocks.length ? blocks : empty('暂无部署记录。');
}

function procurementSections(device) {
  const own = state.catalog.documents.filter((document) => document.device_id === device.id);
  const projects = device.project_ids.map((id) => lookup('projects', id)).filter(Boolean);
  return [
    panel('采购与项目档案', [
      factList([
        ['购置时间', device.purchased_on || '未单列'],
        ['购置价格', device.price == null ? '未单列' : `¥${Number(device.price).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`],
      ]),
      element('div', { class: 'stack procurement-projects' },
        projects.length ? projects.map((project) =>
          element('section', { class: 'subsection' },
            element('h3', {}, internalLink('project', project.id, project.name)),
            documentList(state.catalog.documents.filter((document) => document.project_id === project.id), '暂无项目档案。'),
          )) : element('p', { class: 'muted small-text' }, '暂无关联项目。')),
    ]),
    panel('设备专属档案', documentList(own),
      userCanWrite() ? [button('添加档案', () => openDocumentEditor('device', device), 'small')] : []),
  ];
}

function deviceFacts(device) {
  return factList([
    ['设备编号', device.code], ['设备类型', device.type],
    ['品牌型号', device.model], ['序列号', device.serial],
    ['位置', deviceLocation(device, true), true],
    ...(device.rack_id ? [['安装深度', mountDepthLabels[mountDepth(device)], true]] : []),
    ['运行状态（人工登记）', operatingStatusLabel(device)],
    ['用途', device.purpose || '用途待查', true],
    ['归属', device.ownership || '未登记'], ['最近核实', device.verified_on || '待核实'],
    ['填报人', device.reporter || '未登记'], ['维护人', device.maintainer || '责任人未确认'],
  ]);
}

function dialogHeader(id, title, subtitle, dialog, close = () => dialog.close()) {
  return element('header', { class: 'dialog-head' },
    element('div', {}, element('h2', { id, class: 'dialog-title' }, title),
      subtitle && element('p', { class: 'muted small-text' }, subtitle)),
    button('关闭', close, 'quiet small'));
}

function savedDeviceClickMode() {
  try {
    if (localStorage.getItem(deviceClickModeKey) === 'detail') return 'detail';
  } catch {
    // 存储受限时仍可在本次会话切换查看方式。
  }
  return 'quick';
}

function deviceClickModeControl() {
  const group = element('div', { class: 'device-click-mode', role: 'group', 'aria-label': '设备点击方式' });
  const choices = deviceClickModes.map(([mode, label]) => button(label, () => {
    if (state.deviceClickMode === mode) return;
    state.deviceClickMode = mode;
    try { localStorage.setItem(deviceClickModeKey, mode); } catch { /* 沿用会话内选择 */ }
    closeDevicePresentation();
    update();
  }, 'quiet small'));
  function update() {
    choices.forEach((choice, index) =>
      choice.setAttribute('aria-pressed', String(state.deviceClickMode === deviceClickModes[index][0])));
  }
  update();
  group.append(...choices);
  return group;
}

function selectDevice(device, anchor) {
  if (device && anchor && anchor === deviceSelection?.anchor) return;
  deviceSelection?.anchor?.setSelected?.(false);
  const point = Number.isFinite(anchor?.x) && Number.isFinite(anchor?.y);
  const anchorRect = point && anchor.element?.getBoundingClientRect();
  deviceSelection = device ? {
    anchor,
    offset: anchorRect ? {
      x: anchor.x - anchorRect.left,
      y: anchor.y - anchorRect.top,
      width: anchorRect.width,
      height: anchorRect.height,
    } : null,
  } : null;
  deviceSelection?.anchor?.setSelected?.(true);
}

function closeDevicePresentation({ restoreFocus = false } = {}) {
  const anchor = deviceSelection?.anchor;
  closeQuickPanel();
  if (drawer.open) drawer.close();
  selectDevice(null);
  restoreDevicePageScroll();
  if (restoreFocus) {
    const source = anchor?.element;
    const visible = source?.isConnected && (anchor.visible?.() ?? source.getClientRects().length > 0);
    (visible ? source : page).focus({ preventScroll: true });
  }
}

function closeQuickPanel() {
  deviceQuickGuide.setAttribute('hidden', '');
  if (deviceQuick.open) deviceQuick.close();
}

function dismissDeviceQuick() {
  if (deviceQuick.open) closeDevicePresentation();
}

function selectedDeviceRect() {
  const { anchor, offset } = deviceSelection ?? {};
  const source = anchor?.element;
  if (!source?.isConnected || !source.getClientRects().length) return null;
  const rect = source.getBoundingClientRect();
  if (offset && (!anchor.devicePoint || (rect.width === offset.width && rect.height === offset.height))) {
    const x = rect.left + offset.x;
    const y = rect.top + offset.y;
    return { left: x, right: x, top: y, bottom: y };
  }
  if (!anchor?.devicePoint) return rect;
  const point = anchor.devicePoint();
  return point && { left: point.x, right: point.x, top: point.y, bottom: point.y };
}

function restoreDevicePageScroll() {
  if (devicePageScroll === null) return;
  const scroll = devicePageScroll;
  devicePageScroll = null;
  workspace.style.removeProperty('--device-sheet-height');
  window.scrollTo(0, scroll);
}

function showDeviceAboveSheet(panel) {
  if (!deviceSheetMedia.matches) {
    restoreDevicePageScroll();
    return;
  }
  const target = selectedDeviceRect();
  if (!target) return;
  devicePageScroll ??= window.scrollY;
  const height = panel.offsetHeight;
  workspace.style.setProperty('--device-sheet-height', `${height}px`);
  const visibleHeight = window.innerHeight - height;
  const y = (target.top + target.bottom) / 2;
  if (y < 36 || y > visibleHeight - 32) {
    window.scrollBy(0, y - visibleHeight * .52);
  }
}

function positionDeviceQuick() {
  const edge = 12;
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = window.innerHeight;
  const target = selectedDeviceRect();
  const x = target ? (target.left + target.right) / 2 : viewportWidth / 2;
  const y = target ? (target.top + target.bottom) / 2 : viewportHeight / 2;

  if (!deviceSheetMedia.matches) {
    const anchor = deviceSelection?.anchor;
    const cabinet = anchor?.cabinetRect?.() ?? target;
    const neighbor = anchor?.neighborCabinetRect?.();
    const cabinetLeft = cabinet?.left ?? x;
    const cabinetRight = cabinet?.right ?? x;
    const leftLimit = neighbor?.right <= cabinetLeft ? Math.max(edge, neighbor.right + edge) : edge;
    const rightLimit = neighbor?.left >= cabinetRight
      ? Math.min(viewportWidth - edge, neighbor.left - edge) : viewportWidth - edge;
    const availableLeft = cabinetLeft - leftLimit;
    const availableRight = rightLimit - cabinetRight;
    deviceQuick.style.removeProperty('--quick-width');
    const compactWidth = Math.floor(Math.max(availableLeft, availableRight) - 20);
    if (neighbor && compactWidth >= 216 && compactWidth < deviceQuick.offsetWidth) {
      deviceQuick.style.setProperty('--quick-width', `${compactWidth}px`);
    }
    const width = deviceQuick.offsetWidth;
    const height = deviceQuick.offsetHeight;
    const rightSpace = availableRight - width;
    const leftSpace = availableLeft - width;
    let left;
    let top = y - height / 2;
    if (rightSpace >= 40 || (rightSpace >= 20 && leftSpace < 40)) {
      left = cabinetRight + Math.min(40, rightSpace);
    } else if (leftSpace >= 20) {
      left = cabinetLeft - width - Math.min(40, leftSpace);
    } else {
      left = x - width / 2;
      const lower = (cabinet?.bottom ?? y) + 24;
      const upper = (cabinet?.top ?? y) - height - 24;
      if (lower + height <= viewportHeight - edge) top = lower;
      else if (upper >= edge) top = upper;
      else top = y + height + 20 <= viewportHeight - edge ? y + 20 : y - height - 20;
    }
    left = Math.max(edge, Math.min(left, viewportWidth - width - edge));
    top = Math.max(edge, Math.min(top, viewportHeight - height - edge));
    deviceQuick.style.setProperty('--quick-left', `${left}px`);
    deviceQuick.style.setProperty('--quick-top', `${top}px`);
    deviceQuick.style.setProperty('--quick-origin', `${Math.max(0, Math.min(width, x - left))}px ${Math.max(0, Math.min(height, y - top))}px`);
  }

  const visible = Boolean(target && x >= 0 && x < viewportWidth && y >= 0 && y < viewportHeight);
  drawDeviceQuickGuide(visible ? { x, y } : null);
}

function drawDeviceQuickGuide(point) {
  const card = deviceQuick.getBoundingClientRect();
  const dx = point ? Math.max(card.left - point.x, point.x - card.right, 0) : 0;
  const dy = point ? Math.max(card.top - point.y, point.y - card.bottom, 0) : 0;
  deviceQuickGuide.toggleAttribute('hidden', dx < 6 && dy < 6);
  if (dx < 6 && dy < 6) return;

  const { x, y } = point;
  let path;
  if (dx >= dy) {
    const startX = x < card.left ? card.left : card.right;
    const startY = Math.max(card.top + 14, Math.min(y, card.bottom - 14));
    path = `M ${startX} ${startY} H ${(startX + x) / 2} L ${x} ${y}`;
  } else {
    const startX = Math.max(card.left + 14, Math.min(x, card.right - 14));
    const startY = y < card.top ? card.top : card.bottom;
    path = `M ${startX} ${startY} V ${(startY + y) / 2} L ${x} ${y}`;
  }
  deviceQuickPath.setAttribute('d', path);
  deviceQuickTarget.setAttribute('cx', x);
  deviceQuickTarget.setAttribute('cy', y);
  deviceQuickGuide.classList.toggle('device-quick-guide-elevation', deviceSelection?.anchor?.element instanceof SVGElement);
}

function openDevicePresentation(device, anchor) {
  deviceOpenedByScenePointer = Number.isFinite(anchor?.x) && Number.isFinite(anchor?.y);
  if (state.deviceClickMode === 'detail' || drawer.open) {
    openDeviceDrawer(device, anchor);
    return;
  }
  selectDevice(device, anchor);
  const close = button('×', () => closeDevicePresentation({ restoreFocus: true }), 'quiet small device-quick-close',
    { 'aria-label': '关闭快览' });
  const details = button('查看详情', () => openDeviceDrawer(device, anchor), 'primary small', { autofocus: true });
  deviceQuick.dataset.deviceId = device.id;
  deviceQuick.replaceChildren(
    element('div', { class: 'device-quick-head' },
      element('div', {},
        element('h2', { id: 'device-quick-title' }, device.name),
        element('p', { class: 'muted small-text code' }, device.code)),
      close),
    element('p', { class: 'small-text' }, deviceLocation(device)),
    device.model && element('p', { class: 'muted small-text' }, device.model),
    element('div', { class: 'device-quick-actions' },
      element('span', { class: 'device-quick-status', 'data-status': operatingStatus(device) }, operatingStatusLabel(device)),
      details));
  if (!deviceQuick.open) deviceQuick.show();
  showDeviceAboveSheet(deviceQuick);
  positionDeviceQuick();
  details.focus({ preventScroll: true });
}

function openDeviceDrawer(device, anchor = (state.rackView ?? state.roomOverview?.controller)?.deviceAnchor?.(device?.id)) {
  if (!device) return;
  closeQuickPanel();
  selectDevice(device, anchor);
  drawer.dataset.deviceId = device.id;
  const actions = [internalLink('device', device.id, '打开设备详情', { class: 'button primary' })];
  if (userCanWrite()) actions.push(button('编辑设备', () => openDeviceEditor(device)));
  byId('drawer-content').replaceChildren(
    dialogHeader('drawer-title', device.name, `${device.code} · ${deviceLocation(device)}`, drawer,
      () => closeDevicePresentation({ restoreFocus: true })),
    element('div', { class: 'drawer-body' },
      element('div', { class: 'row-actions' }, actions),
      panel('业务系统与服务入口', systemAssociations(device)),
      procurementSections(device),
      panel('设备资料', deviceFacts(device))),
  );
  if (!drawer.open) drawer.show();
  drawer.scrollTop = 0;
  showDeviceAboveSheet(drawer);
  drawer.querySelector('.dialog-head button').focus({ preventScroll: true });
}

function renderDevicePage(device) {
  page.append(
    internalLink('devices', null, '返回设备台账', { class: 'back-link' }),
    pageHeading(device.name, `${device.code} · ${device.type}`,
      userCanWrite() ? [button('编辑设备', () => openDeviceEditor(device), 'primary')] : []),
    element('div', { class: 'detail-columns' },
      element('div', { class: 'stack' }, panel('设备资料', deviceFacts(device)), panel('业务系统与服务入口', systemAssociations(device))),
      element('div', { class: 'stack' }, procurementSections(device)),
    ),
  );
}

function renderSystemPage(system) {
  const deployments = system.deployments.map((deployment) => {
    const device = lookup('devices', deployment.device_id);
    if (!device) return null;
    return element('section', { class: 'subsection' },
      element('h3', {}, internalLink('device', device.id, device.name)),
      element('div', { class: 'stack' },
        element('p', { class: 'muted small-text' }, deviceLocation(device, true),
          deployment.note && ` · ${deployment.note}`),
        serviceEntries(deployment.entries)),
    );
  }).filter(Boolean);
  page.append(
    internalLink('systems', null, '返回业务系统', { class: 'back-link' }),
    pageHeading(system.name, system.description,
      userCanWrite() ? [button('编辑系统与部署', () => openSystemEditor(system), 'primary')] : []),
    panel('部署设备及服务入口', deployments.length ? deployments : empty('暂无部署。')),
  );
}

function renderProjectPage(project) {
  const documents = state.catalog.documents.filter((document) => document.project_id === project.id);
  const devices = project.device_ids.map((id) => lookup('devices', id)).filter(Boolean);
  page.append(
    internalLink('projects', null, '返回项目档案', { class: 'back-link' }),
    pageHeading(project.name, joinedPath(project.code, lookup('sites', project.site_id)?.name),
      userCanWrite() ? [button('编辑项目', () => openProjectEditor(project), 'primary')] : []),
  );
  if (project.description) page.append(panel('项目说明', element('p', {}, project.description)));
  page.append(
    element('div', { class: 'detail-columns' },
      panel('项目档案', documentList(documents),
        userCanWrite() ? [button('添加档案', () => openDocumentEditor('project', project), 'small')] : []),
      panel('采购设备', table(['设备', '位置'], devices.map((device) => [
        element('div', {}, internalLink('device', device.id, device.name),
          element('div', { class: 'muted small-text code' }, device.code)),
        deviceLocation(device, true),
      ]), '暂无关联设备。')),
    ),
  );
}

function readRoute() {
  const [kind, id] = location.hash.slice(1).split('/');
  if (Object.hasOwn(collectionRoutes, kind)) return { kind, id, section: collectionRoutes[kind] };
  if (kind === 'rack') return { kind, id, section: 'rooms' };
  if (Object.hasOwn(titles, kind)) return { kind, id, section: kind };
  return { kind: 'rooms', id: null, section: 'rooms' };
}

function renderPage({ preserveRackView = false, roomFilterChanged = false } = {}) {
  if (!state.catalog) return;
  closeDevicePresentation();
  const view = preserveRackView ? state.rackView?.snapshot?.() : undefined;
  state.rackView?.();
  state.rackView = null;
  const { kind, id, section } = readRoute();
  if (kind === 'rack' && state.roomOverview) state.rackOverviewRoomId = state.roomOverview.roomId;
  else if (kind !== 'rack') state.rackOverviewRoomId = null;
  disposeRoomOverview(true);
  byId('breadcrumb').replaceChildren(element('span', { 'aria-current': 'page' }, titles[section]));
  document.querySelectorAll('.nav [data-route]').forEach((link) => {
    if (link.dataset.route === section) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  page.replaceChildren();
  if (kind === 'rooms') return renderRoomPage(id, roomFilterChanged);
  if (kind === 'rack') renderRackPage(id, view);
  if (kind === 'devices') renderDevicesPage();
  if (kind === 'systems') renderSystemsPage();
  if (kind === 'projects') renderProjectsPage();
  if (Object.hasOwn(collectionRoutes, kind)) {
    const item = lookup(section, id);
    if (!item) page.append(pageHeading(titles[section]), empty('当前范围内没有这条记录。'));
    else if (kind === 'device') renderDevicePage(item);
    else if (kind === 'system') renderSystemPage(item);
    else renderProjectPage(item);
  }
  return state.rackView?.ready;
}

function inputField(label, name, value, attributes = {}, layout = '') {
  return labelInput(label, element('input', { type: 'text', name, value: value ?? '', ...attributes }), layout);
}

function textAreaField(label, name, value, attributes = {}) {
  return labelInput(label, element('textarea', { name, rows: 2, ...attributes }, value), 'wide');
}

function labeledSelect(label, name, options, value, blank = null, attributes = {}) {
  return labelInput(label, selectInput(name, options, value ?? '', blank, attributes));
}

function checkboxGroup(caption, items, chosen, name, emptyMessage) {
  const select = new Set(chosen);
  return element('fieldset', { class: 'fieldset' }, element('legend', {}, caption),
    items.length ? element('div', { class: 'checkbox-list' }, items.map(([value, text]) =>
      element('label', { class: 'checkbox' }, element('input', { type: 'checkbox', name, value, checked: select.has(value) }), text)))
      : element('p', { class: 'muted small-text' }, emptyMessage));
}

function numberOrNull(value) {
  return value === '' || value == null ? null : Number(value);
}

function showEditor({ title, id, fields, save, success, afterSave }) {
  const errorBox = element('div', { class: 'form-error', role: 'alert', tabindex: -1, hidden: true });
  const submit = element('button', { class: 'button primary', type: 'submit' }, '保存');
  const form = element('form', { id, onsubmit: async (event) => {
    event.preventDefault();
    const origin = location.hash;
    const originView = state.rackView ?? state.roomOverview;
    submit.disabled = true;
    showError(errorBox);
    let record;
    try {
      record = await save(form);
    } catch (error) {
      showError(errorBox, error.message);
      if (editor.open && editor.contains(form)) errorBox.focus();
      submit.disabled = false;
      return;
    }
    const restoreContext = editor.open && editor.contains(form) && location.hash === origin;
    const initialScroll = devicePageScroll ?? window.scrollY;
    if (restoreContext) closeDialogs();
    try {
      state.catalog = await request('catalog');
      const route = location.hash;
      const restoreOrigin = restoreContext && route === origin && (state.rackView ?? state.roomOverview) === originView;
      const scroll = restoreOrigin ? initialScroll : window.scrollY;
      await renderPage({ preserveRackView: true });
      if (location.hash === route) {
        window.scrollTo(0, scroll);
        if (restoreOrigin && !editor.open && !drawer.open) {
          page.focus({ preventScroll: true });
          if (afterSave) afterSave(record);
        }
      }
      notify(success);
    } catch {
      if (state.user) notify('已保存。台账刷新失败，请重新加载页面。');
    }
  } },
  element('div', { class: 'editor-body' }, errorBox, fields),
  element('footer', { class: 'editor-actions' },
    button('取消', () => editor.close()), submit));

  byId('editor-content').replaceChildren(dialogHeader('editor-title', title, null, editor), form);
  if (!editor.open) editor.showModal();
}

function roomOptions() {
  return state.catalog.rooms.map((room) =>
    [room.id, joinedPath(lookup('sites', room.site_id)?.name, room.name)]);
}

function openDeviceEditor(device = null, rack = null, slot = null) {
  const original = device || {};
  const drawerScroll = device && drawer.open ? drawer.scrollTop : null;
  const roomChoice = selectInput('room_id', roomOptions(), original.room_id || rack?.room_id,
    '选择机房或房间', { required: true });
  const rackChoice = selectInput('rack_id', [], '', '非上架设备');
  const faceChoice = selectInput('face', [['front', '正面'], ['rear', '背面']],
    original.face || slot?.face || 'front');
  const startInput = element('input', { name: 'u_start', type: 'number', min: 1, step: 1,
    value: original.u_start ?? slot?.u_start ?? 1 });
  const heightInput = element('input', { name: 'u_height', type: 'number', min: 1, step: 1, value: original.u_height ?? 1 });
  const depthChoice = selectInput('mount_depth', Object.entries(mountDepthLabels), mountDepth(original), null,
    { 'aria-describedby': 'mount-depth-hint' });
  const rackSlots = element('div', { class: 'field-grid wide' },
    labelInput('安装面', faceChoice), labelInput('起始 U 位', startInput),
    labelInput('占用高度（U）', heightInput), labelInput('安装深度', depthChoice),
    element('p', { class: 'muted small-text wide', id: 'mount-depth-hint' }, '前后共用 U 位时，两台设备均需为半深。'));
  const workstation = inputField('工位', 'workstation', original.workstation, { maxlength: 180 }, 'wide');

  function syncMountFields() {
    const choice = lookup('racks', rackChoice.value);
    rackSlots.hidden = !choice;
    workstation.hidden = Boolean(choice);
    workstation.querySelector('input').disabled = Boolean(choice);
    for (const input of [faceChoice, startInput, heightInput, depthChoice]) {
      input.disabled = !choice;
      input.required = Boolean(choice);
    }
    for (const input of [startInput, heightInput]) {
      if (choice) input.max = choice.height;
      else input.removeAttribute('max');
    }
  }

  function syncRackChoices(selected) {
    const options = state.catalog.racks.filter((item) => String(item.room_id) === roomChoice.value);
    rackChoice.replaceChildren(element('option', { value: '' }, '非上架设备'),
      ...options.map((item) => element('option', { value: item.id }, `${item.name} · ${item.height}U`)));
    rackChoice.value = options.some((item) => String(item.id) === String(selected)) ? selected : '';
    syncMountFields();
  }

  roomChoice.addEventListener('change', () => syncRackChoices(rackChoice.value));
  rackChoice.addEventListener('change', syncMountFields);
  syncRackChoices(original.rack_id || rack?.id);
  const id = original.id;
  showEditor({
    title: id ? '编辑设备' : '新增设备', id: 'device-form',
    fields: [
      element('div', { class: 'field-grid' },
        inputField('设备编号', 'code', original.code, { required: true, maxlength: 80 }),
        inputField('设备名称', 'name', original.name, { required: true, maxlength: 160 }),
        inputField('设备类型', 'type', original.type, { required: true, maxlength: 80, placeholder: '例如服务器、交换机、打印机' }),
        inputField('品牌型号', 'model', original.model, { maxlength: 160 }),
        labelInput('运行状态（人工登记）', selectInput(
          'operating_status', Object.entries(OPERATING_STATUS_LABELS), operatingStatus(original), null,
        )),
        inputField('序列号', 'serial', original.serial, { maxlength: 160 }),
        inputField('归属', 'ownership', original.ownership, { maxlength: 160 }),
        labelInput('机房／房间', roomChoice), labelInput('机柜', rackChoice),
        rackSlots, workstation,
        textAreaField('用途', 'purpose', original.purpose, { maxlength: 500, placeholder: '用途待查' }),
        inputField('填报人', 'reporter', original.reporter, { maxlength: 120 }),
        inputField('维护人', 'maintainer', original.maintainer, { maxlength: 120, placeholder: '责任人未确认' }),
        inputField('最近核实时间', 'verified_on', original.verified_on, { type: 'date' }),
        inputField('购置时间', 'purchased_on', original.purchased_on, { type: 'date' }),
        inputField('购置价格（元）', 'price', original.price, { type: 'number', min: '0', step: '0.01', placeholder: '未单列' }),
      ),
      checkboxGroup('关联项目', state.catalog.projects.map((project) => [project.id, `${project.name} · ${project.code}`]),
        original.project_ids || [], 'project_ids', '暂无项目。'),
    ],
    save: (form) => {
      const values = new FormData(form);
      return request(id ? `devices/${id}` : 'devices', {
        method: id ? 'PATCH' : 'POST',
        data: {
          ...Object.fromEntries(values),
          room_id: Number(values.get('room_id')),
          rack_id: numberOrNull(values.get('rack_id')),
          face: values.get('face'),
          u_start: numberOrNull(values.get('u_start')),
          u_height: numberOrNull(values.get('u_height')),
          workstation: values.get('workstation') ?? '',
          verified_on: values.get('verified_on') || null,
          purchased_on: values.get('purchased_on') || null,
          price: numberOrNull(values.get('price')),
          project_ids: values.getAll('project_ids').map(Number),
        },
      });
    },
    success: id ? '设备更新成功。' : '设备已添加。',
    afterSave: drawerScroll == null ? undefined : (record) => {
      const updated = lookup('devices', record.id);
      if (!updated) return;
      openDeviceDrawer(updated);
      drawer.scrollTop = drawerScroll;
    },
  });
}

function openRoomLayoutEditor(room, layout, racks) {
  const positions = new Map((layout?.positions ?? []).map((position) => [position.rack_id, position]));
  const rotations = [
    [0, '0° 朝近侧'],
    [90, '90° 朝右'],
    [180, '180° 朝远侧'],
    [270, '270° 朝左'],
  ];
  const rackRows = racks.map((rack) => {
    const position = positions.get(rack.id);
    return [
      rack.name,
      element('input', {
        type: 'number', name: `row-${rack.id}`, value: position?.row ?? '',
        min: 1, max: 12, step: 1, 'aria-label': `${rack.name} 排`,
      }),
      element('input', {
        type: 'number', name: `slot-${rack.id}`, value: position?.slot ?? '',
        min: 1, max: 20, step: 1, 'aria-label': `${rack.name} 柜位`,
      }),
      selectInput(`rotation-${rack.id}`, rotations, position?.rotation ?? 0, null, {
        'aria-label': `${rack.name} 朝向`,
      }),
    ];
  });
  showEditor({
    title: '编辑机柜布局', id: 'room-layout-form',
    fields: [
      element('div', { class: 'field-grid' },
        inputField('排数', 'rows', layout?.rows ?? 2, { type: 'number', min: 1, max: 12, step: 1, required: true }),
        inputField('每排柜位数', 'columns', layout?.columns ?? 5, { type: 'number', min: 1, max: 20, step: 1, required: true })),
      element('p', { class: 'muted small-text' },
        '以正俯视为准，第一排在下方，柜位从左向右编号。排和柜位均留空时，机柜显示在「待摆放」。'),
      table(['机柜', '排', '柜位', '朝向'], rackRows, '本机房暂未登记机柜。'),
    ],
    save: (form) => {
      const values = new FormData(form);
      const updated = [];
      for (const rack of racks) {
        const row = numberOrNull(values.get(`row-${rack.id}`));
        const slot = numberOrNull(values.get(`slot-${rack.id}`));
        if (row == null && slot == null) continue;
        if (row == null || slot == null) throw new Error(`请同时填写 ${rack.name} 的排和柜位。`);
        updated.push({ rack_id: rack.id, row, slot, rotation: Number(values.get(`rotation-${rack.id}`)) });
      }
      return request(`rooms/${room.id}/layout`, {
        method: 'PATCH',
        data: { rows: Number(values.get('rows')), columns: Number(values.get('columns')), positions: updated },
      });
    },
    success: '机房布局已保存。',
  });
}

function removeAction(label, block) {
  return button(label, () => {
    const container = block.parentElement;
    block.remove();
    const survivor = container.querySelector('input, select, textarea, button');
    survivor?.focus();
  }, 'quiet small danger');
}

function buildServiceEntry(entry = {}) {
  const wrapper = element('div', { class: 'fieldset stack', 'data-entry': true });
  wrapper.append(element('div', { class: 'panel-heading' },
    element('h3', {}, '服务入口'), removeAction('移除此入口', wrapper)),
    element('div', { class: 'field-grid' },
      inputField('IP／域名', 'host', entry.host, { maxlength: 253, placeholder: '192.0.2.10' }),
      inputField('协议', 'protocol', entry.protocol, { required: true, maxlength: 32, placeholder: 'HTTPS' }),
      inputField('端口', 'port', entry.port, { type: 'number', min: 1, max: 65535, step: 1 }),
      inputField('用途', 'purpose', entry.purpose, { maxlength: 300 }),
      inputField('网页访问地址', 'url', entry.url, { type: 'url', maxlength: 1000, placeholder: 'https://example.test/' }, 'wide')));
  return wrapper;
}

function buildDeployment(deployment = {}) {
  const deploymentBlock = element('fieldset', { class: 'fieldset stack', 'data-deployment': true });
  const entries = element('div', { class: 'stack' }, (deployment.entries || []).map(buildServiceEntry));
  deploymentBlock.append(
    element('legend', {}, '部署记录'),
    element('div', { class: 'field-grid' },
      labeledSelect('部署设备', 'device_id',
        state.catalog.devices.map((device) => [device.id, `${device.name} · ${device.code}`]),
        deployment.device_id, '选择设备', { required: true }),
      inputField('部署备注', 'note', deployment.note, { maxlength: 500 })),
    entries,
    element('div', { class: 'row-actions' },
      button('添加服务入口', () => {
        const row = buildServiceEntry();
        entries.append(row);
        row.querySelector('input').focus();
      }, 'small'), removeAction('移除此部署', deploymentBlock)),
  );
  return deploymentBlock;
}

function openSystemEditor(system = null) {
  const original = system || {};
  const deployments = element('div', { class: 'stack' }, (original.deployments || []).map(buildDeployment));
  const id = original.id;
  showEditor({
    title: id ? '编辑系统与部署' : '新增系统', id: 'system-form',
    fields: [
      element('div', { class: 'field-grid' },
        inputField('系统名称', 'name', original.name, { required: true, maxlength: 160 }, 'wide'),
        textAreaField('用途说明', 'description', original.description, { maxlength: 1000 })),
      deployments,
      button('添加部署设备', () => {
        const deployment = buildDeployment();
        deployments.append(deployment);
        deployment.querySelector('select').focus();
      }, 'small'),
    ],
    save: (form) => request(id ? `systems/${id}` : 'systems', {
      method: id ? 'PATCH' : 'POST',
      data: {
        name: form.elements.name.value,
        description: form.elements.description.value,
        deployments: Array.from(deployments.children).map((block) => ({
          device_id: Number(block.querySelector('[name="device_id"]').value),
          note: block.querySelector('[name="note"]').value,
          entries: Array.from(block.querySelectorAll('[data-entry]')).map((entry) => ({
            host: entry.querySelector('[name="host"]').value,
            protocol: entry.querySelector('[name="protocol"]').value,
            port: numberOrNull(entry.querySelector('[name="port"]').value),
            purpose: entry.querySelector('[name="purpose"]').value,
            url: entry.querySelector('[name="url"]').value,
          })),
        })),
      },
    }),
    success: id ? '系统部署已更新。' : '系统已添加。',
  });
}

function openProjectEditor(project = null) {
  const original = project || {};
  const id = original.id;
  showEditor({
    title: id ? '编辑项目' : '新增项目', id: 'project-form',
    fields: [
      element('div', { class: 'field-grid' },
        inputField('项目编号', 'code', original.code, { required: true, maxlength: 80 }),
        inputField('项目名称', 'name', original.name, { required: true, maxlength: 160 }),
        labeledSelect('归属站点', 'site_id', state.catalog.sites.map((site) => [site.id, site.name]),
          original.site_id, '选择站点', { required: true }),
        textAreaField('项目说明', 'description', original.description, { maxlength: 1000 })),
      checkboxGroup('关联设备', state.catalog.devices.map((device) => [device.id, `${device.name} · ${device.code}`]),
        original.device_ids || [], 'device_ids', '暂无设备。'),
    ],
    save: (form) => {
      const values = new FormData(form);
      return request(id ? `projects/${id}` : 'projects', {
        method: id ? 'PATCH' : 'POST',
        data: {
          ...Object.fromEntries(values),
          site_id: Number(values.get('site_id')),
          device_ids: values.getAll('device_ids').map(Number),
        },
      });
    },
    success: id ? '项目已更新。' : '项目已添加。',
  });
}

function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',', 2)[1]));
    reader.addEventListener('error', () => reject(new Error('读取文件失败。')));
    reader.readAsDataURL(file);
  });
}

function openDocumentEditor(type, record) {
  const wasInDrawer = drawer.open;
  const categories = ['工程量清单', '施工设计图', '合同', '验收报告', '设备资料', '其他'];
  const acceptedExtensions = Array.from(documentTypes.keys(), (extension) => `.${extension}`).join(',');
  const fileInput = element('input', { name: 'file', type: 'file', accept: acceptedExtensions, required: true,
    'aria-describedby': 'document-file-hint' });
  const referenceInput = element('input', { name: 'page', type: 'number', min: 1, max: 9999, step: 1, disabled: true });
  const referenceField = labelInput('参考页码', referenceInput);
  referenceField.hidden = true;
  fileInput.addEventListener('change', () => {
    const allowsPage = documentType(fileInput.files[0]?.name) === 'PDF';
    referenceField.hidden = !allowsPage;
    referenceInput.disabled = !allowsPage;
    if (!allowsPage) referenceInput.value = '';
  });
  showEditor({
    title: '添加档案', id: 'document-form',
    fields: [
      element('p', { class: 'muted small-text' }, `${type === 'project' ? '项目' : '设备'} · ${record.name}`),
      element('div', { class: 'field-grid' },
        inputField('档案名称', 'title', null, { required: true, maxlength: 160 }),
        labeledSelect('档案类别', 'category', categories.map((value) => [value, value]),
          '', '选择类别', { required: true }),
        labelInput('档案原件（最多 8 MiB）', fileInput, 'wide'),
        element('p', { id: 'document-file-hint', class: 'muted small-text wide' },
          '支持 PDF、PNG、JPEG、GIF、WebP、Word 和 Excel。'),
        referenceField,
        textAreaField('备注', 'note', '', { maxlength: 800 })),
    ],
    save: async (form) => {
      const values = new FormData(form);
      const file = values.get('file');
      if (!file?.size) throw new Error('请选择档案文件。');
      const kind = documentType(file.name);
      if (!kind) throw new Error('请选择受支持的档案格式。');
      if (file.size > 8 * 1024 * 1024) throw new Error('档案原件大小不能超过 8 MiB。');
      return request('documents', {
        method: 'POST',
        data: {
          title: values.get('title'),
          category: values.get('category'),
          page: kind === 'PDF' ? numberOrNull(values.get('page')) : null,
          note: values.get('note'),
          filename: file.name,
          content_base64: await readFileBase64(file),
          [`${type}_id`]: record.id,
        },
      });
    },
    success: '档案已添加。',
    afterSave: wasInDrawer && type === 'device' ? () => openDeviceDrawer(lookup('devices', record.id)) : null,
  });
}

function syncLoginControls() {
  loginSubmit.disabled = auth.submitting || !auth.mode || (auth.mode === 'ai' && !auth.captchaId);
  byId('captcha-refresh').disabled = auth.refreshing || auth.submitting;
}

async function refreshCaptcha() {
  if (auth.refreshing || auth.submitting) return;
  auth.captchaId = '';
  auth.refreshing = true;
  syncLoginControls();
  const image = byId('captcha-image');
  const placeholder = byId('captcha-placeholder');
  image.hidden = true;
  image.removeAttribute('src');
  placeholder.hidden = false;
  placeholder.textContent = '正在加载…';
  loginForm.elements.captcha.value = '';
  try {
    const { captcha_id: id, image_svg: svg } = await request('captcha', { ai: true });
    if (!id || typeof svg !== 'string' || !svg.startsWith('<svg')) throw new Error('验证码响应无效。');
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    image.hidden = false;
    placeholder.hidden = true;
    auth.captchaId = id;
  } catch {
    placeholder.textContent = '重新获取';
    if (byId('login-error').hidden) showError(byId('login-error'), '验证码加载失败，请重新获取。');
  } finally {
    auth.refreshing = false;
    syncLoginControls();
  }
}

async function loginWithAi(credentials) {
  const captcha = loginForm.elements.captcha.value.trim().toUpperCase();
  const captchaId = auth.captchaId;
  auth.captchaId = '';
  try {
    await request('login', { ai: true, method: 'POST', data: { ...credentials, captcha_id: captchaId, captcha } });
  } catch (error) {
    if (error.status === 401) throw new Error('账号、密码或验证码不正确。');
    throw error;
  }
  loginForm.elements.password.value = '';
  return request('me');
}

byId('captcha-refresh').addEventListener('click', () => {
  showError(byId('login-error'));
  void refreshCaptcha();
});

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (loginSubmit.disabled) return;
  auth.submitting = true;
  syncLoginControls();
  showError(byId('login-error'));
  try {
    const credentials = {
      username: loginForm.elements.username.value.trim(), password: loginForm.elements.password.value,
    };
    const user = auth.mode === 'ai' ? await loginWithAi(credentials)
      : await request('login', { method: 'POST', data: credentials });
    loginForm.elements.password.value = '';
    await openWorkspace(user);
    page.focus();
  } catch (error) {
    showError(byId('login-error'), error.message);
    (auth.mode === 'ai' ? loginForm.elements.captcha : loginForm.elements.password).focus();
  } finally {
    auth.submitting = false;
    syncLoginControls();
    if (auth.mode === 'ai' && !state.user) void refreshCaptcha();
  }
});

byId('logout').addEventListener('click', async () => {
  try {
    await request('logout', { method: 'POST', data: {}, ai: auth.mode === 'ai' });
    showLogin();
    loginForm.elements.username.focus();
  } catch (error) {
    if (state.user) notify(error.message);
  }
});

document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  (state.user ? page : loginForm.elements.username).focus();
});

window.addEventListener('hashchange', () => {
  closeDialogs();
  renderPage();
  if (state.user) {
    if (readRoute().kind !== 'rooms') window.scrollTo(0, 0);
    page.focus({ preventScroll: true });
  }
});

let outsideDevicePointer;
document.addEventListener('pointerdown', (event) => {
  deviceOpenedByScenePointer = false;
  const panel = deviceQuick.open ? deviceQuick : drawer.open ? drawer : null;
  outsideDevicePointer = panel && !editor.open && !preview.open && event.isPrimary && event.button === 0
    && !panel.contains(event.target)
    ? { panel, selection: deviceSelection, id: event.pointerId, touch: event.pointerType === 'touch',
      x: event.clientX, y: event.clientY } : null;
}, { capture: true });
document.addEventListener('pointermove', (event) => {
  const pointer = outsideDevicePointer;
  if (pointer?.id === event.pointerId && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 6) {
    outsideDevicePointer = null;
  }
}, { capture: true, passive: true });
document.addEventListener('pointercancel', () => { outsideDevicePointer = null; });
document.addEventListener('click', (event) => {
  // 场景在 pointerup 展开浮层，阻止同一次触点的 click 被新出现的按钮接住。
  const fromScene = deviceOpenedByScenePointer;
  deviceOpenedByScenePointer = false;
  if (fromScene && event.detail &&
    ((deviceQuick.open && deviceQuick.contains(event.target)) || (drawer.open && drawer.contains(event.target)))) {
    event.preventDefault();
    event.stopPropagation();
  }
}, { capture: true });
document.addEventListener('click', (event) => {
  const pointer = outsideDevicePointer;
  outsideDevicePointer = null;
  // 浏览器可能微调触屏 click 的落点，实际拖动已在 pointermove 时排除。
  if (event.detail && pointer?.panel.open && !editor.open && !preview.open && pointer.selection === deviceSelection
    && !pointer.panel.contains(event.target) && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) <= (pointer.touch ? 14 : 6)) {
    closeDevicePresentation();
  }
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !editor.open && !preview.open && (deviceQuick.open || drawer.open)) {
    event.preventDefault();
    closeDevicePresentation({ restoreFocus: true });
  }
});
window.addEventListener('resize', () => {
  if (deviceQuick.open) {
    showDeviceAboveSheet(deviceQuick);
    positionDeviceQuick();
  } else if (drawer.open) {
    showDeviceAboveSheet(drawer);
  }
});
deviceQuick.addEventListener('animationend', () => {
  if (deviceQuick.open) positionDeviceQuick();
});
window.addEventListener('scroll', (event) => {
  if (deviceQuick.open && !(event.target instanceof Node && deviceQuick.contains(event.target))) positionDeviceQuick();
}, { capture: true, passive: true });

preview.addEventListener('close', () => {
  if (!preview.open) {
    clearPdfViewer();
    byId('pdf-content').replaceChildren();
  }
});

async function loadWorkspace() {
  try {
    const { mode } = await request('auth-config');
    if (mode !== 'ai' && mode !== 'local') throw new Error('登录配置无效，请刷新页面。');
    auth.mode = mode;
    if (mode === 'ai') {
      byId('login-hint').textContent = '使用已开通机房权限的 AI 槑槑账号登录。';
      byId('login-captcha').hidden = false;
      loginForm.elements.captcha.disabled = false;
      loginForm.elements.captcha.required = true;
      byId('logout').textContent = '退出统一登录';
    }
    await openWorkspace(await request('me'));
  } catch (error) {
    showLogin(error.status === 401 ? '' : error.message);
  } finally {
    syncLoginControls();
  }
}

void loadWorkspace();
