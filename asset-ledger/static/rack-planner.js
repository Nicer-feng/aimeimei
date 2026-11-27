import { units } from './rack.js?v=operating-status';

const faces = { front: '正面', rear: '背面' };
const depths = { full: '全深', half: '半深', unknown: '深度待核' };
const states = { free: '空位', occupied: '本面占用', full: '对面全深占用', half: '仅可半深共享', unknown: '对面深度待核' };
const sides = Object.keys(faces);

function node(tag, attributes = {}, ...children) {
  const item = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, value);
  item.append(...children.flat(Infinity));
  return item;
}

function button(text, action, className = 'button') {
  const item = node('button', { type: 'button', class: className }, text);
  item.addEventListener('click', action);
  return item;
}

function select(name, options) {
  return node('select', { name }, options.map(([value, label]) => node('option', { value }, label)));
}

function label(text, control) {
  return node('label', {}, text, control);
}

function isPlaced(device) {
  return Boolean(device?.rack_id && device?.u_start && device?.u_height);
}

function rackLabel(catalog, rack) {
  const room = catalog.rooms.find((item) => item.id === rack.room_id);
  const site = catalog.sites?.find((item) => item.id === room?.site_id);
  return [site?.name, room?.name, rack.name].filter(Boolean).join(' / ');
}

function deviceLabel(device) {
  return device ? [device.name, device.code].filter(Boolean).join(' · ') : '拟装设备';
}

function slotLabel(slot, devices) {
  return [`U${slot.u}`, states[slot.state], devices.get(slot.device_id)?.name, slot.code].filter(Boolean).join(' · ');
}

function description(slot) {
  return `${faces[slot.face]} ${units(slot)} · ${depths[slot.mount_depth]}`;
}

function setGridSpan(node, last, lower, upper = lower) {
  node.style.gridRow = `${last - upper + 1} / span ${upper - lower + 1}`;
}

function slotRun(slots, index) {
  const first = slots[index];
  let end = index;
  while (slots[end + 1]?.device_id === first.device_id && slots[end + 1]?.state === first.state) end += 1;
  return end;
}

function drawFace(rack, face, devices, choose, first, last) {
  const grid = node('div', { class: 'rack-planner-rail' });
  const data = rack.faces[face];
  const slots = data.slots.slice(first - 1, last);
  const starts = new Set(data.starts);
  for (const slot of [...slots].reverse()) {
    const available = starts.has(slot.u);
    const label = slotLabel(slot, devices) + (choose && available ? ' · 可作起始位' : '');
    const attributes = { 'data-state': slot.state, 'data-u': slot.u, 'data-face': face, title: label };
    const cell = choose
      ? node('button', { ...attributes, type: 'button', class: 'rack-planner-slot', 'aria-label': label,
        'aria-pressed': 'false', tabindex: '-1' }, node('span', {}, `U${slot.u}`))
      : node('div', { ...attributes, class: 'rack-planner-slot' }, node('span', {}, `U${slot.u}`));
    if (choose) {
      cell.toggleAttribute('data-available', available);
      cell.addEventListener('click', () => choose(face, slot.u, true));
      cell.addEventListener('keydown', (event) => {
        const next = { ArrowUp: slot.u + 1, ArrowDown: slot.u - 1, Home: rack.height, End: 1 }[event.key];
        if (next == null) return;
        event.preventDefault();
        choose(face, Math.min(rack.height, Math.max(1, next)), true);
      });
    }
    setGridSpan(cell, last, slot.u);
    grid.append(cell);
  }

  for (let index = 0; index < slots.length; index += 1) {
    const slot = slots[index];
    if (slot.state === 'free') continue;
    const end = slotRun(slots, index);
    const device = devices.get(slot.device_id);
    const code = slot.code || states[slot.state];
    const name = device?.name || code;
    const block = node('span', { class: 'rack-planner-device', 'data-state': slot.state },
      node('span', { class: 'rack-planner-device-name' }, name),
      ...(end > index && device?.name && code !== name ? [node('span', { class: 'rack-planner-device-code' }, code)] : []));
    block.setAttribute('aria-hidden', 'true');
    setGridSpan(block, last, slot.u, slots[end].u);
    grid.append(block);
    index = end;
  }
  return node('section', { class: 'rack-planner-face', 'aria-label': faces[face] },
    node('h3', {}, faces[face]), grid);
}

