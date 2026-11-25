const SVG_NS = 'http://www.w3.org/2000/svg';
const UNIT = 22;
const FRAME_TOP = 10;
const FACE_NAMES = { front: '正面', rear: '背面' };

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

function deviceKind(device) {
  if (/交换|路由|防火墙|网关/.test(device.type)) return 'network';
  if (/配电|电源|UPS/i.test(device.type)) return 'power';
  if (/存储|磁盘/.test(device.type)) return 'storage';
  return 'server';
}

function units(device) {
  const end = device.u_start + device.u_height - 1;
  return end === device.u_start ? `U${end}` : `U${device.u_start}–U${end}`;
}

function elevation(rack, devices, face, onDevice, onEmpty) {
  const side = element('section', 'rack-elevation');
  const caption = element('header', 'rack-elevation-caption');
  caption.append(element('h3', '', FACE_NAMES[face]));
  const occupied = devices.reduce((count, device) => count + device.u_height, 0);
  caption.append(element('span', 'rack-face-stat', `占用 ${occupied}U · 空闲 ${rack.height - occupied}U`));
  side.append(caption);

  const height = rack.height * UNIT;
  const diagram = svg('svg', {
    class: 'rack-elevation-svg', viewBox: `0 0 308 ${height + 20}`,
    role: 'group', 'aria-label': `${rack.name} ${FACE_NAMES[face]}立面`, 'data-face': face,
  });
  const y = (unit) => FRAME_TOP + (rack.height - unit) * UNIT;
  const placements = new Set(devices.flatMap((device) => (
    Array.from({ length: device.u_height }, (_, offset) => device.u_start + offset)
  )));
  diagram.append(svg('rect', { class: 'rack-svg-frame', x: 32, y: FRAME_TOP - 4, width: 271, height: height + 8, rx: 3 }));
  for (let unit = rack.height; unit > 0; unit -= 1) {
    const row = svg('g', { 'data-u': unit });
    row.append(svg('text', { class: 'rack-svg-scale', x: 26, y: y(unit) + 15 }, `U${unit}`));
    const empty = !placements.has(unit);
    const cell = svg('rect', { class: 'rack-svg-slot', x: 41, y: y(unit), width: 253, height: UNIT });
    if (empty) {
      row.setAttribute('data-empty', 'true');
      row.append(svg('title', {}, `${FACE_NAMES[face]} U${unit} 空位`));
      if (onEmpty) {
        row.classList.add('rack-slot-selectable');
        cell.addEventListener('click', () => onEmpty({ face, u_start: unit }));
      }
    }
    row.append(cell);
    row.append(svg('circle', { class: 'rack-svg-screw', cx: 36.5, cy: y(unit) + UNIT / 2, r: 1.1 }));
    row.append(svg('circle', { class: 'rack-svg-screw', cx: 298.5, cy: y(unit) + UNIT / 2, r: 1.1 }));
    diagram.append(row);
  }
  for (const device of devices) {
    const top = y(device.u_start + device.u_height - 1);
    const depth = device.u_height * UNIT;
    const label = `${device.name}，${FACE_NAMES[face]} ${units(device)}，${device.u_height}U`;
    const deviceNode = svg('g', {
      class: `rack-svg-device rack-kind-${deviceKind(device)}`, role: 'button', tabindex: 0,
      'aria-label': label, 'data-device-id': device.id, 'data-u-height': device.u_height,
      'data-u-start': device.u_start,
    });
    deviceNode.append(svg('title', {}, label));
    deviceNode.append(svg('rect', { class: 'rack-svg-device-body', x: 41, y: top, width: 253, height: depth }));
    deviceNode.append(svg('rect', { class: 'rack-svg-device-mark', x: 41, y: top + 1, width: 4, height: depth - 2 }));
    const visibleName = Array.from(device.name);
    const name = visibleName.length > 17 ? `${visibleName.slice(0, 17).join('')}…` : device.name;
    deviceNode.append(svg('text', { class: 'rack-svg-device-name', x: 50, y: top + depth / 2 + 4 }, name));
    deviceNode.append(svg('text', { class: 'rack-svg-device-u', x: 285, y: top + depth / 2 + 4 }, `${device.u_height}U`));
    deviceNode.addEventListener('click', () => onDevice(device));
    deviceNode.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onDevice(device);
      }
    });
    diagram.append(deviceNode);
  }
  side.append(diagram);
  return side;
}

export function renderRack(host, { rack, devices, onDevice, onEmpty }) {
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
    chart.append(elevation(rack, devices.filter((device) => device.face === face), face, onDevice, onEmpty));
  }
  const spatial = element('div', 'rack-3d');
  spatial.hidden = true;
  host.replaceChildren(viewBar, chart, spatial);

  let generation = 0;
  let disposeScene;
  let removed = false;
  function activate(mode) {
    chart.hidden = mode !== '2d';
    spatial.hidden = mode !== '3d';
    buttons[0].setAttribute('aria-pressed', String(mode === '2d'));
    buttons[1].setAttribute('aria-pressed', String(mode === '3d'));
  }

  function showElevation(message = '') {
    generation += 1;
    disposeScene?.();
    disposeScene = undefined;
    spatial.replaceChildren();
    activate('2d');
    status.textContent = message;
  }

  async function showScene() {
    if (!spatial.hidden) return;
    const request = ++generation;
    activate('3d');
    status.textContent = '加载 3D 视图…';
    try {
      const { mountRackScene } = await import('./rack-3d.js');
      if (removed || request !== generation) return;
      disposeScene = mountRackScene(spatial, {
        rack, devices, onDevice, deviceKind, units,
        onContextLost: () => showElevation('3D 已断开，已返回立面。'),
      });
      status.textContent = '';
    } catch {
      if (!removed && request === generation) showElevation('当前浏览器无法使用 3D，已返回立面。');
    }
  }

  buttons[0].addEventListener('click', () => showElevation());
  buttons[1].addEventListener('click', showScene);
  activate('2d');
  return () => {
    removed = true;
    showElevation();
  };
}
