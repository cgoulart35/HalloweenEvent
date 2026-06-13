# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"The Long Night" — a Halloween party game. Each participant gets a personal QR code; players
scan each other's codes to trigger a randomized "fight" (winner +2 pts, loser +1, each pair may
fight only once). State lives in a Firebase Realtime Database. It runs as **two Docker containers**
on a Raspberry Pi 4 (aarch64), Python 3.12.

## Architecture

Two independent Flask apps share `src/common/`:

- **API** — `src/api/api.py`, port **5007** (HTTP). Flask-RESTful resources: `Scoreboard` (GET),
  `Fight` (POST), `Users` (POST=register / PUT=update), `Login` (POST). bcrypt for passwords. All
  game/data logic is in `src/common/queries.py`.
- **Web app** — `src/app/app.py` + `src/app/views.py`, port **5009** (HTTPS, self-signed). A Flask
  Blueprint (`views`) that renders Jinja templates and calls the API over HTTP (`API_HOST`). Sessions
  are **in-memory server-side** (`openSessions` dict in `views.py`), not signed cookies; a background
  job expires them. QR scanning (`/scan/`) decodes uploads with `cv2.QRCodeDetector`.

Both processes run Flask's built-in werkzeug server via `app.run(...)` — intentional for a small app
behind a Cloudflare tunnel. **Prod** launches it directly (`python3 src/...`); only the **dev** Docker
target wraps it in `debugpy` (see the Dockerfile entrypoints). `PYTHONPATH=/HalloweenEvent`, set in
both images, keeps `src` importable under the plain-`python3` prod launch.

`src/common/`:
- `firebase.py` — `FirebaseService`: thin facade over **firebase-admin** Realtime DB
  (`get/set/push/update/remove/query`, plus `listRootKeys()` via a shallow read for enumerating the
  yearly archive nodes). Reads return a `_Result` exposing `.val()` (Pyrebase-shaped). Init from
  `FIREBASE_CONFIG_JSON` (JSON containing `serviceAccount` + `databaseURL`). Live data lives under
  `{EVENT_ROOT}/users/{userKey}`, `{EVENT_ROOT}/scoreboard`, and `{EVENT_ROOT}/meta`; finished
  seasons are archived to `{EVENT_ROOT}-{year}`.
