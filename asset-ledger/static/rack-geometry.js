/** 机柜与设备的共享几何常量及局部坐标计算（与渲染引擎解耦）。 */

export const RACK_UNIT = 0.12;
export const RACK_WIDTH = 1.98;
export const RACK_DEPTH = 2.35;
export const RACK_BOTTOM = -0.1605;
export const RACK_TOP_MARGIN = 0.1065;
export const DEVICE_HALF_WIDTH = 0.869;
export const MOUNT_HALF_Z = 0.025;
export const MOUNT_FULL_Z = RACK_DEPTH / 2 - 0.10;
export const PANEL_Z = MOUNT_FULL_Z - 0.020;
export const DETAIL_Z = MOUNT_FULL_Z + 0.003;
export const OPERATING_LAMP_X = 0.778;
export const OPERATING_LAMP_Z = DETAIL_Z + 0.009;

export const SURFACES = {
  frame: [0x232b31, 0.57, 0.27],
  rail: [0x525d64, 0.55, 0.34],
  trim: [0x3b454d, 0.52, 0.30],
  cover: [0x303a41, 0.65, 0.23],
  chassis: [0x3c454c, 0.68, 0.16],
  panel: [0x48515a, 0.62, 0.18],
  inset: [0x131a20, 0.78, 0.10],
  socket: [0x151d22, 0.74, 0.20],
  screw: [0x79848c, 0.49, 0.46],
  scale: [0x9ba9ae, 0.62, 0.16],
  foot: [0x252a2c, 0.86, 0.08],
  sidePanel: [0x27313a, 0.54, 0.35],
  handle: [0x485560, 0.43, 0.49],
};

export const PANEL_COLORS = {
  generic: 0x424c55,
  server: 0x596570,
  network: 0x35434b,
  power: 0x343b44,
  storage: 0x4c545f,
};

export const TYPE_ACCENTS = {
  generic: 0x8698a2,
  server: 0x7295b6,
  network: 0x547780,
  power: 0xd1a157,
  storage: 0x9d8daf,
};

export const STATUS_COLORS = {
  running: 0x3fa86b,
  unpowered: 0xd14d43,
  disabled: 0x7b8a94,
  unknown: 0xd89b32,
};

export const DEPTH_COLORS = {
  full: 0x3b6998,
  half: 0x4b93a8,
  unknown: 0xe5a131,
};

export function normalizeStatus(device) {
  const status = device?.operating_status;
  return Object.hasOwn(STATUS_COLORS, status) ? status : 'unknown';
}

export function normalizeDepth(device) {
  const depth = device?.mount_depth;
  return depth === 'full' || depth === 'half' ? depth : 'unknown';
}

export function rackVerticalBounds(rackHeight, unit = RACK_UNIT) {
  const height = rackHeight * unit;
  return { height, bottom: RACK_BOTTOM, top: height + RACK_TOP_MARGIN };
}

export function deviceMetrics(device, unit = RACK_UNIT) {
  const sign = device.face === 'front' ? 1 : -1;
  const full = normalizeDepth(device) === 'full';
  const front = device.face === 'front';
  const minY = (device.u_start - 1) * unit + 0.003;
  const maxY = (device.u_start - 1 + device.u_height) * unit - 0.003;
  const centerY = (device.u_start - 1 + device.u_height / 2) * unit;
  const faceHeight = device.u_height * unit - 0.006;
  const minZ = full || !front ? -MOUNT_FULL_Z : MOUNT_HALF_Z;
  const maxZ = full || front ? MOUNT_FULL_Z : -MOUNT_HALF_Z;
  const chassisMinZ = minZ + (full || front ? 0.035 : 0);
  const chassisMaxZ = maxZ - (full || !front ? 0.035 : 0);
  return {
    sign,
    full,
    front,
    minY,
    maxY,
    centerY,
    faceHeight,
    minZ,
    maxZ,
    chassisDepth: chassisMaxZ - chassisMinZ,
    chassisCenterZ: (chassisMinZ + chassisMaxZ) / 2,
  };
}

export function rackOccupancy(rack, devices) {
  const occupiedUnits = new Set();
  let unknownDepthCount = 0;
  const statusCounts = { running: 0, unpowered: 0, disabled: 0, unknown: 0 };
  for (const device of devices) {
    statusCounts[normalizeStatus(device)] += 1;
    if (normalizeDepth(device) === 'unknown') unknownDepthCount += 1;
    for (let offset = 0; offset < device.u_height; offset += 1) {
      occupiedUnits.add(device.u_start + offset);
    }
  }
  const usedU = occupiedUnits.size;
  const ratio = rack.height > 0 ? Math.min(1, usedU / rack.height) : 0;
  return { usedU, freeU: Math.max(0, rack.height - usedU), ratio, unknownDepthCount, statusCounts };
}

export function rackSummaryColor(rack, devices, mode) {
  const stats = rackOccupancy(rack, devices);
  if (mode === 'status') {
    if (!devices.length) return 0x9aa8a6;
    if (stats.statusCounts.unpowered > 0) return STATUS_COLORS.unpowered;
    if (stats.statusCounts.unknown > 0) return STATUS_COLORS.unknown;
    if (stats.statusCounts.running > 0) return STATUS_COLORS.running;
    return STATUS_COLORS.disabled;
  }
  if (mode === 'capacity') {
    if (stats.unknownDepthCount > 0) return DEPTH_COLORS.unknown;
    if (stats.ratio >= 0.85) return 0xcf5444;
    if (stats.ratio >= 0.5) return 0xd39636;
    return 0x3b8d7a;
  }
  return 0xffffff;
}
