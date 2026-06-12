"""Unit tests for the seasonal lifecycle engine (src/common/lifecycle.py).

Uses a tiny in-memory FakeDB monkeypatched over FirebaseService so provisioning,
archiving/rollover, and the reconcile transitions can be driven deterministically with
an injected `now`. Email sends are stubbed -- no SMTP, no network.
"""
from datetime import datetime
from unittest.mock import Mock

import pytest

from src.api.properties import APIPropertiesManager
from src.common import lifecycle, queries
from src.common.eventstate import seasonOpenString, seasonCloseString
from src.common.firebase import FirebaseService


class FakeResult:
    def __init__(self, value):
        self._value = value

    def val(self):
        return self._value


class FakeDB:
    """Nested-dict stand-in for the Realtime Database keyed by path segments."""

    def __init__(self, data=None):
        self.data = data or {}

    def get(self, children):
        node = self.data
        for child in children:
            if not isinstance(node, dict) or child not in node:
                return FakeResult(None)
            node = node[child]
        return FakeResult(node)

    def set(self, children, value):
        node = self.data
        for child in children[:-1]:
            node = node.setdefault(child, {})
        node[children[-1]] = value

    def remove(self, children):
        node = self.data
        for child in children[:-1]:
            if child not in node:
                return
            node = node[child]
        node.pop(children[-1], None)

    def listRootKeys(self):
        return list(self.data.keys())


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(FirebaseService, "get", fake.get)
    monkeypatch.setattr(FirebaseService, "set", fake.set)
    monkeypatch.setattr(FirebaseService, "remove", fake.remove)
    monkeypatch.setattr(FirebaseService, "listRootKeys", fake.listRootKeys)
    return fake


@pytest.fixture
def no_email(monkeypatch):
    """Stub both outgoing emails so reconcile never opens SMTP."""
    start = Mock()
    results = Mock()
    monkeypatch.setattr(lifecycle, "sendSeasonStartEmail", start)
    monkeypatch.setattr(queries, "emailResults", results)
    return start, results


def _meta(year, openTime=None, closeTime=None, resultsEmailed=False, startEmailed=False):
    return {
        "year": year,
        "openTime": openTime or seasonOpenString(year),
        "closeTime": closeTime or seasonCloseString(year),
        "resultsEmailed": resultsEmailed,
        "startEmailed": startEmailed,
    }


# --- getAllPastParticipantEmails -----------------------------------------

def test_collects_and_dedupes_emails_across_schemas(db):
    db.data.update({
        "halloween-event-2024": {"users": {
            "a": {"email": "A@X.com"}, "b": {"email": "b@x.com"}}},
        "halloween-event-2025": {"users": {
            "c": {"email": "a@x.com"},          # dup of A@X.com, different case
            "d": {"email": " "}}},              # blank -> skipped
        "halloween-event": {"users": {"e": {"email": "live@x.com"}}},
        "unrelated-node": {"users": {"z": {"email": "nope@x.com"}}},  # ignored
    })
    emails = sorted(e.lower() for e in lifecycle.getAllPastParticipantEmails())
    assert emails == ["a@x.com", "b@x.com", "live@x.com"]


# --- rolloverEvent --------------------------------------------------------

def test_rollover_archives_and_resets(db):
    db.data["halloween-event"] = {
        "meta": _meta(2026, resultsEmailed=True, startEmailed=True),
        "users": {"u1": {"name": "Alice", "email": "a@x.com", "score": 5}},
        "scoreboard": {"s1": {"winner": "Alice (5 pts)"}},
    }
    lifecycle.rolloverEvent(2026)

    assert db.data["halloween-event-2026"]["users"]["u1"]["name"] == "Alice"
    assert db.data["halloween-event-2026"]["scoreboard"]["s1"]["winner"] == "Alice (5 pts)"
    # live node reset to a fresh empty season 2027 (rule window, flags cleared)
    assert db.data["halloween-event"] == {"meta": _meta(2027)}


def test_rollover_skips_empty_node(db):
    db.data["halloween-event"] = {"meta": _meta(2026)}  # no users
    lifecycle.rolloverEvent(2026)
    assert "halloween-event-2026" not in db.data
    assert db.data["halloween-event"]["meta"]["year"] == 2027


def test_rollover_does_not_clobber_existing_archive(db):
    db.data["halloween-event-2026"] = {"users": {"old": {"email": "old@x.com"}}}
    db.data["halloween-event"] = {
        "meta": _meta(2026), "users": {"new": {"email": "new@x.com"}}}
    lifecycle.rolloverEvent(2026)
    assert db.data["halloween-event-2026"]["users"] == {"old": {"email": "old@x.com"}}


