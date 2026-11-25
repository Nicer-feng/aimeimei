import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { animateOperatingLamps, buildRackModel } from './rack-3d-model.js?v=operating-status';
import { operatingStatusLabel } from './rack.js?v=operating-status';

const UNIT = 0.12;
const CAMERA_VIEWS = [
  { label: '斜视', direction: [0.65, 0.29, 1] },
  { label: '看正面', direction: [0, 0.035, 1] },
  { label: '看背面', direction: [0, 0.035, -1] },
];

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

export function mountRackScene(host, { rack, devices, onDevice, deviceKind, units, depthLabel, onContextLost, initialCamera }) {
  const initialView = initialCamera ?? { direction: CAMERA_VIEWS[0].direction, zoom: 1, activeView: 0 };
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
  viewport.append(canvas, tooltip);
  panel.append(viewport);

  const toolbar = document.createElement('div');
  toolbar.className = 'rack-spatial-toolbar';
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
      frameView(new THREE.Vector3(...direction).normalize());
    });
    rotation.append(button);
    return button;
  });
  const hover = document.createElement('span');
  hover.className = 'rack-spatial-hover';
  const hint = '拖动旋转，滚动缩放';
  hover.textContent = hint;
  toolbar.append(rotation, hover);
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
  const model = buildRackModel(scene, { rack, devices, deviceKind, unit: UNIT });
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
  controls.enablePan = false;
  controls.minDistance = 1.32;
  controls.minPolarAngle = 0.35;
  controls.maxPolarAngle = 1.78;
  controls.addEventListener('change', () => {
    if (applyingView) return;
    setActiveView(-1);
    clearHover();
    draw();
  });
  const observer = new ResizeObserver(resize);
  observer.observe(viewport);
  const lampAnimation = animateOperatingLamps(viewport, model.lamps, draw);
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

  function dispose() {
    observer.disconnect();
    lampAnimation?.dispose();
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
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
    const offset = camera.position.clone().sub(center);
    const distance = offset.length();
    const direction = offset.normalize();
    return { direction: direction.toArray(), zoom: distance / fittedDistance(direction), activeView };
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

  function frameView(direction, zoom = 1) {
    clearHover();
    const distance = fittedDistance(direction);
    controls.maxDistance = distance * 2.8;
    controls.target.copy(center);
    camera.position.copy(center).addScaledVector(direction, distance * zoom);
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
    const { direction, zoom } = snapshot() ?? initialView;
    renderer.setSize(width, viewportHeight, false);
    camera.aspect = width / viewportHeight;
    camera.updateProjectionMatrix();
    sized = true;
    frameView(new THREE.Vector3(...direction).normalize(), zoom);
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
    model.highlight(null);
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
