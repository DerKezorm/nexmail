"""nexkonten: accounts, setup, invitation, signing in with a password, profile and a forgotten password, the same in
every nex app.

This package is vendored unchanged into ``backend/app/vendor/nexkonten/``. A test in the app compares the files with
the checksums in ``MANIFEST.json``, so a change is made in the module's source, never in the copy.

What lives here:

- ``config``: what the app tells the module about itself (``configure(AppConfig(...))``);
- ``model``: accounts, invitations, links, mails, and the ``Store`` the app implements over its database;
- ``names``: display name, username and address: rules, suggestion, numbering;
- ``visible``: what a display name shows, and the key under which look-alike names are equal;
- ``login``: "Username or email" and the password;
- ``setup``: the first account with the setup code;
- ``invites``: what the operator gives, the form and accepting an invitation;
- ``profiles``: changing username, display name and address, the confirmation link;
- ``resets``: a forgotten password, by mail or by a link from the operator;
- ``pictures``: a provider's picture, fetched with care.

Only httpx and Pillow are needed (for a provider's picture); nothing from an app is imported.
"""

from __future__ import annotations

from . import common, invites, login, names, pictures, profiles, resets, setup, visible
from .config import AppConfig, configure, current, use_transport
from .errors import CODES, AccountError, PictureRefused
from .model import (
    EMAIL_OWN,
    EMAIL_PROVIDER,
    EVENT_CREATED,
    EVENT_EMAIL_CHANGED,
    EVENT_JOINED,
    EVENT_PASSWORD_SET,
    EVENT_RENAMED,
    MAIL_CONFIRM_EMAIL,
    MAIL_EMAIL_CHANGED,
    MAIL_RESET,
    MAIL_USERNAME_CHANGED,
    NEXT_SECOND_FACTOR,
    NEXT_SECOND_FACTOR_SETUP,
    NEXT_SESSION,
    NEXT_SIGN_IN,
    PICTURE_NONE,
    PICTURE_OWN,
    PICTURE_PROVIDER,
    RESET_OPERATOR,
    RESET_SELF,
    RESET_SERVER,
    SECOND_FACTOR_ACTIVE,
    SECOND_FACTOR_NONE,
    SECOND_FACTOR_REQUIRED,
    Access,
    Account,
    AccountId,
    EmailChange,
    Event,
    Invite,
    Mail,
    NewAccount,
    Picture,
    Reset,
    Store,
    Taken,
)

__version__ = "0.2.1"

__all__ = [
    "CODES",
    "EMAIL_OWN",
    "EMAIL_PROVIDER",
    "EVENT_CREATED",
    "EVENT_EMAIL_CHANGED",
    "EVENT_JOINED",
    "EVENT_PASSWORD_SET",
    "EVENT_RENAMED",
    "MAIL_CONFIRM_EMAIL",
    "MAIL_EMAIL_CHANGED",
    "MAIL_RESET",
    "MAIL_USERNAME_CHANGED",
    "NEXT_SECOND_FACTOR",
    "NEXT_SECOND_FACTOR_SETUP",
    "NEXT_SESSION",
    "NEXT_SIGN_IN",
    "PICTURE_NONE",
    "PICTURE_OWN",
    "PICTURE_PROVIDER",
    "RESET_OPERATOR",
    "RESET_SELF",
    "RESET_SERVER",
    "SECOND_FACTOR_ACTIVE",
    "SECOND_FACTOR_NONE",
    "SECOND_FACTOR_REQUIRED",
    "Access",
    "Account",
    "AccountError",
    "AccountId",
    "AppConfig",
    "EmailChange",
    "Event",
    "Invite",
    "Mail",
    "NewAccount",
    "Picture",
    "PictureRefused",
    "Reset",
    "Store",
    "Taken",
    "__version__",
    "common",
    "configure",
    "current",
    "invites",
    "login",
    "names",
    "pictures",
    "profiles",
    "resets",
    "setup",
    "use_transport",
    "visible",
]
