const stateLabels = {
  connected: '已关联',
  pending: '对端待核',
  free: '空闲',
  unknown: '未核实',
  restricted: '对端受限',
};

const matchLabels = { label: '线标匹配', position: '位置或端口匹配' };
const faceLabels = { front: '正面', rear: '背面' };

function rackPosition(endpoint) {
  const start = Number(endpoint.u_start);
  const height = Number(endpoint.u_height);
  const units = start > 0 && height > 1 ? `U${start}–U${start + height - 1}` : start > 0 ? `U${start}` : '';
  return [endpoint.rack_name, faceLabels[endpoint.face], units].filter(Boolean).join(' · ');
}

function endpointCard(endpoint, side, paired, element, deviceLink, showLabel) {
  let heading = element('span', { class: 'cable-endpoint-heading' },
    element('strong', {}, endpoint.device_name),
    element('code', { class: 'code cable-port-name' }, endpoint.port_name));
  const location = [endpoint.site_name, endpoint.room_name].filter(Boolean).join(' / ');
  const position = [rackPosition(endpoint), endpoint.device_code].filter(Boolean).join(' · ');
  const label = showLabel ? endpoint.label : '';
  const attrs = { class: 'cable-endpoint', 'data-cable-endpoint': side, 'data-port-id': endpoint.port_id };

  if (!endpoint.archived_at && endpoint.device_id && endpoint.port_id) {
    const link = deviceLink(endpoint);
    link.classList.add('cable-endpoint-link');
    link.dataset.cableEndpointLink = '';
    link.append(heading);
    heading = link;
  }

  return element('div', attrs,
    paired ? element('span', { class: 'cable-endpoint-side' }, side === 'local' ? '本端' : '对端') : null,
    heading,
    location ? element('span', { class: 'cable-endpoint-meta' }, location) : null,
    position ? element('span', { class: 'cable-endpoint-meta' }, position) : null,
    label ? rawLabel(element, label) : null,
    endpoint.archived_at ? element('span', { class: 'cable-endpoint-meta' }, '设备已归档') : null);
}

function rawLabel(element, label) {
  return element('span', { class: 'cable-endpoint-label' },
    element('span', {}, '线标'), element('code', { class: 'code' }, label));
}

export function renderCableSearchResults(payload, { element, deviceLink }) {
  if (!payload.results.length) {
    return element('p', { class: 'cable-search-empty muted small-text' }, '没有找到匹配的物理端口或线标。');
  }

  return element('ul', { class: 'cable-search-results', 'aria-label': '物理端口与接线结果' }, payload.results.map((result) => {
    const { local, state } = result;
    const peer = state === 'restricted' ? null : result.peer;
    const paired = Boolean(peer) || state === 'pending' || state === 'restricted';
    const peerCard = peer ? endpointCard(peer, 'peer', true, element, deviceLink, true)
      : element('div', { class: 'cable-endpoint cable-endpoint-unresolved', 'data-cable-endpoint': 'peer' },
        element('span', { class: 'cable-endpoint-side' }, '对端'),
        element('p', {}, state === 'restricted' ? '对端超出可见范围' : '对端位置待核实'),
        state === 'pending' && result.peer_label ? rawLabel(element, result.peer_label) : null);
    return element('li', { class: 'cable-search-result', 'data-cable-search-result': true, 'data-cable-state': state },
      element('div', { class: 'cable-result-head' },
        element('span', { class: 'cable-result-state' }, stateLabels[state] ?? stateLabels.unknown),
        matchLabels[result.match] ? element('span', { class: 'cable-result-match' }, matchLabels[result.match]) : null),
      element('div', { class: 'cable-search-endpoints', 'data-paired': paired },
        endpointCard(local, 'local', paired, element, deviceLink, state !== 'restricted'),
        paired ? [element('span', { class: 'cable-search-joint', 'aria-hidden': 'true' }, '↔'), peerCard] : null));
  }));
}
