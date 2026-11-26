export function normalizeSearchText(value) {
  return String(value ?? '').trim().normalize('NFKC').toLowerCase();
}

function modelKey(text) {
  return text.replace(/[\s\p{Pd}]+/gu, '');
}

function parsePort(value) {
  const text = String(value ?? '');
  if (!/^\d{1,5}$/.test(text)) return null;
  const port = Number(text);
  return port >= 1 && port <= 65535 ? port : null;
}

function hostKey(value) {
  const text = normalizeSearchText(value).replace(/^\[([^\]]+)\]$/, '$1');
  if (!text.includes(':')) return text.replace(/\.$/, '');
  try {
    return new URL(`http://[${text}]/`).hostname.slice(1, -1);
  } catch {
    return text;
  }
}

function isIpAddress(text) {
  return text.includes(':') ||
    (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(text) && text.split('.').every((octet) => Number(octet) <= 255));
}

function parseQuery(query) {
  const term = normalizeSearchText(query);
  const typedPort = term.match(/^(?:端口|port)\s*[:=]?\s*(\d+)$/);
  if (typedPort) return { term, kind: 'port', port: parsePort(typedPort[1]) };

  const combined = term.match(/^(\[[^\]]+\]|[^\s:]+)\s*:\s*(\d+)$/) ??
    term.match(/^(\S*[.:]\S*)\s+(?:\+\s*)?(?:(?:端口|port)\s*[:=]?\s*)?(\d+)$/);
  if (combined) return { term, kind: 'endpoint', host: hostKey(combined[1]), port: parsePort(combined[2]) };

  const host = hostKey(term);
  return { term, kind: 'text', host, exactHost: isIpAddress(host), port: parsePort(term) };
}

function serviceEndpoints(entry) {
  const endpoints = [];
  const host = String(entry.host ?? '').trim();
  const port = parsePort(entry.port);
  if (host || port !== null) endpoints.push({ host, key: hostKey(host), port });
  if (entry.url) {
    try {
      const url = new URL(entry.url);
      const defaultPort = url.protocol === 'https:' ? 443 : url.protocol === 'http:' ? 80 : null;
      const urlPort = parsePort(url.port) ?? defaultPort ?? port;
      const key = hostKey(url.hostname);
      if (key && !endpoints.some((endpoint) => endpoint.key === key && endpoint.port === urlPort)) {
        endpoints.push({ host: url.hostname, key, port: urlPort });
      }
    } catch {
      // 旧记录中无法解析的访问地址仍可在设备详情里查看。
    }
  }
  return endpoints;
}

function matchHost(key, query) {
  if (!key || !query.host || query.port !== null && query.kind === 'text') return false;
  return query.exactHost || query.kind === 'endpoint' ? key === query.host : key.includes(query.host);
}

function matchEndpoint(endpoint, query) {
  const portMatches = query.port !== null && endpoint.port === query.port;
  if (query.kind === 'port') return portMatches;
  if (query.kind === 'endpoint') return portMatches && matchHost(endpoint.key, query);
  return portMatches || matchHost(endpoint.key, query);
}

export function deviceAddressLabel(address) {
  return typeof address === 'string' ? address : address?.address ?? address?.host ?? '';
}

export function isDeviceArchived(device) {
  return Boolean(device.archived_at || device.archived === true);
}

export function buildDeviceSearch(devices, systems, { includeArchived = false } = {}) {
  const index = new Map();
  for (const device of devices) {
    if (!includeArchived && isDeviceArchived(device)) continue;
    index.set(String(device.id), {
      device,
      name: normalizeSearchText(device.name),
      code: normalizeSearchText(device.code),
      model: modelKey(normalizeSearchText(device.model)),
      addresses: (device.addresses ?? []).map((address) => ({ address, key: hostKey(deviceAddressLabel(address)) })),
      deployments: [],
    });
  }
  for (const system of systems) {
    const name = normalizeSearchText(system.name);
    for (const deployment of system.deployments ?? []) {
      const record = index.get(String(deployment.device_id));
      if (!record) continue;
      record.deployments.push({
        system: system.name,
        name,
        entries: (deployment.entries ?? []).map((entry) => ({ entry, endpoints: serviceEndpoints(entry) })),
      });
    }
  }
  return (input) => {
    const query = parseQuery(input);
    const textQuery = query.kind === 'text';
    const modelTerms = textQuery && !query.exactHost ? query.term.split(/\s+/).map(modelKey).filter(Boolean) : [];
    const results = [];
    for (const record of index.values()) {
      const result = { device: record.device, systems: [], entries: [], addresses: [] };
      if (!query.term) {
        results.push(result);
        continue;
      }
      const deviceMatches = textQuery && (record.name.includes(query.term) || record.code.includes(query.term));
      if (modelTerms.length && modelTerms.every((term) => record.model.includes(term))) {
        result.matchedModel = record.device.model;
      }
      if (textQuery) {
        result.addresses = record.addresses.filter(({ key }) => matchHost(key, query)).map(({ address }) => address);
      }
      const names = new Set();
      for (const { name, system, entries } of record.deployments) {
        if (textQuery && name.includes(query.term)) names.add(system);
        for (const { entry, endpoints } of entries) {
          const matchedEndpoint = endpoints.find((endpoint) => matchEndpoint(endpoint, query));
          if (!matchedEndpoint) continue;
          names.add(system);
          result.entries.push({
            ...entry, system, matchedHost: matchedEndpoint.host, matchedPort: matchedEndpoint.port,
          });
        }
      }
      result.systems = [...names];
      if (deviceMatches || result.matchedModel || names.size || result.addresses.length) results.push(result);
    }
    return results;
  };
}

export function endpointLabel(entry) {
  const host = entry.matchedHost ?? entry.host;
  const port = entry.matchedPort === undefined ? entry.port : entry.matchedPort;
  const displayHost = host?.includes(':') && !host.startsWith('[') && port ? `[${host}]` : host;
  const endpoint = displayHost && port ? `${displayHost}:${port}` : displayHost || (port ? `端口 ${port}` : '');
  return [entry.protocol, endpoint].filter(Boolean).join(' ');
}

function csvCell(value) {
  let text = Array.isArray(value) ? value.join('；') : String(value ?? '');
  if (typeof value !== 'number') {
    const prefix = text.normalize('NFKC');
    if (/^[ \uFEFF]*[\t\r\n]/.test(prefix) || /^[\s\u200B-\u200D\uFEFF]*[=+\-@]/.test(prefix)) text = `'${text}`;
  }
  return `"${text.replaceAll('"', '""')}"`;
}

export function downloadDeviceCsv(devices, { location = () => '', project = () => '', filename = '设备台账.csv' } = {}) {
  const statuses = { running: '运行中', unpowered: '未通电', disabled: '已停用', unknown: '待核实' };
  const rows = [[
    '设备编号', '设备名称', '类型', '品牌型号', '序列号', '位置', '设备地址', '运行状态',
    '用途', '归属', '填报人', '维护人', '最近核实时间', '购置时间', '价格', '关联项目',
  ]];
  for (const device of devices) {
    rows.push([
      device.code, device.name, device.type, device.model, device.serial, location(device),
      (device.addresses ?? []).map(deviceAddressLabel), statuses[device.operating_status] ?? '待核实',
      device.purpose, device.ownership, device.reporter, device.maintainer, device.verified_on,
      device.purchased_on, device.price ?? '未单列', project(device),
    ]);
  }
  const csv = '\uFEFF' + rows.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
