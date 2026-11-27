// 精选规格与标准端口取自 NetBox Community Device Type Library（CC0）。
const SOURCE = 'https://github.com/netbox-community/devicetype-library/blob/master/device-types/';
const SVG = 'http://www.w3.org/2000/svg';

function ethernet(name, group = '管理', kind = 'copper') {
  return { name, kind, group, state: 'unknown' };
}

function series(prefix, count, group, kind) {
  return Array.from({ length: count }, (_, index) => ethernet(prefix + (index + 1), group, kind));
}

function ciscoPorts(count) {
  return [
    ...series('GigabitEthernet1/0/', count, '接入口', 'copper'),
    ...series('GigabitEthernet1/1/', 4, 'SFP 上联', 'fiber'),
    ethernet('GigabitEthernet0/0'),
  ];
}

const TEMPLATES = [
  {
    model: 'Dell PowerEdge R730', aliases: ['PowerEdge R730', 'Dell R730', '戴尔 R730', 'R730'],
    u_height: 2, mount_depth: 'full', ports: [ethernet('iDRAC')],
    style: 'dell', source: 'Dell/PowerEdge-R730.yaml',
  },
  {
    model: 'Dell PowerEdge R740', aliases: ['PowerEdge R740', 'Dell R740', '戴尔 R740', 'R740'],
    u_height: 2, mount_depth: 'full', ports: [ethernet('iDRAC9')],
    style: 'dell', source: 'Dell/PowerEdge-R740.yaml',
  },
  {
    model: 'HPE ProLiant DL380 Gen10', aliases: ['ProLiant DL380 Gen10', 'HPE DL380 Gen10', 'HP DL380 Gen10', 'DL380 Gen10', 'DL380 G10'],
    u_height: 2, mount_depth: 'full', ports: [...series('Gig-E ', 4, '板载网络', 'copper'), ethernet('iLO')],
    style: 'hpe', source: 'HPE/ProLiant-DL380-Gen10.yaml',
  },
  {
    model: 'Cisco Catalyst C9200L-24T-4G-E', aliases: ['C9200L-24T-4G-E', 'Cisco C9200L-24T-4G-E'],
    u_height: 1, mount_depth: 'half', ports: ciscoPorts(24), accessPorts: 24,
    style: 'switch', source: 'Cisco/C9200L-24T-4G-E.yaml',
  },
  {
    model: 'Cisco Catalyst 9200L-48P-4G', aliases: ['Catalyst 9200L-48P-4G', 'C9200L-48P-4G', 'Cisco C9200L-48P-4G'],
    u_height: 1, mount_depth: 'half', ports: ciscoPorts(48), accessPorts: 48,
    style: 'switch', source: 'Cisco/C9200L-48P-4G.yaml',
  },
];

function modelKey(value) {
  return String(value ?? '').normalize('NFKC').toLowerCase().replace(/[\s-]+/g, '');
}

const BY_MODEL = new Map(TEMPLATES.flatMap((template) =>
  [template.model, ...template.aliases].map((name) => [modelKey(name), template])));

export function matchDeviceModelTemplate(model) {
  return BY_MODEL.get(modelKey(model));
}

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function sourceLink(template) {
  const link = node('a', '规格来源（NetBox · CC0）');
  link.href = SOURCE + template.source;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
}

export function deviceModelTemplatePicker(modelInput, { applyPlacement } = {}) {
  const picker = node('div', '', 'device-model-picker wide');
  const list = node('datalist');
  list.id = 'device-model-templates';
  for (const template of TEMPLATES) {
    const option = node('option');
    option.value = template.model;
    list.append(option);
  }
  const info = node('div', '', 'device-model-template-info');
  info.setAttribute('aria-live', 'polite');
  info.hidden = true;
  let currentTemplate;
  picker.append(list, info);
  modelInput.setAttribute('list', list.id);

  function update() {
    const template = matchDeviceModelTemplate(modelInput.value);
    if (template === currentTemplate) return;
    currentTemplate = template;
    info.hidden = !template;
    info.replaceChildren();
    if (!template) return;
    const depth = template.mount_depth === 'full' ? '全深' : '半深';
    info.append(node('span', `型号参考 · ${template.u_height}U · ${depth}`), sourceLink(template));
    if (!applyPlacement) return;
    const button = node('button', `填入 ${template.u_height}U`, 'button small');
    button.type = 'button';
    button.addEventListener('click', () => applyPlacement({ u_height: template.u_height, mount_depth: template.mount_depth }));
    info.append(button);
  }

  modelInput.addEventListener('input', update);
  modelInput.addEventListener('change', update);
  update();
  return picker;
}

