"""Test "Bestand": every sign-in that worked in 0.33.0 still works in the running version.

The database comes from 0.33.0 itself (``tests/bestand/bauen.py``, stored as ``bestand-0.33.0.sql.gz``, the accounts
and their test values in ``bestand-0.33.0.json``). Each test loads it in place of the fresh test database and then
starts the schema upkeep exactly like a container start after an update (``init_db``). Then it signs in the way each
account could sign in before: username and password (any case), second factor and recovery code, a provider, an open
browser session, a paired iPhone, an API key, an open invitation, a forgotten password.

⚠️ **Nothing here may be adapted to make a new version pass.** A red test means: an installation that runs 0.33.0
today loses a way in after the update. Change the code, not the test. The only thing that is allowed to change is
the list at the end (``NACH_DEM_UMBAU``): ways in that 0.33.0 did not have and that the account module adds.

⚠️ **The fixture ages.** Sessions run out after 30 days and invitations after 7; loading pushes those two dates into
the future, and nothing else is touched before the start.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect

sys.path.insert(0, str(Path(__file__).resolve().parent / "nexoidc"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "bestand"))

import oidc_fakes as fakes  # noqa: E402
from bauen import dump_datei, manifest_datei, totp_geheimnis  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, einstellung_schreiben, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import anmeldebremse, systempost  # noqa: E402
from app.vendor import nexoidc  # noqa: E402
from app.vendor.nexoidc import attempt, protocol  # noqa: E402

MANIFEST = json.loads(manifest_datei().read_text(encoding="utf-8"))
KONTEN = MANIFEST["konten"]
ANBIETER = MANIFEST["anbieter"]
ADRESSE_DER_APP = MANIFEST["oeffentliche_adresse"]

MIT_PASSWORT = [k for k in KONTEN if k.get("passwort")]
MIT_FAKTOR = [k for k in KONTEN if k.get("zweiter_faktor")]
MIT_ANBIETER = [k for k in KONTEN if k.get("anbieter")]
#: Unique addresses (case ignored): the ones that may sign in and reset a password by address after the change.
_ZAHL = {}
for _k in KONTEN:
    if _k["adresse"]:
        _ZAHL[_k["adresse"].lower()] = _ZAHL.get(_k["adresse"].lower(), 0) + 1
EINDEUTIGE_ADRESSE = [k for k in MIT_PASSWORT if k["adresse"] and _ZAHL[k["adresse"].lower()] == 1]
DOPPELTE_ADRESSE = [k for k in MIT_PASSWORT if k["adresse"] and _ZAHL[k["adresse"].lower()] > 1]

#: The tables and row counts that the start must leave as they are (nothing renamed, nothing deleted).
ZAEHLEN = (
    "benutzer",
    "einladung",
    "sitzung",
    "wiederherstellungscode",
    "oidc_anbieter",
    "oidc_verknuepfung",
    "api_schluessel",
    "konto",
    "ruecksetzung",
)


def _name(konto: dict) -> str:
    return konto["benutzername"]


def _schema(datei: Path) -> tuple[dict[str, set[str]], dict[str, int]]:
    verbindung = sqlite3.connect(str(datei))
    try:
        tabellen = [
            z[0]
            for z in verbindung.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'nachricht_fts%'"
            )
        ]
        spalten = {t: {z[1] for z in verbindung.execute(f'PRAGMA table_info("{t}")')} for t in tabellen}
        zahlen = {t: verbindung.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in ZAEHLEN if t in spalten}
    finally:
        verbindung.close()
    return spalten, zahlen


@pytest.fixture
def bestand():
    """The 0.33.0 database in place of the fresh one, then the start of the running version.

    Gives back what the old database had (columns per table, rows per counted table), read before the start.
    """
    engine.dispose()
    ziel = get_settings().db_path
    for rest in ("", "-wal", "-shm"):
        Path(str(ziel) + rest).unlink(missing_ok=True)
    verbindung = sqlite3.connect(str(ziel))
    try:
        verbindung.executescript(gzip.decompress(dump_datei().read_bytes()).decode("utf-8"))
        verbindung.execute("UPDATE sitzung SET gueltig_bis = datetime('now', '+30 days')")
        verbindung.execute("UPDATE einladung SET laeuft_ab = datetime('now', '+7 days') WHERE eingeloest IS NULL")
        verbindung.commit()
    finally:
        verbindung.close()
    vorher = _schema(ziel)
    init_db()
    anmeldebremse.zuruecksetzen()
    return vorher


@pytest.fixture
def anbieter():
    netz = fakes.Network()
    nexoidc.use_transport(netz.transport())
    protocol.clear_caches()
    attempt.forget_used_states()
    fake = netz.add(
        fakes.FakeProvider(
            ANBIETER["issuer"], client_id=ANBIETER["client_id"], client_secret=ANBIETER["client_geheimnis"]
        )
    )
    yield fake
    nexoidc.use_transport(None)
    protocol.clear_caches()
    attempt.forget_used_states()


@pytest.fixture
def post(monkeypatch):
    """System mail goes into a list instead of out (the fixture has no mail server)."""
    gesendet: list[dict] = []

    def senden(db, an, betreff, text, html=""):  # noqa: ARG001
        gesendet.append({"an": an, "betreff": betreff, "text": text})

    monkeypatch.setattr(systempost, "senden", senden)
    return gesendet


def browser() -> TestClient:
    # The fixture's public address is https: cookies are Secure there, as in production.
    return TestClient(app, base_url=ADRESSE_DER_APP, follow_redirects=False)


def ich(klient: TestClient) -> dict | None:
    antwort = klient.get("/api/auth/ich")
    return antwort.json() if antwort.status_code == 200 else None


def mit_passwort(klient: TestClient, konto: dict, eingabe: str | None = None, passwort: str | None = None):
    """The sign-in form of 0.33.0: field ``benutzername``, then the code if the account has a second factor."""
    antwort = klient.post(
        "/api/auth/anmelden",
        json={"benutzername": eingabe or _name(konto), "passwort": passwort or konto["passwort"]},
    )
    assert antwort.status_code == 200, (_name(konto), antwort.status_code, antwort.text)
    if antwort.json()["schritt"] == "code":
        code = pyotp.TOTP(totp_geheimnis(konto["zweiter_faktor"])).now()
        zweiter = klient.post("/api/auth/code", json={"code": code})
        assert zweiter.status_code == 200, (_name(konto), zweiter.text)
    else:
        assert antwort.json()["schritt"] == "fertig", antwort.json()


def code_wieder_frei() -> None:
    """A TOTP code counts once per 30 seconds; a second sign-in in the same test needs the step freed again."""
    with engine.begin() as verbindung:
        verbindung.exec_driver_sql("UPDATE benutzer SET totp_letzter_schritt = 0")


def ueber_anbieter(klient: TestClient, fake, person: dict):
    fake.person = dict(person)
    start = klient.get(f"/api/oidc/{ANBIETER['kuerzel']}/start")
    assert start.status_code in (302, 303), start.text
    beim_anbieter = start.headers["location"]
    pfad = urlsplit(parse_qs(urlsplit(beim_anbieter).query)["redirect_uri"][0]).path
    return klient.get(f"{pfad}?{urlencode(fake.authorize(beim_anbieter))}")


# --- The start after the update -------------------------------------------------------------------------------------


def test_the_fixture_is_from_0_33_0():
    assert MANIFEST["fassung"] == "0.33.0"
    roh = gzip.decompress(dump_datei().read_bytes()).decode("utf-8")
    assert 'CREATE TABLE "benutzer"' in roh or "CREATE TABLE benutzer" in roh


def test_the_start_only_adds(bestand):
    """Rule 10 of the plan: new columns with a default, nothing renamed or deleted, no row lost."""
    spalten_vorher, zahlen_vorher = bestand
    spalten_nachher, zahlen_nachher = _schema(get_settings().db_path)
    for tabelle, spalten in spalten_vorher.items():
        assert tabelle in spalten_nachher, f"table {tabelle} is gone"
        fehlt = spalten - spalten_nachher[tabelle]
        assert not fehlt, f"{tabelle}: columns gone {sorted(fehlt)}"
    assert zahlen_nachher == zahlen_vorher


def test_every_account_is_still_there_with_its_names(bestand):
    with SessionLocal() as db:
        from app.models import Benutzer

        leute = {p.benutzername: p for p in db.query(Benutzer).all()}
    assert set(leute) == {_name(k) for k in KONTEN}
    for konto in KONTEN:
        person = leute[_name(konto)]
        assert person.kontaktadresse == konto["adresse"], _name(konto)
        assert bool(person.passwort_hash) == bool(konto.get("passwort")), _name(konto)
        assert person.totp_bestaetigt == bool(konto.get("zweiter_faktor")), _name(konto)
        assert person.ist_betreiber == bool(konto.get("betreiber")), _name(konto)


# --- Username and password ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("konto", MIT_PASSWORT, ids=_name)
def test_username_and_password_still_sign_in(bestand, konto):
    klient = browser()
    mit_passwort(klient, konto)
    assert ich(klient)["benutzername"] == _name(konto)


@pytest.mark.parametrize("konto", MIT_PASSWORT, ids=_name)
def test_the_username_in_other_case_still_signs_in(bestand, konto):
    """0.33.0 compares without case; ``Erika.Muster`` keeps her capitals and may type ``erika.muster``."""
    for eingabe in (_name(konto).lower(), _name(konto).upper()):
        anmeldebremse.zuruecksetzen()
        code_wieder_frei()
        klient = browser()
        mit_passwort(klient, konto, eingabe=eingabe)
        assert ich(klient)["benutzername"] == _name(konto)


@pytest.mark.parametrize("konto", MIT_PASSWORT, ids=_name)
def test_a_wrong_password_is_still_refused(bestand, konto):
    antwort = browser().post(
        "/api/auth/anmelden", json={"benutzername": _name(konto), "passwort": konto["passwort"] + "x"}
    )
    assert antwort.status_code == 401


def test_passwords_shorter_than_the_new_minimum_still_sign_in(bestand):
    """Rule 9: 0.33.0 took 10 characters; the new minimum of 12 is for new passwords only."""
    kurz = [k for k in MIT_PASSWORT if len(k["passwort"]) < 12]
    assert {len(k["passwort"]) for k in kurz} == {10, 11}
    for konto in kurz:
        klient = browser()
        mit_passwort(klient, konto)
        assert ich(klient)["benutzername"] == _name(konto)


@pytest.mark.parametrize("konto", MIT_FAKTOR, ids=_name)
def test_a_recovery_code_still_replaces_the_app(bestand, konto):
    klient = browser()
    antwort = klient.post("/api/auth/anmelden", json={"benutzername": _name(konto), "passwort": konto["passwort"]})
    assert antwort.status_code == 200 and antwort.json()["schritt"] == "code", antwort.text
    zweiter = klient.post("/api/auth/wiederherstellung", json={"code": konto["wiederherstellungscodes"][0]})
    assert zweiter.status_code == 200, zweiter.text
    assert ich(klient)["benutzername"] == _name(konto)


def test_password_sign_in_switched_off_still_keeps_members_out_and_lets_the_operator_in(bestand):
    """nexmail has no blocked accounts; what keeps an account out is "sign-in with password off" (a provider is
    set up in the fixture). That must hold after the update, and the operator must still get in."""
    from app.routers.oidc import SCHLUESSEL_PASSWORT

    with SessionLocal() as db:
        einstellung_schreiben(db, SCHLUESSEL_PASSWORT, "aus")
    for konto in MIT_PASSWORT:
        anmeldebremse.zuruecksetzen()
        klient = browser()
        if konto.get("betreiber"):
            mit_passwort(klient, konto)
            assert ich(klient)["benutzername"] == _name(konto)
        else:
            antwort = klient.post(
                "/api/auth/anmelden", json={"benutzername": _name(konto), "passwort": konto["passwort"]}
            )
            assert antwort.status_code == 401, (_name(konto), antwort.text)


def test_the_brake_still_locks_after_ten_wrong_passwords(bestand):
    """The brake waits between tries; the waits are skipped here so that ten wrong passwords come quickly."""
    konto = next(k for k in MIT_PASSWORT if not k.get("betreiber"))
    klient = browser()
    for _ in range(anmeldebremse.SPERRE_AB_VERSUCH):
        for zaehler in anmeldebremse._zaehler.values():
            zaehler.frei_ab = 0
        klient.post("/api/auth/anmelden", json={"benutzername": _name(konto), "passwort": "falsch-falsch-falsch"})
    antwort = klient.post("/api/auth/anmelden", json={"benutzername": _name(konto), "passwort": konto["passwort"]})
    assert antwort.status_code == 429, antwort.text


# --- Providers ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("konto", MIT_ANBIETER, ids=_name)
def test_the_provider_still_signs_in(bestand, anbieter, konto):
    klient = browser()
    zurueck = ueber_anbieter(klient, anbieter, konto["anbieter"])
    assert zurueck.status_code in (302, 303), zurueck.text
    assert "error" not in zurueck.headers["location"], zurueck.headers["location"]
    assert ich(klient)["benutzername"] == _name(konto)


@pytest.mark.parametrize("konto", [k for k in MIT_ANBIETER if not k.get("passwort")], ids=_name)
def test_an_account_without_password_still_has_none(bestand, konto):
    """A provider-only account must not get a password sign-in by the update (no empty or guessed password)."""
    for versuch in ("", " ", _name(konto)):
        antwort = browser().post("/api/auth/anmelden", json={"benutzername": _name(konto), "passwort": versuch or "-"})
        assert antwort.status_code == 401


# --- What is already signed in --------------------------------------------------------------------------------------


def test_an_open_browser_session_stays_open(bestand):
    konto = next(k for k in KONTEN if k.get("sitzung"))
    klient = browser()
    from app.services.sitzung import COOKIE_NAME

    klient.cookies.set(COOKIE_NAME, konto["sitzung"])
    assert (ich(klient) or {}).get("benutzername") == _name(konto)


def test_a_paired_iphone_stays_paired(bestand):
    konto = next(k for k in KONTEN if k.get("geraet"))
    antwort = browser().get("/api/app/1/me", headers={"Authorization": f"Bearer {konto['geraet']}"})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["konto"]["benutzername"] == _name(konto)


def test_an_api_key_keeps_working(bestand):
    konto = next(k for k in KONTEN if k.get("api_schluessel"))
    antwort = browser().get("/api/v1/me", headers={"Authorization": f"Bearer {konto['api_schluessel']}"})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["user"]["username"] == _name(konto)


# --- Invitation and forgotten password ------------------------------------------------------------------------------


def test_the_open_invitation_keeps_its_username(bestand):
    """Rule 7: an invitation from 0.33.0 names the username; it stays that name."""
    offen = MANIFEST["offene_einladung"]
    klient = browser()
    vorschau = klient.get(f"/api/einladung/{offen['schluessel']}")
    assert vorschau.status_code == 200, vorschau.text
    assert vorschau.json()["benutzername"] == offen["benutzername"]
    neues_passwort = "Bestand-gast-neu-2026"
    annahme = klient.post(f"/api/einladung/{offen['schluessel']}", json={"passwort": neues_passwort})
    assert annahme.status_code == 201, annahme.text
    selbst = ich(klient)
    assert selbst["benutzername"] == offen["benutzername"]
    assert selbst["kontaktadresse"] == offen["adresse"]
    anmeldebremse.zuruecksetzen()
    zweiter = browser()
    mit_passwort(zweiter, {"benutzername": offen["benutzername"], "passwort": neues_passwort})
    assert ich(zweiter)["benutzername"] == offen["benutzername"]


def _link_schluessel(mail: dict) -> str:
    treffer = re.search(re.escape(ADRESSE_DER_APP) + r"/\S+", mail["text"])
    assert treffer, mail["text"]
    return treffer.group(0).rstrip(".,)").rsplit("/", 1)[-1]


@pytest.mark.parametrize("konto", EINDEUTIGE_ADRESSE, ids=_name)
def test_forgot_password_with_the_username_still_sends_a_link(bestand, post, konto):
    antwort = browser().post("/api/auth/kennwort-vergessen", json={"benutzername": _name(konto)})
    assert antwort.status_code == 202
    assert [m["an"].lower() for m in post] == [konto["adresse"].lower()]
    neues = "Bestand-ganz-neu-2026"
    gesetzt = browser().post(
        "/api/auth/kennwort-neu", json={"schluessel": _link_schluessel(post[0]), "passwort": neues}
    )
    assert gesetzt.status_code == 204, gesetzt.text
    anmeldebremse.zuruecksetzen()
    klient = browser()
    mit_passwort(klient, konto, passwort=neues)
    assert ich(klient)["benutzername"] == _name(konto)


@pytest.mark.parametrize("konto", DOPPELTE_ADRESSE, ids=_name)
def test_forgot_password_for_a_shared_address_never_reaches_the_other_account(bestand, post, konto):
    """0.33.0 sends the link of ``kim`` to kim's address, which lou has too. Whether that stays is open (rule 3 of
    the draft); what may never happen is a link for one account going out on behalf of the other."""
    antwort = browser().post("/api/auth/kennwort-vergessen", json={"benutzername": _name(konto)})
    assert antwort.status_code == 202
    assert len(post) <= 1
    for mail in post:
        assert mail["an"] == konto["adresse"]
        assert _name(konto) in mail["text"]


def test_forgot_password_without_an_address_still_sends_nothing_and_says_the_same(bestand, post):
    konto = next(k for k in MIT_PASSWORT if not k["adresse"])
    antwort = browser().post("/api/auth/kennwort-vergessen", json={"benutzername": _name(konto)})
    assert antwort.status_code == 202
    assert post == []


# --- After the change (account module): ways in that 0.33.0 did not have -------------------------------------------
#
# ⚠️ **Strict xfail.** They fail today because 0.33.0 only knows the username. The day the module is wired in they
# pass, strict turns that into a red test, and whoever wired it removes the marker. Until then they say what the
# plan promises for the Bestand (rules 2 and 3 of the draft).

NACH_DEM_UMBAU = pytest.mark.xfail(strict=True, reason="sign-in by email comes with the account module")


@NACH_DEM_UMBAU
@pytest.mark.parametrize("konto", EINDEUTIGE_ADRESSE, ids=_name)
def test_after_the_change_a_unique_contact_address_signs_in(bestand, konto):
    klient = browser()
    mit_passwort(klient, konto, eingabe=konto["adresse"].upper())
    assert ich(klient)["benutzername"] == _name(konto)


@NACH_DEM_UMBAU
@pytest.mark.parametrize("konto", EINDEUTIGE_ADRESSE, ids=_name)
def test_after_the_change_forgot_password_takes_a_unique_address(bestand, post, konto):
    browser().post("/api/auth/kennwort-vergessen", json={"benutzername": konto["adresse"]})
    assert [m["an"].lower() for m in post] == [konto["adresse"].lower()]


@pytest.mark.parametrize("konto", DOPPELTE_ADRESSE, ids=_name)
def test_a_shared_address_never_signs_in(bestand, post, konto):
    """Rule 3, true today and after the change: an address that two accounts share opens neither."""
    antwort = browser().post(
        "/api/auth/anmelden", json={"benutzername": konto["adresse"], "passwort": konto["passwort"]}
    )
    assert antwort.status_code == 401
    browser().post("/api/auth/kennwort-vergessen", json={"benutzername": konto["adresse"]})
    assert post == []
