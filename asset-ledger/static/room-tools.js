import { isDeviceArchived } from './asset-search.js';
import { FRONT_MARKERS } from './room-overview.js';
import { OPERATING_STATUS_LABELS, operatingStatus } from './rack.js?v=operating-status';
import { rackOccupancy } from './rack-geometry.js';

const FACE_NAMES = { front: '正面', rear: '背面' };
const LAYOUT_ROTATIONS = [0, 90, 180, 270];
const LAYOUT_LIMITS = { rows: 12, columns: 20 };
const RACK_HEIGHT_LIMIT = 255;
let activeAvailabilityPicker = null;

function roomPath(catalog, room) {
  if (!room) return '';
  const site = catalog.sites.find((item) => item.id === room.site_id);
  const unit = catalog.units.find((item) => item.id === site?.unit_id);
  return [unit?.name, site?.name, room.name].filter(Boolean).join(' / ');
}

function unitRange(start, end) {
  return start === end ? `U${start}` : `U${start}–U${end}`;
}

function displayedStatus(catalog, room) {
  const racks = catalog.racks.filter((rack) => rack.room_id === room.id);
  const devices = catalog.devices.filter((device) => device.room_id === room.id && !isDeviceArchived(device));
  const mounted = new Map(racks.map((rack) => [rack.id, []]));
  const statusCounts = Object.fromEntries(Object.keys(OPERATING_STATUS_LABELS).map((key) => [key, 0]));
  for (const device of devices) {
    statusCounts[operatingStatus(device)] += 1;
    mounted.get(device.rack_id)?.push(device);
  }
  let usedU = 0;
  let totalU = 0;
  let mountedCount = 0;
  for (const rack of racks) {
    const rackDevices = mounted.get(rack.id);
    usedU += rackOccupancy(rack, rackDevices).usedU;
    totalU += rack.height;
    mountedCount += rackDevices.length;
  }
  return { racks, devices, usedU, totalU, mountedCount, statusCounts };
}

export function renderRoomStatistics(catalog, room, { element }) {
  const { racks, devices, usedU, totalU, mountedCount, statusCounts } = displayedStatus(catalog, room);
  const rate = totalU ? Math.round(100 * usedU / totalU) : 0;
  const metric = (label, value, detail) => element('div', { class: 'room-statistic' },
    element('dt', {}, label), element('dd', {}, value), detail);
  return element('section', { class: 'panel room-statistics', 'aria-label': '机房统计' },
    element('h2', {}, '机房统计'),
    element('dl', { class: 'room-statistics-grid' },
      metric('机柜', racks.length),
      metric('在册设备', devices.length,
        element('small', {}, `上架 ${mountedCount} · 未上架 ${devices.length - mountedCount}`)),
      metric('物理 U 位占用', totalU ? `${usedU} / ${totalU}U` : '—', totalU
        ? element('small', {}, element('meter', { min: 0, max: totalU, value: usedU, 'aria-label': '物理 U 位占用' }),
          `${rate}%`)
        : null)),
    element('p', { class: 'small-text muted' }, '正背面共用的 U 位只计一次。按面和深度查具体位置请使用空位查询。'),
    element('ul', { class: 'room-statistics-status', 'aria-label': '人工登记运行状态' },
      Object.entries(OPERATING_STATUS_LABELS).map(([status, label]) =>
        element('li', { 'data-status': status }, element('span', {}, label),
          element('strong', {}, statusCounts[status])))));
}

function showNameEditor({ element, selectInput, showEditor, request }, {
  record, title, formId, ownerField, ownerLabel, options, selected, route, afterSave, nameMax,
  nameLabel = title + '名称', additional = [],
}) {
  const owner = selectInput(ownerField, options, selected ?? '', `选择${ownerLabel}`, { required: true, disabled: Boolean(record) });
  const name = element('input', { name: 'name', value: record?.name ?? '', maxlength: nameMax, required: true });
  showEditor({
    title: `${record ? '编辑' : '新增'}${title}`,
    id: formId,
    fields: [element('div', { class: 'field-grid' },
      element('label', {}, ownerLabel, owner),
      element('label', {}, nameLabel, name),
      additional.map(({ label, control }) => element('label', {}, label, control)))],
    save(form) {
      const values = new FormData(form);
      const data = { name: String(values.get('name')).trim() };
      if (!record) data[ownerField] = Number(values.get(ownerField));
      for (const { control } of additional) data[control.name] = Number(values.get(control.name));
      return request(record ? `${route}/${record.id}` : route, { method: record ? 'PATCH' : 'POST', data });
    },
    success: `${title}已保存。`,
    afterSave,
  });
}

