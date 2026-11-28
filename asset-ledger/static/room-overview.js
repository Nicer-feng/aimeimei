import { OPERATING_STATUS_LABELS, operatingStatus } from './rack.js?v=operating-status';
import { rackOccupancy } from './rack-geometry.js';
import { renderRoomProfilePlan } from './room-profiles.js';
import {
  buildDeviceSearch, deviceAddressLabel, endpointLabel, isDeviceArchived, normalizeSearchText as normalize,
} from './asset-search.js';

export const FRONT_MARKERS = {
  0: ['↓', '下'],
  90: ['→', '右'],
  180: ['↑', '上'],
  270: ['←', '左'],
};

function element(tag, className, label) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (label) node.textContent = label;
  return node;
}

function action(label, className, onClick) {
  const button = element('button', className, label);
  button.type = 'button';
  button.addEventListener('click', onClick);
  return button;
}

function locateIcon() {
  const namespace = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(namespace, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const ring = document.createElementNS(namespace, 'circle');
  ring.setAttribute('cx', '12');
  ring.setAttribute('cy', '12');
  ring.setAttribute('r', '6');
  const marks = document.createElementNS(namespace, 'path');
  marks.setAttribute('d', 'M12 2v4m0 12v4M2 12h4m12 0h4');
  const center = document.createElementNS(namespace, 'circle');
  center.setAttribute('cx', '12');
  center.setAttribute('cy', '12');
  center.setAttribute('r', '1.4');
  center.setAttribute('fill', 'currentColor');
  center.setAttribute('stroke', 'none');
  svg.append(ring, marks, center);
  return svg;
}

function cabinetLink(rack, onRack, className) {
  const link = element('a', className);
  link.href = `#rack/${rack.id}`;
  link.dataset.rackId = rack.id;
  link.addEventListener('click', (event) => {
    if (!onRack || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onRack(rack);
  });
  return link;
}

function cabinetList(racks, onRack) {
  const list = element('ul', 'room-overview-cabinet-list');
  for (const rack of racks) {
    const item = element('li');
    const link = cabinetLink(rack, onRack, 'room-overview-cabinet-link');
    link.append(element('span', '', rack.name), element('span', 'room-overview-rack-height', `${rack.height}U`));
    item.append(link);
    list.append(item);
  }
  return list;
}

function roomStatistics(racks, devices, slotCount) {
  const mounted = new Map(racks.map((rack) => [String(rack.id), []]));
  const statusCounts = { running: 0, unknown: 0, unpowered: 0, disabled: 0 };
  let mountedCount = 0;
  for (const device of devices) {
    statusCounts[operatingStatus(device)] += 1;
    const rackDevices = mounted.get(String(device.rack_id));
    if (rackDevices) {
      rackDevices.push(device);
      mountedCount += 1;
    }
  }
  let usedU = 0;
  let totalU = 0;
  for (const rack of racks) {
    usedU += rackOccupancy(rack, mounted.get(String(rack.id))).usedU;
    totalU += rack.height;
  }
  const statistics = element('div', 'room-statistics');
  const totals = element('dl', 'room-statistic-list');
  totals.setAttribute('aria-label', '机房统计');
  function metric(list, label, value) {
    const item = element('div', 'room-statistic');
    const reading = element('dd', '', String(value));
    item.append(element('dt', '', label), reading);
    list.append(item);
    return item;
  }
  metric(totals, '机柜', racks.length);
  metric(totals, '在册设备', devices.length);
  const occupancy = metric(totals, 'U 位利用率', totalU ? `${Math.round(100 * usedU / totalU)}%` : '—');
  occupancy.title = '已占物理 U 位 / 机房总 U 位，正背面共用的 U 位只计一次。';
  const details = element('details', 'room-statistic-details');
  const summary = element('summary', '', '状态明细');
  const counts = element('dl', 'room-statistic-list');
  counts.setAttribute('aria-label', '设备状态与上架统计');
  for (const [status, count] of Object.entries(statusCounts)) {
    const item = metric(counts, OPERATING_STATUS_LABELS[status], count);
    item.dataset.status = status;
  }
  const unmounted = devices.length - mountedCount;
  if (slotCount) metric(counts, '柜位', slotCount);
  metric(counts, '已上架', mountedCount);
  metric(counts, '未上架', unmounted);
  if (totalU) metric(counts, '已占 U 位', `${usedU} / ${totalU}U`);
  const attention = statusCounts.unknown + statusCounts.unpowered;
  if (attention) {
    summary.append(element('span', 'room-statistic-alert', String(attention)));
    summary.setAttribute('aria-label', `状态明细，${attention} 台待核实或未通电`);
  }
  details.append(summary, counts);
  statistics.append(totals, details);
  return statistics;
}

function floorPlan(room, layout, racksById, onRack) {
  const plan = element('section', 'room-overview-plan');
  const scroll = element('div', 'room-overview-plan-scroll');
  scroll.tabIndex = 0;
  scroll.setAttribute('role', 'region');
  scroll.setAttribute('aria-label', `${room.name}平面布置`);
  const grid = element('div', 'room-overview-grid');
  grid.style.setProperty('--room-columns', layout.columns);
  const positions = new Map(layout.positions.map((position) => [`${position.row}:${position.slot}`, position]));

  // 平面布局的第一排在画面近侧，与 3D 正俯视的排向一致。
  for (let row = layout.rows; row >= 1; row -= 1) {
    if (row !== layout.rows) grid.append(element('div', 'room-overview-aisle', '走道'));
    grid.append(element('span', 'room-overview-row-label', `第 ${row} 排`));
    for (let slot = 1; slot <= layout.columns; slot += 1) {
      const position = positions.get(`${row}:${slot}`);
      const rack = racksById.get(position?.rack_id);
      if (!rack) {
        const empty = element('span', 'room-overview-slot room-overview-slot-empty', layout.illustrative ? '预留' : '空位');
        empty.title = `第 ${row} 排第 ${slot} 位`;
        grid.append(empty);
        continue;
      }
      const [arrow, side] = FRONT_MARKERS[position.rotation];
      const link = cabinetLink(rack, onRack, 'room-overview-slot room-overview-slot-rack');
      link.dataset.rotation = position.rotation;
      link.setAttribute('aria-label', `${rack.name}，${rack.height}U，第 ${row} 排第 ${slot} 位，正面朝${side}`);
      const marker = element('span', 'room-overview-front', arrow);
      marker.setAttribute('aria-hidden', 'true');
      link.append(element('strong', '', rack.name), element('span', 'room-overview-rack-height', `${rack.height}U`), marker);
      grid.append(link);
    }
  }
  scroll.append(grid);
  plan.append(scroll, element('p', 'room-overview-plan-key', '箭头表示机柜正面'));
  return plan;
}

export function renderRoomOverview(host, {
  room, layout, floorProfile, racks, devices = [], systems = [], deviceKind, units, siteName, toolbar, disclosures,
  onRack, onDevice, onSceneInteraction, onClearDeviceSelection, onGlobalSearch, onCableSearch, onFindCable, view, switchingRoom = false,
}) {
  const racksById = new Map(racks.map((rack) => [rack.id, rack]));
  const positions = layout?.positions.filter((position) => racksById.has(position.rack_id)) ?? [];
  const placed = new Map(positions.map((position) => [position.rack_id, position]));
  const unplaced = racks.filter((rack) => !placed.has(rack.id));
  const roomDevices = devices.filter((device) => String(device.room_id) === String(room.id) && !isDeviceArchived(device));
  const rackNames = racks.map((rack) => ({ rack, key: normalize(rack.name) }));
  const searchDevices = buildDeviceSearch(roomDevices, systems);
  const overview = element('section', 'room-overview');
  const header = element('header', 'room-overview-header');
  const info = element('div', 'room-overview-summary');
  const context = element('div', 'room-overview-site');
  if (siteName && siteName !== room.name) context.append(element('span', '', siteName));
  if (layout?.illustrative) context.append(element('span', 'room-overview-illustrative', '示意布局'));
  if (context.childElementCount) info.append(context);
  const title = element('h1', '', room.name);
  title.id = 'room-overview-title';
  overview.setAttribute('aria-labelledby', title.id);
  info.append(title);
  const intro = element('div', 'room-overview-intro');
  intro.append(info);
  if (toolbar) intro.append(toolbar);
  header.append(intro);
  if (disclosures) header.append(disclosures);

  const actions = element('div', 'room-overview-actions');
  const search = element('form', 'room-overview-search');
  search.setAttribute('role', 'search');
  const searchInput = element('input');
  searchInput.type = 'search';
  searchInput.autocomplete = 'off';
  searchInput.maxLength = 160;
  searchInput.placeholder = '柜号、设备、型号、系统、IP、端口或线标';
  searchInput.setAttribute('aria-label', '查找机柜、设备、品牌型号、业务系统、IP、域名、端口或线标');
  const searchButton = element('button', 'button primary', '搜索');
  searchButton.type = 'submit';
  search.append(searchInput, searchButton);
  const clear = action('清除搜索', 'button small quiet', () => {
    clearSearch();
    searchButton.focus({ preventScroll: true });
  });
  clear.hidden = true;
  const reset = action('回到全览', 'button small quiet', clearLocation);
  reset.hidden = true;
  const lookup = element('div', 'room-overview-find');
  if (racks.length || roomDevices.length) lookup.append(search, clear, reset);
  if (onGlobalSearch) lookup.append(action('跨机房搜索', 'button small', () => onGlobalSearch(searchInput.value)));
  if (onCableSearch) lookup.append(action('线缆搜索', 'button small', () => onCableSearch(searchInput.value.trim())));
  const controls = element('div', 'room-overview-switch');
  controls.setAttribute('role', 'group');
  controls.setAttribute('aria-label', '机房布置视图');
  const threeButton = action('3D 总览', '', () => { void show3d(); });
  const planButton = action('平面布局', '', () => showPlan());
  controls.append(threeButton, planButton);
  if (positions.length || floorProfile) actions.append(controls);
  const summary = element('div', 'room-overview-viewbar');
  summary.append(roomStatistics(racks, roomDevices, positions.length ? layout.rows * layout.columns : 0));
  if (positions.length || floorProfile) summary.append(actions);
  const querybar = element('div', 'room-overview-querybar');
  if (lookup.children.length) querybar.append(lookup);
  querybar.append(summary);
  header.append(querybar);
  overview.append(header);
  const searchPanel = element('div', 'room-overview-search-panel');
  const searchStatus = element('p', 'room-overview-search-status');
  searchStatus.setAttribute('role', 'status');
  const searchResults = element('ul', 'room-overview-search-results');
  searchResults.setAttribute('aria-label', '搜索结果');
  searchResults.tabIndex = 0;
  searchPanel.append(searchStatus, searchResults);
  searchPanel.hidden = true;
  overview.append(searchPanel);

  const spatial = element('div', 'room-overview-render-host');
  const sceneLayout = layout ? { ...layout, positions } : { rows: 1, columns: 1, positions };
  const plan = floorProfile ? renderRoomProfilePlan(room, floorProfile, sceneLayout, racksById, onRack)
    : positions.length ? floorPlan(room, layout, racksById, onRack) : null;
  const notice = element('p', 'room-overview-status');
  notice.setAttribute('role', 'status');
  notice.hidden = true;
  if (plan) {
    overview.append(spatial, plan, notice);
    const shortcuts = element('details', 'room-overview-cabinet-shortcuts');
    shortcuts.append(element('summary', '', `已摆放机柜（${placed.size}）`), cabinetList(racks.filter((rack) => placed.has(rack.id)), onRack));
    overview.append(shortcuts);
  }
  if (unplaced.length) {
    const waiting = element('section', 'room-overview-unplaced');
    waiting.append(element('h3', '', '待摆放'), cabinetList(unplaced, onRack));
    overview.append(waiting);
  }
  if (!racks.length) overview.append(element('p', 'room-overview-empty', '这间机房还没有机柜。'));
  host.replaceChildren(overview);

  const savedView = view?.roomId === room.id ? view : undefined;
  let entry = switchingRoom ? 'switch' : savedView ? undefined : 'arrival';
  let camera = savedView?.camera;
  let locatedRack = placed.has(savedView?.locatedRackId) ? racksById.get(savedView.locatedRackId) : undefined;
  let locatedDevice = locatedRack && roomDevices.find((device) =>
    device.id === savedView?.locatedDeviceId && device.rack_id === locatedRack.id);
  let locatedFace = savedView?.locatedFace === 'rear' ? 'rear' : 'front';
  let focusOnMount = Boolean(savedView?.focusOnMount);
  let mode;
  let scene;
  let generation = 0;
  let disposed = false;
  let appliedQuery = '';
  let searchFilter = null;
  let results = { groups: [], unmounted: [], deviceCount: 0 };

  function matchRoom(term) {
    const groupsByRack = new Map();
    const unmounted = [];
    if (!term) return { groups: [], unmounted, deviceCount: 0 };
    for (const { rack, key } of rackNames) {
      if (key.includes(term)) groupsByRack.set(rack.id, { rack, direct: true, matches: [] });
    }
    const matches = searchDevices(term);
    for (const match of matches) {
      const rack = racksById.get(match.device.rack_id);
      if (!rack) {
        unmounted.push(match);
        continue;
      }
      if (!groupsByRack.has(rack.id)) groupsByRack.set(rack.id, { rack, direct: false, matches: [] });
      groupsByRack.get(rack.id).matches.push(match);
    }
    const groups = racks.map((rack) => groupsByRack.get(rack.id)).filter(Boolean);
    groups.sort((left, right) => Number(right.matches.some(({ exactAddress }) => exactAddress))
      - Number(left.matches.some(({ exactAddress }) => exactAddress)));
    return { groups, unmounted, deviceCount: matches.length };
  }

  function deviceLocationLabel(device) {
    return `${device.face === 'rear' ? '背面' : '正面'} ${units?.(device) ?? `U${device.u_start}`}`;
  }

  function deviceResults(matches, rack) {
    const list = element('ul', 'room-overview-search-devices');
    for (const { device, matchedModel, systems: names, entries, addresses } of matches) {
      const item = element('li', 'room-overview-search-device');
      item.dataset.deviceId = device.id;
      const deviceLink = element('a', 'room-overview-search-device-name', device.name);
      deviceLink.href = `#device/${device.id}`;
      const title = element('span', 'room-overview-search-device-main');
      title.append(deviceLink);
      if (device.code) title.append(element('span', 'code muted', device.code));
      const location = rack ? deviceLocationLabel(device)
        : (device.workstation ? `工位 ${device.workstation}` : '');
      const context = [location, matchedModel, names.length ? `业务系统 ${names.join('、')}` : ''].filter(Boolean).join(' · ');
      const info = element('div', 'room-overview-search-device-info');
      info.append(title);
      if (context) info.append(element('div', 'room-overview-search-device-meta', context));
      const endpoints = [...new Set(entries.map(endpointLabel).filter(Boolean))];
      const addressLabels = [...new Set(addresses.map(deviceAddressLabel).filter(Boolean))];
      if (endpoints.length) info.append(element('div', 'room-overview-search-device-meta', `入口 ${endpoints.join('、')}`));
      if (addressLabels.length) info.append(element('div', 'room-overview-search-device-meta', `设备地址 ${addressLabels.join('、')}`));
      item.append(info);
      if (placed.has(rack?.id)) {
        const locateButton = action('', 'room-overview-device-locate', () => locate(rack, device.face, device));
        const label = `定位 ${device.name}（${rack.name} ${location}）`;
        locateButton.title = label;
        locateButton.setAttribute('aria-label', label);
        locateButton.append(locateIcon());
        item.append(locateButton);
      }
      list.append(item);
    }
    return list;
  }

  function faceFor(group) {
    return group.matches.length && group.matches.every(({ device }) => device.face === 'rear') ? 'rear' : 'front';
  }

  function resultStatus(message) {
    const { groups, unmounted, deviceCount } = results;
    const hasMatches = groups.length || unmounted.length;
    const summary = hasMatches ? `找到 ${groups.length} 台机柜、${deviceCount} 台设备。` : '当前机房没有匹配的机柜或设备。';
    searchStatus.textContent = message ? `${message}${hasMatches ? ` · ${summary}` : ''}` : summary;
  }

  function deviceLocationStatus() {
    return `已定位 ${locatedDevice.name} · ${locatedRack.name} · ${deviceLocationLabel(locatedDevice)}`;
  }

  function markDeviceResult() {
    for (const button of searchResults.querySelectorAll('.room-overview-device-locate')) {
      const row = button.closest('.room-overview-search-device');
      const selected = row.dataset.deviceId === String(locatedDevice?.id);
      row.toggleAttribute('data-located', selected);
      button.setAttribute('aria-pressed', String(selected));
    }
  }

  function displayResults(message) {
    const { groups, unmounted } = results;
    const lines = [];
    for (const group of groups) {
      const { rack, matches } = group;
      const item = element('li', 'room-overview-search-group');
      item.dataset.rackId = rack.id;
      const head = element('div', 'room-overview-search-group-head');
      const title = cabinetLink(rack, onRack, 'room-overview-search-rack-name');
      title.textContent = rack.name;
      const position = placed.get(rack.id);
      head.append(title, element('span', 'room-overview-search-device-meta',
        position ? `第 ${position.row} 排第 ${position.slot} 位` : '待摆放'));
      if (position) {
        const locateButton = action('聚焦', 'button small', () => locate(rack, faceFor(group)));
        locateButton.setAttribute('aria-label', `聚焦 ${rack.name}`);
        head.append(locateButton);
      }
      item.append(head);
      if (matches.length) item.append(deviceResults(matches, rack));
      lines.push(item);
    }
    if (unmounted.length) {
      const item = element('li', 'room-overview-search-group room-overview-search-unmounted');
      item.append(element('h3', 'room-overview-search-group-head', '未上架设备'), deviceResults(unmounted));
      if (unmounted.some(({ exactAddress }) => exactAddress)) {
        const firstPrefix = groups.findIndex(({ matches }) => !matches.some(({ exactAddress }) => exactAddress));
        lines.splice(firstPrefix < 0 ? lines.length : firstPrefix, 0, item);
      } else lines.push(item);
    }
    resultStatus(message ?? (locatedDevice ? deviceLocationStatus() : undefined));
    searchResults.replaceChildren(...lines);
    markDeviceResult();
    searchPanel.hidden = false;
  }

  function applySearch(query) {
    appliedQuery = query.trim();
    const term = normalize(appliedQuery);
    results = matchRoom(term);
    const drawn = results.groups.filter(({ rack }) => placed.has(rack.id));
    searchFilter = drawn.length ? {
      rackIds: new Set(drawn.map(({ rack }) => String(rack.id))),
      directRackIds: new Set(drawn.filter(({ direct }) => direct).map(({ rack }) => String(rack.id))),
      deviceIds: new Set(drawn.flatMap(({ matches }) => matches.map(({ device }) => String(device.id)))),
    } : null;
    if (locatedDevice && !searchFilter?.deviceIds.has(String(locatedDevice.id))) {
      locatedDevice = undefined;
      scene?.clearLocatedDevice?.();
    }
    scene?.setSearchFilter?.(searchFilter);
    markPlan();
    clear.hidden = !term;
    if (term) displayResults();
    else {
      searchPanel.hidden = true;
      searchStatus.textContent = '';
      searchResults.replaceChildren();
    }
  }

  function markPlan() {
    if (!plan) return;
    for (const link of plan.querySelectorAll('.room-overview-slot-rack')) {
      if (searchFilter) {
        link.dataset.searchMatch = String(searchFilter.rackIds.has(link.dataset.rackId));
        link.dataset.searchDirect = String(searchFilter.directRackIds.has(link.dataset.rackId));
      } else {
        delete link.dataset.searchMatch;
        delete link.dataset.searchDirect;
      }
      const selected = locatedRack && link.dataset.rackId === String(locatedRack.id);
      if (selected) link.dataset.located = 'true';
      else delete link.dataset.located;
      if (!selected || plan.hidden) continue;
      const scroll = link.closest('.room-overview-plan-scroll');
      const box = link.getBoundingClientRect();
      const area = scroll.getBoundingClientRect();
      if (box.left < area.left || box.right > area.right) scroll.scrollLeft += (box.left + box.right - area.left - area.right) / 2;
      if (box.top < area.top || box.bottom > area.bottom) scroll.scrollTop += (box.top + box.bottom - area.top - area.bottom) / 2;
    }
  }

  function flyToLocation() {
    if (!locatedRack) return false;
    return locatedDevice
      ? scene?.locateDevice?.(locatedRack.id, locatedDevice.id)
      : scene?.locateRack?.(locatedRack.id, locatedFace);
  }

  function locate(rack, face = 'front', device) {
    const position = placed.get(rack.id);
    if (!position) return;
    locatedRack = rack;
    locatedFace = face;
    locatedDevice = device;
    resultStatus(device ? deviceLocationStatus() : `已定位 ${rack.name} · 第 ${position.row} 排第 ${position.slot} 位`);
    markDeviceResult();
    reset.hidden = false;
    focusOnMount = !flyToLocation();
    markPlan();
    if (device) {
      const target = mode === '3d' ? spatial : plan;
      const bounds = target?.getBoundingClientRect();
      if (bounds && (bounds.top > window.innerHeight - 96 || bounds.bottom < 96)) {
        target.scrollIntoView({ block: 'nearest' });
      }
    }
  }

  function clearSearch() {
    searchInput.value = '';
    applySearch('');
  }

  function clearLocation() {
    locatedRack = undefined;
    locatedDevice = undefined;
    focusOnMount = false;
    if (scene) scene.resetView?.();
    else camera = undefined;
    clearSearch();
    reset.hidden = true;
    searchButton.focus({ preventScroll: true });
  }

  search.addEventListener('submit', (event) => {
    event.preventDefault();
    const term = normalize(searchInput.value);
    if (!term) {
      displayResults('请输入柜号、设备编号、名称、品牌型号、业务系统、IP、域名或端口。');
      searchInput.focus({ preventScroll: true });
      return;
    }
    applySearch(searchInput.value);
    searchButton.focus({ preventScroll: true });
    const { groups, unmounted } = results;
    if (!groups.length && !unmounted.length) {
      const query = searchInput.value.trim();
      onFindCable?.(query, () => !disposed && searchInput.value.trim() === query && document.activeElement === searchButton);
      return;
    }
    const exactRacks = groups.filter(({ rack, direct }) => direct && normalize(rack.name) === term);
    if (exactRacks.length === 1) {
      locate(exactRacks[0].rack);
      return;
    }
    if (groups.length !== 1 || unmounted.length) return;
    const [group] = groups;
    if (group.matches.length <= 1) locate(group.rack, faceFor(group), group.matches[0]?.device);
  });
  searchInput.addEventListener('input', (event) => {
    if (!event.isComposing) applySearch(searchInput.value);
  });
  searchInput.addEventListener('compositionend', () => applySearch(searchInput.value));
  searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !event.isComposing && !searchPanel.hidden) {
      event.preventDefault();
      clearSearch();
    }
  });

  function show(modeToShow, message) {
    mode = modeToShow;
    const is3d = mode === '3d';
    threeButton.setAttribute('aria-pressed', String(is3d));
    planButton.setAttribute('aria-pressed', String(!is3d));
    spatial.hidden = !is3d;
    if (plan) plan.hidden = is3d;
    notice.textContent = message || '';
    notice.hidden = !message;
  }

  function showPlan(message) {
    generation += 1;
    onSceneInteraction?.();
    camera = scene?.snapshot?.() ?? camera;
    scene?.();
    scene = undefined;
    spatial.replaceChildren();
    show('2d', message);
    markPlan();
  }

  function fallback(ticket) {
    if (disposed || ticket !== generation) return;
    showPlan('3D 无法加载，已切换为平面布局。');
    threeButton.disabled = true;
  }

  async function show3d() {
    if (!plan || disposed || mode === '3d') return;
    const ticket = ++generation;
    show('3d', '正在加载 3D 总览…');
    try {
      const { mountRoomScene } = await import('./room-overview-3d.js');
      if (disposed || ticket !== generation) return;
      const mounted = mountRoomScene(spatial, {
        layout: sceneLayout, floorProfile, racks, devices: roomDevices, deviceKind, units, initialCamera: camera, onRack,
        roomName: room.name, siteName, entry: focusOnMount ? undefined : entry,
        initialLocatedRackId: locatedRack?.id, initialLocatedDeviceId: locatedDevice?.id,
        initialSearchFilter: searchFilter, onDevice, onSceneInteraction, onClearDeviceSelection,
        onFallback: () => fallback(ticket),
      });
      if (disposed || ticket !== generation) {
        mounted?.();
        return;
      }
      scene = mounted;
      entry = undefined;
      if (focusOnMount && flyToLocation()) focusOnMount = false;
      show('3d');
    } catch {
      fallback(ticket);
    }
  }

  if (locatedRack) reset.hidden = false;
  if (savedView?.searchQuery) {
    searchInput.value = savedView.searchQuery;
    applySearch(searchInput.value);
  }
  const ready = plan && savedView?.mode !== '2d' ? show3d() : Promise.resolve(show('2d'));
  markPlan();
  const dispose = () => {
    disposed = true;
    generation += 1;
    scene?.();
    scene = undefined;
  };
  const snapshot = () => ({
    roomId: room.id, mode: plan ? mode : undefined, camera: scene?.snapshot?.() ?? camera, locatedRackId: locatedRack?.id,
    searchQuery: appliedQuery, locatedFace, locatedDeviceId: locatedDevice?.id, focusOnMount,
  });
  const deviceAnchor = (id) => scene?.deviceAnchor?.(id) ?? null;
  return Object.assign(dispose, { ready, snapshot, deviceAnchor });
}
