import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import {
  DETAIL_Z, DEVICE_HALF_WIDTH, RACK_DEPTH, RACK_UNIT, RACK_WIDTH,
  deviceMetrics, normalizeDepth, normalizeStatus, rackOccupancy, rackVerticalBounds,
} from './rack-geometry.js';
import {
  animateOperatingLamps, buildRackFineDetails, buildRackOverviewLayer, createDeviceSelectionLabel,
  createDeviceSelectionOutline, createRackPalette, projectCabinetRect, projectScenePoint,
} from './rack-3d-model.js';
import { createContactShadowTexture, createFloorTileTexture, createRackEnvironment } from './rack-textures.js';
import { buildRoomLighting } from './room-immersive.js';
import { operatingStatusLabel } from './rack.js?v=operating-status';

const COLUMN_GAP = 1.21;
const ROW_GAP = 2.30;
const RACK_SCALE = 0.535;
const FLOOR_TILE_SIZE = RACK_UNIT * RACK_SCALE * 600 / 44.45;
const CABINET_WIDTH = RACK_WIDTH * RACK_SCALE;
const CABINET_DEPTH = RACK_DEPTH * RACK_SCALE;
const MIN_DISTANCE = 1.05;
const FINE_CACHE_LIMIT = 12;
const MAX_DAMPING_FRAMES = 100;
const MAX_DAMPING_MS = 1050;
const SINGLE_CLICK_DELAY = 320;
const ANGLED = [0.42, 2.30, 1.12];
const IMMERSIVE_ANGLED = [0.32, 1.20, 1.48];
const TOP = [0, 1, 0.001];
const PORTRAIT_ASPECT = 1.05;
const ENTRY_VIEWS = {
  arrival: { duration: 1050, pullback: 1.28 },
  switch: { duration: 400, pullback: 1.12 },
};
const SEARCH_OUTLINE_COLORS = [0x0875ba, 0x02836e];
const SEARCH_DEVICE_COLOR = 0x79f4ff;
const FACE_OUTLINE_EDGES = [[-1, 0], [1, 0], [1, 0], [1, 1], [1, 1], [-1, 1], [-1, 1], [-1, 0]];

const easeOut = (t) => 1 - (1 - t) ** 3;
const easeInOut = (t) => t * t * (3 - 2 * t);

const VIEW_MODES = [
  { id: 'appearance', label: '外观' },
  { id: 'immersive', label: '沉浸模式' },
  { id: 'status', label: '运行状态' },
  { id: 'capacity', label: '空间核查' },
];

const LEGENDS = {
  status: [
    ['#3fa86b', '运行中'],
    ['#d14d43', '未通电'],
    ['#7b8a94', '已停用'],
    ['#d89b32', '待核实'],
  ],
  capacity: [
    ['#3b8d7a', '负载 <50% · 半/全深'],
    ['#d39636', '负载 50–85%'],
    ['#cf5444', '负载 ≥85%'],
    ['#e5a131', '含深度待核设备'],
  ],
};

const IMMERSIVE_SURFACES = new Map([
  [0xa9babc, 0x162635], [0xd4dfe1, 0x2c4354], [0xd8e2e5, 0x486072],
  [0xb7d0c2, 0x344e5a], [0xbdcbd0, 0x304855], [0xc9d9d6, 0x476372],
  [0x487165, 0x5b9ba9], [0x8fa9a5, 0x476372],
]);

const DEPTH_LABELS = { full: '全深', half: '半深', unknown: '深度待核' };