export function openRoomEditor(catalog, room, ui) {
  if (!ui.userCanWrite()) return;
  const options = catalog.sites.map((site) => [
    site.id, [catalog.units.find((unit) => unit.id === site.unit_id)?.name, site.name].filter(Boolean).join(' / '),
  ]);
  showNameEditor(ui, {
    record: room, title: '机房', formId: 'room-form', ownerField: 'site_id', ownerLabel: '站点',
    options, selected: room?.site_id ?? (options.length === 1 ? options[0][0] : null),
    route: 'rooms', afterSave: ui.afterRoomSave, nameMax: 160,
  });
}

export function openRackEditor(catalog, room, rack, ui) {
  if (!ui.userCanWrite()) return;
  const height = ui.element('input', {
    name: 'height', type: 'number', min: 1, max: RACK_HEIGHT_LIMIT, step: 1, required: true, value: rack?.height ?? 42,
  });
  const options = catalog.rooms.map((candidate) => [candidate.id, roomPath(catalog, candidate)]);
  showNameEditor(ui, {
    record: rack, title: '机柜', formId: 'rack-form', ownerField: 'room_id', ownerLabel: '机房',
    options, selected: rack?.room_id ?? room?.id ?? (options.length === 1 ? options[0][0] : null),
    route: 'racks', afterSave: ui.afterRackSave, nameMax: 80, nameLabel: '柜号', additional: [{ label: '柜高（U）', control: height }],
  });
}

