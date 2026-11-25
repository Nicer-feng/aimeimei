import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import {
  DEVICE_HALF_WIDTH, RACK_UNIT,
  deviceMetrics, normalizeDepth, rackOccupancy, rackVerticalBounds,
} from './rack-geometry.js';
import {
  animateOperatingLamps, buildRackFineDetails, buildRackOverviewLayer, createRackPalette,
} from './rack-3d-model.js';
import { operatingStatusLabel } from './rack.js?v=operating-status';

const COLUMN_GAP = 1.21;
const ROW_GAP = 2.30;
const RACK_SCALE = 0.535;
const CABINET_WIDTH = 1.98 * RACK_SCALE;
const CABINET_DEPTH = 1.27 * RACK_SCALE;
const MIN_DISTANCE = 1.05;
const FINE_CACHE_LIMIT = 12;
const ANGLED = [0.42, 2.30, 1.12];
const TOP = [0, 1, 0.001];

const VIEW_MODES = [
  { id: 'appearance', label: '外观' },
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

function makeRoom(scene, { room, racks, devices, deviceKind, palette }) {
  const racksById = new Map(racks.map((rack) => [String(rack.id), rack]));
  const devicesByRack = new Map();
  for (const device of devices) {
    const id = String(device.rack_id);
    if (!racksById.has(id)) continue;
    if (!devicesByRack.has(id)) devicesByRack.set(id, []);
    devicesByRack.get(id).push(device);
  }
  const placements = new Map(room.positions.map((entry) => [`${entry.row}/${entry.slot}`, entry]));
  const width = room.columns * COLUMN_GAP + 0.68;
  const depth = (room.rows - 1) * ROW_GAP + 2.26;
  const finishes = new Map();
  const boxes = new Map();
  const symbols = [];
  const targets = [];
  const entries = [];
  const targetsById = new Map();
  const bounds = new THREE.Box3(
    new THREE.Vector3(-width / 2, -0.16, -depth / 2), new THREE.Vector3(width / 2, 0, depth / 2),
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

  function flat(color, x, y, z, size) {
    const material = finish(color);
    if (!boxes.has(material)) boxes.set(material, []);
    transform.compose(location.set(x, y, z), level, scale.fromArray(size));
    boxes.get(material).push(transform.clone());
  }

  flat(0xafc0c0, 0, -0.116, 0, [width, 0.088, depth]);
  flat(0xdbe5e4, 0, -0.056, 0, [width + 0.032, 0.110, depth + 0.032]);
  for (let row = 1; row < room.rows; row += 1) {
    const z = (room.rows / 2 - row) * ROW_GAP;
    flat(0xc9d9d6, 0, 0.002, z, [width - 0.65, 0.007, 0.72]);
  }
  for (const side of [-1, 1]) {
    flat(0xc9d9d6, side * (width / 2 - 0.24), 0.002, 0, [0.026, 0.008, depth - 0.32]);
    flat(0xc9d9d6, 0, 0.002, side * (depth / 2 - 0.18), [width - 0.46, 0.008, 0.026]);
  }

  const baseY = 0.100;
  for (let row = 1; row <= room.rows; row += 1) {
    for (let slot = 1; slot <= room.columns; slot += 1) {
      const x = (slot - (room.columns + 1) / 2) * COLUMN_GAP;
      const z = ((room.rows + 1) / 2 - row) * ROW_GAP;
      const entry = placements.get(`${row}/${slot}`);
      const rack = entry && racksById.get(String(entry.rack_id));
      flat(0xc0cecd, x, 0.002, z, [1.175, 0.008, 1.37]);
      flat(0xe8efed, x, 0.009, z, [1.135, 0.008, 1.32]);
      if (!rack) {
        for (const sx of [-1, 1]) {
          for (const sz of [-1, 1]) {
            flat(0x8fa9a5, x + sx * 0.50, 0.016, z + sz * 0.53, [0.20, 0.006, 0.024]);
            flat(0x8fa9a5, x + sx * 0.54, 0.016, z + sz * 0.445, [0.024, 0.006, 0.18]);
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
        x, y: baseY, z, rotation: entry.rotation, scale: RACK_SCALE, middle: (top + bottom) / 2,
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
      symbols.push({ row, slot, rack, point: new THREE.Vector3(x, top + 0.05, z) });
    }
  }

  for (const [material, matrices] of boxes) {
    const mesh = new THREE.InstancedMesh(block, material, matrices.length);
    matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
  }
  const overviewLayer = buildRackOverviewLayer(scene, { entries, unit: RACK_UNIT, deviceKind, palette });
  if (!targets.length) pickMaterial.dispose();

  const outline = new THREE.LineSegments(new THREE.EdgesGeometry(block), new THREE.LineBasicMaterial({ color: 0x538f80 }));
  outline.visible = false;
  scene.add(outline);
  function highlight(id) {
    const target = targetsById.get(id);
    outline.visible = Boolean(target);
    if (!target) return;
    outline.position.copy(target.position);
    outline.rotation.copy(target.rotation);
    outline.scale.copy(target.scale).multiplyScalar(1.014);
  }
  return { bounds, entries, highlight, lamps: overviewLayer.lamps, setMode: overviewLayer.setMode, symbols, targets };
}

export function mountRoomScene(host, {
  layout, racks, initialCamera, onRack, onFallback, devices = [], deviceKind = () => 'server', units = (device) => `U${device.u_start}`,
}) {
  const panel = node('section', 'room-3d');
  panel.setAttribute('aria-label', '机房三维总览');
  const viewport = node('div', 'room-3d-viewport');
  const labels = node('div', 'room-3d-labels');
  labels.setAttribute('aria-label', '机柜及预留位');
  const tooltip = node('div', 'rack-spatial-tooltip room-3d-device-tooltip');
  tooltip.hidden = true;
  tooltip.setAttribute('aria-hidden', 'true');
  tooltip.style.zIndex = '3';
  const tooltipName = node('strong', '');
  const tooltipPosition = node('span', '');
  tooltip.append(tooltipName, tooltipPosition);

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
  toolbar.append(toolbarGroups, node('span', 'room-3d-hint', '左键旋转 · 右键平移 · 滚轮缩放'));

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  const canvas = renderer.domElement;
  canvas.className = 'room-3d-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', '三维机柜布局');
  canvas.dataset.detailCount = '0';
  canvas.dataset.detailRacks = '';
  viewport.append(canvas, labels, legend, tooltip);
  panel.append(viewport, toolbar);
  host.replaceChildren(panel);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeff4f4);
  scene.add(new THREE.HemisphereLight(0xf8fcff, 0x748282, 2.1));
  const key = new THREE.DirectionalLight(0xfff2de, 2.4);
  key.position.set(-5, 12, 9);
  const fill = new THREE.DirectionalLight(0xf4f6f8, 0.52);
  fill.position.set(0, 3, 8);
  const rim = new THREE.DirectionalLight(0xc8e3f4, 1.30);
  rim.position.set(8, 6, -9);
  scene.add(key, fill, rim);

  const palette = createRackPalette();
  const model = makeRoom(scene, { room: layout, racks, devices, deviceKind, palette });
  const center = model.bounds.getCenter(new THREE.Vector3());
  const corners = [];
  for (const x of [model.bounds.min.x, model.bounds.max.x]) {
    for (const y of [model.bounds.min.y, model.bounds.max.y]) {
      for (const z of [model.bounds.min.z, model.bounds.max.z]) corners.push(new THREE.Vector3(x, y, z).sub(center));
    }
  }

  const camera = new THREE.PerspectiveCamera(35, 1, 0.04, 400);
  const controls = new OrbitControls(camera, viewport);
  controls.enablePan = true;
  controls.screenSpacePanning = false;
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
  const fineLayers = new Map();
  let deviceHitCache;
  let frame;
  let flyFrame;
  let disposed = false;
  let applyingPreset = false;
  let sized = false;
  let pressed;
  let hovered;
  let activeView;
  let viewMode = VIEW_MODES.some((m) => m.id === initialCamera?.viewMode) ? initialCamera.viewMode : 'appearance';

  const preset = ['angled', 'top'].includes(initialCamera?.activeView) ? initialCamera.activeView : null;
  const restored = Array.isArray(initialCamera?.direction) && initialCamera.direction.length === 3 &&
    initialCamera.direction.every(Number.isFinite) && initialCamera.direction[1] > 0;
  const restoredTarget = Array.isArray(initialCamera?.target) && initialCamera.target.length === 3 &&
    initialCamera.target.every(Number.isFinite)
    ? new THREE.Vector3(...initialCamera.target) : center.clone();
  const initial = {
    direction: restored ? initialCamera.direction : ANGLED,
    activeView: restored ? preset : 'angled',
    zoom: Number.isFinite(initialCamera?.zoom) ? THREE.MathUtils.clamp(initialCamera.zoom, 0.12, 3) : 1,
    target: restoredTarget,
    viewMode,
  };
  setActive(initial.activeView);

  const labelItems = model.symbols.map((symbol) => {
    const rack = symbol.rack;
    const item = node(rack ? 'button' : 'span', `room-3d-label${rack ? '' : ' room-3d-label-reserved'}`,
      rack?.name ?? (layout.illustrative ? '预留' : '空位'));
    item.dataset.roomRow = symbol.row;
    item.dataset.roomSlot = symbol.slot;
    if (rack) {
      item.type = 'button';
      item.dataset.rackId = rack.id;
      item.title = `${rack.name} · ${rack.height}U`;
      item.setAttribute('aria-label', `查看机柜 ${rack.name}，${rack.height}U`);
      item.addEventListener('click', (event) => {
        if (event.detail === 0) onRack(rack);
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

  angledButton.addEventListener('click', () => usePreset('angled', ANGLED));
  topButton.addEventListener('click', () => usePreset('top', TOP));
  for (const [id, button] of modeButtons) {
    button.addEventListener('click', () => {
      if (viewMode === id) return;
      applyViewMode(id);
      invalidate();
    });
  }

  controls.addEventListener('change', () => {
    if (applyingPreset) return;
    cancelFly();
    clampTarget();
    setActive(null);
    setHover(null);
    hideTooltip();
    invalidate();
  });

  viewport.addEventListener('pointerdown', (event) => {
    cancelFly();
    hideTooltip();
    if (event.button === 0 && event.isPrimary) {
      const label = event.target.closest('button.room-3d-label');
      const rack = label ? racks.find((item) => String(item.id) === label.dataset.rackId) : undefined;
      pressed = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false, rack };
    } else if (pressed && event.pointerType === 'touch') pressed.moved = true;
  });
  viewport.addEventListener('pointermove', (event) => {
    if (pressed) {
      pressed.moved ||= Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 5;
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
    pressed = undefined;
    if (clicked) {
      const hit = labelRack ? null : pick(event);
      const rack = labelRack ?? hit?.object.userData.entry.rack;
      if (rack) onRack(rack, hit ? pickDevice(hit) : undefined);
    }
  });
  viewport.addEventListener('pointercancel', () => { pressed = undefined; });
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
  const lampAnimation = animateOperatingLamps(viewport, model.lamps, () => renderer.render(scene, camera));
  applyViewMode(viewMode);
  resize();

  function clampTarget() {
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, model.bounds.min.x, model.bounds.max.x);
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, model.bounds.min.z, model.bounds.max.z);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, 0, Math.max(0.4, model.bounds.max.y * 0.7));
  }

  function applyViewMode(mode) {
    viewMode = mode;
    for (const [id, button] of modeButtons) {
      button.setAttribute('aria-pressed', String(id === mode));
    }
    model.setMode(mode);
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
    applyingPreset = true;
    controls.update();
    applyingPreset = false;
    invalidate();
  }

  function cancelFly() {
    if (flyFrame != null) {
      cancelAnimationFrame(flyFrame);
      flyFrame = undefined;
    }
  }

  function flyTo(direction, zoom, target) {
    cancelFly();
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || !sized) {
      placeView(direction, zoom, target);
      return;
    }
    const startTarget = controls.target.clone();
    const startPos = camera.position.clone();
    const endTarget = target.clone();
    const fit = fittedDistance(direction);
    const endPos = endTarget.clone().addScaledVector(direction, fit * zoom);
    const startTime = performance.now();
    const duration = 260;

    function step(now) {
      if (disposed) return;
      const t = Math.min(1, (now - startTime) / duration);
      const ease = 1 - (1 - t) ** 3;
      controls.minDistance = MIN_DISTANCE;
      controls.maxDistance = fit * 3;
      controls.target.lerpVectors(startTarget, endTarget, ease);
      camera.position.lerpVectors(startPos, endPos, ease);
      applyingPreset = true;
      controls.update();
      applyingPreset = false;
      invalidate();
      if (t < 1) flyFrame = requestAnimationFrame(step);
      else flyFrame = undefined;
    }
    flyFrame = requestAnimationFrame(step);
  }

  function setActive(view) {
    activeView = view;
    angledButton.setAttribute('aria-pressed', String(view === 'angled'));
    topButton.setAttribute('aria-pressed', String(view === 'top'));
  }

  function usePreset(view, direction) {
    setActive(view);
    setHover(null);
    hideTooltip();
    flyTo(new THREE.Vector3(...direction).normalize(), 1, center);
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
    if (!viewport.clientWidth || !viewport.clientHeight) return;
    const current = snapshot();
    renderer.setSize(viewport.clientWidth, viewport.clientHeight, false);
    camera.aspect = viewport.clientWidth / viewport.clientHeight;
    camera.updateProjectionMatrix();
    sized = true;
    const targetVec = current.target instanceof THREE.Vector3
      ? current.target : new THREE.Vector3(...(current.target ?? center.toArray()));
    placeView(new THREE.Vector3(...current.direction).normalize(), current.zoom, targetVec);
  }

  function invalidate() {
    if (frame == null && !disposed && sized) frame = requestAnimationFrame(draw);
  }

  function layoutLabels(width, height) {
    const narrow = width < 520;
    const maxLabels = narrow ? 18 : 48;
    const showEmpty = model.symbols.length <= 24;
    const placedBoxes = [];
    const candidates = [];

    for (const entry of labelItems) {
      const { item, point, rack } = entry;
      const isHovered = Boolean(rack && String(rack.id) === hovered);
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
      candidates.push({ entry, left, top, dist, isHovered, isRack: Boolean(rack) });
    }

    candidates.sort((a, b) => {
      if (a.isHovered !== b.isHovered) return a.isHovered ? -1 : 1;
      if (a.isRack !== b.isRack) return a.isRack ? -1 : 1;
      return a.dist - b.dist;
    });

    let visibleCount = 0;
    for (const { entry, left, top, isHovered } of candidates) {
      const { item, rack } = entry;
      const estW = Math.min(120, Math.max(46, (rack ? rack.name.length : 2) * 9 + 18));
      const estH = 22;
      const box = { l: left - estW / 2 - 4, r: left + estW / 2 + 4, t: top - estH - 4, b: top + 2 };
      const collides = !isHovered && placedBoxes.some((p) => box.l < p.r && box.r > p.l && box.t < p.b && box.b > p.t);
      if (collides || (!isHovered && visibleCount >= maxLabels)) {
        item.hidden = true;
      } else {
        item.hidden = false;
        item.style.left = `${left}px`;
        item.style.top = `${top}px`;
        placedBoxes.push(box);
        visibleCount += 1;
      }
      item.dataset.highlighted = String(isHovered);
    }
  }

  function draw() {
    frame = undefined;
    if (disposed) return;
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    camera.updateMatrixWorld();
    updateDetails(width);
    renderer.render(scene, camera);
    layoutLabels(width, height);
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
    model.highlight(id);
    hovered = id;
    canvas.dataset.pickable = String(Boolean(id));
    if (id) canvas.dataset.hoveredRackId = id;
    else delete canvas.dataset.hoveredRackId;
    invalidate();
  }

  function updateDetails(width) {
    const viewDir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
    const narrow = width < 520;
    const candidates = [];
    if (viewDir.y < 0.985) {
      for (const entry of model.entries) {
        const id = String(entry.rack.id);
        const activeGroup = fineLayers.get(id);
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

    for (const [id, group] of fineLayers) {
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
      buildRackFineDetails(group, { rack: entry.rack, devices: entry.devices, unit: RACK_UNIT, deviceKind, palette });
      fineLayers.set(id, group);
      scene.add(group);
      changed = true;
    }

    // 超出 LRU 上限时仅淘汰未显示的历史细节层。
    if (fineLayers.size > FINE_CACHE_LIMIT) {
      for (const [id, group] of fineLayers) {
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
    if (!entry) {
      hideTooltip();
      return;
    }
    if (!device) {
      if (viewMode === 'appearance') {
        hideTooltip();
        return;
      }
      const key = `rack:${entry.rack.id}:${viewMode}`;
      if (tooltip.dataset.deviceId !== key) {
        tooltip.dataset.deviceId = key;
        tooltipName.textContent = `${entry.rack.name} · ${entry.rack.height}U`;
        const s = entry.stats;
        tooltipPosition.textContent = viewMode === 'status'
          ? `运行 ${s.statusCounts.running} · 未通电 ${s.statusCounts.unpowered} · 停用 ${s.statusCounts.disabled} · 待核 ${s.statusCounts.unknown}`
          : `已用 ${s.usedU}/${entry.rack.height}U（空闲 ${s.freeU}U）${s.unknownDepthCount ? ` · 深度待核 ${s.unknownDepthCount} 台` : ''}`;
        tooltip.hidden = false;
      }
    } else {
      const id = `${device.id}:${viewMode}`;
      if (tooltip.dataset.deviceId !== id) {
        tooltip.dataset.deviceId = id;
        tooltipName.textContent = device.name;
        const depth = DEPTH_LABELS[normalizeDepth(device)];
        tooltipPosition.textContent = `${entry.rack.name} · ${device.face === 'front' ? '正面' : '背面'} ${units(device)} · ${depth} · ${operatingStatusLabel(device)}`;
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
    cancelFly();
    observer.disconnect();
    lampAnimation?.dispose();
    if (frame != null) cancelAnimationFrame(frame);
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
    disposeObjects(scene);
    palette.dispose();
    fineLayers.clear();
    renderer.dispose();
    renderer.forceContextLoss();
    panel.remove();
  }

  return Object.assign(dispose, { snapshot });
}
