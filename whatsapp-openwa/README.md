# OpenWA WhatsApp bridge

This companion process links a WhatsApp account through OpenWA, decrypts incoming direct audio/PTT messages, forwards the bytes to the support assistant's authenticated internal endpoint, and sends the resulting assistant reply to the same chat.

## Local setup

1. Use Node.js 22.21.1 or newer, the system `zstd` command (Windows workspace setup includes a local ignored `.tools/zstd.exe`), and a WhatsApp account with access to **Linked devices**.
2. Set the same strong random value (at least 32 characters) in the root `.env` as `OPENWA_SHARED_SECRET`. Inject it securely into the API and OpenWA process; do not commit it.
3. Start the support API with the secret loaded. For a host process, set `ASSISTANT_OPENWA_URL=http://127.0.0.1:8000/integrations/openwa/messages`.
4. In this directory run `npm install`, then `npm test`, then `npm start`.
5. Scan the QR code printed by OpenWA using WhatsApp → **Linked devices** → **Link a device**. The session is persisted in `whatsapp-openwa/.session`; keep it private and backed up securely.
6. Send a short text message and then a voice note from a separate test account. Check that the assistant responds in that chat. Do not use customer records for the smoke test.

The bridge ignores groups and messages sent by the linked account. Decrypted audio is held in memory only, limited to 20 MB, and is not logged or written to disk. The Python service requires the shared bearer secret, deduplicates message IDs in memory, and transcribes with Groq Whisper when `GROQ_API_KEY` is configured. A production process without Groq is configured to refuse voice transcription rather than return simulated text.

## Operations

- Keep the process online and persist `.session` across restarts. Verify the session is ready after deployment; a running Node process alone does not prove WhatsApp is linked.
- Keep the API endpoint private to the bridge network and do not publish an OpenWA control/API port.
- Provide a process supervisor, restart policy, memory headroom for Chromium, secret injection, and log/health monitoring before production.
- Re-authenticate from the linked device if WhatsApp invalidates the session. Never delete the profile as a routine troubleshooting step.

OpenWA owns a browser session connected to WhatsApp Web. This is a third-party automation route, separate from the official Meta Cloud API integration already in the backend; review applicable WhatsApp terms, account restrictions, and OpenWA's license requirements for the features/account before using it with customers.
