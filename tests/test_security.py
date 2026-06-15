"""Unit tests for src/common/security.py.

security.py is safely importable in isolation (no Flask/Firebase init at import time).
verifyTurnstile is tested by monkeypatching requests.post so no network is required.
"""
from unittest.mock import MagicMock

import pytest

from src.common.security import (constantTimeEquals, verifyTurnstile, escapeHtml,
                                  makeUnsubscribeToken, verifyUnsubscribeToken)


# --- constantTimeEquals ---------------------------------------------------

def test_constant_time_equals_match():
    assert constantTimeEquals("abc", "abc") is True


def test_constant_time_equals_mismatch():
    assert constantTimeEquals("abc", "xyz") is False


def test_constant_time_equals_empty():
    assert constantTimeEquals("", "") is True


def test_constant_time_equals_partial_mismatch():
    assert constantTimeEquals("abc", "abcd") is False


# --- verifyTurnstile ------------------------------------------------------

def test_verify_turnstile_empty_secret_bypasses(monkeypatch):
    called = []
    monkeypatch.setattr("src.common.security._requests.post",
                        lambda *a, **kw: called.append(True) or None)
    result = verifyTurnstile("", "some-token")
    assert result is True
    assert called == [], "should not call the network when secret is empty"


def test_verify_turnstile_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"success": True}
    monkeypatch.setattr("src.common.security._requests.post", lambda *a, **kw: mock_resp)
    assert verifyTurnstile("secret", "valid-token") is True


def test_verify_turnstile_failure(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}
    monkeypatch.setattr("src.common.security._requests.post", lambda *a, **kw: mock_resp)
    assert verifyTurnstile("secret", "bad-token") is False


def test_verify_turnstile_network_error(monkeypatch):
    def boom(*a, **kw):
        raise ConnectionError("network down")
    monkeypatch.setattr("src.common.security._requests.post", boom)
    assert verifyTurnstile("secret", "token") is False


# --- escapeHtml -----------------------------------------------------------

def test_escape_html_script_tag():
    result = escapeHtml("<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_escape_html_onerror_attribute():
    result = escapeHtml('<img src=x onerror=alert(1)>')
    assert "onerror" not in result or "&lt;" in result


def test_escape_html_plain_text_unchanged():
    assert escapeHtml("Alice") == "Alice"


def test_escape_html_ampersand():
    result = escapeHtml("Alice & Bob")
    assert "&amp;" in result


# --- unsubscribe token ----------------------------------------------------

def test_unsubscribe_token_round_trips():
    token = makeUnsubscribeToken("secret", "Player@X.com")
    assert verifyUnsubscribeToken("secret", "Player@X.com", token) is True


def test_unsubscribe_token_is_case_and_space_insensitive():
    # the link carries one spelling; verification normalizes both sides
    token = makeUnsubscribeToken("secret", "Player@X.com")
    assert verifyUnsubscribeToken("secret", "  player@x.com ", token) is True


def test_unsubscribe_token_rejects_tampered_or_empty_token():
    token = makeUnsubscribeToken("secret", "a@x.com")
    assert verifyUnsubscribeToken("secret", "a@x.com", token + "0") is False
    assert verifyUnsubscribeToken("secret", "a@x.com", "") is False


def test_unsubscribe_token_rejects_other_email():
    token = makeUnsubscribeToken("secret", "a@x.com")
    assert verifyUnsubscribeToken("secret", "b@x.com", token) is False


def test_unsubscribe_token_rejects_wrong_secret():
    token = makeUnsubscribeToken("secret", "a@x.com")
    assert verifyUnsubscribeToken("other-secret", "a@x.com", token) is False
