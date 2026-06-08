---
name: prod-logs
description: Show status and tail recent logs for the running production containers (API and/or web app). Use to check whether prod is up and healthy, or to inspect recent output when debugging the live stack.
argument-hint: "[api|webapp] [tail-count]"
---

# Production status & logs (read-only)

Shows container status and recent log output for the prod stack. Safe and read-only — it never
starts, stops, or changes anything.

**Arguments** (from `$ARGUMENTS`, both optional):
- A service selector: `api` → `halloween-api-prod`, `webapp` (or `web`/`app`) → `halloween-webapp-prod`.
  Omit to show **both**.
- A number → how many log lines to tail (default **50**).

So `/prod-logs api 200` tails 200 lines of the API; `/prod-logs` shows status + 50 lines of each.

## Steps

1. **Always start with status:**

   ```bash
   docker compose -f docker-compose-prod.yml ps
   ```

   If a service isn't listed/`running`, say so — the user may need **`/prod-up`**.

2. **Tail the requested logs.** Substitute the tail count (`N`, default 50) and pick the service(s):

   - Both (default):
     ```bash
     docker compose -f docker-compose-prod.yml logs --tail=50 halloween-api-prod
     docker compose -f docker-compose-prod.yml logs --tail=50 halloween-webapp-prod
     ```
   - API only:
     ```bash
     docker compose -f docker-compose-prod.yml logs --tail=200 halloween-api-prod
     ```
   - Web app only:
     ```bash
     docker compose -f docker-compose-prod.yml logs --tail=200 halloween-webapp-prod
     ```

3. **Summarize for the user**: whether each container is up, and anything notable in the logs
   (tracebacks, repeated errors, the 5-minute `reconcileEventLifecycle` heartbeat on the API,
   request errors on the web app). Quote the relevant lines.

## Notes

- **Do not** stream with `-f`/`--follow` by default — it blocks indefinitely. Only use it if the
  user explicitly wants a live stream, and warn them it won't return on its own.
- To narrow to a time window, add `--since=10m` (or `--since=1h`) to a `logs` command.
