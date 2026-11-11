import { createHmac, timingSafeEqual } from 'node:crypto';

const MAX_BODY_BYTES = 30 * 1024 * 1024;

export function verifyOpenWaSignature(rawBody, signature, secret) {
  if (typeof signature !== 'string' || !secret) return false;
  const expected = `sha256=${createHmac('sha256', secret).update(rawBody).digest('hex')}`;
  const actualBytes = Buffer.from(signature);
  const expectedBytes = Buffer.from(expected);
  return actualBytes.length === expectedBytes.length && timingSafeEqual(actualBytes, expectedBytes);
}

async function readBody(request) {
  const parts = [];
  let size = 0;
  for await (const part of request) {
    size += part.length;
    if (size > MAX_BODY_BYTES) throw Object.assign(new Error('Payload too large'), { statusCode: 413 });
    parts.push(part);
  }
  return Buffer.concat(parts);
}

function getAudioBase64(media) {
  if (!media || typeof media.data !== 'string') return undefined;
  const match = /^(?:data:[^;,]+;base64,)?([A-Za-z0-9+/]+={0,2})$/.exec(media.data);
  return match?.[1];
}

function splitMarkdownTableRow(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null;
  return trimmed.slice(1, -1).split('|').map((cell) => cell.trim());
}

function isMarkdownTableSeparator(line) {
  const cells = splitMarkdownTableRow(line);
  return cells?.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderMarkdownTable(lines, start) {
  const headers = splitMarkdownTableRow(lines[start]);
  if (!headers || !isMarkdownTableSeparator(lines[start + 1] || '')) return null;

  let end = start + 2;
  const records = [];
  while (end < lines.length) {
    const cells = splitMarkdownTableRow(lines[end]);
    if (!cells || cells.length !== headers.length) break;
    records.push(cells);
    end += 1;
  }
  if (!records.length) return null;

  const idIndex = headers.findIndex((header) => /^(order\s*id|id)$/i.test(header.replaceAll('*', '').trim()));
  const cardLines = records.map((record) => {
    const values = headers.map((header, index) => ({
      label: header.replaceAll('*', '').trim(),
      value: record[index].replaceAll('**', '').trim(),
    })).filter(({ value }, index) => value && index !== idIndex);
    const orderId = idIndex >= 0 ? record[idIndex].replaceAll('**', '').trim() : '';
    const lines = [orderId ? `*${orderId}*` : 'Order details'];
    for (const { label, value } of values) lines.push(`${label}: ${value}`);
    return lines.join('\n');
  });
  return { text: cardLines.join('\n\n'), nextIndex: end };
}

export function formatWhatsAppMessage(message) {
  if (typeof message !== 'string') return '';
  const lines = message.replace(/\r\n?/g, '\n').split('\n');
  const formatted = [];
  for (let index = 0; index < lines.length;) {
    const table = renderMarkdownTable(lines, index);
    if (table) {
      formatted.push(table.text);
      index = table.nextIndex;
      continue;
    }
    formatted.push(lines[index]
      .replace(/^\s{0,3}#{1,6}\s+(.+)$/, '*$1*')
      .replace(/^\s*[-+]\s+/, '• ')
      .replace(/\*\*(.+?)\*\*/g, '*$1*'));
    index += 1;
  }
  return formatted.join('\n').trim();
}

export async function processOpenWaEvent(event, config, fetchImpl = fetch) {
  if (event?.event !== 'message.received' || !event.data || typeof event.data !== 'object') {
    return { ignored: true };
  }
  if (!event.sessionId || event.sessionId !== config.sessionId) throw new Error('OpenWA event belongs to an unexpected session');
  const message = event.data;
  if (message.fromMe || message.isGroup) return { ignored: true };

  const messageId = String(message.id || event.idempotencyKey || '');
  const sender = String(message.chatId || message.from || '');
  if (!messageId || !sender || sender.endsWith('@g.us')) return { ignored: true };

  const type = String(message.type || 'text').toLowerCase();
  const payload = {
    message_id: messageId,
    sender,
    type: ['voice', 'audio', 'ptt'].includes(type) ? 'voice' : 'chat',
    text: typeof message.body === 'string' ? message.body : '',
  };
  if (payload.type === 'voice') {
    const audioBase64 = getAudioBase64(message.media);
    if (audioBase64) {
      payload.audio_base64 = audioBase64;
      payload.mime_type = String(message.media?.mimetype || 'audio/ogg').slice(0, 128);
    }
  }

  const assistantResponse = await fetchImpl(config.assistantUrl, {
    method: 'POST',
    headers: { authorization: `Bearer ${config.assistantSecret}`, 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });
  if (!assistantResponse.ok) throw new Error(`Assistant API returned HTTP ${assistantResponse.status}`);
  const result = await assistantResponse.json();
  if (result.reply && result.status !== 'duplicate_ignored') {
    const sendResponse = await fetchImpl(
      `${config.apiUrl}/sessions/${encodeURIComponent(event.sessionId)}/messages/send-text`,
      {
        method: 'POST',
        headers: {
          'X-API-Key': config.apiKey,
          'Idempotency-Key': String(event.idempotencyKey || messageId).slice(0, 256),
          'content-type': 'application/json',
        },
        body: JSON.stringify({ chatId: sender, text: formatWhatsAppMessage(result.reply) }),
        signal: AbortSignal.timeout(30_000),
      },
    );
    if (!sendResponse.ok) throw new Error(`OpenWA send failed with HTTP ${sendResponse.status}`);
  }
  return { status: result.status || 'processed' };
}

export async function handleWebhookRequest(request, response, config, fetchImpl = fetch) {
  if (request.method !== 'POST' || request.url !== '/webhooks/openwa') {
    response.writeHead(404).end();
    return;
  }
  try {
    const rawBody = await readBody(request);
    if (!verifyOpenWaSignature(rawBody, request.headers['x-openwa-signature'], config.webhookSecret)) {
      response.writeHead(401).end('Invalid OpenWA signature.');
      return;
    }
    const event = JSON.parse(rawBody.toString('utf8'));
    await processOpenWaEvent(event, config, fetchImpl);
    response.writeHead(200, { 'content-type': 'application/json' }).end('{"status":"accepted"}');
  } catch (error) {
    const status = error?.statusCode || (error instanceof SyntaxError ? 400 : 502);
    response.writeHead(status, { 'content-type': 'text/plain' }).end(status === 502 ? 'Webhook processing failed.' : 'Invalid webhook request.');
  }
}
