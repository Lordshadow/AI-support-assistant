import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { handleWebhookRequest, processOpenWaEvent, verifyOpenWaSignature } from '../src/bridge.js';

const config = {
  assistantUrl: 'http://assistant/integrations/openwa/messages',
  assistantSecret: 'a'.repeat(40),
  webhookSecret: 'w'.repeat(32),
  apiUrl: 'http://openwa/api',
  apiKey: 'openwa-test-key',
  sessionId: 'session-123',
};

test('verifies OpenWA HMAC over the raw body in constant-time comparison', () => {
  const body = Buffer.from('{"event":"message.received"}');
  const signature = `sha256=${createHmac('sha256', config.webhookSecret).update(body).digest('hex')}`;
  assert.equal(verifyOpenWaSignature(body, signature, config.webhookSecret), true);
  assert.equal(verifyOpenWaSignature(body, `${signature}x`, config.webhookSecret), false);
  assert.equal(verifyOpenWaSignature(body, undefined, config.webhookSecret), false);
});

test('forwards OpenWA text and sends assistant reply with OpenWA REST API', async () => {
  const requests = [];
  const result = await processOpenWaEvent({
    event: 'message.received', sessionId: 'session-123', idempotencyKey: 'event-1',
    data: { id: 'msg-1', from: '919876543210@c.us', chatId: '919876543210@c.us', body: 'Where is my order?', type: 'text' },
  }, config, async (url, options) => {
    requests.push({ url, options });
    return requests.length === 1
      ? { ok: true, async json() { return { status: 'processed', reply: 'Please share your order number.' }; } }
      : { ok: true };
  });
  assert.deepEqual(result, { status: 'processed' });
  assert.equal(requests[0].url, config.assistantUrl);
  assert.equal(requests[0].options.headers.authorization, `Bearer ${config.assistantSecret}`);
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    message_id: 'msg-1', sender: '919876543210@c.us', type: 'chat', text: 'Where is my order?',
  });
  assert.equal(requests[1].url, 'http://openwa/api/sessions/session-123/messages/send-text');
  assert.equal(requests[1].options.headers['X-API-Key'], config.apiKey);
  assert.deepEqual(JSON.parse(requests[1].options.body), {
    chatId: '919876543210@c.us', text: 'Please share your order number.',
  });
});

test('ignores group, own, and non-message events', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls += 1; throw new Error('must not call services'); };
  assert.deepEqual(await processOpenWaEvent({ event: 'session.status' }, config, fetchImpl), { ignored: true });
  assert.deepEqual(await processOpenWaEvent({ event: 'message.received', data: { fromMe: true } }, config, fetchImpl), { ignored: true });
  assert.deepEqual(await processOpenWaEvent({ event: 'message.received', data: { isGroup: true } }, config, fetchImpl), { ignored: true });
  assert.equal(calls, 0);
});

test('rejects unsigned webhook before parsing or forwarding', async () => {
  const server = createServer((req, res) => void handleWebhookRequest(req, res, config));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const { port } = server.address();
    const response = await fetch(`http://127.0.0.1:${port}/webhooks/openwa`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{invalid',
    });
    assert.equal(response.status, 401);
  } finally {
    server.close();
  }
});

test('accepts correctly signed events and rejects malformed JSON', async () => {
  const server = createServer((req, res) => void handleWebhookRequest(req, res, config, async () => ({ ok: true, async json() { return {}; } })));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const { port } = server.address();
    const url = `http://127.0.0.1:${port}/webhooks/openwa`;
    const body = Buffer.from('{"event":"session.status"}');
    const signature = `sha256=${createHmac('sha256', config.webhookSecret).update(body).digest('hex')}`;
    const valid = await fetch(url, { method: 'POST', headers: { 'X-OpenWA-Signature': signature }, body });
    assert.equal(valid.status, 200);
    const invalid = await fetch(url, {
      method: 'POST', headers: { 'X-OpenWA-Signature': signature }, body: '{bad json',
    });
    assert.equal(invalid.status, 401);
  } finally {
    server.close();
  }
});
