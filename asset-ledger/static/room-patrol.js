import { operatingStatus, operatingStatusLabel, units } from './rack.js?v=operating-status';

const rackOrder = new Intl.Collator('zh-CN', { numeric: true });
const checkTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
const recordedLabels = { device: '巡检核实', placement: '安装位置缺项', ports: '对端缺项' };
const queues = [
  { id: 'all', name: '全部', includes: () => true, empty: '这个柜位没有设备。' },
  { id: 'device', name: '待核', includes: (device) => device.pending, empty: '这个柜位的设备都已有核实记录。' },
  { id: 'placement', name: '缺 U 位', includes: (device) => device.missing_u, empty: '这个柜位没有待补安装位置的设备。' },
  { id: 'ports', name: '缺对端', includes: (device) => device.missing_peers > 0, empty: '这个柜位没有已登记但缺少对端的接线。' },
];

export function openRoomPatrol({ roomId, request, canWrite, onLocate, element, button }) {
  const dialog = element('dialog', { class: 'room-patrol-dialog', 'aria-labelledby': 'room-patrol-title' });
  const subtitle = element('p', { class: 'muted small-text' });
  const report = element('p', { class: 'muted small-text', role: 'status' });
  const progress = element('progress', { max: 1, value: 0, 'aria-label': '全房设备核实进度' });
  const error = element('p', { class: 'form-error', role: 'alert', hidden: true });
  const rackSelect = element('select', {
    id: 'room-patrol-rack', 'aria-label': '巡检机柜', onchange: renderQueue,
  });
  const previous = button('上一柜', () => moveRack(-1), 'small');
  const next = button('下一柜', () => moveRack(1), 'small');
  const queueControls = queues.map((queue) => button(queue.name, () => {
    activeQueue = queue;
    if (queue.id === 'placement' && devices.some(queue.includes)) rackSelect.value = 'unplaced';
    renderQueue();
  }, 'small'));
  const toolbar = element('div', { class: 'room-patrol-toolbar', hidden: true },
    element('div', { class: 'room-patrol-progress' }, progress, report),
    element('div', { class: 'room-patrol-racks' }, previous, rackSelect, next),
    element('div', { class: 'room-patrol-filters', role: 'group', 'aria-label': '筛选巡检项目' }, queueControls));
  const list = element('ul', { class: 'room-patrol-devices', 'aria-label': '巡检设备' });
  const body = element('div', { class: 'room-patrol-scroll' }, list, error);
  const groups = new Map();
  let devices = [];
  let activeQueue = queues[0];
  let activeForm;
  let saving = false;

  function dismiss() {
    if (dialog.open) dialog.close();
    dialog.remove();
  }

  function moveRack(delta) {
    rackSelect.selectedIndex += delta;
    renderQueue();
    if ((delta < 0 && previous.disabled) || (delta > 0 && next.disabled)) rackSelect.focus();
  }

  function locationLabel(device) {
    if (device.rack_id != null) return `${device.face === 'rear' ? '背面' : '正面'} · ${units(device)}`;
    return device.workstation || '安装位置待补';
  }

  function recordDetails(device) {
    const records = Object.entries(recordedLabels).map(([kind, label]) => {
      const check = device.checks[kind];
      if (!check) return null;
      return element('li', {},
        element('strong', {}, label), ' · ',
        element('time', { datetime: check.checked_at }, checkTime.format(new Date(check.checked_at))),
        ' · ', check.checked_by,
        check.note && element('p', { class: 'room-patrol-note' }, check.note));
    }).filter(Boolean);
    if (device.verified_on && !device.checks.device) {
      records.unshift(element('li', {}, '台账上次核实 · ', element('time', { datetime: device.verified_on }, device.verified_on)));
    }
    return records.length ? element('ul', { class: 'room-patrol-records', 'aria-label': '最近核实记录' }, records) : null;
  }

  function openCheckForm(device, card, trigger, kind) {
    if (saving) return;
    activeForm?.remove();
    const confirmingDevice = kind === 'device';
    const note = element('textarea', {
      name: 'note', rows: 2, maxlength: 500, required: !confirmingDevice,
      placeholder: confirmingDevice ? '填写现场核对情况' : '填写已看到的情况或需要补查的内容',
    });
    const formError = element('p', { class: 'form-error', role: 'alert', hidden: true });
    const submit = element('button', { type: 'submit', class: 'button primary' },
      confirmingDevice ? '保存核实' : '保存缺项记录');
    const cancel = button('取消', () => { activeForm.remove(); activeForm = null; trigger.focus(); }, 'quiet');
    const form = element('form', { class: 'room-patrol-form', onsubmit: save },
      element('label', {}, confirmingDevice ? '巡检备注（选填）' : '缺项备注', note), formError,
      element('div', { class: 'room-patrol-actions' }, cancel, submit));
    activeForm = form;
    card.append(form);
    note.focus();

    async function save(event) {
      event.preventDefault();
      if (saving) return;
      saving = true;
      submit.disabled = cancel.disabled = note.disabled = true;
      formError.hidden = true;
      try {
        const check = await request('room-patrol', {
          method: 'POST', data: { room_id: roomId, device_id: device.id, kind, note: note.value },
        });
        if (!dialog.open) return;
        device.checks[check.kind] = check;
        if (confirmingDevice) device.pending = false;
        renderQueue({ message: `${device.name}已保存${confirmingDevice ? '核实记录' : '缺项记录'}。`, keepScroll: true });
        const action = list.querySelector(`[data-patrol-device-id="${device.id}"] .room-patrol-record`);
        if (action) action.focus({ preventScroll: true });
        else queueControls[queues.indexOf(activeQueue)].focus();
      } catch (requestError) {
        formError.textContent = requestError.message;
        formError.hidden = false;
      } finally {
        saving = false;
        submit.disabled = cancel.disabled = note.disabled = false;
      }
    }
  }

  function deviceCard(device) {
    const kind = activeQueue.id === 'all' ? 'device' : activeQueue.id;
    const card = element('li', { class: 'room-patrol-device', 'data-patrol-device-id': device.id },
      element('div', { class: 'room-patrol-device-title' },
        element('strong', {}, device.name),
        element('span', { class: `room-patrol-mark ${device.pending ? 'is-pending' : ''}` }, device.pending ? '待核' : '已核')),
      element('div', { class: 'room-patrol-device-facts muted' },
        element('code', { class: 'code' }, device.code),
        element('span', {}, locationLabel(device)),
        element('span', { class: `room-patrol-status is-${operatingStatus(device)}` }, operatingStatusLabel(device)),
        device.missing_peers > 0 && element('span', {}, `${device.missing_peers} 个对端待补`),
        activeQueue.id === 'ports' && element('span', {}, `共 ${device.port_count} 口已登记`)),
      recordDetails(device));
    const locate = button('定位设备', () => { dismiss(); onLocate(device.id); }, 'small quiet',
      { 'aria-label': `定位设备 ${device.name}` });
    const record = canWrite && button(kind === 'device' ? '记录核实' : '记录缺项',
      () => openCheckForm(device, card, record, kind), 'room-patrol-record small',
      { 'aria-label': `${kind === 'device' ? '记录核实' : '记录缺项'} ${device.name}` });
    card.append(element('div', { class: 'room-patrol-actions' }, locate, record));
    return card;
  }

  function renderQueue({ message = '', keepScroll = false } = {}) {
    activeForm = null;
    const scoped = groups.get(rackSelect.value) ?? [];
    const roomChecked = devices.filter((device) => !device.pending).length;
    const rackChecked = scoped.filter((device) => !device.pending).length;
    progress.max = Math.max(1, devices.length);
    progress.value = roomChecked;
    report.textContent = `${message}本柜已核 ${rackChecked}/${scoped.length} · 全房已核 ${roomChecked}/${devices.length}`;
    previous.disabled = rackSelect.selectedIndex < 1;
    next.disabled = rackSelect.selectedIndex >= rackSelect.options.length - 1;
    queueControls.forEach((control, index) => {
      const queue = queues[index];
      const candidates = queue.id === 'placement' ? devices : scoped;
      control.textContent = `${queue.name} ${candidates.filter(queue.includes).length}`;
      control.setAttribute('aria-pressed', String(queue === activeQueue));
    });
    const visible = scoped.filter(activeQueue.includes);
    list.replaceChildren(...(visible.length ? visible.map(deviceCard) : [
      element('li', { class: 'empty' }, rackSelect.options.length ? activeQueue.empty : '本机房暂无机柜和设备。'),
    ]));
    if (!keepScroll) body.scrollTop = 0;
  }

  async function load() {
    error.hidden = true;
    loading.hidden = false;
    retry.hidden = true;
    body.setAttribute('aria-busy', 'true');
    try {
      const data = await request(`room-patrol?room_id=${encodeURIComponent(roomId)}`);
      if (!dialog.open) return;
      subtitle.textContent = canWrite ? data.room.name : `${data.room.name} · 仅查看`;
      devices = data.devices;
      for (const device of devices) {
        const key = String(device.rack_id ?? 'unplaced');
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(device);
      }
      const racks = [...data.racks].sort((a, b) => rackOrder.compare(a.name, b.name));
      rackSelect.append(...racks.map((rack) => element('option', { value: rack.id }, rack.name)));
      if (groups.has('unplaced')) rackSelect.append(element('option', { value: 'unplaced' }, '未分柜'));
      toolbar.hidden = !rackSelect.options.length;
      renderQueue();
    } catch (requestError) {
      error.textContent = requestError.message;
      error.hidden = retry.hidden = false;
    } finally {
      body.removeAttribute('aria-busy');
      loading.hidden = true;
    }
  }

  const loading = element('p', { class: 'muted', role: 'status' }, '正在加载巡检清单…');
  const retry = button('重试', load, 'small', { hidden: true });
  body.prepend(loading);
  body.append(retry);
  dialog.append(element('header', { class: 'dialog-head' },
    element('div', {}, element('h2', { id: 'room-patrol-title', class: 'dialog-title' }, '机房巡检'), subtitle),
    button('关闭', dismiss, 'quiet', { autofocus: true })), toolbar, body);
  dialog.addEventListener('close', () => dialog.remove(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
  void load();
  return dismiss;
}
