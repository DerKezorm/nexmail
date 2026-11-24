"""Passkeys: signing in with finger, face or the device's PIN, without a password, and as a second factor.

Built on ``webauthn`` (3.0.1) as nexpaper and nexdiary do: a key that lives on the device (discoverable), user
verification required, signing in without a username (the browser offers whichever passkey of this site it holds).
The relying party is the public address of the app: its host is the ``rp_id``, its origin the one the browser must
report. Challenges live five minutes in memory and count once. The sign count only moves forward (``claim_counter``).

The operator turns passkeys on or off for the server (``PasskeyStore.passkeys_allowed``, on by default); off, no new
passkey is added and none signs in, but none is deleted.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from . import common
from .common import log
from .errors import AccountError
from .model import Account, AccountId, Store
from .model2 import FactorStore, Passkey, PasskeyStore

CHALLENGE_SECONDS = 300
MAX_PASSKEYS = 10
NAME_MAX = 60
#: Open sign-in challenges at most (a sender cannot fill the memory).
MAX_OPEN = 5000


class AppStore(Store, FactorStore, PasskeyStore, Protocol):
    """One store of the app for accounts, second factor and passkeys."""


@dataclass(frozen=True)
class Party:
    """Where passkeys belong: the host of the public address, and its origin."""

    rp_id: str
    origin: str


def party(public_url: str) -> Party:
    """The relying party of an app from its public address (``https://notes.example.com``)."""
    parts = urlsplit(public_url.strip())
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https"):
        raise AccountError("passkeys_off", "Passkeys need the public address of the app.", 409)
    return Party(host, f"{parts.scheme}://{parts.netloc.lower()}")


_challenges: dict[str, tuple[bytes, AccountId | None, float]] = {}
_lock = threading.Lock()


def _keep(key: str, challenge: bytes, account_id: AccountId | None) -> None:
    now = time.monotonic()
    with _lock:
        for old in [old for old, held in _challenges.items() if held[2] < now]:
            _challenges.pop(old, None)
        if len(_challenges) >= MAX_OPEN:
            raise AccountError("too_many_attempts", "Too many open sign-ins. Try again in a moment.", 429)
        _challenges[key] = (challenge, account_id, now + CHALLENGE_SECONDS)


def _take(key: str) -> tuple[bytes, AccountId | None] | None:
    with _lock:
        held = _challenges.pop(key, None)
    if held is None or held[2] < time.monotonic():
        return None
    return held[0], held[1]


def _allowed(store: AppStore) -> None:
    if not store.passkeys_allowed():
        raise AccountError("passkeys_off", "Passkeys are turned off on this server.", 409)


def clean_name(name: str) -> str:
    """One line, no control characters, at most ``NAME_MAX``; "Passkey" when nothing is left."""
    text = " ".join("".join(char if char.isprintable() else " " for char in (name or "")).split())
    return text[:NAME_MAX] or "Passkey"


def begin_register(store: AppStore, account_id: AccountId, where: Party, *, app_name: str) -> tuple[str, str]:
    """A new passkey for the signed-in account: the token for the browser's cookie and the options (JSON)."""
    _allowed(store)
    account = common.account_or_404(store, account_id)
    keys = store.passkeys_of(account.id)
    if len(keys) >= MAX_PASSKEYS:
        raise AccountError("too_many_passkeys", f"At most {MAX_PASSKEYS} passkeys per account.", 409)
    token = secrets.token_urlsafe(32)
    challenge = secrets.token_bytes(32)
    _keep("add:" + token, challenge, account.id)
    options = generate_registration_options(
        rp_id=where.rp_id,
        rp_name=app_name,
        user_id=store.user_handle(account.id),
        user_name=account.username,
        user_display_name=account.display_name or account.username,
        challenge=challenge,
        timeout=CHALLENGE_SECONDS * 1000,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=key.credential_id) for key in keys],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return token, options_to_json(options)


