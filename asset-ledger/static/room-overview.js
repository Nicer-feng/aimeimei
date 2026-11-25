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

export function renderRoomOverview(host, { room, layout, racks, onRack, onEdit, view }) {
  const racksById = new Map(racks.map((rack) => [rack.id, rack]));
  const positions = layout?.positions.filter((position) => racksById.has(position.rack_id)) ?? [];
  const placed = new Set(positions.map((position) => position.rack_id));
  const unplaced = racks.filter((rack) => !placed.has(rack.id));
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
  let mode;
  let scene;
  let generation = 0;
  let disposed = false;

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
    camera = scene?.snapshot?.() ?? camera;
    scene?.();
    scene = undefined;
    spatial.replaceChildren();
    show('2d', message);
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
      const mounted = mountRoomScene(spatial, { layout: { ...layout, positions }, racks, initialCamera: camera, onRack,
        onFallback: () => fallback(ticket) });
      if (disposed || ticket !== generation) {
        mounted?.();
        return;
      }
      scene = mounted;
      show('3d');
    } catch {
      fallback(ticket);
    }
  }

  const ready = plan && savedView?.mode !== '2d' ? show3d() : Promise.resolve(show('2d'));
  const dispose = () => {
    disposed = true;
    generation += 1;
    scene?.();
    scene = undefined;
  };
  const snapshot = () => ({ roomId: room.id, mode: plan ? mode : undefined, camera: scene?.snapshot?.() ?? camera });
  return Object.assign(dispose, { ready, snapshot });
}
