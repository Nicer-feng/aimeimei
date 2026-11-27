import * as THREE from './vendor/three/three.module.min.js';
import {
  DEPTH_COLORS, DETAIL_Z, DEVICE_HALF_WIDTH, OPERATING_LAMP_X, OPERATING_LAMP_Z, PANEL_COLORS, PANEL_Z,
  RACK_DEPTH, RACK_WIDTH, STATUS_COLORS, SURFACES, TYPE_ACCENTS,
  deviceMetrics, normalizeDepth, normalizeStatus, rackSummaryColor,
} from './rack-geometry.js';
import { createCabinetMeshTexture, createDeviceLabelTexture, createOperatingLampTexture, createRackScaleTexture } from './rack-textures.js';

const LAMP_PERIOD_MS = 3200;
const LAMP_FRAME_MS = 80;
const SEARCH_DIM = 0.27;

function canvasRect(canvas) {
  const rect = canvas.getBoundingClientRect();
  if (![rect.left, rect.top, rect.width, rect.height].every(Number.isFinite) ||
      rect.width <= 0 || rect.height <= 0) return null;
  return rect;
}

function projectX(rect, x) {
  return rect.left + (x + 1) * rect.width / 2;
}

function projectY(rect, y) {
  return rect.top + (1 - y) * rect.height / 2;
}

export function projectScenePoint(camera, canvas, point) {
  const rect = canvasRect(canvas);
  if (!rect) return null;
  camera.updateWorldMatrix(true, false);
  const view = point.clone().applyMatrix4(camera.matrixWorldInverse);
  if (view.z > -camera.near || view.z < -camera.far) return null;
  view.applyMatrix4(camera.projectionMatrix);
  if (![view.x, view.y].every(Number.isFinite) || Math.abs(view.x) > 1 || Math.abs(view.y) > 1) return null;
  return { x: projectX(rect, view.x), y: projectY(rect, view.y) };
}

export function projectCabinetRect(camera, canvas, bounds, matrixWorld) {
  const rect = canvasRect(canvas);
  if (!rect || bounds.isEmpty()) return null;
  camera.updateWorldMatrix(true, false);
  const transform = camera.matrixWorldInverse.clone();
  if (matrixWorld) transform.multiply(matrixWorld);
  const corners = Array.from({ length: 8 }, (_, index) => new THREE.Vector3(
    index & 1 ? bounds.max.x : bounds.min.x,
    index & 2 ? bounds.max.y : bounds.min.y,
    index & 4 ? bounds.max.z : bounds.min.z,
  ).applyMatrix4(transform));
  if (corners.some((point) => ![point.x, point.y, point.z].every(Number.isFinite))) return null;

  const near = -camera.near;
  const far = -camera.far;
  const visible = corners.filter((point) => point.z <= near && point.z >= far);
  // 剪裁包围盒棱线，避免靠近机柜时，镜头后方的顶点把投影范围翻转。
  for (const plane of [near, far]) {
    if (!Number.isFinite(plane)) continue;
    for (let index = 0; index < corners.length; index += 1) {
      for (const axis of [1, 2, 4]) {
        if (index & axis) continue;
        const start = corners[index];
        const end = corners[index | axis];
        if ((start.z - plane) * (end.z - plane) < 0) {
          visible.push(start.clone().lerp(end, (plane - start.z) / (end.z - start.z)));
        }
      }
    }
  }

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const point of visible) {
    const projected = point.clone().applyMatrix4(camera.projectionMatrix);
    if (![projected.x, projected.y].every(Number.isFinite)) continue;
    minX = Math.min(minX, projected.x);
    minY = Math.min(minY, projected.y);
    maxX = Math.max(maxX, projected.x);
    maxY = Math.max(maxY, projected.y);
  }
  minX = Math.max(-1, minX);
  minY = Math.max(-1, minY);
  maxX = Math.min(1, maxX);
  maxY = Math.min(1, maxY);
  if (minX >= maxX || minY >= maxY) return null;
  const left = projectX(rect, minX);
  const right = projectX(rect, maxX);
  const top = projectY(rect, maxY);
  const bottom = projectY(rect, minY);
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

function material(color, roughness, metalness) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness });
}

function panelColor(kind) {
  return PANEL_COLORS[kind] ?? PANEL_COLORS.generic;
}

function beveledBox(width, height, depth, edge) {
  const w = width / 2 - edge;
  const h = height / 2 - edge;
  const span = depth - 2 * edge;
  const face = new THREE.Shape();
  face.moveTo(-w, -h);
  face.lineTo(w, -h);
  face.lineTo(w, h);
  face.lineTo(-w, h);
  face.closePath();
  const geometry = new THREE.ExtrudeGeometry(face, {
    depth: span, steps: 1, bevelEnabled: true,
    bevelThickness: edge, bevelSize: edge, bevelSegments: 1,
  });
  geometry.translate(0, 0, -span / 2);
  return geometry;
}

const accent = (kind) => `accent/${kind}`;

