"""Konversationsansicht: was zu einem Strang gehoert und was nicht.

⚠️ **Falsch gruppiert versteckt eine Nachricht.** Sie steckt dann in einem
zugeklappten Strang, und man merkt es erst, wenn man sie sucht. Die Tests hier
sind deshalb zur Haelfte darauf gerichtet, dass **nichts Fremdes** in einen
Strang rutscht — nicht nur darauf, dass Zusammengehoeriges zusammenfindet.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Nachricht, Ordner
from app.services import anbieter, konten, straenge
from conftest import einrichten
from test_konten import _eingabe, _guter_befund


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="", token="": _guter_befund())
    yield


@pytest.fixture
def welt(klient, ohne_netz, db):
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]
    from app.models import Konto

    konto = db.get(Konto, konto_id)
    ordner = {o.rolle: o for o in konto.ordner}
    return konto, ordner


def _legen(
    db,
    konto,
    ordner,
    *,
    kennung: str,
    betreff: str,
    von: str = "anna@example.com",
    an: str = "anna@example.com",
    references: list[str] | None = None,
    in_reply_to: str = "",
    tage: int = 0,
) -> Nachricht:
    """Eine Nachricht anlegen — mit demselben Weg wie der Abgleich."""
    datum = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc) + timedelta(days=tage)
    kern = betreff.lower().removeprefix("re: ").removeprefix("aw: ").strip()
    beteiligte = {von.lower(), an.lower()}

    key = straenge.schluessel(
        db,
        konto,
        message_id=kennung,
        references=references or [],
        in_reply_to=in_reply_to,
        betreff_kern=kern,
        beteiligte=beteiligte,
        datum=datum,
    )
    n = Nachricht(
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=abs(hash(kennung)) % 100000,
        message_id=kennung,
        thread_key=key,
        referenzen=" ".join([*(references or []), in_reply_to]).strip(),
        betreff_kern=kern,
        betreff=betreff,
        von_name="",
        von_adresse=von,
        an_json=json.dumps([{"name": "", "adresse": an}]),
        datum=datum,
    )
    db.add(n)
    db.commit()
    return n


# --- Was zusammengehoert ------------------------------------------------- #


def test_antwort_und_ursprung_landen_im_selben_strang(welt, db):
    """⚠️ **Der Fehler, den der alte Schluessel hatte.**

    Er nahm bei einer Nachricht ohne ``References`` den Betreff-Hash. Die
    Antwort darauf traegt ``References: <kennung-der-ersten>`` — und bekam
    damit einen **anderen** Schluessel als die Nachricht, auf die sie
    antwortet. Der Strang zerfiel an genau der Stelle, an der er entsteht.
    """
    konto, ordner = welt
    erste = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    antwort = _legen(
        db,
        konto,
        ordner["posteingang"],
        kennung="<b@x>",
        betreff="Re: Angebot",
        references=["<a@x>"],
        tage=1,
    )
    assert antwort.thread_key == erste.thread_key


def test_die_kette_haelt_ueber_mehrere_stufen(welt, db):
    konto, ordner = welt
    a = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    _legen(db, konto, ordner["posteingang"], kennung="<b@x>", betreff="Re: Angebot",
           references=["<a@x>"], tage=1)
    c = _legen(db, konto, ordner["posteingang"], kennung="<c@x>", betreff="Re: Angebot",
               references=["<a@x>", "<b@x>"], tage=2)
    assert c.thread_key == a.thread_key


def test_die_eigene_antwort_aus_gesendet_gehoert_dazu(welt, db):
    """⚠️ **Der eigentliche Nutzen der Ansicht.**

    Ohne das sieht man die Frage, aber nicht die eigene Antwort darauf.
    """
    konto, ordner = welt
    frage = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    meine = _legen(
        db,
        konto,
        ordner["gesendet"],
        kennung="<b@x>",
        betreff="Re: Angebot",
        von="anna@example.com",
        an="anna@example.com",
        references=["<a@x>"],
        tage=1,
    )
    assert meine.thread_key == frage.thread_key


def test_fehlende_kopfzeilen_faengt_der_betreff_auf(welt, db):
    """Manche Clients setzen ``References`` nicht — Formular-Mails etwa."""
    konto, ordner = welt
    erste = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    ohne = _legen(db, konto, ordner["posteingang"], kennung="<b@x>", betreff="Re: Angebot", tage=1)
    assert ohne.thread_key == erste.thread_key


# --- Was NICHT zusammengehoert ------------------------------------------- #


def test_gleicher_betreff_von_fremden_bleibt_getrennt(welt, db):
    """⚠️ **Der Fall, an dem eine Gruppierung kippt.**

    „Rechnung" schreiben drei verschiedene Leute. Ohne die Bedingung
    „gemeinsame Beteiligte" laegen sie in einem Strang — und zwei davon waeren
    zugeklappt unsichtbar.
    """
    konto, ordner = welt
    eine = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Rechnung",
                  von="anna@example.com")
    andere = _legen(db, konto, ordner["posteingang"], kennung="<b@x>", betreff="Rechnung",
                    von="berta@example.com", an="jemand@example.com", tage=1)
    assert andere.thread_key != eine.thread_key


def test_gleicher_betreff_nach_langer_zeit_bleibt_getrennt(welt, db):
    """„Rechnung" kommt jeden Monat. Zwei Jahre davon waeren ein Strang, in
    dem die aktuelle verschwindet."""
    konto, ordner = welt
    alt = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Rechnung")
    neu = _legen(db, konto, ordner["posteingang"], kennung="<b@x>", betreff="Rechnung", tage=60)
    assert neu.thread_key != alt.thread_key


# --- Die Ansicht ---------------------------------------------------------- #


def test_gruppiert_gibt_eine_zeile_je_strang(klient, welt, db):
    konto, ordner = welt
    _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    _legen(db, konto, ordner["posteingang"], kennung="<b@x>", betreff="Re: Angebot",
           references=["<a@x>"], tage=1)
    _legen(db, konto, ordner["posteingang"], kennung="<c@x>", betreff="Etwas anderes",
           von="carla@example.com", tage=2)

    flach = klient.get("/api/nachrichten?nur_posteingaenge=true&grenze=200").json()
    assert len(flach) == 3

    strang = klient.get("/api/nachrichten?nur_posteingaenge=true&grenze=200&gruppiert=true").json()
    assert len(strang) == 2
    # Die neueste des Strangs steht oben, mit der Zahl daneben.
    angebot = next(z for z in strang if "Angebot" in z["betreff"])
    assert angebot["strang_anzahl"] == 2
    assert angebot["betreff"] == "Re: Angebot"


def test_die_zahl_zaehlt_ueber_ordner_hinweg(klient, welt, db):
    """⚠️ Sonst fehlt im Strang die eigene Antwort — und die ist der Nutzen."""
    konto, ordner = welt
    _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    _legen(db, konto, ordner["gesendet"], kennung="<b@x>", betreff="Re: Angebot",
           von="anna@example.com", references=["<a@x>"], tage=1)

    strang = klient.get("/api/nachrichten?nur_posteingaenge=true&grenze=200&gruppiert=true").json()
    assert len(strang) == 1
    assert strang[0]["strang_anzahl"] == 2, "Die Antwort aus „Gesendet“ wird nicht mitgezählt."


def test_einen_strang_aufklappen(klient, welt, db):
    konto, ordner = welt
    a = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    _legen(db, konto, ordner["gesendet"], kennung="<b@x>", betreff="Re: Angebot",
           von="anna@example.com", references=["<a@x>"], tage=1)

    zeilen = klient.get(f"/api/nachrichten/strang/{a.thread_key}").json()
    # ⚠️ Aeltestes zuerst: Ein Gespraech liest man von vorn.
    assert [z["betreff"] for z in zeilen] == ["Angebot", "Re: Angebot"]


def test_ein_fremder_strang_gibt_nichts_heraus(klient, zweiter_klient, welt, db):
    from conftest import anmelden, zweiten_benutzer_anlegen

    konto, ordner = welt
    a = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")

    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    assert zweiter_klient.get(f"/api/nachrichten/strang/{a.thread_key}").json() == []


def test_neu_aufbauen_repariert_zerrissene_straenge(welt, db):
    """⚠️ Ohne diesen Lauf zeigte die neue Ansicht bei bestehender Post lauter
    Einzelstuecke und saehe aus, als taete sie nichts."""
    konto, ordner = welt
    a = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    b = _legen(db, konto, ordner["posteingang"], kennung="<b@x>", betreff="Re: Angebot",
               references=["<a@x>"], tage=1)

    # Den alten, kaputten Zustand herstellen: verschiedene Schluessel.
    a.thread_key = "betreff:altmodisch"
    b.thread_key = "<a@x>"
    db.commit()

    straenge.neu_aufbauen(db, konto.benutzer_id)
    db.refresh(a)
    db.refresh(b)
    assert a.thread_key == b.thread_key


def test_die_kette_traegt_auch_ohne_gleichen_betreff(welt, db):
    """⚠️ **Der Test, der die Antwortkette wirklich prueft.**

    Bei der Mutationsprobe am 01.09.2026 blieben die anderen Tests gruen, als
    ich die Kette abschaltete — der Betreff-Rueckfall gruppierte dieselben
    Mails ohnehin. Sie bewiesen also nicht, was sie behaupteten.

    Hier kann **nur** die Kette greifen: Jemand benennt den Betreff im
    Verlauf um, wie es in jedem laengeren Gespraech passiert.
    """
    konto, ordner = welt
    erste = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot")
    umbenannt = _legen(
        db,
        konto,
        ordner["posteingang"],
        kennung="<b@x>",
        betreff="Terminvorschlag für nächste Woche",
        references=["<a@x>"],
        tage=1,
    )
    assert umbenannt.thread_key == erste.thread_key


def test_die_kette_traegt_auch_bei_neuen_beteiligten(welt, db):
    """Jemand wird in ein laufendes Gespraech hineingezogen — auch dann haelt
    die Kette, obwohl kein Beteiligter uebereinstimmt."""
    konto, ordner = welt
    erste = _legen(db, konto, ordner["posteingang"], kennung="<a@x>", betreff="Angebot",
                   von="anna@example.com", an="anna@example.com")
    dritter = _legen(
        db,
        konto,
        ordner["posteingang"],
        kennung="<c@x>",
        betreff="Zwischenstand",
        von="carla@example.com",
        an="dora@example.com",
        references=["<a@x>"],
        tage=2,
    )
    assert dritter.thread_key == erste.thread_key
