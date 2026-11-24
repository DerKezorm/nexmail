"""The profile: display name, username, language and address, changed by the person (and by the operator under
Accounts).

**Username:** everybody changes their own, within the rules and only when the name is free: no other account has it
now (without regard to case, unique in the database too, so that two changes at the same moment do not both get
through), had it once, or shows it as display name. An account with a password confirms with it. It counts at once;
sessions and devices stay (they hang on the account's id). The old name stays reserved for ever and keeps working only
for things in the background (calendar programs, an inbox folder), never for signing in. A confirmed address hears
"Your username is now …". A display name that is exactly the old username follows the new one; any other stays. The
operator changes it with the operator's own password, an operator without one after a fresh sign-in at the provider
(``actor_confirmed``).

**Display name:** unique (``names.display_key``), may be empty in the profile (the username shows).

**Language:** kept at the account, part of the profile.

**Address:** changed only with the password (an account without one: a fresh sign-in at the provider). With a mail
server a new one counts only after its confirmation link, until then the old one; without one at once. The old
address hears of the change where a mail can go. The link can be sent again. The operator may only take an address
away, never set one (or a password link could go to an address of the operator's choosing). Whenever the address in
effect changes, open links a person asked for to the old one stop counting.

**Address from a provider:** an account through a provider only follows the provider's address
(``follow_provider_email``), which never counts at once and never takes an address another account has.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import common, names
from .common import acting, address_hint, log, reload, tell
from .errors import AccountError
from .model import (
    EMAIL_OWN,
    EMAIL_PROVIDER,
    EVENT_EMAIL_CHANGED,
    EVENT_RENAMED,
    MAIL_CONFIRM_EMAIL,
    MAIL_EMAIL_CHANGED,
    MAIL_USERNAME_CHANGED,
    RESET_SELF,
    Account,
    AccountId,
    EmailChange,
    Event,
    Mail,
    Store,
    Taken,
)

#: How long the link that confirms an address holds.
CONFIRM_HOURS = 24


@dataclass(frozen=True)
class EmailChanged:
    """The account after the change. ``pending`` is the address that waits for its link (``mail`` says what to
    send), "" when the change counted at once. ``notice`` is the mail to the old address, where one can go."""

    account: Account
    pending: str = ""
    mail: Mail | None = None
    notice: Mail | None = None


def change_username(
    store: Store,
    account_id: AccountId,
    new: str,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
) -> Mail | None:
    """A new username for the account; the notice for its confirmed address, None when it has none or nothing
    changed. The store hears ``EVENT_RENAMED`` with the old and the new name after the commit."""
    target, actor = acting(store, account_id, actor_id, password, confirm_self=True, actor_confirmed=actor_confirmed)
    name = names.check_username(new)
    if name == target.username:
        return None
    if names.username_taken(store, name, except_id=target.id):
        raise AccountError("username_taken", "Someone has this username already.", 409)
    try:
        store.set_username(target.id, name)
        if target.display_name and target.display_name == target.username:
            store.set_display_name(target.id, name)
    except Taken as error:
        store.rollback()
        raise common.taken_error(error.what) from error
    store.commit()
    log().info("Username changed name=%s from=%s by=%s", name, target.username, actor.username)
    tell(store, Event(EVENT_RENAMED, target.id, old=target.username, new=name))
    if target.email and target.email_confirmed:
        return Mail(MAIL_USERNAME_CHANGED, target.email, target.id, name, target.display_name)
    return None


def change_display_name(
    store: Store,
    account_id: AccountId,
    new: str,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
) -> Account:
    """The display name; empty shows the username, another account's (or a username) is taken. One's own without a
    password, somebody else's as operator, confirmed."""
    target, actor = acting(store, account_id, actor_id, password, confirm_self=False, actor_confirmed=actor_confirmed)
    shown = names.check_display_name(store, new, target.id, required=False)
    try:
        store.set_display_name(target.id, shown)
    except Taken as error:
        store.rollback()
        raise common.taken_error(error.what) from error
    store.commit()
    if actor.id != target.id:
        log().info("Display name changed name=%s by=%s", target.username, actor.username)
    return reload(store, target.id)