export function createRackPalette() {
  const materials = new Map();
  const scaleMaterials = new Map();
  const textures = [];
  let perforatedMaterial;

  function materialFor(surface) {
    if (!materials.has(surface)) {
      if (SURFACES[surface]) {
        materials.set(surface, material(...SURFACES[surface]));
      } else if (surface.startsWith('panel/')) {
        materials.set(surface, material(panelColor(surface.slice('panel/'.length)), SURFACES.panel[1], SURFACES.panel[2]));
      } else {
        const color = TYPE_ACCENTS[surface.slice('accent/'.length)] ?? TYPE_ACCENTS.generic;
        materials.set(surface, material(color, 0.72, 0.10));
      }
    }
    return materials.get(surface);
  }

  function cabinetMeshMaterial() {
    if (!perforatedMaterial) {
      const map = createCabinetMeshTexture();
      if (map) textures.push(map);
      perforatedMaterial = new THREE.MeshStandardMaterial({
        color: 0x303a42, roughness: 0.66, metalness: 0.26, map,
      });
      materials.set('cabinet-mesh', perforatedMaterial);
    }
    return perforatedMaterial;
  }

  function scaleMaterial(rackHeight) {
    if (!scaleMaterials.has(rackHeight)) {
      const texture = createRackScaleTexture(rackHeight);
      if (!texture) return null;
      textures.push(texture);
      scaleMaterials.set(rackHeight, new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: -1,
      }));
    }
    return scaleMaterials.get(rackHeight);
  }

  function dispose() {
    for (const mat of materials.values()) mat.dispose();
    for (const mat of scaleMaterials.values()) mat.dispose();
    for (const tex of textures) tex.dispose();
    materials.clear();
    scaleMaterials.clear();
    textures.length = 0;
  }

  return Object.assign(materialFor, { scaleMaterial, cabinetMeshMaterial, dispose });
}

function matchesRoomSearch(filter, { rackId, deviceId }) {
  return !filter || filter.directRackIds.has(rackId) ||
    (filter.rackIds.has(rackId) && (!deviceId || filter.deviceIds.has(deviceId)));
}

function roomSearchOwners(rack) {
  const rackId = String(rack.id);
  const cabinet = { rackId };
  const devices = new Map();
  return (device) => {
    if (!device) return cabinet;
    const id = String(device.id);
    if (!devices.has(id)) devices.set(id, { rackId, deviceId: id });
    return devices.get(id);
  };
}

function roomSearchTint() {
  const normal = new THREE.Color(1, 1, 1);
  const subdued = new THREE.Color(SEARCH_DIM, SEARCH_DIM, SEARCH_DIM);
  const tracked = [];

  function add(mesh, owners) {
    // 实例乘色独立于共享材质；搜索清除后各实例恢复原色。
    mesh.setColorAt(0, normal);
    mesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
    tracked.push({ mesh, owners, muted: new Uint8Array(owners.length) });
  }

  function setSearchFilter(filter) {
    for (const { mesh, owners, muted } of tracked) {
      let changed = false;
      owners.forEach((owner, index) => {
        const dim = matchesRoomSearch(filter, owner) ? 0 : 1;
        if (muted[index] === dim) return;
        muted[index] = dim;
        mesh.setColorAt(index, dim ? subdued : normal);
        changed = true;
      });
      if (changed) mesh.instanceColor.needsUpdate = true;
    }
  }

  return { add, setSearchFilter };
}

function instancedBoxes(parent, materialFor, tint) {
  const buckets = new Map();
  const matrix = new THREE.Matrix4();
  const position = new THREE.Vector3();
  const rotation = new THREE.Quaternion();
  const scale = new THREE.Vector3();

  function add(surface, size, center, world, owner) {
    if (!buckets.has(surface)) buckets.set(surface, { matrices: [], owners: [] });
    const bucket = buckets.get(surface);
    matrix.compose(position.fromArray(center), rotation, scale.fromArray(size));
    if (world) matrix.premultiply(world);
    bucket.matrices.push(matrix.clone());
    if (tint) bucket.owners.push(owner);
  }

  function finish() {
    if (!buckets.size) return [];
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const meshes = [];
    for (const [surface, { matrices, owners }] of buckets) {
      const mesh = new THREE.InstancedMesh(geometry, materialFor(surface), matrices.length);
      matrices.forEach((transform, index) => mesh.setMatrixAt(index, transform));
      mesh.instanceMatrix.needsUpdate = true;
      tint?.add(mesh, owners);
      parent.add(mesh);
      meshes.push(mesh);
    }
    buckets.clear();
    return meshes;
  }

  return { add, finish };
}

function addScaleStrips(parent, rackHeight, unit, scaleMat, tint, owner) {
  if (!scaleMat) return;
  const stripHeight = rackHeight * unit;
  const geometry = new THREE.PlaneGeometry(0.088, stripHeight);
  const centerY = stripHeight / 2;
  const batch = tint && new THREE.InstancedMesh(geometry, scaleMat, 4);
  const pose = batch && new THREE.Object3D();
  let index = 0;
  for (const face of [-1, 1]) {
    for (const side of [-1, 1]) {
      const strip = pose || new THREE.Mesh(geometry, scaleMat);
      strip.position.set(side * 0.905, centerY, face * (DETAIL_Z + 0.008));
      strip.rotation.y = face < 0 ? Math.PI : 0;
      if (batch) {
        strip.updateMatrix();
        batch.setMatrixAt(index++, strip.matrix);
      } else {
        parent.add(strip);
      }
    }
  }
  if (batch) {
    batch.instanceMatrix.needsUpdate = true;
    tint.add(batch, Array(4).fill(owner));
    parent.add(batch);
  }
}

