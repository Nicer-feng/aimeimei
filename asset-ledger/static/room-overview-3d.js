import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const COLUMN_GAP = 1.21;
const ROW_GAP = 2.30;
const CABINET_WIDTH = 1.06;
const CABINET_DEPTH = 1.10;
const ANGLED = [.42, 2.30, 1.12];
const TOP = [0, 1, .001];
const CABINET_COLOR = 0x29353d;
const FOCUS_COLOR = 0x3c7067;

function node(tag, className, label) {
  const element = document.createElement(tag);
  element.className = className;
  if (label) element.textContent = label;
  return element;
}

function makeRoom(scene, { room, racks }) {
  const racksById = new Map(racks.map((rack) => [String(rack.id), rack]));
  const placements = new Map(room.positions.map((entry) => [`${entry.row}/${entry.slot}`, entry]));
  const width = room.columns * COLUMN_GAP + .68;
  const depth = (room.rows - 1) * ROW_GAP + 2.26;
  const graphite = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: .68, metalness: .18 });
  const finishes = new Map();
  const boxes = new Map();
  const symbols = [];
  const targets = [];
  const cabinetSlots = new Map();
  const bounds = new THREE.Box3(
    new THREE.Vector3(-width / 2, -.16, -depth / 2), new THREE.Vector3(width / 2, 0, depth / 2),
  );
  const block = new THREE.BoxGeometry(1, 1, 1);
  const pickMaterial = new THREE.MeshBasicMaterial();
  const transform = new THREE.Matrix4();
  const location = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const level = new THREE.Quaternion();
  const angle = new THREE.Quaternion();
  const yAxis = new THREE.Vector3(0, 1, 0);

  function finish(color) {
    if (!finishes.has(color)) {
      finishes.set(color, new THREE.MeshStandardMaterial({ color, roughness: .83, metalness: .07 }));
    }
    return finishes.get(color);
  }

  function box(material, position, size, rotation = level) {
    if (!boxes.has(material)) boxes.set(material, []);
    const batch = boxes.get(material);
    transform.compose(position, rotation, scale.fromArray(size));
    batch.push(transform.clone());
    return batch.length - 1;
  }

  function flat(color, x, y, z, size) {
    box(finish(color), location.set(x, y, z), size);
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
      const h = Math.max(.60, rack.height * .058);
      const origin = new THREE.Vector3(x, 0, z);
      const rotation = THREE.MathUtils.degToRad(Number(entry.rotation) || 0);
      angle.setFromAxisAngle(yAxis, rotation);
      const cabinetBox = (material, px, py, pz, size) => box(
        material, location.set(px, py, pz).applyQuaternion(angle).add(origin), size, angle,
      );
      cabinetSlots.set(id, cabinetBox(graphite, 0, h * .50 + .04, 0, [.986, h, 1.018]));
      cabinetBox(finish(0x46555d), 0, h + .048, 0, [CABINET_WIDTH, .072, CABINET_DEPTH]);
      cabinetBox(finish(0x46555d), 0, .043, 0, [CABINET_WIDTH, .058, CABINET_DEPTH]);
      cabinetBox(finish(0x1d2930), 0, h * .50 + .04, .523, [.889, h - .085, .041]);
      cabinetBox(finish(0x1d2930), 0, h * .50 + .04, -.523, [.89, h - .085, .041]);
      for (const side of [-1, 1]) {
        for (const face of [-1, 1]) {
          cabinetBox(finish(0x46555d), side * .506, h * .50 + .04, face * .52, [.043, h + .011, .053]);
        }
      }
      cabinetBox(finish(0x608c80), -.325, h - .080, .550, [.142, .045, .014]);
      cabinetBox(finish(0x53666b), 0, h * .64 + .035, .550, [.665, .024, .014]);
      cabinetBox(finish(0x53666b), 0, h * .32 + .035, .550, [.665, .024, .014]);
      cabinetBox(finish(0x53666b), -.328, h * .51 + .038, -.548, [.033, h * .16, .012]);
      bounds.max.y = Math.max(bounds.max.y, h + .24);

      const target = new THREE.Mesh(block, pickMaterial);
      target.position.set(x, h / 2 + .04, z);
      target.scale.set(CABINET_WIDTH, h + .08, CABINET_DEPTH);
      target.quaternion.copy(angle);
      target.visible = false;
      target.userData.rack = rack;
      scene.add(target);
      targets.push(target);
      symbols.push({ row, slot, rack, point: new THREE.Vector3(x, h + .114, z) });
    }
  }

  let cabinetBatch;
  for (const [material, matrices] of boxes) {
    const mesh = new THREE.InstancedMesh(block, material, matrices.length);
    const cabinet = material === graphite;
    const color = new THREE.Color(CABINET_COLOR);
    matrices.forEach((matrix, index) => {
      mesh.setMatrixAt(index, matrix);
      if (cabinet) mesh.setColorAt(index, color);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (cabinet) cabinetBatch = mesh;
    scene.add(mesh);
  }
  if (!cabinetBatch) graphite.dispose();
  if (!targets.length) pickMaterial.dispose();

  const tone = new THREE.Color();
  function tint(id, hovered) {
    const index = cabinetSlots.get(id);
    if (!cabinetBatch || index == null) return;
    cabinetBatch.setColorAt(index, tone.setHex(hovered ? FOCUS_COLOR : CABINET_COLOR));
    cabinetBatch.instanceColor.needsUpdate = true;
  }
  return { bounds, symbols, targets, tint };
}

export function mountRoomScene(host, { layout, racks, initialCamera, onRack, onFallback }) {
  const panel = node('section', 'room-3d');
  panel.setAttribute('aria-label', '机房三维总览');
  const viewport = node('div', 'room-3d-viewport');
  const labels = node('div', 'room-3d-labels');
  labels.setAttribute('aria-label', '机柜及预留位');
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
  viewport.append(canvas, labels);
  panel.append(viewport, toolbar);
  host.replaceChildren(panel);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeff4f4);
  scene.add(new THREE.HemisphereLight(0xf8fcff, 0x748282, 2.1));
  const key = new THREE.DirectionalLight(0xfff2de, 2.4);
  key.position.set(-5, 12, 9);
  const rim = new THREE.DirectionalLight(0xc8e3f4, 1.30);
  rim.position.set(8, 6, -9);
  scene.add(key, rim);
  const model = makeRoom(scene, { room: layout, racks });
  const center = model.bounds.getCenter(new THREE.Vector3());
  const corners = [];
  for (const x of [model.bounds.min.x, model.bounds.max.x]) {
    for (const y of [model.bounds.min.y, model.bounds.max.y]) {
      for (const z of [model.bounds.min.z, model.bounds.max.z]) corners.push(new THREE.Vector3(x, y, z).sub(center));
    }
  }

  const camera = new THREE.PerspectiveCamera(35, 1, .04, 400);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false;
  controls.minPolarAngle = .001;
  controls.maxPolarAngle = Math.PI / 2 - .12;
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const projected = new THREE.Vector3();
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
    zoom: Number.isFinite(initialCamera?.zoom) ? THREE.MathUtils.clamp(initialCamera.zoom, .4, 3) : 1,
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
      item.addEventListener('click', () => onRack(rack));
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
    invalidate();
  });
  canvas.addEventListener('pointerdown', (event) => {
    if (event.button === 0 && event.isPrimary) pressed = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    else if (pressed && event.pointerType === 'touch') pressed.moved = true;
  });
  canvas.addEventListener('pointermove', (event) => {
    if (pressed) {
      pressed.moved ||= Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 5;
    } else if (event.pointerType !== 'touch') {
      setHover(pick(event));
    }
  });
  canvas.addEventListener('pointerup', (event) => {
    const clicked = pressed?.id === event.pointerId && !pressed.moved &&
      Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) <= 5;
    pressed = undefined;
    if (clicked) {
      const rack = pick(event);
      if (rack) onRack(rack);
    }
  });
  canvas.addEventListener('pointercancel', () => { pressed = undefined; });
  canvas.addEventListener('pointerleave', () => setHover(null));
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
    controls.minDistance = Math.max(1, fit * .4);
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
    renderer.render(scene, camera);
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
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
    return ray.intersectObjects(model.targets, false)[0]?.object.userData.rack ?? null;
  }

  function setHover(rack) {
    const id = rack ? String(rack.id) : undefined;
    if (hovered === id) return;
    model.tint(hovered, false);
    model.tint(id, true);
    hovered = id;
    canvas.dataset.pickable = String(Boolean(id));
    if (id) canvas.dataset.hoveredRackId = id;
    else delete canvas.dataset.hoveredRackId;
    invalidate();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    observer.disconnect();
    if (frame != null) cancelAnimationFrame(frame);
    canvas.removeEventListener('webglcontextlost', contextLost);
    controls.dispose();
    const geometries = new Set();
    const materials = new Set();
    for (const object of scene.children) {
      if (!object.isMesh) continue;
      geometries.add(object.geometry);
      materials.add(object.material);
      if (object.isInstancedMesh) object.dispose();
    }
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    panel.remove();
  }

  return Object.assign(dispose, { snapshot });
}
