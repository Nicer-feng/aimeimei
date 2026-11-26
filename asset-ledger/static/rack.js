const SVG_NS = 'http://www.w3.org/2000/svg';
const UNIT = 22;
const FRAME_TOP = 10;
const FACE_NAMES = { front: '正面', rear: '背面' };
const DEPTH_NAMES = { full: '全深', half: '半深', unknown: '深度待核' };
export const OPERATING_STATUS_LABELS = Object.freeze({
  unknown: '待核实', running: '运行中', disabled: '已停用', unpowered: '未通电',
});

export function operatingStatus(device) {
  const status = device?.operating_status;
  return Object.hasOwn(OPERATING_STATUS_LABELS, status) ? status : 'unknown';
}

export function operatingStatusLabel(device) {
  return OPERATING_STATUS_LABELS[operatingStatus(device)];
}

function element(tag, className, label) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (label) node.textContent = label;
  return node;
}

function svg(tag, attributes, label) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (label) node.textContent = label;
  return node;
}

export function deviceKind(device) {
  if (/交换|路由|防火墙|网关/.test(device.type)) return 'network';
  if (/配电|电源|UPS/i.test(device.type)) return 'power';
  if (/存储|磁盘/.test(device.type)) return 'storage';
  return 'server';
}

export function units(device) {
  const end = device.u_start + device.u_height - 1;
  return end === device.u_start ? `U${end}` : `U${device.u_start}–U${end}`;
}

function mountDepth(device) {
  if (device.mount_depth === 'full' || device.mount_depth === 'half') return device.mount_depth;
  return 'unknown';
}

function depthLabel(device) {
  return DEPTH_NAMES[mountDepth(device)];
}

function occupiedSlots(devices) {
  const slots = new Map();
  for (const device of devices) {
    for (let offset = 0; offset < device.u_height; offset += 1) {
      slots.set(device.u_start + offset, device);
    }
  }
  return slots;
}

function elevationDevice(device, { face, start, count, y, onDevice, crossing = false }) {
  const top = y(start + count - 1);
  const height = count * UNIT;
  const range = units({ u_start: start, u_height: count });
  const state = crossing ? '跨面占用' : depthLabel(device);
  const label = `${device.name}，${FACE_NAMES[face]} ${range}，${count}U，${state}`;
  const node = svg('g', {
    class: `rack-svg-device ${crossing ? 'rack-svg-cross-face' : `rack-kind-${deviceKind(device)}`}`,
    role: 'button', tabindex: 0, 'aria-label': label, 'aria-pressed': 'false', 'data-device-id': device.id,
    'data-u-height': count, 'data-u-start': start, 'data-mount-depth': mountDepth(device),
  });
  if (crossing) node.setAttribute('data-cross-face', 'true');
  node.append(svg('title', {}, label));
  node.append(svg('rect', { class: 'rack-svg-device-body', x: 41, y: top, width: 253, height }));
  node.append(svg('rect', { class: 'rack-svg-device-mark', x: 41, y: top + 1, width: 4, height: height - 2 }));
  const visibleName = Array.from(crossing ? `跨面占用 · ${device.name}` : device.name);
  const nameLimit = crossing ? 19 : 17;
  const name = visibleName.length > nameLimit ? `${visibleName.slice(0, nameLimit).join('')}…` : visibleName.join('');
  node.append(svg('text', { class: 'rack-svg-device-name', x: 50, y: top + height / 2 + 4 }, name));
  node.append(svg('text', { class: 'rack-svg-device-u', x: 285, y: top + height / 2 + 4 }, `${count}U`));
  node.addEventListener('click', () => onDevice(device, node));
  node.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onDevice(device, node);
    }
  });
  return node;
}

