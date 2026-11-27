import { RACK_DEPTH, RACK_UNIT, RACK_WIDTH } from './rack-geometry.js';

const SVG = 'http://www.w3.org/2000/svg';
const KINDS = { wall: '墙体', entrance: '入口', aisle: '走道', equipment: '设备区' };
const COLORS = { wall: 0x63788c, entrance: 0x087e78, aisle: 0x73ac9e, equipment: 0x8d8bb6 };
const DIRECTIONS = { 0: ['↓', '下'], 90: ['→', '右'], 180: ['↑', '上'], 270: ['←', '左'] };
const MAX_SIDE = 1600;
const PREVIEW_LIMIT = 8 * 1024 * 1024;
const UNITS_PER_METER = RACK_UNIT / 0.04445;

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text) item.textContent = text;
  return item;
}

function action(label, fn, className = 'button small') {
  const button = node('button', className, label);
  button.type = 'button';
  button.addEventListener('click', fn);
  return button;
}

function field(name, input) {
  const label = node('label', '', name);
  input.setAttribute('aria-label', name);
  label.append(input);
  return label;
}

function number(value, min, max, step) {
  const input = node('input');
  Object.assign(input, { type: 'number', value, min, max, step, required: true });
  return input;
}

function svg(tag, attributes) {
  const item = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) item.setAttribute(key, value);
  return item;
}

export function profiledRackCenters(profile, layout) {
  const overrides = new Map((profile.racks ?? []).map(({ rack_id, x, y }) => [String(rack_id), [x, y]]));
  return new Map((layout?.positions ?? []).map(({ rack_id, row, slot }) => {
    const key = String(rack_id);
    return [key, overrides.get(key) ?? [
      0.05 + 0.90 * (slot - 0.5) / layout.columns,
      0.12 + 0.76 * (1 - (row - 0.5) / layout.rows),
    ]];
  }));
}

export function roomProfileColor(kind) {
  return COLORS[kind];
}

export function roomProfileFeatureName(feature) {
  return feature.label || KINDS[feature.kind] || '';
}

function stylesheetVar(item, name, value) {
  item.style.setProperty(name, value);
}

function pointStyle(item, [x, y]) {
  stylesheetVar(item, '--floor-x', `${x * 100}%`);
  stylesheetVar(item, '--floor-y', `${y * 100}%`);
}

function drawVector(layer, { kind, from, to }) {
  const [x1, y1] = from.map((axis) => axis * 1000);
  const [x2, y2] = to.map((axis) => axis * 1000);
  const classes = { class: `room-floor-vector room-floor-${kind}`, 'vector-effect': 'non-scaling-stroke' };
  const area = kind === 'aisle' || kind === 'equipment';
  layer.append(area ? svg('rect', {
    ...classes, x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x1 - x2), height: Math.abs(y1 - y2),
  }) : svg('line', { ...classes, x1, y1, x2, y2 }));
}

function decorateMap(map, profile, layout, racksById, onRack) {
  const image = profile.reference?.url;
  let reference;
  if (image) {
    reference = node('img', 'room-floor-reference');
    reference.alt = '';
    reference.src = image;
  }
  stylesheetVar(map, '--floor-ratio', profile.width_m / profile.depth_m);
  const vectors = svg('svg', {
    viewBox: '0 0 1000 1000', preserveAspectRatio: 'none', class: 'room-floor-vectors', 'aria-hidden': 'true',
  });
  for (const feature of profile.features) {
    drawVector(vectors, feature);
    if (feature.kind === 'wall' && !feature.label) continue;
    const label = node('span', `room-floor-marker room-floor-marker-${feature.kind}`, roomProfileFeatureName(feature));
    pointStyle(label, feature.from.map((value, index) => (value + feature.to[index]) / 2));
    map.append(label);
  }
  if (profile.calibration && !onRack) drawVector(vectors, { ...profile.calibration, kind: 'scale' });
  map.prepend(vectors);
  if (reference) map.prepend(reference);

  const centers = profiledRackCenters(profile, layout);
  for (const position of layout?.positions ?? []) {
    const key = String(position.rack_id);
    const rack = racksById.get(key);
    if (!rack) continue;
    const [arrow, direction] = DIRECTIONS[position.rotation] ?? DIRECTIONS[0];
    const item = node(onRack ? 'a' : 'span', 'room-floor-cabinet room-overview-slot-rack');
    item.dataset.rackId = key;
    item.dataset.rotation = position.rotation;
    pointStyle(item, centers.get(key));
    const sideways = position.rotation === 90 || position.rotation === 270;
    stylesheetVar(item, '--floor-cabinet-width', `${100 * (sideways ? RACK_DEPTH : RACK_WIDTH) / UNITS_PER_METER / profile.width_m}%`);
    stylesheetVar(item, '--floor-cabinet-depth', `${100 * (sideways ? RACK_WIDTH : RACK_DEPTH) / UNITS_PER_METER / profile.depth_m}%`);
    if (onRack) {
      item.href = `#rack/${key}`;
      item.setAttribute('aria-label', `${rack.name}，${rack.height}U，正面朝${direction}`);
      item.addEventListener('click', (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        onRack(rack);
      });
    }
    item.append(node('strong', '', rack.name), node('span', '', arrow));
    map.append(item);
  }
}