def change_language(store: Store, account_id: AccountId, language: str) -> Account:
    """The account's own language; a tag that is none (or "") means the browser's."""
    account = common.account_or_404(store, account_id)
    store.set_language(account.id, common.clean_language(language))
    store.commit()
    return reload(store, account.id)


def _set_email(store: Store, account_id: AccountId, address: str, *, proven: bool) -> None:
    try:
        store.set_email(account_id, address, confirmed=True, proven=proven, source=EMAIL_OWN)
    except Taken as error:
        store.rollback()
        raise common.taken_error(error.what) from error


def _notice(account: Account, new: str) -> Mail | None:
    """To the old address after a change: only where it counted, and only when it is another than the new one."""
    if not account.email or not account.email_confirmed or names.same_address(account.email, new):
        return None
    return Mail(MAIL_EMAIL_CHANGED, account.email, account.id, account.username, account.display_name,
                new_hint=address_hint(new))


def change_email(
    store: Store,
    account_id: AccountId,
    new: str,
    *,
    password: str = "",
    actor_confirmed: bool = False,
    mail: bool = False,
) -> EmailChanged:
    """The account's own address, with its password (``actor_confirmed``: the app confirmed, an account without a
    password by a fresh sign-in at its provider). ``mail``: a mail server and the public address are there, so the
    new address waits for its link and the old one hears of a removal; otherwise it counts at once. "" takes the
    address away (and what waits)."""
    target, _ = acting(
        store, account_id, account_id, password, confirm_self=True, self_without_password=True,
        actor_confirmed=actor_confirmed,
    )
    address = names.clean_email(new)
    if not address:
        store.drop_email_change(target.id)
        store.set_email(target.id, "", confirmed=True, proven=False, source=EMAIL_OWN)
        store.drop_resets(target.id, origin=RESET_SELF)
        store.commit()
        log().info("Email removed name=%s", target.username)
        tell(store, Event(EVENT_EMAIL_CHANGED, target.id, old=target.email, new=""))
        return EmailChanged(reload(store, target.id), notice=_notice(target, "") if mail else None)
    if names.same_address(address, target.email) and target.email_confirmed and target.email_source == EMAIL_OWN:
        raise AccountError("email_same", "This is your address already.", 409)
    if names.email_taken(store, address, except_id=target.id):
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    if mail:
        token = common.new_token()
        store.start_email_change(target.id, address, token, common.utcnow() + timedelta(hours=CONFIRM_HOURS))
        store.commit()
        log().info("Email change waits for its link name=%s", target.username)
        letter = Mail(MAIL_CONFIRM_EMAIL, address, target.id, target.username, target.display_name, token,
                      CONFIRM_HOURS)
        return EmailChanged(reload(store, target.id), address, letter)
    store.drop_email_change(target.id)
    _set_email(store, target.id, address, proven=False)
    store.drop_resets(target.id, origin=RESET_SELF)
    store.commit()
    log().info("Email changed name=%s", target.username)
    tell(store, Event(EVENT_EMAIL_CHANGED, target.id, old=target.email, new=address))
    return EmailChanged(reload(store, target.id))


def resend_email_link(store: Store, account_id: AccountId) -> Mail:
    """"Send the link again": a new link for the address that waits (the one before stops counting), 24 hours from
    now. ``no_pending_email`` when nothing waits. The app's brake holds back a sender who asks too often."""
    account = common.account_or_404(store, account_id)
    if not account.pending_email:
        raise AccountError("no_pending_email", "No address waits for its link.", 409)
    token = common.new_token()
    store.start_email_change(account.id, account.pending_email, token, common.utcnow() + timedelta(hours=CONFIRM_HOURS))
    store.commit()
    return Mail(MAIL_CONFIRM_EMAIL, account.pending_email, account.id, account.username, account.display_name, token,
                CONFIRM_HOURS)


