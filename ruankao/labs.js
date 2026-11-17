const vlanSteps = [
  {
    title: '准备发送',
    detail: '假设两台主机和网关的 ARP 缓存为空。先想一想：A 访问另一个子网里的 B 时，第一次 ARP 要查询谁的 MAC？',
    active: ['a']
  },
  {
    title: '判断目的地址是否在本地网段',
    detail: 'A 用 /24 掩码比较 192.168.10.10 和 192.168.20.20，发现目标在其他网段，因此下一跳是网关 192.168.10.1。',
    active: ['a']
  },
  {
    title: '用 ARP 找到网关的 MAC',
    detail: 'A 在 VLAN 10 广播询问 192.168.10.1 的 MAC。接入口上传的是无标签帧，交换机在 Trunk 上加 VLAN 10 标签。网关回复自己的 VLAN 10 接口 MAC。',
    active: ['a', 'switch', 'trunk', 'router']
  },
  {
    title: '网关为目标主机发出 ARP',
    detail: 'A 把 IP 包封在发给网关 MAC 的帧里。网关查路由，发现目标网段直连 VLAN 20，便在 VLAN 20 内广播询问 B 的 MAC。交换机把广播转发给 B，B 回复自己的 MAC。',
    active: ['switch', 'trunk', 'router', 'b']
  },
  {
    title: '网关用新的二层帧转发给 B',
    detail: '目的 IP 保持为 192.168.20.20。网关把二层目的 MAC 换成 B 的 MAC，发出带 VLAN 20 标签的帧。交换机从 B 的接入口送出无标签帧，B 收到数据。',
    active: ['switch', 'trunk', 'router', 'b']
  }
];

const vlanBlocked = {
  title: 'VLAN 20 的 ARP 在 Trunk 处被丢弃',
  detail: 'A 仍能找到 VLAN 10 的网关。网关收到 IP 包、查到 VLAN 20 后发出 ARP，但交换机的 Trunk 允许列表中没有 VLAN 20。B 收不到 ARP，网关也得不到 B 的 MAC，所以无法交付数据。',
  active: ['router', 'trunk'],
  blocked: true
};

const routes = [
  { network: '10.0.0.0', prefix: 8, nextHop: '192.0.2.1', interface: 'GE0/0' },
  { network: '10.24.0.0', prefix: 16, nextHop: '192.0.2.2', interface: 'GE0/0' },
  { network: '10.24.8.0', prefix: 24, nextHop: '192.0.2.3', interface: 'GE0/0' },
  { network: '0.0.0.0', prefix: 0, nextHop: '192.0.2.254', interface: 'GE0/0' }
];
const destinations = ['10.24.8.40', '10.24.42.9', '10.55.3.20', '203.0.113.80'];

function toUint32(address) {
  return address.split('.').reduce((value, octet) => value * 256 + Number(octet), 0);
}

function matchesPrefix(address, route) {
  if (route.prefix === 0) return true;
  const hostBits = 32 - route.prefix;
  return (toUint32(address) >>> hostBits) === (toUint32(route.network) >>> hostBits);
}

function makeElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content) element.textContent = content;
  return element;
}

function attachLab(container, title, description) {
  const lab = makeElement('section', 'lab');
  lab.append(
    makeElement('h3', 'lab-title', title),
    makeElement('p', 'lab-intro', description)
  );
  container.replaceChildren(lab);
  return lab;
}

function makeSelect(labelText, values) {
  const field = makeElement('label', 'lab-field');
  const select = makeElement('select', 'lab-select');
  for (const [value, label] of values) {
    const option = makeElement('option', '', label);
    option.value = value;
    select.append(option);
  }
  field.append(makeElement('span', 'lab-label', labelText), select);
  return { field, select };
}

function stepControls(onChange) {
  const controls = makeElement('div', 'lab-controls');
  const back = makeElement('button', 'lab-button', '上一步');
  const next = makeElement('button', 'lab-button lab-button-primary', '下一步');
  const reset = makeElement('button', 'lab-button lab-button-reset', '重置');
  for (const button of [back, next, reset]) button.type = 'button';
  back.addEventListener('click', () => onChange('back'));
  next.addEventListener('click', () => onChange('next'));
  reset.addEventListener('click', () => onChange('reset'));
  controls.append(back, next, reset);

  return {
    controls,
    update(step, count) {
      back.disabled = step === 0;
      next.disabled = step === count - 1;
      next.textContent = step === 0 ? '开始演示' : step === count - 1 ? '演示完成' : '下一步';
    }
  };
}

function changeStep(action, current, count) {
  if (action === 'back') return Math.max(0, current - 1);
  if (action === 'next') return Math.min(count - 1, current + 1);
  return 0;
}

function statusPanel() {
  const status = makeElement('div', 'lab-status');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-atomic', 'true');
  const counter = makeElement('span', 'lab-counter');
  const title = makeElement('strong', 'lab-status-title');
  const detail = makeElement('p', 'lab-status-detail');
  status.append(counter, title, detail);
  return {
    status,
    update(step, count, entry) {
      status.classList.toggle('lab-status-blocked', Boolean(entry.blocked));
      counter.textContent = step === 0 ? '演示预备' : `步骤 ${step} / ${count - 1}`;
      title.textContent = entry.title;
      detail.textContent = entry.detail;
    }
  };
}

function topologyNode(key, title, detail) {
  const node = makeElement('div', `lab-node lab-node-${key}`);
  node.append(makeElement('strong', 'lab-node-title', title), makeElement('span', 'lab-node-detail', detail));
  return node;
}

