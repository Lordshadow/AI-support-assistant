/**
 * WCAG 2.1 AA Contrast Ratio Verification Script
 * Validates token color pairs against WCAG AA standards (4.5:1 for normal text, 3:1 for large/UI components).
 */

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const bigint = parseInt(clean, 16);
  return [
    (bigint >> 16) & 255,
    (bigint >> 8) & 255,
    bigint & 255
  ];
}

function getLuminance(r, g, b) {
  const [rs, gs, bs] = [r, g, b].map(val => {
    const s = val / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function getContrast(hex1, hex2) {
  const rgb1 = hexToRgb(hex1);
  const rgb2 = hexToRgb(hex2);
  const l1 = getLuminance(...rgb1);
  const l2 = getLuminance(...rgb2);
  const brighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (brighter + 0.05) / (darker + 0.05);
}

const tests = [
  { name: 'Primary Text on Dark Teal Canvas', fg: '#EAF6F4', bg: '#041E1D', required: 4.5 },
  { name: 'Primary Text on Teal Panel (glass-panel)', fg: '#EAF6F4', bg: '#062F2E', required: 4.5 },
  { name: 'Primary Text on Teal Chrome (glass-chrome)', fg: '#EAF6F4', bg: '#0B4A47', required: 4.5 },
  { name: 'Secondary Text on Teal Panel', fg: '#B6D5D1', bg: '#062F2E', required: 4.5 },
  { name: 'Micro-Label Aqua on Teal Panel', fg: '#3FD2C0', bg: '#062F2E', required: 4.5 },
  { name: 'Primary Text on Mint Surface (glass-panel-light)', fg: '#0F3D3B', bg: '#E8F2F0', required: 4.5 },
  { name: 'Primary Text on Ultra-Clean Mint (mint-50)', fg: '#0F3D3B', bg: '#F5FAF9', required: 4.5 },
  { name: 'Secondary Text on Mint Surface', fg: '#1F5A57', bg: '#E8F2F0', required: 4.5 },
  { name: 'Aqua Focus / UI Edge on Dark Base (3:1 required)', fg: '#3FD2C0', bg: '#041E1D', required: 3.0 },
  { name: 'Emerald Accent on Dark Base (3:1 required)', fg: '#17A58F', bg: '#041E1D', required: 3.0 },
  { name: 'Success Alert on Teal Dark', fg: '#2ED573', bg: '#062F2E', required: 3.0 },
  { name: 'Warning Alert on Teal Dark', fg: '#FFA502', bg: '#062F2E', required: 3.0 },
  { name: 'Danger Alert on Teal Dark', fg: '#FF5252', bg: '#062F2E', required: 3.0 },
];

console.log('=== WCAG 2.1 AA Color Contrast Verification ===');
let failed = 0;

for (const t of tests) {
  const ratio = getContrast(t.fg, t.bg);
  const passed = ratio >= t.required;
  const status = passed ? 'PASS' : 'FAIL';
  console.log(`[${status}] ${t.name}: ${ratio.toFixed(2)}:1 (Min required: ${t.required}:1)`);
  if (!passed) failed++;
}

console.log('================================================');
if (failed > 0) {
  console.error(`FAILED: ${failed} contrast tests failed WCAG requirements.`);
  process.exit(1);
} else {
  console.log('SUCCESS: All 13 token pairs pass WCAG 2.1 AA contrast requirements!');
  process.exit(0);
}
