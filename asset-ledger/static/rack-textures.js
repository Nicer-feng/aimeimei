/** 机柜标尺、设备铭牌和场景所用的程序化纹理。 */

import * as THREE from './vendor/three/three.module.min.js';
import { STATUS_COLORS, TYPE_ACCENTS, normalizeStatus } from './rack-geometry.js';

const STATUS_TAGS = {
  running: '运行',
  unpowered: '未通电',
  disabled: '停用',
  unknown: '待核',
};

function hexCss(color) {
  return `#${color.toString(16).padStart(6, '0')}`;
}

function canvasSurface(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  return ctx ? { canvas, ctx } : null;
}

function colorTexture(canvas) {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function createRackEnvironment(renderer) {
  const surface = canvasSurface(256, 128);
  if (!surface) return null;
  const { canvas, ctx } = surface;
  const sky = ctx.createLinearGradient(0, 0, 0, canvas.height);
  sky.addColorStop(0, '#8999a9');
  sky.addColorStop(0.32, '#a5b6c2');
  sky.addColorStop(0.58, '#707f88');
  sky.addColorStop(1, '#303a42');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const softboxes = [
    [60, 37, 57, 31, 'rgba(255, 247, 230, 0.92)'],
    [173, 35, 43, 29, 'rgba(207, 231, 255, 0.84)'],
    [121, 61, 24, 24, 'rgba(236, 248, 255, 0.50)'],
  ];
  for (const [x, y, width, height, color] of softboxes) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(width, height);
    const light = ctx.createRadialGradient(0, 0, 0.16, 0, 0, 1);
    light.addColorStop(0, color);
    light.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = light;
    ctx.fillRect(-1, -1, 2, 2);
    ctx.restore();
  }

  const texture = colorTexture(canvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  let generator;
  try {
    generator = new THREE.PMREMGenerator(renderer);
    return generator.fromEquirectangular(texture);
  } catch {
    // 环境反射不可用时保留场景现有灯光。
    return null;
  } finally {
    generator?.dispose();
    texture.dispose();
  }
}

export function createFloorTileTexture() {
  const size = 128;
  const surface = canvasSurface(size, size);
  if (!surface) return null;
  const { canvas, ctx } = surface;
  const finish = ctx.createLinearGradient(0, 0, size, size);
  finish.addColorStop(0, '#f3f4f4');
  finish.addColorStop(1, '#e8ebeb');
  ctx.fillStyle = finish;
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = 'rgba(117, 129, 128, 0.065)';
  for (let index = 0; index < 200; index += 1) {
    const x = (index * 53 + Math.floor(index / 13) * 41) % (size - 4) + 2;
    const y = (index * 29 + Math.floor(index / 17) * 43) % (size - 4) + 2;
    ctx.fillRect(x, y, 1, 1);
  }
  ctx.fillStyle = '#cbd2d2';
  ctx.fillRect(0, 0, size, 1);
  ctx.fillRect(0, 0, 1, size);
  const texture = colorTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.anisotropy = 4;
  return texture;
}

export function createContactShadowTexture() {
  const size = 96;
  const surface = canvasSurface(size, size);
  if (!surface) return null;
  const { canvas, ctx } = surface;
  const center = size / 2;
  const shade = ctx.createRadialGradient(center, center, center * 0.12, center, center, center);
  shade.addColorStop(0, 'rgba(36, 53, 57, 0.52)');
  shade.addColorStop(0.55, 'rgba(36, 53, 57, 0.33)');
  shade.addColorStop(0.82, 'rgba(36, 53, 57, 0.10)');
  shade.addColorStop(1, 'rgba(36, 53, 57, 0)');
  ctx.fillStyle = shade;
  ctx.fillRect(0, 0, size, size);
  return colorTexture(canvas);
}

export function createOperatingLampTexture() {
  const size = 64;
  const surface = canvasSurface(size, size);
  if (!surface) return null;
  const { canvas, ctx } = surface;
  const center = size / 2;
  const light = ctx.createRadialGradient(center, center, 0, center, center, center - 1);
  light.addColorStop(0, '#ffffff');
  light.addColorStop(0.32, 'rgba(255, 255, 255, 0.95)');
  light.addColorStop(0.57, 'rgba(255, 255, 255, 0.72)');
  light.addColorStop(0.78, 'rgba(255, 255, 255, 0.30)');
  light.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = light;
  ctx.fillRect(0, 0, size, size);
  return colorTexture(canvas);
}

export function createRackScaleTexture(rackHeight) {
  const stepPx = 28;
  const width = 64;
  const height = Math.max(stepPx, rackHeight * stepPx);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.clearRect(0, 0, width, height);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  for (let u = 1; u <= rackHeight; u += 1) {
    const y = height - (u - 0.5) * stepPx;
    const major = u === 1 || u === rackHeight || u % 5 === 0;
    ctx.fillStyle = major ? 'rgba(220, 234, 236, 0.92)' : 'rgba(155, 174, 180, 0.62)';
    ctx.fillRect(6, y - (major ? 1 : 0.5), major ? 10 : 6, major ? 2 : 1);
    ctx.fillRect(width - (major ? 16 : 12), y - (major ? 1 : 0.5), major ? 10 : 6, major ? 2 : 1);
    if (major || rackHeight <= 24) {
      ctx.font = `${major ? 700 : 500} ${major ? 15 : 13}px ui-monospace, SFMono-Regular, Consolas, monospace`;
      ctx.fillStyle = major ? '#edf6f6' : '#b7c7cc';
      ctx.fillText(String(u).padStart(2, '0'), width / 2, y + 0.5);
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

export function createDeviceLabelTexture(device, kind) {
  const width = 512;
  const height = 64;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const status = normalizeStatus(device);
  const accent = TYPE_ACCENTS[kind] ?? TYPE_ACCENTS.server;

  ctx.fillStyle = 'rgba(18, 25, 31, 0.92)';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = 'rgba(130, 152, 164, 0.42)';
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, width - 2, height - 2);

  ctx.fillStyle = hexCss(accent);
  ctx.fillRect(0, 0, 10, height);

  ctx.fillStyle = '#e7f1f4';
  ctx.font = '700 24px ui-monospace, SFMono-Regular, Consolas, monospace';
  ctx.textBaseline = 'middle';
  const code = String(device.code || '').slice(0, 16);
  ctx.fillText(code, 22, 23);

  ctx.fillStyle = '#a8bcc4';
  ctx.font = '500 18px "PingFang SC", "Microsoft YaHei", system-ui, sans-serif';
  const rawName = Array.from(String(device.name || ''));
  const name = rawName.length > 16 ? `${rawName.slice(0, 15).join('')}…` : rawName.join('');
  ctx.fillText(name, 22, 47);

  const badgeText = STATUS_TAGS[status];
  const badgeColor = hexCss(STATUS_COLORS[status]);
  ctx.font = '700 18px "PingFang SC", "Microsoft YaHei", system-ui, sans-serif';
  const badgeWidth = Math.max(66, ctx.measureText(badgeText).width + 24);
  const badgeX = width - badgeWidth - 14;
  ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
  ctx.fillRect(badgeX, 14, badgeWidth, 36);
  ctx.strokeStyle = badgeColor;
  ctx.lineWidth = 2;
  ctx.strokeRect(badgeX, 14, badgeWidth, 36);
  ctx.fillStyle = badgeColor;
  ctx.textAlign = 'center';
  ctx.fillText(badgeText, badgeX + badgeWidth / 2, 33);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}