def finish_register(
    store: AppStore, account_id: AccountId, token: str, credential: dict[str, Any], where: Party, *, name: str = ""
) -> Passkey:
    """The browser's answer to ``begin_register``: the new passkey, stored."""
    _allowed(store)
    held = _take("add:" + (token or ""))
    if held is None or held[1] != account_id:
        raise AccountError("passkey_expired", "That took too long. Start again.", 410)
    account = common.account_or_404(store, account_id)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=held[0],
            expected_rp_id=where.rp_id,
            expected_origin=where.origin,
            require_user_verification=True,
        )
    except Exception as error:  # webauthn raises many kinds for a bad answer
        log().warning("Passkey not added name=%s: %s", account.username, error.__class__.__name__)
        raise AccountError("passkey_invalid", "The browser's answer did not check out.", 422) from error
    if store.find_passkey(verified.credential_id) is not None:
        raise AccountError("passkey_exists", "This passkey is registered already.", 409)
    passkey = Passkey(
        uid=secrets.token_hex(16),
        account_id=account.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=clean_name(name),
        created_at=common.utcnow(),
    )
    store.add_passkey(passkey)
    store.commit()
    log().info("Passkey added name=%s", account.username)
    return passkey


def begin_sign_in(store: AppStore, where: Party) -> tuple[str, str]:
    """A sign-in with a passkey and nothing else: the token for the browser's cookie and the options (JSON)."""
    _allowed(store)
    token = secrets.token_urlsafe(32)
    challenge = secrets.token_bytes(32)
    _keep("in:" + token, challenge, None)
    options = generate_authentication_options(
        rp_id=where.rp_id,
        challenge=challenge,
        timeout=CHALLENGE_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return token, options_to_json(options)


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _credential_id(credential: dict[str, Any]) -> bytes | None:
    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str) or len(raw) > 1400:
        return None
    try:
        return _decode(raw)
    except (ValueError, binascii.Error):
        return None


def refused() -> AccountError:
    return AccountError("passkey_invalid", "This passkey did not sign you in.", 401)


def finish_sign_in(store: AppStore, token: str, credential: dict[str, Any], where: Party) -> Account:
    """The account whose passkey answered. The challenge counts once, whatever the answer; a blocked account hears so
    only after a valid answer. The app starts the session (a passkey is both factors: no code is asked)."""
    _allowed(store)
    held = _take("in:" + (token or ""))
    if held is None:
        raise AccountError("passkey_expired", "That took too long. Start again.", 410)
    credential_id = _credential_id(credential)
    key = store.find_passkey(credential_id) if credential_id else None
    account = store.get_account(key.account_id) if key is not None else None
    if key is None or account is None:
        log().warning("Passkey sign-in with an unknown passkey")
        raise refused()
    response = credential.get("response")
    handle = response.get("userHandle") if isinstance(response, dict) else None
    if handle:
        try:
            same = secrets.compare_digest(_decode(str(handle)), store.user_handle(account.id))
        except (ValueError, binascii.Error):
            same = False
        if not same:
            log().warning("Passkey sign-in with the handle of another account name=%s", account.username)
            raise refused()
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=held[0],
            expected_rp_id=where.rp_id,
            expected_origin=where.origin,
            credential_public_key=key.public_key,
            credential_current_sign_count=key.sign_count,
            require_user_verification=True,
        )
    except Exception as error:  # webauthn raises many kinds for a bad answer
        log().warning("Passkey refused name=%s: %s", account.username, error.__class__.__name__)
        raise refused() from error
    if not store.claim_counter(key.uid, key.sign_count, verified.new_sign_count):
        store.rollback()
        raise refused()
    store.commit()
    if account.blocked:
        raise AccountError("account_blocked", "This account is blocked. Ask the operator.", 403)
    log().info("Signed in with a passkey name=%s", account.username)
    return account


def remove(
    store: AppStore, account_id: AccountId, uid: str, *, password: str = "", actor_confirmed: bool = False
) -> bool:
    """The owner removes one of their passkeys (not the last factor where one is required)."""
    account = common.account_or_404(store, account_id)
    common.confirm(store, account, password, actor_confirmed, without_password=True)
    if store.factor_required() and not store.totp_seed(account.id) and len(store.passkeys_of(account.id)) <= 1:
        raise AccountError("factor_required", "A second factor is required here; set up another one first.", 409)
    removed = store.remove_passkey(account.id, uid)
    store.commit()
    return removed


def view(passkey: Passkey) -> dict[str, object]:
    """What the profile lists of a passkey (never the key itself)."""
    return {
        "uid": passkey.uid,
        "name": passkey.name,
        "created_at": passkey.created_at.isoformat(),
        "last_used_at": passkey.last_used_at.isoformat() if passkey.last_used_at else None,
    }


def options_json(options: str) -> dict[str, Any]:
    """The options as a dict (for apps that wrap them into their answer)."""
    return dict(json.loads(options))


def forget() -> None:
    """Tests: no open challenge left."""
    with _lock:
        _challenges.clear()
