import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { DETAIL_Z, DEVICE_HALF_WIDTH, MOUNT_FULL_Z, RACK_DEPTH, RACK_UNIT, deviceMetrics } from './rack-geometry.js';
import { animateOperatingLamps, buildRackModel, projectCabinetRect, projectScenePoint } from './rack-3d-model.js';
import { isSelectableRackSlot, operatingStatus, operatingStatusLabel, rackFaceSlots, rackSlotSelection } from './rack.js?v=operating-status';
import { createContactShadowTexture, createRackEnvironment } from './rack-textures.js';

const CAMERA_TRANSITION_MS = 240;
const MAX_DAMPING_TAIL_MS = 1000;
const CAMERA_VIEWS = [
  { label: '斜视', direction: [0.65, 0.29, 1] },
  { label: '看正面', direction: [0, 0.035, 1] },
  { label: '看背面', direction: [0, 0.035, -1] },
];

const RACK_MODES = [
  { id: 'appearance', label: '外观' },
  { id: 'status', label: '运行状态' },
  { id: 'depth', label: '深度核查' },
];

const FACE_LABELS = { front: '正面', rear: '背面' };
const SLOT_MARKS = {
  'cross-face': { color: '#497bb5', label: '跨面占用' },
  'half-only': { color: '#258976', label: '空位限半深' },
  unknown: { color: '#d28324', label: '对面深度待核' },
};

const RACK_LEGENDS = {
  status: [
    ['#3fa86b', '运行中'],
    ['#d14d43', '未通电'],
    ['#7b8a94', '已停用'],
    ['#d89b32', '待核实'],
  ],
  depth: [
    ['#3b6998', '全深（占正背面）'],
    ['#4b93a8', '半深（可共享 U 位）'],
    ['#e5a131', '本面设备深度待核'],
    ...Object.values(SLOT_MARKS).map(({ color, label }) => [color, label]),
  ],
};

export function rackFaceSlotAt(ray, slots) {
  const sign = Math.sign(ray.origin.z);
  if (Math.abs(ray.origin.z) <= MOUNT_FULL_Z || ray.direction.z * sign >= -1e-6) return undefined;
  const distance = (sign * MOUNT_FULL_Z - ray.origin.z) / ray.direction.z;
  const x = ray.origin.x + distance * ray.direction.x;
  const y = ray.origin.y + distance * ray.direction.y;
  if (Math.abs(x) > DEVICE_HALF_WIDTH || y < 0) return undefined;
  const face = sign > 0 ? 'front' : 'rear';
  return slots[face].get(Math.floor(y / RACK_UNIT) + 1);
}

function addSlotMarkers(scene, faceSlots) {
  const group = new THREE.Group();
  const geometry = new THREE.PlaneGeometry(0.052, RACK_UNIT * 0.74);
  const matrix = new THREE.Matrix4();
  for (const [kind, { color }] of Object.entries(SLOT_MARKS)) {
    const slots = [...faceSlots.front.values(), ...faceSlots.rear.values()].filter((slot) => slot.kind === kind);
    if (!slots.length) continue;
    const marks = new THREE.InstancedMesh(geometry, new THREE.MeshBasicMaterial({ color, toneMapped: false }), slots.length * 2);
    for (const [index, { face, u_start }] of slots.entries()) {
      const sign = face === 'front' ? 1 : -1;
      for (const [rail, x] of [-0.822, 0.822].entries()) {
        matrix.makeRotationY(sign > 0 ? 0 : Math.PI);
        matrix.setPosition(x, (u_start - 0.5) * RACK_UNIT, sign * (DETAIL_Z + 0.015));
        marks.setMatrixAt(index * 2 + rail, matrix);
      }
    }
    group.add(marks);
  }
  if (!group.children.length) geometry.dispose();
  scene.add(group);
  return group;
}

