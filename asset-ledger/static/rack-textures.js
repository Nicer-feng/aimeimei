/** 程序化 Canvas 纹理：机柜 U 位标尺与设备面板编号铭牌。 */

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
