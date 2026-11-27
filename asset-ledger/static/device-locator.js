import { buildDeviceSearch, normalizeSearchText } from './asset-search.js';

export function locationHash(deviceId, portId) {
  return `#locate/${encodeURIComponent(deviceId)}${portId == null ? '' : `?port=${encodeURIComponent(portId)}`}`;
}

export function openDeviceLocator(dialog, catalog, initialQuery, ui) {
  const { element, dialogHeader, deviceLocation, deviceAddressLabel, endpointLabel } = ui;
  const devices = buildDeviceSearch(catalog.devices, catalog.systems);
  const rooms = new Map(catalog.rooms.map((room) => [room.id, room]));
  const racks = new Map(catalog.racks.map((rack) => [rack.id, rack]));
  const input = element('input', {
    type: 'search', value: initialQuery, maxlength: 160, autocomplete: 'off', autofocus: true,
    placeholder: '设备、型号、机房、柜号、系统、IP 或端口', 'aria-label': '跨机房搜索',
  });
  const status = element('p', { class: 'muted small-text', role: 'status' });
  const list = element('ul', { class: 'locator-results', 'aria-label': '设备定位结果' });
  const limit = 80;

  function update() {
    const term = normalizeSearchText(input.value);
    list.replaceChildren();
    if (!term) {
      status.textContent = '在当前账号可访问的机房中搜索。';
      return;
    }
    const results = devices(term);
    const matched = new Set(results.map(({ device }) => device.id));
    for (const { device } of devices('')) {
      if (matched.has(device.id)) continue;
      const roomName = rooms.get(device.room_id)?.name;
      const rackName = racks.get(device.rack_id)?.name;
      if (normalizeSearchText(rackName).includes(term)) results.push({ device, location: `机柜 ${rackName}` });
      else if (normalizeSearchText(roomName).includes(term)) results.push({ device, location: `机房 ${roomName}` });
    }
    status.textContent = results.length > limit ? `找到 ${results.length} 台设备。显示前 ${limit} 台，请缩小条件。`
      : results.length ? `找到 ${results.length} 台设备` : '没有找到匹配的设备。';
    for (const match of results.slice(0, limit)) {
      const { device } = match;
      const reasons = [
        match.location, match.matchedModel && `型号 ${match.matchedModel}`,
        ...(match.addresses ?? []).map((address) => `地址 ${deviceAddressLabel(address)}`),
        ...(match.entries ?? []).map((entry) => `服务 ${endpointLabel(entry)}`),
        ...(match.systems ?? []).map((system) => `系统 ${system}`),
      ].filter(Boolean);
      const link = element('a', { href: locationHash(device.id), class: 'locator-result', onclick: () => dialog.close() },
        element('strong', {}, device.name), element('code', { class: 'code' }, device.code),
        element('span', { class: 'muted' }, deviceLocation(device)),
        element('small', { class: 'muted' }, reasons.slice(0, 3).join(' · ') || '名称或编号匹配'));
      list.append(element('li', {}, link));
    }
  }

  function moveFocus(event) {
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    const links = [...list.querySelectorAll('a')];
    if (!links.length) return;
    const index = links.indexOf(event.target);
    const next = event.key === 'ArrowDown' ? links[Math.min(index + 1, links.length - 1)]
      : index > 0 ? links[index - 1] : input;
    event.preventDefault();
    next.focus();
  }
  input.addEventListener('input', update);
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    list.querySelector('a')?.click();
  });
  const body = element('div', { class: 'locator-body', onkeydown: moveFocus }, input, status, list);
  dialog.replaceChildren(dialogHeader('locator-title', '跨机房搜索', null, dialog), body);
  update();
  dialog.showModal();
  input.focus();
}
