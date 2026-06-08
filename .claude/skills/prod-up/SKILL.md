---
name: prod-up
description: Build and start the two production Docker containers (API + web app) for The Long Night on this host. Use when asked to bring up, start, boot, rebuild, or restart the production stack.
---

# Bring up the production stack

Builds and starts both prod containers with `docker-compose-prod.yml`:
`HalloweenEventApi_prod` (service `halloween-api-prod`, host port **5007** → HTTP) and
`HalloweenEventWebApp_prod` (service `halloween-webapp-prod`, host port **5009** → HTTPS, self-signed).

> ⚠️ **This is the live production stack.** On the Raspberry Pi (this deploy target) these are the
> containers real players hit through the Cloudflare tunnel. The API uses the **real** Firebase node
> (`halloween-event`) and **real** SMTP, and its lifecycle reconcile loop can send real emails near a
> season boundary. To exercise the app **without** touching real data or mailing real people, use
> **`/qa`** instead.
>
> Normal deploys happen automatically via the GitProjectUpdateHandler webhook (see `/preflight`). Run
> this skill for a deliberate manual (re)start of the stack on this host.

## Steps

1. **Confirm the secrets are present** (the compose file mounts/loads all three; without them the
   build or boot fails):

   ```bash
   ls -1 api.env app.env serviceAccountKey.json
   ```

   If any is missing, stop and tell the user — on the Pi these are copied in from the
   GitProjectUpdateHandler Shared dir at deploy time; do not fabricate them.

2. **Build and start** (recreates both containers; `-d` = detached):

   ```bash
   docker compose -f docker-compose-prod.yml up -d --build
   ```

3. **Verify both are up:**

   ```bash
   docker compose -f docker-compose-prod.yml ps
   ```

   Both services should show state `running`/`Up`. Then sanity-check the logs:

   ```bash
   docker compose -f docker-compose-prod.yml logs --tail=20 halloween-api-prod
   docker compose -f docker-compose-prod.yml logs --tail=20 halloween-webapp-prod
   ```

   Healthy startup looks like each Flask/werkzeug app reporting it's serving (API on `:5004`
   inside the container → published as **5007**; web app on `:5004` → **5009** HTTPS). Report any
   traceback (common causes: a missing/blank required env var, or a bad `FIREBASE_CONFIG_JSON`).

## Notes

- **Quick restart without rebuilding** (e.g. after nothing but a container hiccup):
  `docker compose -f docker-compose-prod.yml restart`. Use the full `up -d --build` above whenever
  code changed.
- Local URLs once up: API `http://localhost:5007`, web app `https://localhost:5009` (self-signed
  cert — browser warning is expected).
- `restart: unless-stopped` is set, so the containers come back on reboot/crash on their own.
- To stop the stack, use **`/prod-down`**. To inspect a running stack, use **`/prod-logs`**.
