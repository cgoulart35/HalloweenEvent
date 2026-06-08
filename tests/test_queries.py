"""Unit tests for src/common/queries.py.

queries.py is safely importable in isolation: unlike api.py / app.py it does NOT
call app.run() or initialize Firebase / read env at import time. All Firebase
access goes through src.common.firebase.FirebaseService, whose methods we
monkeypatch here so the tests need no network, no env, and no live database.

These tests pin the core game logic so a dependency bump can't silently change
behavior.
"""
from unittest.mock import Mock

import pytest

from src.common import queries
from src.common.firebase import FirebaseService
from src.common.exceptions import NotAllowedToFightSelf, NotAllowedToFightAgain


class FakeResult:
    """Mimics the pyrebase query result object: only .val() is used by queries."""

    def __init__(self, value):
        self._value = value

    def val(self):
        return self._value


def make_get(users, scoreboard):
    """Return a fake FirebaseService.get dispatching on the child path.

    - ["halloween-event", "scoreboard"]        -> scoreboard payload
    - ["halloween-event", "users"]             -> all users
    - ["halloween-event", "users", <userKey>]  -> single user
    """

    def _get(children):
        if children[-1] == "scoreboard":
            return FakeResult(scoreboard)
        if len(children) >= 3 and children[1] == "users":
            return FakeResult(users.get(children[2]))
        if children[-1] == "users":
            return FakeResult(users)
        return FakeResult(None)

    return _get


@pytest.fixture
def users():
    return {
        "userA": {"name": "Alice", "email": "a@example.com", "score": 0},
        "userB": {"name": "Bob", "email": "b@example.com", "score": 0},
    }


# --- performFight ---------------------------------------------------------

def test_perform_fight_self_raises(monkeypatch, users):
    monkeypatch.setattr(FirebaseService, "get", make_get(users, None))
    with pytest.raises(NotAllowedToFightSelf):
        queries.performFight("userA", "userA", "06/05/26 01:00:00 PM")


def test_perform_fight_again_raises(monkeypatch, users):
    prior = [
        {
            "winnerKey": "userA",
            "loserKey": "userB",
            "winner": "Alice (2 pts)",
            "loser": "Bob (1 pts)",
            "time": "06/01/26 01:00:00 PM",
        }
    ]
    monkeypatch.setattr(FirebaseService, "get", make_get(users, prior))
    # scanned/scanner reversed from the prior event -> still the same pair
    with pytest.raises(NotAllowedToFightAgain):
        queries.performFight("userB", "userA", "06/05/26 01:00:00 PM")


def test_perform_fight_happy_path(monkeypatch, users):
    monkeypatch.setattr(FirebaseService, "get", make_get(users, None))
    set_mock = Mock()
    push_mock = Mock()
    monkeypatch.setattr(FirebaseService, "set", set_mock)
    monkeypatch.setattr(FirebaseService, "push", push_mock)
    # deterministic winner: first element of [scannedUserKey, scannerUserKey]
    monkeypatch.setattr(queries.random, "choice", lambda seq: seq[0])

    event = queries.performFight("userA", "userB", "06/05/26 01:00:00 PM")

    assert event["winnerKey"] == "userA"
    assert event["loserKey"] == "userB"
    assert event["winner"] == "Alice (2 pts)"   # winner gets +2
    assert event["loser"] == "Bob (1 pts)"      # loser gets +1
    assert event["time"] == "06/05/26 01:00:00 PM"
    set_mock.assert_any_call(["halloween-event", "users", "userA", "score"], 2)
    set_mock.assert_any_call(["halloween-event", "users", "userB", "score"], 1)
    push_mock.assert_called_once()


# --- getScoreboard --------------------------------------------------------

def test_get_scoreboard_sorts_newest_first(monkeypatch):
    data = {
        "k1": {"winner": "A", "loser": "B", "time": "06/01/26 01:00:00 PM"},
        "k2": {"winner": "C", "loser": "D", "time": "06/02/26 01:00:00 PM"},
    }
    monkeypatch.setattr(FirebaseService, "get", make_get({}, data))
    result = queries.getScoreboard()
    assert [e["time"] for e in result] == [
        "06/02/26 01:00:00 PM",
        "06/01/26 01:00:00 PM",
    ]


def test_get_scoreboard_empty(monkeypatch):
    monkeypatch.setattr(FirebaseService, "get", make_get({}, None))
    assert queries.getScoreboard() == []


# --- getTopScore ----------------------------------------------------------

def test_get_top_score(monkeypatch):
    users = {"a": {"score": 3}, "b": {"score": 7}, "c": {"score": 1}}
    monkeypatch.setattr(FirebaseService, "get", lambda children: FakeResult(users))
    assert queries.getTopScore() == 7


def test_get_top_score_empty(monkeypatch):
    monkeypatch.setattr(FirebaseService, "get", lambda children: FakeResult(None))
    assert queries.getTopScore() == 0


# --- emailResults ---------------------------------------------------------

def test_email_results_no_users_is_noop(monkeypatch):
    # A season with zero signups must return cleanly: raising here would leave
    # resultsEmailed unset, so reconcileEventLifecycle would retry emailResults()
    # every tick for the rest of the off-season. It must also not open SMTP.
    monkeypatch.setattr(FirebaseService, "get", lambda children: FakeResult(None))
    smtp = Mock()
    monkeypatch.setattr(queries.smtplib, "SMTP_SSL", smtp)
    assert queries.emailResults() is None
    smtp.assert_not_called()
