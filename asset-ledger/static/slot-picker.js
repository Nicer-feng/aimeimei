const slotLabels = {
  free: '空位',
  occupied: '本面占用',
  full: '对面全深占用',
  unknown: '对面深度待核',
  half: '限半深共享',
};

export function createSlotPicker({ element, button, request, getPlacement, startInput }) {
  const status = element('p', { class: 'muted small-text', role: 'status' });
  const body = element('div', { class: 'slot-picker-faces' });
  const host = element('section', { class: 'slot-picker wide', 'aria-label': '目标机柜 U 位预览' },
    element('h3', {}, '目标机柜 U 位'), status, body);
  let query = '';
  let ticket = 0;
  let rack;

  function refreshSelection() {
    if (!rack) return;
    const { face, height, depth } = getPlacement();
    const start = Number(startInput.value);
    const current = rack.faces[face];
    const allowed = current?.starts.includes(start);
    const end = start + height - 1;
    const blocked = current?.slots.find((slot) => slot.u >= start && slot.u <= end
      && slot.state !== 'free' && !(slot.state === 'half' && depth === 'half'));
    const message = allowed ? '' : (end > rack.height || start < 1 ? `所选区间超出 ${rack.height}U。`
      : (blocked ? `U${blocked.u} ${slotLabels[blocked.state]}${blocked.code ? `（${blocked.code}）` : ''}。` : '这段 U 位不可用，请另选起始位。'));
    startInput.setCustomValidity(message);
    status.textContent = allowed
      ? `${face === 'front' ? '正面' : '背面'} U${start}${end > start ? `–U${end}` : ''} 可用`
      : message;
    status.classList.toggle('slot-conflict', Boolean(message));
    for (const item of body.querySelectorAll('button[data-u]')) {
      const u = Number(item.dataset.u);
      item.setAttribute('aria-pressed', String(item.dataset.face === face && u >= start && u <= end));
    }
  }

  function render() {
    const { face } = getPlacement();
    body.replaceChildren(...['front', 'rear'].map((side) => {
      const { starts, slots } = rack.faces[side];
      const allowed = new Set(starts);
      return element('section', { class: 'slot-picker-face', 'aria-label': side === 'front' ? '正面' : '背面' },
        element('h4', {}, side === 'front' ? '正面' : '背面', side === face ? '（当前安装面）' : ''),
        element('div', { class: 'slot-picker-units' }, [...slots].reverse().map((slot) => {
          const label = `U${slot.u} · ${slotLabels[slot.state]}${slot.code ? ` · ${slot.code}` : ''}`;
          const selectable = side === face && allowed.has(slot.u);
          return button(`U${slot.u}`, () => {
            startInput.value = slot.u;
            refreshSelection();
          }, `slot-picker-unit ${selectable ? 'slot-available' : ''}`, {
            'data-u': slot.u, 'data-face': side, 'data-state': slot.state,
            'aria-label': label, title: label, disabled: !selectable,
          });
        })),
      );
    }));
    refreshSelection();
  }

  async function refresh({ reload = false } = {}) {
    const { rackId, face, height, depth, exclude } = getPlacement();
    if (!rackId || !Number.isInteger(height) || height < 1) {
      query = '';
      ticket += 1;
      rack = null;
      body.replaceChildren();
      startInput.setCustomValidity('');
      status.textContent = '选择机柜并填写占用高度后查看 U 位。';
      status.classList.remove('slot-conflict');
      return;
    }
    const args = new URLSearchParams({ rack_id: rackId, face, height, depth });
    if (exclude) args.set('exclude_device_id', exclude);
    const next = args.toString();
    if (!reload && query === next) {
      refreshSelection();
      return;
    }
    query = next;
    const current = ++ticket;
    rack = null;
    body.replaceChildren();
    startInput.setCustomValidity('');
    status.textContent = '正在核对目标机柜…';
    status.classList.remove('slot-conflict');
    try {
      const payload = await request(`rack-availability?${next}`);
      if (current !== ticket || !host.isConnected) return;
      rack = payload.racks[0];
      if (rack) render();
      else status.textContent = '当前机柜无可查看的 U 位。';
    } catch (error) {
      if (current !== ticket || !host.isConnected) return;
      query = '';
      status.textContent = error.message;
      status.classList.add('slot-conflict');
    }
  }

  return { host, refresh };
}
