import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const UNIT = 0.12;
const COLORS = { network: 0x36736d, power: 0x806429, storage: 0x60598b, server: 0x3a627e };

export function mountRackScene(host, { rack, devices, onDevice, deviceKind, units, depthLabel, onContextLost }) {
  const panel = document.createElement('div');
  panel.className = 'rack-spatial-panel';
  const viewport = document.createElement('div');
  viewport.className = 'rack-spatial-viewport';
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.domElement.setAttribute('aria-label', `${rack.name} 三维机柜`);
  renderer.domElement.setAttribute('role', 'img');
  viewport.append(renderer.domElement);
  panel.append(viewport);

  const toolbar = document.createElement('div');
  toolbar.className = 'rack-spatial-toolbar';
  const rotation = document.createElement('div');
  rotation.className = 'rack-camera-controls';
  rotation.setAttribute('aria-label', '相机方向');
  nextCameraButton('斜视', 0.7, 1);
  nextCameraButton('看正面', 0, 1);
  nextCameraButton('看背面', 0, -1);
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
    button.textContent = `${device.face === 'front' ? '正面' : '背面'} ${units(device)} · ${device.name} · ${depthLabel(device)}`;
    button.addEventListener('click', () => onDevice(device));
    shortcuts.append(button);
  }
  if (devices.length) panel.append(shortcuts);
  host.replaceChildren(panel);

  const height = rack.height * UNIT;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe9eef0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x627682, 2.4));
  const light = new THREE.DirectionalLight(0xffffff, 2.0);
  light.position.set(4, 7, 5);
  scene.add(light);

  const frameMaterial = new THREE.MeshStandardMaterial({ color: 0x405968, roughness: 0.72 });
  const slotMaterial = new THREE.MeshStandardMaterial({ color: 0x9eafba, roughness: 0.9 });
  const darkMaterial = new THREE.MeshStandardMaterial({ color: 0x24333e, roughness: 0.85 });
  const labels = new THREE.MeshBasicMaterial({ color: 0xc7dade });
  const materials = Object.fromEntries(Object.entries(COLORS).map(([kind, color]) => (
    [kind, new THREE.MeshStandardMaterial({ color, roughness: 0.72 })]
  )));
  const parts = [];
  for (const side of [-1, 1]) {
    for (const face of [-1, 1]) {
      box([0.095, height + 0.13, 0.095], [side * 0.90, height / 2, face * 0.56], frameMaterial);
      for (let unit = 1; unit <= rack.height; unit += 1) {
        box([0.062, 0.012, 0.102], [side * 0.84, (unit - 0.5) * UNIT, face * 0.56], slotMaterial);
      }
    }
  }
  box([1.96, 0.085, 1.27], [0, height + 0.07, 0], frameMaterial);
  box([1.96, 0.085, 1.27], [0, -0.07, 0], frameMaterial);
  box([200, 0.1, 200], [0, -0.20, 0], new THREE.MeshStandardMaterial({ color: 0xe5ebee }));

  for (const device of devices) {
    const face = device.face === 'front' ? 1 : -1;
    const center = (device.u_start - 1 + device.u_height / 2) * UNIT;
    const size = device.u_height * UNIT - 0.006;
    const material = materials[deviceKind(device)];
    const full = device.mount_depth === 'full';
    const chassis = box([1.67, size, full ? 1.11 : 0.53], [0, center, full ? 0 : 0.29 * face], material);
    chassis.userData.device = device;
    const bezel = box([1.74, size, 0.045], [0, center, 0.57 * face], material);
    bezel.userData.device = device;
    parts.push(chassis, bezel);
    box([0.46, Math.min(0.045, size * 0.52), 0.012], [-0.31, center, face * 0.599], darkMaterial);
    for (let index = 0; index < 3; index += 1) {
      box([0.06, 0.012, 0.013], [0.35 + 0.10 * index, center, face * 0.599], labels);
    }
  }

  const camera = new THREE.PerspectiveCamera(38, 1, 0.06, 300);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = false;
  controls.minDistance = 1.4;
  controls.maxDistance = Math.max(height * 4.0, 12);
  controls.minPolarAngle = 0.35;
  controls.maxPolarAngle = 1.83;
  controls.addEventListener('change', draw);
  setCamera(0.7, 1);

  const observer = new ResizeObserver(resize);
  observer.observe(viewport);
  resize();

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let down;
  const canvas = renderer.domElement;
  canvas.addEventListener('pointerdown', (event) => { down = [event.clientX, event.clientY]; });
  canvas.addEventListener('pointercancel', () => { down = undefined; });
  canvas.addEventListener('pointermove', (event) => {
    const hit = pick(event);
    hover.textContent = hit ? `${hit.name} · ${units(hit)} · ${hit.u_height}U · ${depthLabel(hit)}` : hint;
    canvas.classList.toggle('rack-spatial-hit', Boolean(hit));
  });
  canvas.addEventListener('pointerleave', () => {
    hover.textContent = hint;
    canvas.classList.remove('rack-spatial-hit');
  });
  canvas.addEventListener('pointerup', (event) => {
    const isClick = down && Math.hypot(event.clientX - down[0], event.clientY - down[1]) <= 5;
    down = undefined;
    if (!isClick) return;
    const hit = pick(event);
    if (hit) onDevice(hit);
  });
  const contextLost = (event) => {
    event.preventDefault();
    onContextLost();
  };
  canvas.addEventListener('webglcontextlost', contextLost);

  return () => {
    observer.disconnect();
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
    for (const mesh of scene.children) {
      if (mesh.isMesh) mesh.geometry.dispose();
    }
    const usedMaterials = new Set(scene.children.filter((object) => object.isMesh).map((mesh) => mesh.material));
    for (const material of usedMaterials) material.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  };

  function box(dimensions, position, material) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...dimensions), material);
    mesh.position.set(...position);
    scene.add(mesh);
    return mesh;
  }

  function nextCameraButton(label, side, face) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', () => setCamera(side, face));
    rotation.append(button);
  }

  function setCamera(side, face) {
    const distance = Math.max(height * 1.75, 4.4);
    controls.target.set(0, height / 2, 0);
    camera.position.set(side * distance * 0.57, height / 2 + distance * (side ? 0.23 : 0.015), distance * face);
    controls.update();
    draw();
  }

  function draw() {
    renderer.render(scene, camera);
  }

  function resize() {
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    draw();
  }

  function pick(event) {
    const bounds = canvas.getBoundingClientRect();
    pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(parts, false)[0];
    return hit?.object.userData.device;
  }
}
