import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { processIncomingMessage } from './bridge.js';
import { writePairingQr } from './qr.js';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const chromeCandidates = process.platform === 'win32'
  ? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe']
  : [];
const executablePath = process.env.OPENWA_CHROME_PATH || chromeCandidates.find((candidate) => fs.existsSync(candidate));
if (process.platform === 'win32') {
  const toolsDir = path.join(projectDir, '.tools');
  process.env.PATH = [toolsDir, process.env.PATH || ''].filter(Boolean).join(path.delimiter);
}
const openwa = await import('@open-wa/wa-automate');
const output = openwa.getCliOutputSink();
openwa.setCliOutputSink({
  write(entry) { output.write(entry); },
  status(update) { output.status(update); },
  qr(payload) {
    void writePairingQr(payload.qr, path.join(projectDir, '.session')).catch(() => {
      console.error('Could not save the QR image; use the QR shown in this terminal output.');
    });
    output.qr(payload);
  },
  ...(output.promptChoice ? { promptChoice: (...args) => output.promptChoice(...args) } : {}),
});
const { create } = openwa;

const apiUrl = process.env.ASSISTANT_OPENWA_URL || 'http://127.0.0.1:8000/integrations/openwa/messages';
const sharedSecret = process.env.OPENWA_SHARED_SECRET || '';
if (sharedSecret.length < 32) {
  throw new Error('Set OPENWA_SHARED_SECRET to a randomly generated value of at least 32 characters.');
}

const client = await create({
  sessionId: process.env.OPENWA_SESSION_ID || 'novaretail-support',
  userDataDir: process.env.OPENWA_USER_DATA_DIR || './.session',
  headless: true,
  ...(executablePath ? { executablePath } : {}),
  ...(process.env.OPENWA_NO_SANDBOX === 'true' ? { chromiumArgs: ['--no-sandbox'] } : {}),
  qrTimeout: 0,
  browser: { cacheDirectory: path.join(projectDir, '.browser-cache') },
});
fs.rmSync(path.join(projectDir, '.session', 'pairing-qr.svg'), { force: true });
fs.rmSync(path.join(projectDir, '.session', 'pairing-qr.png'), { force: true });

console.log('OpenWA session is ready. Incoming direct messages are enabled.');
client.onMessage(async (message) => {
  try {
    await processIncomingMessage(message, client, { apiUrl, sharedSecret, fetch });
  } catch (error) {
    // Do not write message content, phone numbers, or decrypted audio to logs.
    console.error(`OpenWA message processing failed (${error?.name || 'Error'}).`);
  }
});

let stopping = false;
async function stop(signal) {
  if (stopping) return;
  stopping = true;
  await client.stop(signal);
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => void stop(signal));