function linkSegment(key, label) {
  return makeElement('div', `lab-link lab-link-${key}`, label);
}

function mountVlanLab(container) {
  const lab = attachLab(container, '跟踪一次跨 VLAN 通信', '主机 A 要给主机 B 发送数据。先预测 A 会向谁发 ARP，再观察每一跳。');
  const { field, select } = makeSelect('交换机 Trunk 允许列表', [
    ['all', '允许 VLAN 10 和 VLAN 20'],
    ['10', '仅允许 VLAN 10']
  ]);
  const diagram = makeElement('div', 'lab-diagram');
  const nodes = {
    a: topologyNode('a', '主机 A · VLAN 10', '192.168.10.10/24'),
    switch: topologyNode('switch', '二层交换机', '两台主机各连接一个 Access 口'),
    b: topologyNode('b', '主机 B · VLAN 20', '192.168.20.20/24'),
    router: topologyNode('router', '三层网关', '192.168.10.1 / 192.168.20.1'),
    trunk: linkSegment('trunk', '802.1Q Trunk')
  };
  const leftLink = linkSegment('left', 'Access · VLAN 10');
  const rightLink = linkSegment('right', 'Access · VLAN 20');
  diagram.append(nodes.router, nodes.trunk, nodes.a, leftLink, nodes.switch, rightLink, nodes.b);
  const { status, update } = statusPanel();
  let current = 0;
  let steps = vlanSteps;

  const controls = stepControls((action) => {
    current = changeStep(action, current, steps.length);
    render();
  });

  function render() {
    const entry = steps[current];
    for (const [key, node] of Object.entries(nodes)) {
      node.classList.toggle('lab-active', entry.active.includes(key));
    }
    leftLink.classList.toggle('lab-active', entry.active.includes('a') && entry.active.includes('switch'));
    rightLink.classList.toggle('lab-active', entry.active.includes('b') && entry.active.includes('switch'));
    nodes.trunk.classList.toggle('lab-link-blocked', Boolean(entry.blocked));
    nodes.trunk.textContent = entry.blocked ? 'Trunk · VLAN 20 丢弃' : '802.1Q Trunk';
    update(current, steps.length, entry);
    controls.update(current, steps.length);
  }

  select.addEventListener('change', () => {
    current = 0;
    steps = select.value === '10' ? [...vlanSteps.slice(0, 3), vlanBlocked] : vlanSteps;
    render();
  });

  lab.append(field, diagram, status, controls.controls);
  render();
}

function mountRouteLab(container) {
  const lab = attachLab(container, '路由表怎么选下一跳', '切换目的地址，看看哪些路由先通过前缀匹配，再选出最长的前缀。假设表内路由都已生效，下一跳均可经 GE0/0 到达。');
  const { field, select } = makeSelect('目的地址', destinations.map((ip) => [ip, ip]));
  const table = makeElement('table', 'lab-table');
  const heading = makeElement('tr', 'lab-table-heading');
  for (const label of ['目的前缀', '下一跳', '结果']) {
    const th = makeElement('th', 'lab-table-header', label);
    th.scope = 'col';
    heading.append(th);
  }
  const head = makeElement('thead');
  head.append(heading);
  const body = makeElement('tbody');
  const rows = routes.map((route) => {
    const row = makeElement('tr', 'lab-route');
    const badge = makeElement('span', 'lab-route-result');
    const result = makeElement('td', 'lab-cell');
    result.append(badge);
    row.append(
      makeElement('td', 'lab-cell lab-address', `${route.network}/${route.prefix}`),
      makeElement('td', 'lab-cell lab-address', route.nextHop),
      result
    );
    body.append(row);
    return { route, row, badge };
  });
  table.append(head, body);

  const { status, update } = statusPanel();
  const lastStep = 3;
  let current = 0;
  const controls = stepControls((action) => {
    current = changeStep(action, current, lastStep + 1);
    render();
  });

  function render() {
    const destination = select.value;
    const matching = routes.filter((route) => matchesPrefix(destination, route));
    const best = matching.reduce((longest, route) => route.prefix > longest.prefix ? route : longest);
    const steps = [
      { title: '观察目的 IP 和路由表', detail: '先猜哪条前缀会胜出。表中顺序可以变化，最终结果取决于匹配成功的前缀里谁最具体。' },
      { title: '找出所有匹配的前缀', detail: `目的地址 ${destination} 匹配 ${matching.length} 条路由。每条路由只比较斜线后所指定的位数，/0 匹配任何地址。` },
      { title: '选出匹配成功的最长前缀', detail: `匹配项里 ${best.network}/${best.prefix} 最具体，因此选中这条。` },
      { title: '按所选路由转发', detail: `从 ${best.interface} 把包交给 ${best.nextHop}。IP 包的目的地址仍是 ${destination}，下一跳只决定接下来把包交给谁。` }
    ];

    for (const { route, row, badge } of rows) {
      const matched = current > 0 && matching.includes(route);
      const selected = current > 1 && route === best;
      row.classList.toggle('lab-route-matched', matched);
      row.classList.toggle('lab-route-selected', selected);
      badge.textContent = selected ? '已选中' : matched ? '匹配' : current ? '不匹配' : '待检查';
    }

    update(current, steps.length, steps[current]);
    controls.update(current, steps.length);
  }

  select.addEventListener('change', () => {
    current = 0;
    render();
  });
  lab.append(field, table, status, controls.controls);
  render();
}

export function mountLab(container, kind) {
  if (kind === 'vlan') mountVlanLab(container);
  if (kind === 'route') mountRouteLab(container);
}
