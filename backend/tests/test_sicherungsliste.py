"""Ruecksetzpunkte auf dem Server.

⚠️ **Der wichtigste Test hier ist ``test_ein_erfundener_name_kommt_nicht_durch``.**
Der Name steht in der Adresszeile. Ohne Pruefung stuende hier ein Weg offen,
mit ``../../`` jede Datei des Containers zu holen oder zu loeschen — und zwar
fuer den Betreiber, also genau fuer das Konto, das nichts davon merken wuerde.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal, einstellung_lesen, einstellung_schreiben
from app.services import sicherung, sicherungsliste
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen

ARCHIVPASSWORT = "archiv-passwort-1"


def test_die_liste_ist_zuerst_leer(klient):
    einrichten(klient)
    antwort = klient.get("/api/sicherung/liste")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["eintraege"] == []


def test_anlegen_und_wiederfinden(klient):
    einrichten(klient)
    angelegt = klient.post("/api/sicherung/liste", json={"kommentar": "vor dem Umbau"})
    assert angelegt.status_code == 201, angelegt.text

    eintraege = klient.get("/api/sicherung/liste").json()["eintraege"]
    assert len(eintraege) == 1
    assert eintraege[0]["art"] == "manuell"
    assert eintraege[0]["kommentar"] == "vor dem Umbau"
    assert eintraege[0]["groesse"] > 0


def test_entfernen_raeumt_auch_den_beipackzettel_weg(klient):
    einrichten(klient)
    name = klient.post("/api/sicherung/liste", json={"kommentar": "weg damit"}).json()["name"]

    assert klient.delete(f"/api/sicherung/liste/{name}").status_code == 204
    assert klient.get("/api/sicherung/liste").json()["eintraege"] == []

    ordner = sicherungsliste._ordner()
    assert not (ordner / name).exists()
    assert not (ordner / name.replace(".db", ".json")).exists()


@pytest.mark.parametrize(
    "name",
    [
        "../nexmail.db",
        "../secret.key",
        "..\\nexmail.db",
        "nexmail-20260901.db",
        "nexmail-20260901-120000.db.bak",
    ],
)
def test_ein_erfundener_name_kommt_nicht_durch(klient, name):
    """⚠️ Geprueft wird gegen ein Muster, nicht gegen „enthaelt keine Punkte".

    ⚠️ **Und geprueft wird am Dienst, nicht ueber HTTP.** Der erste Anlauf ging
    ueber die Adresse — und war damit hohl: Ein erfundener Name trifft ohnehin
    keine Datei, also antwortete es auch ohne jede Pruefung mit 404. Die
    Mutationsprobe hat genau das gezeigt.

    ``../nexmail.db`` ist der Fall, auf den es ankommt: Diese Datei **gibt es**
    — es ist die laufende Datenbank. Ohne das Muster liesse sie sich hier
    herunterladen und loeschen.
    """
    einrichten(klient)
    with pytest.raises(sicherung.SicherungFehler):
        sicherungsliste._datei(name)


def test_die_laufende_datenbank_liegt_wirklich_dort(klient):
    """Ohne das waere der Test darueber eine Behauptung ueber eine leere Stelle."""
    einrichten(klient)
    assert (sicherungsliste._ordner() / ".." / "nexmail.db").resolve().exists()


def test_ueber_die_adresse_kommt_auch_nichts_durch(klient):
    einrichten(klient)
    for name in ("nexmail-20260901.db", "irgendwas.db"):
        assert klient.delete(f"/api/sicherung/liste/{name}").status_code == 404
        assert (
            klient.post(
                f"/api/sicherung/liste/{name}/archiv", json={"passwort": ARCHIVPASSWORT}
            ).status_code
            == 400
        )


def test_der_download_ist_die_schlanke_fassung(klient):
    """⚠️ Was hinausgeht, ist nicht die Datei aus der Liste."""
    einrichten(klient)
    name = klient.post("/api/sicherung/liste", json={"kommentar": ""}).json()["name"]

    antwort = klient.post(
        f"/api/sicherung/liste/{name}/archiv", json={"passwort": ARCHIVPASSWORT}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.headers["content-type"] == "application/zip"
    assert name[:-3] in antwort.headers["content-disposition"]


def test_nur_der_betreiber_kommt_an_die_liste(klient, db):
    """⚠️ Eine Kopie der Datenbank traegt die Postfaecher **aller** Benutzer."""
    einrichten(klient)
    _, geheimnis = zweiten_benutzer_anlegen(db)

    zweiter = klient
    zweiter.post("/api/auth/abmelden")
    anmelden(zweiter, "zweiter", "auch-geheim-456", geheimnis)

    assert zweiter.get("/api/sicherung/liste").status_code == 403
    assert zweiter.post("/api/sicherung/liste", json={"kommentar": ""}).status_code == 403


# --- Aufraeumen und Zeitplan ---------------------------------------------- #


def test_aufraeumen_behaelt_die_juengsten(klient):
    einrichten(klient)
    for n in range(4):
        sicherungsliste.anlegen("manuell", f"Nummer {n}")

    namen_vorher = [e["name"] for e in sicherungsliste.liste()]
    sicherungsliste.aufraeumen(2)
    namen_nachher = [e["name"] for e in sicherungsliste.liste()]

    assert len(namen_nachher) == 2
    assert namen_nachher == namen_vorher[:2], "Es wurden die falschen weggeworfen."


def test_der_zeitplan_wird_gemerkt(klient):
    einrichten(klient)
    antwort = klient.put(
        "/api/sicherung/zeitplan", json={"takt": "woechentlich", "behalten": 7}
    )
    assert antwort.status_code == 200, antwort.text

    uebersicht = klient.get("/api/sicherung/liste").json()
    assert uebersicht["zeitplan"] == {"takt": "woechentlich", "behalten": 7}


def test_ein_unbekannter_takt_wird_abgewiesen(klient):
    einrichten(klient)
    antwort = klient.put("/api/sicherung/zeitplan", json={"takt": "stuendlich", "behalten": 5})
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "takt_unbekannt"
    assert "taeglich" in antwort.json()["werte"]["moeglich"]


def test_ohne_zeitplan_ist_nie_etwas_faellig(klient):
    einrichten(klient)
    with SessionLocal() as db:
        assert sicherungsliste.faellig(db) is False


def test_der_erste_lauf_ist_sofort_faellig(klient):
    """Sonst entstuende die erste Sicherung erst einen Tag nach dem Einschalten."""
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, "taeglich")
        db.commit()
        assert sicherungsliste.faellig(db) is True


def test_gemessen_wird_am_letzten_lauf_nicht_an_der_uhrzeit(klient):
    """⚠️ „Täglich um 3 Uhr" faellt bei einem NAS aus, das nachts aus ist."""
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, "woechentlich")

        vor_sechs_tagen = datetime.now(timezone.utc) - timedelta(days=6)
        einstellung_schreiben(
            db, sicherungsliste.SCHLUESSEL_ZULETZT, vor_sechs_tagen.isoformat()
        )
        db.commit()
        assert sicherungsliste.faellig(db) is False

        vor_acht_tagen = datetime.now(timezone.utc) - timedelta(days=8)
        einstellung_schreiben(
            db, sicherungsliste.SCHLUESSEL_ZULETZT, vor_acht_tagen.isoformat()
        )
        db.commit()
        assert sicherungsliste.faellig(db) is True