function elevation(rack, devices, face, onDevice, onEmpty) {
  const mounted = devices.filter((device) => device.face === face);
  const placements = occupiedSlots(mounted);
  const reservations = occupiedSlots(devices.filter((device) => device.face !== face && mountDepth(device) !== 'half'));
  // 已有同位设备以本面实际安装为准，跨面标识只覆盖空出的格。
  for (const unit of placements.keys()) reservations.delete(unit);
  const crossingSlots = [...reservations.values()].filter((device) => mountDepth(device) === 'full').length;
  const pending = reservations.size - crossingSlots;
  const occupied = placements.size + crossingSlots;
  const free = rack.height - occupied - pending;
  const side = element('section', 'rack-elevation');
  const caption = element('header', 'rack-elevation-caption');
  caption.append(element('h3', '', FACE_NAMES[face]));
  const counts = [`占用 ${occupied}U`, `空闲 ${free}U`];
  if (pending) counts.push(`深度待核 ${pending}U`);
  caption.append(element('span', 'rack-face-stat', counts.join(' · ')));
  side.append(caption);

  const height = rack.height * UNIT;
  const diagram = svg('svg', {
    class: 'rack-elevation-svg', viewBox: `0 0 308 ${height + 20}`,
    role: 'group', 'aria-label': `${rack.name} ${FACE_NAMES[face]}立面`, 'data-face': face,
  });
  const y = (unit) => FRAME_TOP + (rack.height - unit) * UNIT;
  diagram.append(svg('rect', { class: 'rack-svg-frame', x: 32, y: FRAME_TOP - 4, width: 271, height: height + 8, rx: 3 }));
  for (let unit = rack.height; unit > 0; unit -= 1) {
    const row = svg('g', { 'data-u': unit });
    row.append(svg('text', { class: 'rack-svg-scale', x: 26, y: y(unit) + 15 }, `U${unit}`));
    const device = reservations.get(unit);
    const blocked = device && mountDepth(device);
    const cell = svg('rect', { class: 'rack-svg-slot', x: 41, y: y(unit), width: 253, height: UNIT });
    row.append(cell);
    if (blocked) {
      row.setAttribute('data-blocked', blocked);
      if (blocked === 'unknown') {
        row.append(svg('title', {}, `${FACE_NAMES[face]} U${unit} 对面深度待核 · ${device.name}`));
        row.append(svg('text', { class: 'rack-svg-pending-label', x: 50, y: y(unit) + 15 }, '对面深度待核'));
      }
    } else if (!placements.has(unit)) {
      row.setAttribute('data-empty', 'true');
      row.append(svg('title', {}, `${FACE_NAMES[face]} U${unit} 空位`));
      if (onEmpty) {
        row.classList.add('rack-slot-selectable');
        cell.addEventListener('click', () => onEmpty({ face, u_start: unit }));
      }
    }
    row.append(svg('circle', { class: 'rack-svg-screw', cx: 36.5, cy: y(unit) + UNIT / 2, r: 1.1 }));
    row.append(svg('circle', { class: 'rack-svg-screw', cx: 298.5, cy: y(unit) + UNIT / 2, r: 1.1 }));
    diagram.append(row);
  }
  for (let unit = rack.height; unit > 0; unit -= 1) {
    const device = reservations.get(unit);
    if (!device || mountDepth(device) !== 'full') continue;
    const end = unit;
    while (reservations.get(unit - 1) === device) unit -= 1;
    diagram.append(elevationDevice(device, { face, start: unit, count: end - unit + 1, y, onDevice, crossing: true }));
  }
  for (const device of mounted) {
    diagram.append(elevationDevice(device, { face, start: device.u_start, count: device.u_height, y, onDevice }));
  }
  side.append(diagram);
  return side;
}

