import { createServer } from 'node:http';
import { handleWebhookRequest } from './bridge.js';

const config = {
  assistantUrl: process.env.ASSISTANT_OPENWA_URL || 'http://127.0.0.1:8000/integrations/openwa/messages',
  assistantSecret: process.env.OPENWA_SHARED_SECRET || '',
  webhookSecret: process.env.OPENWA_WEBHOOK_SECRET || '',
  apiUrl: (process.env.OPENWA_API_URL || 'http://127.0.0.1:2785/api').replace(/\/$/, ''),
  apiKey: process.env.OPENWA_API_KEY || '',
  sessionId: process.env.OPENWA_SESSION_ID || '',
};

for (const [name, value, minimum] of [
  ['OPENWA_SHARED_SECRET', config.assistantSecret, 32],
  ['OPENWA_WEBHOOK_SECRET', config.webhookSecret, 16],
  ['OPENWA_API_KEY', config.apiKey, 1],
  ['OPENWA_SESSION_ID', config.sessionId, 1],
]) {
  if (value.length < minimum) throw new Error(`Set ${name} (minimum length ${minimum}).`);
}

const server = createServer((request, response) => {
  void handleWebhookRequest(request, response, config).catch(() => {
    if (!response.headersSent) response.writeHead(502, { 'content-type': 'text/plain' });
    response.end('OpenWA webhook processing failed.');
  });
});
const port = Number(process.env.OPENWA_WEBHOOK_PORT || 2786);
server.listen(port, '0.0.0.0', () => console.log(`OpenWA webhook adapter listening on port ${port}.`));

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => server.close(() => process.exit(0)));
}
