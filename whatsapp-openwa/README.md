# OpenWA support assistant adapter

This small Node.js adapter connects the support assistant to the `rmyndharis/OpenWA` REST gateway. OpenWA delivers signed `message.received` webhooks to this adapter. The adapter verifies the raw-body HMAC, forwards a normalized request to the assistant's authenticated integration endpoint, then sends the assistant reply through OpenWA's `send-text` API.

## Configure

1. Deploy OpenWA using its [official setup guide](https://github.com/rmyndharis/OpenWA#quick-start) and start a session. OpenWA's API/dashboard is normally at `http://localhost:2785`; create or use an operator API key allowed to send messages in that session.
2. Set these values in the support project's root `.env` (use independent randomly generated secrets; do not commit them):
   - `OPENWA_SHARED_SECRET`: at least 32 characters; authenticates the adapter to the support assistant.
   - `OPENWA_WEBHOOK_SECRET`: at least 16 characters; OpenWA signs webhook deliveries with it.
   - `OPENWA_API_URL`: OpenWA API base, including `/api` (for example `http://127.0.0.1:2785/api`).
   - `OPENWA_API_KEY`: OpenWA operator key with send permission.
   - `OPENWA_SESSION_ID`: the session ID linked to WhatsApp.
   - `ASSISTANT_OPENWA_URL`: `http://127.0.0.1:8000/integrations/openwa/messages` for a local assistant API.
3. Start the adapter with Node.js 22.21.1 or newer:

   ```powershell
   cd whatsapp-openwa
   npm ci
   npm test
   npm start
   ```

   The adapter listens at `http://0.0.0.0:2786/webhooks/openwa` by default (`OPENWA_WEBHOOK_PORT` changes the port). If OpenWA runs in Docker, use a callback URL reachable from that container, such as `http://host.docker.internal:2786/webhooks/openwa` on Docker Desktop. Keep the callback private to the OpenWA host/network.
4. In OpenWA's Dashboard, open the linked session's **Webhooks** and add that callback URL, event `message.received`, and the exact `OPENWA_WEBHOOK_SECRET` from the support project's environment. Or use its API:

   ```sh
   curl -X POST "$OPENWA_API_URL/sessions/$OPENWA_SESSION_ID/webhooks" \
     -H "X-API-Key: $OPENWA_API_KEY" -H "Content-Type: application/json" \
     -d '{"url":"http://host.docker.internal:2786/webhooks/openwa","events":["message.received"],"secret":"<same OPENWA_WEBHOOK_SECRET>"}'
   ```

5. Send a direct text from a separate test account. The adapter ignores groups and messages sent by the linked account. Confirm the assistant reply arrives in that same chat.

## Voice notes

The assistant API can transcribe audio bytes forwarded through its internal route. OpenWA's webhook only includes usable audio when its message event carries `data.media.data`; without those bytes the assistant safely asks the customer to type the request. Text messages work independently of speech-to-text configuration.

## Security and operations

- Use a dedicated linked number and review OpenWA's [current account-risk and compliance guidance](https://github.com/rmyndharis/OpenWA#before-you-connect-a-number--please-read). It is an unofficial WhatsApp Web gateway and can lead to account restrictions; use Meta's Cloud API for regulated or high-risk customer communications.
- Keep the OpenWA API/dashboard and the webhook adapter private; never publish the API key or webhook secret.
- The adapter verifies `X-OpenWA-Signature` over the exact raw request bytes before parsing, bounds incoming body size, and does not log message bodies, phone numbers, or media.
- Run the adapter under a process supervisor and monitor its logs. OpenWA retries unsuccessful webhook deliveries.
