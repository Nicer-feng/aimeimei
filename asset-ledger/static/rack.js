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
  const type = device.type ?? '';
  if (/存储|磁盘|磁带|storage|\bNAS\b|\bSAN\b/i.test(type)) return 'storage';
  if (/服务器|\bserver\b/i.test(type)) return 'server';
  if (/交换|路由|防火墙|网关|switch|router|firewall|gateway/i.test(type)) return 'network';
  if (/配电|电源|\bUPS\b|\bPDU\b/i.test(type)) return 'power';
  return 'generic';
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

export function rackFaceSlots(rack, devices, excludeDeviceId) {
  const included = excludeDeviceId == null ? devices : devices.filter((device) => device.id !== excludeDeviceId);
  const front = occupiedSlots(included.filter((device) => device.face === 'front'));
  const rear = occupiedSlots(included.filter((device) => device.face === 'rear'));
  const oppositeKinds = { full: 'cross-face', half: 'half-only', unknown: 'unknown' };
  function build(face, own, opposite) {
    const slots = new Map();
    for (let u_start = 1; u_start <= rack.height; u_start += 1) {
      const mounted = own.get(u_start);
      const behind = opposite.get(u_start);
      const kind = mounted ? 'occupied' : behind ? oppositeKinds[mountDepth(behind)] : 'free';
      slots.set(u_start, { face, u_start, kind, device: mounted ?? behind });
    }
    return slots;
  }
  return { front: build('front', front, rear), rear: build('rear', rear, front) };
}

export function isSelectableRackSlot(slot) {
  return slot?.kind === 'free' || slot?.kind === 'half-only';
}

export function rackSlotSelection({ face, u_start, kind }) {
  return { face, u_start, ...(kind === 'half-only' ? { requiresHalf: true } : {}) };
}

function svgButton(node, activate) {
  node.addEventListener('click', activate);
  node.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activate();
    }
  });
}

function elevationDevice(device, { face, start, count, y, onDevice, crossing = false }) {
  const top = y(start + count - 1);
  const height = count * UNIT;
  const range = units({ u_start: start, u_height: count });
  const state = crossing ? '跨面占用' : depthLabel(device);
  const status = operatingStatus(device);
  const label = `${device.name}，${FACE_NAMES[face]} ${range}，${count}U，${state}，${OPERATING_STATUS_LABELS[status]}`;
  const node = svg('g', {
    class: `rack-svg-device ${crossing ? 'rack-svg-cross-face' : `rack-kind-${deviceKind(device)}`}`,
    role: 'button', tabindex: 0, 'aria-label': label, 'aria-pressed': 'false', 'data-device-id': device.id,
    'data-u-height': count, 'data-u-start': start, 'data-mount-depth': mountDepth(device),
    'data-operating-status': status,
  });
  if (crossing) node.setAttribute('data-cross-face', 'true');
  node.append(svg('title', {}, label));
  node.append(svg('rect', { class: 'rack-svg-device-body', x: 41, y: top, width: 253, height }));
  node.append(svg('rect', { class: 'rack-svg-device-mark', x: 41, y: top + 1, width: 4, height: height - 2 }));
  const visibleName = Array.from(crossing ? `跨面占用 · ${device.name}` : device.name);
  const nameLimit = crossing ? 19 : 13;
  const name = visibleName.length > nameLimit ? `${visibleName.slice(0, nameLimit).join('')}…` : visibleName.join('');
  const mid = top + height / 2;
  node.append(svg('text', { class: 'rack-svg-device-name', x: 50, y: mid + 4 }, name));
  if (!crossing) {
    node.append(svg('rect', { class: 'rack-svg-status-badge', x: 215, y: mid - 7, width: 41, height: 14, rx: 3 }));
    node.append(svg('text', { class: 'rack-svg-status-text', x: 235.5, y: mid + 3.1 }, OPERATING_STATUS_LABELS[status]));
  }
  node.append(svg('circle', { class: 'rack-svg-status', cx: 262, cy: mid, r: 3, 'aria-hidden': 'true' }));
  node.append(svg('text', { class: 'rack-svg-device-u', x: 285, y: mid + 4 }, `${count}U`));
  svgButton(node, () => onDevice(device, node));
  return node;
}

