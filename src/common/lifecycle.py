#region IMPORTS
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from urllib.parse import quote

from src.api.properties import APIPropertiesManager
from src.common.firebase import FirebaseService
from src.common import queries
from src.common.eventstate import (
    EVENT_ROOT,
    FORMAT,
    currentEventYear,
    eventIsOpen,
    seasonCloseString,
    seasonOpenDatetime,
    seasonOpenString,
)
from src.common.security import escapeHtml, makeUnsubscribeToken
#endregion

# Self-restarting yearly season engine (API only -- single writer).
#
# The active season runs Oct 1 -> Nov 1 by rule (see eventstate). The current season's
# window + identity + which emails have gone out live in {EVENT_ROOT}/meta:
#
#   meta = {
#     "year":           <int>,        # season identity / archive suffix
#     "openTime":       <FORMAT str>, # when this season opens
#     "closeTime":      <FORMAT str>, # when it closes
#     "resultsEmailed": <bool>,       # final-results email sent for this season?
#     "startEmailed":   <bool>,       # season-start email sent for this season?
#   }
#
# reconcileEventLifecycle() runs on an interval and is the single driver: at close it
# emails final results; at the next season open (Oct 1) it archives the finished season
# to {EVENT_ROOT}-{year}, opens a fresh one, and emails the reminder list (past players +
# opt-ins, minus opt-outs). It is idempotent
# and self-heals across restarts -- it re-derives state from meta + now, guarded by the
# emailed flags, so nothing depends on hitting an exact instant.

logger = logging.getLogger()


def _getMeta():
    return FirebaseService.get([EVENT_ROOT, "meta"]).val()


def _setMetaField(field, value):
    FirebaseService.set([EVENT_ROOT, "meta", field], value)


def _seasonMeta(year, startEmailed):
    return {
        "year": year,
        "openTime": seasonOpenString(year),
        "closeTime": seasonCloseString(year),
        "resultsEmailed": False,
        "startEmailed": startEmailed,
    }


def ensureProvisioned(now=None):
    # Seed {EVENT_ROOT}/meta if missing. Purely additive -- never touches existing
    # users/scoreboard. Suppresses an immediate season-start blast if we happen to
    # deploy mid-season (only a real Oct 1 transition should fire it).
    if _getMeta():
        return
    now = now or datetime.now()
    year = currentEventYear(now)
    alreadyOpen = eventIsOpen(seasonOpenString(year), seasonCloseString(year), now)
    FirebaseService.set([EVENT_ROOT, "meta"], _seasonMeta(year, startEmailed=alreadyOpen))
    logger.info("Provisioned %s/meta for season %s", EVENT_ROOT, year)


def getAllPastParticipantEmails():
    # Every email that ever signed up, across the live node and all yearly archives,
    # deduped case-insensitively (first-seen spelling kept).
    emails = {}
    for node in FirebaseService.listRootKeys():
        if node != EVENT_ROOT and not node.startswith(EVENT_ROOT + "-"):
            continue
        users = FirebaseService.get([node, "users"]).val()
        if not users:
            continue
        values = users.values() if isinstance(users, dict) else users
        for user in values:
            email = (user.get("email") or "").strip()
            if email:
                emails.setdefault(email.lower(), email)
    return list(emails.values())


def getSeasonStartRecipients():
    # Who gets the season-start blast: every past player UNION explicit "remind me"
    # opt-ins, MINUS explicit opt-outs, deduped case-insensitively (first-seen spelling
    # kept). With no reminder records this is exactly getAllPastParticipantEmails(), so
    # default behavior is unchanged; the reminders list only adds new opt-ins and removes
    # players who unsubscribed.
    subscriptions = queries.getReminderSubscriptions()   # {lower: (email, status)}
    recipients = {}                                      # lower -> spelling to send to
    for email in getAllPastParticipantEmails():
        recipients.setdefault(email.lower(), email)
    for lower, (email, status) in subscriptions.items():
        if status == "subscribed":
            recipients.setdefault(lower, email)
    optedOut = {lower for lower, (_email, status) in subscriptions.items()
                if status == "unsubscribed"}
    return [spelling for lower, spelling in recipients.items() if lower not in optedOut]


