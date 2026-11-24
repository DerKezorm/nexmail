"""The second factor: a time-based code (TOTP), recovery codes, the sign-in that waits for the code, the operator's
reset. Passkeys are in ``passkeys``.

TOTP after RFC 6238 with HMAC-SHA1, 30 seconds, 6 digits, one step either side: the values every app uses today, so
that the authenticator apps set up under the older version keep working (the seed is base32, sealed by the app).
A code counts once: the store keeps the last step with one statement that only moves forward (``claim_step``).

Recovery codes: 10 new ones (``xxxxx-xxxxx``, no 0, o, 1, l, i), stored as ``h1:`` + HMAC-SHA256 with the app's
key (``FactorStore.recovery_key``). Lists of the older versions keep working: a plain SHA-256 of the code in small
letters (most apps) or in capitals (one app) is recognised too, whatever the count.

Setting up keeps the new seed in memory for ten minutes and stores it only once a code confirmed it; nothing
unconfirmed is ever a factor. The sign-in that waits for the code is in memory for five minutes and five attempts.

Every change of a factor is confirmed: with the password (or a fresh sign-in at the provider for an account without one,
``actor_confirmed`` from the app), also when an account replaces its authenticator; wrong passwords there are braked
like sign-ins (``confirmed``). Only the very first factor of an account in a session that can only set one up needs
nothing more (the app passes ``actor_confirmed``).

Nobody must have a second factor unless the operator says so (``FactorStore.factor_required``, off by default); then
the last factor of an account cannot be taken away by its owner, and ``common.next_step`` sends an account without
one to set one up first.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from . import brake, common
from .common import log
from .errors import AccountError
from .model import (
    MAIL_FACTOR_RESET,
    SECOND_FACTOR_ACTIVE,
    SECOND_FACTOR_NONE,
    SECOND_FACTOR_REQUIRED,
    Account,
    AccountId,
    Mail,
    Store,
)
from .model2 import FactorStore, PasskeyStore

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1
SEED_BYTES = 20
ENROLMENT_SECONDS = 600
PENDING_SECONDS = 300
MAX_ATTEMPTS = 5
#: Waiting sign-ins per account at the same time (two browsers, or one that asked twice); the oldest goes.
WAITING_PER_ACCOUNT = 3
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_LENGTH = 10
RECOVERY_MARK = "h1:"


class AppStore(Store, FactorStore, PasskeyStore, Protocol):
    """One store of the app that answers the accounts, the second factor and the passkeys."""


# --- Codes ------------------------------------------------------------------------------------------------------------


def new_seed() -> str:
    """A fresh seed, base32 without padding, the way authenticator apps take it."""
    return base64.b32encode(secrets.token_bytes(SEED_BYTES)).decode("ascii").rstrip("=")


def _seed_bytes(seed: str) -> bytes:
    cleaned = (seed or "").strip().replace(" ", "").upper()
    if not cleaned:
        raise ValueError("an empty seed verifies nothing")
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def code_at(seed: str, moment: float) -> str:
    """The code for a point in time, RFC 6238 with HMAC-SHA1."""
    counter = int(moment) // STEP_SECONDS
    digest = hmac.new(_seed_bytes(seed), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10**DIGITS)).zfill(DIGITS)


def matching_step(seed: str, typed: str, now: float | None = None) -> int | None:
    """The time step a code belongs to, or None. Every candidate is compared in constant time."""
    code = typed.strip().replace(" ", "").replace("-", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int(time.time() if now is None else now) // STEP_SECONDS
    found = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(seed, step * STEP_SECONDS), code):
            found = step
    return found


def provisioning_uri(seed: str, issuer: str, label: str) -> str:
    """For the QR code: ``otpauth://totp/<issuer>:<label>``, the label being the username (as today)."""
    name = quote(f"{issuer}:{label}", safe=":")
    return (
        f"otpauth://totp/{name}?secret={seed}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}"
        f"&period={STEP_SECONDS}"
    )


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def _cleaned(code: str) -> str:
    return code.strip().replace("-", "").replace(" ", "")