function elevation(rack, devices, slots, face, onDevice, onEmpty) {
  const totals = { occupied: 0, 'cross-face': 0, free: 0, 'half-only': 0, unknown: 0 };
  for (const slot of slots.values()) totals[slot.kind] += 1;
  const side = element('section', 'rack-elevation');
  const caption = element('header', 'rack-elevation-caption');
  caption.append(element('h3', '', FACE_NAMES[face]));
  const counts = [`占用 ${totals.occupied + totals['cross-face']}U`, `空闲 ${totals.free}U`];
  if (totals['half-only']) counts.push(`限半深 ${totals['half-only']}U`);
  if (totals.unknown) counts.push(`深度待核 ${totals.unknown}U`);
  caption.append(element('span', 'rack-face-stat', counts.join(' · ')));
  side.append(caption);

  const height = rack.height * UNIT;
  const diagram = svg('svg', {
    class: 'rack-elevation-svg', viewBox: `0 0 308 ${height + 20}`,
    role: 'group', 'aria-label': `${rack.name} ${FACE_NAMES[face]}立面`, 'data-face': face,
  });
  const y = (unit) => FRAME_TOP + (rack.height - unit) * UNIT;
  diagram.append(svg('rect', { class: 'rack-svg-frame', x: 32, y: FRAME_TOP - 4, width: 271, height: height + 8, rx: 3 }));
  for (const [side, x] of [['left', 33], ['right', 295]]) {
    diagram.append(svg('rect', { class: `rack-svg-rail rack-svg-rail-${side}`, x, y: FRAME_TOP - 2, width: 7, height: height + 4, rx: 1 }));
  }
  for (let unit = rack.height; unit > 0; unit -= 1) {
    const slot = slots.get(unit);
    const row = svg('g', { 'data-u': unit, 'data-slot-state': slot.kind, 'data-parity': unit % 2 ? 'odd' : 'even' });
    row.append(svg('text', { class: 'rack-svg-scale', x: 26, y: y(unit) + 15 }, `U${unit}`));
    row.append(svg('rect', { class: 'rack-svg-slot', x: 41, y: y(unit), width: 253, height: UNIT }));
    if (slot.kind === 'cross-face') row.setAttribute('data-blocked', 'full');
    if (slot.kind === 'unknown') {
      row.setAttribute('data-blocked', 'unknown');
      row.append(svg('title', {}, `${FACE_NAMES[face]} U${unit} 对面深度待核 · ${slot.device.name}`));
      row.append(svg('text', { class: 'rack-svg-pending-label', x: 50, y: y(unit) + 15 }, '对面深度待核'));
    }
    if (isSelectableRackSlot(slot)) {
      row.setAttribute('data-empty', 'true');
      const half = slot.kind === 'half-only';
      const label = `${FACE_NAMES[face]} U${unit} ${half ? '限半深' : '空位'}`;
      row.append(svg('title', {}, label));
      if (half) row.append(svg('text', { class: 'rack-svg-half-label', x: 50, y: y(unit) + 15 }, '限半深'));
      if (onEmpty) {
        row.classList.add('rack-slot-selectable');
        row.setAttribute('role', 'button');
        row.setAttribute('tabindex', '0');
        row.setAttribute('aria-label', `${label}，在此新增`);
        svgButton(row, () => onEmpty(rackSlotSelection(slot)));
      }
    }
    row.append(svg('circle', { class: 'rack-svg-screw', cx: 36.5, cy: y(unit) + UNIT / 2, r: 1.1 }));
    row.append(svg('circle', { class: 'rack-svg-screw', cx: 298.5, cy: y(unit) + UNIT / 2, r: 1.1 }));
    diagram.append(row);
  }
  for (let unit = rack.height; unit > 0; unit -= 1) {
    const slot = slots.get(unit);
    if (slot.kind !== 'cross-face') continue;
    const end = unit;
    while (slots.get(unit - 1)?.kind === 'cross-face' && slots.get(unit - 1).device === slot.device) unit -= 1;
    diagram.append(elevationDevice(slot.device, { face, start: unit, count: end - unit + 1, y, onDevice, crossing: true }));
  }
  for (const device of devices.filter((item) => item.face === face)) {
    diagram.append(elevationDevice(device, { face, start: device.u_start, count: device.u_height, y, onDevice }));
  }
  side.append(diagram);
  return side;
}

