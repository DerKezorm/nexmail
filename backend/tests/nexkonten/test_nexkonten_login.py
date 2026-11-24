"""Signing in: "Username or email" and the password. Only confirmed addresses no other account has; the display name
never; one refusal for everything."""

from __future__ import annotations

from typing import Any

import pytest
from konten_contract import password


def test_a_username_signs_in_in_any_case(app: Any) -> None:
    secret = password()
    account_id = app.seed("alex", password=secret)
    for typed in ("alex", "ALEX", " Alex "):
        assert app.sign_in(typed, secret) == account_id, typed


def test_a_username_of_the_older_version_with_capitals_keeps_working(app: Any) -> None:
    secret = password()
    account_id = app.seed("Kim.Lee", password=secret)
    assert app.sign_in("kim.lee", secret) == account_id
    assert app.sign_in("Kim.Lee", secret) == account_id


def test_a_one_letter_name_of_the_older_version_keeps_working(app: Any) -> None:
    secret = password()
    account_id = app.seed("Q", password=secret)
    assert app.sign_in("q", secret) == account_id


def test_the_brake_counts_one_account_once_however_it_is_named(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        keys = {konten.login.attempt_key(store, typed, "203.0.113.9") for typed in ("alex", "ALEX@example.com")}
        unknown = konten.login.attempt_key(store, "nobody", "203.0.113.9")
    assert keys == {f"account:{alex}"} and unknown == "sender:203.0.113.9"


def test_a_confirmed_address_signs_in_in_any_case(app: Any) -> None:
    secret = password()
    account_id = app.seed("alex", email="Alex@Example.com", password=secret)
    assert app.sign_in("alex@example.com", secret) == account_id
    assert app.sign_in("ALEX@EXAMPLE.COM", secret) == account_id


def test_an_address_that_is_not_confirmed_does_not_sign_in(app: Any) -> None:
    secret = password()
    account_id = app.seed("alex", email="alex@example.com", email_confirmed=False, password=secret)
    assert app.sign_in("alex@example.com", secret) is None
    assert app.sign_in("alex", secret) == account_id


def test_an_address_two_accounts_share_signs_in_neither_but_each_username_does(app: Any) -> None:
    first_secret, second_secret = password(), password()
    first = app.seed("first", email="shared@example.com", password=first_secret)
    second = app.seed("second", email="SHARED@example.com", password=second_secret)
    assert app.sign_in("shared@example.com", first_secret) is None
    assert app.sign_in("shared@example.com", second_secret) is None
    assert app.sign_in("first", first_secret) == first
    assert app.sign_in("second", second_secret) == second


def test_the_display_name_never_signs_in(app: Any) -> None:
    secret = password()
    app.seed("alex", display_name="Chef", password=secret)
    assert app.sign_in("Chef", secret) is None


def test_an_account_through_a_provider_only_does_not_sign_in_with_a_password(app: Any) -> None:
    app.seed("alex", email="alex@example.com", password=None)
    assert app.sign_in("alex", "") is None
    assert app.sign_in("alex", password()) is None


def test_a_blocked_account_does_not_sign_in(app: Any) -> None:
    secret = password()
    app.seed("alex", password=secret, blocked=True)
    assert app.sign_in("alex", secret) is None


def test_every_refusal_says_the_same(app: Any, konten: Any) -> None:
    secret = password()
    app.seed("alex", email="alex@example.com", password=secret)
    app.seed("pending", email="pending@example.com", email_confirmed=False, password=secret)
    answers = set()
    for typed, given in (
        ("alex", secret + "x"),
        ("nobody", secret),
        ("nobody@example.com", secret),
        ("pending@example.com", secret),
        ("", secret),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.login.authenticate(store, typed, given)
        answers.add((caught.value.code, caught.value.message, caught.value.status))
    assert answers == {("wrong_credentials", "Username, email or password is wrong.", 401)}


def test_a_blocked_account_hears_so_only_after_its_right_password(app: Any, konten: Any) -> None:
    secret = password()
    app.seed("alex", password=secret, blocked=True)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.login.authenticate(store, "alex", secret + "x")
    assert caught.value.code == "wrong_credentials"
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.login.authenticate(store, "alex", secret)
    assert caught.value.code == "account_blocked"


def test_a_password_of_the_older_version_shorter_than_the_rule_still_signs_in(app: Any) -> None:
    short = password()[:10]
    account_id = app.seed("alex", password=short)
    assert app.sign_in("alex", short) == account_id


def test_a_former_username_does_not_sign_in_in_the_browser(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret)
    assert app.sign_in("alex", secret) is None
    assert app.sign_in("alexa", secret) == alex


def test_programs_in_the_background_find_the_account_by_current_or_former_name_or_address(
    app: Any, konten: Any
) -> None:
    secret = password()
    alex = app.seed("alex", email="alex@example.com", email_confirmed=False, password=secret)
    app.seed("one", email="shared@example.com", password=password())
    app.seed("two", email="shared@example.com", password=password())
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret)
    with app.store() as store:
        for typed in ("alexa", "ALEX", "alex@example.com"):
            found = konten.login.background_account(store, typed)
            assert found is not None and found.id == alex, typed
        assert konten.login.background_account(store, "shared@example.com") is None
        assert konten.login.background_account(store, "nobody") is None


def test_wrong_passwords_lock_the_account_however_it_is_named(app: Any, konten: Any) -> None:
    if not app.lock_after:
        return
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    for index in range(app.lock_after):
        typed = "alex" if index % 2 else "ALEX@example.com"
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.login.authenticate(store, typed, secret + "x")
        assert caught.value.code == "wrong_credentials" and caught.value.account_id == alex
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.login.authenticate(store, "alex", secret)
    assert caught.value.code == "wrong_credentials"
    with app.store() as store:
        assert konten.login.authenticate(store, "alex", secret, known_browser=alex).id == alex
        konten.login.succeeded(store, alex)
    with app.store() as store:
        assert konten.login.authenticate(store, "alex", secret).id == alex


def test_failures_from_the_owners_own_browser_do_not_count(app: Any, konten: Any) -> None:
    if not app.lock_after:
        return
    secret = password()
    alex = app.seed("alex", password=secret)
    for _ in range(app.lock_after + 1):
        with app.store() as store, pytest.raises(konten.AccountError):
            konten.login.authenticate(store, "alex", secret + "x", known_browser=alex)
    with app.store() as store:
        assert konten.login.authenticate(store, "alex", secret).id == alex