def stored_form(key: bytes, code: str) -> str:
    return RECOVERY_MARK + hmac.new(key, _cleaned(code).lower().encode("utf-8"), hashlib.sha256).hexdigest()


def recognised_forms(key: bytes, code: str) -> tuple[str, ...]:
    """The forms a typed code may be stored in: the current one, and the plain SHA-256 of older versions, in small
    letters and in capitals."""
    cleaned = _cleaned(code)
    return (
        stored_form(key, code),
        hashlib.sha256(cleaned.lower().encode("utf-8")).hexdigest(),
        hashlib.sha256(cleaned.upper().encode("utf-8")).hexdigest(),
    )


# --- State ------------------------------------------------------------------------------------------------------------


def has_factor(store: FactorStore | AppStore, account_id: AccountId) -> bool:
    """A confirmed TOTP or a passkey."""
    if store.totp_seed(account_id):
        return True
    passkeys = getattr(store, "passkeys_of", None)
    return bool(passkeys and passkeys(account_id))


def state(store: AppStore, account_id: AccountId) -> str:
    """What ``Store.second_factor`` answers, for an app that lets the module decide: active, required (the operator
    asks one of everybody and the account has none), none."""
    if has_factor(store, account_id):
        return SECOND_FACTOR_ACTIVE
    return SECOND_FACTOR_REQUIRED if store.factor_required() else SECOND_FACTOR_NONE


# --- Confirming a change -------------------------------------------------------------------------------------------


def too_many_attempts(wait: float) -> AccountError:
    return AccountError(
        "too_many_attempts", "Too many attempts. Wait a moment.", 429, retry_after=max(1, int(wait + 0.999))
    )


def confirmed(
    store: Store, account: Account, password: str, actor_confirmed: bool, *, without_password: bool
) -> None:
    """``common.confirm`` behind the brake: a wrong password here counts at the account (``confirm:<id>``, five free)
    as a sign-in would, so that a session cannot guess the password through these pages."""
    if actor_confirmed or not account.has_password:
        common.confirm(store, account, password, actor_confirmed, without_password=without_password)
        return
    keys = (f"confirm:{account.id}",)
    wait = brake.BRAKE.claim(keys)
    if wait > 0:
        raise too_many_attempts(wait)
    common.confirm(store, account, password, actor_confirmed, without_password=without_password)
    brake.BRAKE.succeeded(keys)


# --- Setting up -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Enrolment:
    seed: str
    uri: str


@dataclass(frozen=True)
class Confirmed:
    """The factor counts; ``codes`` are shown once (only when the account had none)."""

    codes: list[str]


_enrolments: dict[AccountId, tuple[str, float]] = {}
_enrolments_lock = threading.Lock()


def begin_totp(store: AppStore, account_id: AccountId, *, issuer: str) -> Enrolment:
    """A new seed for the account, kept in memory for ten minutes; nothing is stored yet."""
    account = common.account_or_404(store, account_id)
    seed = new_seed()
    with _enrolments_lock:
        _enrolments[account.id] = (seed, time.monotonic() + ENROLMENT_SECONDS)
    return Enrolment(seed, provisioning_uri(seed, issuer, account.username))


def confirm_totp(
    store: AppStore, account_id: AccountId, code: str, *, password: str = "", actor_confirmed: bool = False
) -> Confirmed:
    """The code of the new seed confirms it: from now on it counts. Confirmed with the password (or by the app), except
    in a session that can only set up a factor (the app passes ``actor_confirmed``). Replacing an authenticator that
    is set up already needs the password, or a fresh sign-in for an account without one, like taking it away."""
    account = common.account_or_404(store, account_id)
    confirmed(store, account, password, actor_confirmed, without_password=has_factor(store, account.id))
    with _enrolments_lock:
        held = _enrolments.get(account.id)
    if held is None or held[1] < time.monotonic():
        raise AccountError("enrolment_expired", "That took too long. Start again.", 410)
    step = matching_step(held[0], code)
    if step is None:
        raise AccountError("code_wrong", "The code is wrong.", 422)
    with _enrolments_lock:
        _enrolments.pop(account.id, None)
    store.set_totp(account.id, held[0])
    store.claim_step(account.id, step)
    codes: list[str] = []
    if not store.recovery_hashes(account.id):
        codes = new_recovery_codes()
        key = store.recovery_key()
        store.set_recovery(account.id, [stored_form(key, entry) for entry in codes])
    store.commit()
    log().info("Second factor set up name=%s", account.username)
    return Confirmed(codes)