function addCabinetEnclosure(parent, { rack, unit, palette, tint, owner }) {
  const height = rack.height * unit;
  const sides = instancedBoxes(parent, palette, tint);
  const sections = 3;
  const sectionHeight = height / sections;
  const panelX = RACK_WIDTH / 2 - 0.023;
  const doorZ = RACK_DEPTH / 2 - 0.035;
  const doorInset = 0.09;
  const doorOpening = RACK_WIDTH - doorInset * 3.4;
  for (const sign of [-1, 1]) {
    for (let index = 0; index < sections; index += 1) {
      const y = sectionHeight * (index + 0.5);
      sides.add('sidePanel', [0.037, sectionHeight - 0.022, RACK_DEPTH - 0.135], [sign * panelX, y, 0], undefined, owner);
      for (const end of [-1, 1]) {
        const z = end * (doorZ - 0.23);
        const latchY = y + sectionHeight * 0.34;
        sides.add('handle', [0.014, 0.102, 0.076], [sign * (panelX + 0.020), latchY, z], undefined, owner);
        sides.add('inset', [0.010, 0.065, 0.045], [sign * (panelX + 0.027), latchY, z], undefined, owner);
      }
    }
  }
  sides.finish();

  const doors = new THREE.Group();
  const frames = instancedBoxes(doors, palette, tint);
  const doorMesh = new THREE.InstancedMesh(
    new THREE.PlaneGeometry(doorOpening + 0.016, height - 0.16), palette.cabinetMeshMaterial(), 2,
  );
  const pose = new THREE.Object3D();
  for (const [index, sign] of [1, -1].entries()) {
    for (const end of [-1, 1]) {
      frames.add('doorFrame', [RACK_WIDTH - 0.10, 0.092, 0.045], [0, end < 0 ? 0.039 : height - 0.039, sign * doorZ], undefined, owner);
      frames.add('doorFrame', [0.108, height, 0.045], [end * (doorOpening / 2 + 0.048), height / 2, sign * doorZ], undefined, owner);
    }
    const pullX = sign * (doorOpening / 2 + 0.021);
    const pullY = height * 0.42;
    const length = Math.min(height * 0.20, 0.81);
    frames.add('inset', [0.072, length + 0.10, 0.022], [pullX, pullY, sign * (doorZ + 0.023)], undefined, owner);
    frames.add('handle', [0.037, length, 0.029], [pullX, pullY + 0.012, sign * (doorZ + 0.041)], undefined, owner);
    pose.position.set(0, height / 2, sign * (doorZ + 0.014));
    pose.rotation.y = sign < 0 ? Math.PI : 0;
    pose.updateMatrix();
    doorMesh.setMatrixAt(index, pose.matrix);
  }
  doorMesh.instanceMatrix.needsUpdate = true;
  tint?.add(doorMesh, [owner, owner]);
  doors.add(doorMesh);
  frames.finish();
  parent.add(doors);
  return doors;
}

function buildLampGlow(core, texture) {
  const geometry = new THREE.PlaneGeometry(0.12, 0.12).translate(0, 0, -0.0015);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    blending: THREE.AdditiveBlending,
    opacity: 0.55,
    depthWrite: false,
    toneMapped: false,
  });
  const glow = new THREE.InstancedMesh(geometry, material, core.count);
  glow.name = 'running-device-glows';
  // 两层共用实例矩阵和颜色，灯效每帧仍只改写同一份实例数据。
  glow.instanceMatrix = core.instanceMatrix;
  glow.instanceColor = core.instanceColor;
  return glow;
}

