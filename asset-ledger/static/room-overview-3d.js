import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { buildRackFineDetails, buildRackOverviewLayer } from './rack-3d-model.js?v=room-detail';

const COLUMN_GAP = 1.21;
const ROW_GAP = 2.30;
const RACK_SCALE = .535;
const RACK_UNIT = .12;
const RACK_BASE_Y = .100;
const RACK_BOTTOM = -.1605;
const RACK_TOP_MARGIN = .1065;
const CABINET_WIDTH = 1.98 * RACK_SCALE;
const CABINET_DEPTH = 1.27 * RACK_SCALE;
const MIN_ZOOM = .32;
const ANGLED = [.42, 2.30, 1.12];
const TOP = [0, 1, .001];

function disposeObjects(root) {
  const geometries = new Set();
  const materials = new Set();
  root.traverse((object) => {
    if (!object.isMesh && !object.isLineSegments) return;
    geometries.add(object.geometry);
    materials.add(object.material);
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

function makeRoom(scene, { room, racks, devices, deviceKind }) {
  const racksById = new Map(racks.map((rack) => [String(rack.id), rack]));
  const devicesByRack = new Map();
  for (const device of devices) {
    const id = String(device.rack_id);
    if (!racksById.has(id)) continue;
    if (!devicesByRack.has(id)) devicesByRack.set(id, []);
    devicesByRack.get(id).push(device);
  }
  const placements = new Map(room.positions.map((entry) => [`${entry.row}/${entry.slot}`, entry]));
  const width = room.columns * COLUMN_GAP + .68;
  const depth = (room.rows - 1) * ROW_GAP + 2.26;
  const finishes = new Map();
  const boxes = new Map();
  const symbols = [];
  const targets = [];
  const entries = [];
  const targetsById = new Map();
  const bounds = new THREE.Box3(
    new THREE.Vector3(-width / 2, -.16, -depth / 2), new THREE.Vector3(width / 2, 0, depth / 2),
  );
  const block = new THREE.BoxGeometry(1, 1, 1);
  const pickMaterial = new THREE.MeshBasicMaterial();
  const transform = new THREE.Matrix4();
  const location = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const level = new THREE.Quaternion();

  function finish(color) {
    if (!finishes.has(color)) {
      finishes.set(color, new THREE.MeshStandardMaterial({ color, roughness: .83, metalness: .07 }));
    }
    return finishes.get(color);
  }

  function flat(color, x, y, z, size) {
    const material = finish(color);
    if (!boxes.has(material)) boxes.set(material, []);
    transform.compose(location.set(x, y, z), level, scale.fromArray(size));
    boxes.get(material).push(transform.clone());
  }

  flat(0xafc0c0, 0, -.116, 0, [width, .088, depth]);
  flat(0xdbe5e4, 0, -.056, 0, [width + .032, .110, depth + .032]);
  for (let row = 1; row < room.rows; row += 1) {
    const z = (room.rows / 2 - row) * ROW_GAP;
    flat(0xc9d9d6, 0, .002, z, [width - .65, .007, .72]);
  }
  for (const side of [-1, 1]) {
    flat(0xc9d9d6, side * (width / 2 - .24), .002, 0, [.026, .008, depth - .32]);
    flat(0xc9d9d6, 0, .002, side * (depth / 2 - .18), [width - .46, .008, .026]);
  }

  for (let row = 1; row <= room.rows; row += 1) {
    for (let slot = 1; slot <= room.columns; slot += 1) {
      const x = (slot - (room.columns + 1) / 2) * COLUMN_GAP;
      const z = ((room.rows + 1) / 2 - row) * ROW_GAP;
      const entry = placements.get(`${row}/${slot}`);
      const rack = entry && racksById.get(String(entry.rack_id));
      flat(0xc0cecd, x, .002, z, [1.175, .008, 1.37]);
      flat(0xe8efed, x, .009, z, [1.135, .008, 1.32]);
      if (!rack) {
        for (const sx of [-1, 1]) {
          for (const sz of [-1, 1]) {
            flat(0x8fa9a5, x + sx * .50, .016, z + sz * .53, [.20, .006, .024]);
            flat(0x8fa9a5, x + sx * .54, .016, z + sz * .445, [.024, .006, .18]);
          }
        }
        symbols.push({ row, slot, point: new THREE.Vector3(x, .045, z) });
        continue;
      }

      const id = String(rack.id);
      const top = RACK_BASE_Y + (rack.height * RACK_UNIT + RACK_TOP_MARGIN) * RACK_SCALE;
      const bottom = RACK_BASE_Y + RACK_BOTTOM * RACK_SCALE;
      bounds.max.y = Math.max(bounds.max.y, top + .12);
      const rackEntry = { rack, devices: devicesByRack.get(id) ?? [], x, y: RACK_BASE_Y, z, rotation: entry.rotation,
        scale: RACK_SCALE, middle: (top + bottom) / 2 };
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
      symbols.push({ row, slot, rack, point: new THREE.Vector3(x, top + .04, z) });
    }
  }

  for (const [material, matrices] of boxes) {
    const mesh = new THREE.InstancedMesh(block, material, matrices.length);
    matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
  }
  buildRackOverviewLayer(scene, { entries, unit: RACK_UNIT, deviceKind });
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
  return { bounds, entries, highlight, symbols, targets };
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
  const toolbar = node('div', 'room-3d-toolbar');
  const presets = node('div', 'room-3d-presets');
  presets.setAttribute('role', 'group');
  presets.setAttribute('aria-label', '机房视角');
  const angledButton = node('button', '', '斜俯视');
  const topButton = node('button', '', '正俯视');
  angledButton.type = topButton.type = 'button';
  presets.append(angledButton, topButton);
  toolbar.append(presets, node('span', 'room-3d-hint', '拖动旋转，滚动或双指缩放'));

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
  viewport.append(canvas, labels, tooltip);
  panel.append(viewport, toolbar);
  host.replaceChildren(panel);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeff4f4);
  scene.add(new THREE.HemisphereLight(0xf8fcff, 0x748282, 2.1));
  const key = new THREE.DirectionalLight(0xfff2de, 2.4);
  key.position.set(-5, 12, 9);
  const fill = new THREE.DirectionalLight(0xf4f6f8, .52);
  fill.position.set(0, 3, 8);
  const rim = new THREE.DirectionalLight(0xc8e3f4, 1.30);
  rim.position.set(8, 6, -9);
  scene.add(key, fill, rim);
  const model = makeRoom(scene, { room: layout, racks, devices, deviceKind });
  const center = model.bounds.getCenter(new THREE.Vector3());
  const corners = [];
  for (const x of [model.bounds.min.x, model.bounds.max.x]) {
    for (const y of [model.bounds.min.y, model.bounds.max.y]) {
      for (const z of [model.bounds.min.z, model.bounds.max.z]) corners.push(new THREE.Vector3(x, y, z).sub(center));
    }
  }

  const camera = new THREE.PerspectiveCamera(35, 1, .04, 400);
  const controls = new OrbitControls(camera, viewport);
  controls.enablePan = false;
  controls.minPolarAngle = .001;
  controls.maxPolarAngle = Math.PI / 2 - .12;
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
  let disposed = false;
  let applyingPreset = false;
  let sized = false;
  let pressed;
  let hovered;
  let activeView;

  const preset = ['angled', 'top'].includes(initialCamera?.activeView) ? initialCamera.activeView : null;
  const restored = Array.isArray(initialCamera?.direction) && initialCamera.direction.length === 3 &&
    initialCamera.direction.every(Number.isFinite) && initialCamera.direction[1] > 0;
  const initial = {
    direction: restored ? initialCamera.direction : ANGLED,
    activeView: restored ? preset : 'angled',
    zoom: Number.isFinite(initialCamera?.zoom) ? THREE.MathUtils.clamp(initialCamera.zoom, MIN_ZOOM, 3) : 1,
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
        // 指针点击统一交给视口，键盘或辅助技术仍可触发按钮。
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
  controls.addEventListener('change', () => {
    if (applyingPreset) return;
    setActive(null);
    setHover(null);
    hideTooltip();
    invalidate();
  });
  viewport.addEventListener('pointerdown', (event) => {
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
      const rack = hit?.object.userData.entry.rack;
      setHover(rack);
      showTooltip(pickDevice(hit), rack, event);
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
      const rack = labelRack ?? pick(event)?.object.userData.entry.rack;
      if (rack) onRack(rack);
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
  resize();

  function fittedDistance(direction) {
    const right = new THREE.Vector3().crossVectors(camera.up, direction);
    if (right.lengthSq() < 1e-12) right.set(1, 0, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(direction, right);
    const vertical = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * .84;
    const horizontal = vertical * camera.aspect;
    return Math.max(...corners.map((corner) => corner.dot(direction) + Math.max(
      Math.abs(corner.dot(right)) / horizontal,
      Math.abs(corner.dot(up)) / vertical,
    )));
  }

  function placeView(direction, zoom) {
    const fit = fittedDistance(direction);
    controls.minDistance = Math.max(1, fit * MIN_ZOOM);
    controls.maxDistance = fit * 3;
    controls.target.copy(center);
    camera.position.copy(center).addScaledVector(direction, fit * zoom);
    applyingPreset = true;
    controls.update();
    applyingPreset = false;
    invalidate();
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
    placeView(new THREE.Vector3(...direction).normalize(), 1);
  }

  function snapshot() {
    if (!sized) return initial;
    const vector = new THREE.Vector3().subVectors(camera.position, center);
    const distance = vector.length();
    const direction = vector.normalize();
    return { direction: direction.toArray(), zoom: distance / fittedDistance(direction), activeView };
  }

  function resize() {
    if (!viewport.clientWidth || !viewport.clientHeight) return;
    const current = snapshot();
    renderer.setSize(viewport.clientWidth, viewport.clientHeight, false);
    camera.aspect = viewport.clientWidth / viewport.clientHeight;
    camera.updateProjectionMatrix();
    sized = true;
    placeView(new THREE.Vector3(...current.direction).normalize(), current.zoom);
  }

  function invalidate() {
    if (frame == null && !disposed && sized) frame = requestAnimationFrame(draw);
  }

  function draw() {
    frame = undefined;
    if (disposed) return;
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    camera.updateMatrixWorld();
    updateDetails(width);
    renderer.render(scene, camera);
    const labelLimit = width < 520 ? 12 : 24;
    labelItems.forEach(({ item, point, rack }, index) => {
      projected.copy(point).project(camera);
      item.hidden = (index >= labelLimit && (!rack || String(rack.id) !== hovered)) ||
        Math.abs(projected.x) > .985 || Math.abs(projected.y) > .985 || projected.z < -1 || projected.z > 1;
      if (!item.hidden) {
        item.style.left = `${(projected.x + 1) * width / 2}px`;
        item.style.top = `${(1 - projected.y) * height / 2}px`;
      }
      item.dataset.highlighted = String(Boolean(rack && String(rack.id) === hovered));
    });
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
    const { direction, zoom } = snapshot();
    const narrow = width < 520;
    const candidates = [];
    if (zoom <= .91 && direction[1] < .985) {
      for (const entry of model.entries) {
        const id = String(entry.rack.id);
        const active = fineLayers.has(id);
        if (zoom > (active ? .91 : .83)) continue;
        projected.set(entry.x, entry.middle, entry.z).project(camera);
        if (Math.abs(projected.x) > .95 || Math.abs(projected.y) > .95 || projected.z < -1 || projected.z > 1) continue;
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
      if (selected.has(id)) continue;
      scene.remove(group);
      disposeObjects(group);
      fineLayers.delete(id);
      changed = true;
    }
    for (const [id, entry] of selected) {
      if (fineLayers.has(id)) continue;
      const group = new THREE.Group();
      group.position.set(entry.x, entry.y, entry.z);
      group.rotation.y = THREE.MathUtils.degToRad(entry.rotation);
      group.scale.setScalar(entry.scale);
      buildRackFineDetails(group, { rack: entry.rack, devices: entry.devices, unit: RACK_UNIT, deviceKind });
      fineLayers.set(id, group);
      scene.add(group);
      changed = true;
    }
    if (changed) {
      canvas.dataset.detailRacks = [...fineLayers.keys()].join(' ');
      canvas.dataset.detailCount = String(fineLayers.size);
    }
  }

  function pickDevice(hit) {
    if (!hit || Math.abs(hit.face.normal.y) > .5) return undefined;
    const entry = hit.object.userData.entry;
    if (!entry.devices.length) return undefined;
    if (deviceHitCache?.entry !== entry) {
      localRotation.setFromAxisAngle(yAxis, THREE.MathUtils.degToRad(entry.rotation));
      localTransform.compose(new THREE.Vector3(entry.x, entry.y, entry.z), localRotation, new THREE.Vector3().setScalar(entry.scale));
      localTransform.invert();
      // Scale and mount ranges are the same as the shared rack model.
      const parts = entry.devices.map((device) => {
        const lower = (device.u_start - 1) * RACK_UNIT + .003;
        const upper = (device.u_start - 1 + device.u_height) * RACK_UNIT - .003;
        const full = device.mount_depth === 'full';
        const front = device.face === 'front';
        const minZ = full || !front ? -.593 : .025;
        const maxZ = full || front ? .593 : -.025;
        const box = new THREE.Box3(new THREE.Vector3(-.869, lower, minZ), new THREE.Vector3(.869, upper, maxZ));
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

  function showTooltip(device, rack, event) {
    if (!device) {
      hideTooltip();
      return;
    }
    const id = String(device.id);
    if (tooltip.dataset.deviceId !== id) {
      tooltip.dataset.deviceId = id;
      tooltipName.textContent = device.name;
      tooltipPosition.textContent = `${rack.name} · ${device.face === 'front' ? '正面' : '背面'} ${units(device)}`;
      tooltip.hidden = false;
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
    observer.disconnect();
    if (frame != null) cancelAnimationFrame(frame);
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
    disposeObjects(scene);
    fineLayers.clear();
    renderer.dispose();
    renderer.forceContextLoss();
    panel.remove();
  }

  return Object.assign(dispose, { snapshot });
}
