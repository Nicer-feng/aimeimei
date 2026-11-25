import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { RACK_UNIT } from './rack-geometry.js';
import { animateOperatingLamps, buildRackModel } from './rack-3d-model.js';
import { operatingStatusLabel } from './rack.js?v=operating-status';

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
    ['#e5a131', '深度待核'],
  ],
};

function addContactShadow(scene, bounds) {
  const stamp = document.createElement('canvas');
  stamp.width = stamp.height = 128;
  const context = stamp.getContext('2d');
  if (!context) return;
  const fade = context.createRadialGradient(64, 64, 2, 64, 64, 64);
  fade.addColorStop(0, '#283e4a51');
  fade.addColorStop(0.52, '#283e4a35');
  fade.addColorStop(0.79, '#283e4a16');
  fade.addColorStop(1, '#283e4a00');
  context.fillStyle = fade;
  context.fillRect(0, 0, 128, 128);

  const map = new THREE.CanvasTexture(stamp);
  map.colorSpace = THREE.SRGBColorSpace;
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
  rack, devices, onDevice, deviceKind, units, depthLabel, onContextLost, initialCamera, initialDeviceId,
}) {
  const initialView = initialCamera ?? { direction: CAMERA_VIEWS[0].direction, zoom: 1, activeView: 0, viewMode: 'appearance' };
  let viewMode = RACK_MODES.some((m) => m.id === initialView.viewMode) ? initialView.viewMode : 'appearance';

  const panel = document.createElement('div');
  panel.className = 'rack-spatial-panel';
  const viewport = document.createElement('div');
  viewport.className = 'rack-spatial-viewport';
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.16;
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-label', `${rack.name} 三维机柜`);
  canvas.setAttribute('role', 'img');
  const tooltip = document.createElement('div');
  tooltip.className = 'rack-spatial-tooltip';
  tooltip.hidden = true;
  tooltip.setAttribute('aria-hidden', 'true');
  const tooltipName = document.createElement('strong');
  const tooltipPosition = document.createElement('span');
  tooltip.append(tooltipName, tooltipPosition);
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
  rotation.setAttribute('aria-label', '相机方向');
  const viewButtons = CAMERA_VIEWS.map(({ label, direction }, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.setAttribute('aria-pressed', String(index === initialView.activeView));
    button.addEventListener('click', () => {
      setActiveView(index);
      frameView(new THREE.Vector3(...direction).normalize(), 1, center);
    });
    rotation.append(button);
    return button;
  });

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
      draw();
    });
    modeGroup.append(button);
    modeButtons.set(id, button);
  }
  toolbarGroups.append(rotation, modeGroup);

  const hover = document.createElement('span');
  hover.className = 'rack-spatial-hover';
  const hint = '左键旋转 · 右键平移 · 滚轮缩放';
  hover.textContent = hint;
  toolbar.append(toolbarGroups, hover);
  panel.append(toolbar);

  const shortcuts = document.createElement('div');
  shortcuts.className = 'rack-spatial-devices';
  shortcuts.setAttribute('aria-label', '机柜设备');
  for (const device of devices) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.deviceId = device.id;
    button.textContent = `${device.face === 'front' ? '正面' : '背面'} ${units(device)} · ${device.name} · ${depthLabel(device)} · ${operatingStatusLabel(device)}`;
    button.addEventListener('click', () => onDevice(device));
    shortcuts.append(button);
  }
  if (devices.length) panel.append(shortcuts);
  host.replaceChildren(panel);

  const scene = new THREE.Scene();
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

  const camera = new THREE.PerspectiveCamera(36, 1, 0.04, 120);
  const controls = new OrbitControls(camera, renderer.domElement);
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let down;
  let hovered;
  let activeView = initialView.activeView;
  let applyingView = false;
  let sized = false;
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.minDistance = 0.90;
  controls.minPolarAngle = 0.25;
  controls.maxPolarAngle = 1.82;
  controls.addEventListener('change', () => {
    if (applyingView) return;
    clampTarget();
    setActiveView(-1);
    clearHover();
    draw();
  });

  const observer = new ResizeObserver(resize);
  observer.observe(viewport);
  const lampAnimation = animateOperatingLamps(viewport, model.lamps, draw);
  applyViewMode(viewMode);
  if (initialDeviceId != null) model.highlight(initialDeviceId);
  resize();

  canvas.addEventListener('pointerdown', (event) => {
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
    const device = pick(event);
    if (device) showHover(device, event);
    else if (clearHover()) draw();
  });
  canvas.addEventListener('pointerleave', () => { if (clearHover()) draw(); });
  canvas.addEventListener('pointerup', (event) => {
    const isClick = down?.pointerId === event.pointerId && !down.moved &&
      Math.hypot(event.clientX - down.x, event.clientY - down.y) <= 5;
    down = undefined;
    if (!isClick) return;
    const device = pick(event);
    if (clearHover()) draw();
    if (device) onDevice(device);
  });
  const contextLost = (event) => {
    event.preventDefault();
    onContextLost();
  };
  canvas.addEventListener('webglcontextlost', contextLost);

  return Object.assign(dispose, { snapshot });

  function clampTarget() {
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -1.0, 1.0);
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, -0.8, 0.8);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, bounds.min.y, bounds.max.y);
  }

  function applyViewMode(mode) {
    viewMode = mode;
    for (const [id, button] of modeButtons) {
      button.setAttribute('aria-pressed', String(id === mode));
    }
    model.setMode(mode);
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
    observer.disconnect();
    lampAnimation?.dispose();
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
    const vertical = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.82;
    const horizontal = vertical * camera.aspect;
    // 按当前相机方向投影柜体的八个角，兼顾纵向高柜和窄屏横向空间。
    return Math.max(...corners.map((corner) => corner.dot(direction) + Math.max(
      Math.abs(corner.dot(right)) / horizontal,
      Math.abs(corner.dot(up)) / vertical,
    )));
  }

  function frameView(direction, zoom = 1, target = center) {
    clearHover();
    const distance = fittedDistance(direction);
    controls.maxDistance = distance * 2.8;
    controls.target.copy(target);
    clampTarget();
    camera.position.copy(controls.target).addScaledVector(direction, distance * zoom);
    applyingView = true;
    controls.update();
    applyingView = false;
    draw();
  }

  function draw() {
    renderer.render(scene, camera);
  }

  function resize() {
    const width = viewport.clientWidth;
    const viewportHeight = viewport.clientHeight;
    if (!width || !viewportHeight) return;
    const current = snapshot() ?? initialView;
    renderer.setSize(width, viewportHeight, false);
    camera.aspect = width / viewportHeight;
    camera.updateProjectionMatrix();
    sized = true;
    const targetVec = Array.isArray(current.target) && current.target.length === 3
      ? new THREE.Vector3(...current.target) : center;
    frameView(new THREE.Vector3(...current.direction).normalize(), current.zoom, targetVec);
  }

  function pick(event) {
    const bounds = canvas.getBoundingClientRect();
    pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(model.parts, false)[0];
    return hit?.object.userData.device;
  }

  function clearHover() {
    if (!hovered) return false;
    hovered = undefined;
    tooltip.hidden = true;
    hover.textContent = hint;
    canvas.classList.remove('rack-spatial-hit');
    model.highlight(initialDeviceId ?? null);
    return true;
  }

  function showHover(device, event) {
    if (hovered !== device) {
      hovered = device;
      const face = device.face === 'front' ? '正面' : '背面';
      tooltipName.textContent = device.name;
      tooltipPosition.textContent = `${face} ${units(device)} · ${device.u_height}U · ${depthLabel(device)} · ${operatingStatusLabel(device)}`;
      hover.textContent = `${device.name} · ${tooltipPosition.textContent}`;
      tooltip.hidden = false;
      canvas.classList.add('rack-spatial-hit');
      model.highlight(device.id);
      draw();
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