export function openRoomLayoutEditor(room, layout, racks, { button, element, request, showEditor, userCanWrite }) {
  if (!room || !userCanWrite()) return;
  const racksById = new Map(racks.map((rack) => [rack.id, rack]));
  const draft = new Map((layout?.positions ?? []).filter(({ rack_id }) => racksById.has(rack_id))
    .map((position) => [position.rack_id, { ...position }]));
  let selectedId = null;
  let rows = layout?.rows ?? 2;
  let columns = layout?.columns ?? 5;
  let cellFocus = null;
  const cellButtons = new Map();
  const numberField = (name, value) => element('input', {
    name, type: 'number', min: 1, max: LAYOUT_LIMITS[name], step: 1, required: true, value,
  });
  const rowsField = numberField('rows', rows);
  const columnsField = numberField('columns', columns);

  const grid = element('div', { class: 'room-layout-grid' });
  const viewport = element('div', {
    class: 'room-layout-viewport', role: 'region', 'aria-label': '布局网格', 'aria-describedby': 'room-layout-instructions',
  }, grid);
  const waiting = element('div', { class: 'room-layout-waiting' });
  const announcement = element('p', { class: 'room-layout-announcement', role: 'status' });
  const selection = element('strong', { class: 'room-layout-selection' });
  const rotate = button('顺时针旋转 90°', rotateSelected, 'small');
  const unplace = button('移至待摆放', unplaceSelected, 'small');
  const deselect = button('取消选中', () => {
    selectedId = null;
    render('已取消选中。');
    focusCell(cellFocus);
  }, 'small quiet');

  const inGrid = (position) => position && position.row <= rows && position.slot <= columns;
  const positionKey = (row, slot) => `${row}:${slot}`;
  const selectedRack = () => racksById.get(selectedId);
  const outsideGrid = () => [...draft.values()].filter((position) => !inGrid(position));

  function focusCell(key) {
    const target = cellButtons.get(key);
    if (!target) return;
    cellButtons.get(cellFocus)?.setAttribute('tabindex', '-1');
    cellFocus = key;
    target.tabIndex = 0;
    target.focus();
  }

  function render(message) {
    const positions = new Map([...draft.values()].filter(inGrid)
      .map((position) => [positionKey(position.row, position.slot), position]));
    if (!cellFocus || Number(cellFocus.split(':')[0]) > rows || Number(cellFocus.split(':')[1]) > columns) {
      cellFocus = positionKey(rows, 1);
    }
    grid.style.setProperty('--room-columns', columns);
    cellButtons.clear();
    const axis = element('div', { class: 'room-layout-row room-layout-axis', 'aria-hidden': 'true' },
      element('span', {}, '柜位'), Array.from({ length: columns }, (_, index) => element('span', {}, index + 1)));
    const planRows = [axis];
    for (let row = rows; row >= 1; row -= 1) {
      if (row !== rows) planRows.push(element('div', { class: 'room-layout-aisle', 'aria-hidden': 'true' }, '走道'));
      const planRow = element('div', { class: 'room-layout-row' },
        element('span', { class: 'room-overview-row-label', 'aria-hidden': 'true' }, `第 ${row} 排`));
      for (let slot = 1; slot <= columns; slot += 1) {
        const key = positionKey(row, slot);
        const position = positions.get(key);
        const rack = racksById.get(position?.rack_id);
        const [arrow, orientation] = FRONT_MARKERS[position?.rotation ?? 0];
        const label = `第 ${row} 排第 ${slot} 位${rack ? `，${rack.name}，${rack.height}U，正面朝${orientation}` : '，空位'}`;
        const cell = element('button', {
          type: 'button',
          class: `room-layout-cell room-overview-slot ${rack ? 'room-overview-slot-rack' : 'room-overview-slot-empty'}`,
          'data-row': row, 'data-slot': slot, 'data-rack-id': rack?.id, 'data-rotation': position?.rotation,
          'aria-label': label, 'aria-pressed': rack ? String(rack.id === selectedId) : null,
          title: label, tabindex: key === cellFocus ? 0 : -1,
          onclick: () => useCell(row, slot, rack),
          onfocus: () => {
            if (cellFocus === key) return;
            cellButtons.get(cellFocus)?.setAttribute('tabindex', '-1');
            cellFocus = key;
            cell.tabIndex = 0;
          },
        }, rack ? [
          element('strong', {}, rack.name),
          element('span', { class: 'room-overview-rack-height' }, `${rack.height}U`),
          element('span', { class: 'room-overview-front', 'aria-hidden': 'true' }, arrow),
        ] : '空位');
        cellButtons.set(key, cell);
        planRow.append(cell);
      }
      planRows.push(planRow);
    }
    grid.replaceChildren(...planRows);

    const unplacedRacks = racks.filter((rack) => !draft.has(rack.id));
    const outsideRacks = outsideGrid();
    waiting.replaceChildren();
    if (outsideRacks.length) waiting.append(rackGroup('超出网格', 'room-layout-outside', outsideRacks.map((position) => {
      const rack = racksById.get(position.rack_id);
      return [rack, `${rack.name} · 第 ${position.row} 排第 ${position.slot} 位`];
    })));
    if (unplacedRacks.length) waiting.append(rackGroup('待摆放', 'room-layout-unplaced',
      unplacedRacks.map((rack) => [rack, `${rack.name} · ${rack.height}U`])));
    const rack = selectedRack();
    selection.textContent = rack ? `已选 ${rack.name}` : '请选择机柜';
    rotate.disabled = !draft.has(selectedId);
    unplace.disabled = !draft.has(selectedId);
    deselect.disabled = !rack;
    if (message != null) announcement.textContent = message;
  }

  function rackGroup(title, className, entries) {
    return element('div', { class: `room-layout-rack-group ${className}` },
      element('h3', {}, title),
      element('div', { class: 'room-layout-rack-buttons' }, entries.map(([rack, label]) =>
        button(label, () => {
          selectedId = rack.id;
          render(`已选 ${rack.name}，请选择空位。`);
          waiting.querySelector(`[data-rack-id="${rack.id}"]`)?.focus();
        }, 'small', { 'data-rack-id': rack.id, 'aria-pressed': String(rack.id === selectedId) }))));
  }

  function useCell(row, slot, target) {
    const key = positionKey(row, slot);
    const rack = selectedRack();
    if (!rack || target?.id === rack.id) {
      if (!target) {
        announcement.textContent = '请先选择要摆放的机柜。';
        return;
      }
      selectedId = target.id;
      render(`已选 ${target.name}，点空位可移动，点另一台机柜可交换。`);
      focusCell(key);
      return;
    }
    const previous = draft.get(rack.id);
    if (target && !inGrid(previous)) {
      announcement.textContent = '请先选择一个空位，或先将目标机柜移至待摆放。';
      return;
    }
    if (target) draft.set(target.id, { ...draft.get(target.id), row: previous.row, slot: previous.slot });
    draft.set(rack.id, { rack_id: rack.id, row, slot, rotation: previous?.rotation ?? 0 });
    render(target ? `已交换 ${rack.name} 和 ${target.name}。` : `${rack.name} 已移到第 ${row} 排第 ${slot} 位。`);
    focusCell(key);
  }

  function rotateSelected() {
    const current = draft.get(selectedId);
    if (!current) return;
    const rotation = LAYOUT_ROTATIONS[(LAYOUT_ROTATIONS.indexOf(current.rotation) + 1) % LAYOUT_ROTATIONS.length];
    draft.set(selectedId, { ...current, rotation });
    render(`${selectedRack().name} 正面朝${FRONT_MARKERS[rotation][1]}。`);
  }

  function unplaceSelected() {
    const rack = selectedRack();
    if (!rack || !draft.delete(rack.id)) return;
    render(`${rack.name} 已移到待摆放。`);
    waiting.querySelector(`[data-rack-id="${rack.id}"]`)?.focus();
  }

  function resizeLayout() {
    if (!rowsField.validity.valid || !columnsField.validity.valid) return;
    rows = rowsField.valueAsNumber;
    columns = columnsField.valueAsNumber;
    const outside = outsideGrid().length;
    render(outside ? `${outside} 台机柜超出网格，请移回网格或移至待摆放。` : '');
  }

  grid.addEventListener('keydown', (event) => {
    const arrow = { ArrowUp: [1, 0], ArrowDown: [-1, 0], ArrowRight: [0, 1], ArrowLeft: [0, -1] }[event.key];
    const { row, slot } = event.target.dataset;
    if (!arrow || !row || !slot) return;
    event.preventDefault();
    const nextRow = Math.max(1, Math.min(rows, Number(row) + arrow[0]));
    const nextSlot = Math.max(1, Math.min(columns, Number(slot) + arrow[1]));
    focusCell(positionKey(nextRow, nextSlot));
  });
  rowsField.addEventListener('input', resizeLayout);
  columnsField.addEventListener('input', resizeLayout);
  render();
  showEditor({
    title: '编辑机柜布局', id: 'room-layout-form',
    fields: [
      element('div', { class: 'room-layout-dimensions' },
        element('label', {}, '排数', rowsField), element('label', {}, '每排柜位数', columnsField)),
      layout?.illustrative ? element('p', { class: 'small-text muted' }, '当前为示意布局，请核实实际摆位后保存。') : null,
      element('p', { class: 'small-text muted', id: 'room-layout-instructions' },
        '选中机柜后，点空位移动，点另一机柜交换。箭头指向机柜正面。键盘可用方向键移格，按回车选择。'),
      element('div', { class: 'room-layout-editor' },
        element('div', { class: 'room-layout-controls' }, selection, rotate, unplace, deselect),
        viewport, waiting, announcement),
    ],
    save(form) {
      const values = new FormData(form);
      const nextRows = Number(values.get('rows'));
      const nextColumns = Number(values.get('columns'));
      const overflow = [...draft.values()].filter(({ row, slot }) => row > nextRows || slot > nextColumns);
      if (overflow.length) {
        const names = overflow.map(({ rack_id }) => racksById.get(rack_id).name).join('、');
        throw new Error(`超出网格的机柜须先调整位置或移至待摆放：${names}。`);
      }
      return request(`rooms/${room.id}/layout`, {
        method: 'PATCH',
        data: { rows: nextRows, columns: nextColumns, positions: [...draft.values()] },
      });
    },
    success: '机房布局已保存。',
  });
}