function drawing(tag, attributes) {
  const shape = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) shape.setAttribute(name, value);
  return shape;
}

function panelDrawing(template, face) {
  const height = 34 * template.u_height + 16;
  const panel = drawing('svg', {
    viewBox: `0 0 560 ${height}`, class: 'device-model-drawing',
    role: 'img', 'aria-label': `${template.model} ${face === '正面' ? '正面' : '背面'}示意图`,
  });
  const box = (x, y, width, height, fill, stroke = 'none', rx = 2) => panel.append(
    drawing('rect', { x, y, width, height, fill, stroke, rx }),
  );
  box(3, 3, 554, height - 6, '#283642', '#566679', 5);
  for (const x of [14, 546]) {
    panel.append(drawing('circle', { cx: x, cy: height / 2, r: 3.1, fill: '#9babb8' }));
  }
  if (template.style === 'switch' && face === '正面') {
    const columns = template.accessPorts / 2;
    const pitch = 392 / columns;
    for (let column = 0; column < columns; column += 1) {
      for (const y of [11, 27]) {
        box(34 + column * pitch, y, pitch - 3, 12, '#111c27', '#708394');
      }
    }
    for (const x of [447, 470, 493, 516]) box(x, 16, 17, 17, '#122630', '#5faca3');
    return panel;
  }
  if (face === '背面') {
    const bayHeight = height - 24;
    box(26, 12, 178, bayHeight, '#14202c');
    for (const x of [36, 115]) {
      box(x, 19, 67, bayHeight - 14, '#3a4d5b', '#718394');
      box(x + 9, height / 2 - 6, 22, 12, '#172631');
      box(x + 43, height / 2 - 10, 12, 20, '#607483');
    }
    box(218, 12, 313, bayHeight, '#344552', '#5c7081');
    const ports = template.ports.filter(({ group }) => group === '管理' || group === '板载网络');
    for (const [index] of ports.entries()) box(238 + index * 25, height / 2 - 8, 16, 16, '#111c27', '#899dab');
    for (const x of [397, 422, 447, 472, 497]) box(x, height / 2 - 3, 17, 6, '#283642');
    return panel;
  }

  const accent = template.style === 'hpe' ? '#aac5be' : '#8fb4c8';
  box(28, 12, 504, height - 24, '#1c2935', '#536879');
  for (let y = 18; y <= height - 20; y += 7) {
    for (let x = 38; x < 493; x += 14) box(x, y, 9, 1.8, '#465969', 'none', 1);
  }
  box(48, height / 2 - 9, 49, 18, '#263745');
  box(56, height / 2 - 3, 31, 6, accent);
  box(506, height / 2 - 8, 11, 16, '#425563');
  return panel;
}

const PHOTO_TYPES = { 正面: '设备正面照片', 背面: '设备背面照片' };

export function deviceModelPanel(device, documents, fileAddress) {
  const template = matchDeviceModelTemplate(device.model);
  const photos = new Map(Object.entries(PHOTO_TYPES).map(([face, category]) => [face, documents
    .filter((record) => record.device_id === device.id && record.category === category && /\.(png|jpe?g|webp)$/i.test(record.filename))
    .at(-1)]));
  if (!template && ![...photos.values()].some(Boolean)) return null;
  const section = node('section', '', 'panel device-model-panel');
  section.append(node('h2', '设备面板'));
  const panels = node('div', '', 'device-model-panels');
  for (const [face, photo] of photos) {
    if (!photo && !template) continue;
    const figure = node('figure');
    const caption = node('figcaption', `${face} · ${photo ? '档案实拍' : '型号示意'}`);
    if (photo) {
      const image = node('img');
      image.src = fileAddress(photo);
      image.alt = `${device.name} ${face}照片`;
      image.loading = 'lazy';
      image.decoding = 'async';
      image.addEventListener('error', () => {
        image.replaceWith(template ? panelDrawing(template, face) : node('p', '照片不可用。', 'muted'));
        caption.textContent = `${face} · ${template ? '型号示意' : '照片不可用'}`;
      }, { once: true });
      figure.append(image);
    } else {
      figure.append(panelDrawing(template, face));
    }
    figure.append(caption);
    panels.append(figure);
  }
  section.append(panels);
  if (template) section.append(sourceLink(template));
  return section;
}
