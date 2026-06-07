import os
from datetime import datetime

from src.common.firebase import FirebaseService

# Single source of truth for "is The Long Night open right now?", shared by the API
# and web app. The apps don't shut down at a cutoff; they run year-round and switch
# between an OPEN (playable) and a CLOSED ("ended") state based on the season window.
#
# The season is, by rule, the month of October: it OPENS Oct 1 00:00 and CLOSES
# Nov 1 00:00 each year. The *current* season's window and identity live in the
# database at {EVENT_ROOT}/meta (so the schedule auto-advances and survives restarts,
# and so QA can drop in a short window without touching prod code). The Oct 1 -> Nov 1
# values below are what fill that meta in production.

# Top-level database node the game lives under. Defaults to "halloween-event"; override
# with the EVENT_ROOT env var to run against an isolated sandbox (e.g. "qa-halloween-event")
# so QA never reads or writes real data. All paths in queries/lifecycle derive from this.
EVENT_ROOT = os.getenv("EVENT_ROOT", "halloween-event")

FORMAT = "%m/%d/%y %I:%M:%S %p"

# (month, day) the active period opens / closes, at 00:00. Change these to move the
# season; production meta is seeded from them.
SEASON_OPEN = (10, 1)   # Oct 1 00:00
SEASON_CLOSE = (11, 1)  # Nov 1 00:00


def seasonOpenDatetime(year):
    return datetime(year, SEASON_OPEN[0], SEASON_OPEN[1], 0, 0, 0)


def seasonCloseDatetime(year):
    return datetime(year, SEASON_CLOSE[0], SEASON_CLOSE[1], 0, 0, 0)


def seasonOpenString(year):
    return seasonOpenDatetime(year).strftime(FORMAT)


def seasonCloseString(year):
    return seasonCloseDatetime(year).strftime(FORMAT)


def eventIsOpen(openTime, closeTime, now=None):
    # Open only within the window: openTime <= now < closeTime. Both pre-season and
    # post-season are closed (two-sided check). Times are FORMAT strings.
    now = now or datetime.now()
    return datetime.strptime(openTime, FORMAT) <= now < datetime.strptime(closeTime, FORMAT)


def currentEventYear(now=None):
    # The season year to seed when provisioning (and the gating fallback): this year's
    # October unless we're already past this year's close, in which case it's next year.
    now = now or datetime.now()
    return now.year if now < seasonCloseDatetime(now.year) else now.year + 1


def getCurrentSeasonWindow():
    # The current season's (openTime, closeTime) from the database, with a calendar
    # fallback so gating still works before the API provisions meta or if a read fails.
    try:
        meta = FirebaseService.get([EVENT_ROOT, "meta"]).val()
        return meta["openTime"], meta["closeTime"]
    except Exception:
        year = currentEventYear()
        return seasonOpenString(year), seasonCloseString(year)