function statusLegend() {
  const legend = element('ul', 'rack-status-legend');
  legend.setAttribute('aria-label', '运行状态图例');
  for (const status of ['running', 'unpowered', 'disabled', 'unknown']) {
    const item = element('li', 'rack-status-legend-item', OPERATING_STATUS_LABELS[status]);
    item.dataset.operatingStatus = status;
    legend.append(item);
  }
  return legend;
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
  const faceSlots = rackFaceSlots(rack, devices);
  chart.append(statusLegend());
  for (const face of Object.keys(FACE_NAMES)) {
    chart.append(elevation(rack, devices, faceSlots[face], face, (device, node) => onDevice(device, svgAnchor(device.id, node)), onEmpty));
  }
  const deviceNodes = [...chart.querySelectorAll('g[data-device-id]')];
  const spatial = element('div', 'rack-3d');
  spatial.hidden = true;
  host.replaceChildren(viewBar, chart, spatial);

  const sameRackView = view?.rackId === rack.id ? view : undefined;
  let lastCamera = sameRackView?.camera;
  let pendingDeviceId = initialDeviceId;
  let generation = 0;
  let scene;
  let removed = false;
  const wantedDeviceId = initialDeviceId ?? sameRackView?.selectedDeviceId;
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

  async function showScene() {
    if (removed || !spatial.hidden) return;
    const request = ++generation;
    activate('3d');
    status.textContent = '加载 3D 视图…';
    try {
      const { mountRackScene } = await import('./rack-3d.js');
      if (removed || request !== generation) return;
      scene = mountRackScene(spatial, {
        rack, devices, deviceKind, units, depthLabel, initialCamera: lastCamera, faceSlots, onEmpty,
        initialDeviceId: selectedDeviceId, onSceneInteraction,
        onDevice: (device, anchor) => onDevice(device, anchor ? bindSelection(device.id, anchor) : undefined),
        onContextLost: () => showElevation('3D 已断开，已返回立面。'),
      });
      if (lastCamera && pendingDeviceId != null && selectedDeviceId === pendingDeviceId) {
        scene.focusDevice?.(pendingDeviceId);
      }
      pendingDeviceId = undefined;
      status.textContent = '';
    } catch {
      if (!removed && request === generation) showElevation('当前浏览器无法使用 3D，已返回立面。');
    }
  }

  buttons[0].addEventListener('click', () => {
    if (spatial.hidden) return;
    lastCamera = scene?.snapshot?.() ?? lastCamera;
    onSceneInteraction?.();
    showElevation();
  });
  buttons[1].addEventListener('click', () => {
    if (!spatial.hidden) return;
    onSceneInteraction?.();
    void showScene();
  });
  const restoreScene = sameRackView?.mode === '3d';
  const ready = restoreScene ? showScene() : undefined;
  if (!restoreScene) activate('2d');
  const dispose = () => {
    removed = true;
    clearScene();
  };
  const snapshot = () => ({
    rackId: rack.id, mode: spatial.hidden ? '2d' : '3d', camera: scene?.snapshot?.() ?? lastCamera, selectedDeviceId,
  });
  return Object.assign(dispose, { ready, snapshot, deviceAnchor });
}