export function renderRack(host, { rack, devices, onDevice, onEmpty, view, initialDeviceId, onSceneInteraction }) {
  const viewBar = element('div', 'rack-view-bar');
  const modes = element('div', 'rack-mode-switch');
  modes.setAttribute('role', 'group');
  modes.setAttribute('aria-label', '机柜视图');
  const buttons = ['2D 立面', '3D 机柜'].map((label) => element('button', 'rack-mode-button', label));
  for (const button of buttons) {
    button.type = 'button';
    modes.append(button);
  }
  const status = element('span', 'rack-view-status');
  status.setAttribute('role', 'status');
  viewBar.append(modes, status);
  const chart = element('div', 'rack-2d');
  for (const face of Object.keys(FACE_NAMES)) {
    chart.append(elevation(rack, devices, face, (device, node) => onDevice(device, svgAnchor(device.id, node)), onEmpty));
  }
  const deviceNodes = [...chart.querySelectorAll('g[data-device-id]')];
  const spatial = element('div', 'rack-3d');
  spatial.hidden = true;
  host.replaceChildren(viewBar, chart, spatial);

  let generation = 0;
  let scene;
  let removed = false;
  const wantedDeviceId = initialDeviceId ?? (view?.rackId === rack.id ? view.selectedDeviceId : null);
  let selectedDeviceId = devices.some((device) => device.id === wantedDeviceId) ? wantedDeviceId : null;

  function updateElevationSelection() {
    for (const node of deviceNodes) {
      node.setAttribute('aria-pressed', String(node.dataset.deviceId === String(selectedDeviceId)));
    }
  }

  function bindSelection(deviceId, anchor) {
    return {
      ...anchor,
      setSelected(selected) {
        if (removed || (!selected && selectedDeviceId !== deviceId)) return;
        const next = selected ? deviceId : null;
        if (next === selectedDeviceId) return;
        selectedDeviceId = next;
        updateElevationSelection();
        scene?.setSelectedDevice?.(next);
      },
    };
  }

  function svgAnchor(deviceId, node) {
    const frame = node.ownerSVGElement?.querySelector('.rack-svg-frame');
    const neighbor = [...chart.querySelectorAll('.rack-svg-frame')].find((item) => item !== frame);
    return bindSelection(deviceId, {
      element: node,
      cabinetRect: () => frame?.getBoundingClientRect(),
      neighborCabinetRect: () => neighbor?.getBoundingClientRect(),
      visible: () => node.isConnected && !chart.hidden && node.getClientRects().length > 0,
    });
  }

  function deviceAnchor(deviceId) {
    if (removed) return null;
    if (!spatial.hidden) {
      const anchor = scene?.deviceAnchor?.(deviceId);
      return anchor ? bindSelection(deviceId, anchor) : null;
    }
    const matches = deviceNodes.filter((node) => node.dataset.deviceId === String(deviceId));
    const node = matches.find((item) => !item.hasAttribute('data-cross-face')) ?? matches[0];
    return node ? svgAnchor(deviceId, node) : null;
  }

  updateElevationSelection();

  function activate(mode) {
    chart.hidden = mode !== '2d';
    spatial.hidden = mode !== '3d';
    buttons[0].setAttribute('aria-pressed', String(mode === '2d'));
    buttons[1].setAttribute('aria-pressed', String(mode === '3d'));
  }

  function clearScene() {
    generation += 1;
    scene?.();
    scene = undefined;
    spatial.replaceChildren();
  }

  function showElevation(message = '') {
    clearScene();
    activate('2d');
    status.textContent = message;
  }

  async function showScene(initialCamera) {
    if (removed || !spatial.hidden) return;
    const request = ++generation;
    activate('3d');
    status.textContent = '加载 3D 视图…';
    try {
      const { mountRackScene } = await import('./rack-3d.js');
      if (removed || request !== generation) return;
      scene = mountRackScene(spatial, {
        rack, devices, deviceKind, units, depthLabel, initialCamera,
        initialDeviceId: selectedDeviceId, onSceneInteraction,
        onDevice: (device, anchor) => onDevice(device, anchor ? bindSelection(device.id, anchor) : undefined),
        onContextLost: () => showElevation('3D 已断开，已返回立面。'),
      });
      status.textContent = '';
    } catch {
      if (!removed && request === generation) showElevation('当前浏览器无法使用 3D，已返回立面。');
    }
  }

  buttons[0].addEventListener('click', () => {
    if (spatial.hidden) return;
    onSceneInteraction?.();
    showElevation();
  });
  buttons[1].addEventListener('click', () => {
    if (!spatial.hidden) return;
    onSceneInteraction?.();
    void showScene();
  });
  const restoreScene = view?.rackId === rack.id && view.mode === '3d';
  const ready = restoreScene ? showScene(view.camera) : undefined;
  if (!restoreScene) activate('2d');
  const dispose = () => {
    removed = true;
    clearScene();
  };
  const snapshot = () => ({
    rackId: rack.id, mode: spatial.hidden ? '2d' : '3d', camera: scene?.snapshot?.(), selectedDeviceId,
  });
  return Object.assign(dispose, { ready, snapshot, deviceAnchor });
}