export function renderRoomProfilePlan(room, profile, layout, racksById, onRack) {
  const plan = node('section', 'room-overview-plan room-floor-plan');
  const scroll = node('div', 'room-overview-plan-scroll room-floor-scroll');
  scroll.tabIndex = 0;
  scroll.setAttribute('role', 'region');
  scroll.setAttribute('aria-label', `${room.name}平面布置`);
  const map = node('div', 'room-floor-map');
  decorateMap(map, profile, layout, new Map([...racksById].map(([id, rack]) => [String(id), rack])), onRack);
  scroll.append(map);
  const context = profile.illustrative ? '演示平面 · ' : '';
  plan.append(scroll, node('p', 'room-overview-plan-key', `${context}${profile.width_m} × ${profile.depth_m} 米 · 箭头表示机柜正面`));
  return plan;
}

async function importReference(file, pageNumber) {
  if (file.size > PREVIEW_LIMIT) throw new Error('底图原文件须小于 8 MB。');
  const canvas = node('canvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('当前浏览器无法生成底图。');
  if (/\.pdf$/i.test(file.name)) {
    const vendor = new URL('./vendor/pdfjs/', import.meta.url);
    const pdfjs = await import(new URL('pdf.min.mjs?v=6.5.438', vendor).href);
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdf.worker.min.mjs?v=6.5.438', vendor).href;
    const task = pdfjs.getDocument({
      data: new Uint8Array(await file.arrayBuffer()), cMapUrl: new URL('cmaps/', vendor).href,
      cMapPacked: true, standardFontDataUrl: new URL('standard_fonts/', vendor).href,
      useWasm: false, enableXfa: false, isEvalSupported: false, canvasMaxAreaInBytes: MAX_SIDE ** 2 * 4,
    });
    try {
      const pdf = await task.promise;
      if (!Number.isSafeInteger(pageNumber) || pageNumber < 1 || pageNumber > pdf.numPages) {
        throw new Error(`请选择第 1–${pdf.numPages} 页。`);
      }
      const page = await pdf.getPage(pageNumber);
      const size = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: MAX_SIDE / Math.max(size.width, size.height) });
      canvas.width = Math.max(1, Math.floor(viewport.width));
      canvas.height = Math.max(1, Math.floor(viewport.height));
      await page.render({ canvas, canvasContext: ctx, viewport, background: '#fff' }).promise;
    } finally {
      await task.destroy();
    }
  } else {
    if (!/\.(png|jpe?g)$/i.test(file.name)) throw new Error('请选择 PNG、JPEG 或 PDF 文件。');
    const bitmap = await createImageBitmap(file);
    try {
      const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    } finally {
      bitmap.close();
    }
  }
  const url = canvas.toDataURL('image/jpeg', 0.85);
  const ratio = canvas.width / canvas.height;
  canvas.width = canvas.height = 0;
  return { name: file.name, url, data: url.split(',')[1], ratio };
}