function buildOperatingLamps(parent, entries, unit) {
  const indicesByRack = new Map();
  const matrices = [];
  const owners = [];
  const world = new THREE.Matrix4();
  const local = new THREE.Matrix4();
  const position = new THREE.Vector3();
  const size = new THREE.Vector3();
  const normalSize = new THREE.Vector3(1, 1, 1);
  const yAxis = new THREE.Vector3(0, 1, 0);
  const rotation = new THREE.Quaternion();
  const front = new THREE.Quaternion();
  const rear = new THREE.Quaternion().setFromAxisAngle(yAxis, Math.PI);

  for (const { rack, devices, x, y, z, rotation: angle, scale } of entries) {
    const running = devices.filter((device) => device.operating_status === 'running');
    if (!running.length) continue;
    world.compose(position.set(x, y, z), rotation.setFromAxisAngle(yAxis, THREE.MathUtils.degToRad(angle)), size.setScalar(scale));
    const ownerFor = roomSearchOwners(rack);
    const indices = [];
    for (const device of running) {
      const onFront = device.face === 'front';
      const height = (device.u_start - 1 + device.u_height / 2) * unit;
      position.set(OPERATING_LAMP_X, height, (onFront ? 1 : -1) * OPERATING_LAMP_Z);
      indices.push(matrices.length);
      matrices.push(local.compose(position, onFront ? front : rear, normalSize).clone().premultiply(world));
      owners.push(ownerFor(device));
    }
    indicesByRack.set(String(rack.id), indices);
  }
  if (!matrices.length) return undefined;

  const steadyColor = new THREE.Color(0x4b7b60);
  const subdued = steadyColor.clone().multiplyScalar(SEARCH_DIM);
  const dimColor = new THREE.Color(0x4a875f);
  const brightColor = new THREE.Color(0x8ce9a9);
  const pulseColor = new THREE.Color();
  const nearScale = new THREE.Vector3(1.30, 1.30, 1);
  const texture = createOperatingLampTexture();
  const geometry = texture ? new THREE.PlaneGeometry(0.054, 0.054) : new THREE.CircleGeometry(0.023, 8);
  const material = new THREE.MeshBasicMaterial({
    map: texture, transparent: Boolean(texture), depthWrite: !texture, toneMapped: false,
  });
  const mesh = new THREE.InstancedMesh(geometry, material, matrices.length);
  mesh.name = 'running-device-lamps';
  mesh.renderOrder = 1;
  matrices.forEach((matrix, index) => {
    mesh.setMatrixAt(index, matrix);
    mesh.setColorAt(index, steadyColor);
  });
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.instanceMatrix.needsUpdate = true;
  mesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
  parent.add(mesh);
  const glow = texture ? buildLampGlow(mesh, texture) : null;
  if (glow) parent.add(glow);

  let animated = [];
  let nearby = [];
  let searchFilter = null;
  function paint(color) {
    if (!animated.length) return;
    for (const index of animated) mesh.setColorAt(index, color);
    mesh.instanceColor.needsUpdate = true;
  }
  function updateAnimated() {
    paint(steadyColor);
    for (const index of animated) mesh.setMatrixAt(index, matrices[index]);
    animated = nearby.filter((index) => matchesRoomSearch(searchFilter, owners[index]));
    for (const index of animated) mesh.setMatrixAt(index, local.copy(matrices[index]).scale(nearScale));
    mesh.instanceMatrix.needsUpdate = true;
  }
  return {
    mesh,
    texture,
    hasNearbyLamps: () => animated.length > 0,
    setVisible(visible) {
      mesh.visible = visible;
      if (glow) glow.visible = visible;
    },
    setNearbyRacks(rackIds) {
      nearby = [];
      for (const id of rackIds) {
        const indices = indicesByRack.get(String(id));
        if (indices) nearby.push(...indices);
      }
      updateAnimated();
    },
    setSearchFilter(filter) {
      searchFilter = filter;
      updateAnimated();
      owners.forEach((owner, index) => mesh.setColorAt(index, matchesRoomSearch(filter, owner) ? steadyColor : subdued));
      mesh.instanceColor.needsUpdate = true;
    },
    steady: () => paint(steadyColor),
    pulse(time) {
      const phase = (time % LAMP_PERIOD_MS) / LAMP_PERIOD_MS;
      const amount = 0.5 - 0.5 * Math.cos(phase * Math.PI * 2);
      paint(pulseColor.lerpColors(dimColor, brightColor, amount));
    },
  };
}

// 灯效只重绘画布，机房的柜号和细节分层仍由相机操作触发。
export function animateOperatingLamps(viewport, lamps, redraw) {
  if (!lamps) return undefined;
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let timer;
  let disposed = false;
  const observer = new IntersectionObserver(sync);
  observer.observe(viewport);
  motion.addEventListener('change', changeMotion);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('scroll', sync, { capture: true, passive: true });
  window.addEventListener('resize', sync);
  sync();

  function isInViewport() {
    const { top, right, bottom, left, width, height } = viewport.getBoundingClientRect();
    return width > 0 && height > 0 && right > 0 && bottom > 0 && left < window.innerWidth && top < window.innerHeight;
  }

  function canAnimate() {
    // 观察器异步回调可能滞后，以当前画布位置决定是否继续刷帧。
    return !disposed && !document.hidden && !motion.matches && lamps.mesh.visible && lamps.hasNearbyLamps() && isInViewport();
  }
  function sync() {
    if (!canAnimate()) {
      clearTimeout(timer);
      timer = undefined;
    } else if (timer === undefined) {
      timer = window.setTimeout(tick, LAMP_FRAME_MS);
    }
  }
  function tick() {
    timer = undefined;
    if (!canAnimate()) return;
    lamps.pulse(performance.now());
    redraw();
    timer = window.setTimeout(tick, LAMP_FRAME_MS);
  }
  function changeMotion() {
    if (motion.matches) {
      lamps.steady();
      if (!document.hidden && isInViewport()) redraw();
    }
    sync();
  }
  function dispose() {
    disposed = true;
    observer.disconnect();
    motion.removeEventListener('change', changeMotion);
    document.removeEventListener('visibilitychange', sync);
    window.removeEventListener('scroll', sync, true);
    window.removeEventListener('resize', sync);
    clearTimeout(timer);
  }
  return { sync, dispose };
}

