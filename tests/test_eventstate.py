"""Unit tests for the event-ended cutoff that switches the app into its closed
state (replaces the old kill -15 self-shutdown). Pure stdlib -- no network/env."""
from datetime import datetime, timedelta

from src.common.eventstate import eventHasEnded

FORMAT = "%m/%d/%y %I:%M:%S %p"


def test_not_ended_before_cutoff():
    future = (datetime.now() + timedelta(hours=1)).strftime(FORMAT)
    assert eventHasEnded(future) is False


def test_ended_after_cutoff():
    past = (datetime.now() - timedelta(hours=1)).strftime(FORMAT)
    assert eventHasEnded(past) is True