def test_eine_faellige_runde_legt_an_und_merkt_sich_das(klient):
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, "taeglich")
        db.commit()

    assert sicherungsliste.wenn_faellig() is True
    eintraege = sicherungsliste.liste()
    assert len(eintraege) == 1
    assert eintraege[0]["art"] == "zeitplan"

    # Und beim zweiten Mal passiert nichts mehr.
    assert sicherungsliste.wenn_faellig() is False
    assert len(sicherungsliste.liste()) == 1

    with SessionLocal() as db:
        assert einstellung_lesen(db, sicherungsliste.SCHLUESSEL_ZULETZT) != ""


def test_eine_kopie_ohne_beipackzettel_verschwindet_nicht(klient):
    """⚠️ ``db.py`` legt vor einem Schemawechsel nur die ``.db`` an.

    Wer nur Eintraege mit Zettel zeigt, blendet genau die Ruecksetzpunkte aus,
    die vor einem Update entstanden sind — also die wichtigsten.
    """
    einrichten(klient)
    name = sicherungsliste.anlegen("manuell", "mit Zettel")["name"]
    (sicherungsliste._ordner() / name.replace(".db", ".json")).unlink()

    eintraege = sicherungsliste.liste()
    assert len(eintraege) == 1
    assert eintraege[0]["art"] == "update"