// 机柜本地空间的 +Z 为正面。medium 标记用于总览也需要保留的外形细节。
function describeRack({ rack, devices, deviceKind, unit, reserveNameplate = false }, { solid, detail }, includeFine = true) {
  const height = rack.height * unit;
  solid('cover', [RACK_WIDTH, 0.077, RACK_DEPTH], [0, height + 0.065, 0], 0.012);
  solid('cover', [RACK_WIDTH, 0.077, RACK_DEPTH], [0, -0.070, 0], 0.012);
  const frameZ = PANEL_Z - 0.020;
  const footZ = RACK_DEPTH / 2 - 0.14;
  for (const side of [-1, 1]) {
    detail('trim', [0.07, 0.038, RACK_DEPTH - 0.12], [side * 0.89, height + 0.012, 0], true);
    detail('trim', [0.07, 0.038, RACK_DEPTH - 0.12], [side * 0.89, -0.018, 0], true);
    for (const face of [-1, 1]) {
      solid('frame', [0.095, height + 0.10, 0.095], [side * 0.92, height / 2, face * frameZ], 0.009);
      detail('rail', [0.055, height + 0.018, 0.035], [side * 0.844, height / 2, face * (frameZ + 0.015)], true);
      detail('trim', [0.022, height + 0.018, 0.046], [side * 0.885, height / 2, face * (frameZ + 0.002)], true);
      detail('foot', [0.13, 0.053, 0.14], [side * 0.89, -0.134, face * footZ], true);
      if (!includeFine || reserveNameplate) continue;
      for (let u = 1; u <= rack.height; u += 1) {
        const center = (u - 0.5) * unit;
        for (const offset of [-0.26, 0, 0.26]) {
          detail('inset', [0.020, unit * 0.115, 0.004], [side * 0.844, center + offset * unit, face * (frameZ + 0.035)]);
        }
        if (u === 1 || u === rack.height || u % 5 === 0) {
          detail('scale', [0.022, 0.006, 0.003], [side * 0.918, center, face * (DETAIL_Z + 0.007)]);
        }
      }
    }
  }
  if (includeFine) {
    for (let slot = -7; slot <= 7; slot += 1) {
      detail('inset', [0.045, 0.003, 0.34], [slot * 0.072, height + 0.105, 0]);
    }
  }

  function metalFace(device, sign, center, faceHeight, kind) {
    solid('panel', [DEVICE_HALF_WIDTH * 2, faceHeight, 0.040], [0, center, sign * PANEL_Z], 0.005, device, kind);
    if (!includeFine) return;
    // 面板耳与螺栓只提供外观，拾取使用背后的整块面板。
    for (const side of [-1, 1]) {
      detail('trim', [0.050, faceHeight * 0.86, 0.008], [side * 0.833, center, sign * DETAIL_Z], false, device);
      detail('screw', [0.018, 0.018, 0.003], [side * 0.834, center, sign * (DETAIL_Z + 0.005)], false, device);
    }
  }

  function frontDetail(device, kind, sign, center, faceHeight) {
    const feature = (surface, size, center, medium) => detail(surface, size, center, medium, device);
    const frontZ = sign * DETAIL_Z;
    if (!reserveNameplate) {
      feature(accent(kind), [0.039, Math.min(0.040, faceHeight * 0.34), 0.004], [-0.762, center, frontZ],
        [0.080, Math.min(0.052, faceHeight * 0.46), 0.004]);
    }
    const areaCenter = reserveNameplate ? 0.25 : 0;
    const areaWidth = reserveNameplate ? 0.83 : 1.16;
    const areaHeight = Math.min(faceHeight * 0.73, 0.28);
    const base = (surface, width = areaWidth, x = areaCenter) => {
      feature(surface, [width, areaHeight, 0.004], [x, center, frontZ], true);
    };
    if (kind === 'generic') {
      feature('inset', [areaWidth * 0.66, Math.min(0.026, faceHeight * 0.17), 0.004], [areaCenter, center, frontZ], true);
      return;
    }
    if (kind === 'network') {
      const bankWidth = areaWidth * 0.42;
      const slotWidth = bankWidth / 4;
      for (const bank of [-1, 1]) {
        const bankX = areaCenter + bank * areaWidth * 0.26;
        base('inset', bankWidth, bankX);
        if (!includeFine) continue;
        for (const offset of [-1.5, -0.5, 0.5, 1.5]) {
          for (const row of [-1, 1]) {
            const x = bankX + offset * slotWidth;
            const y = center + row * areaHeight * 0.235;
            feature('rail', [slotWidth * 0.78, areaHeight * 0.32, 0.005], [x, y, frontZ * 1.004]);
            feature('socket', [slotWidth * 0.56, areaHeight * 0.20, 0.005], [x, y, frontZ * 1.008]);
          }
        }
      }
      return;
    }
    if (kind === 'power') {
      base('inset', areaWidth * 0.35, areaCenter - areaWidth * 0.30);
      base('trim', areaWidth * 0.50, areaCenter + areaWidth * 0.19);
      if (includeFine) {
        for (const offset of [-0.28, 0, 0.28]) {
          feature('inset', [areaWidth * 0.44, areaHeight * 0.11, 0.004],
            [areaCenter + areaWidth * 0.19, center + areaHeight * offset, frontZ * 1.006]);
        }
      }
      return;
    }

    const storage = kind === 'storage';
    const columns = storage ? 5 : 3;
    const rows = device.u_height >= 2 ? 2 : 1;
    const driveWidth = areaWidth * (storage ? 1 : 0.70);
    const driveCenter = areaCenter - (areaWidth - driveWidth) / 2;
    base('inset', driveWidth, driveCenter);
    if (!storage) base('trim', areaWidth * 0.23, areaCenter + areaWidth * 0.36);
    if (!includeFine) return;
    const pitch = driveWidth / columns;
    const rowHeight = areaHeight / rows;
    for (let row = 0; row < rows; row += 1) {
      const y = center + (row - (rows - 1) / 2) * rowHeight;
      for (let bay = 0; bay < columns; bay += 1) {
        const x = driveCenter + (bay - (columns - 1) / 2) * pitch;
        feature('trim', [pitch * 0.88, rowHeight * 0.78, 0.005], [x, y, frontZ * 1.004]);
        feature('socket', [pitch * 0.49, rowHeight * 0.19, 0.004], [x, y, frontZ * 1.008]);
      }
    }
    if (!storage) {
      for (const offset of [-0.30, -0.10, 0.10, 0.30]) {
        feature('inset', [areaWidth * 0.18, areaHeight * 0.075, 0.004],
          [areaCenter + areaWidth * 0.36, center + areaHeight * offset, frontZ * 1.006]);
      }
    }
  }

  function backDetail(device, kind, sign, center, faceHeight) {
    const feature = (surface, size, center, medium) => detail(surface, size, center, medium, device);
    if (kind === 'generic') {
      feature('inset', [reserveNameplate ? 0.54 : 0.74, Math.min(0.026, faceHeight * 0.17), 0.004],
        [reserveNameplate ? 0.23 : 0, center, sign * DETAIL_Z], true);
      return;
    }
    if (includeFine) {
      const shift = reserveNameplate ? 0.24 : 0;
      for (const centerX of (reserveNameplate ? [shift - 0.16, shift + 0.10] : [-0.57, -0.30])) {
        for (let slot = 0; slot < 5; slot += 1) {
          const y = center + (slot - 2) * Math.min(0.017, faceHeight * 0.16);
          feature('inset', [0.206, 0.008, 0.004], [centerX, y, sign * DETAIL_Z]);
        }
      }
      for (const x of (reserveNameplate ? [shift + 0.28, shift + 0.39] : [-0.04, 0.08, 0.20, 0.37])) {
        feature('rail', [0.072, 0.039, 0.005], [x, center, sign * DETAIL_Z]);
        feature('socket', [0.054, 0.025, 0.005], [x, center, sign * (DETAIL_Z + 0.003)]);
      }
      if (!reserveNameplate) feature('inset', [0.115, 0.053, 0.006], [0.61, center, sign * DETAIL_Z]);
    }
    if (!reserveNameplate) {
      feature(accent(kind), [0.018, 0.009, 0.004], [0.710, center, sign * DETAIL_Z], [0.042, 0.017, 0.004]);
    }
  }

  for (const device of devices) {
    const metrics = deviceMetrics(device, unit);
    const kind = deviceKind(device);
    solid('chassis', [1.665, metrics.faceHeight, metrics.chassisDepth], [0, metrics.centerY, metrics.chassisCenterZ], 0.007, device);
    metalFace(device, metrics.sign, metrics.centerY, metrics.faceHeight, kind);
    frontDetail(device, kind, metrics.sign, metrics.centerY, metrics.faceHeight);
    if (metrics.full) {
      metalFace(device, -metrics.sign, metrics.centerY, metrics.faceHeight, kind);
      backDetail(device, kind, -metrics.sign, metrics.centerY, metrics.faceHeight);
    }
  }
}