function drawGhost(diagram, slot, valid, name) {
  diagram.querySelectorAll('.rack-planner-ghost').forEach((ghost) => ghost.remove());
  const last = Number(diagram.dataset.lastUnit);
  const lower = Math.max(Number(diagram.dataset.firstUnit), slot.u_start);
  const upper = Math.min(last, slot.u_start + slot.u_height - 1);
  if (!Number.isInteger(lower) || !Number.isInteger(upper) || lower > upper) return;
  for (const face of slot.mount_depth === 'full' ? sides : [slot.face]) {
    const ghost = node('span', { class: 'rack-planner-ghost', 'data-face': face, 'data-valid': String(valid),
      'aria-hidden': 'true' }, node('span', {}, face === slot.face ? name : '全深跨面'));
    setGridSpan(ghost, last, lower, upper);
    diagram.querySelector(`[aria-label="${faces[face]}"] .rack-planner-rail`).append(ghost);
  }
}

function drawDiagram(rack, devices, choose, first = 1, last = rack.height) {
  return node('div', { class: 'rack-planner-diagram', 'data-first-unit': first, 'data-last-unit': last },
    sides.map((face) => drawFace(rack, face, devices, choose, first, last)));
}

function canPlace(rack, slot) {
  return Boolean(rack?.faces[slot.face].starts.includes(slot.u_start));
}

function conflictText(rack, slot, devices) {
  if (!Number.isInteger(slot.u_start) || slot.u_start < 1
      || slot.u_start + slot.u_height - 1 > rack.height) {
    return `安装范围须在 U1–U${rack.height} 以内。`;
  }
  const blocked = rack.faces[slot.face].slots.find((row) =>
    row.u >= slot.u_start && row.u < slot.u_start + slot.u_height &&
    row.state !== 'free' && !(row.state === 'half' && slot.mount_depth === 'half'));
  return blocked ? `发生冲突 · ${slotLabel(blocked, devices)}。` : '此处无法上架，请选择其他起始 U 位。';
}