# --- ensureProvisioned ----------------------------------------------------

def test_provision_preseason_leaves_start_email_pending(db):
    lifecycle.ensureProvisioned(datetime(2026, 6, 6))
    assert db.data["halloween-event"]["meta"] == _meta(2026, startEmailed=False)


def test_provision_midseason_suppresses_start_email(db):
    lifecycle.ensureProvisioned(datetime(2026, 10, 15))
    assert db.data["halloween-event"]["meta"]["startEmailed"] is True


def test_provision_is_noop_when_meta_exists(db):
    db.data["halloween-event"] = {"meta": _meta(1999)}
    lifecycle.ensureProvisioned(datetime(2026, 10, 15))
    assert db.data["halloween-event"]["meta"]["year"] == 1999


# --- reconcileEventLifecycle ---------------------------------------------

def test_reconcile_sends_start_email_once_when_open(db, no_email):
    start, results = no_email
    db.data["halloween-event"] = {
        "meta": _meta(2026), "users": {"u": {"email": "a@x.com", "score": 1}}}

    lifecycle.reconcileEventLifecycle(datetime(2026, 10, 1, 0, 0, 1))
    assert start.call_count == 1
    assert db.data["halloween-event"]["meta"]["startEmailed"] is True
    results.assert_not_called()

    lifecycle.reconcileEventLifecycle(datetime(2026, 10, 2))  # already sent -> no-op
    assert start.call_count == 1


def test_reconcile_emails_results_once_at_close(db, no_email):
    start, results = no_email
    db.data["halloween-event"] = {
        "meta": _meta(2026, startEmailed=True), "users": {"u": {"email": "a@x.com", "score": 1}}}

    lifecycle.reconcileEventLifecycle(datetime(2026, 11, 1, 0, 0, 1))
    results.assert_called_once_with(2026)  # the season year drives the gift-card check
    assert db.data["halloween-event"]["meta"]["resultsEmailed"] is True

    lifecycle.reconcileEventLifecycle(datetime(2026, 11, 2))  # already emailed -> no-op
    assert results.call_count == 1


# --- sendSeasonStartEmail gift-card prize ----------------------------------

@pytest.fixture
def start_email_env(db, monkeypatch):
    """One past player + captured SMTP so sendSeasonStartEmail's body can be inspected."""
    db.data["halloween-event-2025"] = {"users": {"a": {"email": "past@x.com"}}}
    monkeypatch.setattr(APIPropertiesManager, "WEBAPP_HOST", "https://example.test")
    sent = []

    class _FakeSMTP:
        def __init__(self, host, port):
            pass

        def login(self, sender, password):
            pass

        def sendmail(self, sender, receivers, message):
            sent.append(message)

        def quit(self):
            pass

    monkeypatch.setattr(lifecycle.smtplib, "SMTP_SSL", _FakeSMTP)
    return sent


def _setGiftCard(monkeypatch, year):
    monkeypatch.setattr(APIPropertiesManager, "GIFT_CARD_LABEL", "$50 gift card")
    monkeypatch.setattr(APIPropertiesManager, "GIFT_CARD_CODE", "SPOOKY-123")
    monkeypatch.setattr(APIPropertiesManager, "GIFT_CARD_YEAR", year)


def test_season_start_email_announces_active_prize(start_email_env, monkeypatch):
    _setGiftCard(monkeypatch, "2026")
    lifecycle.sendSeasonStartEmail(2026)
    assert len(start_email_env) == 1
    assert "$50 gift card" in start_email_env[0]
    assert "SPOOKY-123" not in start_email_env[0]  # the code is never announced up front


def test_season_start_email_omits_stale_prize(start_email_env, monkeypatch):
    _setGiftCard(monkeypatch, "2025")  # last season's card -> say nothing
    lifecycle.sendSeasonStartEmail(2026)
    assert len(start_email_env) == 1
    assert "$50 gift card" not in start_email_env[0]
    assert "prize" not in start_email_env[0].lower()


def test_reconcile_rolls_over_at_next_october(db, no_email):
    start, results = no_email
    db.data["halloween-event"] = {
        "meta": _meta(2026, resultsEmailed=True, startEmailed=True),
        "users": {"u": {"email": "a@x.com", "score": 7}},
        "scoreboard": {"s": {"winner": "x"}}}

    lifecycle.reconcileEventLifecycle(datetime(2027, 10, 1, 0, 0, 1))

    assert db.data["halloween-event-2026"]["users"]["u"]["score"] == 7   # archived
    assert db.data["halloween-event"]["meta"]["year"] == 2027            # fresh season
    assert db.data["halloween-event"].get("users") is None              # wiped
    assert start.call_count == 1                                         # new-season email