function buildSemanticOverlay(scene, entries, unit) {
  const world = new THREE.Matrix4();
  const local = new THREE.Matrix4();
  const axis = new THREE.Vector3(0, 1, 0);
  const pos = new THREE.Vector3();
  const rot = new THREE.Quaternion();
  const scl = new THREE.Vector3();

  const rackMatrices = [];
  const rackEntries = [];
  const deviceMatrices = [];
  const deviceEntries = [];

  for (const entry of entries) {
    const { rack, devices, x, y, z } = entry;
    world.compose(pos.set(x, y, z), rot.setFromAxisAngle(axis, THREE.MathUtils.degToRad(entry.rotation)), scl.setScalar(entry.scale));
    const height = rack.height * unit;
    const ownerFor = roomSearchOwners(rack);
    local.compose(pos.set(0, height + 0.125, 0), rot.identity(), scl.set(RACK_WIDTH * 0.96, 0.036, RACK_DEPTH * 0.96));
    rackEntries.push({ rack, devices, owner: ownerFor() });
    rackMatrices.push(local.clone().premultiply(world));

    for (const device of devices) {
      const m = deviceMetrics(device, unit);
      const semanticDevice = { device, owner: ownerFor(device) };
      local.compose(pos.set(0, m.centerY, m.sign * (DETAIL_Z + 0.014)), rot.identity(), scl.set(1.75, m.faceHeight, 0.018));
      deviceEntries.push(semanticDevice);
      deviceMatrices.push(local.clone().premultiply(world));
      if (m.full) {
        local.compose(pos.set(0, m.centerY, -m.sign * (DETAIL_Z + 0.014)), rot.identity(), scl.set(1.75, m.faceHeight, 0.018));
        deviceEntries.push(semanticDevice);
        deviceMatrices.push(local.clone().premultiply(world));
      }
    }
  }

  const group = new THREE.Group();
  group.name = 'room-semantic-overlay';
  group.visible = false;
  const box = new THREE.BoxGeometry(1, 1, 1);
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.55, metalness: 0.08 });
  const color = new THREE.Color();

  let rackMesh;
  if (rackMatrices.length) {
    rackMesh = new THREE.InstancedMesh(box, mat, rackMatrices.length);
    rackMatrices.forEach((m, i) => {
      rackMesh.setMatrixAt(i, m);
      rackMesh.setColorAt(i, color.setHex(0xffffff));
    });
    rackMesh.instanceMatrix.needsUpdate = true;
    rackMesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
    group.add(rackMesh);
  }

  let deviceMesh;
  if (deviceMatrices.length) {
    deviceMesh = new THREE.InstancedMesh(box, mat, deviceMatrices.length);
    deviceMatrices.forEach((m, i) => {
      deviceMesh.setMatrixAt(i, m);
      deviceMesh.setColorAt(i, color.setHex(0xffffff));
    });
    deviceMesh.instanceMatrix.needsUpdate = true;
    deviceMesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
    group.add(deviceMesh);
  }

  scene.add(group);

  let mode = 'appearance';
  let searchFilter = null;
  function semanticColor(hex, owner) {
    color.setHex(hex);
    if (!matchesRoomSearch(searchFilter, owner)) color.multiplyScalar(SEARCH_DIM);
    return color;
  }

  function paint() {
    if (!group.visible) return;
    if (rackMesh) {
      rackEntries.forEach(({ rack, devices, owner }, i) => {
        rackMesh.setColorAt(i, semanticColor(rackSummaryColor(rack, devices, mode), owner));
      });
      rackMesh.instanceColor.needsUpdate = true;
    }
    if (deviceMesh) {
      deviceEntries.forEach(({ device, owner }, i) => {
        const hex = mode === 'status'
          ? STATUS_COLORS[normalizeStatus(device)]
          : DEPTH_COLORS[normalizeDepth(device)];
        deviceMesh.setColorAt(i, semanticColor(hex, owner));
      });
      deviceMesh.instanceColor.needsUpdate = true;
    }
  }

  return {
    group,
    setMode(next) {
      mode = next;
      group.visible = mode !== 'appearance';
      paint();
    },
    setSearchFilter(filter) {
      searchFilter = filter;
      paint();
    },
  };
}

