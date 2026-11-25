import * as THREE from './vendor/three/three.module.min.js';

const SURFACES = {
  frame: [0x232b31, .57, .27],
  rail: [0x525d64, .55, .34],
  trim: [0x3b454d, .52, .30],
  cover: [0x303a41, .65, .23],
  chassis: [0x3c454c, .68, .16],
  panel: [0x48515a, .62, .18],
  inset: [0x131a20, .78, .10],
  socket: [0x151d22, .74, .20],
  screw: [0x79848c, .49, .46],
  scale: [0x9ba9ae, .62, .16],
  foot: [0x252a2c, .86, .08],
};
const TYPE_ACCENTS = { server: 0x7295b6, network: 0x547780, power: 0xd1a157, storage: 0x9d8daf };
const PANEL_Z = .573;
const DETAIL_Z = .596;
const LAMP_PERIOD_MS = 3200;
const LAMP_FRAME_MS = 80;

function material(color, roughness, metalness) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness });
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

function rackPalette() {
  const materials = new Map();
  return (surface) => {
    if (!materials.has(surface)) {
      if (SURFACES[surface]) {
        materials.set(surface, material(...SURFACES[surface]));
      } else {
        const color = TYPE_ACCENTS[surface.slice('accent/'.length)] ?? TYPE_ACCENTS.server;
        materials.set(surface, material(color, .72, .10));
      }
    }
    return materials.get(surface);
  };
}

function instancedBoxes(parent, materialFor) {
  const buckets = new Map();
  const matrix = new THREE.Matrix4();
  const position = new THREE.Vector3();
  const rotation = new THREE.Quaternion();
  const scale = new THREE.Vector3();

  function add(surface, size, center, world) {
    if (!buckets.has(surface)) buckets.set(surface, []);
    matrix.compose(position.fromArray(center), rotation, scale.fromArray(size));
    if (world) matrix.premultiply(world);
    buckets.get(surface).push(matrix.clone());
  }

  function finish() {
    if (!buckets.size) return [];
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const meshes = [];
    for (const [surface, matrices] of buckets) {
      const mesh = new THREE.InstancedMesh(geometry, materialFor(surface), matrices.length);
      matrices.forEach((transform, index) => mesh.setMatrixAt(index, transform));
      mesh.instanceMatrix.needsUpdate = true;
      mesh.receiveShadow = true;
      parent.add(mesh);
      meshes.push(mesh);
    }
    buckets.clear();
    return meshes;
  }

  return { add, finish };
}

