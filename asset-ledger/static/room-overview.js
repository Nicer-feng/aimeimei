const FRONT_MARKERS = {
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
  room, layout, racks, devices = [], systems = [], deviceKind, units, onRack, onDevice, onSceneInteraction, onEdit, view,
}) {
  const racksById = new Map(racks.map((rack) => [rack.id, rack]));
  const positions = layout?.positions.filter((position) => racksById.has(position.rack_id)) ?? [];
  const placed = new Map(positions.map((position) => [position.rack_id, position]));
  const unplaced = racks.filter((rack) => !placed.has(rack.id));
  const roomDevices = devices.filter((device) => String(device.room_id) === String(room.id));
  const scopeIds = new Set(roomDevices.map((device) => String(device.id)));
  const systemNames = new Map();
  const normalize = (value) => String(value ?? '').trim().normalize('NFKC').toLocaleLowerCase();
  for (const system of systems) {
    const name = { text: system.name, key: normalize(system.name) };
    for (const deployment of system.deployments ?? []) {
      const id = String(deployment.device_id);
      if (!scopeIds.has(id)) continue;
      if (!systemNames.has(id)) systemNames.set(id, []);
      systemNames.get(id).push(name);
    }
  }
  const rackNames = racks.map((rack) => ({ rack, key: normalize(rack.name) }));
  const deviceNames = roomDevices.map((device) => ({
    device, name: normalize(device.name), code: normalize(device.code), systems: systemNames.get(String(device.id)) ?? [],
  }));
  const overview = element('section', 'room-overview');
  const header = element('header', 'room-overview-header');
  const info = element('div', 'room-overview-summary');
  const title = element('h2', '', room.name);
  title.id = 'room-overview-title';
  overview.setAttribute('aria-labelledby', title.id);
  const titleLine = element('div', 'room-overview-title-line');
  titleLine.append(title);
  if (layout?.illustrative) titleLine.append(element('span', 'room-overview-illustrative', '示意布局'));
  const summary = [`${racks.length} 台机柜`];
  if (positions.length) summary.push(`${layout.rows * layout.columns} 个柜位`);
  info.append(titleLine, element('p', 'room-overview-count', summary.join(' · ')));

  const actions = element('div', 'room-overview-actions');
  const search = element('form', 'room-overview-search');
  search.setAttribute('role', 'search');
  const searchInput = element('input');
  searchInput.type = 'search';
  searchInput.autocomplete = 'off';
  searchInput.maxLength = 160;
  searchInput.placeholder = '柜号、设备或业务系统';
  searchInput.setAttribute('aria-label', '查找机柜、设备或业务系统');
  const searchButton = element('button', 'button small', '搜索');
  searchButton.type = 'submit';
  search.append(searchInput, searchButton);
  const clear = action('清除搜索', 'button small quiet', () => {
    clearSearch();
    searchButton.focus({ preventScroll: true });
  });
  clear.hidden = true;
  const reset = action('回到全览', 'button small quiet', clearLocation);
  reset.hidden = true;
  if (racks.length || roomDevices.length) actions.append(search, clear, reset);
  const controls = element('div', 'room-overview-switch');
  controls.setAttribute('role', 'group');
  controls.setAttribute('aria-label', '机房布置视图');
  const threeButton = action('3D 总览', '', () => { void show3d(); });
  const planButton = action('平面布局', '', () => showPlan());
  controls.append(threeButton, planButton);
  if (positions.length) actions.append(controls);
  if (onEdit) actions.append(action('编辑布置', 'button', onEdit));
  header.append(info, actions);
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
  const plan = positions.length ? floorPlan(room, layout, racksById, onRack) : null;
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
  let camera = savedView?.camera;
  let locatedRack = placed.has(savedView?.locatedRackId) ? racksById.get(savedView.locatedRackId) : undefined;
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
    let deviceCount = 0;
    for (const item of deviceNames) {
      const names = item.systems.filter((system) => system.key.includes(term)).map((system) => system.text);
      if (!item.name.includes(term) && !item.code.includes(term) && !names.length) continue;
      deviceCount += 1;
      const match = { device: item.device, systems: [...new Set(names)] };
      const rack = racksById.get(item.device.rack_id);
      if (!rack) {
        unmounted.push(match);
        continue;
      }
      if (!groupsByRack.has(rack.id)) groupsByRack.set(rack.id, { rack, direct: false, matches: [] });
      groupsByRack.get(rack.id).matches.push(match);
    }
    const groups = racks.map((rack) => groupsByRack.get(rack.id)).filter(Boolean);
    return { groups, unmounted, deviceCount };
  }

  function deviceResults(matches, mounted) {
    const list = element('ul', 'room-overview-search-devices');
    for (const { device, systems: names } of matches) {
      const item = element('li', 'room-overview-search-device');
      item.dataset.deviceId = device.id;
      const deviceLink = element('a', 'room-overview-search-device-name', device.name);
      deviceLink.href = `#device/${device.id}`;
      const title = element('span', 'room-overview-search-device-main');
      title.append(deviceLink);
      if (device.code) title.append(element('span', 'code muted', device.code));
      const location = mounted ? `${device.face === 'rear' ? '背面' : '正面'} ${units?.(device) ?? `U${device.u_start}`}`
        : (device.workstation ? `工位 ${device.workstation}` : '');
      const context = [location, names.length ? `业务系统 ${names.join('、')}` : ''].filter(Boolean).join(' · ');
      item.append(title);
      if (context) item.append(element('span', 'room-overview-search-device-meta', context));
      list.append(item);
    }
    return list;
  }

  function faceFor(group) {
    return group.matches.length && group.matches.every(({ device }) => device.face === 'rear') ? 'rear' : 'front';
  }

  function displayResults(message) {
    const { groups, unmounted, deviceCount } = results;
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
      if (matches.length) item.append(deviceResults(matches, true));
      lines.push(item);
    }
    if (unmounted.length) {
      const item = element('li', 'room-overview-search-group room-overview-search-unmounted');
      item.append(element('h3', 'room-overview-search-group-head', '未上架设备'), deviceResults(unmounted, false));
      lines.push(item);
    }
    const summary = lines.length ? `找到 ${groups.length} 台机柜、${deviceCount} 台设备。` : '当前机房没有匹配的机柜或设备。';
    searchStatus.textContent = message ? `${message}${lines.length ? ` · ${summary}` : ''}` : summary;
    searchResults.replaceChildren(...lines);
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

  function locate(rack, face = 'front') {
    const position = placed.get(rack.id);
    if (!position) return;
    locatedRack = rack;
    locatedFace = face;
    displayResults(`已定位 ${rack.name} · 第 ${position.row} 排第 ${position.slot} 位`);
    reset.hidden = false;
    focusOnMount = !scene?.locateRack?.(rack.id, face);
    markPlan();
    searchButton.focus({ preventScroll: true });
  }

  function clearSearch() {
    searchInput.value = '';
    applySearch('');
  }

  function clearLocation() {
    locatedRack = undefined;
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
      displayResults('请输入柜号、设备编号、设备名称或业务系统名称。');
      searchInput.focus({ preventScroll: true });
      return;
    }
    applySearch(searchInput.value);
    searchButton.focus({ preventScroll: true });
    const { groups, unmounted } = results;
    const exactRacks = groups.filter(({ rack, direct }) => direct && normalize(rack.name) === term);
    if (exactRacks.length === 1) {
      locate(exactRacks[0].rack);
      return;
    }
    if (groups.length !== 1 || unmounted.length) return;
    const [group] = groups;
    if (group.matches.length <= 1) locate(group.rack, faceFor(group));
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
        layout: { ...layout, positions }, racks, devices: roomDevices, deviceKind, units, initialCamera: camera, onRack,
        initialLocatedRackId: locatedRack?.id, initialSearchFilter: searchFilter, onDevice, onSceneInteraction,
        onFallback: () => fallback(ticket),
      });
      if (disposed || ticket !== generation) {
        mounted?.();
        return;
      }
      scene = mounted;
      if (focusOnMount && locatedRack && scene.locateRack?.(locatedRack.id, locatedFace)) focusOnMount = false;
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
    searchQuery: appliedQuery, locatedFace, focusOnMount,
  });
  const deviceAnchor = (id) => scene?.deviceAnchor?.(id) ?? null;
  return Object.assign(dispose, { ready, snapshot, deviceAnchor });
}
