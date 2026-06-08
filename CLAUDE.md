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
image, which is the only one that installs `libgl1` (required by `cv2`):
```
docker compose -f docker-compose-prod.yml build halloween-webapp-prod
docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
  halloween-webapp-prod -c "pip install -q -r requirements-dev.txt && python -m pytest -q"
```
Single test: append `tests/test_queries.py::test_perform_fight_happy_path` (or `-k <name>`) to pytest.
`tests/` deliberately exercises only safely-importable code (`queries`, `eventstate`, `lifecycle`,
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
overridden away from the prod node. Then sign up / fight / watch close+results in the browser. The
deterministic logic is covered separately by `test_lifecycle.py`. **One-time:** the sandbox node
needs the same `.indexOn: ["email"]` rule on `{EVENT_ROOT}/users` that prod has on
`halloween-event/users` (add it in the Firebase console) — without it the email-lookup query behind
signup/login returns HTTP 400.

## Deployment & secrets (important)

- Deploy script: `~/Code/GitProjectUpdateHandler/Scripts/UpdateHalloweenEvent.sh` — copies secrets
  from `~/Code/GitProjectUpdateHandler/Shared/HalloweenEvent/{serviceAccountKey.json,api.env,app.env}`
  into the repo, then `docker compose -f docker-compose-prod.yml down && up -d --build`.
- Triggered by the `GitProjectUpdateHandler` webhook service, which runs `git reset --hard` +
  `git pull` (discarding all local working-tree edits) **then** runs the script (which re-copies
  secrets). Leaving local `master` behind `origin/master` is what makes it detect and deploy.
- **`api.env` / `app.env` are gitignored; only `api.env.example` / `app.env.example` are tracked.**
  Real values live **only** in the Shared dir above and are copied in at deploy time (after the
  `git reset`); `serviceAccountKey.json` is gitignored too. To change a deployed secret, edit the
  **Shared dir** files — editing the local repo copies alone won't survive the deploy's `git reset`.
- **Never commit real env values.** Stage files explicitly by name; never `git add -A` / `git add -u`.
  Before claiming a secret is leaked, verify with `git show HEAD:<file>` and `git log --all -S '<value>'`
  rather than trusting working-tree contents. (The Shared dir is its own git repo, `GitProjectUpdateHandler`,
  whose tracked env files are **blank-secret**; the real values sit in its working tree uncommitted.)

Env vars are loaded in `src/{api,app}/properties.py`. **Required** (`getEnvProperty`) — `api.env`:
`VERSION`, `WEBAPP_HOST`, `API_KEY`, `FIREBASE_CONFIG_JSON`, `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_SENDER`, `EMAIL_PASSWORD`; `app.env`: `VERSION`, `API_HOST`, `API_KEY`, `FIREBASE_CONFIG_JSON`.
`API_KEY` is the shared web↔API secret and **must be identical in both files**. Also recognized
(optional/defaulted): `API_PORT`, `LOG_LEVEL`, `TZ`, `EMAIL_OVERRIDE_RECIPIENT` (api); `WEBAPP_PORT`,
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