export function openRackPlanner({ catalog, rack, device, request, onApply, returnFocus = document.activeElement }) {
  if (!catalog.racks.length) return;
  const devices = new Map(catalog.devices.map((item) => [item.id, item]));
  const sourceRack = isPlaced(device) ? catalog.racks.find((item) => item.id === device.rack_id) : null;
  const initialRack = rack ?? sourceRack ?? catalog.racks[0];
  const dialog = node('dialog', { class: 'editor rack-planner', 'aria-labelledby': 'rack-planner-title' });
  const close = button('关闭', () => dialog.close(), 'button quiet');
  const title = sourceRack ? '移位预演' : '上架预演';
  const subtitle = sourceRack ? `${deviceLabel(device)} · 当前 ${rackLabel(catalog, sourceRack)} · ${description(device)}`
    : device ? `${deviceLabel(device)} · 当前未安装到机柜` : '选择机柜与 U 位，核对正背面占用';
  const controls = node('div', { class: 'rack-planner-controls' });
  const rackSelect = select('planner_rack', catalog.racks.map((item) => [item.id, `${rackLabel(catalog, item)} · ${item.height}U`]));
  const faceSelect = select('planner_face', Object.entries(faces));
  const depthSelect = select('planner_depth', Object.entries(depths));
  const heightInput = node('input', { name: 'planner_height', type: 'number', min: '1', max: '255', step: '1' });
  const startInput = node('input', { name: 'planner_start', type: 'number', min: '1', step: '1' });
  rackSelect.value = initialRack.id;
  faceSelect.value = device?.face ?? 'front';
  depthSelect.value = device?.mount_depth ?? 'full';
  heightInput.value = device?.u_height ?? 2;
  startInput.value = device?.u_start ?? 1;
  startInput.max = initialRack.height;
  controls.append(label('目标机柜', rackSelect), label('安装面', faceSelect), label('安装深度', depthSelect),
    label('占用高度（U）', heightInput), label('起始 U 位', startInput));

  const status = node('p', { class: 'rack-planner-status', role: 'status' });
  const alternatives = node('div', { class: 'rack-planner-alternatives', 'aria-label': '可选的连续 U 位' });
  const view = node('div', { class: 'rack-planner-view' });
  const legend = node('ul', { class: 'rack-planner-legend', 'aria-label': '立面图例' },
    Object.entries({ available: '可用起点', occupied: '本面占用', full: '对面全深', unknown: '深度待核', half: '限半深共享' })
      .map(([kind, text]) => node('li', { 'data-kind': kind }, text)));
  const drag = node('button', { type: 'button', class: 'button rack-planner-drag', draggable: 'true' },
    '拖动拟装设备');
  drag.title = '拖到起始 U 位；也可以直接点选立面上的 U 位';
  const statusBox = node('div', { class: 'rack-planner-status-box' },
    node('div', { class: 'rack-planner-selection' }, status, drag), alternatives, legend);
  const currentPrint = button('打印当前立面', () => void printRack(false));
  const comparisonPrint = button('打印前后对照', () => void printRack(true));
  const confirm = button('确认带入', apply, 'button primary');
  const dismiss = button('返回预演', () => hideConfirmation());
  const confirmText = node('p', {});
  const confirmation = node('div', { class: 'rack-planner-confirm', hidden: '' }, confirmText,
    node('div', { class: 'rack-planner-confirm-actions' }, dismiss, confirm));
  const applyButton = button('带入设备表单', showConfirmation, 'button primary');
  const footer = node('footer', { class: 'editor-actions rack-planner-actions' },
    ...(onApply ? [confirmation] : []), currentPrint, comparisonPrint, ...(onApply ? [applyButton] : []));
  dialog.append(node('header', { class: 'dialog-head' },
    node('div', {}, node('h2', { id: 'rack-planner-title', class: 'dialog-title' }, title),
      node('p', { class: 'muted small-text' }, subtitle)), close),
    node('div', { class: 'rack-planner-body' }, controls, statusBox, view), footer);

  let checkedRack = null;
  let diagram = null;
  let ticket = 0;
  let printing = false;
  let printRoot = null;
  let dragging = false;
  let dragTarget = null;

  function selectedRack() {
    return catalog.racks.find((item) => String(item.id) === rackSelect.value);
  }

  function selectedSlot() {
    return { face: faceSelect.value, u_start: startInput.valueAsNumber, u_height: heightInput.valueAsNumber,
      mount_depth: depthSelect.value };
  }

  async function readRack(target, height, depth, exclude = false) {
    const query = new URLSearchParams({ rack_id: target.id, height, depth, face: 'any' });
    if (exclude && device?.id) query.set('exclude_device_id', device.id);
    const payload = await request(`rack-availability?${query}`);
    const found = payload.racks.find((item) => item.id === target.id);
    if (!found) throw new Error('未能读取当前机柜立面。');
    return found;
  }

  function hideConfirmation(restore = true) {
    if (confirmation.hidden) return;
    confirmation.hidden = true;
    if (restore === true) applyButton.focus({ preventScroll: true });
  }

  function showAlternatives(rack, slot) {
    const order = (starts) => [...starts]
      .sort((a, b) => Math.abs(a - (slot.u_start || 1)) - Math.abs(b - (slot.u_start || 1)))
      .slice(0, 3);
    const options = [slot.face, ...sides.filter((face) => face !== slot.face)].flatMap((face) =>
      order(rack.faces[face].starts.filter((start) => face !== slot.face || start !== slot.u_start)).map((start) =>
        button(`${faces[face]} ${units({ u_start: start, u_height: slot.u_height })}`,
          () => choose(face, start, true), 'button small rack-planner-alternative')));
    alternatives.replaceChildren(...options.length
      ? [node('span', { class: 'muted small-text' }, '其他可用位置'), ...options]
      : [node('span', { class: 'muted small-text' }, canPlace(rack, slot) ? '已显示唯一可用位置' : '该柜暂无符合条件的连续 U 位')]);
  }

  function refreshSelection() {
    const slot = selectedSlot();
    const target = selectedRack();
    const valid = canPlace(checkedRack, slot);
    hideConfirmation(false);
    currentPrint.disabled = !target || printing;
    comparisonPrint.disabled = !checkedRack || !Number.isInteger(slot.u_start) || printing;
    applyButton.disabled = !valid || printing;
    drag.disabled = !checkedRack || printing;
    if (!checkedRack) return;
    status.textContent = valid ? `${description(slot)} · 可用` : conflictText(checkedRack, slot, devices);
    status.dataset.state = valid ? 'available' : 'conflict';
    showAlternatives(checkedRack, slot);
    drawGhost(diagram, slot, valid, device?.name || '拟装设备');
    for (const row of diagram.querySelectorAll('button[data-u]')) {
      const u = Number(row.dataset.u);
      row.tabIndex = u === Math.min(checkedRack.height, Math.max(1, slot.u_start || 1)) ? 0 : -1;
      row.setAttribute('aria-pressed', String(row.dataset.face === slot.face && u === slot.u_start));
    }
  }

  function choose(face, start, focusRow = false) {
    faceSelect.value = face;
    startInput.value = start;
    refreshSelection();
    if (focusRow) {
      const row = diagram?.querySelector(`[data-face="${face}"][data-u="${start}"]`);
      row?.focus({ preventScroll: true });
      row?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }

  async function refreshRack() {
    const current = ++ticket;
    const target = selectedRack();
    const slot = selectedSlot();
    checkedRack = null;
    diagram = null;
    view.replaceChildren();
    alternatives.replaceChildren();
    status.dataset.state = '';
    refreshSelection();
    if (!target || !Number.isInteger(slot.u_height) || slot.u_height < 1 || slot.u_height > 255) {
      status.textContent = '请输入有效的占用高度（1–255U）。';
      return;
    }
    startInput.max = target.height;
    status.textContent = '正在核对目标机柜…';
    try {
      const rack = await readRack(target, slot.u_height, slot.mount_depth, true);
      if (!dialog.open || current !== ticket) return;
      checkedRack = rack;
      diagram = drawDiagram(rack, devices, choose);
      view.replaceChildren(diagram);
      refreshSelection();
    } catch (error) {
      if (!dialog.open || current !== ticket) return;
      status.textContent = error.message;
      status.dataset.state = 'conflict';
    }
  }

  function showConfirmation() {
    const slot = selectedSlot();
    if (!canPlace(checkedRack, slot)) return;
    confirmText.textContent = `将 ${rackLabel(catalog, selectedRack())} · ${description(slot)} 带入设备表单，核对后再保存。`;
    confirmation.hidden = false;
    confirm.focus();
  }

  function apply() {
    const rack = selectedRack();
    const slot = selectedSlot();
    if (confirmation.hidden || !rack || !canPlace(checkedRack, slot)) return;
    confirm.disabled = true;
    dialog.close();
    onApply({ rack, slot });
  }

  function clearPrint() {
    window.removeEventListener('afterprint', clearPrint);
    printRoot?.remove();
    printRoot = null;
    document.documentElement.classList.remove('rack-planner-printing');
  }

  async function printRack(compare) {
    const target = selectedRack();
    if (!target || printing) return;
    const slot = selectedSlot();
    if (compare && (!checkedRack || !Number.isInteger(slot.u_start))) return;
    const requests = [readRack(target, 1, 'half')];
    if (compare) requests.push(readRack(target, slot.u_height, slot.mount_depth, true));
    const separateSource = compare && sourceRack && sourceRack.id !== target.id;
    if (separateSource) requests.push(readRack(sourceRack, 1, 'half'), readRack(sourceRack, 1, 'half', true));
    printing = true;
    refreshSelection();
    try {
      const [originalTarget, plannedTarget, originalSource, plannedSource] = await Promise.all(requests);
      if (!dialog.open) return;
      const valid = compare && canPlace(plannedTarget, slot);
      clearPrint();
      printRoot = node('main', { class: 'rack-planner-print', 'aria-hidden': 'true' },
        node('header', {},
          node('h1', {}, compare ? '机柜上架前后对照 · 预演草稿' : '机柜当前立面'),
          node('p', {}, new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date())),
          ...(compare ? [
            node('p', {}, `${deviceLabel(device)} · 计划 ${rackLabel(catalog, target)} · ${description(slot)}`),
            node('p', {}, valid ? '预演草稿 · 此方案尚未保存。' : `预演草稿 · ${conflictText(plannedTarget, slot, devices)}`),
          ] : [])));
      const appendPage = (title, item, ghost = false) => {
        for (let last = item.height; last > 0; last -= 42) {
          const first = Math.max(1, last - 41);
          const range = item.height > 42 ? ` · U${first}–U${last}` : '';
          const diagram = drawDiagram(item, devices, null, first, last);
          if (ghost) drawGhost(diagram, slot, valid, device?.name || '拟装设备');
          printRoot.append(node('section', { class: 'rack-planner-print-page' },
            node('h2', {}, `${title} · ${rackLabel(catalog, item)} · ${item.height}U${range}`), diagram));
        }
      };
      if (separateSource) appendPage('当前 · 来源柜', originalSource);
      appendPage('当前', originalTarget);
      if (separateSource) appendPage('计划 · 来源柜移出', plannedSource);
      if (compare) appendPage('计划 · 目标柜', plannedTarget, true);
      document.body.append(printRoot);
      document.documentElement.classList.add('rack-planner-printing');
      window.addEventListener('afterprint', clearPrint, { once: true });
      window.print();
    } catch (error) {
      if (dialog.open) {
        status.textContent = error.message;
        status.dataset.state = 'conflict';
      }
      return;
    } finally {
      printing = false;
      currentPrint.disabled = !selectedRack();
      comparisonPrint.disabled = !checkedRack || !Number.isInteger(selectedSlot().u_start);
      applyButton.disabled = !canPlace(checkedRack, selectedSlot());
      drag.disabled = !checkedRack;
    }
  }

  function clearDrag() {
    dragTarget?.removeAttribute('data-drop-target');
    dragTarget = null;
  }

  drag.addEventListener('click', () => {
    const { face, u_start } = selectedSlot();
    choose(face, Math.min(checkedRack.height, Math.max(1, u_start || 1)), true);
  });
  drag.addEventListener('dragstart', (event) => {
    dragging = true;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', '拟装设备');
  });
  drag.addEventListener('dragend', () => {
    dragging = false;
    clearDrag();
  });
  view.addEventListener('dragover', (event) => {
    const row = event.target.closest('button[data-u]');
    if (!dragging || !row) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    if (dragTarget === row) return;
    clearDrag();
    dragTarget = row;
    row.setAttribute('data-drop-target', '');
  });
  view.addEventListener('dragleave', (event) => {
    if (!view.contains(event.relatedTarget)) clearDrag();
  });
  view.addEventListener('drop', (event) => {
    const row = event.target.closest('button[data-u]');
    if (!dragging || !row) return;
    event.preventDefault();
    dragging = false;
    clearDrag();
    choose(row.dataset.face, Number(row.dataset.u), true);
  });

  for (const control of [rackSelect, depthSelect]) control.addEventListener('change', () => void refreshRack());
  heightInput.addEventListener('input', () => void refreshRack());
  faceSelect.addEventListener('change', refreshSelection);
  startInput.addEventListener('input', refreshSelection);
  dialog.addEventListener('close', () => {
    ticket += 1;
    clearPrint();
    dialog.remove();
    if (!confirm.disabled && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
  });
  document.body.append(dialog);
  dialog.showModal();
  void refreshRack();
  return dialog;
}