function buildOperatingLamps(parent, entries, unit) {
  const indicesByRack = new Map();
  const matrices = [];
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
    const indices = [];
    for (const device of running) {
      const onFront = device.face === 'front';
      const height = (device.u_start - 1 + device.u_height / 2) * unit;
      position.set(.778, height, (onFront ? 1 : -1) * (DETAIL_Z + .009));
      indices.push(matrices.length);
      matrices.push(local.compose(position, onFront ? front : rear, normalSize).clone().premultiply(world));
    }
    indicesByRack.set(String(rack.id), indices);
  }
  if (!matrices.length) return undefined;

  const steadyColor = new THREE.Color(0x4b7b60);
  const dimColor = new THREE.Color(0x56906a);
  const brightColor = new THREE.Color(0x70a785);
  const pulseColor = new THREE.Color();
  const mesh = new THREE.InstancedMesh(new THREE.CircleGeometry(.023, 8),
    new THREE.MeshBasicMaterial({ toneMapped: false }), matrices.length);
  mesh.name = 'running-device-lamps';
  matrices.forEach((matrix, index) => {
    mesh.setMatrixAt(index, matrix);
    mesh.setColorAt(index, steadyColor);
  });
  mesh.instanceMatrix.needsUpdate = true;
  mesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
  parent.add(mesh);

  let animated = [];
  function paint(color) {
    if (!animated.length) return;
    for (const index of animated) mesh.setColorAt(index, color);
    mesh.instanceColor.needsUpdate = true;
  }
  return {
    hasNearbyLamps: () => animated.length > 0,
    setNearbyRacks(rackIds) {
      paint(steadyColor);
      animated = [];
      for (const id of rackIds) {
        const indices = indicesByRack.get(String(id));
        if (indices) animated.push(...indices);
      }
    },
    steady: () => paint(steadyColor),
    pulse(time) {
      const phase = (time % LAMP_PERIOD_MS) / LAMP_PERIOD_MS;
      const amount = .5 - .5 * Math.cos(phase * Math.PI * 2);
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
    return !disposed && !document.hidden && !motion.matches && lamps.hasNearbyLamps() && isInViewport();
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
function describeRack({ rack, devices, deviceKind, unit }, { solid, detail }, includeFine = true) {
  const height = rack.height * unit;
  solid('cover', [1.98, .077, 1.27], [0, height + .065, 0], .012);
  solid('cover', [1.98, .077, 1.27], [0, -.070, 0], .012);
  for (const side of [-1, 1]) {
    detail('trim', [.07, .038, 1.15], [side * .89, height + .012, 0], true);
    detail('trim', [.07, .038, 1.15], [side * .89, -.018, 0], true);
    for (const face of [-1, 1]) {
      solid('frame', [.095, height + .10, .095], [side * .92, height / 2, face * .553], .009);
      detail('rail', [.055, height + .018, .035], [side * .844, height / 2, face * .568], true);
      detail('trim', [.022, height + .018, .046], [side * .885, height / 2, face * .555], true);
      detail('foot', [.13, .053, .14], [side * .89, -.134, face * .50], true);
      if (!includeFine) continue;
      for (let u = 1; u <= rack.height; u += 1) {
        const center = (u - .5) * unit;
        for (const offset of [-.26, 0, .26]) {
          detail('inset', [.020, unit * .115, .004], [side * .844, center + offset * unit, face * .588]);
        }
        if (u === 1 || u === rack.height || u % 5 === 0) {
          detail('scale', [.022, .006, .003], [side * .918, center, face * .603]);
        }
      }
    }
  }
  if (includeFine) {
    for (let slot = -7; slot <= 7; slot += 1) {
      detail('inset', [.045, .003, .34], [slot * .072, height + .105, 0]);
    }
  }

  function metalFace(device, sign, center, faceHeight, kind) {
    solid('panel', [1.738, faceHeight, .040], [0, center, sign * PANEL_Z], .005, device, kind);
    if (!includeFine) return;
    // 面板耳与螺栓只提供外观，拾取使用背后的整块面板。
    for (const side of [-1, 1]) {
      detail('trim', [.050, faceHeight * .86, .008], [side * .833, center, sign * DETAIL_Z]);
      detail('screw', [.018, .018, .003], [side * .834, center, sign * (DETAIL_Z + .005)]);
    }
  }

  function frontDetail(kind, sign, center, faceHeight, units) {
    const frontZ = sign * DETAIL_Z;
    detail(accent(kind), [.039, Math.min(.040, faceHeight * .34), .004], [-.762, center, frontZ],
      [.080, Math.min(.052, faceHeight * .46), .004]);
    if (!includeFine) return;
    if (kind === 'network') {
      for (const bank of [-1, 1]) {
        for (let port = 0; port < 6; port += 1) {
          const x = bank * .316 + (port - 2.5) * .087;
          for (const row of [-1, 1]) {
            const y = center + row * Math.min(.022, faceHeight * .19);
            detail('rail', [.071, .027, .004], [x, y, frontZ]);
            detail('socket', [.052, .017, .004], [x, y, sign * (DETAIL_Z + .003)]);
          }
        }
      }
      for (const offset of [-.012, .012]) {
        detail('inset', [.014, .006, .005], [.737, center + offset, frontZ]);
      }
      return;
    }
    if (kind === 'power') {
      for (let outlet = 0; outlet < 6; outlet += 1) {
        const x = (outlet - 2.5) * .172;
        detail('rail', [.111, .066, .005], [x, center, frontZ]);
        detail('socket', [.093, .048, .005], [x, center, sign * (DETAIL_Z + .003)]);
        for (const offset of [-.024, .024]) {
          detail('screw', [.011, .014, .003], [x + offset, center, sign * (DETAIL_Z + .005)]);
        }
      }
      detail(accent(kind), [.055, .043, .008], [.685, center, frontZ]);
      return;
    }

    const columns = kind === 'storage' ? 5 : 7;
    const rows = Math.min(3, Math.max(1, Math.ceil(units / 1.7)));
    const pitch = 1.14 / columns;
    const rowHeight = Math.min(.080, faceHeight * .86 / rows);
    for (let row = 0; row < rows; row += 1) {
      const y = center + (row - (rows - 1) / 2) * rowHeight;
      for (let bay = 0; bay < columns; bay += 1) {
        const x = -.07 + (bay - (columns - 1) / 2) * pitch;
        detail('inset', [pitch - .013, rowHeight * .80, .006], [x, y, frontZ]);
        detail('trim', [pitch - .031, .013, .005], [x, y - rowHeight * .13, sign * (DETAIL_Z + .004)]);
      }
    }
    for (const offset of [-.024, 0, .024]) {
      detail('inset', [.014, .006, .004], [.683, center + offset, frontZ]);
    }
  }

  function backDetail(kind, sign, center, faceHeight) {
    if (includeFine) {
      for (const centerX of [-.57, -.30]) {
        for (let slot = 0; slot < 5; slot += 1) {
          const y = center + (slot - 2) * Math.min(.017, faceHeight * .16);
          detail('inset', [.206, .008, .004], [centerX, y, sign * DETAIL_Z]);
        }
      }
      for (const x of [-.04, .08, .20, .37]) {
        detail('rail', [.072, .039, .005], [x, center, sign * DETAIL_Z]);
        detail('socket', [.054, .025, .005], [x, center, sign * (DETAIL_Z + .003)]);
      }
      detail('inset', [.115, .053, .006], [.61, center, sign * DETAIL_Z]);
    }
    detail(accent(kind), [.018, .009, .004], [.710, center, sign * DETAIL_Z], [.042, .017, .004]);
  }

  for (const device of devices) {
    const sign = device.face === 'front' ? 1 : -1;
    const full = device.mount_depth === 'full';
    const center = (device.u_start - 1 + device.u_height / 2) * unit;
    const faceHeight = device.u_height * unit - .006;
    const kind = deviceKind(device);
    solid('chassis', [1.665, faceHeight, full ? 1.11 : .53], [0, center, full ? 0 : .29 * sign], .007, device);
    metalFace(device, sign, center, faceHeight, kind);
    frontDetail(kind, sign, center, faceHeight, device.u_height);
    if (full) {
      metalFace(device, -sign, center, faceHeight, kind);
      backDetail(kind, -sign, center, faceHeight);
    }
  }
}

export function buildRackOverviewLayer(scene, { entries, unit, deviceKind }) {
  const batches = instancedBoxes(scene, rackPalette());
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
    describeRack({ rack, devices, unit, deviceKind }, {
      solid(surface, size, center) {
        batches.add(surface, size, center, world);
      },
      detail(surface, size, center, medium) {
        if (medium) batches.add(surface, Array.isArray(medium) ? medium : size, center, world);
      },
    }, false);
  }
  return { meshes: batches.finish(), lamps: buildOperatingLamps(scene, entries, unit) };
}

export function buildRackFineDetails(group, options) {
  const batches = instancedBoxes(group, rackPalette());
  describeRack(options, {
    solid() {},
    detail(surface, size, center, medium) {
      if (!medium) batches.add(surface, size, center);
    },
  });
  return { meshes: batches.finish() };
}

export function buildRackModel(scene, options) {
  const materialFor = rackPalette();
  const details = instancedBoxes(scene, materialFor);
  const solids = new Map();
  const frontPanels = new Map();
  const parts = [];

  function panelFor(device, kind) {
    const id = String(device.id);
    if (!frontPanels.has(id)) {
      // 同一设备正背面的高亮由同一材质控制。
      const panel = material(...SURFACES.panel);
      panel.emissive.setHex(TYPE_ACCENTS[kind] ?? TYPE_ACCENTS.server);
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
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    scene.add(mesh);
    if (device) {
      mesh.userData.device = device;
      parts.push(mesh);
    }
  }

  describeRack(options, {
    solid,
    detail(surface, size, center) { details.add(surface, size, center); },
  });
  details.finish();

  let selected;
  function highlight(deviceId) {
    const panel = deviceId == null ? undefined : frontPanels.get(String(deviceId));
    if (panel === selected) return;
    if (selected) selected.emissiveIntensity = 0;
    if (panel) panel.emissiveIntensity = .24;
    selected = panel;
  }

  const lamps = buildOperatingLamps(scene, [{ rack: options.rack, devices: options.devices, x: 0, y: 0, z: 0,
    rotation: 0, scale: 1 }], options.unit);
  lamps?.setNearbyRacks([options.rack.id]);
  return { parts, highlight, lamps };
}
