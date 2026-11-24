"""Sessions: starting, checking, listing, signing out one or everywhere, "stay signed in", the cookie rules, and the
mark of a known browser.

A session is a random token in an HttpOnly cookie; the app keeps only its SHA-256 (hex, as every app does today, so
running sessions survive the change). "Stay signed in" (on by default): 30 days from the last use, sliding; without
it the cookie lives until the browser closes and the session at most 12 hours. A session that can only set up a
second factor lives 15 minutes.

"Where am I signed in" lists browsers and paired devices with a sign-out each. "Sign out everywhere" ends every
browser and paired device but the current one; calendar and address book programs, API keys and passkeys stay and are
listed apart (``Store.list_access``, "Disconnect all").

The mark of a known browser (``login.authenticate``'s ``known_browser``) holds no account id: ``<nonce>.<mac>`` per
account, the MAC over the account's random device key (``SessionStore.device_key``). A new device key (new password,
block, delete) makes every mark of the account worthless. A cookie holds the marks of up to five accounts.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import model2
from .common import utcnow
from .model import MAIL_NEW_SIGN_IN, Account, AccountId, Mail
from .model2 import (
    KIND_BROWSER,
    KIND_DEVICE,
    STAGE_FULL,
    STAGE_SETUP,
    Session,
    SessionStore,
)

REMEMBER_DAYS = 30
BROWSER_HOURS = 12
SETUP_MINUTES = 15
#: ``last_seen_at`` and the sliding end are written at most this often.
TOUCH_SECONDS = 300
#: The cookie of "stay signed in" outlives the session; the server decides.
REMEMBER_COOKIE_DAYS = 400
MARK_COOKIE_DAYS = 365
MARKS_MAX = 5


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Cookie:
    """What the app sets: ``max_age`` None for a cookie that ends with the browser."""

    name: str
    value: str
    max_age: int | None
    path: str = "/"
    http_only: bool = True
    same_site: str = "lax"
    secure: bool = False


@dataclass(frozen=True)
class Started:
    token: str
    session: Session
    cookie: Cookie


def _end_for(remember: bool, stage: str, now: datetime) -> datetime:
    if stage == STAGE_SETUP:
        return now + timedelta(minutes=SETUP_MINUTES)
    return now + (timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=BROWSER_HOURS))


def start(
    store: SessionStore,
    account_id: AccountId,
    *,
    cookie_name: str,
    secure: bool,
    remember: bool = True,
    stage: str = STAGE_FULL,
    provider_checked: bool = False,
    kind: str = model2.KIND_BROWSER,
    label: str = "",
    address: str = "",
    path: str = "/",
) -> Started:
    """A new session and the cookie for it. ``cookie_name`` is the app's own (with the suffix of the instance where
    it has one, ``nexlore_session`` without): running sessions keep their cookie."""
    now = utcnow()
    token = secrets.token_urlsafe(32)
    session = Session(
        uid=secrets.token_hex(12),
        account_id=account_id,
        kind=kind,
        created_at=now,
        expires_at=_end_for(remember, stage, now),
        last_seen_at=now,
        remember=remember,
        stage=stage,
        provider_checked=provider_checked,
        label=label[:200],
        address=address[:64],
    )
    store.add_session(session, hash_token(token))
    max_age = REMEMBER_COOKIE_DAYS * 86400 if remember and stage != STAGE_SETUP else None
    return Started(token, session, Cookie(cookie_name, token, max_age, path=path, secure=secure))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def current(store: SessionStore, token: str) -> Session | None:
    """The session of a cookie, or None (unknown, ended, run out, or not a session at all: a waiting sign-in never
    counts here, whatever its row says). A remembered session slides: its end moves to 30 days from now; every
    session's last use is written, both at most every five minutes. Whether the account may still use it (blocked,
    deleted) is the app's check, with ``account_out``; the stage (``STAGE_SETUP``) too."""
    if not token:
        return None
    session = store.session_by_hash(hash_token(token))
    now = utcnow()
    if session is None or session.kind not in (KIND_BROWSER, KIND_DEVICE) or _aware(session.expires_at) <= now:
        return None
    seen = _aware(session.last_seen_at) if session.last_seen_at else None
    if seen is None or (now - seen).total_seconds() > TOUCH_SECONDS:
        slides = session.remember and session.stage == STAGE_FULL
        store.touch_session(session.uid, now, now + timedelta(days=REMEMBER_DAYS) if slides else session.expires_at)
    return session


