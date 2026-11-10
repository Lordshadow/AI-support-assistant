const MAX_AUDIO_BYTES = 20 * 1024 * 1024;

export async function processIncomingMessage(message, client, config) {
  if (!message || message.fromMe || message.isGroupMsg) return { ignored: true };
  const chatId = message.from;
  const messageId = typeof message.id === 'string' ? message.id : message.id?._serialized;
  if (!chatId || !messageId) return { ignored: true };

  const type = String(message.type || 'chat').toLowerCase();
  const payload = { message_id: messageId, sender: chatId, type, text: message.body || '' };
  if (type === 'audio' || type === 'ptt') {
    if (!message.mimetype) throw new Error('Incoming WhatsApp audio has no MIME type');
    const dataUrl = await client.decryptMedia(message);
    const match = /^data:([^;,]+);base64,([A-Za-z0-9+/=]+)$/.exec(dataUrl || '');
    if (!match) throw new Error('OpenWA returned an invalid media data URL');
    const audio = Buffer.from(match[2], 'base64');
    if (!audio.length || audio.length > MAX_AUDIO_BYTES) throw new Error('WhatsApp voice note exceeds the 20 MB limit');
    payload.mime_type = message.mimetype || match[1];
    payload.audio_base64 = audio.toString('base64');
  }

  const response = await config.fetch(config.apiUrl, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${config.sharedSecret}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`Assistant API returned HTTP ${response.status}`);
  const result = await response.json();
  if (result.reply) await client.reply(chatId, result.reply, messageId);
  return result;
}