function groupStarts(starts) {
  const groups = [];
  for (const start of starts) {
    const last = groups.at(-1);
    if (last && last.end + 1 === start) last.end = start;
    else groups.push({ start, end: start });
  }
  return groups;
}

export function openAvailabilityPicker(catalog, room, ui, onSelect) {
  const { element, button, selectInput, request, internalLink, userCanWrite } = ui;
  if (activeAvailabilityPicker) activeAvailabilityPicker();
  const canSelect = typeof onSelect === 'function' && userCanWrite();
  const roomsById = new Map(catalog.rooms.map((candidate) => [candidate.id, candidate]));
  const roomChoice = selectInput('room_id', catalog.rooms.map((candidate) => [
    candidate.id, roomPath(catalog, candidate),
  ]), roomsById.has(room?.id) ? room.id : '', '所有可见机房');
  const faceChoice = selectInput('face', [['any', '正面和背面'], ...Object.entries(FACE_NAMES)], 'any');
  const heightChoice = element('input', {
    name: 'u_height', type: 'number', min: 1, max: RACK_HEIGHT_LIMIT, step: 1, required: true, value: 1,
  });
  const depthChoice = selectInput('mount_depth', [['full', '全深'], ['half', '半深']], 'full');
  const submit = element('button', { class: 'button primary', type: 'submit' }, '查询空位');
  const status = element('p', { class: 'muted small-text', role: 'status' }, '设置占用高度、深度和安装面后查询。');
  const errors = element('p', { class: 'form-error', role: 'alert', hidden: true });
  const results = element('div', { class: 'rack-availability-results' });

  const form = element('form', { class: 'rack-availability-filter' },
    element('label', {}, '机房', roomChoice),
    element('label', {}, '安装面', faceChoice),
    element('label', {}, '占用高度（U）', heightChoice),
    element('label', {}, '安装深度', depthChoice),
    submit);
  const dialog = element('dialog', {
    id: 'rack-availability-dialog', class: 'rack-availability-dialog', 'aria-labelledby': 'rack-availability-title',
  },
  element('header', { class: 'dialog-head' },
    element('h2', { class: 'dialog-title', id: 'rack-availability-title' }, '查询空位'),
    button('关闭', close, 'quiet small')),
  element('div', { class: 'editor-body' }, form, status, errors, results));

  let disposed = false;
  let queryVersion = 0;
  function close() {
    if (disposed) return;
    disposed = true;
    if (activeAvailabilityPicker === close) activeAvailabilityPicker = null;
    dialog.close();
    dialog.remove();
  }

  function resultFace(rack, face, starts, height, depth) {
    const ranges = groupStarts(starts);
    const faceLabel = FACE_NAMES[face];
    const groups = element('ul', { class: 'rack-availability-ranges', 'aria-label': `${faceLabel}可用起点` },
      ranges.map(({ start, end }) => element('li', {},
        start === end ? `起始 U${start}` : `起始 ${unitRange(start, end)}`)));
    const faceRow = element('div', { class: 'rack-availability-face', 'data-face': face },
      element('strong', {}, `${faceLabel} · ${starts.length} 个起点`), groups);
    if (canSelect) {
      const choices = element('div', { class: 'rack-availability-choices' });
      const options = element('details', { open: starts.length <= 10 },
        element('summary', {}, '选择起始 U 位'), choices);
      function showChoices() {
        if (!options.open || choices.childElementCount) return;
        choices.append(...starts.map((start) => {
          const range = unitRange(start, start + height - 1);
          return button(range, () => {
            if (disposed || !userCanWrite()) return;
            close();
            onSelect({ rack_id: rack.id, face, u_start: start, u_height: height, mount_depth: depth });
          }, 'small', {
            'data-u-start': start,
            'aria-label': `选择 ${rack.name} ${faceLabel} ${range}`,
          });
        }));
      }
      options.addEventListener('toggle', showChoices);
      showChoices();
      faceRow.append(options);
    }
    return faceRow;
  }

  function renderResults(racks, height, depth) {
    let count = 0;
    const matching = [];
    for (const rack of racks) {
      const rackRoom = roomsById.get(rack.room_id);
      if (!rackRoom) continue;
      const faces = [];
      for (const face of Object.keys(FACE_NAMES)) {
        const starts = rack.faces[face].starts;
        if (!starts.length) continue;
        count += starts.length;
        faces.push(resultFace(rack, face, starts, height, depth));
      }
      if (!faces.length) continue;
      matching.push(element('article', { class: 'rack-availability-rack', 'data-rack-id': rack.id },
        element('header', {}, element('h3', {}, internalLink('rack', rack.id, rack.name), ` · ${rack.height}U`),
          element('p', { class: 'muted small-text' }, roomPath(catalog, rackRoom))),
        faces));
    }
    results.replaceChildren(...matching);
    const depthLabel = depth === 'full' ? '全深' : '半深';
    status.textContent = matching.length
      ? `${height}U ${depthLabel} · ${matching.length} 台机柜 · ${count} 个可用起点。`
      : `没有找到可放置 ${height}U ${depthLabel}设备的位置。`;
  }

  function invalidateResults() {
    queryVersion += 1;
    results.replaceChildren();
    results.removeAttribute('aria-busy');
    submit.disabled = false;
    errors.hidden = true;
    status.textContent = '筛选条件已调整，请重新查询。';
  }

  form.addEventListener('change', invalidateResults);
  heightChoice.addEventListener('input', invalidateResults);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const ticket = ++queryVersion;
    const height = heightChoice.valueAsNumber;
    const depth = depthChoice.value;
    const query = new URLSearchParams({ height: String(height), depth, face: faceChoice.value });
    if (roomChoice.value) query.set('room_id', roomChoice.value);
    results.replaceChildren();
    results.setAttribute('aria-busy', 'true');
    errors.hidden = true;
    submit.disabled = true;
    status.textContent = '正在查询可用位置…';
    try {
      const response = await request(`rack-availability?${query}`);
      if (!disposed && ticket === queryVersion) renderResults(response.racks, height, depth);
    } catch (error) {
      if (!disposed && ticket === queryVersion) {
        status.textContent = '';
        errors.textContent = error.message;
        errors.hidden = false;
      }
    } finally {
      if (!disposed && ticket === queryVersion) {
        results.removeAttribute('aria-busy');
        submit.disabled = false;
      }
    }
  });
  dialog.addEventListener('close', close);
  document.body.append(dialog);
  dialog.showModal();
  activeAvailabilityPicker = close;
  return close;
}
