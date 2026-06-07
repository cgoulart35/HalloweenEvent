"""Unit tests for the seasonal open/closed calendar in src/common/eventstate.py.
Pure stdlib + monkeypatched FirebaseService -- no network/env/database."""
from datetime import datetime

from src.common import eventstate
from src.common.eventstate import (
    currentEventYear,
    eventIsOpen,
    getCurrentSeasonWindow,
    seasonCloseString,
    seasonOpenString,
    seasonOpenDatetime,
    seasonCloseDatetime,
)
from src.common.firebase import FirebaseService


class FakeResult:
    def __init__(self, value):
        self._value = value

    def val(self):
        return self._value


# --- season window math ---------------------------------------------------

def test_season_window_is_october():
    assert seasonOpenDatetime(2026) == datetime(2026, 10, 1, 0, 0, 0)
    assert seasonCloseDatetime(2026) == datetime(2026, 11, 1, 0, 0, 0)
    assert seasonOpenString(2026) == "10/01/26 12:00:00 AM"
    assert seasonCloseString(2026) == "11/01/26 12:00:00 AM"


def test_event_open_only_during_october():
    open_, close_ = seasonOpenString(2026), seasonCloseString(2026)
    assert eventIsOpen(open_, close_, datetime(2026, 6, 6)) is False          # pre-season
    assert eventIsOpen(open_, close_, datetime(2026, 10, 1, 0, 0, 0)) is True  # opens at midnight Oct 1
    assert eventIsOpen(open_, close_, datetime(2026, 10, 31, 23, 59)) is True  # last minute of Halloween
    assert eventIsOpen(open_, close_, datetime(2026, 11, 1, 0, 0, 0)) is False # closes at midnight Nov 1
    assert eventIsOpen(open_, close_, datetime(2027, 2, 1)) is False           # post-season


# --- year selection -------------------------------------------------------

def test_current_event_year():
    assert currentEventYear(datetime(2026, 6, 6)) == 2026    # before this year's close
    assert currentEventYear(datetime(2026, 10, 15)) == 2026  # in-season
    assert currentEventYear(datetime(2026, 11, 2)) == 2027   # after close -> next season


# --- getCurrentSeasonWindow (DB-backed with calendar fallback) ------------

def test_get_current_season_window_from_meta(monkeypatch):
    meta = {"openTime": "10/01/31 12:00:00 AM", "closeTime": "11/01/31 12:00:00 AM"}
    monkeypatch.setattr(FirebaseService, "get", lambda children: FakeResult(meta))
    assert getCurrentSeasonWindow() == ("10/01/31 12:00:00 AM", "11/01/31 12:00:00 AM")


def test_get_current_season_window_falls_back_on_error(monkeypatch):
    def boom(children):
        raise RuntimeError("firebase down")
    monkeypatch.setattr(FirebaseService, "get", boom)
    year = currentEventYear()
    assert getCurrentSeasonWindow() == (seasonOpenString(year), seasonCloseString(year))