def _change(store: Store, token: str) -> tuple[EmailChange, Account]:
    change = store.find_email_change(token) if token else None
    if change is None:
        raise AccountError("email_link_invalid", "This link has been used already or is not valid any more.", 404)
    if common.expired(change.expires_at):
        raise AccountError("email_link_expired", "This link has expired.", 404)
    account = store.get_account(change.account_id)
    if account is None or account.blocked:
        raise AccountError("email_link_invalid", "This link has been used already or is not valid any more.", 404)
    return change, account


def email_change_state(store: Store, token: str) -> EmailChange:
    """The page of a confirmation link: which address it confirms (nothing is used up)."""
    return _change(store, token)[0]


def confirm_email(store: Store, token: str) -> EmailChanged:
    """The address of the link counts from now on and is proven. The link works once; an address another account
    took meanwhile is refused. ``notice`` goes to the old address."""
    change, account = _change(store, token)
    if not store.consume_email_change(change):
        store.rollback()
        raise AccountError("email_link_invalid", "This link has been used already or is not valid any more.", 404)
    if names.email_taken(store, change.address, except_id=account.id):
        store.rollback()
        raise AccountError("email_taken", "This address belongs to another account already.", 409)
    _set_email(store, account.id, change.address, proven=True)
    store.drop_resets(account.id, origin=RESET_SELF)
    store.commit()
    log().info("Email confirmed name=%s", account.username)
    tell(store, Event(EVENT_EMAIL_CHANGED, account.id, old=account.email, new=change.address))
    return EmailChanged(reload(store, account.id), notice=_notice(account, change.address))


def withdraw_email_change(store: Store, account_id: AccountId) -> None:
    """The address that waits for its link is withdrawn; the one in effect stays."""
    common.account_or_404(store, account_id)
    store.drop_email_change(account_id)
    store.commit()


def remove_email(
    store: Store,
    account_id: AccountId,
    *,
    actor_id: AccountId,
    password: str = "",
    actor_confirmed: bool = False,
    mail: bool = False,
) -> EmailChanged:
    """Take an account's address away (and what waits for a link). The operator can do this, never set one; the old
    address hears of it where a mail can go."""
    target, actor = acting(
        store, account_id, actor_id, password, confirm_self=True, self_without_password=True,
        actor_confirmed=actor_confirmed,
    )
    store.drop_email_change(target.id)
    store.set_email(target.id, "", confirmed=True, proven=False, source=EMAIL_OWN)
    store.drop_resets(target.id, origin=RESET_SELF)
    store.commit()
    log().info("Email removed name=%s by=%s", target.username, actor.username)
    tell(store, Event(EVENT_EMAIL_CHANGED, target.id, old=target.email, new=""))
    return EmailChanged(reload(store, target.id), notice=_notice(target, "") if mail else None)


def follow_provider_email(store: Store, account_id: AccountId, raw: str) -> bool:
    """What a provider says about the address of an account at a sign-in or a link, for the OIDC binding (inside its
    transaction: nothing is committed here). Only an account without an address of its own follows it: no address,
    or one that came from a provider. The provider's address never counts at once and is never proven (the provider
    may let anybody set any address), and it is never taken when another account has it. True when it was taken."""
    account = common.account_or_404(store, account_id)
    try:
        address = names.clean_email(raw)
    except AccountError:
        return False
    if not address or (account.email and account.email_source != EMAIL_PROVIDER):
        return False
    if names.same_address(address, account.email):
        return False
    if names.email_taken(store, address, except_id=account.id):
        log().warning("Provider address not taken, another account has it name=%s", account.username)
        return False
    store.set_email(account.id, address, confirmed=False, proven=False, source=EMAIL_PROVIDER)
    store.drop_resets(account.id, origin=RESET_SELF)
    log().info("Provider address followed name=%s", account.username)
    return True
