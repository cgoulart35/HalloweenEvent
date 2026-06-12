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

from src.api.properties import APIPropertiesManager
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
    assert queries.emailResults(2026) is None
    smtp.assert_not_called()


# --- gift card prize -------------------------------------------------------

def _setGiftCard(monkeypatch, label="$50 gift card", code="SPOOKY-123", year="2026"):
    monkeypatch.setattr(APIPropertiesManager, "GIFT_CARD_LABEL", label)
    monkeypatch.setattr(APIPropertiesManager, "GIFT_CARD_CODE", code)
    monkeypatch.setattr(APIPropertiesManager, "GIFT_CARD_YEAR", year)


def _fight(winnerKey, loserKey, time):
    return {"winner": "x", "loser": "y", "winnerKey": winnerKey, "loserKey": loserKey, "time": time}


@pytest.fixture
def sent_mail(monkeypatch):
    """Capture (receivers, message) for every sendmail call; never opens real SMTP."""
    sent = []

    class _FakeSMTP:
        def __init__(self, host, port):
            pass

        def login(self, sender, password):
            pass

        def sendmail(self, sender, receivers, message):
            sent.append((receivers, message))

        def quit(self):
            pass

    monkeypatch.setattr(queries.smtplib, "SMTP_SSL", _FakeSMTP)
    return sent


def test_gift_card_inactive_by_default():
    # properties never loaded in tests (None) -> feature fully dormant
    assert queries.getActiveGiftCard(2026) is None


@pytest.mark.parametrize("label,code,year", [
    ("", "SPOOKY-123", "2026"),                # missing label
    ("$50 gift card", "", "2026"),             # missing code
    ("$50 gift card", "SPOOKY-123", ""),       # missing year
    ("$50 gift card", "SPOOKY-123", "2025"),   # stale year
    ("$50 gift card", "SPOOKY-123", "2027"),   # accidentally future year
])
def test_gift_card_inactive_when_incomplete_or_wrong_year(monkeypatch, label, code, year):
    _setGiftCard(monkeypatch, label, code, year)
    assert queries.getActiveGiftCard(2026) is None


def test_gift_card_active_when_complete_and_year_matches(monkeypatch):
    _setGiftCard(monkeypatch)
    assert queries.getActiveGiftCard(2026) == ("$50 gift card", "SPOOKY-123")


def test_pick_winner_single_top_scorer():
    users = {"a": {"score": 4}, "b": {"score": 2}}
    assert queries.pickGiftCardWinner(users, [], 4) == "a"


def test_pick_winner_tie_broken_by_most_wins():
    # a and b both finish on 4 points, but a has 2 wins to b's 1; b finished
    # fighting earlier, so a winning proves wins outrank the time tiebreak
    users = {"a": {"score": 4}, "b": {"score": 4}}
    scoreboard = [
        _fight("b", "x", "10/01/26 01:00:00 PM"),
        _fight("z", "b", "10/01/26 02:00:00 PM"),
        _fight("w", "b", "10/01/26 03:00:00 PM"),
        _fight("a", "x", "10/02/26 01:00:00 PM"),
        _fight("a", "y", "10/03/26 01:00:00 PM"),
    ]
    assert queries.pickGiftCardWinner(users, scoreboard, 4) == "a"


def test_pick_winner_tie_broken_by_earliest_final_score():
    # equal score AND equal wins -> whoever reached their final score first
    users = {"a": {"score": 2}, "b": {"score": 2}}
    scoreboard = [
        _fight("b", "y", "10/06/26 01:00:00 PM"),
        _fight("a", "x", "10/05/26 01:00:00 PM"),
    ]
    assert queries.pickGiftCardWinner(users, scoreboard, 2) == "a"


def test_pick_winner_full_tie_falls_back_to_earliest_signup():
    # nobody fought (top score 0): Firebase push keys are chronological -> lowest key
    users = {"k2": {"score": 0}, "k1": {"score": 0}}
    assert queries.pickGiftCardWinner(users, [], 0) == "k1"


