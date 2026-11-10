import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import QRCodePng from 'qrcode';

const require = createRequire(import.meta.url);
const QRCode = require('qrcode-terminal/vendor/QRCode');
const errorLevel = require('qrcode-terminal/vendor/QRCode/QRErrorCorrectLevel');

export function toQrSvg(data) {
  const qr = new QRCode(-1, errorLevel.M);
  qr.addData(data);
  qr.make();
  const modules = qr.getModuleCount();
  const margin = 4;
  const scale = 10;
  const size = (modules + margin * 2) * scale;
  const cells = [];
  for (let row = 0; row < modules; row++) {
    for (let column = 0; column < modules; column++) {
      if (qr.isDark(row, column)) {
        cells.push(`M${column + margin},${row + margin}h1v1h-1z`);
      }
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${modules + margin * 2} ${modules + margin * 2}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><path d="${cells.join('')}" fill="#000"/></svg>`;
}

export function writePairingQr(data, sessionDir) {
  fs.mkdirSync(sessionDir, { recursive: true });
  const svgPath = path.join(sessionDir, 'pairing-qr.svg');
  const pngPath = path.join(sessionDir, 'pairing-qr.png');
  fs.writeFileSync(svgPath, toQrSvg(data), { mode: 0o600 });
  return QRCodePng.toFile(pngPath, data, {
    type: 'png', errorCorrectionLevel: 'M', margin: 4, width: 700,
  }).then(() => {
    if (process.platform !== 'win32') fs.chmodSync(pngPath, 0o600);
    return pngPath;
  });
}
