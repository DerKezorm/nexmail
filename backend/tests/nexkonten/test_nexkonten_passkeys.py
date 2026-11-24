"""Passkeys through the app's store: added and signing in without a password, each answer counting once, the count
only moving forward, the operator's switch, a blocked account, and the last factor where one is required."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

import pytest
from konten_contract import password
from webauthn_device import Device

PUBLIC_URL = "https://app.example.com"


def _where(konten: Any) -> Any:
    return konten.passkeys.party(PUBLIC_URL)


def _register(app: Any, konten: Any, account_id: Any, name: str = "Phone") -> tuple[Device, Any]:
    where = _where(konten)
    device = Device(where.origin, where.rp_id)
    with app.store() as store:
        token, options = konten.passkeys.begin_register(store, account_id, where, app_name="nexapp")
        key = konten.passkeys.finish_register(store, account_id, token, device.create(options), where, name=name)
    return device, key


def _sign_in(app: Any, konten: Any, device: Device, **answer: Any) -> Any:
    where = _where(konten)
    with app.store() as store:
        token, options = konten.passkeys.begin_sign_in(store, where)
        return konten.passkeys.finish_sign_in(store, token, device.get(options, **answer), where)


def _refused(konten: Any, call: Any, code: str) -> None:
    with pytest.raises(konten.AccountError) as caught:
        call()
    assert caught.value.code == code


def test_the_party_is_the_public_address_of_the_app(konten: Any) -> None:
    where = konten.passkeys.party("https://Notes.Example.com:8443/app")
    assert (where.rp_id, where.origin) == ("notes.example.com", "https://notes.example.com:8443")
    _refused(konten, lambda: konten.passkeys.party("notes.example.com"), "passkeys_off")


def test_a_passkey_is_added_and_signs_in_without_a_password(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    device, key = _register(app, konten, alex, name="  Phone\nof Alex  ")
    assert key.name == "Phone of Alex" and key.sign_count == 0
    with app.store() as store:
        assert [entry.uid for entry in store.passkeys_of(alex)] == [key.uid]
        assert store.find_passkey(device.credential_id).account_id == alex
        assert konten.factor.has_factor(store, alex)
        assert store.second_factor(alex) == konten.SECOND_FACTOR_ACTIVE
        assert device.user_handle == store.user_handle(alex) and len(device.user_handle) >= 16
    assert _sign_in(app, konten, device).id == alex
    assert _sign_in(app, konten, device).id == alex
    with app.store() as store:
        used = store.passkeys_of(alex)[0]
    assert used.sign_count == 2 and used.last_used_at is not None
    shown = konten.passkeys.view(used)
    assert set(shown) == {"uid", "name", "created_at", "last_used_at"}


def test_the_same_passkey_is_not_added_twice_and_handles_differ_per_account(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    device, _ = _register(app, konten, alex)
    where = _where(konten)
    with app.store() as store:
        token, options = konten.passkeys.begin_register(store, alex, where, app_name="nexapp")
        assert device.credential_id != b"" and konten.passkeys.options_json(options)["excludeCredentials"]
        answer = device.create(options)
        _refused(konten, lambda: konten.passkeys.finish_register(store, alex, token, answer, where), "passkey_exists")
        assert store.user_handle(alex) != store.user_handle(kim)
        token, options = konten.passkeys.begin_register(store, alex, where, app_name="nexapp")
        _refused(
            konten,
            lambda: konten.passkeys.finish_register(
                store, kim, token, Device(where.origin, where.rp_id).create(options), where
            ),
            "passkey_expired",
        )


def test_an_answer_counts_once_and_a_count_that_does_not_move_is_refused(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    device, _ = _register(app, konten, alex)
    where = _where(konten)
    with app.store() as store:
        token, options = konten.passkeys.begin_sign_in(store, where)
        answer = device.get(options)
        assert konten.passkeys.finish_sign_in(store, token, answer, where).id == alex
        _refused(konten, lambda: konten.passkeys.finish_sign_in(store, token, answer, where), "passkey_expired")
    _refused(konten, lambda: _sign_in(app, konten, device, count_up=False), "passkey_invalid")
    with app.store() as store:
        uid = store.passkeys_of(alex)[0].uid
    with app.store() as first, app.store() as second:
        assert first.claim_counter(uid, 1, 5) is True
        first.commit()
        assert second.claim_counter(uid, 1, 5) is False


def test_a_wrong_origin_an_unknown_passkey_or_another_accounts_handle_is_refused(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    device, _ = _register(app, konten, alex)
    _register(app, konten, kim)
    _refused(konten, lambda: _sign_in(app, konten, device, origin="https://app.example.org"), "passkey_invalid")
    with app.store() as store:
        other = store.user_handle(kim)
    _refused(konten, lambda: _sign_in(app, konten, device, user_handle=other), "passkey_invalid")
    stranger = Device(device.origin, device.rp_id)
    _refused(konten, lambda: _sign_in(app, konten, stranger), "passkey_invalid")
    assert _sign_in(app, konten, device).id == alex


def test_the_operator_turns_passkeys_off_and_none_signs_in_but_none_is_deleted(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    device, _ = _register(app, konten, alex)
    with app.store() as store:
        assert store.passkeys_allowed() is True
    app.switch("passkeys_allowed", False)
    where = _where(konten)
    with app.store() as store:
        _refused(konten, lambda: konten.passkeys.begin_sign_in(store, where), "passkeys_off")
        _refused(konten, lambda: konten.passkeys.begin_register(store, alex, where, app_name="x"), "passkeys_off")
        assert len(store.passkeys_of(alex)) == 1
    app.switch("passkeys_allowed", True)
    assert _sign_in(app, konten, device).id == alex


def test_a_blocked_account_hears_so_only_after_a_valid_answer(app: Any, konten: Any) -> None:
    gone = app.seed("gone", password=password(), blocked=True)
    where = _where(konten)
    device = Device(where.origin, where.rp_id)
    with app.store() as store:
        device.user_handle = store.user_handle(gone)
        store.add_passkey(
            konten.model2.Passkey(
                uid=secrets.token_hex(16),
                account_id=gone,
                credential_id=device.credential_id,
                public_key=device.public_key(),
                sign_count=0,
                name="Phone",
                created_at=datetime.now(UTC),
            )
        )
        store.commit()
    _refused(konten, lambda: _sign_in(app, konten, device, origin="https://app.example.net"), "passkey_invalid")
    _refused(konten, lambda: _sign_in(app, konten, device), "account_blocked")


def test_the_last_factor_stays_where_the_operator_requires_one(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    _, first = _register(app, konten, alex)
    app.switch("factor_required", True)
    with app.store() as store:
        _refused(konten, lambda: konten.passkeys.remove(store, alex, first.uid, password=secret), "factor_required")
    _, second = _register(app, konten, alex)
    with app.store() as store:
        _refused(konten, lambda: konten.passkeys.remove(store, alex, first.uid, password=password()), "wrong_password")
        assert konten.passkeys.remove(store, alex, first.uid, password=secret) is True
    with app.store() as store:
        assert [key.uid for key in store.passkeys_of(alex)] == [second.uid]


def test_the_operators_reset_takes_the_passkeys_too(app: Any, konten: Any, operator: tuple[Any, str]) -> None:
    boss, boss_secret = operator
    alex = app.seed("alex", password=password())
    device, _ = _register(app, konten, alex)
    with app.store() as store:
        assert konten.factor.operator_reset(store, alex, actor_id=boss, password=boss_secret) is None
    with app.store() as store:
        assert store.passkeys_of(alex) == [] and not konten.factor.has_factor(store, alex)
    _refused(konten, lambda: _sign_in(app, konten, device), "passkey_invalid")
