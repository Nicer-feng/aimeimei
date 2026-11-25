import * as THREE from './vendor/three/three.module.min.js';

const SURFACES = {
  frame: [0x232b31, .57, .27],
  rail: [0x525d64, .55, .34],
  trim: [0x3b454d, .52, .30],
  cover: [0x303a41, .65, .23],
  chassis: [0x323940, .68, .19],
  panel: [0x242b31, .55, .26],
  inset: [0x131a20, .78, .10],
  socket: [0x151d22, .74, .20],
  screw: [0x79848c, .49, .46],
  scale: [0x9ba9ae, .62, .16],
  foot: [0x252a2c, .86, .08],
};
const TYPE_ACCENTS = { server: 0x7295b6, network: 0x539e8b, power: 0xd1a157, storage: 0x9d8daf };
const PANEL_Z = .573;
const DETAIL_Z = .596;

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

export function buildRackModel(scene, { rack, devices, deviceKind, unit }) {
  const surfaces = Object.fromEntries(Object.entries(SURFACES).map(([key, values]) => [key, material(...values)]));
  const accents = new Map();
  const buckets = new Map();
  const solids = new Map();
  const parts = [];
  const frontPanels = new Map();
  const height = rack.height * unit;

  function solid(surface, size, position, edge) {
    const key = [...size, edge].join('/');
    if (!solids.has(key)) solids.set(key, beveledBox(...size, edge));
    const mesh = new THREE.Mesh(solids.get(key), surface);
    mesh.position.set(...position);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    scene.add(mesh);
    return mesh;
  }

  function detail(surface, size, position) {
    if (!buckets.has(surface)) buckets.set(surface, []);
    buckets.get(surface).push({ size, position });
  }

  function accent(kind) {
    if (!accents.has(kind)) {
      const color = TYPE_ACCENTS[kind] ?? TYPE_ACCENTS.server;
      const light = material(color, .63, .10);
      light.emissive.setHex(color);
      light.emissiveIntensity = .12;
      accents.set(kind, light);
    }
    return accents.get(kind);
  }

  solid(surfaces.cover, [1.98, .077, 1.27], [0, height + .065, 0], .012);
  solid(surfaces.cover, [1.98, .077, 1.27], [0, -.070, 0], .012);
  for (const side of [-1, 1]) {
    detail(surfaces.trim, [.07, .038, 1.15], [side * .89, height + .012, 0]);
    detail(surfaces.trim, [.07, .038, 1.15], [side * .89, -.018, 0]);
    for (const face of [-1, 1]) {
      solid(surfaces.frame, [.095, height + .10, .095], [side * .92, height / 2, face * .553], .009);
      detail(surfaces.rail, [.055, height + .018, .035], [side * .844, height / 2, face * .568]);
      detail(surfaces.trim, [.022, height + .018, .046], [side * .885, height / 2, face * .555]);
      detail(surfaces.foot, [.13, .053, .14], [side * .89, -.134, face * .50]);
      for (let u = 1; u <= rack.height; u += 1) {
        const center = (u - .5) * unit;
        for (const offset of [-.26, 0, .26]) {
          detail(surfaces.inset, [.020, unit * .115, .004], [side * .844, center + offset * unit, face * .588]);
        }
        if (u === 1 || u === rack.height || u % 5 === 0) {
          detail(surfaces.scale, [.022, .006, .003], [side * .918, center, face * .603]);
        }
      }
    }
  }
  for (let slot = -7; slot <= 7; slot += 1) {
    detail(surfaces.inset, [.045, .003, .34], [slot * .072, height + .105, 0]);
  }

  function metalFace(device, sign, center, faceHeight, surface) {
    const panel = solid(surface, [1.738, faceHeight, .040], [0, center, sign * PANEL_Z], .005);
    panel.userData.device = device;
    parts.push(panel);
    // 面板耳与螺栓只提供外观，拾取使用背后的整块面板。
    for (const side of [-1, 1]) {
      detail(surfaces.trim, [.050, faceHeight * .86, .008], [side * .833, center, sign * DETAIL_Z]);
      detail(surfaces.screw, [.018, .018, .003], [side * .834, center, sign * (DETAIL_Z + .005)]);
    }
  }

  function frontDetail(kind, sign, center, faceHeight, units) {
    const frontZ = sign * DETAIL_Z;
    detail(accent(kind), [.039, Math.min(.040, faceHeight * .34), .004], [-.762, center, frontZ]);
    if (kind === 'network') {
      for (const bank of [-1, 1]) {
        for (let port = 0; port < 6; port += 1) {
          const x = bank * .316 + (port - 2.5) * .087;
          for (const row of [-1, 1]) {
            const y = center + row * Math.min(.022, faceHeight * .19);
            detail(surfaces.rail, [.071, .027, .004], [x, y, frontZ]);
            detail(surfaces.socket, [.052, .017, .004], [x, y, sign * (DETAIL_Z + .003)]);
          }
        }
      }
      for (const offset of [-.012, .012]) {
        detail(accent(kind), [.014, .006, .005], [.737, center + offset, frontZ]);
      }
      return;
    }
    if (kind === 'power') {
      for (let outlet = 0; outlet < 6; outlet += 1) {
        const x = (outlet - 2.5) * .172;
        detail(surfaces.rail, [.111, .066, .005], [x, center, frontZ]);
        detail(surfaces.socket, [.093, .048, .005], [x, center, sign * (DETAIL_Z + .003)]);
        for (const offset of [-.024, .024]) {
          detail(surfaces.screw, [.011, .014, .003], [x + offset, center, sign * (DETAIL_Z + .005)]);
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
        detail(surfaces.inset, [pitch - .013, rowHeight * .80, .006], [x, y, frontZ]);
        detail(surfaces.trim, [pitch - .031, .013, .005], [x, y - rowHeight * .13, sign * (DETAIL_Z + .004)]);
      }
    }
    for (const offset of [-.024, 0, .024]) {
      detail(accent(kind), [.014, .006, .004], [.683, center + offset, frontZ]);
    }
  }

  function backDetail(kind, sign, center, faceHeight) {
    for (const centerX of [-.57, -.30]) {
      for (let slot = 0; slot < 5; slot += 1) {
        const y = center + (slot - 2) * Math.min(.017, faceHeight * .16);
        detail(surfaces.inset, [.206, .008, .004], [centerX, y, sign * DETAIL_Z]);
      }
    }
    for (const x of [-.04, .08, .20, .37]) {
      detail(surfaces.rail, [.072, .039, .005], [x, center, sign * DETAIL_Z]);
      detail(surfaces.socket, [.054, .025, .005], [x, center, sign * (DETAIL_Z + .003)]);
    }
    detail(surfaces.inset, [.115, .053, .006], [.61, center, sign * DETAIL_Z]);
    detail(accent(kind), [.018, .009, .004], [.710, center, sign * DETAIL_Z]);
  }

  for (const device of devices) {
    const sign = device.face === 'front' ? 1 : -1;
    const full = device.mount_depth === 'full';
    const center = (device.u_start - 1 + device.u_height / 2) * unit;
    const faceHeight = device.u_height * unit - .006;
    const kind = deviceKind(device);
    const chassis = solid(surfaces.chassis, [1.665, faceHeight, full ? 1.11 : .53],
      [0, center, full ? 0 : .29 * sign], .007);
    chassis.userData.device = device;
    parts.push(chassis);

    // 每台设备的两个可见面共用高亮材质，切换时只修改该材质的发光强度。
    const panel = surfaces.panel.clone();
    panel.emissive.setHex(TYPE_ACCENTS[kind] ?? TYPE_ACCENTS.server);
    panel.emissiveIntensity = 0;
    frontPanels.set(String(device.id), panel);
    metalFace(device, sign, center, faceHeight, panel);
    frontDetail(kind, sign, center, faceHeight, device.u_height);
    if (full) {
      metalFace(device, -sign, center, faceHeight, panel);
      backDetail(kind, -sign, center, faceHeight);
    }
  }
  surfaces.panel.dispose();

  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const matrix = new THREE.Matrix4();
  const position = new THREE.Vector3();
  const rotation = new THREE.Quaternion();
  const scale = new THREE.Vector3();
  for (const [surface, marks] of buckets) {
    const mesh = new THREE.InstancedMesh(geometry, surface, marks.length);
    marks.forEach((mark, index) => {
      matrix.compose(position.fromArray(mark.position), rotation, scale.fromArray(mark.size));
      mesh.setMatrixAt(index, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.receiveShadow = true;
    scene.add(mesh);
  }

  let selected;
  function highlight(deviceId) {
    const panel = deviceId == null ? undefined : frontPanels.get(String(deviceId));
    if (panel === selected) return;
    if (selected) selected.emissiveIntensity = 0;
    if (panel) panel.emissiveIntensity = .24;
    selected = panel;
  }

  return { parts, highlight };
}
