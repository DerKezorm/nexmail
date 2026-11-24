"""The app's store for the OIDC module answers with nexkonten: the same naming rules, reserved names, a display name
from the provider only when nobody else shows it, the provider's address never counting at once and never another
account's."""

from __future__ import annotations

from typing import Any

from konten_contract import password


def _create(app: Any, **values: Any) -> Any:
    arguments: dict[str, Any] = {"invite": None, "email": None, "display_name": "", "picture": ""}
    arguments.update(values)
    name = arguments.pop("name", "newcomer")
    with app.oidc_store() as oidc:
        created = oidc.create_account(name, **arguments)
        oidc.commit()
    return app.account_of(created)


def test_the_oidc_store_takes_the_naming_rules_of_konten(app: Any) -> None:
    with app.oidc_store() as oidc:
        assert oidc.clean_name("Max Müller") == "max-mueller"
        assert oidc.clean_name("max-2") == "max-2"
        assert oidc.clean_name("🦊") == ""


def test_a_former_name_and_a_display_name_are_taken_for_the_oidc_module(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    app.seed("kim", display_name="Chef", password=password())
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret)
    with app.oidc_store() as oidc:
        assert oidc.name_taken("ALEX") and oidc.name_taken("alexa") and oidc.name_taken("chef")
        assert not oidc.name_taken("nobody")


def test_a_display_name_from_the_provider_that_another_account_shows_stays_empty(app: Any) -> None:
    app.seed("kim", display_name="Kim Lee", password=password())
    taken = _create(app, name="kim2", display_name="KIM LEE")
    free = _create(app, name="alex", display_name="Alex Example")
    with app.store() as store:
        assert store.get_account(taken).display_name == ""
        assert store.get_account(free).display_name == "Alex Example"


def test_the_providers_address_follows_but_does_not_count(app: Any, konten: Any) -> None:
    account_id = _create(app, email="new@example.com")
    with app.store() as store:
        account = store.get_account(account_id)
    assert account.email == "new@example.com" and not account.email_confirmed and not account.email_proven
    assert account.email_source == konten.EMAIL_PROVIDER
    assert app.sign_in("new@example.com", "") is None


def test_an_address_another_account_has_is_not_taken_from_the_provider(app: Any) -> None:
    app.seed("kim", email="kim@example.com", password=password())
    account_id = _create(app, email="KIM@example.com")
    with app.store() as store:
        assert store.get_account(account_id).email == ""


def test_a_provider_address_follows_only_an_account_without_one_of_its_own(app: Any, konten: Any) -> None:
    own = app.seed("own", email="own@example.com", password=password())
    follows = app.seed("follows", password=None)
    with app.store() as store:
        assert not konten.profiles.follow_provider_email(store, own, "other@example.com")
        assert konten.profiles.follow_provider_email(store, follows, "first@example.com")
        assert konten.profiles.follow_provider_email(store, follows, "second@example.com")
        store.commit()
    with app.store() as store:
        assert store.get_account(own).email == "own@example.com"
        followed = store.get_account(follows)
    assert followed.email == "second@example.com" and not followed.email_confirmed
