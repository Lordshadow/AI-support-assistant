import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { processIncomingMessage } from '../src/bridge.js';
import { toQrSvg, writePairingQr } from '../src/qr.js';

test('forwards decrypted WhatsApp voice-note bytes and replies in the same chat', async () => {
  let request;
  let reply;
  const client = {
    async decryptMedia() { return 'data:audio/ogg;base64,' + Buffer.from('synthetic voice sample').toString('base64'); },
    async reply(...args) { reply = args; },
  };
  const result = await processIncomingMessage({
    id: 'msg-voice-1', from: '123@c.us', type: 'ptt', mimetype: 'audio/ogg; codecs=opus', body: '',
  }, client, {
    apiUrl: 'http://assistant/integrations/openwa/messages', sharedSecret: 'x'.repeat(40),
    fetch: async (url, options) => {
      request = { url, options };
      return { ok: true, async json() { return { status: 'processed', reply: 'Your order is on its way.' }; } };
    },
  });
  assert.equal(result.status, 'processed');
  assert.equal(request.url, 'http://assistant/integrations/openwa/messages');
  assert.equal(request.options.headers.authorization, `Bearer ${'x'.repeat(40)}`);
  const sent = JSON.parse(request.options.body);
  assert.equal(sent.type, 'ptt');
  assert.equal(sent.mime_type, 'audio/ogg; codecs=opus');
  assert.equal(Buffer.from(sent.audio_base64, 'base64').toString(), 'synthetic voice sample');
  assert.deepEqual(reply, ['123@c.us', 'Your order is on its way.', 'msg-voice-1']);
});

test('ignores own messages and group messages', async () => {
  const client = {};
  const config = { fetch: async () => { throw new Error('must not call API'); } };
  assert.deepEqual(await processIncomingMessage({ fromMe: true }, client, config), { ignored: true });
  assert.deepEqual(await processIncomingMessage({ fromMe: false, isGroupMsg: true }, client, config), { ignored: true });
});

test('rejects oversized decrypted audio before forwarding', async () => {
  const client = { async decryptMedia() { return `data:audio/ogg;base64,${Buffer.alloc(20 * 1024 * 1024 + 1).toString('base64')}`; } };
  await assert.rejects(processIncomingMessage({
    id: 'msg-too-large', from: '123@c.us', type: 'audio', mimetype: 'audio/ogg',
  }, client, { fetch: async () => assert.fail('must not forward oversized media') }), /20 MB limit/);
});

test('renders the pairing token into a scannable SVG matrix', () => {
  const svg = toQrSvg('openwa-test-pairing-token');
  assert.match(svg, /^<svg /);
  assert.match(svg, /<path d="M/);
  assert.match(svg, /shape-rendering="crispEdges"/);
});

test('writes the current pairing code as a PNG image', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'openwa-qr-test-'));
  try {
    const file = await writePairingQr('openwa-test-pairing-token', dir);
    const pngHeader = fs.readFileSync(file).subarray(0, 8);
    assert.deepEqual([...pngHeader], [137, 80, 78, 71, 13, 10, 26, 10]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