function disposeObjects(root, { keepSharedMaterials = false } = {}) {
  const geometries = new Set();
  const materials = new Set();
  root.traverse((object) => {
    if (!object.isMesh && !object.isLineSegments) return;
    geometries.add(object.geometry);
    if (!keepSharedMaterials) {
      for (const mat of [].concat(object.material)) materials.add(mat);
    }
    if (object.isInstancedMesh) object.dispose();
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
}

function node(tag, className, label) {
  const element = document.createElement(tag);
  element.className = className;
  if (label) element.textContent = label;
  return element;
}

function nanchangFront(layout, racksById, roomName, siteName) {
  if (roomName !== '中心机房' || !siteName?.includes('南昌东') || layout.illustrative ||
      layout.rows !== 1 || layout.columns !== 9 || layout.positions.length !== 9) return 0;
  const rotation = layout.positions[0].rotation;
  if (rotation !== 0 && rotation !== 180) return 0;
  const names = new Set();
  const slots = new Set();
  for (const entry of layout.positions) {
    const name = racksById.get(String(entry.rack_id))?.name;
    if (!/^A0[1-9]$/i.test(name ?? '') || entry.rotation !== rotation || entry.row !== 1 ||
        entry.slot < 1 || entry.slot > 9) return 0;
    names.add(name.toUpperCase());
    slots.add(entry.slot);
  }
  return names.size === 9 && slots.size === 9 ? (rotation === 0 ? 1 : -1) : 0;
}

function makeRoom(scene, { room, roomName, siteName, racks, devices, deviceKind, palette, floorTexture, shadowTexture }) {
  const racksById = new Map(racks.map((rack) => [String(rack.id), rack]));
  const photoFront = nanchangFront(room, racksById, roomName, siteName);
  const turned = room.positions.some(({ rotation }) => rotation === 90 || rotation === 270);
  const columnGap = photoFront ? CABINET_WIDTH + 0.045 : Math.max(COLUMN_GAP, turned ? CABINET_DEPTH + 0.10 : 0);
  const frontSign = photoFront || 1;
  const devicesByRack = new Map();
  for (const device of devices) {
    const id = String(device.rack_id);
    if (!racksById.has(id)) continue;
    if (!devicesByRack.has(id)) devicesByRack.set(id, []);
    devicesByRack.get(id).push(device);
  }
  const placements = new Map(room.positions.map((entry) => [`${entry.row}/${entry.slot}`, entry]));
  const width = room.columns * columnGap + 0.68;
  const rowExtent = (room.rows - 1) * ROW_GAP / 2;
  const rearEdge = -rowExtent - (frontSign > 0 ? 1.00 : 1.58);
  const frontEdge = rowExtent + (frontSign > 0 ? 1.58 : 1.00);
  const depth = frontEdge - rearEdge;
  const floorCenter = (frontEdge + rearEdge) / 2;
  const finishes = new Map();
  const boxes = new Map();
  const symbols = [];
  const targets = [];
  const entries = [];
  const targetsById = new Map();
  const bounds = new THREE.Box3(
    new THREE.Vector3(-width / 2, -0.16, rearEdge), new THREE.Vector3(width / 2, 0, frontEdge),
  );
  const block = new THREE.BoxGeometry(1, 1, 1);
  const pickMaterial = new THREE.MeshBasicMaterial();
  const transform = new THREE.Matrix4();
  const location = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const level = new THREE.Quaternion();

  function finish(color) {
    if (!finishes.has(color)) {
      finishes.set(color, new THREE.MeshStandardMaterial({ color, roughness: 0.83, metalness: 0.07 }));
    }
    return finishes.get(color);
  }

  function flat(color, x, y, z, size, angle = 0) {
    const material = finish(color);
    if (!boxes.has(material)) boxes.set(material, []);
    level.set(0, Math.sin(angle / 2), 0, Math.cos(angle / 2));
    transform.compose(location.set(x, y, z), level, scale.fromArray(size));
    boxes.get(material).push(transform.clone());
  }

  flat(0xa9babc, 0, -0.116, floorCenter, [width, 0.088, depth]);
  flat(0xd4dfe1, 0, -0.056, floorCenter, [width + 0.032, 0.110, depth + 0.032]);
  if (floorTexture) {
    floorTexture.wrapS = floorTexture.wrapT = THREE.RepeatWrapping;
    floorTexture.repeat.set(width / FLOOR_TILE_SIZE, depth / FLOOR_TILE_SIZE);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), new THREE.MeshStandardMaterial({
      color: 0xd8e2e5, map: floorTexture, roughness: 0.92, metalness: 0,
    }));
    finishes.set(0xd8e2e5, floor.material);
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(0, 0.0005, floorCenter);
    scene.add(floor);
  }
  const frontAisle = frontSign * (rowExtent + 1.08);
  const rearAisle = -frontSign * (rowExtent + 0.82);
  flat(0xb7d0c2, 0, 0.003, frontAisle, [width - 0.22, 0.008, photoFront ? 0.032 : 0.76]);
  flat(0xbdcbd0, 0, 0.003, rearAisle, [width - 0.22, 0.008, photoFront ? 0.032 : 0.24]);
  for (let row = 1; row < room.rows; row += 1) {
    const z = (room.rows / 2 - row) * ROW_GAP;
    flat(0xc9d9d6, 0, 0.002, z, [width - 0.65, 0.007, 0.72]);
  }
  for (const side of [-1, 1]) {
    flat(0xc9d9d6, side * (width / 2 - 0.14), 0.002, floorCenter, [0.026, 0.008, depth - 0.24]);
  }

  const entranceX = -width / 2 + 0.61;
  const entranceZ = frontSign * (rowExtent + 1.47);
  for (const side of [-1, 1]) {
    flat(0x487165, entranceX + side * 0.41, 0.47, entranceZ, [0.062, 0.94, 0.10]);
  }
  flat(0x487165, entranceX, 0.94, entranceZ, [0.88, 0.065, 0.10]);
  flat(0x487165, entranceX, 0.014, entranceZ, [0.88, 0.025, 0.15]);
  flat(0x487165, entranceX, 0.013, frontAisle, [0.045, 0.006, 0.28]);
  for (const side of [-1, 1]) {
    flat(0x487165, entranceX + side * 0.058, 0.013, frontAisle - frontSign * 0.12,
      [0.033, 0.006, 0.17], frontSign * side * 0.73);
  }
  const landmarks = [
    { id: 'entrance', text: '入口（示意）', point: new THREE.Vector3(entranceX, 1.07, entranceZ) },
    { id: 'front-aisle', text: '前走道', point: new THREE.Vector3(width * 0.24, 0.035, frontAisle) },
    { id: 'rear-aisle', text: '后走道', point: new THREE.Vector3(-width * 0.20, 0.035, rearAisle) },
  ];
  bounds.max.y = 1.12;

  const baseY = 0.100;
  for (let row = 1; row <= room.rows; row += 1) {
    for (let slot = 1; slot <= room.columns; slot += 1) {
      const x = (slot - (room.columns + 1) / 2) * columnGap;
      const z = ((room.rows + 1) / 2 - row) * ROW_GAP;
      const entry = placements.get(`${row}/${slot}`);
      const rack = entry && racksById.get(String(entry.rack_id));
      if (!rack) {
        for (const sx of [-1, 1]) {
          for (const sz of [-1, 1]) {
            flat(0x8fa9a5, x + sx * (CABINET_WIDTH / 2 - 0.04), 0.016,
              z + sz * (CABINET_DEPTH / 2 + 0.05), [0.20, 0.006, 0.024]);
            flat(0x8fa9a5, x + sx * (CABINET_WIDTH / 2 + 0.035), 0.016,
              z + sz * (CABINET_DEPTH / 2 - 0.035), [0.024, 0.006, 0.18]);
          }
        }
        symbols.push({ row, slot, point: new THREE.Vector3(x, 0.045, z) });
        continue;
      }

      const id = String(rack.id);
      const vb = rackVerticalBounds(rack.height, RACK_UNIT);
      const top = baseY + vb.top * RACK_SCALE;
      const bottom = baseY + vb.bottom * RACK_SCALE;
      bounds.max.y = Math.max(bounds.max.y, top + 0.12);
      const rackDevices = devicesByRack.get(id) ?? [];
      const rackEntry = {
        rack, devices: rackDevices, stats: rackOccupancy(rack, rackDevices),
        x, y: baseY, z, rotation: entry.rotation, scale: RACK_SCALE, middle: (top + bottom) / 2, height: top - bottom,
        enclosure: Boolean(photoFront),
      };
      entries.push(rackEntry);

      const target = new THREE.Mesh(block, pickMaterial);
      target.position.set(x, rackEntry.middle, z);
      target.scale.set(CABINET_WIDTH, top - bottom, CABINET_DEPTH);
      target.rotation.y = THREE.MathUtils.degToRad(rackEntry.rotation);
      target.visible = false;
      target.userData.entry = rackEntry;
      scene.add(target);
      targets.push(target);
      targetsById.set(id, target);
      symbols.push({ row, slot, rack, stats: rackEntry.stats,
        point: new THREE.Vector3(x, top + 0.05, z + photoFront * CABINET_DEPTH * 0.43) });
    }
  }

  if (photoFront) {
    // 桥架沿照片中的柜列连续布置，离开柜顶的空隙由托架支撑。
    const z = -photoFront * 0.31;
    const railY = Math.max(...entries.map((entry) => entry.middle + entry.height / 2)) + 0.24;
    const length = entries.at(-1).x - entries[0].x + CABINET_WIDTH * 0.86;
    const railColor = 0x72838a;
    const railSpacing = 0.205;
    for (const side of [-1, 1]) {
      flat(railColor, 0, railY - 0.028, z + side * railSpacing, [length, 0.037, 0.022]);
      flat(railColor, 0, railY + 0.065, z + side * railSpacing, [length, 0.018, 0.019]);
    }
    for (const [index, entry] of entries.entries()) {
      if (index % 2 !== 0) continue;
      const rackTop = entry.middle + entry.height / 2;
      const supportHeight = railY - rackTop;
      for (const side of [-1, 1]) {
        flat(railColor, entry.x, rackTop + supportHeight / 2, z + side * railSpacing,
          [0.034, supportHeight, 0.035]);
      }
    }
    const sections = Math.ceil(length / 0.24);
    for (let step = 0; step <= sections; step += 1) {
      const x = (step / sections - 0.5) * (length - 0.022);
      flat(railColor, x, railY - 0.04, z, [0.018, 0.018, railSpacing * 2]);
      for (const side of [-1, 1]) {
        flat(railColor, x, railY + 0.015, z + side * railSpacing, [0.011, 0.10, 0.014]);
      }
    }
    for (const [index, offset] of [-0.133, -0.095, 0.018, 0.055, 0.097].entries()) {
      flat(index % 2 ? 0x313c43 : 0x232c33, 0, railY - 0.009, z + offset, [length - 0.12, 0.026, 0.025]);
    }
    bounds.max.y = Math.max(bounds.max.y, railY + 0.09);
  }

  for (const [material, matrices] of boxes) {
    const mesh = new THREE.InstancedMesh(block, material, matrices.length);
    matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
  }
  if (shadowTexture && entries.length) {
    const material = new THREE.MeshBasicMaterial({
      color: 0x394c56, map: shadowTexture, opacity: 0.54, transparent: true, depthWrite: false,
    });
    const shadows = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), material, entries.length);
    const horizontal = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
    const yAxis = new THREE.Vector3(0, 1, 0);
    const rotation = new THREE.Quaternion();
    entries.forEach((entry, index) => {
      rotation.setFromAxisAngle(yAxis, THREE.MathUtils.degToRad(entry.rotation)).multiply(horizontal);
      transform.compose(location.set(entry.x, 0.004, entry.z), rotation, scale.set(CABINET_WIDTH * 1.56, CABINET_DEPTH * 1.82, 1));
      shadows.setMatrixAt(index, transform);
    });
    shadows.instanceMatrix.needsUpdate = true;
    scene.add(shadows);
  }
  const overviewLayer = buildRackOverviewLayer(scene, { entries, unit: RACK_UNIT, deviceKind, palette });
  if (!targets.length) pickMaterial.dispose();

  const outline = new THREE.LineSegments(new THREE.EdgesGeometry(block), new THREE.LineBasicMaterial({ color: 0x538f80 }));
  outline.visible = false;
  scene.add(outline);
  const deviceOutline = createDeviceSelectionOutline(scene);
  const locatedDeviceOutline = new THREE.LineSegments(
    outline.geometry, new THREE.LineBasicMaterial({ color: 0xff9f42, toneMapped: false }),
  );
  locatedDeviceOutline.visible = false;
  scene.add(locatedDeviceOutline);
  const outlineEdges = outline.geometry.getAttribute('position');
  let immersiveLayer;
  let highlightedRackId;
  let selectedRackId;
  let hasLocatedDevice = false;
  let activeFilter;

  function updateRoomLighting() {
    if (immersiveLayer?.group.visible) immersiveLayer.highlight(highlightedRackId, selectedRackId, activeFilter);
  }

  function setImmersive(active) {
    if (active && !immersiveLayer) {
      immersiveLayer = buildRoomLighting(scene, bounds, entries, CABINET_WIDTH, CABINET_DEPTH,
        { hasCableTray: Boolean(photoFront), frontSign });
    }
    if (immersiveLayer) immersiveLayer.group.visible = active;
    for (const [color, material] of finishes) {
      material.color.setHex(active ? (IMMERSIVE_SURFACES.get(color) ?? color) : color);
    }
    outline.material.color.setHex(active ? 0x77eaff : 0x538f80);
    locatedDeviceOutline.material.color.setHex(active ? 0xb4f7ff : 0xff9f42);
    updateRoomLighting();
  }

  const searchOutlines = SEARCH_OUTLINE_COLORS.map((color) => searchLines(color, targets.length * outlineEdges.count));
  const deviceFaceLimit = entries.reduce((count, entry) => count + entry.devices.length * 2, 0);
  const deviceSearchOutline = searchLines(SEARCH_DEVICE_COLOR, deviceFaceLimit * FACE_OUTLINE_EDGES.length);

  function searchLines(color, vertexLimit) {
    const geometry = new THREE.BufferGeometry();
    const position = new THREE.BufferAttribute(new Float32Array(vertexLimit * 3), 3);
    position.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('position', position);
    const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, toneMapped: false }));
    lines.visible = false;
    lines.frustumCulled = false;
    scene.add(lines);
    return { lines, position };
  }

  function showSearchLines({ lines, position }, count) {
    lines.visible = count > 0;
    lines.geometry.setDrawRange(0, count);
    if (lines.visible) position.needsUpdate = true;
  }

  function highlightSearchDevices(filter) {
    const { position } = deviceSearchOutline;
    let count = 0;
    if (filter?.deviceIds.size) {
      for (const entry of entries) {
        if (filter.directRackIds.has(String(entry.rack.id))) continue;
        const angle = THREE.MathUtils.degToRad(entry.rotation);
        const sin = Math.sin(angle);
        const cos = Math.cos(angle);
        for (const device of entry.devices) {
          if (!filter.deviceIds.has(String(device.id))) continue;
          const { minY, maxY, sign, full } = deviceMetrics(device, RACK_UNIT);
          for (const face of full ? [sign, -sign] : [sign]) {
            const z = face * (DETAIL_Z + 0.026) * entry.scale;
            for (const [side, upper] of FACE_OUTLINE_EDGES) {
              const x = side * (DEVICE_HALF_WIDTH - 0.015) * entry.scale;
              const y = (upper ? maxY : minY) * entry.scale;
              position.setXYZ(count++, entry.x + cos * x + sin * z, entry.y + y, entry.z - sin * x + cos * z);
            }
          }
        }
      }
    }
    showSearchLines(deviceSearchOutline, count);
  }

  function setSearchFilter(filter) {
    overviewLayer.setSearchFilter?.(filter);
    activeFilter = filter;
    updateRoomLighting();
    const counts = [0, 0];
    if (filter) {
      const vertex = new THREE.Vector3();
      for (const [id, target] of targetsById) {
        const direct = filter.directRackIds.has(id);
        if (!direct && !filter.rackIds.has(id)) continue;
        const index = direct ? 1 : 0;
        const { position } = searchOutlines[index];
        target.updateWorldMatrix(true, false);
        for (let edge = 0; edge < outlineEdges.count; edge += 1) {
          vertex.fromBufferAttribute(outlineEdges, edge).multiplyScalar(1.026).applyMatrix4(target.matrixWorld);
          position.setXYZ(counts[index]++, vertex.x, vertex.y, vertex.z);
        }
      }
    }
    searchOutlines.forEach((batch, index) => showSearchLines(batch, counts[index]));
    highlightSearchDevices(filter);
  }

  function highlight(id) {
    highlightedRackId = id;
    updateRoomLighting();
    const target = targetsById.get(id);
    outline.visible = Boolean(target);
    if (!target) return;
    outline.position.copy(target.position);
    outline.rotation.copy(target.rotation);
    outline.scale.copy(target.scale).multiplyScalar(1.014);
  }

  function positionDeviceOutline(line, entry, device, padding) {
    line.visible = Boolean(device);
    if (!device) return;
    const metrics = deviceMetrics(device, RACK_UNIT);
    const rotation = THREE.MathUtils.degToRad(entry.rotation);
    const centerZ = (metrics.minZ + metrics.maxZ) * entry.scale / 2;
    line.position.set(
      entry.x + Math.sin(rotation) * centerZ,
      entry.y + (metrics.minY + metrics.maxY) * entry.scale / 2,
      entry.z + Math.cos(rotation) * centerZ,
    );
    line.rotation.y = rotation;
    line.scale.set(
      DEVICE_HALF_WIDTH * 2,
      metrics.maxY - metrics.minY,
      metrics.maxZ - metrics.minZ,
    ).multiplyScalar(entry.scale * padding);
  }
  function highlightDevice(entry, device) {
    if (device) deviceOutline.set(device, { ...entry, unit: RACK_UNIT });
    else deviceOutline.clear();
    selectedRackId = device ? String(entry.rack.id) : undefined;
    locatedDeviceOutline.visible = hasLocatedDevice && !device;
    updateRoomLighting();
  }
  function highlightLocatedDevice(entry, device) {
    positionDeviceOutline(locatedDeviceOutline, entry, device, 1.052);
    hasLocatedDevice = Boolean(device);
    locatedDeviceOutline.visible = hasLocatedDevice && !selectedRackId;
  }
  const targetForRack = (id) => targetsById.get(String(id));
  const entryForRack = (id) => targetForRack(id)?.userData.entry;
  return { bounds, entries, entryForRack, targetForRack, highlight, highlightDevice, landmarks, lamps: overviewLayer.lamps,
    highlightLocatedDevice, photoFront, selectedDeviceCenter: deviceOutline.center, setImmersive,
    setMode: overviewLayer.setMode, setSearchFilter, symbols, targets };
}

