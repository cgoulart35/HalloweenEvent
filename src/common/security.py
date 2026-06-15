import hashlib
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


def _normalizeEmail(email):
    return (email or "").strip().lower()


def makeUnsubscribeToken(secret, email):
    # Stateless unsubscribe token: HMAC-SHA256 of the normalized email keyed on the
    # shared API_KEY (identical in api.env/app.env). The API mints the link inside the
    # season-start email; the web app verifies it -- no per-user token has to be stored,
    # and you can't unsubscribe an arbitrary address without the secret. Normalizing the
    # email means the token is case-/whitespace-insensitive, matching the reminder list.
    return hmac.new((secret or "").encode(), _normalizeEmail(email).encode(),
                    hashlib.sha256).hexdigest()


def verifyUnsubscribeToken(secret, email, token):
    return constantTimeEquals(makeUnsubscribeToken(secret, email), token or "")