export function buildRackOverviewLayer(scene, { entries, unit, deviceKind, palette = createRackPalette() }) {
  const tint = roomSearchTint();
  const batches = instancedBoxes(scene, palette, tint);
  const doorsByRack = new Map();
  const world = new THREE.Matrix4();
  const axis = new THREE.Vector3(0, 1, 0);
  const position = new THREE.Vector3();
  const rotation = new THREE.Quaternion();
  const scale = new THREE.Vector3();
  for (const entry of entries) {
    const { rack, devices, x, y, z } = entry;
    position.set(x, y, z);
    rotation.setFromAxisAngle(axis, THREE.MathUtils.degToRad(entry.rotation));
    scale.setScalar(entry.scale);
    world.compose(position, rotation, scale);
    const ownerFor = roomSearchOwners(rack);
    describeRack({ rack, devices, unit, deviceKind }, {
      solid(surface, size, center, _edge, device, kind) {
        batches.add(surface === 'panel' ? `panel/${kind}` : surface, size, center, world, ownerFor(device));
      },
      detail(surface, size, center, medium, device) {
        if (medium) batches.add(surface, Array.isArray(medium) ? medium : size, center, world, ownerFor(device));
      },
    }, false);
    if (entry.enclosure) {
      const enclosure = new THREE.Group();
      enclosure.position.copy(position);
      enclosure.quaternion.copy(rotation);
      enclosure.scale.copy(scale);
      const doors = addCabinetEnclosure(enclosure, { rack, unit, palette, tint, owner: ownerFor() });
      doorsByRack.set(String(rack.id), doors);
      scene.add(enclosure);
    }
  }
  const meshes = batches.finish();
  const lamps = buildOperatingLamps(scene, entries, unit);
  const semantic = buildSemanticOverlay(scene, entries, unit);
  let openIds = new Set();
  let doorMode = true;
  function updateDoors() {
    for (const [id, doors] of doorsByRack) doors.visible = doorMode && !openIds.has(id);
  }
  return {
    meshes,
    lamps,
    setOpenRacks(ids) {
      openIds = ids;
      updateDoors();
    },
    setMode(mode) {
      doorMode = mode === 'appearance';
      updateDoors();
      lamps?.setVisible(mode === 'appearance');
      semantic.setMode(mode);
    },
    setSearchFilter(filter) {
      tint.setSearchFilter(filter);
      semantic.setSearchFilter(filter);
      lamps?.setSearchFilter(filter);
    },
  };
}

export function buildRackFineDetails(group, options) {
  const palette = options.palette ?? createRackPalette();
  const tint = roomSearchTint();
  const batches = instancedBoxes(group, palette, tint);
  const ownerFor = roomSearchOwners(options.rack);
  describeRack(options, {
    solid() {},
    detail(surface, size, center, medium, device) {
      if (!medium) batches.add(surface, size, center, undefined, ownerFor(device));
    },
  });
  const meshes = batches.finish();
  addScaleStrips(group, options.rack.height, options.unit, palette.scaleMaterial(options.rack.height), tint, ownerFor());
  return { meshes, setSearchFilter: tint.setSearchFilter };
}