def test_email_results_sends_code_to_exactly_one_winner(monkeypatch, sent_mail):
    _setGiftCard(monkeypatch)
    # Alice and Bob tie at 4 points with 2 wins each; Alice finished first (10/01
    # 02:00 PM vs 04:00 PM) so the earliest-final-score tiebreak picks her
    users = {
        "k1": {"name": "Alice", "email": "a@x.com", "score": 4},
        "k2": {"name": "Bob", "email": "b@x.com", "score": 4},
        "k3": {"name": "Eve", "email": "e@x.com", "score": 2},
        "k4": {"name": "Fred", "email": "f@x.com", "score": 2},
    }
    scoreboard = {
        "s1": _fight("k1", "k3", "10/01/26 01:00:00 PM"),
        "s2": _fight("k1", "k4", "10/01/26 02:00:00 PM"),
        "s3": _fight("k2", "k3", "10/01/26 03:00:00 PM"),
        "s4": _fight("k2", "k4", "10/01/26 04:00:00 PM"),
    }
    monkeypatch.setattr(FirebaseService, "get", make_get(users, scoreboard))

    queries.emailResults(2026)

    assert len(sent_mail) == 4
    withCode = [(receivers, message) for receivers, message in sent_mail if "SPOOKY-123" in message]
    assert len(withCode) == 1
    assert withCode[0][0] == ["a@x.com"]
    # a short code uses the letter-spaced code box, not a link
    assert "redeem with this code:" in withCode[0][1]
    assert "<a href=" not in withCode[0][1]
    # everyone is told what the prize was and who claimed it (incl. the tie note)
    for _, message in sent_mail:
        assert "$50 gift card" in message
        assert "goes to <strong>Alice</strong>" in message
        assert "Tie broken by most fight wins" in message


def test_email_results_renders_url_code_as_link(monkeypatch, sent_mail):
    # When the code is a redemption URL it becomes a tappable link (not a
    # letter-spaced code box), and query-string ampersands are HTML-escaped.
    url = "https://www.amazon.com/gc/redeem?code=ABC-123&x=1"
    _setGiftCard(monkeypatch, code=url)
    users = {
        "k1": {"name": "Alice", "email": "a@x.com", "score": 4},
        "k2": {"name": "Bob", "email": "b@x.com", "score": 2},
    }
    scoreboard = {"s1": _fight("k1", "k2", "10/01/26 01:00:00 PM")}
    monkeypatch.setattr(FirebaseService, "get", make_get(users, scoreboard))

    queries.emailResults(2026)

    winner = [m for r, m in sent_mail if r == ["a@x.com"]][0]
    loser = [m for r, m in sent_mail if r == ["b@x.com"]][0]
    assert 'href="https://www.amazon.com/gc/redeem?code=ABC-123&amp;x=1"' in winner
    assert "redeem here:" in winner
    assert "redeem with this code:" not in winner  # URL branch, not the code box
    assert "<a href=" not in loser                  # only the winner gets the link


def test_email_results_inactive_gift_card_mentions_nothing(monkeypatch, sent_mail):
    _setGiftCard(monkeypatch, year="2025")  # stale year -> dormant
    users = {
        "k1": {"name": "Alice", "email": "a@x.com", "score": 2},
        "k2": {"name": "Bob", "email": "b@x.com", "score": 1},
    }
    scoreboard = {"s1": _fight("k1", "k2", "10/01/26 01:00:00 PM")}
    monkeypatch.setattr(FirebaseService, "get", make_get(users, scoreboard))

    queries.emailResults(2026)

    assert len(sent_mail) == 2
    for _, message in sent_mail:
        assert "SPOOKY-123" not in message
        assert "$50 gift card" not in message
        assert "prize" not in message.lower()