- `queries.py` — game logic, Firebase access, and **email** (welcome email with embedded QR in
  `addParticipant`; results emails in `emailResults`). `styledEmail()` wraps email bodies in the
  app's theme. `resolveRecipients()` redirects all mail to `EMAIL_OVERRIDE_RECIPIENT` when set (QA).
  Also the optional yearly **gift-card prize**: `getActiveGiftCard(year)` is the single gate —
  active only when `GIFT_CARD_LABEL`/`GIFT_CARD_CODE`/`GIFT_CARD_YEAR` (api.env) are all set
  **and** the year exactly matches the season being emailed about, otherwise the prize is fully
  dormant (so a stale entry can't leak into a later season). When active, the label is announced
  in the welcome + season-start emails and the code goes to **exactly one** winner's results
  email; `pickGiftCardWinner` breaks top-score ties deterministically (most fight wins → earliest
  to reach final score → earliest signup via chronological push keys), deliberately stateless so
  the lifecycle's retry-the-whole-batch failure mode can never award the code twice.
- `eventstate.py` — the seasonal calendar: `EVENT_ROOT` (DB node, env-overridable for sandboxing),
  `eventIsOpen(openTime, closeTime, now)` (the single source of truth for whether the game is
  currently playable — a **two-sided** window check), `getCurrentSeasonWindow()` (reads
  `{EVENT_ROOT}/meta` `openTime`/`closeTime` with a calendar fallback), and the pure date helpers
  (`season{Open,Close}Datetime`, `season{Open,Close}String`, `currentEventYear`). The Oct 1 → Nov 1
  rule (`SEASON_OPEN`/`SEASON_CLOSE`) is what fills `meta` in prod.
- `lifecycle.py` — **API-only** self-restarting season engine: `ensureProvisioned`, the interval
  `reconcileEventLifecycle` heartbeat, `rolloverEvent` (archive + reset), `sendSeasonStartEmail`,
  `getAllPastParticipantEmails`.
- `security.py` — shared, dependency-free helpers: `constantTimeEquals` (API-key compare),
  `verifyTurnstile` (Cloudflare siteverify; returns `True`/bypasses when the secret is blank, for
  local/QA), `escapeHtml` (markupsafe wrapper for the XSS fix). Safely importable (no Flask/Firebase
  init at import), so it's unit-tested in `tests/test_security.py`.

### Auth & hardening (web↔API and the web forms)

The API requires a shared secret on every request: header `X-API-Key` matched (constant-time) against
`API_KEY` via a `@before_request` gate; the web app sends it on all calls (`_apiHeaders()`);
`/favicon.ico` and `OPTIONS` are exempt. CORS is restricted to `WEBAPP_HOST`. The web app adds
Cloudflare **Turnstile** on signup/login (verified server-side; **disabled when `TURNSTILE_SECRET_KEY`
is blank**), per-session **CSRF** tokens on its POST forms (`/scan/` and the QR `GET /fight/` are
exempt — `SameSite=Lax` covers the latter), `Secure`/`HttpOnly`/`SameSite=Lax` session cookies, and
`escapeHtml()` on user-supplied names everywhere they're built into HTML or email. `PUT /users/`
requires the current password (bcrypt-verified) before any credential change.

### Event lifecycle (read before touching season/scheduler/gating code)

The game is **seasonal and self-restarting** — no env cutoff, no manual yearly action. The active
window is **Oct 1 00:00 → Nov 1 00:00** by rule (`SEASON_OPEN`/`SEASON_CLOSE` in `eventstate.py`).
The current season's window + identity + which emails have gone out live in the DB at
`{EVENT_ROOT}/meta` = `{year, openTime, closeTime, resultsEmailed, startEmailed}`, so the schedule
auto-advances and survives restarts. (Storing the window as data — rather than recomputing it — also
lets QA drop a short window into a **sandbox** `meta` and drive the real app; see Manual QA.)

- **Gating** (both apps): playable iff `eventIsOpen(*getCurrentSeasonWindow())`. Pre-season **and**
  post-season are closed. Web app `@views.before_request` serves `ended.html`; API `Fight.post` /
  `Users.post` return 403; `Scoreboard.get` / `Login` stay open.
- **Lifecycle driver**: the **API** runs `lifecycle.reconcileEventLifecycle` on a 5-min interval
  (single writer). It is idempotent/restart-safe (re-derives state from `meta` + `now`, guarded by
  the `resultsEmailed` / `startEmailed` flags — nothing depends on hitting an exact instant):
  - at **close** (Nov 1): emails final results once;
  - at the next **open** (Oct 1): archives the finished season to `{EVENT_ROOT}-{year}`, opens a
    fresh empty season, and emails all past players (`sendSeasonStartEmail`).
  Archiving happens **at reopen, not at close**, so the off-season `ended.html` keeps showing the
  finished season's standings.

The apps **must not** self-terminate (they previously did `os.system("kill -15 1")`); they stay up so
the containers can auto-restart (`restart: unless-stopped`).

## Skills (`/commands`)

Repo skills live in `.claude/skills/<name>/SKILL.md` (tracked in git) and are invokable as `/<name>`;
all are also auto-invokable (Claude loads one when a request matches its `description`). They wrap the
raw commands documented below with the right flags, safety rails, and verification — prefer them over
hand-running docker/compose:

- **`/prod-up`** — build + start the two prod containers, then verify `ps` + logs.
- **`/prod-down`** — stop/remove the prod containers (game state is safe in Firebase, not the containers).
- **`/prod-logs [api|webapp] [N]`** — read-only status + tail logs (never `-f`/follow by default).
- **`/test [-k … | path | audit]`** — run pytest (or `pip-audit`) the ephemeral-container way.
- **`/qa [open|tick|close|restart|status|wipe] [--minutes N]`** — drive the isolated QA sandbox
  lifecycle; isolates via `EVENT_ROOT=qa-halloween-event` passed with `docker compose run -e …`, so it
  never touches real data and (in its core path) never edits `api.env`/`app.env`. Local builds use
  `IMAGE_TAG=qa` (watcher-safe); pass `GIFT_CARD_*` to QA the prize ON, omit/blank to QA it OFF.
- **`/preflight`** — pre-flight checks, then hand the trigger (merge to `master`) to the user, then
  post-deploy verify; it **never** pushes, merges, or deploys on its own (deploy = merge → CI builds
  & pushes the image → the in-repo watcher pulls it; see Deployment).

## Common commands

All commands assume repo root and that `api.env`, `app.env`, and `serviceAccountKey.json` exist
locally (see Deployment).

**Build + run prod locally** (recreates the two prod containers):
```
docker compose -f docker-compose-prod.yml up -d --build
docker compose -f docker-compose-prod.yml ps
docker compose -f docker-compose-prod.yml logs --tail=20 halloween-api-prod
```
Dev stack (`docker-compose-dev.yml`, ports 5006/5008) uses `debugpy --wait-for-client`, so the
container blocks until a debugger attaches — not for casual running.

**Tests** — pytest is **not** baked into the images (only `requirements.txt` is installed;
`requirements-dev.txt` has pytest + pip-audit). Run in an ephemeral container against the **webapp**
image, which is the only one that installs `libgl1` (required by `cv2`). The `IMAGE_TAG=test` prefix
is **required on this host**: building under the compose-default `:latest` name changes the local
image ID, which the deploy-watcher reads as a newly published image — it responds with `deploy.sh`
(hard `git checkout -f master` + `git reset --hard`, wiping uncommitted work) within one poll
interval. A `:test`-tagged build is invisible to the watcher (its detector only compares `:latest`):
```
IMAGE_TAG=test docker compose -f docker-compose-prod.yml build halloween-webapp-prod
IMAGE_TAG=test docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
  halloween-webapp-prod -c "pip install -q -r requirements-dev.txt && python -m pytest -q"
```
Single test: append `tests/test_queries.py::test_perform_fight_happy_path` (or `-k <name>`) to pytest.
`tests/` deliberately exercises only safely-importable code (`queries`, `eventstate`, `lifecycle`, `security`,
the dep set, the cv2 QR round-trip); `api.py`/`app.py` aren't imported because they run `app.run()` /
Firebase init at import time. `test_lifecycle.py` drives provision/rollover/reconcile with a tiny
in-memory `FakeDB` and an injected `now`, mirroring the monkeypatch style in `test_queries.py`.

**Dependency CVE audit:** `pip-audit` (in `requirements-dev.txt`), run the same ephemeral way.

**Manual E2E QA:** QA reuses the **real** environment (same domain, Firebase project, SMTP — so
QR/email links are the real domain and work on a phone) and isolates itself purely by switching the
**data node**. The domain serves prod *or* QA at a time, so QA runs in place of prod with the real
`api.env`/`app.env` plus `EVENT_ROOT=qa-halloween-event` (**required** — all reads/writes/archives
hit `qa-*` nodes; real data untouched) and, optionally, `EMAIL_OVERRIDE_RECIPIENT=<you>` (routes the
season-start blast to you and guards against mailing a real address). Use `scripts/qa_lifecycle.py`
to drive the season window on the real clock. Commands: `open --minutes N` (open a fresh sandbox
season now, seeds past players for the blast), `tick` (run reconcile once → fire due emails
immediately), `close` (force the window closed now so `tick` sends results), `restart --minutes N`
(archive + open a fresh season), `status`, `wipe`. The script refuses to run unless `EVENT_ROOT` is
overridden away from the prod node. Then sign up / fight / watch close+results in the browser. To QA
the **gift-card prize**, pass `GIFT_CARD_LABEL`/`GIFT_CARD_CODE`/`GIFT_CARD_YEAR` (fake code,
`YEAR` = the sandbox season's `currentEventYear()`) to test it ON, omit/blank them to test it OFF;
`open`/`status` print whether the prize is `ACTIVE`/`dormant`. QA must run the **branch's** code, so
its local image builds use **`IMAGE_TAG=qa`** (like `/test`'s `IMAGE_TAG=test`) to stay invisible to
the deploy-watcher — commit before building. The deterministic logic is covered separately by
`test_lifecycle.py` / `test_queries.py`. **One-time:** the sandbox node
needs the same `.indexOn: ["email"]` rule on `{EVENT_ROOT}/users` that prod has on
`halloween-event/users` (add it in the Firebase console) — without it the email-lookup query behind
signup/login returns HTTP 400.

## Deployment & secrets (important)

HalloweenEvent has its **own self-contained CD** — it does **not** use GitProjectUpdateHandler (GPUH)
anymore (GPUH now deploys only GBot).

- **Build (CI):** on push to `master`, the `publish` job in `.github/workflows/ci.yml` builds native
  **arm64** images and pushes them to **GHCR** — `ghcr.io/cgoulart35/halloweenevent-{api,webapp}`
  (`:latest` + `:<short-sha>`). Packages are **public**, so the Pi pulls anonymously (no `docker login`).
  A `changes` job gates `publish`: pushes touching only docs/CI config (`**.md` / `.claude/` /
  `.github/`) still run `test`+`audit` but skip the build, so docs/skills/CI-config changes don't
  publish or redeploy.
- **PR review (CI):** `.github/workflows/claude-review.yml` runs Claude (`anthropics/claude-code-action@v1`)
  on every PR, posting inline findings; authed by the `CLAUDE_CODE_OAUTH_TOKEN` repo secret (a Claude
  **Pro** subscription, not API billing). Comments only — never approves or blocks. Editing this
  workflow makes a PR fail its own review (the action requires the workflow to match `master`), so
  merge workflow changes first.
- **Deploy (Pi):** `scripts/deploy-watcher.sh`, started at boot from `/etc/rc.local` via
  `scripts/start.sh`, polls GHCR every `DEPLOY_POLL_INTERVAL`s (default 120) and — when a new image
  digest appears — runs `scripts/deploy.sh`: `git fetch` + `git checkout -f master` +
  `git reset --hard origin/master`, then `docker compose -f docker-compose-prod.yml pull && up -d`
  (+ `docker image prune -f`). The trigger is the **published image, not the commit**, so it can't
  deploy before CI has built. `docker-compose-prod.yml` carries both `image:` (pull) and `build:`
  (local fallback). Roll back with `IMAGE_TAG=<sha> docker compose -f docker-compose-prod.yml up -d`.
- **Secrets live persistently in the repo dir on the Pi.** The real `api.env`, `app.env`, and
  `serviceAccountKey.json` sit in `~/Code/HalloweenEvent/` (all **gitignored**), injected at runtime
  (`env_file:` + the `serviceAccountKey.json` volume mount) and **never** baked into the image
  (`.dockerignore` excludes them). They **survive every deploy** — `git reset --hard` / `git pull`
  don't touch gitignored files. To change a deployed secret, edit the file in the repo dir on the Pi
  and redeploy (`sh scripts/deploy.sh`). Adding a **new** env var means updating the tracked
  `*.env.example` templates here **and** the real env file in the repo dir on the Pi (no second repo
  involved anymore).
- **Never commit real env values.** Only the `*.env.example` templates are tracked. Stage files
  explicitly by name; never `git add -A` / `git add -u`. Before claiming a secret is leaked, verify
  with `git show HEAD:<file>` and `git log --all -S '<value>'` rather than trusting working-tree
  contents.

Env vars are loaded in `src/{api,app}/properties.py`. **Required** (`getEnvProperty`) — `api.env`:
`VERSION`, `WEBAPP_HOST`, `API_KEY`, `FIREBASE_CONFIG_JSON`, `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_SENDER`, `EMAIL_PASSWORD`; `app.env`: `VERSION`, `API_HOST`, `API_KEY`, `FIREBASE_CONFIG_JSON`.
`API_KEY` is the shared web↔API secret and **must be identical in both files**. Also recognized
(optional/defaulted): `API_PORT`, `LOG_LEVEL`, `TZ`, `EMAIL_OVERRIDE_RECIPIENT`,
`GIFT_CARD_LABEL`/`GIFT_CARD_CODE`/`GIFT_CARD_YEAR` (api; the yearly prize — set all three each
season **in the real `api.env` on the Pi** and redeploy; incomplete or wrong-year config means the
prize is never mentioned or sent — see the `queries.py` bullet); `WEBAPP_PORT`,
`LOG_LEVEL`, `TZ`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` (app). `SECRET_KEY` (app) is read via
`os.getenv` — if unset, a random per-boot key is generated (sessions reset on restart), so set it for
stable sessions; the old `"super secret key"` default is gone. Turnstile is **disabled when
`TURNSTILE_SECRET_KEY` is blank** (so local/QA works without a widget). `EVENT_ROOT` (both apps,
default `halloween-event`, read via `os.getenv`) and `EMAIL_OVERRIDE_RECIPIENT` (api, default empty,
a defaulted `getEnvProperty`) are **QA-only** knobs — leave unset in production. There is **no** cutoff env var anymore; the season
window is hardcoded in `eventstate.py` (`SEASON_OPEN` / `SEASON_CLOSE`). Datetime strings still use
the `"%m/%d/%y %I:%M:%S %p"` format (e.g. `"11/01/26 12:00:00 AM"`).

## Conventions & gotchas

- Functions use **camelCase** throughout (e.g. `getScoreboard`, `buildScoreboard`, `eventIsOpen`).
- numpy 2.x is in use — decode image bytes with `numpy.frombuffer` (not the removed `fromstring`).
- HTML emails must be **inline-CSS + table-based** (mail clients strip `<style>`/external CSS); the
  custom `GOT` font only loads in the web UI, so emails fall back to a serif stack.
- Keep dependency changes minimal and CVE-justified; Dependabot is configured for security updates
  only (no version-update PRs / no `dependabot.yml`).