function slotControls(faceSlots, onEmpty, initialFace) {
  const group = document.createElement('div');
  group.className = 'rack-spatial-slot-controls';
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', '按面和 U 位新增设备');
  const face = document.createElement('select');
  face.className = 'rack-spatial-slot-face';
  face.setAttribute('aria-label', '安装面');
  for (const [value, label] of Object.entries(FACE_LABELS)) face.append(new Option(label, value));
  const unit = document.createElement('select');
  unit.className = 'rack-spatial-slot-u';
  unit.setAttribute('aria-label', '可用起始 U 位');
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'rack-spatial-slot-add';
  add.textContent = '在此新增';
  add.addEventListener('click', () => {
    const slot = faceSlots[face.value].get(Number(unit.value));
    if (isSelectableRackSlot(slot)) onEmpty(rackSlotSelection(slot));
  });
  face.addEventListener('change', refresh);
  group.append(face, unit, add);
  setFace(initialFace);
  return { group, setFace };

  function setFace(next) {
    face.value = next;
    refresh();
  }

  function refresh() {
    const previousUnit = unit.value;
    const slots = [...faceSlots[face.value].values()].filter(isSelectableRackSlot).reverse();
    unit.replaceChildren(...slots.map((slot) => new Option(
      `U${slot.u_start}${slot.kind === 'half-only' ? '（限半深）' : ''}`, slot.u_start,
    )));
    if (slots.some((slot) => String(slot.u_start) === previousUnit)) unit.value = previousUnit;
    if (!slots.length) unit.append(new Option('本面无可用 U 位'));
    unit.disabled = add.disabled = !slots.length;
  }
}

