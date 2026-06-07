# The Long Night

A Halloween party game. Every participant gets a personal QR code; players scan each other's codes
to trigger a randomized **fight** — the winner gets +2 points, the loser +1, and any pair may fight
only once. State lives in a Firebase Realtime Database. It runs as two Docker containers on a
Raspberry Pi 4 (aarch64), Python 3.12.

## How it works

- **Sign up** on the web app to get a QR code emailed to you.
- **Scan** another player's QR code to fight them. The winner is random; scores update live.
- A **live scoreboard** shows every fight.
- When the season ends, everyone gets a **results email** summarizing their fights.

## Seasonal, self-restarting lifecycle

The game runs **one season per year, every October**, and restarts itself with no manual work:

| When | What happens |
| --- | --- |
| **Oct 1 → Nov 1** | Season is **open** — sign-ups and fights allowed. |
| **Nov 1 00:00** (close) | Game closes; final **results email** sent. The site shows the finished standings all off-season. |
| **Oct 1 00:00** (next year) | The finished season is archived to `halloween-event-{year}`, a fresh empty season opens, and a **"new season" email** goes to everyone who has ever played. |

The active window is **Oct 1 → Nov 1** by rule (`SEASON_OPEN`/`SEASON_CLOSE` in
`src/common/eventstate.py`). The current season's window and identity live in the database at
`halloween-event/meta`:

```json
"meta": {
  "year": 2026,
  "openTime":  "10/01/26 12:00:00 AM",
  "closeTime": "11/01/26 12:00:00 AM",
  "resultsEmailed": false,
  "startEmailed": false
}
```

so the schedule auto-advances and stays correct across restarts. The API runs the lifecycle on a
5-minute reconcile loop that is idempotent and self-healing — see `src/common/lifecycle.py`.

**The annual cycle:**

```mermaid
flowchart TD
    D["Deploy / boot<br/>ensureProvisioned seeds meta<br/>(year · Oct 1 → Nov 1 window · email flags)"] --> PRE["🌙 Off-season<br/>gate CLOSED · ended.html shows last standings"]
    PRE -->|"Oct 1 00:00"| OPEN["🎃 Season OPEN<br/>signups + fights allowed<br/>season-start email → all past players"]
    OPEN -->|"Nov 1 00:00"| CLOSE["🌙 Season CLOSED<br/>results email → participants<br/>ended.html shows final standings"]
    CLOSE -->|"next Oct 1"| ROLL["♻️ Rollover<br/>archive → halloween-event-{year}<br/>open a fresh empty season"]
    ROLL --> OPEN
```

**The reconcile heartbeat** (idempotent — re-derives everything from `meta` + `now` each tick):

```mermaid
flowchart TD
    T(["reconcile tick — every 5 min<br/>(and once on boot)"]) --> EP["ensureProvisioned:<br/>seed meta if missing"]
    EP --> Q1{"now ≥ next season's<br/>Oct 1 open?"}
    Q1 -->|yes| RO["rolloverEvent:<br/>archive → -{year} + fresh season"]
    RO --> Q1
    Q1 -->|no| Q2{"season open and<br/>season-start unsent?"}
    Q2 -->|yes| SS["send season-start email<br/>· set startEmailed"]
    Q2 -->|no| Q3{"past close and<br/>results unsent?"}
    SS --> Q3
    Q3 -->|yes| RR["send results email<br/>· set resultsEmailed"]
    Q3 -->|no| DONE(["done — retries next tick<br/>on any failure"])
    RR --> DONE
```

## Architecture

Two independent Flask apps share `src/common/`:

- **API** (`src/api/api.py`, port **5007**, HTTP) — Flask-RESTful resources: `Scoreboard` (GET),
  `Fight` (POST), `Users` (POST register / PUT update), `Login` (POST). Owns the season lifecycle.
- **Web app** (`src/app/app.py` + `src/app/views.py`, port **5009**, HTTPS self-signed) — renders
  Jinja templates and calls the API. Server-side in-memory sessions; QR scanning via `cv2`.

`src/common/`: `firebase.py` (DB facade), `queries.py` (game logic + email), `eventstate.py` (the
seasonal calendar / gating), `lifecycle.py` (archive + reset + promo engine, API-only).

Data layout in Firebase: live season under `halloween-event/{users,scoreboard,meta}`; past seasons
archived under `halloween-event-{year}`.

```mermaid
flowchart LR
    P["Player<br/>phone / browser"] -->|HTTPS| CF["Cloudflare tunnel<br/>halloween.stormerg.com"]
    CF --> W["Web app · Flask :5009<br/>Jinja templates + QR scan"]
    W -->|"HTTP (API_HOST)"| A["API · Flask-RESTful :5007<br/>game endpoints + lifecycle loop"]
    W & A --> CM["src/common<br/>queries · eventstate · lifecycle · firebase"]
    CM -->|firebase-admin| DB[("Firebase RTDB<br/>halloween-event/{users,scoreboard,meta}<br/>halloween-event-YYYY archives")]
    A -->|SMTP_SSL| MAIL["welcome · season-start · results emails"]
```

