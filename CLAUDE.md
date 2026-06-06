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

Both processes run Flask's built-in werkzeug server via `app.run(...)`, launched under `debugpy`
(see the Dockerfile entrypoints). This is intentional for a small app behind a Cloudflare tunnel.

`src/common/`:
- `firebase.py` — `FirebaseService`: thin facade over **firebase-admin** Realtime DB
  (`get/set/push/update/remove/query`). Reads return a `_Result` exposing `.val()` (Pyrebase-shaped).
  Init from `FIREBASE_CONFIG_JSON` (JSON containing `serviceAccount` + `databaseURL`). Data lives
  under `halloween-event/users/{userKey}` and `halloween-event/scoreboard`.
- `queries.py` — game logic, Firebase access, and **email** (welcome email with embedded QR in
  `addParticipant`; results emails in `emailResults`). `styledEmail()` wraps email bodies in the
  app's theme.
- `eventstate.py` — `eventHasEnded(shutdownTime)`: the single source of truth for whether the event
  is over (compares `datetime.now()` to `SCHEDULED_SHUTDOWN_TIME`).

### Event lifecycle (read before touching shutdown/scheduler/gating code)

The event is **open** until `SCHEDULED_SHUTDOWN_TIME`, then both services switch to a **closed
"ended" state** instead of shutting down:
- Web app: `@views.before_request` (`gateClosedAfterEvent`) serves `ended.html` (with final standings)
  for **every** route once `eventHasEnded()` is true.
- API: `Fight.post` and `Users.post` return 403; `Scoreboard.get`/`Login` stay open.
- At the cutoff the API's scheduled `endEvent` job emails final results once (`emailResults`).

The apps **must not** self-terminate (they previously did `os.system("kill -15 1")`); they stay up so
the containers can auto-restart (`restart: unless-stopped`). The check is **time-based, computed per
request/start** — not a one-shot scheduler job — so it stays correct across container restarts.

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
Single test: append `tests/test_queries.py::test_performFight_happy_path` (or `-k <name>`) to pytest.
`tests/` deliberately exercises only safely-importable code (`queries`, `eventstate`, the dep set,
the cv2 QR round-trip); `api.py`/`app.py` aren't imported because they run `app.run()` / Firebase
init at import time.

**Dependency CVE audit:** `pip-audit` (in `requirements-dev.txt`), run the same ephemeral way.

## Deployment & secrets (important)

- Deploy script: `~/Code/GitProjectUpdateHandler/Scripts/UpdateHalloweenEvent.sh` — copies secrets
  from `~/Code/GitProjectUpdateHandler/Shared/HalloweenEvent/{serviceAccountKey.json,api.env,app.env}`
  into the repo, then `docker compose -f docker-compose-prod.yml down && up -d --build`.
- Triggered by the `GitProjectUpdateHandler` webhook service, which runs `git reset --hard` +
  `git pull` (discarding all local working-tree edits) **then** runs the script (which re-copies
  secrets). Leaving local `master` behind `origin/master` is what makes it detect and deploy.
- **`api.env` / `app.env` are committed as blank-secret templates.** Real values (and the real
  `SCHEDULED_SHUTDOWN_TIME`) live **only** in the Shared dir above and are copied in at deploy time;
  `serviceAccountKey.json` is gitignored. To change a deployed secret or the shutdown date, edit the
  **Shared dir** files — editing the local repo copies alone won't survive the deploy's `git reset`.
- **Never commit real env values.** Stage files explicitly by name; never `git add -A` / `git add -u`.
  Before claiming a secret is leaked, verify with `git show HEAD:<file>` and `git log --all -S '<value>'`
  rather than trusting working-tree contents.

Env vars are loaded in `src/{api,app}/properties.py`. **Required** (`getEnvProperty`) — `api.env`:
`VERSION`, `SCHEDULED_SHUTDOWN_TIME`, `WEBAPP_HOST`, `FIREBASE_CONFIG_JSON`, `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_SENDER`, `EMAIL_PASSWORD`; `app.env`: `VERSION`, `SCHEDULED_SHUTDOWN_TIME`, `API_HOST`,
`FIREBASE_CONFIG_JSON`. Also recognized (optional/defaulted): `API_PORT`, `LOG_LEVEL`, `TZ` (api);
`WEBAPP_PORT`, `SECRET_KEY`, `LOG_LEVEL`, `TZ` (app). `SCHEDULED_SHUTDOWN_TIME` format is
`"%m/%d/%y %I:%M:%S %p"` (e.g. `"11/01/26 01:00:00 AM"`).

## Conventions & gotchas

- Functions use **camelCase** throughout (e.g. `getScoreboard`, `buildScoreboard`, `eventHasEnded`).
- numpy 2.x is in use — decode image bytes with `numpy.frombuffer` (not the removed `fromstring`).
- HTML emails must be **inline-CSS + table-based** (mail clients strip `<style>`/external CSS); the
  custom `GOT` font only loads in the web UI, so emails fall back to a serif stack.
- Keep dependency changes minimal and CVE-justified; Dependabot is configured for security updates
  only (no version-update PRs / no `dependabot.yml`).
