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
- This does not affect the GitProjectUpdateHandler webhook service; a subsequent push-triggered
  deploy will run `down` then `up -d --build` again on its own (see `/preflight`).
- If you only need to cycle the containers, prefer `docker compose -f docker-compose-prod.yml restart`
  over a full down/up.
