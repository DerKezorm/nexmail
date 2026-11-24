"""The second factor through the app's store: a time-based code and recovery codes, sealed, each counting once; the
sign-in that waits for the code; the operator's reset and switch; and what the older version set up keeps working."""

from __future__ import annotations

import time
from typing import Any

import pytest
from konten_contract import password

ISSUER = "nexapp"


def _wrong(code: str) -> str:
    return str((int(code[0]) + 5) % 10) + code[1:]


def _set_up(app: Any, konten: Any, account_id: Any, secret: str) -> tuple[str, list[str]]:
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, account_id, issuer=ISSUER)
        code = konten.factor.code_at(enrolment.seed, time.time())
        done = konten.factor.confirm_totp(store, account_id, code, password=secret)
    return enrolment.seed, done.codes


def _refused(konten: Any, call: Any, code: str) -> None:
    with pytest.raises(konten.AccountError) as caught:
        call()
    assert caught.value.code == code


def test_a_time_based_code_counts_only_once_a_code_confirmed_it_and_is_kept_sealed(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, alex, issuer=ISSUER)
        assert enrolment.uri.startswith(f"otpauth://totp/{ISSUER}:alex?secret={enrolment.seed}&")
        assert store.totp_seed(alex) is None and not konten.factor.has_factor(store, alex)
        code = konten.factor.code_at(enrolment.seed, time.time())
        _refused(konten, lambda: konten.factor.confirm_totp(store, alex, _wrong(code), password=secret), "code_wrong")
        _refused(konten, lambda: konten.factor.confirm_totp(store, alex, code, password=password()), "wrong_password")
        assert store.totp_seed(alex) is None
        done = konten.factor.confirm_totp(store, alex, code, password=secret)
    assert len(done.codes) == 10 and len(set(done.codes)) == 10
    with app.store() as store:
        assert store.totp_seed(alex) == enrolment.seed
        assert store.second_factor(alex) == konten.SECOND_FACTOR_ACTIVE
        account = store.get_account(alex)
        assert konten.common.next_step(store, account) == konten.NEXT_SECOND_FACTOR
        # The code that confirmed it is used up.
        _refused(konten, lambda: konten.factor.check_code(store, alex, code), "code_wrong")
    raw = app.raw_text()
    assert enrolment.seed not in raw and enrolment.seed.lower() not in raw
    assert not any(entry in raw or entry.replace("-", "") in raw for entry in done.codes)


def test_a_code_counts_once_also_for_two_requests_at_the_same_moment(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    seed, _ = _set_up(app, konten, alex, secret)
    later = konten.factor.code_at(seed, time.time() + konten.factor.STEP_SECONDS)
    with app.store() as store:
        assert konten.factor.check_code(store, alex, later) == "totp"
    with app.store() as store:
        _refused(konten, lambda: konten.factor.check_code(store, alex, later), "code_wrong")
    step = int(time.time()) // konten.factor.STEP_SECONDS + 10
    with app.store() as first, app.store() as second:
        assert first.claim_step(alex, step) is True
        first.commit()
        assert second.claim_step(alex, step) is False
        assert second.claim_step(alex, step + 1) is True
        second.commit()


def test_a_recovery_code_counts_once_in_any_spelling_and_new_ones_replace_the_old(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    _, codes = _set_up(app, konten, alex, secret)
    assert all(len(code) == 11 and code[5] == "-" for code in codes)
    with app.store() as store:
        assert konten.factor.check_code(store, alex, codes[0]) == "recovery"
    with app.store() as store:
        _refused(konten, lambda: konten.factor.check_code(store, alex, codes[0]), "code_wrong")
        assert konten.factor.check_code(store, alex, " " + codes[1].upper().replace("-", " ") + " ") == "recovery"
        assert len(store.recovery_hashes(alex)) == 8
    with app.store() as first, app.store() as second:
        stored = first.recovery_hashes(alex)[0]
        assert stored in second.recovery_hashes(alex)
        assert first.claim_recovery(alex, stored) is True
        first.commit()
        assert second.claim_recovery(alex, stored) is False
    with app.store() as store:
        fresh = konten.factor.new_codes(store, alex, password=secret)
    assert len(fresh) == 10 and not set(fresh) & set(codes)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.check_code(store, alex, codes[2]), "code_wrong")
        assert konten.factor.check_code(store, alex, fresh[0]) == "recovery"


def test_the_owner_takes_the_code_away_unless_the_operator_requires_a_second_factor(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    _set_up(app, konten, alex, secret)
    app.switch("factor_required", True)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.disable_totp(store, alex, password=secret), "factor_required")
        assert store.totp_seed(alex)
    app.switch("factor_required", False)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.disable_totp(store, alex, password=password()), "wrong_password")
        konten.factor.disable_totp(store, alex, password=secret)
    with app.store() as store:
        assert store.totp_seed(alex) is None and store.recovery_hashes(alex) == []
        assert store.second_factor(alex) == konten.SECOND_FACTOR_NONE


