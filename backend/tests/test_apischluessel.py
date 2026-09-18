"""API-Schluessel und die Leseadressen unter ``/api/v1``.

Was hier festgehalten wird, sind die Grenzen, nicht die Bequemlichkeit:

* Ohne den Riegel des Betreibers geht gar nichts, und Zusperren wirkt sofort.
* Ein Schluessel sieht nur die Postfaecher, die an ihm stehen, und nur die
  seines Besitzers.
* Die Stufe ``anzahl`` gibt keine Absender und keine Betreffzeilen heraus.
* Eine Sitzung oeffnet ``/api/v1`` nicht, ein Schluessel oeffnet nichts sonst.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import ApiSchluessel, Nachricht, Ordner
from app.services import anbieter, konten
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen
from test_konten import _eingabe, _guter_befund

JETZT = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="", token="": _guter_befund())
    yield


def _postfach(klient, adresse: str) -> str:
    return klient.post("/api/konten", json=_eingabe(adresse)).json()["id"]


def _ordner(db, konto_id: str, rolle: str) -> Ordner:
    vorhanden = (
        db.query(Ordner).filter(Ordner.konto_id == konto_id, Ordner.rolle == rolle).first()
    )
    if vorhanden:
        return vorhanden
    neu = Ordner(konto_id=konto_id, pfad=f"X-{rolle}", name=rolle, rolle=rolle)
    db.add(neu)
    db.commit()
    return neu


def _mail(konto_id: str, betreff: str, *, rolle: str = "posteingang", gelesen: bool = False,
          minuten: int = 0, von: str = "absender@example.com") -> None:
    with SessionLocal() as db:
        ordner = _ordner(db, konto_id, rolle)
        uid = db.query(Nachricht).filter(Nachricht.ordner_id == ordner.id).count() + 1
        db.add(
            Nachricht(
                benutzer_id=ordner.konto.benutzer_id,
                konto_id=konto_id,
                ordner_id=ordner.id,
                uid=uid,
                betreff=betreff,
                von_name="Absender",
                von_adresse=von,
                gelesen=gelesen,
                datum=JETZT - timedelta(minutes=minuten),
                anreisser="Geheimer Anfang des Textes",
                koerper_text="Geheimer Text",
            )
        )
        db.commit()


def _aufmachen(klient) -> None:
    assert klient.put("/api/apischluessel/erlaubt", json={"erlaubt": True}).status_code == 200


def _schluessel(klient, konten: list[str], stufe: str = "betreff", name: str = "Dashboard") -> dict:
    antwort = klient.post(
        "/api/apischluessel", json={"name": name, "stufe": stufe, "konten": konten}
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _mit(klartext: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {klartext}"}


# --- Der Riegel ---------------------------------------------------------- #


def test_ab_werk_ist_zu(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")

    assert klient.get("/api/apischluessel").json()["erlaubt"] is False
    antwort = klient.post(
        "/api/apischluessel", json={"name": "x", "stufe": "anzahl", "konten": [konto]}
    )
    assert antwort.status_code == 403
    assert antwort.json()["detail"] == "api_schluessel_abgeschaltet"


def test_zusperren_haelt_vorhandene_schluessel_sofort_an_und_loescht_sie_nicht(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    klartext = _schluessel(klient, [konto])["schluessel"]
    assert klient.get("/api/v1/summary", headers=_mit(klartext)).status_code == 200

    klient.put("/api/apischluessel/erlaubt", json={"erlaubt": False})
    zu = klient.get("/api/v1/summary", headers=_mit(klartext))
    assert zu.status_code == 403
    assert zu.json()["detail"] == "api_schluessel_abgeschaltet"
    assert len(klient.get("/api/apischluessel").json()["schluessel"]) == 1

    _aufmachen(klient)
    assert klient.get("/api/v1/summary", headers=_mit(klartext)).status_code == 200


def test_nur_der_betreiber_legt_den_riegel_um(klient, zweiter_klient, db):
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.put("/api/apischluessel/erlaubt", json={"erlaubt": True})
    assert antwort.status_code == 403
    assert klient.get("/api/apischluessel/erlaubt").json()["erlaubt"] is False
    # Lesen darf jeder Angemeldete: Sein Reiter haengt davon ab.
    assert zweiter_klient.get("/api/apischluessel/erlaubt").status_code == 200


# --- Anlegen und Verwalten ----------------------------------------------- #


def test_der_klartext_steht_genau_einmal_da(klient, ohne_netz, db):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    neu = _schluessel(klient, [konto])

    assert neu["schluessel"].startswith("nxm_")
    assert len(neu["schluessel"]) > 40
    assert neu["praefix"] == neu["schluessel"][:10]
    liste = klient.get("/api/apischluessel").json()["schluessel"]
    assert "schluessel" not in liste[0]
    # Und in der Datenbank steht er auch nicht.
    zeile = db.query(ApiSchluessel).one()
    assert neu["schluessel"] not in (zeile.schluessel_hash, zeile.praefix, zeile.konten_json)


@pytest.mark.parametrize(
    "eingabe,kennung",
    [
        ({"name": " ", "stufe": "anzahl"}, "api_schluessel_name_fehlt"),
        ({"name": "x" * 81, "stufe": "anzahl"}, "api_schluessel_name_zu_lang"),
        ({"name": "x", "stufe": "alles"}, "api_schluessel_stufe_unbekannt"),
    ],
)
def test_unbrauchbare_eingaben_werden_benannt(klient, ohne_netz, eingabe, kennung):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    antwort = klient.post("/api/apischluessel", json={**eingabe, "konten": [konto]})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == kennung


def test_ohne_postfach_entsteht_kein_schluessel(klient, ohne_netz):
    einrichten(klient)
    _aufmachen(klient)
    antwort = klient.post("/api/apischluessel", json={"name": "x", "stufe": "anzahl", "konten": []})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "api_schluessel_ohne_postfach"


def test_die_obergrenze_nennt_ihre_zahl(klient, ohne_netz, monkeypatch):
    from app.services import apischluessel

    monkeypatch.setattr(apischluessel, "MAX_JE_BENUTZER", 2)
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    _schluessel(klient, [konto])
    _schluessel(klient, [konto])
    antwort = klient.post(
        "/api/apischluessel", json={"name": "x", "stufe": "anzahl", "konten": [konto]}
    )
    assert antwort.status_code == 400
    assert antwort.json() == {"detail": "api_schluessel_zu_viele", "werte": {"max": 2}}


def test_ein_fremdes_postfach_laesst_sich_nicht_freigeben(klient, zweiter_klient, db, ohne_netz):
    einrichten(klient)
    fremdes = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.post(
        "/api/apischluessel", json={"name": "x", "stufe": "betreff", "konten": [fremdes]}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "postfach_unbekannt"


def test_fremde_schluessel_sind_unsichtbar_und_unantastbar(klient, zweiter_klient, db, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    meiner = _schluessel(klient, [konto])
    _, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter_klient.get("/api/apischluessel").json()["schluessel"] == []
    assert zweiter_klient.delete(f"/api/apischluessel/{meiner['id']}").status_code == 404
    antwort = zweiter_klient.put(
        f"/api/apischluessel/{meiner['id']}",
        json={"name": "gekapert", "stufe": "betreff", "konten": []},
    )
    assert antwort.status_code == 404
    assert klient.get("/api/v1/me", headers=_mit(meiner["schluessel"])).status_code == 200


def test_widerrufen_wirkt_sofort(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    neu = _schluessel(klient, [konto])
    assert klient.delete(f"/api/apischluessel/{neu['id']}").status_code == 204

    antwort = klient.get("/api/v1/summary", headers=_mit(neu["schluessel"]))
    assert antwort.status_code == 401
    assert antwort.json()["detail"] == "api_schluessel_ungueltig"


def test_aendern_hebt_die_stufe_ohne_neuen_schluessel(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    neu = _schluessel(klient, [konto], stufe="anzahl")
    assert klient.get("/api/v1/messages/latest", headers=_mit(neu["schluessel"])).status_code == 403

    antwort = klient.put(
        f"/api/apischluessel/{neu['id']}",
        json={"name": "Flur", "stufe": "betreff", "konten": [konto]},
    )
    assert antwort.status_code == 200
    assert antwort.json()["name"] == "Flur"
    assert klient.get("/api/v1/messages/latest", headers=_mit(neu["schluessel"])).status_code == 200


# --- Die Tuer ------------------------------------------------------------ #


def test_ohne_kopfzeile_kommt_nichts_heraus(klient, ohne_netz):
    """⚠️ **Auch nicht mit Sitzung.** ``klient`` ist angemeldet; das Cookie
    faehrt mit, und trotzdem bleibt ``/api/v1`` zu."""
    einrichten(klient)
    _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    for pfad in ("/api/v1/me", "/api/v1/summary", "/api/v1/messages/latest"):
        antwort = klient.get(pfad)
        assert antwort.status_code == 401, pfad
        assert antwort.json()["detail"] == "api_schluessel_fehlt"
        assert antwort.headers["www-authenticate"] == "Bearer"


def test_ein_falscher_schluessel_ist_unbekannt(klient, ohne_netz):
    einrichten(klient)
    _aufmachen(klient)
    for falsch in ("nxm_erfunden", "irgendwas", "nxm_"):
        antwort = klient.get("/api/v1/me", headers=_mit(falsch))
        assert antwort.status_code == 401, falsch
        assert antwort.json()["detail"] == "api_schluessel_ungueltig"


def test_ein_schluessel_oeffnet_keine_andere_adresse(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    klartext = _schluessel(klient, [konto])["schluessel"]
    klient.cookies.clear()

    for pfad in ("/api/konten", "/api/nachrichten", "/api/auth/ich", "/api/apischluessel"):
        assert klient.get(pfad, headers=_mit(klartext)).status_code == 401, pfad


def test_zuletzt_benutzt_wird_gemerkt(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    neu = _schluessel(klient, [konto])
    assert neu["zuletzt_benutzt"] is None

    klient.get("/api/v1/me", headers=_mit(neu["schluessel"]))
    assert klient.get("/api/apischluessel").json()["schluessel"][0]["zuletzt_benutzt"]


def test_zuletzt_benutzt_schreibt_nicht_bei_jeder_abfrage(klient, ohne_netz, db):
    """Ein Dashboard fragt alle paar Sekunden; jede Abfrage darf kein
    Schreibvorgang sein."""
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _aufmachen(klient)
    klartext = _schluessel(klient, [konto])["schluessel"]
    klient.get("/api/v1/me", headers=_mit(klartext))
    erster = db.query(ApiSchluessel).one().zuletzt_benutzt

    klient.get("/api/v1/me", headers=_mit(klartext))
    db.expire_all()
    assert db.query(ApiSchluessel).one().zuletzt_benutzt == erster


# --- Was herauskommt ----------------------------------------------------- #


def test_me_nennt_nur_die_freigegebenen_postfaecher(klient, ohne_netz):
    einrichten(klient)
    privat = _postfach(klient, "privat@example.com")
    _postfach(klient, "arbeit@example.com")
    _aufmachen(klient)
    klartext = _schluessel(klient, [privat], stufe="anzahl", name="Flur")["schluessel"]

    ich = klient.get("/api/v1/me", headers=_mit(klartext)).json()
    assert ich["key"] == {"name": "Flur", "scope": "count"}
    assert ich["user"]["username"] == "betreiber"
    assert [m["address"] for m in ich["mailboxes"]] == ["privat@example.com"]


def test_summary_zaehlt_ungelesene_im_posteingang(klient, ohne_netz):
    einrichten(klient)
    privat = _postfach(klient, "privat@example.com")
    arbeit = _postfach(klient, "arbeit@example.com")
    fremd = _postfach(klient, "nicht-freigegeben@example.com")
    _mail(privat, "neu 1")
    _mail(privat, "neu 2")
    _mail(privat, "schon gelesen", gelesen=True)
    _mail(privat, "im Archiv", rolle="archiv")
    _mail(privat, "Werbung", rolle="junk")
    _mail(arbeit, "Dienst")
    _mail(fremd, "gehoert nicht dazu")
    _aufmachen(klient)
    klartext = _schluessel(klient, [privat, arbeit], stufe="anzahl")["schluessel"]

    stand = klient.get("/api/v1/summary", headers=_mit(klartext)).json()
    assert stand["unread"] == 3
    zahlen = {m["address"]: m["unread"] for m in stand["mailboxes"]}
    assert zahlen == {"privat@example.com": 2, "arbeit@example.com": 1}
    assert {m["status"] for m in stand["mailboxes"]} == {"ok"}


def test_summary_meldet_eine_abgewiesene_anmeldung(klient, ohne_netz, db):
    from app.models import Konto

    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    db.get(Konto, konto).stoerung = "anmeldung"
    db.commit()
    _aufmachen(klient)
    klartext = _schluessel(klient, [konto], stufe="anzahl")["schluessel"]

    stand = klient.get("/api/v1/summary", headers=_mit(klartext)).json()
    assert stand["mailboxes"][0]["status"] == "sign_in_failed"


def test_die_stufe_anzahl_gibt_keine_betreffzeilen_heraus(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _mail(konto, "Vertraulich")
    _aufmachen(klient)
    klartext = _schluessel(klient, [konto], stufe="anzahl")["schluessel"]

    antwort = klient.get("/api/v1/messages/latest", headers=_mit(klartext))
    assert antwort.status_code == 403
    assert antwort.json()["detail"] == "api_schluessel_nur_anzahl"
    for pfad in ("/api/v1/me", "/api/v1/summary"):
        assert "Vertraulich" not in klient.get(pfad, headers=_mit(klartext)).text


def test_latest_zeigt_absender_und_betreff_neueste_zuerst(klient, ohne_netz):
    einrichten(klient)
    privat = _postfach(klient, "privat@example.com")
    arbeit = _postfach(klient, "arbeit@example.com")
    _mail(privat, "aelter", minuten=30)
    _mail(arbeit, "neuer", minuten=5)
    _mail(privat, "gelesen", minuten=10, gelesen=True)
    _mail(privat, "nicht im Posteingang", rolle="gesendet", minuten=1)
    _aufmachen(klient)
    klartext = _schluessel(klient, [privat, arbeit])["schluessel"]

    mails = klient.get("/api/v1/messages/latest", headers=_mit(klartext)).json()["messages"]
    assert [m["subject"] for m in mails] == ["neuer", "gelesen", "aelter"]
    assert mails[0]["mailbox_id"] == arbeit
    assert mails[0]["from_address"] == "absender@example.com"
    assert [m["unread"] for m in mails] == [True, False, True]

    # ⚠️ Ohne Grenze und mit einer gelesenen Mail dazwischen: Mit ``limit=1``
    # kam die ungelesene ohnehin zuerst, und der Filter bewies nichts.
    nur_neu = klient.get(
        "/api/v1/messages/latest?unread_only=true", headers=_mit(klartext)
    ).json()["messages"]
    assert [m["subject"] for m in nur_neu] == ["neuer", "aelter"]
    eine = klient.get("/api/v1/messages/latest?limit=1", headers=_mit(klartext)).json()
    assert [m["subject"] for m in eine["messages"]] == ["neuer"]


def test_latest_gibt_keinen_text_heraus(klient, ohne_netz):
    einrichten(klient)
    konto = _postfach(klient, "privat@example.com")
    _mail(konto, "Betreff")
    _aufmachen(klient)
    klartext = _schluessel(klient, [konto])["schluessel"]

    antwort = klient.get("/api/v1/messages/latest", headers=_mit(klartext))
    assert "Geheimer" not in antwort.text
    assert set(antwort.json()["messages"][0]) == {
        "id", "mailbox_id", "mailbox", "from_name", "from_address",
        "subject", "date", "unread", "flagged",
    }


def test_latest_schraenkt_auf_ein_postfach_ein(klient, ohne_netz):
    einrichten(klient)
    privat = _postfach(klient, "privat@example.com")
    arbeit = _postfach(klient, "arbeit@example.com")
    _mail(privat, "Privatpost")
    _mail(arbeit, "Dienstpost")
    _aufmachen(klient)
    klartext = _schluessel(klient, [privat, arbeit])["schluessel"]

    mails = klient.get(
        f"/api/v1/messages/latest?mailbox={arbeit}", headers=_mit(klartext)
    ).json()["messages"]
    assert [m["subject"] for m in mails] == ["Dienstpost"]


def test_ein_eigenes_postfach_ohne_freigabe_ist_unbekannt(klient, ohne_netz):
    """⚠️ Sonst liesse sich die Auswahl am Schluessel mit einem Parameter
    umgehen."""
    einrichten(klient)
    privat = _postfach(klient, "privat@example.com")
    arbeit = _postfach(klient, "arbeit@example.com")
    _mail(arbeit, "Dienstpost")
    _aufmachen(klient)
    klartext = _schluessel(klient, [privat])["schluessel"]

    antwort = klient.get(f"/api/v1/messages/latest?mailbox={arbeit}", headers=_mit(klartext))
    assert antwort.status_code == 404
    assert "Dienstpost" not in antwort.text


def test_ein_entferntes_postfach_faellt_heraus(klient, ohne_netz):
    einrichten(klient)
    privat = _postfach(klient, "privat@example.com")
    arbeit = _postfach(klient, "arbeit@example.com")
    _aufmachen(klient)
    klartext = _schluessel(klient, [privat, arbeit])["schluessel"]
    assert klient.delete(f"/api/konten/{arbeit}").status_code in (200, 204)

    ich = klient.get("/api/v1/me", headers=_mit(klartext)).json()
    assert [m["id"] for m in ich["mailboxes"]] == [privat]
    assert klient.get("/api/apischluessel").json()["schluessel"][0]["konten"] == [privat]


def test_der_schluessel_geht_mit_seinem_benutzer(klient, zweiter_klient, db, ohne_netz):
    einrichten(klient)
    _aufmachen(klient)
    person, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    konto = _postfach(zweiter_klient, "zweiter@example.com")
    klartext = _schluessel(zweiter_klient, [konto])["schluessel"]

    assert klient.delete(f"/api/benutzer/{person.id}").status_code == 204
    assert klient.get("/api/v1/me", headers=_mit(klartext)).status_code == 401