function addContactShadow(scene, bounds) {
  const map = createContactShadowTexture();
  if (!map) return;
  const size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(size.x * 1.48, size.z * 1.65),
    new THREE.MeshBasicMaterial({ map, transparent: true, depthWrite: false, toneMapped: false }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(center.x, bounds.min.y - 0.008, center.z);
  scene.add(shadow);
}

export function mountRackScene(host, {
  rack, devices, onDevice, onEmpty, deviceKind, units, depthLabel, onContextLost, onSceneInteraction, initialCamera,
  initialDeviceId, faceSlots = rackFaceSlots(rack, devices),
}) {
  const initialView = initialCamera ?? { direction: CAMERA_VIEWS[0].direction, zoom: 1, activeView: 0, viewMode: 'appearance' };
  let viewMode = RACK_MODES.some((m) => m.id === initialView.viewMode) ? initialView.viewMode : 'appearance';
  let doorVisible = Boolean(initialView.doorVisible && viewMode === 'appearance' && initialDeviceId == null);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  const panel = document.createElement('div');
  panel.className = 'rack-spatial-panel';
  const viewport = document.createElement('div');
  viewport.className = 'rack-spatial-viewport';
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.16;
  const canvas = renderer.domElement;
  canvas.tabIndex = -1;
  canvas.setAttribute('aria-label', `${rack.name} 三维机柜`);
  canvas.setAttribute('role', 'img');
  canvas.dataset.pickable = 'false';
  const tooltip = document.createElement('div');
  tooltip.className = 'rack-spatial-tooltip';
  tooltip.hidden = true;
  tooltip.setAttribute('aria-hidden', 'true');
  const tooltipName = document.createElement('strong');
  const tooltipPosition = document.createElement('span');
  const tooltipStatus = document.createElement('span');
  tooltipStatus.className = 'rack-spatial-tooltip-status';
  tooltip.append(tooltipName, tooltipPosition, tooltipStatus);
  const legend = document.createElement('div');
  legend.className = 'rack-spatial-legend';
  legend.hidden = true;
  viewport.append(canvas, legend, tooltip);
  panel.append(viewport);

  const toolbar = document.createElement('div');
  toolbar.className = 'rack-spatial-toolbar';
  const toolbarGroups = document.createElement('div');
  toolbarGroups.className = 'rack-spatial-toolbar-groups';
  const rotation = document.createElement('div');
  rotation.className = 'rack-camera-controls';
  rotation.setAttribute('role', 'group');
  rotation.setAttribute('aria-label', '观察机柜');
  const viewButtons = CAMERA_VIEWS.map(({ label, direction }, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.setAttribute('aria-pressed', String(index === initialView.activeView));
    button.addEventListener('click', () => {
      const moved = index !== activeView;
      markFocusedDevice();
      setActiveView(index);
      const directionVector = new THREE.Vector3(...direction).normalize();
      transitionView(directionVector, fittedDistance(directionVector), center);
      slotPicker?.setFace(index === 2 ? 'rear' : 'front');
      if (moved) onSceneInteraction?.();
    });
    rotation.append(button);
    return button;
  });
  const doorButton = document.createElement('button');
  doorButton.type = 'button';
  doorButton.textContent = '柜门';
  doorButton.title = '显示柜门';
  doorButton.setAttribute('aria-label', '柜门');
  doorButton.addEventListener('click', () => setDoorVisible(!doorVisible));
  rotation.append(doorButton);

  const modeGroup = document.createElement('div');
  modeGroup.className = 'rack-camera-controls';
  modeGroup.setAttribute('role', 'group');
  modeGroup.setAttribute('aria-label', '着色模式');
  const modeButtons = new Map();
  for (const { id, label } of RACK_MODES) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', () => {
      if (viewMode === id) return;
      applyViewMode(id);
      invalidate();
    });
    modeGroup.append(button);
    modeButtons.set(id, button);
  }
  toolbarGroups.append(rotation, modeGroup);

  const hover = document.createElement('span');
  hover.className = 'rack-spatial-hover';
  const hint = window.matchMedia('(pointer: coarse)').matches
    ? '单指旋转 · 双指缩放和平移'
    : '左键旋转 · 右键平移 · 滚轮缩放';
  hover.textContent = hint;
  toolbar.append(toolbarGroups, hover);
  viewport.append(toolbar);
  const slotPicker = onEmpty && slotControls(faceSlots, onEmpty, initialView.direction[2] < 0 ? 'rear' : 'front');
  if (slotPicker) panel.append(slotPicker.group);

  const shortcuts = document.createElement('div');
  shortcuts.className = 'rack-spatial-devices';
  shortcuts.setAttribute('aria-label', '机柜设备');
  for (const device of devices) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.deviceId = device.id;
    button.setAttribute('aria-pressed', 'false');
    button.textContent = `${device.face === 'front' ? '正面' : '背面'} ${units(device)} · ${device.name} · ${depthLabel(device)} · ${operatingStatusLabel(device)}`;
    button.addEventListener('click', () => {
      onSceneInteraction?.();
      focusDevice(device.id, () => onDevice(device, makeAnchor(device, button)));
    });
    shortcuts.append(button);
  }
  if (devices.length) panel.append(shortcuts);
  host.replaceChildren(panel);

  const scene = new THREE.Scene();
  const environment = createRackEnvironment(renderer);
  if (environment) {
    scene.environment = environment.texture;
    scene.environmentIntensity = 0.48;
  }
  scene.add(new THREE.HemisphereLight(0xf2f8ff, 0x687788, 1.8));
  addLight(0xfff2e3, 3.3, [-4, 8, 6]);
  addLight(0xc2d9f6, 1.5, [4, 3, 3]);
  addLight(0xecf5ff, 2.6, [1, 5, -7]);
  const model = buildRackModel(scene, { rack, devices, deviceKind, unit: RACK_UNIT });
  const bounds = new THREE.Box3().setFromObject(scene);
  const center = bounds.getCenter(new THREE.Vector3());
  const corners = [];
  for (const x of [bounds.min.x, bounds.max.x]) {
    for (const y of [bounds.min.y, bounds.max.y]) {
      for (const z of [bounds.min.z, bounds.max.z]) corners.push(new THREE.Vector3(x, y, z).sub(center));
    }
  }
  addContactShadow(scene, bounds);
  const slotMarkers = addSlotMarkers(scene, faceSlots);
  const slotHover = new THREE.Mesh(
    new THREE.PlaneGeometry(DEVICE_HALF_WIDTH * 1.93, RACK_UNIT * 0.86),
    new THREE.MeshBasicMaterial({ color: '#66c8aa', opacity: 0.38, transparent: true, depthWrite: false, toneMapped: false }),
  );
  slotHover.visible = false;
  scene.add(slotHover);

  const camera = new THREE.PerspectiveCamera(36, 1, 0.04, 120);
  const controls = new OrbitControls(camera, renderer.domElement);
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const renderSize = new THREE.Vector2();
  const requestedTarget = new THREE.Vector3();
  const transitionOffset = new THREE.Vector3();
  const transitionSpherical = new THREE.Spherical();
  let down;
  let hovered;
  let selectedDeviceId = null;
  let focusedDeviceId;
  let pendingDeviceId = initialCamera ? undefined : initialDeviceId;
  let activeView = initialView.activeView;
  let applyingView = false;
  let sized = false;
  let disposed = false;
  let renderFrame;
  let settling = false;
  let settleBy = 0;
  let transition;
  controls.enablePan = true;
  controls.enableDamping = !reducedMotion.matches;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;
  controls.minDistance = 0.90;
  controls.minPolarAngle = 0.25;
  controls.maxPolarAngle = 1.82;
  controls.addEventListener('start', () => {
    if (transition) setActiveView(-1);
    transition = undefined;
    clearHover();
    invalidate();
  });
  controls.addEventListener('change', () => {
    if (applyingView) return;
    clampTarget();
    setActiveView(-1);
    clearHover();
    settling = controls.enableDamping;
    settleBy = performance.now() + MAX_DAMPING_TAIL_MS;
    invalidate();
    onSceneInteraction?.();
  });
  reducedMotion.addEventListener('change', updateMotionPreference);

  const observer = new ResizeObserver(resize);
  observer.observe(viewport);
  const lampAnimation = animateOperatingLamps(viewport, model.lamps, invalidate);
  applyViewMode(viewMode);
  setSelectedDevice(initialDeviceId ?? null);
  resize();

  canvas.addEventListener('pointerdown', (event) => {
    if (!event.isPrimary && event.pointerType === 'touch') down = undefined;
    if (event.button === 0 && event.isPrimary) {
      down = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    }
  });
  canvas.addEventListener('pointercancel', () => { down = undefined; });
  canvas.addEventListener('pointermove', (event) => {
    if (down) {
      if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) down.moved = true;
      return;
    }
    if (event.pointerType === 'touch') return;
    if (doorVisible) return;
    const hit = pick(event);
    if (hit) showHover(hit, event);
    else if (clearHover()) invalidate();
  });
  canvas.addEventListener('pointerleave', () => { if (clearHover()) invalidate(); });
  canvas.addEventListener('pointerup', (event) => {
    const isClick = down?.pointerId === event.pointerId && !down.moved &&
      Math.hypot(event.clientX - down.x, event.clientY - down.y) <= 5;
    down = undefined;
    if (!isClick) return;
    const hit = pick(event);
    if (clearHover()) invalidate();
    if (doorVisible) {
      if (hit) setDoorVisible(false);
      if (!hit?.device) return;
    }
    if (hit?.device) onDevice(hit.device, makeAnchor(hit.device, canvas, { x: event.clientX, y: event.clientY }));
    else if (onEmpty && isSelectableRackSlot(hit?.slot)) onEmpty(rackSlotSelection(hit.slot));
    else if (hit?.slot?.kind === 'unknown' && event.pointerType === 'touch') showHover(hit, event);
  });
  const contextLost = (event) => {
    event.preventDefault();
    onContextLost();
  };
  canvas.addEventListener('webglcontextlost', contextLost);

  return Object.assign(dispose, { snapshot, deviceAnchor, setSelectedDevice, focusDevice });

  function makeAnchor(device, anchorElement, point) {
    return {
      element: anchorElement,
      ...(anchorElement === canvas ? { viewport, ...point } : {}),
      visible: () => anchorElement.isConnected && anchorElement.getClientRects().length > 0,
      cabinetRect: () => projectCabinetRect(camera, canvas, bounds),
      devicePoint() {
        const { centerY, full, sign } = deviceMetrics(device, RACK_UNIT);
        const visibleFace = full ? (camera.position.z >= 0 ? 1 : -1) : sign;
        return projectScenePoint(camera, canvas, new THREE.Vector3(0, centerY, visibleFace * DETAIL_Z));
      },
      setSelected(selected) {
        if (selected || selectedDeviceId === device.id) setSelectedDevice(selected ? device.id : null);
      },
    };
  }

  function deviceAnchor(deviceId) {
    const device = devices.find((item) => item.id === deviceId);
    return device ? makeAnchor(device, canvas) : null;
  }

  function setSelectedDevice(deviceId) {
    if (disposed) return;
    if (deviceId != null && doorVisible) setDoorVisible(false);
    selectedDeviceId = deviceId;
    if (deviceId == null) delete canvas.dataset.selectedDeviceId;
    else canvas.dataset.selectedDeviceId = deviceId;
    updateDeviceSelection();
  }

  function setDoorVisible(visible) {
    doorVisible = visible;
    doorButton.setAttribute('aria-pressed', String(visible));
    model.setDoorVisible(visible);
    if (visible) clearHover();
    invalidate();
  }

  function clampTarget() {
    requestedTarget.copy(controls.target);
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -1.0, 1.0);
    const depthLimit = RACK_DEPTH / 2 + 0.15;
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, -depthLimit, depthLimit);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, bounds.min.y, bounds.max.y);
    if (!requestedTarget.equals(controls.target)) camera.position.sub(requestedTarget).add(controls.target);
  }

  function applyViewMode(mode) {
    viewMode = mode;
    doorButton.disabled = mode !== 'appearance';
    setDoorVisible(mode === 'appearance' && doorVisible);
    for (const [id, button] of modeButtons) {
      button.setAttribute('aria-pressed', String(id === mode));
    }
    model.setMode(mode);
    slotMarkers.visible = mode === 'depth';
    const entries = RACK_LEGENDS[mode];
    if (!entries) {
      legend.hidden = true;
      legend.replaceChildren();
    } else {
      legend.replaceChildren(...entries.map(([color, text]) => {
        const item = document.createElement('span');
        item.className = 'rack-spatial-legend-item';
        const dot = document.createElement('i');
        dot.className = 'rack-spatial-legend-dot';
        dot.style.backgroundColor = color;
        item.append(dot, text);
        return item;
      }));
      legend.hidden = false;
    }
    lampAnimation?.sync();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (renderFrame != null) cancelAnimationFrame(renderFrame);
    observer.disconnect();
    lampAnimation?.dispose();
    reducedMotion.removeEventListener('change', updateMotionPreference);
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
    model.disposeExtra?.();
    const geometries = new Set();
    const materials = new Set();
    const textures = new Set();
    scene.traverse((object) => {
      if (!object.isMesh) return;
      geometries.add(object.geometry);
      for (const material of [].concat(object.material)) {
        materials.add(material);
        if (material.map) textures.add(material.map);
      }
      if (object.isInstancedMesh) object.dispose();
    });
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    for (const texture of textures) texture.dispose();
    environment?.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  }

  function snapshot() {
    if (!sized) return undefined;
    const offset = camera.position.clone().sub(controls.target);
    const distance = offset.length();
    const direction = offset.normalize();
    return {
      direction: direction.toArray(),
      zoom: distance / fittedDistance(direction),
      target: controls.target.toArray(),
      activeView,
      viewMode,
      doorVisible,
    };
  }

  function addLight(color, intensity, position) {
    const light = new THREE.DirectionalLight(color, intensity);
    light.position.set(...position);
    scene.add(light);
  }

  function setActiveView(index) {
    if (index === activeView) return;
    activeView = index;
    for (const [position, button] of viewButtons.entries()) {
      button.setAttribute('aria-pressed', String(position === index));
    }
  }

  function fittedDistance(direction) {
    const right = new THREE.Vector3().crossVectors(camera.up, direction).normalize();
    const up = new THREE.Vector3().crossVectors(direction, right);
    // 手机上的 HUD 可能换行，给完整机柜留出底部可点击空间。
    const bottomInset = toolbar.offsetHeight + 14;
    const frame = THREE.MathUtils.clamp(1 - 2 * bottomInset / Math.max(1, viewport.clientHeight), 0.42, 0.82);
    const vertical = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * frame;
    const horizontal = vertical * camera.aspect;
    // 按当前相机方向投影柜体的八个角，兼顾纵向高柜和窄屏横向空间。
    return Math.max(...corners.map((corner) => corner.dot(direction) + Math.max(
      Math.abs(corner.dot(right)) / horizontal,
      Math.abs(corner.dot(up)) / vertical,
    )));
  }

  function placeView(direction, distance, target) {
    controls.maxDistance = fittedDistance(direction) * 2.8;
    controls.target.copy(target);
    camera.position.copy(target).addScaledVector(direction, distance);
    clampTarget();
    updateControls();
    camera.updateMatrixWorld();
  }

  function updateControls() {
    applyingView = true;
    const moved = controls.update();
    applyingView = false;
    return moved;
  }

  function stopDamping() {
    settling = false;
    if (!controls.enableDamping) return;
    const position = camera.position.clone();
    const target = controls.target.clone();
    // 清空 OrbitControls 累积的惯性，并恢复切换前这一帧的相机。
    controls.enableDamping = false;
    updateControls();
    controls.target.copy(target);
    camera.position.copy(position);
    updateControls();
    controls.enableDamping = true;
  }

  function transitionView(direction, distance, target, onArrive) {
    clearHover();
    stopDamping();
    transition = undefined;
    if (reducedMotion.matches || !sized) {
      placeView(direction, distance, target);
      onArrive?.();
    } else {
      const start = new THREE.Spherical().setFromVector3(transitionOffset.copy(camera.position).sub(controls.target));
      const end = new THREE.Spherical().setFromVector3(direction.clone().multiplyScalar(distance));
      // 用球面方向过渡，切换正背面时相机沿柜外转动。
      const angle = THREE.MathUtils.euclideanModulo(end.theta - start.theta + Math.PI, 2 * Math.PI) - Math.PI;
      controls.maxDistance = Math.max(controls.maxDistance, end.radius, fittedDistance(direction) * 2.8);
      transition = {
        start, end, angle, fromTarget: controls.target.clone(), target, direction, distance, onArrive, started: performance.now(),
      };
    }
    invalidate();
  }

  function updateTransition(now) {
    const { start, end, angle, fromTarget, target, direction, distance, onArrive, started } = transition;
    const progress = Math.min(1, Math.max(0, (now - started) / CAMERA_TRANSITION_MS));
    if (progress === 1) {
      transition = undefined;
      placeView(direction, distance, target);
      onArrive?.();
      return;
    }
    const ease = 1 - (1 - progress) ** 3;
    transitionSpherical.set(
      THREE.MathUtils.lerp(start.radius, end.radius, ease),
      THREE.MathUtils.lerp(start.phi, end.phi, ease),
      start.theta + angle * ease,
    );
    controls.target.lerpVectors(fromTarget, target, ease);
    camera.position.copy(controls.target).add(transitionOffset.setFromSpherical(transitionSpherical));
    clampTarget();
    updateControls();
  }

  function updateMotionPreference() {
    if (reducedMotion.matches) {
      stopDamping();
      if (transition) {
        const { direction, distance, target, onArrive } = transition;
        transition = undefined;
        placeView(direction, distance, target);
        onArrive?.();
      }
      invalidate();
    }
    controls.enableDamping = !reducedMotion.matches;
  }

  function invalidate() {
    if (!disposed && renderFrame == null) renderFrame = requestAnimationFrame(render);
  }

  function render(now) {
    renderFrame = undefined;
    if (!sized || disposed) return;
    if (transition) updateTransition(now);
    else if (settling) {
      settling = updateControls();
      clampTarget();
      if (now >= settleBy) stopDamping();
    }
    if (disposed) return;
    renderer.render(scene, camera);
    if (transition || settling) invalidate();
  }

  function markFocusedDevice(deviceId) {
    focusedDeviceId = deviceId;
    if (deviceId == null) delete canvas.dataset.focusedDeviceId;
    else canvas.dataset.focusedDeviceId = deviceId;
    updateDeviceSelection();
  }

  function updateDeviceSelection() {
    const activeDeviceId = selectedDeviceId ?? focusedDeviceId;
    for (const button of shortcuts.children) {
      button.setAttribute('aria-pressed', String(button.dataset.deviceId === String(activeDeviceId)));
    }
    model.highlight(activeDeviceId ?? hovered?.device?.id ?? null);
    invalidate();
  }

  function focusDevice(id, onArrive) {
    if (disposed) return false;
    const device = devices.find(({ id: itemId }) => String(itemId) === String(id));
    if (!device) return false;
    if (doorVisible) setDoorVisible(false);
    if (!sized) {
      pendingDeviceId = device.id;
      return true;
    }
    const { centerY, faceHeight, front, minZ, maxZ } = deviceMetrics(device, RACK_UNIT);
    const direction = new THREE.Vector3(0, 0.035, front ? 1 : -1).normalize();
    const halfFov = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const distance = Math.max(
      (DEVICE_HALF_WIDTH + 0.09) / (halfFov * camera.aspect * 0.84),
      (faceHeight / 2 + RACK_UNIT * 2) / (halfFov * 0.72),
      1.65,
    );
    setActiveView(-1);
    markFocusedDevice(device.id);
    slotPicker?.setFace(device.face);
    transitionView(direction, distance, new THREE.Vector3(0, centerY, front ? maxZ : minZ), onArrive);
    return true;
  }

  function resize() {
    const width = viewport.clientWidth;
    const viewportHeight = viewport.clientHeight;
    if (!width || !viewportHeight) return;
    if (sized && width === renderSize.x && viewportHeight === renderSize.y) return;
    const current = snapshot() ?? initialView;
    renderer.setSize(width, viewportHeight, false);
    camera.aspect = width / viewportHeight;
    camera.updateProjectionMatrix();
    sized = true;
    const targetVec = Array.isArray(current.target) && current.target.length === 3
      ? new THREE.Vector3(...current.target) : center;
    const direction = new THREE.Vector3(...current.direction).normalize();
    placeView(direction, fittedDistance(direction) * current.zoom, targetVec);
    renderSize.set(width, viewportHeight);
    if (pendingDeviceId != null) {
      const id = pendingDeviceId;
      pendingDeviceId = undefined;
      focusDevice(id);
    }
    invalidate();
  }

  function pick(event) {
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return undefined;
    pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    camera.updateMatrixWorld();
    raycaster.setFromCamera(pointer, camera);
    const slot = rackFaceSlotAt(raycaster.ray, faceSlots);
    if (slot) {
      const activeDevice = slot.kind === 'occupied' || slot.kind === 'cross-face' ? slot.device : undefined;
      return { slot, device: activeDevice };
    }
    const hit = raycaster.intersectObjects(model.parts, false)[0];
    const device = hit?.object.userData.device;
    return device ? { device } : undefined;
  }

  function clearHover() {
    if (!hovered) return false;
    hovered = undefined;
    tooltip.hidden = true;
    canvas.classList.remove('rack-spatial-hit');
    delete canvas.dataset.slotFace;
    delete canvas.dataset.slotU;
    delete canvas.dataset.slotState;
    canvas.dataset.pickable = 'false';
    slotHover.visible = false;
    model.highlight(selectedDeviceId ?? focusedDeviceId ?? null);
    return true;
  }

  function showHover(hit, event) {
    const { device, slot } = hit;
    if (hovered?.device !== device || hovered?.slot !== slot) {
      clearHover();
      hovered = hit;
      if (slot) {
        canvas.dataset.slotFace = slot.face;
        canvas.dataset.slotU = slot.u_start;
        canvas.dataset.slotState = slot.kind;
      }
      const canAdd = Boolean(onEmpty && isSelectableRackSlot(slot));
      tooltipStatus.hidden = !device;
      if (device) {
        tooltipName.textContent = device.name;
        const cross = slot?.kind === 'cross-face' ? `${FACE_LABELS[slot.face]} U${slot.u_start} 跨面占用 · ` : '';
        tooltipPosition.textContent = `${cross}${FACE_LABELS[device.face]} ${units(device)} · ${device.u_height}U · ${depthLabel(device)}`;
        tooltipStatus.dataset.operatingStatus = operatingStatus(device);
        tooltipStatus.textContent = operatingStatusLabel(device);
      } else {
        tooltipName.textContent = `${FACE_LABELS[slot.face]} U${slot.u_start} · ${SLOT_MARKS[slot.kind]?.label ?? '空位'}`;
        tooltipPosition.textContent = slot.kind === 'unknown' ? `待核实对面设备「${slot.device.name}」的深度` : canAdd ? '选择此 U 位新增设备' : '';
      }
      tooltip.hidden = false;
      const pickable = Boolean(device || canAdd);
      canvas.classList.toggle('rack-spatial-hit', pickable);
      canvas.dataset.pickable = String(pickable);
      model.highlight(selectedDeviceId ?? focusedDeviceId ?? device?.id ?? null);
      if (canAdd) {
        const sign = slot.face === 'front' ? 1 : -1;
        slotHover.position.set(0, (slot.u_start - 0.5) * RACK_UNIT, sign * (DETAIL_Z + 0.008));
        slotHover.rotation.y = sign > 0 ? 0 : Math.PI;
        slotHover.visible = true;
      }
      invalidate();
    }
    const bounds = canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    const width = tooltip.offsetWidth;
    const height = tooltip.offsetHeight;
    const left = x + width + 24 > bounds.width ? x - width - 14 : x + 14;
    const top = y - height - 14 < 10 ? y + 14 : y - height - 14;
    tooltip.style.left = `${Math.max(10, Math.min(bounds.width - width - 10, left))}px`;
    tooltip.style.top = `${Math.max(10, Math.min(bounds.height - height - 10, top))}px`;
  }
}