def test_nobody_needs_a_second_factor_until_the_operator_switches_it_on(app: Any, konten: Any) -> None:
    plain = app.seed("plain", password=password())
    with app.store() as store:
        assert store.factor_required() is False
        assert konten.factor.state(store, plain) == konten.SECOND_FACTOR_NONE
        assert konten.common.next_step(store, store.get_account(plain)) == konten.NEXT_SESSION
    app.switch("factor_required", True)
    with app.store() as store:
        assert store.factor_required() is True
        assert konten.factor.state(store, plain) == konten.SECOND_FACTOR_REQUIRED
        assert store.second_factor(plain) == konten.SECOND_FACTOR_REQUIRED
        assert konten.common.next_step(store, store.get_account(plain)) == konten.NEXT_SECOND_FACTOR_SETUP


def test_the_operator_resets_every_factor_of_another_account_and_its_sessions_end(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    boss, boss_secret = operator
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    _set_up(app, konten, alex, secret)
    session = app.open_session(alex)
    with app.store() as store:
        _refused(
            konten,
            lambda: konten.factor.operator_reset(store, alex, actor_id=boss, password=password()),
            "wrong_password",
        )
        _refused(
            konten,
            lambda: konten.factor.operator_reset(store, boss, actor_id=boss, password=boss_secret),
            "use_account_page",
        )
        with pytest.raises(konten.AccountError):
            konten.factor.operator_reset(store, boss, actor_id=alex, password=secret)
    assert app.session_alive(session)
    with app.store() as store:
        mail = konten.factor.operator_reset(store, alex, actor_id=boss, password=boss_secret)
    assert mail is not None and mail.kind == konten.MAIL_FACTOR_RESET and mail.to == "alex@example.com"
    assert not app.session_alive(session)
    with app.store() as store:
        assert not konten.factor.has_factor(store, alex) and store.recovery_hashes(alex) == []


def test_the_waiting_sign_in_takes_the_code_and_ends_after_five_wrong_ones(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    seed, _ = _set_up(app, konten, alex, secret)
    token = konten.factor.start_waiting(alex, remember=False)
    assert konten.factor.waiting_account(token) == alex and konten.factor.waiting_account("other") is None
    wrong = _wrong(konten.factor.code_at(seed, time.time() + 30))
    for _ in range(konten.factor.MAX_ATTEMPTS):
        with app.store() as store:
            _refused(konten, lambda: konten.factor.finish_waiting(store, token, wrong), "code_wrong")
    with app.store() as store:
        right = konten.factor.code_at(seed, time.time() + 30)
        _refused(konten, lambda: konten.factor.finish_waiting(store, token, right), "sign_in_expired")
    token = konten.factor.start_waiting(alex, remember=False, provider_checked=True)
    with app.store() as store:
        waited = konten.factor.finish_waiting(store, token, right)
    assert (waited.account_id, waited.remember, waited.provider_checked, waited.method) == (alex, False, True, "totp")
    assert konten.factor.waiting_account(token) is None


def test_a_blocked_account_gets_no_further_with_its_code(app: Any, konten: Any) -> None:
    gone = app.seed("gone", password=password(), blocked=True)
    seed = konten.factor.new_seed()
    with app.store() as store:
        store.set_totp(gone, seed)
        store.commit()
    token = konten.factor.start_waiting(gone)
    with app.store() as store:
        code = konten.factor.code_at(seed, time.time())
        _refused(konten, lambda: konten.factor.finish_waiting(store, token, code), "account_blocked")


def test_the_authenticator_apps_and_codes_of_the_older_version_keep_working(app: Any, konten: Any) -> None:
    legacy = app.legacy()
    assert legacy.factors, "Legacy.factors: the second factors the older version set up"
    for username, seed, codes in legacy.factors:
        with app.store() as store:
            account = store.find_by_username(username)[0]
            assert konten.factor.has_factor(store, account.id)
            assert store.second_factor(account.id) == konten.SECOND_FACTOR_ACTIVE
            assert konten.factor.check_code(store, account.id, konten.factor.code_at(seed, time.time())) == "totp"
        for code in codes:
            with app.store() as store:
                assert konten.factor.check_code(store, account.id, code) == "recovery"
            with app.store() as store:
                _refused(konten, lambda: konten.factor.check_code(store, account.id, code), "code_wrong")  # noqa: B023
