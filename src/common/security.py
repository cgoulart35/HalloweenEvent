import hmac
import requests as _requests
from markupsafe import escape as _escape


def constantTimeEquals(a, b):
    try:
        return hmac.compare_digest(a.encode() if isinstance(a, str) else a,
                                   b.encode() if isinstance(b, str) else b)
    except Exception:
        return False


def verifyTurnstile(secret, token, remoteip=None):
    # When secret is blank, CAPTCHA is disabled (local/QA dev mode).
    if not secret:
        return True
    payload = {"secret": secret, "response": token or ""}
    if remoteip:
        payload["remoteip"] = remoteip
    try:
        resp = _requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload,
            timeout=5,
        )
        return resp.json().get("success", False)
    except Exception:
        return False


def escapeHtml(s):
    return str(_escape(s))