def account_out(account: Account | None) -> bool:
    """The account behind a session can no longer use it: gone, blocked or deleted. The app answers
    ``account_blocked`` to an open window instead of sending it to sign in."""
    return account is None or account.blocked


def finish_setup(store: SessionStore, session: Session) -> None:
    """The second factor is set up: the session becomes a full one (the app commits)."""
    store.set_stage(session.uid, STAGE_FULL)
    now = utcnow()
    store.touch_session(session.uid, now, _end_for(session.remember, STAGE_FULL, now))


def listing(store: SessionStore, account_id: AccountId, current_uid: str = "") -> list[dict[str, object]]:
    """"Where am I signed in": browsers and paired devices, newest use first, the current one marked."""
    rows = sorted(
        store.sessions_of(account_id),
        key=lambda row: _aware(row.last_seen_at or row.created_at),
        reverse=True,
    )
    return [
        {
            "uid": row.uid,
            "kind": row.kind,
            "label": row.label,
            "address": row.address,
            "created_at": row.created_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "current": row.uid == current_uid,
            "device": row.kind == KIND_DEVICE,
        }
        for row in rows
    ]


def new_sign_in(account: Account, *, known: bool, wanted: bool = True) -> Mail | None:
    """The mail "new sign-in" after a sign-in from a browser the account does not know yet (no valid mark,
    ``is_known``), to a confirmed address, unless the person turned it off (``wanted``, on by default). The app adds
    the browser and the time (``post.letters.from_account_mail(..., where=...)``)."""
    if known or not wanted or not account.email or not account.email_confirmed:
        return None
    return Mail(MAIL_NEW_SIGN_IN, account.email, account.id, account.username, account.display_name)


def sign_out(store: SessionStore, account_id: AccountId, uid: str) -> bool:
    """One entry of the list ends (only the account's own)."""
    return store.end_session(account_id, uid)


def sign_out_everywhere(store: SessionStore, account_id: AccountId, *, keep_uid: str | None = None) -> int:
    """Every browser and paired device but ``keep_uid``; programs, API keys, passkeys stay."""
    return store.end_everywhere(account_id, keep_uid)


# --- Known browser ------------------------------------------------------------------------------------------------


def _mac(secret: bytes, device_key: str, nonce: str) -> str:
    return hmac.new(secret, f"known-browser|{device_key}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]


def mark(secret: bytes, device_key: str) -> str:
    """A new mark for an account: random, signed with the server's secret over the account's device key."""
    nonce = secrets.token_urlsafe(12)
    return f"{nonce}.{_mac(secret, device_key, nonce)}"


def add_mark(cookie: str, new: str) -> str:
    """The cookie with one more mark (the newest first, at most five)."""
    marks = [entry for entry in (cookie or "").split("~") if entry and entry != new]
    return "~".join([new, *marks][:MARKS_MAX])


def is_known(
    cookie: str, secret: bytes, device_key: str, *, older: Callable[[str], bool] | None = None
) -> bool:
    """Whether the cookie holds a valid mark for the account with ``device_key``. ``older`` checks one entry in the
    format of the app's older version (one version long, so that owners stay known)."""
    for entry in (cookie or "").split("~")[:MARKS_MAX]:
        nonce, _, mac = entry.partition(".")
        if nonce and mac and "." not in mac and hmac.compare_digest(_mac(secret, device_key, nonce), mac):
            return True
        if older is not None and older(entry):
            return True
    return False