export function openRoomProfileEditor(room, profile, layout, racks, { request, showEditor, userCanWrite, onSaved }) {
  if (!userCanWrite()) return;
  const draft = structuredClone(profile ?? {
    width_m: Math.max(4, (layout?.columns ?? 5) * 0.85), depth_m: Math.max(3, (layout?.rows ?? 1) * 1.8),
    revision: 0, features: [], racks: [], reference: null, calibration: null,
  });
  const editor = node('div', 'room-floor-editor');
  const widthField = number(draft.width_m, 2, 100, 'any');
  const depthField = number(draft.depth_m, 2, 100, 'any');
  const distance = number(draft.calibration?.length_m ?? 1, 0.1, 100, 'any');
  const page = number(1, 1, 5000, 1);
  const file = node('input');
  file.type = 'file';
  file.accept = 'image/jpeg,image/png,application/pdf';
  const name = node('input');
  name.maxLength = 40;
  name.placeholder = '可选';
  const choice = node('select');
  const rackChoice = node('select');
  const rackIds = new Set((layout?.positions ?? []).map(({ rack_id }) => String(rack_id)));
  const racksById = new Map(racks.filter((rack) => rackIds.has(String(rack.id))).map((rack) => [String(rack.id), rack]));
  for (const [kind, label] of [...Object.entries(KINDS), ['scale', '校准比例'], ['rack', '机柜位置']]) {
    const option = node('option', '', label);
    option.value = kind;
    option.disabled = kind === 'rack' && !racksById.size;
    choice.append(option);
  }
  for (const [id, rack] of racksById) {
    const option = node('option', '', rack.name);
    option.value = id;
    rackChoice.append(option);
  }
  const dimensions = node('div', 'room-floor-fields');
  dimensions.append(field('宽度（米）', widthField), field('进深（米）', depthField));
  const importFields = node('div', 'room-floor-fields room-floor-import');
  importFields.append(field('导入参考底图', file), field('PDF 页码', page));
  const referenceStatus = node('span', 'room-floor-reference-status');
  const referenceActions = node('div', 'room-floor-row');
  const removeReference = action('移除底图', () => {
    importId += 1;
    pending = false;
    referenceChange = null;
    draft.reference = null;
    draft.calibration = null;
    file.value = '';
    render();
  });
  referenceActions.append(referenceStatus, removeReference);
  const tools = node('div', 'room-floor-fields');
  const nameField = field('标记名称', name);
  const rackField = field('机柜', rackChoice);
  const scaleField = field('两点实距（米）', distance);
  tools.append(field('绘制', choice), nameField, rackField, scaleField);
  const scroll = node('div', 'room-floor-scroll');
  const map = node('div', 'room-floor-map room-floor-map-editor');
  map.tabIndex = 0;
  map.setAttribute('aria-label', '平面绘图。方向键移动光标，回车标点，Escape 清除待定点。');
  scroll.append(map);
  const status = node('p', 'room-floor-editor-status');
  status.setAttribute('role', 'status');
  const list = node('ul', 'room-floor-feature-list');
  const resetRack = action('恢复选中机柜的网格位置', () => {
    draft.racks = draft.racks.filter(({ rack_id }) => String(rack_id) !== rackChoice.value);
    render();
  });
  const clearScale = action('清除校准线', () => {
    draft.calibration = null;
    render();
  });
  const cancelPoint = action('撤销待定点', () => cancel());
  const edits = node('div', 'room-floor-row');
  edits.append(resetRack, clearScale, cancelPoint);
  editor.append(dimensions, importFields, referenceActions, tools, status, scroll, edits, list);

  let first = null;
  let cursor = [0.5, 0.5];
  let pending = false;
  let importId = 0;
  let referenceChange;

  function instructions() {
    return choice.value === 'rack' ? '选定机柜后，在平面中点选柜体中心。'
      : ['aisle', 'equipment'].includes(choice.value) ? '依次点选矩形区域的两个对角。'
        : choice.value === 'scale' ? '填写两点的实际距离，再点选图上两个对应位置。'
          : '依次点选两个端点。';
  }

  function syncList() {
    const rows = draft.features.map((feature, index) => {
      const row = node('li');
      const label = feature.label ? `${KINDS[feature.kind]} · ${feature.label}` : KINDS[feature.kind];
      row.append(node('span', '', label), action('移除', () => {
        draft.features.splice(index, 1);
        render();
      }));
      row.lastChild.setAttribute('aria-label', `移除${label}`);
      return row;
    });
    list.replaceChildren(...rows);
  }

  function render(message = '') {
    const kind = choice.value;
    rackField.hidden = kind !== 'rack';
    resetRack.hidden = kind !== 'rack' || !draft.racks.some(({ rack_id }) => String(rack_id) === rackChoice.value);
    nameField.hidden = kind === 'rack' || kind === 'scale';
    scaleField.hidden = kind !== 'scale';
    clearScale.hidden = !draft.calibration;
    cancelPoint.hidden = !first;
    referenceStatus.textContent = draft.reference?.name ?? '可选 PNG、JPEG 或指定页 PDF';
    removeReference.hidden = !draft.reference && !pending;
    status.textContent = message || (first ? '已标记第一个点，请选择第二个点。' : instructions());
    map.replaceChildren();
    decorateMap(map, draft, layout, racksById);
    if (first) {
      const mark = node('span', 'room-floor-anchor');
      pointStyle(mark, first);
      map.append(mark);
    }
    const focus = node('span', 'room-floor-cursor');
    pointStyle(focus, cursor);
    map.append(focus);
    syncList();
  }

  function cancel(message = '') {
    first = null;
    render(message);
  }

  function readDimensions() {
    return widthField.checkValidity() && depthField.checkValidity();
  }

  function updateDimensions() {
    if (!readDimensions()) return;
    draft.width_m = widthField.valueAsNumber;
    draft.depth_m = depthField.valueAsNumber;
    draft.calibration = null;
    render();
  }

  function mark(point) {
    const kind = choice.value;
    if (kind === 'rack') {
      const rack_id = Number(rackChoice.value);
      draft.racks = draft.racks.filter((rack) => rack.rack_id !== rack_id);
      draft.racks.push({ rack_id, x: point[0], y: point[1] });
      return cancel('已标记机柜中心。');
    }
    if (!first) {
      first = point;
      return render();
    }
    const [dx, dy] = point.map((value, axis) => Math.abs(value - first[axis]));
    const area = kind === 'aisle' || kind === 'equipment';
    if (Math.hypot(dx, dy) < 0.003 || (area && Math.min(dx, dy) < 0.003)) return render('两个点距离太近，请再选一个点。');
    const segment = { from: first, to: point };
    if (kind === 'scale') {
      if (!readDimensions() || !distance.reportValidity()) return;
      const length_m = distance.valueAsNumber;
      const multiplier = length_m / Math.hypot(dx * draft.width_m, dy * draft.depth_m);
      const width = Number((draft.width_m * multiplier).toFixed(4));
      const depth = Number((draft.depth_m * multiplier).toFixed(4));
      if (Math.min(width, depth) < 2 || Math.max(width, depth) > 100) return render('校准后尺寸超出 2–100 米，请检查点位和实距。');
      widthField.value = draft.width_m = width;
      depthField.value = draft.depth_m = depth;
      draft.calibration = { ...segment, length_m };
      return cancel(`已校准 · ${width} × ${depth} 米`);
    }
    if (draft.features.length >= 100) return cancel('平面标记最多 100 项。');
    draft.features.push({ kind, label: name.value.trim(), ...segment });
    return cancel(`已添加${KINDS[kind]}。`);
  }

  async function loadReference() {
    const selected = file.files[0];
    if (!selected) return;
    const ticket = ++importId;
    pending = true;
    render('正在读取底图…');
    try {
      const next = await importReference(selected, page.valueAsNumber);
      if (ticket !== importId || !editor.isConnected) return;
      pending = false;
      draft.reference = next;
      draft.calibration = null;
      referenceChange = { name: next.name.slice(0, 180), data: next.data };
      const depth = Number((draft.width_m / next.ratio).toFixed(4));
      if (depth >= 2 && depth <= 100) draft.depth_m = depthField.value = depth;
      cancel('底图已载入，可选择两个点校准比例。');
    } catch (error) {
      if (ticket !== importId) return;
      pending = false;
      if (editor.isConnected) render(error.message || '读取底图失败。');
    }
  }

  widthField.addEventListener('change', updateDimensions);
  depthField.addEventListener('change', updateDimensions);
  file.addEventListener('change', () => void loadReference());
  page.addEventListener('change', () => {
    if (/\.pdf$/i.test(file.files[0]?.name ?? '')) void loadReference();
  });
  choice.addEventListener('change', () => cancel());
  rackChoice.addEventListener('change', () => render());
  map.addEventListener('click', (event) => {
    const box = map.getBoundingClientRect();
    cursor = [event.clientX - box.left, event.clientY - box.top].map((axis, index) =>
      Math.max(0, Math.min(1, axis / (index ? box.height : box.width))));
    mark(cursor);
  });
  map.addEventListener('keydown', (event) => {
    const movement = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
    if (!movement && event.key !== 'Enter' && event.key !== 'Escape') return;
    event.preventDefault();
    if (event.key === 'Escape') {
      event.stopPropagation();
      cancel();
    } else if (event.key === 'Enter') mark(cursor);
    else {
      cursor = cursor.map((axis, index) => Math.max(0, Math.min(1, axis + movement[index] * (event.shiftKey ? 0.01 : 0.025))));
      pointStyle(map.querySelector('.room-floor-cursor'), cursor);
    }
  });

  render();
  showEditor({
    title: '编辑机房平面', id: 'room-floor-form', fields: [editor],
    save() {
      if (pending) throw new Error('请等待底图读取完成。');
      const data = {
        revision: draft.revision, width_m: widthField.valueAsNumber, depth_m: depthField.valueAsNumber,
        features: draft.features, racks: draft.racks.filter(({ rack_id }) => rackIds.has(String(rack_id))),
        calibration: draft.calibration,
      };
      if (referenceChange !== undefined) data.reference = referenceChange;
      return request(`rooms/${room.id}/floor-profile`, { method: 'PATCH', data });
    },
    success: '机房平面已保存。',
    afterSave: onSaved,
  });
}
