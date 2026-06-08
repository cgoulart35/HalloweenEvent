---
name: qa
description: Drive the isolated QA sandbox season lifecycle for The Long Night (open / tick / close / restart / status / wipe) and optionally browser-test it, without ever touching real game data or emailing real players. Use for manual end-to-end QA of signup, fights, results emails, and the season rollover.
argument-hint: "[open|tick|close|restart|status|wipe] [--minutes N]"
---

# Drive the QA sandbox lifecycle

`scripts/qa_lifecycle.py` sets up an **isolated** sandbox season so you can exercise the **real** app
on a short, fast window. It isolates itself purely by switching the **data node**: every read / write
/ archive goes to `qa-halloween-event*` instead of the prod `halloween-event*` nodes. The script
**refuses to run** unless `EVENT_ROOT` is overridden away from prod, so real data can't be touched.

> 🔒 **Safety invariants — keep these true:**
> - `EVENT_ROOT` must be a sandbox node (`qa-halloween-event`), **never** `halloween-event`.
> - The commands below pass `EVENT_ROOT` (and the email override) with `docker compose run -e …`, so
>   the **real `api.env` / `app.env` are never edited** — except in the optional *Browser testing*
>   section, which is the only path that touches them and **requires reverting afterward**.
> - Set `EMAIL_OVERRIDE_RECIPIENT` to your own address so any mail goes only to you. If the user
>   hasn't given an address, ask for it before running anything that sends mail (`tick` after a
>   season opens, or browser signups). For read-only `status`/`wipe` you can omit it.

**Arguments** (`$ARGUMENTS`): first token = subcommand; `--minutes N` applies to `open`/`restart`
(default 15). With no subcommand, run **`status`** and show the user the options.

## The command pattern (run this — no stack needed, no secrets edited)

Each Bash call is independent (shell functions don't persist), so use the **full command every time**,
swapping the part after `qa_lifecycle.py`. Replace `you@example.com` with the user's real address:

```bash
docker compose -f docker-compose-prod.yml run --rm --no-deps \
  -e EVENT_ROOT=qa-halloween-event \
  -e EMAIL_OVERRIDE_RECIPIENT=you@example.com \
  --entrypoint sh halloween-api-prod \
  -c "python scripts/qa_lifecycle.py SUBCOMMAND"
```

If the api image isn't built yet, build it once first (this does **not** start the prod server — the
command above overrides the entrypoint to a one-off script run, so the live API/reconcile loop never
runs against real data):

```bash
docker compose -f docker-compose-prod.yml build halloween-api-prod
```

### Subcommands (replace `SUBCOMMAND` above)

| Subcommand | What it does |
| --- | --- |
| `status` | Show sandbox `meta`, whether the window is open, the sandbox nodes, and past-player emails. **Safe; start here.** |
| `open --minutes 30` | Seed a couple of fake past seasons, then open a **fresh empty** season **now** for 30 min. Then sign up / fight in the browser. |
| `tick` | Run the real `reconcileEventLifecycle` once so any **due email fires immediately** (the live app does this every 5 min). Fires the season-start blast once a season is open. |
| `close` | Force the current window **closed now** (sets `closeTime` → now) without resetting players, so the next `tick` sends the **results** email. |
| `restart --minutes 30` | **Archive** the current season to `qa-halloween-event-{year}`, then open a fresh one **now** for 30 min (exercises rollover). |
| `wipe` | **Delete all** `qa-halloween-event*` sandbox nodes. Run this when done. |

### Typical full E2E flow

1. `open --minutes 30` → in a browser on the live domain (now serving the sandbox, see below) sign
   up (welcome + QR email), then fight another account.
2. `tick` → fires the season-start email.
3. `close` then `tick` → fires the results email immediately.
4. `restart --minutes 30` → archive + fresh season.
5. `status` to inspect at any point; `wipe` when finished.

Gating (open vs. `ended.html`) reflects the window instantly — no `tick` needed for that.

## One-time Firebase setup

The sandbox `qa-halloween-event/users` node needs the same `.indexOn: ["email"]` rule prod has on
`halloween-event/users` (add it once in the Firebase console). Without it the email-lookup query
behind signup/login returns **HTTP 400**. If signup/login 400s, this is why — tell the user.

## Browser testing (optional — the ONLY path that edits secrets; revert after!)

The `status/open/tick/close/restart/wipe` commands above need no running stack. To actually click
through the **web UI** against the sandbox, the running containers must see `EVENT_ROOT`, which means
temporarily editing the env files. This is the riskiest step — **if `EVENT_ROOT` is left in
`api.env`, prod will serve QA data.** Follow this exactly:

1. Add to **`api.env`**: `EVENT_ROOT=qa-halloween-event` and `EMAIL_OVERRIDE_RECIPIENT=you@example.com`.
   Add to **`app.env`**: `EVENT_ROOT=qa-halloween-event` (must match).
2. `docker compose -f docker-compose-prod.yml up -d --build`
3. Drive the lifecycle with the command pattern above and test in the browser on the real domain.
4. **Tear down — do all of these:**
   - `wipe` the sandbox (command pattern above).
   - `docker compose -f docker-compose-prod.yml down`
   - **Remove** the lines you added from `api.env` and `app.env`, then **verify they're gone**:
     ```bash
     grep -nE 'EVENT_ROOT|EMAIL_OVERRIDE_RECIPIENT' api.env app.env
     ```
     This must print **nothing**. If it prints anything, delete those lines and check again before
     leaving — otherwise the next prod boot runs against the QA node / redirects all mail.
   - Bring real prod back with **`/prod-up`**.

> Note: QA and prod can't run at the same time (shared domain/host) — QA replaces prod for the
> session. Never `git add` `api.env` / `app.env` (they're gitignored; keep it that way).

## Report

After each run, summarize what changed: quote the `meta before/after` from `tick`, the
open/close times from `open`/`restart`, and the node list / `OPEN?` flag from `status`. Confirm the
sandbox node in use was `qa-halloween-event` (the script prints it on every run).