def sendSeasonStartEmail(year):
    # Announce a fresh season to every reminder recipient (past players + opt-ins, minus
    # opt-outs). Mirrors emailResults' SMTP pattern (one connection, loop recipients) and
    # reuses queries.styledEmail for theming. Each email carries a per-recipient
    # unsubscribe link so the body is themed inside the loop.
    recipients = queries.resolveRecipients(getSeasonStartRecipients())
    if not recipients:
        return

    emailHost = APIPropertiesManager.EMAIL_HOST
    emailPort = APIPropertiesManager.EMAIL_PORT
    emailSender = APIPropertiesManager.EMAIL_SENDER
    emailPassword = APIPropertiesManager.EMAIL_PASSWORD
    webAppHost = APIPropertiesManager.WEBAPP_HOST
    apiKey = APIPropertiesManager.API_KEY

    # what they're playing for, when a gift card is configured for this season
    giftCard = queries.getActiveGiftCard(year)
    prizeLine = ""
    if giftCard:
        prizeLine = (
            '<p style="margin:0 0 14px 0;">This season\'s prize: <strong>'
            + escapeHtml(giftCard[0]) +
            '</strong> -- the top score takes it!</p>'
        )

    content = (
        '<p style="margin:0 0 14px 0;">The Long Night has returned.</p>'
        '<p style="margin:0 0 18px 0;font-size:18px;color:#5f2f87;"><strong>A fresh season is '
        'live for the whole month of October!</strong></p>'
        '<p style="margin:0 0 14px 0;">Every score is wiped clean -- sign up, get your QR code, '
        'and battle other players. Whoever has the most points when October ends wins. '
        'The season closes November 1.</p>'
        + prizeLine +
        f'<p style="margin:0 0 14px 0;">Play here: {webAppHost}</p>'
        '<p style="margin:8px 0 0 0;">See you out there.</p>'
    )

    server = smtplib.SMTP_SSL(emailHost, emailPort)
    server.login(emailSender, emailPassword)
    for email in recipients:
        # Per-recipient unsubscribe link, authed by an HMAC token so it can't be used to
        # unsubscribe anyone else (see security.makeUnsubscribeToken). The link lands on a
        # confirm page that POSTs the actual opt-out, so a link prefetch can't opt anyone out.
        unsubscribeUrl = (webAppHost + "/unsubscribe/?email=" + quote(email, safe="")
                          + "&token=" + makeUnsubscribeToken(apiKey, email))
        footer = (
            '<p style="margin:18px 0 0 0;font-size:12px;color:#777777;">'
            "You're getting this season-opening reminder because you're on The Long Night's "
            'reminder list. This only affects these once-a-year reminders -- your game and '
            'results emails are never affected. '
            f'<a href="{escapeHtml(unsubscribeUrl)}" style="color:#777777;">'
            'Unsubscribe from season reminders</a>.</p>'
        )
        body = queries.styledEmail(content + footer)
        msg = MIMEText(body, 'html')
        msg['Subject'] = "The Long Night returns -- a new season has begun!"
        msg['From'] = emailSender
        msg['To'] = email
        server.sendmail(emailSender, [email], msg.as_string())
    server.quit()
    logger.info("Sent season-start email for %s to %d recipients", year, len(recipients))


def rolloverEvent(year):
    # Archive the finished season's data to {EVENT_ROOT}-{year} and reset the live node
    # to a fresh empty season {year+1}. Skips archiving an empty node and never clobbers
    # an existing archive (idempotent).
    node = FirebaseService.get([EVENT_ROOT]).val() or {}
    users = node.get("users")
    archiveKey = EVENT_ROOT + "-" + str(year)
    if users and not FirebaseService.get([archiveKey]).val():
        FirebaseService.set([archiveKey], {
            "users": users,
            "scoreboard": node.get("scoreboard") or {},
        })
        logger.info("Archived season %s to %s", year, archiveKey)
    freshNode = {"meta": _seasonMeta(year + 1, startEmailed=False)}
    # The reminder opt-in/opt-out list is season-independent -- carry it forward across
    # the reset (only the players/scoreboard get archived, never the reminders).
    reminders = node.get("reminders")
    if reminders:
        freshNode["reminders"] = reminders
    FirebaseService.set([EVENT_ROOT], freshNode)
    logger.info("Opened fresh season %s", year + 1)


def reconcileEventLifecycle(now=None):
    # The heartbeat. Idempotent and restart-safe: re-derives all state from meta + now.
    now = now or datetime.now()
    ensureProvisioned(now)
    meta = _getMeta()
    year = meta["year"]

    # Roll forward to the latest season whose (rule-based) Oct 1 open has arrived. Usually
    # a no-op; fires once each Oct 1, and catches up year-by-year after long downtime.
    while now >= seasonOpenDatetime(year + 1):
        rolloverEvent(year)
        year += 1
        meta = _getMeta()

    # Season-start announcement to the reminder list -- once per open season.
    if eventIsOpen(meta["openTime"], meta["closeTime"], now) and not meta.get("startEmailed"):
        try:
            sendSeasonStartEmail(year)
            _setMetaField("startEmailed", True)
        except Exception:
            logger.error("Error sending season-start email for %s", year)

    # Final results at close -- once per season. (Flag set only on success so a transient
    # failure retries on the next tick.)
    if now >= datetime.strptime(meta["closeTime"], FORMAT) and not meta.get("resultsEmailed"):
        try:
            queries.emailResults(year)
            _setMetaField("resultsEmailed", True)
        except Exception:
            logger.error("Error emailing results for %s", year)
