import * as THREE from './vendor/three/three.module.min.js';

export function buildRoomLighting(scene, bounds, entries, cabinetWidth, cabinetDepth) {
  const group = new THREE.Group();
  scene.add(group);
  const box = new THREE.BoxGeometry(1, 1, 1);
  const matrix = new THREE.Matrix4();
  const position = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const rotation = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const addBoxes = (shapes, material) => {
    const mesh = new THREE.InstancedMesh(box, material, shapes.length);
    shapes.forEach(({ x = 0, y, z, size, angle = 0 }, index) => {
      rotation.setFromAxisAngle(up, angle);
      matrix.compose(position.set(x, y, z), rotation, scale.fromArray(size));
      mesh.setMatrixAt(index, matrix);
    });
    group.add(mesh);
  };
  const { min, max } = bounds;
  const width = max.x - min.x;
  const height = max.y;
  const rows = [...new Set(entries.map(({ z }) => z))];
  const metal = new THREE.MeshStandardMaterial({ color: 0x233747, metalness: 0.36, roughness: 0.58 });

  // Keep the room open above the cabinets so the top view and picking remain clear.
  const rearWall = [
    { y: height * 0.33, z: min.z, size: [width, height * 0.66, 0.045] },
    { y: 0.042, z: max.z - 0.02, size: [width, 0.084, 0.032] },
  ];
  addBoxes(rearWall, new THREE.MeshStandardMaterial({ color: 0x182736, roughness: 0.86 }));

  const rails = [];
  const strips = [
    { y: height * 0.64, z: min.z + 0.029, size: [width * 0.97, 0.014, 0.016] },
    { y: 0.021, z: max.z - 0.040, size: [width * 0.97, 0.014, 0.018] },
  ];
  for (const z of rows) {
    for (const edge of [-1, 1]) {
      rails.push({ y: height + 0.14, z: z + edge * 0.15, size: [width - 0.22, 0.038, 0.034] });
    }
    for (let x = min.x + 0.32; x < max.x - 0.2; x += 0.41) {
      rails.push({ x, y: height + 0.138, z, size: [0.025, 0.033, 0.28] });
    }
    strips.push({ y: height + 0.22, z: z + 0.49, size: [width * 0.92, 0.018, 0.055] });
  }
  if (rails.length) addBoxes(rails, metal);
  else metal.dispose();

  for (const entry of entries) {
    const angle = THREE.MathUtils.degToRad(entry.rotation);
    const front = cabinetDepth * 0.49;
    strips.push({
      x: entry.x + Math.sin(angle) * front,
      y: entry.middle + entry.height / 2 - 0.035,
      z: entry.z + Math.cos(angle) * front,
      size: [cabinetWidth * 0.90, 0.018, 0.022],
      angle,
    });
  }
  addBoxes(strips, new THREE.MeshBasicMaterial({ color: 0x6dbaca, toneMapped: false }));

  const accent = new THREE.InstancedMesh(
    new THREE.RingGeometry(0.91, 1, 32),
    new THREE.MeshBasicMaterial({
      color: 0x68deff, transparent: true, opacity: 0.82, depthWrite: false, toneMapped: false,
    }),
    entries.length,
  );
  accent.count = 0;
  accent.frustumCulled = false;
  group.add(accent);
  const horizontal = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
  function highlight(rackId, selectedRackId, filter) {
    let count = 0;
    for (const entry of entries) {
      const id = String(entry.rack.id);
      if (id !== rackId && id !== selectedRackId && !filter?.rackIds.has(id) && !filter?.directRackIds.has(id)) continue;
      rotation.setFromAxisAngle(up, THREE.MathUtils.degToRad(entry.rotation)).multiply(horizontal);
      matrix.compose(position.set(entry.x, 0.020, entry.z), rotation,
        scale.set(cabinetWidth * 0.55, cabinetDepth * 0.86, 1));
      accent.setMatrixAt(count++, matrix);
    }
    accent.count = count;
    accent.instanceMatrix.needsUpdate = true;
  }
  return { group, highlight };
}
