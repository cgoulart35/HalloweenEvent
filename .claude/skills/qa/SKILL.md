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

`scripts/qa.sh` wraps all of this deterministically: it always sets `IMAGE_TAG=qa` and
`EVENT_ROOT=qa-halloween-event`, builds the api image on first use, and runs the lifecycle
subcommand in a one-off container. Pass the subcommand as args; set the email override (and,
optionally, the gift-card trio) via env vars. Replace `you@example.com` with the user's real address:

```bash
QA_EMAIL=you@example.com bash scripts/qa.sh SUBCOMMAND   # e.g. status, "open --minutes 30", tick
bash scripts/qa.sh build                                 # rebuild after any code change
```

`QA_EMAIL` sets `EMAIL_OVERRIDE_RECIPIENT` so any mail goes only to that address; you can omit it
only for read-only `status`/`wipe`.

**`IMAGE_TAG=qa` is the safety rail and is baked into the script** (build *and* run). QA must exercise
the **current checkout's code**, which means building locally — but a local build of the
compose-default `:latest` image changes its image ID, which the deploy-watcher reads as a newly
published image and answers with `deploy.sh` (hard `git checkout -f master && git reset --hard
origin/master` + redeploy), **wiping uncommitted work within one poll interval**. The `:qa` tag is
invisible to its detector (which only compares `:latest`), and the script `run`s under the same tag so
it uses the locally-built image instead of trying to pull `:qa` from GHCR. Because the build is `:qa`
(not `:latest`) it reads your **working tree** without triggering the watcher, so **committing first
isn't required** — it's an optional safety net that protects uncommitted work only if something *else*
fires the watcher mid-session (a stray `:latest` build or a concurrent merge to `master`).

The script auto-builds the api image on first use and never starts the prod server (it overrides the
entrypoint to a one-off script run, so the live API/reconcile loop never runs against real data). Run
`bash scripts/qa.sh build` to rebuild after a code change so QA reflects it.

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

## Gift-card prize QA (optional)

The optional yearly prize (`GIFT_CARD_LABEL` / `GIFT_CARD_CODE` / `GIFT_CARD_YEAR`, all in `api.env`)
is gated by `queries.getActiveGiftCard(year)`: active **only** when all three are set **and**
`GIFT_CARD_YEAR` equals the sandbox season's year (`currentEventYear()` — pass the **current** year),
else fully dormant. It has just **two states**; pick the one you need to QA (you don't have to test
both unless you're specifically validating the prize feature). Use a **fake QA label/code, never a
real card.** `open`/`status` print `gift-card prize: ACTIVE …` or `dormant …` so you can confirm the
env took effect before testing.

- **Prize ON** — add the trio to the `-e` flags (command pattern) *or*, for browser mode, to
  `api.env` (see below). Expect: the **welcome** email's rules line ends "…wins — and claims this
  season's prize: <label>."; the **season-start** email shows a prize line (label only, **no code**);
  at close the **results** emails name the claimant to everyone, and **exactly one** winner's email
  carries the redemption-code box. Verify only one email in your inbox contains the code.
  ```bash
  GIFT_CARD_LABEL='QA $5 gift card' GIFT_CARD_CODE=QA-TESTCODE GIFT_CARD_YEAR=<season year> \
    QA_EMAIL=you@example.com bash scripts/qa.sh SUBCOMMAND
  ```
- **Prize OFF** — simply **omit** the three `GIFT_CARD_*` vars. The script always passes them as
  explicit `-e` flags (blank when unset), so a populated real `api.env` can't leak the prize in
  either. Expect: no prize line in welcome or season-start, and **no** code or prize wording in any
  results email. `status` shows `dormant`.
  ```bash
  QA_EMAIL=you@example.com bash scripts/qa.sh SUBCOMMAND
  ```

To validate **both** states in one session (e.g. when the prize is a new feature), run the full flow
once per state and `wipe` in between. For browser mode (below), put the trio in `api.env` for the ON
state and **remove those three lines** (then rebuild/up) for the OFF state — the teardown grep already
covers `GIFT_CARD`.

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
   Add to **`app.env`**: `EVENT_ROOT=qa-halloween-event` (must match). *To QA the prize ON*, also add
   the gift-card trio to `api.env` (`GIFT_CARD_LABEL=QA $5 gift card`, `GIFT_CARD_CODE=QA-TESTCODE`,
   `GIFT_CARD_YEAR=<season year>`) — a fake code, never a real one; leave them out for the prize-OFF run.
2. `IMAGE_TAG=qa docker compose -f docker-compose-prod.yml up -d --build` (the `:qa` tag keeps this
   local build invisible to the deploy-watcher — see the command-pattern note above; committing
   first is an optional safety net, not required).
3. Drive the lifecycle with the command pattern above and test in the browser on the real domain.
4. **Tear down — do all of these:**
   - `wipe` the sandbox (command pattern above).
   - `docker compose -f docker-compose-prod.yml down`
   - **Remove** the lines you added from `api.env` and `app.env`, then **verify they're gone**:
     ```bash
     grep -nE 'EVENT_ROOT|EMAIL_OVERRIDE_RECIPIENT|GIFT_CARD' api.env app.env
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