## Running locally

Requires `api.env`, `app.env`, and `serviceAccountKey.json` in the repo root (the `*.env.example`
files document the schema; real values come from deployment).

```bash
docker compose -f docker-compose-prod.yml up -d --build
docker compose -f docker-compose-prod.yml ps
docker compose -f docker-compose-prod.yml logs --tail=20 halloween-api-prod
```

## Tests

pytest isn't baked into the images; run it in an ephemeral container against the webapp image (the
only one with `libgl1` for `cv2`):

```bash
docker compose -f docker-compose-prod.yml build halloween-webapp-prod
docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
  halloween-webapp-prod -c "pip install -q -r requirements-dev.txt && python -m pytest -q"
```

## Manual E2E QA (no real data, no real emails)

QA reuses the **real** environment — same domain, same Firebase project, same SMTP — and isolates
itself purely by switching the **data node**. The domain serves prod *or* QA at a given time, so QA
temporarily runs in place of prod with the real `api.env` / `app.env` plus:

| key | value | why |
| --- | --- | --- |
| `EVENT_ROOT` (both apps) | `qa-halloween-event` | **required** — all reads/writes/archives use `qa-*` nodes; real `halloween-event*` data is untouched |
| `EMAIL_OVERRIDE_RECIPIENT` (api) | your address | *optional* — routes the season-start blast to you (so you can see it), and guards against ever mailing a real address |

Everything else (real `WEBAPP_HOST` domain, `API_HOST`, Firebase creds, SMTP) stays real — so the
QR/email links are the real domain and work on your phone. Drive the season with the harness (it
runs inside a container and refuses to run unless `EVENT_ROOT` is off the prod node):

```bash
docker compose -f docker-compose-prod.yml up --build -d
run() { docker compose -f docker-compose-prod.yml run --rm --no-deps --entrypoint sh \
          halloween-api-prod -c "python scripts/qa_lifecycle.py $*"; }
run "open --minutes 30"      # open a sandbox season now (also seeds past players)
run "tick"                   # fire the season-start email
run "close" && run "tick"    # force-close + fire the results email immediately
run "restart --minutes 30"   # archive + open a fresh season
run "status"                 # inspect sandbox state
run "wipe"                   # delete sandbox nodes when done
```

Then on the real domain (now serving the QA stack): sign up, fight, watch the scoreboard. `tick`
just runs the reconcile loop once so scheduled emails fire immediately (the app does this every
5 min on its own); gating reflects the window instantly.

Notes:
- **One-time setup:** the sandbox node needs the same `.indexOn: ["email"]` rule on
  `qa-halloween-event/users` that prod has on `halloween-event/users` (add it once in the Firebase
  console). Without it the email-lookup query behind signup/login returns HTTP 400.
- QA and prod can't run at the same time (shared domain/host); QA replaces prod for the session.
- A fight needs two accounts and one to scan the other's QR (or visit
  `…/fight/?scannedUserKey=<otherKey>` while logged in as the first).
- For a quick laptop-only smoke (no phone links), additionally override
  `WEBAPP_HOST=https://localhost:5009` and `API_HOST=http://halloween-api-prod:5004`.

## Configuration

Env vars are loaded in `src/{api,app}/properties.py`.

- **`api.env`** (required): `VERSION`, `WEBAPP_HOST`, `FIREBASE_CONFIG_JSON`, `EMAIL_HOST`,
  `EMAIL_PORT`, `EMAIL_SENDER`, `EMAIL_PASSWORD`. Optional: `API_PORT`, `LOG_LEVEL`, `TZ`.
- **`app.env`** (required): `VERSION`, `API_HOST`, `FIREBASE_CONFIG_JSON`. Optional: `WEBAPP_PORT`,
  `SECRET_KEY`, `LOG_LEVEL`, `TZ`.
- **QA-only** (leave unset in production): `EVENT_ROOT` (both apps; sandbox DB node) and
  `EMAIL_OVERRIDE_RECIPIENT` (api; redirect all outgoing mail).

There is no cutoff env var — the season window is hardcoded in `eventstate.py`.

## Deployment

Deployed on a Raspberry Pi via `~/Code/GitProjectUpdateHandler` (a webhook service that, on push,
`git reset --hard` + `git pull`s this repo, copies the real secrets into place, and rebuilds the two
prod containers). `api.env` / `app.env` / `serviceAccountKey.json` are gitignored; only the
`*.env.example` templates are tracked.