def new_codes(
    store: AppStore, account_id: AccountId, *, password: str = "", actor_confirmed: bool = False
) -> list[str]:
    """Ten new recovery codes; the old ones stop counting."""
    account = common.account_or_404(store, account_id)
    confirmed(store, account, password, actor_confirmed, without_password=True)
    if not has_factor(store, account.id):
        raise AccountError("factor_missing", "Set up a second factor first.", 409)
    codes = new_recovery_codes()
    key = store.recovery_key()
    store.set_recovery(account.id, [stored_form(key, entry) for entry in codes])
    store.commit()
    log().info("New recovery codes name=%s", account.username)
    return codes


def _last_factor_guard(store: AppStore, account_id: AccountId, *, removing_totp: bool, removing_passkey: bool) -> None:
    if not store.factor_required():
        return
    totp_left = bool(store.totp_seed(account_id)) and not removing_totp
    passkeys = len(store.passkeys_of(account_id)) - (1 if removing_passkey else 0)
    if not totp_left and passkeys <= 0:
        raise AccountError("factor_required", "A second factor is required here; set up another one first.", 409)


def disable_totp(
    store: AppStore, account_id: AccountId, *, password: str = "", actor_confirmed: bool = False
) -> None:
    """The owner takes the time-based code away (not the last factor where one is required)."""
    account = common.account_or_404(store, account_id)
    confirmed(store, account, password, actor_confirmed, without_password=True)
    _last_factor_guard(store, account.id, removing_totp=True, removing_passkey=False)
    store.set_totp(account.id, None)
    if not store.passkeys_of(account.id):
        store.set_recovery(account.id, [])
    store.commit()
    log().info("Second factor removed name=%s", account.username)


def operator_reset(
    store: AppStore,
    account_id: AccountId,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
    disconnect_devices: bool = True,
) -> Mail | None:
    """The operator takes every factor of another account away (time-based code, recovery codes, passkeys): its
    owner lost the phone. Every browser session and waiting sign-in of the account ends, and with
    ``disconnect_devices`` (on by default; the page asks "Disconnect the devices too") its paired devices too: the lost
    phone may be one of them. A confirmed address hears of it."""
    if account_id == actor_id:
        raise AccountError("use_account_page", "Change your own second factor in your profile.", 409)
    keys = (f"confirm:{actor_id}",)
    if not actor_confirmed:
        wait = brake.BRAKE.claim(keys)
        if wait > 0:
            raise too_many_attempts(wait)
    target, actor = common.acting(
        store, account_id, actor_id, password, confirm_self=True, actor_confirmed=actor_confirmed
    )
    if not actor_confirmed:
        brake.BRAKE.succeeded(keys)
    store.set_totp(target.id, None)
    store.set_recovery(target.id, [])
    store.remove_passkeys(target.id)
    store.end_sessions(target.id)
    if disconnect_devices:
        everywhere = getattr(store, "end_everywhere", None)
        if everywhere is not None:
            everywhere(target.id, None)
        else:
            store.revoke_access(target.id)
    drop_waiting(target.id)
    store.commit()
    log().warning("Second factor reset name=%s by=%s", target.username, actor.username)
    if target.email and target.email_confirmed:
        return Mail(MAIL_FACTOR_RESET, target.email, target.id, target.username, target.display_name)
    return None


# --- Checking a code ------------------------------------------------------------------------------------------------


def check_code(store: AppStore, account_id: AccountId, typed: str) -> str:
    """A time-based code or a recovery code of the account: ``"totp"`` or ``"recovery"``; ``code_wrong`` else.
    Each counts once, also for two requests at the same moment. Commits what it used up."""
    seed = store.totp_seed(account_id)
    if seed:
        step = matching_step(seed, typed)
        if step is not None and store.claim_step(account_id, step):
            store.commit()
            return "totp"
    hashes = store.recovery_hashes(account_id)
    if hashes and not typed.strip().isdigit():
        forms = recognised_forms(store.recovery_key(), typed)
        for stored in hashes:
            if any(hmac.compare_digest(stored, form) for form in forms):
                if store.claim_recovery(account_id, stored):
                    store.commit()
                    log().warning("Recovery code used account=%s left=%s", account_id, len(hashes) - 1)
                    return "recovery"
                break
    store.rollback()
    raise AccountError("code_wrong", "The code is wrong.", 422)


