"""Mails mit einer Person für nexfolk (verbinden 0.1.13, Zweck ``mails.about``, ``services/post_mit_person.py``).

Die Regel: Absender, An oder Cc ist eine der Adressen der Person (ohne Groß/klein), nur in den gegebenen Postfächern
des Kontos, nie in Papierkorb, Entwürfen, Werbung; der Name allein zählt nicht; dieselbe Mail in zwei Ordnern einmal.
Die Antwort nennt nie, was eine Mail sagt: kein Betreff, kein Absendername, kein Text, auch wenn das Modul einen Titel
sonst wegwürfe.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models import Benutzer, Konto, Nachricht, Ordner, neue_id
from app.services import benutzer as benutzerdienst, post_mit_person, suche
from app.services.verbinden_store import store_fuer
from app.vendor.nexverbinden import Person
from conftest import zweiten_benutzer_anlegen

PAT = "pat@example.com"
BETREFF = "Streng geheimer Betreff"


@pytest.fixture
def person(db) -> Benutzer:
    return benutzerdienst.anlegen(db, "betreiber", "sehr-geheim-123")


def _postfach(db, wem: Benutzer, name: str) -> Konto:
    konto = Konto(
        id=neue_id(), benutzer_id=wem.id, anzeigename=name, adresse=f"{name.lower()}@example.org",
        imap_server="imap.example.org", imap_benutzer=name.lower(), smtp_server="smtp.example.org",
        smtp_benutzer=name.lower(),
    )  # fmt: skip
    db.add(konto)
    db.commit()
    return konto


def _ordner(db, konto: Konto, rolle: str = "posteingang", pfad: str = "INBOX") -> Ordner:
    ordner = Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle=rolle)
    db.add(ordner)
    db.commit()
    return ordner


_UID = iter(range(1, 10_000))


def _mail(db, konto: Konto, ordner: Ordner, *, von: str = "jemand@example.org", an=(), cc=(), tage: int = 1,
          message_id: str | None = None, von_name: str = "Pat Example") -> Nachricht:  # fmt: skip
    uid = next(_UID)
    n = Nachricht(
        benutzer_id=konto.benutzer_id, konto_id=konto.id, ordner_id=ordner.id, uid=uid,
        message_id=message_id if message_id is not None else f"<m{uid}@example.org>", von_name=von_name,
        von_adresse=von, an_json=json.dumps([{"n": "", "a": a} for a in an]),
        kopie_json=json.dumps([{"n": "", "a": a} for a in cc]), betreff=BETREFF, anreisser=BETREFF,
        datum=datetime(2026, 11, 20, 9, 0, tzinfo=UTC) - timedelta(days=tage),
    )  # fmt: skip
    db.add(n)
    db.commit()
    return n


def _fragen(db, wem: Benutzer, areas=None, mails=(PAT,), name: str = "Pat Example"):
    caller = SimpleNamespace(account_id=wem.id, areas=areas)
    return post_mit_person.ueber_person(store_fuer(db), caller, "mails.about", Person(name=name, mails=tuple(mails)))


def test_absender_an_und_cc_zaehlen_ohne_gross_klein(db, person):
    konto = _postfach(db, person, "Privat")
    eingang = _ordner(db, konto)
    gesendet = _ordner(db, konto, "gesendet", "Sent")
    _mail(db, konto, eingang, von="Pat@Example.com", tage=3)
    _mail(db, konto, gesendet, von=konto.adresse, an=["pat@example.com"], tage=2)
    neueste = _mail(db, konto, eingang, von="kim@example.org", an=[konto.adresse], cc=["PAT@example.com"], tage=1)
    _mail(db, konto, eingang, von="kim@example.org", an=[konto.adresse])  # ohne Pat
    found = _fragen(db, person)
    assert found["count"] == 3
    assert found["last"] == {"title": "", "at": neueste.datum.isoformat()}
    assert found["next"] is None


def test_nur_die_gegebenen_postfaecher_zaehlen(db, person):
    privat = _postfach(db, person, "Privat")
    arbeit = _postfach(db, person, "Arbeit")
    _mail(db, privat, _ordner(db, privat), von=PAT)
    _mail(db, arbeit, _ordner(db, arbeit), von=PAT)
    assert _fragen(db, person, areas=[privat.id])["count"] == 1
    assert _fragen(db, person, areas=[arbeit.id])["count"] == 1
    assert _fragen(db, person, areas=None)["count"] == 2
    assert _fragen(db, person, areas=[])["count"] == 0


def test_ein_fremdes_postfach_zaehlt_nie(db, person):
    """Auch wenn seine Kennung unter den Bereichen der Verbindung stünde."""
    andere, _ = zweiten_benutzer_anlegen(db)
    fremd = _postfach(db, andere, "Fremd")
    _mail(db, fremd, _ordner(db, fremd), von=PAT)
    assert _fragen(db, person, areas=[fremd.id])["count"] == 0
    assert _fragen(db, person, areas=None)["count"] == 0


@pytest.mark.parametrize("rolle", ["papierkorb", "entwuerfe", "junk"])
def test_papierkorb_entwuerfe_und_werbung_zaehlen_nicht(db, person, rolle):
    konto = _postfach(db, person, "Privat")
    _mail(db, konto, _ordner(db, konto, rolle, rolle.title()), von=PAT)
    _mail(db, konto, _ordner(db, konto), von=PAT, tage=5)
    found = _fragen(db, person)
    assert found["count"] == 1
    assert found["last"]["at"].startswith("2026-11-15")


def test_dieselbe_mail_in_zwei_ordnern_zaehlt_einmal(db, person):
    konto = _postfach(db, person, "Privat")
    _mail(db, konto, _ordner(db, konto), von=PAT, message_id="<eine@example.org>")
    _mail(db, konto, _ordner(db, konto, "archiv", "All Mail"), von=PAT, message_id="<eine@example.org>")
    _mail(db, konto, _ordner(db, konto, "eigen", "Ohne"), von=PAT, message_id="")
    _mail(db, konto, _ordner(db, konto, "eigen", "Auch ohne"), von=PAT, message_id="")
    assert _fragen(db, person)["count"] == 3


def test_ohne_mailadresse_zaehlt_nichts(db, person):
    konto = _postfach(db, person, "Privat")
    _mail(db, konto, _ordner(db, konto), von=PAT, von_name="Pat Example")
    assert _fragen(db, person, mails=())["count"] == 0
    assert _fragen(db, person, mails=("nobody@example.org",))["count"] == 0


def test_die_antwort_nennt_nie_was_eine_mail_sagt(db, person):
    konto = _postfach(db, person, "Privat")
    _mail(db, konto, _ordner(db, konto), von=PAT)
    found = _fragen(db, person)
    assert set(found) == {"count", "next", "last", "open"}
    assert found["last"]["title"] == ""
    text = json.dumps(found)
    for verboten in (BETREFF, "Streng", "Pat Example", konto.adresse):
        assert verboten not in text, verboten


def test_oeffnen_fuehrt_zur_suche_nach_der_adresse(db, person):
    konto = _postfach(db, person, "Privat")
    _mail(db, konto, _ordner(db, konto), von=PAT)
    found = _fragen(db, person, mails=("Pat@Example.com", "zweit@example.org"))
    assert found["open"] == "/?suche=pat@example.com"
    assert _fragen(db, person, mails=("nobody@example.org",))["open"] is None


def test_die_postfaecher_sind_die_bereiche(db, person):
    privat = _postfach(db, person, "Privat")
    arbeit = _postfach(db, person, "Arbeit")
    _postfach(db, zweiten_benutzer_anlegen(db)[0], "Fremd")
    assert store_fuer(db).areas(person.id) == [{"id": privat.id, "name": "Privat"}, {"id": arbeit.id, "name": "Arbeit"}]


def test_die_suche_nach_einer_adresse_findet_auch_an_und_cc(db, person):
    """Wohin „öffnen“ führt: dieselben Mails, die die Karte zählt (außer Papierkorb und Co., die zeigt die Suche)."""
    konto = _postfach(db, person, "Privat")
    eingang = _ordner(db, konto)
    a = _mail(db, konto, eingang, von=PAT)
    b = _mail(db, konto, eingang, von="kim@example.org", an=[PAT])
    c = _mail(db, konto, eingang, von="kim@example.org", cc=["PAT@example.com"])
    _mail(db, konto, eingang, von="kim@example.org", an=["patrick@example.com"])
    gefunden = {n.id for n in suche.suchen(db, person, "Pat@Example.com")}
    assert gefunden == {a.id, b.id, c.id}
    # Ein gewöhnliches Wort sucht weiter nur im Volltext.
    assert {n.id for n in suche.suchen(db, person, "patrick")} == set()
