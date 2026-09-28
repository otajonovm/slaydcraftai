"""Validation of Telegram Mini App init data.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode

INIT_DATA_MAX_AGE = 2 * 24 * 3600


@dataclass(frozen=True, slots=True)
class WebAppAuth:
    user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None
    photo_url: str | None
    start_param: str | None

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)


def validate_init_data(init_data: str, bot_token: str, max_age: int = INIT_DATA_MAX_AGE) -> WebAppAuth | None:
    """Returns the authenticated user or None if the signature is invalid or expired."""
    if not init_data:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None

    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age and time.time() - auth_date > max_age:
        return None

    try:
        user: dict[str, Any] = json.loads(data.get("user") or "{}")
        user_id = int(user["id"])
    except (ValueError, KeyError, TypeError):
        return None

    return WebAppAuth(
        user_id=user_id,
        first_name=str(user.get("first_name") or ""),
        last_name=user.get("last_name") or None,
        username=user.get("username") or None,
        language_code=user.get("language_code") or None,
        photo_url=user.get("photo_url") or None,
        start_param=data.get("start_param") or None,
    )


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Builds a signed init data string (used by tests and local tooling)."""
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signed = dict(fields, hash=hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest())
    return urlencode(signed)