export function buildRackModel(scene, options) {
  const materialFor = createRackPalette();
  const details = instancedBoxes(scene, materialFor);
  const solids = new Map();
  const frontPanels = new Map();
  const deviceMeshes = new Map();
  const parts = [];
  const labelTextures = [];

  function panelFor(device, kind) {
    const id = String(device.id);
    if (!frontPanels.has(id)) {
      // 同一设备正背面的高亮与状态着色由同一材质控制。
      const panel = material(panelColor(kind), SURFACES.panel[1], SURFACES.panel[2]);
      panel.emissive.setHex(TYPE_ACCENTS[kind] ?? TYPE_ACCENTS.generic);
      panel.emissiveIntensity = 0;
      frontPanels.set(id, panel);
    }
    return frontPanels.get(id);
  }

  function solid(surface, size, center, edge, device, kind) {
    const key = [...size, edge].join('/');
    if (!solids.has(key)) solids.set(key, beveledBox(...size, edge));
    const mesh = new THREE.Mesh(solids.get(key), surface === 'panel' ? panelFor(device, kind) : materialFor(surface));
    mesh.position.set(...center);
    scene.add(mesh);
    if (device) {
      mesh.userData.device = device;
      parts.push(mesh);
      const id = String(device.id);
      if (surface === 'panel' && !deviceMeshes.has(id)) {
        deviceMeshes.set(id, { device, panel: mesh.material, kind });
      }
    }
  }

  describeRack({ ...options, reserveNameplate: true }, {
    solid,
    detail(surface, size, center) { details.add(surface, size, center); },
  });
  details.finish();
  addScaleStrips(scene, options.rack.height, options.unit, materialFor.scaleMaterial(options.rack.height));
  const doors = addCabinetEnclosure(scene, { rack: options.rack, unit: options.unit, palette: materialFor });
  doors.visible = false;

  // 为每台设备添加正面（及全深背面）铭牌贴图。
  const plateGeomCache = new Map();
  for (const device of options.devices) {
    const kind = options.deviceKind(device);
    const texture = createDeviceLabelTexture(device, kind);
    if (!texture) continue;
    labelTextures.push(texture);
    const m = deviceMetrics(device, options.unit);
    const plateH = Math.min(0.088, m.faceHeight * 0.78);
    const plateW = 0.62;
    const key = `${plateW}/${plateH.toFixed(4)}`;
    if (!plateGeomCache.has(key)) plateGeomCache.set(key, new THREE.PlaneGeometry(plateW, plateH));
    const plateMat = new THREE.MeshBasicMaterial({
      map: texture,
      transparent: true,
      polygonOffset: true,
      polygonOffsetFactor: -1,
    });
    const addPlate = (sign) => {
      const plate = new THREE.Mesh(plateGeomCache.get(key), plateMat);
      plate.position.set(-0.46, m.centerY, sign * (DETAIL_Z + 0.005));
      if (sign < 0) plate.rotation.y = Math.PI;
      scene.add(plate);
    };
    addPlate(m.sign);
    if (m.full) addPlate(-m.sign);
  }

  let selected;
  let currentMode = 'appearance';

  function applyPanelStyle(entry, isHovered) {
    const panel = entry.panel;
    if (!panel) return;
    if (currentMode === 'appearance') {
      panel.color.setHex(panelColor(entry.kind));
      panel.emissive.setHex(TYPE_ACCENTS[entry.kind] ?? TYPE_ACCENTS.generic);
      panel.emissiveIntensity = isHovered ? 0.24 : 0;
    } else if (currentMode === 'status') {
      const hex = STATUS_COLORS[normalizeStatus(entry.device)];
      panel.color.setHex(hex);
      panel.emissive.setHex(hex);
      panel.emissiveIntensity = isHovered ? 0.42 : 0.14;
    } else if (currentMode === 'depth') {
      const hex = DEPTH_COLORS[normalizeDepth(entry.device)];
      panel.color.setHex(hex);
      panel.emissive.setHex(hex);
      panel.emissiveIntensity = isHovered ? 0.42 : 0.14;
    }
  }

  function highlight(deviceId) {
    const nextId = deviceId == null ? undefined : String(deviceId);
    if (nextId === selected) return;
    const prevId = selected;
    selected = nextId;
    if (prevId && deviceMeshes.has(prevId)) applyPanelStyle(deviceMeshes.get(prevId), false);
    if (nextId && deviceMeshes.has(nextId)) applyPanelStyle(deviceMeshes.get(nextId), true);
  }

  const lamps = buildOperatingLamps(scene, [{
    rack: options.rack, devices: options.devices, x: 0, y: 0, z: 0, rotation: 0, scale: 1,
  }], options.unit);
  lamps?.setNearbyRacks([options.rack.id]);

  function setMode(mode) {
    currentMode = mode;
    lamps?.setVisible(mode === 'appearance');
    for (const [id, entry] of deviceMeshes) applyPanelStyle(entry, id === selected);
  }

  return {
    parts,
    highlight,
    lamps,
    setMode,
    setDoorVisible(visible) { doors.visible = visible; },
    disposeExtra() {
      materialFor.dispose();
      for (const tex of labelTextures) tex.dispose();
    },
  };
}