# --- The sign-in that waits for the code ------------------------------------------------------------------------------


@dataclass
class _Waiting:
    account_id: AccountId
    remember: bool
    provider_checked: bool
    until: float
    attempts: int = 0


@dataclass(frozen=True)
class Waited:
    """The waiting sign-in is done: the app starts the session with these."""

    account_id: AccountId
    remember: bool
    provider_checked: bool
    method: str


_waiting: dict[str, _Waiting] = {}
_waiting_lock = threading.Lock()


def _key(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def start_waiting(account_id: AccountId, *, remember: bool = True, provider_checked: bool = False) -> str:
    """After the password (or a provider that does not check the factor): the token of the waiting sign-in, for a
    cookie of five minutes. Up to three per account at the same time, the oldest goes: a stranger who knows the
    password cannot throw the owner's own waiting sign-in out with one of his own."""
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _waiting_lock:
        for key in [key for key, held in _waiting.items() if held.until < now]:
            _waiting.pop(key, None)
        mine = [key for key, held in _waiting.items() if held.account_id == account_id]
        for key in mine[: max(0, len(mine) - WAITING_PER_ACCOUNT + 1)]:
            _waiting.pop(key, None)
        _waiting[_key(token)] = _Waiting(account_id, remember, provider_checked, now + PENDING_SECONDS)
    return token


def drop_waiting(account_id: AccountId) -> None:
    """Every waiting sign-in of the account ends (new password, reset, block)."""
    with _waiting_lock:
        for key in [key for key, held in _waiting.items() if held.account_id == account_id]:
            _waiting.pop(key, None)


def waiting_account(token: str) -> AccountId | None:
    with _waiting_lock:
        held = _waiting.get(_key(token))
    return held.account_id if held is not None and held.until >= time.monotonic() else None


def finish_waiting(store: AppStore, token: str, typed: str) -> Waited:
    """The code for a waiting sign-in. Each attempt is counted before its code is checked, under the lock: five codes
    at most, also for many requests at the same moment; then it ends (the password is asked again). A blocked account
    is refused here too."""
    key = _key(token)
    with _waiting_lock:
        held = _waiting.get(key)
        if held is not None and (held.until < time.monotonic() or held.attempts >= MAX_ATTEMPTS):
            _waiting.pop(key, None)
            held = None
        if held is not None:
            held.attempts += 1
    if held is None:
        raise AccountError("sign_in_expired", "That took too long. Sign in again.", 401)
    account = store.get_account(held.account_id)
    if account is None or account.blocked:
        with _waiting_lock:
            _waiting.pop(key, None)
        raise AccountError("account_blocked", "This account is blocked. Ask the operator.", 403)
    try:
        method = check_code(store, held.account_id, typed)
    except AccountError:
        with _waiting_lock:
            if held.attempts >= MAX_ATTEMPTS:
                _waiting.pop(key, None)
        raise
    with _waiting_lock:
        _waiting.pop(key, None)
    return Waited(held.account_id, held.remember, held.provider_checked, method)


def finish_waiting_by_passkey(token: str, account_id: AccountId) -> Waited | None:
    """A passkey of the same account answered instead of a code (``passkeys.finish_sign_in``)."""
    key = _key(token)
    with _waiting_lock:
        held = _waiting.get(key)
        if held is None or held.until < time.monotonic() or held.account_id != account_id:
            return None
        _waiting.pop(key, None)
    return Waited(held.account_id, held.remember, held.provider_checked, "passkey")


def forget() -> None:
    """Tests: no enrolment and no waiting sign-in left."""
    with _enrolments_lock:
        _enrolments.clear()
    with _waiting_lock:
        _waiting.clear()
