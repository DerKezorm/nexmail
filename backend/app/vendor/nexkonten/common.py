"""What the flows share: time, tokens, the log, writing an account, who may act on whom, what follows a commit,
and which step of a session the app starts next."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime

from . import config
from .errors import AccountError
from .model import (
    NEXT_SECOND_FACTOR,
    NEXT_SECOND_FACTOR_SETUP,
    NEXT_SESSION,
    NEXT_SIGN_IN,
    SECOND_FACTOR_ACTIVE,
    SECOND_FACTOR_REQUIRED,
    Account,
    AccountId,
    Event,
    NewAccount,
    Store,
    Taken,
)

_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")


def log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


def utcnow() -> datetime:
    return datetime.now(UTC)


def expired(moment: datetime | None) -> bool:
    """A point in time that has passed; a time without a zone is read as UTC (as most apps store it)."""
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment <= utcnow()


def new_token() -> str:
    """The token of a link: 32 random bytes, URL-safe. The store keeps only a hash of it."""
    return secrets.token_urlsafe(32)


def clean_language(raw: str) -> str:
    """A language tag as the browser sends it (``de``, ``en-GB``), "" for anything else."""
    text = (raw or "").strip()
    return text if _LANGUAGE.fullmatch(text) else ""


def taken_error(what: str) -> AccountError:
    if what == "email":
        return AccountError("email_taken", "This address belongs to another account already.", 409)
    if what == "display_name":
        return AccountError("display_name_taken", "Another account shows this name already.", 409)
    return AccountError("username_taken", "Someone has this username already.", 409)


def add_account(store: Store, new: NewAccount) -> AccountId:
    """``store.add_account``; a refusal of the database (another account was faster) rolls back and becomes
    ``username_taken``, ``email_taken`` or ``display_name_taken``."""
    try:
        return store.add_account(new)
    except Taken as error:
        store.rollback()
        raise taken_error(error.what) from error


def account_or_404(store: Store, account_id: AccountId) -> Account:
    account = store.get_account(account_id)
    if account is None:
        raise AccountError("not_found", "No such account.", 404)
    return account


def reload(store: Store, account_id: AccountId) -> Account:
    """The account as the store holds it after a write; a store that loses it is broken."""
    account = store.get_account(account_id)
    if account is None:
        raise RuntimeError(f"account {account_id!r} is gone right after it was written")
    return account


def wrong_password() -> AccountError:
    return AccountError("wrong_password", "The password is wrong.", 401)


def fresh_sign_in_needed() -> AccountError:
    return AccountError(
        "fresh_sign_in_needed", "Confirm with a fresh sign-in at your provider: this account has no password.", 403
    )


def confirm(store: Store, account: Account, password: str, actor_confirmed: bool, *, without_password: bool) -> None:
    """The acting person shows it is them: with their password, or, when the app confirmed it already
    (``actor_confirmed``: a fresh sign-in at the provider for an account without a password, or the app's own check
    of the password with its brake), not again. ``without_password``: what an account without a password needs then
    (True: a fresh sign-in; False: nothing)."""
    if actor_confirmed:
        return
    if account.has_password:
        if not store.check_password(account.id, password or ""):
            raise wrong_password()
        return
    if without_password:
        raise fresh_sign_in_needed()


def acting(
    store: Store,
    account_id: AccountId,
    actor_id: AccountId,
    password: str,
    *,
    confirm_self: bool,
    self_without_password: bool = False,
    actor_confirmed: bool = False,
) -> tuple[Account, Account]:
    """The account acted on and the one acting. Somebody else's account: only an operator who is not blocked, with
    the operator's own password or, for an operator without one, a fresh sign-in at the provider (``actor_confirmed``
    from the app). One's own: confirmed where ``confirm_self`` (``self_without_password``: an account without a
    password needs a fresh sign-in too)."""
    target = account_or_404(store, account_id)
    if actor_id == account_id:
        if confirm_self:
            confirm(store, target, password, actor_confirmed, without_password=self_without_password)
        return target, target
    actor = store.get_account(actor_id)
    if actor is None or not actor.operator or actor.blocked:
        raise AccountError("not_allowed", "Only an operator may change another account.", 403)
    confirm(store, actor, password, actor_confirmed, without_password=True)
    return target, actor


def choose_days(days: int, choices: tuple[int, ...]) -> int:
    """How long a link holds, out of what the operator may choose."""
    if days not in choices:
        raise AccountError("invalid_days", f"Choose one of {', '.join(str(day) for day in choices)} days.", 422)
    return days


def tell(store: Store, event: Event) -> None:
    """``store.notify`` after a commit. Never raises: what the app does then cannot undo the outcome."""
    try:
        store.notify(event)
    except Exception as error:  # noqa: BLE001 (a follow-up of the app must never turn a done thing into an error)
        log().warning("Follow-up of %s failed for account %s: %r", event.kind, event.account_id, error)




def next_step(store: Store, account: Account) -> str:
    """What the app starts for an account that just got in (``NEXT_*`` in ``model``)."""
    if account.blocked:
        return NEXT_SIGN_IN
    state = store.second_factor(account.id)
    if state == SECOND_FACTOR_ACTIVE:
        return NEXT_SECOND_FACTOR
    if state == SECOND_FACTOR_REQUIRED:
        return NEXT_SECOND_FACTOR_SETUP
    return NEXT_SESSION


def address_hint(address: str) -> str:
    """An address as far as a stranger may read it: the first letter and the domain (``m***@example.com``)."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else ""
