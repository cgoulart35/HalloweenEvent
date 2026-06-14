---
name: prod-down
description: Stop and remove the production Docker containers for The Long Night. Use when asked to take down, stop, shut down, or halt the production stack.
---

# Take down the production stack

Stops and removes both prod containers (`halloween-api-prod`, `halloween-webapp-prod`).

> ⚠️ **This stops the live service.** On the Pi, the site behind the Cloudflare tunnel will go down
> (visitors get a tunnel/connection error) until you bring it back with **`/prod-up`**. Game state
> is safe — it lives in Firebase (external), not in the containers — so nothing is lost.

## Steps

1. **Stop and remove the containers:**

   ```bash
   docker compose -f docker-compose-prod.yml down
   ```

2. **Verify nothing prod is still running:**

   ```bash
   docker compose -f docker-compose-prod.yml ps
   ```

   The list should be empty (no `halloween-api-prod` / `halloween-webapp-prod`). Report the result.

## Notes

- `down` removes the containers and the default network but **not** images or any data — there are
  no named volumes here, and game state is in Firebase. Bring the stack back with **`/prod-up`**.
- This does not affect the deploy watcher (`scripts/deploy-watcher.sh`); when a **new** image is
  published it will `pull` + `up -d` and bring the stack back on its own (see **Deployment** in CLAUDE.md). Because
  the watcher only acts on a new image, a stack left `down` stays down until then — use **`/prod-up`**
  to bring it back now.
- If you only need to cycle the containers, prefer `docker compose -f docker-compose-prod.yml restart`
  over a full down/up.