export function mountRoomScene(host, {
  layout, roomName, siteName, racks, initialCamera, onRack, onFallback, devices = [],
  deviceKind = () => 'server', units = (device) => `U${device.u_start}`,
  initialLocatedRackId, initialLocatedDeviceId, initialSearchFilter, onDevice, onSceneInteraction, onClearDeviceSelection, entry,
}) {
  const panel = node('section', 'room-3d');
  panel.setAttribute('aria-label', '机房三维总览');
  const viewport = node('div', 'room-3d-viewport');
  const labels = node('div', 'room-3d-labels');
  labels.setAttribute('aria-label', '机柜及预留位');
  const landmarkLayer = node('div', 'room-3d-landmarks');
  landmarkLayer.setAttribute('aria-label', '示意方位');
  const tooltip = node('div', 'rack-spatial-tooltip room-3d-device-tooltip');
  tooltip.hidden = true;
  tooltip.setAttribute('role', 'tooltip');
  const tooltipName = node('strong', 'room-3d-tooltip-title');
  const tooltipPosition = node('span', 'room-3d-tooltip-position');
  const tooltipStatus = node('span', 'room-3d-tooltip-status');
  tooltip.append(tooltipName, tooltipPosition, tooltipStatus);

  const legend = node('div', 'room-3d-legend');
  legend.hidden = true;
  legend.setAttribute('aria-live', 'polite');

  const toolbar = node('div', 'room-3d-toolbar');
  const toolbarGroups = node('div', 'room-3d-toolbar-groups');
  const presets = node('div', 'room-3d-presets');
  presets.setAttribute('role', 'group');
  presets.setAttribute('aria-label', '机房视角');
  const angledButton = node('button', '', '斜俯视');
  const topButton = node('button', '', '正俯视');
  angledButton.type = topButton.type = 'button';
  presets.append(angledButton, topButton);

  const modesGroup = node('div', 'room-3d-presets');
  modesGroup.setAttribute('role', 'group');
  modesGroup.setAttribute('aria-label', '着色模式');
  const modeButtons = new Map();
  for (const { id, label } of VIEW_MODES) {
    const button = node('button', '', label);
    button.type = 'button';
    button.dataset.viewMode = id;
    modesGroup.append(button);
    modeButtons.set(id, button);
  }
  toolbarGroups.append(presets, modesGroup);
  const hint = window.matchMedia('(pointer: coarse)').matches
    ? '单指旋转 · 双指缩放和平移'
    : '左键旋转 · 右键平移 · 滚轮缩放 · 双击聚焦';
  toolbar.append(toolbarGroups, node('span', 'room-3d-hint', hint));
  toolbar.addEventListener('pointerdown', (event) => {
    clearPendingClick();
    event.stopPropagation();
  });
  toolbar.addEventListener('wheel', (event) => event.stopPropagation(), { passive: true });

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  const canvas = renderer.domElement;
  canvas.className = 'room-3d-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', '三维机柜布局');
  canvas.tabIndex = -1;
  canvas.dataset.detailCount = '0';
  canvas.dataset.detailRacks = '';
  viewport.append(canvas, landmarkLayer, labels, toolbar, legend, tooltip);
  const selectionLabel = createDeviceSelectionLabel(viewport);
  panel.append(viewport);
  host.replaceChildren(panel);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe8eff2);
  const environment = createRackEnvironment(renderer);
  scene.environment = environment?.texture ?? null;
  scene.environmentIntensity = 0.78;
  const ambient = new THREE.HemisphereLight(0xf8fcff, 0x748282, 1.8);
  const key = new THREE.DirectionalLight(0xfff2de, 2.2);
  key.position.set(-5, 12, 9);
  const fill = new THREE.DirectionalLight(0xf4f6f8, 0.52);
  fill.position.set(0, 3, 8);
  const rim = new THREE.DirectionalLight(0xc8e3f4, 1.30);
  rim.position.set(8, 6, -9);
  scene.add(ambient, key, fill, rim);

  const palette = createRackPalette();
  const floorTexture = createFloorTileTexture();
  const shadowTexture = createContactShadowTexture();
  const model = makeRoom(scene, { room: layout, roomName, siteName, racks, devices, deviceKind, palette, floorTexture, shadowTexture });
  if (model.photoFront) viewport.dataset.roomProfile = 'nanchang-east';
  const roomSize = model.bounds.getSize(new THREE.Vector3());
  // 屏幕平移会同时改变目标的高度和纵深，给单排机房的地板边缘留出余量。
  const panBounds = model.bounds.clone().expandByScalar(Math.max(roomSize.y, Math.hypot(roomSize.x, roomSize.z) / 4));
  scene.fog = new THREE.FogExp2(scene.background, Math.min(0.023, 0.18 / Math.hypot(roomSize.x, roomSize.z)));
  const landmarkItems = model.landmarks.map(({ id, text, point }) => {
    const item = node('span', 'room-3d-landmark', text);
    item.dataset.landmark = id;
    landmarkLayer.append(item);
    return { item, point };
  });
  const center = model.bounds.getCenter(new THREE.Vector3());
  const corners = [];
  for (const x of [model.bounds.min.x, model.bounds.max.x]) {
    for (const y of [model.bounds.min.y, model.bounds.max.y]) {
      for (const z of [model.bounds.min.z, model.bounds.max.z]) corners.push(new THREE.Vector3(x, y, z).sub(center));
    }
  }

  const camera = new THREE.PerspectiveCamera(35, 1, 0.04, 400);
  const controls = new OrbitControls(camera, viewport);
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.enableDamping = !motion.matches;
  controls.dampingFactor = 0.08;
  controls.minPolarAngle = 0.001;
  controls.maxPolarAngle = Math.PI / 2 - 0.12;
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const projected = new THREE.Vector3();
  const projectedEdge = new THREE.Vector3();
  const otherEdge = new THREE.Vector3();
  const localRay = new THREE.Ray();
  const hitPoint = new THREE.Vector3();
  const localTransform = new THREE.Matrix4();
  const localRotation = new THREE.Quaternion();
  const yAxis = new THREE.Vector3(0, 1, 0);
  const previousPosition = new THREE.Vector3();
  const previousTarget = new THREE.Vector3();
  const offset = new THREE.Vector3();
  const renderSize = new THREE.Vector2();
  const fineLayers = new Map();
  let deviceHitCache;
  let frame;
  let flight;
  let dampingFrames = 0;
  let dampingDeadline = 0;
  let pendingClick;
  let disposed = false;
  let updatingControls = false;
  let sized = false;
  let pressed;
  let hovered;
  let locatedRackId;
  let selectedDeviceId;
  let activeView;
  let searchFilter;
  let viewMode = VIEW_MODES.some((m) => m.id === initialCamera?.viewMode) ? initialCamera.viewMode : 'appearance';

  const preset = ['angled', 'top'].includes(initialCamera?.activeView) ? initialCamera.activeView : null;
  const restored = Array.isArray(initialCamera?.direction) && initialCamera.direction.length === 3 &&
    initialCamera.direction.every(Number.isFinite) && initialCamera.direction[1] > 0;
  const restoredTarget = Array.isArray(initialCamera?.target) && initialCamera.target.length === 3 &&
    initialCamera.target.every(Number.isFinite)
    ? new THREE.Vector3(...initialCamera.target) : center.clone();
  function defaultAngle(aspect = camera.aspect) {
    const immersive = viewMode === 'immersive';
    if (!model.photoFront) return immersive ? IMMERSIVE_ANGLED : ANGLED;
    const portrait = aspect < PORTRAIT_ASPECT;
    return [portrait ? -0.82 : -0.46, (portrait ? 0.45 : 0.35) - (immersive ? 0.09 : 0), model.photoFront];
  }

  function defaultZoom(aspect = camera.aspect) {
    return model.photoFront && aspect >= 1.45 ? 0.89 : 1;
  }

  const initial = {
    direction: restored ? initialCamera.direction : defaultAngle(viewport.clientWidth / viewport.clientHeight),
    activeView: restored ? preset : 'angled',
    zoom: Number.isFinite(initialCamera?.zoom) ? THREE.MathUtils.clamp(initialCamera.zoom, 0.12, 3) :
      defaultZoom(viewport.clientWidth / viewport.clientHeight),
    target: restoredTarget,
    viewMode,
  };
  setActive(initial.activeView);
  const initialLocatedEntry = model.entryForRack(initialLocatedRackId);
  markLocated(initialLocatedEntry?.rack.id);
  if (initialLocatedDeviceId != null) {
    const initialDevice = deviceInRack(initialLocatedEntry, initialLocatedDeviceId);
    if (initialDevice) markLocatedDevice(initialLocatedEntry, initialDevice);
  }

  const labelItems = model.symbols.map((symbol) => {
    const { rack, stats } = symbol;
    const item = node(rack ? 'button' : 'span', `room-3d-label${rack ? '' : ' room-3d-label-reserved'}`);
    item.append(node('span', 'room-3d-label-name', rack?.name ?? (layout.illustrative ? '预留' : '空位')));
    item.dataset.roomRow = symbol.row;
    item.dataset.roomSlot = symbol.slot;
    if (rack) {
      item.type = 'button';
      item.dataset.rackId = rack.id;
      item.dataset.expanded = 'false';
      item.title = `${rack.name} · ${rack.height}U`;
      item.setAttribute('aria-label', `查看机柜 ${rack.name}，${rack.height}U`);
      item.append(node('span', 'room-3d-label-meta', `${rack.height}U`),
        node('span', 'room-3d-label-meta', `已用 ${stats.usedU}/${rack.height}U`));
      item.addEventListener('click', (event) => {
        if (event.detail !== 0) return;
        clearPendingClick();
        onRack(rack);
      });
      item.addEventListener('pointerenter', () => setHover(rack));
      item.addEventListener('pointerleave', () => setHover(null));
      item.addEventListener('focus', () => setHover(rack));
      item.addEventListener('blur', () => setHover(null));
    } else {
      item.title = `第 ${symbol.row} 排第 ${symbol.slot} 位`;
    }
    labels.append(item);
    return { ...symbol, item };
  });

  angledButton.addEventListener('click', () => usePreset('angled', defaultAngle()));
  topButton.addEventListener('click', () => usePreset('top', TOP));
  for (const [id, button] of modeButtons) {
    button.addEventListener('click', () => {
      if (viewMode === id) return;
      const angleChanged = (viewMode === 'immersive') !== (id === 'immersive');
      applyViewMode(id);
      if (angleChanged && activeView === 'angled') usePreset('angled', defaultAngle());
      else onSceneInteraction?.();
      invalidate();
    });
  }

  controls.addEventListener('start', () => { flight = undefined; });
  controls.addEventListener('change', () => {
    if (updatingControls) return;
    onSceneInteraction?.();
    flight = undefined;
    clampTarget(true);
    setActive(null);
    setHover(null);
    hideTooltip();
    queueDamping();
  });
  controls.addEventListener('end', queueDamping);
  motion.addEventListener('change', changeMotion);

  viewport.addEventListener('pointerdown', (event) => {
    flight = undefined;
    hideTooltip();
    if (event.button === 0 && event.isPrimary) {
      const label = event.target.closest('button.room-3d-label');
      const rack = label ? racks.find((item) => String(item.id) === label.dataset.rackId) : undefined;
      pressed = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false, rack, fromCanvas: event.target === canvas };
    } else if (pressed && event.pointerType === 'touch') pressed.moved = true;
  });
  viewport.addEventListener('pointermove', (event) => {
    if (pressed) {
      pressed.moved ||= Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 5;
      if (pressed.moved) {
        clearPendingClick();
        queueDamping();
      }
    } else if (event.pointerType !== 'touch' && event.target === canvas) {
      const hit = pick(event);
      const entry = hit?.object.userData.entry;
      const rack = entry?.rack;
      setHover(rack);
      showTooltip(pickDevice(hit), entry, event);
    } else {
      hideTooltip();
    }
  });
  viewport.addEventListener('pointerup', (event) => {
    const clicked = pressed?.id === event.pointerId && !pressed.moved &&
      Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) <= 5;
    const labelRack = pressed?.rack;
    const fromCanvas = pressed?.fromCanvas;
    pressed = undefined;
    if (clicked) {
      const hit = labelRack ? null : pick(event);
      const entry = hit?.object.userData.entry;
      const rack = labelRack ?? entry?.rack;
      if (rack) selectRack(rack, entry, pickDevice(hit), event);
      else if (fromCanvas) {
        clearPendingClick();
        if (selectedDeviceId) onClearDeviceSelection?.();
      }
    }
  });
  viewport.addEventListener('pointercancel', () => {
    pressed = undefined;
    clearPendingClick();
  });
  viewport.addEventListener('wheel', clearPendingClick, { passive: true });
  viewport.addEventListener('pointerleave', () => {
    setHover(null);
    hideTooltip();
  });
  const contextLost = (event) => {
    event.preventDefault();
    onFallback();
  };
  canvas.addEventListener('webglcontextlost', contextLost);
  const observer = new ResizeObserver(resize);
  observer.observe(viewport);
  const lampAnimation = animateOperatingLamps(viewport, model.lamps, () => {
    if (frame == null && sized && !disposed) renderer.render(scene, camera);
  });
  applyViewMode(viewMode);
  setSearchFilter(initialSearchFilter);
  resize();

  function clampTarget(keepOrbit = false) {
    offset.copy(controls.target);
    controls.target.clamp(panBounds.min, panBounds.max);
    if (keepOrbit) camera.position.add(offset.subVectors(controls.target, offset));
  }

  function applyViewMode(mode) {
    viewMode = mode;
    for (const [id, button] of modeButtons) {
      button.setAttribute('aria-pressed', String(id === mode));
    }
    const immersive = mode === 'immersive';
    viewport.toggleAttribute('data-immersive', immersive);
    scene.background.setHex(immersive ? 0x0b1420 : 0xe8eff2);
    scene.fog.color.copy(scene.background);
    scene.environmentIntensity = immersive ? 0.72 : 0.78;
    ambient.color.setHex(immersive ? 0xd0e9ff : 0xf8fcff);
    ambient.groundColor.setHex(immersive ? 0x486074 : 0x748282);
    ambient.intensity = immersive ? 1.33 : 1.8;
    key.intensity = immersive ? 2.46 : 2.2;
    fill.intensity = immersive ? 0.74 : 0.52;
    rim.color.setHex(immersive ? 0x8ecfff : 0xc8e3f4);
    rim.intensity = immersive ? 2.04 : 1.30;
    model.setImmersive(immersive);
    model.setMode(immersive ? 'appearance' : mode);
    const entries = LEGENDS[mode];
    if (!entries) {
      legend.hidden = true;
      legend.replaceChildren();
    } else {
      legend.replaceChildren(...entries.map(([color, text]) => {
        const item = node('span', 'room-3d-legend-item');
        const dot = node('i', 'room-3d-legend-dot');
        dot.style.backgroundColor = color;
        item.append(dot, text);
        return item;
      }));
      legend.hidden = false;
    }
    lampAnimation?.sync();
  }

  function fittedDistance(direction) {
    const right = new THREE.Vector3().crossVectors(camera.up, direction);
    if (right.lengthSq() < 1e-12) right.set(1, 0, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(direction, right);
    const vertical = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.84;
    const horizontal = vertical * camera.aspect;
    return Math.max(...corners.map((corner) => corner.dot(direction) + Math.max(
      Math.abs(corner.dot(right)) / horizontal,
      Math.abs(corner.dot(up)) / vertical,
    )));
  }

  function placeView(direction, zoom, target = center) {
    const fit = fittedDistance(direction);
    controls.minDistance = MIN_DISTANCE;
    controls.maxDistance = fit * 3;
    controls.target.copy(target);
    clampTarget();
    camera.position.copy(controls.target).addScaledVector(direction, fit * zoom);
    updateControls();
    invalidate();
  }

  function updateControls() {
    updatingControls = true;
    controls.update();
    updatingControls = false;
  }

  function clearDamping() {
    dampingFrames = 0;
    if (!controls.enableDamping) return;
    previousPosition.copy(camera.position);
    previousTarget.copy(controls.target);
    controls.enableDamping = false;
    updateControls();
    camera.position.copy(previousPosition);
    controls.target.copy(previousTarget);
    controls.enableDamping = !motion.matches;
    updateControls();
  }

  function queueDamping() {
    if (controls.enableDamping && !flight) {
      dampingFrames = MAX_DAMPING_FRAMES;
      dampingDeadline = performance.now() + MAX_DAMPING_MS;
    }
    invalidate();
  }

  function changeMotion() {
    clearDamping();
    controls.enableDamping = !motion.matches;
    if (motion.matches && flight) {
      const { direction, zoom, endTarget } = flight;
      flight = undefined;
      placeView(direction, zoom, endTarget);
    }
  }

  function flyTo(direction, zoom, target, duration = 260, { easing = easeOut, startAfterDraw = false } = {}) {
    clearPendingClick();
    clearDamping();
    flight = undefined;
    if (motion.matches || !sized) {
      placeView(direction, zoom, target);
      return;
    }
    const endTarget = target.clone();
    const fit = fittedDistance(direction);
    flight = {
      direction, zoom, fit, duration, endTarget, easing,
      startTime: startAfterDraw ? null : performance.now(),
      startTarget: controls.target.clone(), startPosition: camera.position.clone(),
      endPosition: endTarget.clone().addScaledVector(direction, fit * zoom),
    };
    invalidate();
  }

  function advanceCamera(now) {
    if (flight) {
      if (flight.startTime === null) return;
      const t = THREE.MathUtils.clamp((now - flight.startTime) / flight.duration, 0, 1);
      const ease = flight.easing(t);
      controls.minDistance = MIN_DISTANCE;
      controls.maxDistance = flight.fit * 3;
      controls.target.lerpVectors(flight.startTarget, flight.endTarget, ease);
      camera.position.lerpVectors(flight.startPosition, flight.endPosition, ease);
      updateControls();
      if (t === 1) flight = undefined;
      return;
    }
    if (!dampingFrames) return;
    previousPosition.copy(camera.position);
    previousTarget.copy(controls.target);
    updateControls();
    clampTarget(true);
    const shift = camera.position.distanceToSquared(previousPosition) + controls.target.distanceToSquared(previousTarget);
    dampingFrames -= 1;
    if (shift < 0.00000001 || dampingFrames === 0 || now >= dampingDeadline) clearDamping();
  }

  function clearPendingClick() {
    if (!pendingClick) return;
    clearTimeout(pendingClick.timer);
    pendingClick = undefined;
  }

  function selectRack(rack, entry, device, event) {
    const anchor = device && onDevice ? makeDeviceAnchor(entry, device, event) : null;
    const open = () => {
      if (disposed) return;
      if (anchor) onDevice(device, anchor);
      else onRack(rack, device);
    };
    if (event.pointerType !== 'mouse') {
      clearPendingClick();
      open();
      return;
    }
    const { clientX: x, clientY: y } = event;
    const twice = pendingClick?.rackId === rack.id && Math.hypot(x - pendingClick.x, y - pendingClick.y) <= 12;
    clearPendingClick();
    if (twice) {
      focusFromClick(model.entryForRack(rack.id));
      return;
    }
    pendingClick = { rackId: rack.id, x, y, timer: window.setTimeout(() => {
      pendingClick = undefined;
      open();
    }, SINGLE_CLICK_DELAY) };
  }

  function focusFromClick(entry) {
    onSceneInteraction?.();
    const target = new THREE.Vector3(entry.x, entry.middle, entry.z);
    const angle = THREE.MathUtils.degToRad(entry.rotation);
    const direction = new THREE.Vector3(Math.sin(angle), 0, Math.cos(angle));
    const approach = new THREE.Vector3().subVectors(camera.position, target);
    if (direction.dot(approach) < -0.1) direction.negate();
    direction.addScaledVector(new THREE.Vector3().crossVectors(yAxis, direction), 0.24);
    direction.y = 0.21;
    direction.normalize();
    const rackHeight = rackVerticalBounds(entry.rack.height, RACK_UNIT);
    const vertical = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.74;
    const distance = Math.max((rackHeight.top - rackHeight.bottom) * entry.scale / (2 * vertical),
      CABINET_WIDTH / (2 * vertical * camera.aspect)) + CABINET_DEPTH * 0.72;
    setActive(null);
    setHover(null);
    hideTooltip();
    flyTo(direction, distance / fittedDistance(direction), target, 420);
  }

  function setActive(view) {
    activeView = view;
    angledButton.setAttribute('aria-pressed', String(view === 'angled'));
    topButton.setAttribute('aria-pressed', String(view === 'top'));
  }

  function usePreset(view, direction) {
    onSceneInteraction?.();
    setActive(view);
    setHover(null);
    hideTooltip();
    flyTo(new THREE.Vector3(...direction).normalize(), view === 'angled' ? defaultZoom() : 1, center);
  }

  function markLocated(id) {
    locatedRackId = id == null ? undefined : String(id);
    if (locatedRackId) canvas.dataset.locatedRackId = locatedRackId;
    else delete canvas.dataset.locatedRackId;
    model.highlight(locatedRackId ?? hovered);
    invalidate();
  }

  function locateRack(id, face = 'front') {
    const entry = model.entryForRack(id);
    if (!entry || disposed) return false;
    clearLocatedDevice();
    focusRack(entry, face);
    return true;
  }

  function locateDevice(rackId, deviceId) {
    if (disposed) return false;
    const entry = model.entryForRack(rackId);
    const device = deviceInRack(entry, deviceId);
    if (!device) return false;
    focusRack(entry, device.face);
    markLocatedDevice(entry, device);
    return true;
  }

  function clearLocatedDevice() {
    if (disposed || !canvas.hasAttribute('data-located-device-id')) return;
    markLocatedDevice();
  }

  function markLocatedDevice(entry, device) {
    if (device) {
      canvas.dataset.locatedDeviceId = device.id;
      canvas.dataset.locatedDeviceFace = device.face;
    } else {
      delete canvas.dataset.locatedDeviceId;
      delete canvas.dataset.locatedDeviceFace;
    }
    model.highlightLocatedDevice(entry, device);
    invalidate();
  }

  function focusRack(entry, face) {
    onSceneInteraction?.();
    setHover(null);
    hideTooltip();
    setActive(null);
    markLocated(entry.rack.id);
    const angle = THREE.MathUtils.degToRad(entry.rotation) + (face === 'rear' ? Math.PI : 0);
    const direction = new THREE.Vector3(0.45, 1.05, 1).applyAxisAngle(yAxis, angle).normalize();
    const halfAngle = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const distance = Math.max(entry.height / (halfAngle * 1.55), CABINET_WIDTH / (halfAngle * camera.aspect * 1.28), 2.4) + 0.38;
    flyTo(direction, distance / fittedDistance(direction), new THREE.Vector3(entry.x, entry.middle, entry.z));
  }

  function resetView() {
    clearLocatedDevice();
    markLocated();
    usePreset('angled', defaultAngle());
  }

  function setSearchFilter(filter) {
    if (disposed) return;
    const matching = new Set();
    if (filter) {
      for (const { rack } of model.entries) {
        const id = String(rack.id);
        if (filter.directRackIds.has(id) || filter.rackIds.has(id)) matching.add(id);
      }
    }
    // 非上架或待摆放机柜中的匹配结果不会让总览所有柜体褪色。
    searchFilter = matching.size ? filter : null;
    for (const { item, rack } of labelItems) {
      if (!rack) continue;
      if (!searchFilter) {
        delete item.dataset.searchMatch;
        delete item.dataset.searchDirect;
        continue;
      }
      const id = String(rack.id);
      item.dataset.searchMatch = String(matching.has(id));
      item.dataset.searchDirect = String(searchFilter.directRackIds.has(id));
    }
    if (searchFilter) canvas.dataset.searchRacks = [...matching].join(' ');
    else delete canvas.dataset.searchRacks;
    model.setSearchFilter(searchFilter);
    for (const { details } of fineLayers.values()) details.setSearchFilter?.(searchFilter);
    lampAnimation?.sync();
    invalidate();
  }

  function snapshot() {
    if (!sized) return initial;
    const vector = new THREE.Vector3().subVectors(camera.position, controls.target);
    const distance = vector.length();
    const direction = vector.normalize();
    return {
      direction: direction.toArray(),
      zoom: distance / fittedDistance(direction),
      target: controls.target.toArray(),
      activeView,
      viewMode,
    };
  }

  function resize() {
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    if (!width || !height) return;
    renderer.getSize(renderSize);
    if (sized && renderSize.x === width && renderSize.y === height) return;
    const firstFrame = !sized;
    const aspect = width / height;
    const changedOrientation = (camera.aspect < PORTRAIT_ASPECT) !== (aspect < PORTRAIT_ASPECT) ||
      defaultZoom(camera.aspect) !== defaultZoom(aspect);
    const current = snapshot();
    const destination = flight;
    flight = undefined;
    clearDamping();
    renderer.setSize(width, height, false);
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
    const reframe = model.photoFront && !destination && current.activeView === 'angled' &&
      (sized ? changedOrientation : !restored);
    sized = true;
    const targetVec = current.target instanceof THREE.Vector3
      ? current.target : new THREE.Vector3(...(current.target ?? center.toArray()));
    const direction = new THREE.Vector3(...(reframe ? defaultAngle() : current.direction)).normalize();
    const zoom = reframe ? defaultZoom() : current.zoom;
    const entryView = firstFrame && !motion.matches ? ENTRY_VIEWS[entry] : undefined;
    placeView(direction, entryView ? Math.min(zoom * entryView.pullback, 3) : zoom, targetVec);
    if (entryView) flyTo(direction, zoom, targetVec, entryView.duration, { easing: easeInOut, startAfterDraw: true });
    if (destination) {
      const startAfterDraw = destination.startTime === null;
      const remaining = startAfterDraw ? destination.duration :
        Math.max(1, destination.startTime + destination.duration - performance.now());
      flyTo(destination.direction, destination.zoom, destination.endTarget, remaining, { easing: destination.easing, startAfterDraw });
    }
  }

  function invalidate() {
    if (frame == null && !disposed && sized) frame = requestAnimationFrame(draw);
  }

  function layoutLabels(width, height) {
    const narrow = width < 520;
    const maxLabels = narrow ? 18 : 48;
    const showEmpty = model.symbols.length <= 24;
    const labelDetailDistance = height * CABINET_WIDTH / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * (narrow ? 98 : 112));
    const placedBoxes = [];
    const candidates = [];

    for (const entry of labelItems) {
      const { item, point, rack } = entry;
      const rackId = rack && String(rack.id);
      const isHovered = Boolean(rackId && rackId === hovered);
      const isLocated = Boolean(rackId && rackId === locatedRackId);
      const priority = isHovered ? 4 : isLocated ? 3 :
        item.dataset.searchDirect === 'true' ? 2 : item.dataset.searchMatch === 'true' ? 1 : 0;
      if (!rack && !showEmpty && !isHovered) {
        item.hidden = true;
        continue;
      }
      projected.copy(point).project(camera);
      if (Math.abs(projected.x) > 0.985 || Math.abs(projected.y) > 0.985 || projected.z < -1 || projected.z > 1) {
        item.hidden = true;
        continue;
      }
      const left = (projected.x + 1) * width / 2;
      const top = (1 - projected.y) * height / 2;
      const dist = camera.position.distanceToSquared(point);
      candidates.push({ entry, left, top, dist, isHovered, isLocated, isRack: Boolean(rack), priority });
    }

    candidates.sort((a, b) => {
      if (a.priority !== b.priority) return b.priority - a.priority;
      if (a.isRack !== b.isRack) return a.isRack ? -1 : 1;
      return a.dist - b.dist;
    });

    let visibleCount = 0;
    for (const { entry, left, top, dist, isHovered, isLocated, priority } of candidates) {
      const { item, rack } = entry;
      const expanded = Boolean(rack && (isHovered || dist < labelDetailDistance ** 2));
      const smallRackLabel = model.photoFront && narrow && rack && !expanded;
      const estW = smallRackLabel ? 28 : Math.min(148, Math.max(expanded ? 104 : 46, (rack ? rack.name.length : 2) * 9 + 18));
      const estH = expanded ? 56 : 22;
      const edge = estW / 2 + (smallRackLabel ? 2 : 4);
      const box = { l: left - edge, r: left + edge, t: top - estH - 4, b: top + 2 };
      const important = isHovered || isLocated;
      const collides = !important && placedBoxes.some((p) => box.l < p.r && box.r > p.l && box.t < p.b && box.b > p.t);
      if (collides || (priority === 0 && visibleCount >= maxLabels)) {
        item.hidden = true;
      } else {
        item.hidden = false;
        item.style.left = `${left}px`;
        item.style.top = `${top}px`;
        placedBoxes.push(box);
        visibleCount += 1;
      }
      item.dataset.highlighted = String(isHovered);
      if (rack) item.dataset.expanded = String(expanded);
      item.dataset.located = String(isLocated);
    }

    const lookX = camera.position.x - controls.target.x;
    const lookY = camera.position.y - controls.target.y;
    const lookZ = camera.position.z - controls.target.z;
    const overhead = lookY > Math.hypot(lookX, lookZ) * 1.75;
    for (const { item, point } of landmarkItems) {
      const rear = item.dataset.landmark === 'rear-aisle';
      const frontVisible = camera.position.z * model.photoFront >= 0;
      if (model.photoFront && !overhead && (rear === frontVisible)) {
        item.hidden = true;
        continue;
      }
      projected.copy(point).project(camera);
      const left = (projected.x + 1) * width / 2;
      const top = (1 - projected.y) * height / 2;
      const halfWidth = item.dataset.landmark === 'entrance' ? 42 : 24;
      const collides = placedBoxes.some((box) => left - halfWidth < box.r && left + halfWidth > box.l &&
        top - 10 < box.b && top + 10 > box.t);
      item.hidden = collides || Math.abs(projected.x) > 0.86 || Math.abs(projected.y) > 0.92 || projected.z < -1 || projected.z > 1;
      if (!item.hidden) {
        item.style.left = `${left}px`;
        item.style.top = `${top}px`;
        placedBoxes.push({ l: left - halfWidth, r: left + halfWidth, t: top - 10, b: top + 10 });
      }
    }
  }

  function draw(now) {
    frame = undefined;
    if (disposed) return;
    advanceCamera(now);
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    camera.updateMatrixWorld();
    updateDetails(width);
    renderer.render(scene, camera);
    if (flight?.startTime === null) flight.startTime = performance.now();
    layoutLabels(width, height);
    selectionLabel.update(camera, canvas, model.selectedDeviceCenter);
    if (flight || dampingFrames) invalidate();
  }

  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2);
    ray.setFromCamera(pointer, camera);
    return ray.intersectObjects(model.targets, false)[0] ?? null;
  }

  function setHover(rack) {
    const id = rack ? String(rack.id) : undefined;
    if (hovered === id) return;
    model.highlight(locatedRackId ?? id);
    hovered = id;
    canvas.dataset.pickable = String(Boolean(id));
    if (id) canvas.dataset.hoveredRackId = id;
    else delete canvas.dataset.hoveredRackId;
    invalidate();
  }

  function makeDeviceAnchor(entry, device, event) {
    const id = String(device.id);
    return {
      element: canvas, x: event?.clientX, y: event?.clientY, viewport, persistSelection: true,
      cabinetRect() {
        if (disposed || !sized) return null;
        const target = model.targetForRack(entry.rack.id);
        if (!target) return null;
        if (!target.geometry.boundingBox) target.geometry.computeBoundingBox();
        target.updateWorldMatrix(true, false);
        return projectCabinetRect(camera, canvas, target.geometry.boundingBox, target.matrixWorld);
      },
      devicePoint() {
        if (disposed || !sized) return null;
        const metrics = deviceMetrics(device, RACK_UNIT);
        const rotation = THREE.MathUtils.degToRad(entry.rotation);
        const sin = Math.sin(rotation);
        const cos = Math.cos(rotation);
        const cameraZ = (camera.position.x - entry.x) * sin + (camera.position.z - entry.z) * cos;
        const front = metrics.full ? cameraZ >= 0 : metrics.front;
        const panelZ = (front ? metrics.maxZ : metrics.minZ) * entry.scale;
        const point = new THREE.Vector3(
          entry.x + sin * panelZ, entry.y + metrics.centerY * entry.scale, entry.z + cos * panelZ,
        );
        return projectScenePoint(camera, canvas, point);
      },
      setSelected(selected) {
        if (disposed || (!selected && selectedDeviceId !== id)) return;
        selectedDeviceId = selected ? id : undefined;
        if (selected) canvas.dataset.selectedDeviceId = id;
        else delete canvas.dataset.selectedDeviceId;
        model.highlightDevice(entry, selected ? device : undefined);
        selectionLabel.set(selected ? `${entry.rack.name} · ${units(device)}` : undefined);
        invalidate();
      },
    };
  }

  function deviceAnchor(id) {
    for (const entry of model.entries) {
      const device = deviceInRack(entry, id);
      if (device) return makeDeviceAnchor(entry, device);
    }
    return null;
  }

  function deviceInRack(entry, id) {
    return entry?.devices.find((device) => String(device.id) === String(id));
  }

  function updateDetails(width) {
    const viewDir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
    const narrow = width < 520;
    const candidates = [];
    if (viewDir.y < 0.985) {
      for (const entry of model.entries) {
        const id = String(entry.rack.id);
        const activeGroup = fineLayers.get(id)?.group;
        const active = Boolean(activeGroup && activeGroup.visible);
        projected.set(entry.x, entry.middle, entry.z).project(camera);
        if (Math.abs(projected.x) > 0.96 || Math.abs(projected.y) > 0.96 || projected.z < -1 || projected.z > 1) continue;
        const angle = THREE.MathUtils.degToRad(entry.rotation);
        const offsetX = Math.cos(angle) * CABINET_WIDTH / 2;
        const offsetZ = Math.sin(angle) * CABINET_WIDTH / 2;
        projectedEdge.set(entry.x + offsetX, entry.middle, entry.z - offsetZ).project(camera);
        otherEdge.set(entry.x - offsetX, entry.middle, entry.z + offsetZ).project(camera);
        const pixels = Math.abs(projectedEdge.x - otherEdge.x) * width / 2;
        const threshold = narrow ? (active ? 94 : 110) : (active ? 104 : 122);
        if (pixels >= threshold) candidates.push({ id, entry, priority: pixels + (active ? 16 : 0) });
      }
    }
    candidates.sort((a, b) => b.priority - a.priority);
    const selected = new Map(candidates.slice(0, narrow ? 2 : 4).map(({ id, entry }) => [id, entry]));
    let changed = false;

    for (const [id, { group }] of fineLayers) {
      const shouldShow = selected.has(id);
      if (group.visible !== shouldShow) {
        group.visible = shouldShow;
        changed = true;
      }
    }

    for (const [id, entry] of selected) {
      if (fineLayers.has(id)) {
        const cached = fineLayers.get(id);
        fineLayers.delete(id);
        fineLayers.set(id, cached);
        continue;
      }
      const group = new THREE.Group();
      group.position.set(entry.x, entry.y, entry.z);
      group.rotation.y = THREE.MathUtils.degToRad(entry.rotation);
      group.scale.setScalar(entry.scale);
      const details = buildRackFineDetails(group, { rack: entry.rack, devices: entry.devices, unit: RACK_UNIT, deviceKind, palette });
      details.setSearchFilter?.(searchFilter);
      fineLayers.set(id, { group, details });
      scene.add(group);
      changed = true;
    }

    // 超出 LRU 上限时仅淘汰未显示的历史细节层。
    if (fineLayers.size > FINE_CACHE_LIMIT) {
      for (const [id, { group }] of fineLayers) {
        if (fineLayers.size <= FINE_CACHE_LIMIT) break;
        if (group.visible) continue;
        scene.remove(group);
        disposeObjects(group, { keepSharedMaterials: true });
        fineLayers.delete(id);
      }
    }

    if (changed) {
      const visibleIds = [...selected.keys()];
      model.lamps?.setNearbyRacks(visibleIds);
      lampAnimation?.sync();
      canvas.dataset.detailRacks = visibleIds.join(' ');
      canvas.dataset.detailCount = String(visibleIds.length);
    }
  }

  function pickDevice(hit) {
    if (!hit || Math.abs(hit.face.normal.y) > 0.5) return undefined;
    const entry = hit.object.userData.entry;
    if (!entry.devices.length) return undefined;
    if (deviceHitCache?.entry !== entry) {
      localRotation.setFromAxisAngle(yAxis, THREE.MathUtils.degToRad(entry.rotation));
      localTransform.compose(new THREE.Vector3(entry.x, entry.y, entry.z), localRotation, new THREE.Vector3().setScalar(entry.scale));
      localTransform.invert();
      const parts = entry.devices.map((device) => {
        const m = deviceMetrics(device, RACK_UNIT);
        const box = new THREE.Box3(
          new THREE.Vector3(-DEVICE_HALF_WIDTH, m.minY, m.minZ),
          new THREE.Vector3(DEVICE_HALF_WIDTH, m.maxY, m.maxZ),
        );
        return { device, box };
      });
      deviceHitCache = { entry, parts };
    }
    localRay.copy(ray.ray).applyMatrix4(localTransform);
    let nearest;
    let distance = Infinity;
    for (const { device, box } of deviceHitCache.parts) {
      if (!localRay.intersectBox(box, hitPoint)) continue;
      const next = hitPoint.distanceToSquared(localRay.origin);
      if (next >= distance) continue;
      nearest = device;
      distance = next;
    }
    return nearest;
  }

  function showTooltip(device, entry, event) {
    if (!entry || (device && String(device.id) === selectedDeviceId)) {
      hideTooltip();
      return;
    }
    if (!device) {
      const key = `rack:${entry.rack.id}:${viewMode}`;
      if (tooltip.dataset.deviceId !== key) {
        tooltip.dataset.deviceId = key;
        tooltipName.textContent = `${entry.rack.name} · ${entry.rack.height}U`;
        const s = entry.stats;
        tooltipPosition.textContent = viewMode === 'status'
          ? `运行 ${s.statusCounts.running} · 未通电 ${s.statusCounts.unpowered} · 停用 ${s.statusCounts.disabled} · 待核 ${s.statusCounts.unknown}`
          : `已用 ${s.usedU}/${entry.rack.height}U（空闲 ${s.freeU}U）${s.unknownDepthCount ? ` · 深度待核 ${s.unknownDepthCount} 台` : ''}`;
        tooltipStatus.hidden = true;
        tooltip.hidden = false;
      }
    } else {
      const id = `${device.id}:${viewMode}`;
      if (tooltip.dataset.deviceId !== id) {
        tooltip.dataset.deviceId = id;
        tooltipName.textContent = device.name;
        const depth = DEPTH_LABELS[normalizeDepth(device)];
        tooltipPosition.textContent = `${entry.rack.name} · ${device.face === 'front' ? '正面' : '背面'} ${units(device)} · ${depth}`;
        tooltipStatus.dataset.operatingStatus = normalizeStatus(device);
        tooltipStatus.textContent = operatingStatusLabel(device);
        tooltipStatus.hidden = false;
        tooltip.hidden = false;
      }
    }
    const bounds = viewport.getBoundingClientRect();
    const left = event.clientX - bounds.left + 12;
    const top = event.clientY - bounds.top + 12;
    tooltip.style.left = `${Math.max(6, Math.min(left, bounds.width - tooltip.offsetWidth - 6))}px`;
    tooltip.style.top = `${Math.max(6, Math.min(top, bounds.height - tooltip.offsetHeight - 6))}px`;
  }

  function hideTooltip() {
    tooltip.hidden = true;
    delete tooltip.dataset.deviceId;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    flight = undefined;
    clearPendingClick();
    motion.removeEventListener('change', changeMotion);
    observer.disconnect();
    lampAnimation?.dispose();
    if (frame != null) cancelAnimationFrame(frame);
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
    disposeObjects(scene);
    palette.dispose();
    floorTexture?.dispose();
    shadowTexture?.dispose();
    model.lamps?.texture?.dispose();
    environment?.dispose();
    fineLayers.clear();
    renderer.dispose();
    renderer.forceContextLoss();
    panel.remove();
  }

  return Object.assign(dispose, { snapshot, locateRack, locateDevice, clearLocatedDevice, resetView, deviceAnchor, setSearchFilter });
}
