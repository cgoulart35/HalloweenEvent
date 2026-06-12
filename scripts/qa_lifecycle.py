"""Manual-QA helper for full E2E testing of the seasonal lifecycle.

It sets up an ISOLATED sandbox season so you can exercise the REAL app (sign up, get the
QR email, fight, watch it close, get results, restart) in your browser on a short window,
with every email redirected to a single address. It never touches real data: it refuses
to run unless EVENT_ROOT is overridden away from the production "halloween-event" node.

Typical flow (run from the repo root with the API env loaded):

    set -a; . api.env; set +a            # real FIREBASE_CONFIG_JSON + email creds
    export EVENT_ROOT=qa-halloween-event           # isolates DB writes
    export EMAIL_OVERRIDE_RECIPIENT=you@example.com # all mail goes only here
    # optional, to QA the gift-card prize (YEAR must equal the sandbox season's year):
    #   export GIFT_CARD_LABEL='QA $5 gift card'; export GIFT_CARD_CODE=QA-TESTCODE
    #   export GIFT_CARD_YEAR=2026
    # 'open'/'status' print whether the prize is ACTIVE or dormant.

    # ... in another shell, run the real app against the same sandbox env:
    #     EVENT_ROOT=qa-halloween-event EMAIL_OVERRIDE_RECIPIENT=you@example.com \
    #       docker compose -f docker-compose-prod.yml up --build

    python scripts/qa_lifecycle.py open --minutes 15   # season open now for 15 min
    #   -> browser: sign up (welcome+QR email), fight, watch the live scoreboard
    python scripts/qa_lifecycle.py tick                # fire season-start email now
    #   ... after closeTime passes ...
    python scripts/qa_lifecycle.py tick                # fire results email(s) now
    python scripts/qa_lifecycle.py restart --minutes 15  # archive + fresh open season
    python scripts/qa_lifecycle.py status
    python scripts/qa_lifecycle.py wipe                # delete sandbox nodes when done

`tick` runs the real reconcile loop once on the real clock (the app does this every
5 min on its own; tick just makes the scheduled emails fire immediately). Gating
(open/closed in the browser) reflects the window instantly without a tick.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.properties import APIPropertiesManager
from src.common.firebase import FirebaseService
from src.common import lifecycle, queries
from src.common.eventstate import EVENT_ROOT, FORMAT, currentEventYear, eventIsOpen

PROD_ROOT = "halloween-event"


def _bootstrap():
    if EVENT_ROOT == PROD_ROOT:
        sys.exit("REFUSING TO RUN against the production node. Set EVENT_ROOT to a sandbox "
                 "(e.g. EVENT_ROOT=qa-halloween-event) before running.")
    APIPropertiesManager.startPropertyManager()
    FirebaseService.startFirebaseScheduler(APIPropertiesManager.FIREBASE_CONFIG_JSON)
    print(f"sandbox node : {EVENT_ROOT}")
    print(f"email override: {APIPropertiesManager.EMAIL_OVERRIDE_RECIPIENT or '(NONE -- real recipients!)'}\n")


def _prizeState(year):
    # One line describing whether the gift-card prize is armed for this season, so QA can
    # confirm the GIFT_CARD_* env vars took effect. Never prints the code itself.
    card = queries.getActiveGiftCard(year)
    if card:
        return f"ACTIVE -- {card[0]} (code set) for {year}"
    return "dormant (GIFT_CARD_* unset, incomplete, or year mismatch)"


def _setWindowMeta(year, minutes):
    now = datetime.now()
    openTime = now.strftime(FORMAT)
    closeTime = (now + timedelta(minutes=minutes)).strftime(FORMAT)
    FirebaseService.set([EVENT_ROOT, "meta"], {
        "year": year, "openTime": openTime, "closeTime": closeTime,
        "resultsEmailed": False, "startEmailed": False,
    })
    return openTime, closeTime


def _seedArchives():
    # A couple of fake past seasons so the season-start blast has recipients. Uses the
    # reserved example.com domain (never delivers) -- player-one repeats across years to
    # exercise dedup. Real delivery is controlled entirely by EMAIL_OVERRIDE_RECIPIENT.
    FirebaseService.set([EVENT_ROOT + "-2024"], {"users": {
        "u1": {"name": "Player One", "email": "player-one@example.com", "score": 5},
        "u2": {"name": "Player Two", "email": "player-two@example.com", "score": 3},
    }, "scoreboard": {}})
    FirebaseService.set([EVENT_ROOT + "-2025"], {"users": {
        "u3": {"name": "Player One", "email": "player-one@example.com", "score": 2},
    }, "scoreboard": {}})


def cmd_open(args):
    _seedArchives()
    year = currentEventYear()
    # Fresh, empty current season (sign up from scratch) with a short open-now window.
    FirebaseService.set([EVENT_ROOT], {"meta": {"year": year}})
    openTime, closeTime = _setWindowMeta(year, args.minutes)
    print(f"season {year} OPEN: {openTime} -> {closeTime} ({args.minutes} min)")
    print(f"gift-card prize: {_prizeState(year)}")
    print("the real app (pointed at this sandbox) is now open -- sign up & fight in the browser")


def cmd_restart(args):
    meta = FirebaseService.get([EVENT_ROOT, "meta"]).val()
    if not meta:
        sys.exit("no sandbox season yet -- run 'open' first")
    year = meta["year"]
    lifecycle.rolloverEvent(year)                 # archive {year} -> {EVENT_ROOT}-{year}, fresh {year+1}
    openTime, closeTime = _setWindowMeta(year + 1, args.minutes)  # but open it NOW for QA
    print(f"archived season {year}; season {year + 1} OPEN: {openTime} -> {closeTime}")


def cmd_tick(args):
    print(f"reconcile @ {datetime.now().strftime(FORMAT)} (fires any due emails now)")
    before = FirebaseService.get([EVENT_ROOT, "meta"]).val()
    lifecycle.reconcileEventLifecycle()
    after = FirebaseService.get([EVENT_ROOT, "meta"]).val()
    print(f"  meta before: {before}")
    print(f"  meta after : {after}")


def cmd_status(args):
    meta = FirebaseService.get([EVENT_ROOT, "meta"]).val()
    print(f"now          : {datetime.now().strftime(FORMAT)}")
    print(f"meta         : {meta}")
    if meta:
        print(f"OPEN?        : {eventIsOpen(meta['openTime'], meta['closeTime'])}")
        print(f"prize        : {_prizeState(meta['year'])}")
    nodes = sorted(k for k in FirebaseService.listRootKeys()
                   if k == EVENT_ROOT or k.startswith(EVENT_ROOT + "-"))
    print(f"sandbox nodes: {nodes}")
    print(f"past players : {lifecycle.getAllPastParticipantEmails()}")


def cmd_close(args):
    # Force the current window closed (closeTime -> now) so 'tick' fires the results email
    # immediately, without resetting the season's players/fights.
    meta = FirebaseService.get([EVENT_ROOT, "meta"]).val()
    if not meta:
        sys.exit("no sandbox season yet -- run 'open' first")
    closeTime = datetime.now().strftime(FORMAT)
    FirebaseService.set([EVENT_ROOT, "meta", "closeTime"], closeTime)
    print(f"closed window at {closeTime} -- run 'tick' to send the results email")


def cmd_wipe(args):
    removed = []
    for key in FirebaseService.listRootKeys():
        if key == EVENT_ROOT or key.startswith(EVENT_ROOT + "-"):
            FirebaseService.remove([key])
            removed.append(key)
    print("removed:", sorted(removed) or "(nothing)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_open = sub.add_parser("open", help="open a fresh sandbox season now for N minutes")
    p_open.add_argument("--minutes", type=int, default=15)
    p_restart = sub.add_parser("restart", help="archive current season + open a fresh one now")
    p_restart.add_argument("--minutes", type=int, default=15)
    sub.add_parser("tick", help="run the reconcile loop once (fire due emails now)")
    sub.add_parser("close", help="force the window closed now (so tick sends results)")
    sub.add_parser("status", help="show the sandbox season state")
    sub.add_parser("wipe", help="delete all sandbox nodes")
    args = parser.parse_args()

    _bootstrap()
    {"open": cmd_open, "restart": cmd_restart, "tick": cmd_tick, "close": cmd_close,
     "status": cmd_status, "wipe": cmd_wipe}[args.command](args)


if __name__ == "__main__":
    main()
