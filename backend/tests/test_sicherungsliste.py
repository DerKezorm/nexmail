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
from app.services import sicherung_haken, sicherungsliste
from app.vendor import nexsicherung
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
    # Seit dem Modul sicherung prüft das Modul den Namen (``archives.path_of``), für alte und neue Namen.
    with pytest.raises(nexsicherung.BackupError):
        nexsicherung.archives.path_of(name)


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
    """Seit dem Modul sicherung: von den automatischen bleiben die jüngsten; eine von Hand gemachte bleibt immer."""
    einrichten(klient)
    von_hand = nexsicherung.archives.create(kind=nexsicherung.MANUAL, note="von Hand").name
    automatisch = [nexsicherung.archives.create(kind=nexsicherung.SCHEDULED).name for _ in range(4)]

    nexsicherung.archives.prune(2)
    namen = [e["name"] for e in klient.get("/api/sicherung/liste").json()["eintraege"]]

    assert von_hand in namen
    assert [n for n in automatisch if n in namen] == automatisch[-2:], "Es wurden die falschen weggeworfen."


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


def test_der_zeitplan_haelt_die_uhrzeit_und_bis_365(klient):
    """Seit dem Modul: dazu eine Uhrzeit (``sicherung_uhrzeit``), Behalten bis 365; der alte Weg behält seine Form."""
    einrichten(klient)
    gesetzt = klient.put("/api/server/storage/backups/schedule", json={"every": "monthly", "time": "04:30", "keep": 200})
    assert gesetzt.status_code == 200, gesetzt.text
    assert klient.get("/api/sicherung/liste").json()["zeitplan"] == {"takt": "monatlich", "behalten": 200}
    with SessionLocal() as db:
        assert einstellung_lesen(db, sicherung_haken.SCHLUESSEL_UHRZEIT) == "04:30"
    # Der alte Weg lässt die Uhrzeit stehen.
    assert klient.put("/api/sicherung/zeitplan", json={"takt": "taeglich", "behalten": 3}).status_code == 200
    assert klient.get("/api/server/storage/backups").json()["schedule"] == {"every": "daily", "time": "04:30", "keep": 3}


def test_ein_gespeicherter_takt_von_vorher_gilt_weiter(klient):
    """Was 0.33.0 gespeichert hat (deutsche Namen, ohne Uhrzeit), liest das Modul als seinen Zeitplan."""
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, "woechentlich")
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_BEHALTEN, "7")
    assert nexsicherung.plan.load() == nexsicherung.Schedule(every="weekly", time="03:00", keep=7)


def test_ohne_zeitplan_ist_nie_etwas_faellig(klient):
    einrichten(klient)
    assert nexsicherung.plan.run_job() is False
    assert klient.get("/api/sicherung/liste").json()["eintraege"] == []


def test_der_erste_lauf_ist_sofort_faellig(klient):
    """Sonst entstuende die erste Sicherung erst einen Tag nach dem Einschalten."""
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, "taeglich")
        db.commit()
    assert nexsicherung.plan.run_job() is True


def test_ein_server_der_aus_war_holt_nach(klient):
    """⚠️ „Täglich um 3 Uhr" fiel früher bei einem NAS aus, das nachts aus ist. Das Modul holt nach: fällig, sobald
    die letzte Uhrzeit vorbei ist und seit ihr keine geplante kam (Woche: 6 Tage 18 Stunden Abstand)."""
    einrichten(klient)
    woche = nexsicherung.Schedule(every="weekly", time="03:00", keep=5)
    jetzt = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    assert nexsicherung.plan.due(woche, jetzt - timedelta(days=6), jetzt, timezone.utc) is False
    assert nexsicherung.plan.due(woche, jetzt - timedelta(days=8), jetzt, timezone.utc) is True


def test_eine_faellige_runde_legt_an_und_merkt_sich_das(klient):
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, sicherungsliste.SCHLUESSEL_TAKT, "taeglich")
        db.commit()

    assert nexsicherung.plan.run_job() is True
    eintraege = klient.get("/api/sicherung/liste").json()["eintraege"]
    assert len(eintraege) == 1
    assert eintraege[0]["art"] == "zeitplan"

    # Und beim zweiten Mal passiert nichts mehr.
    assert nexsicherung.plan.run_job() is False
    assert len(klient.get("/api/sicherung/liste").json()["eintraege"]) == 1
    assert klient.get("/api/sicherung/liste").json()["zuletzt"] != ""


def test_eine_kopie_ohne_beipackzettel_verschwindet_nicht(klient):
    """⚠️ ``db.py`` legt vor einem Schemawechsel nur die ``.db`` an.

    Wer nur Eintraege mit Zettel zeigt, blendet genau die Ruecksetzpunkte aus,
    die vor einem Update entstanden sind — also die wichtigsten.
    """
    einrichten(klient)
    name = sicherungsliste.anlegen("manuell", "mit Zettel")["name"]
    (sicherungsliste._ordner() / name.replace(".db", ".json")).unlink()

    eintraege = klient.get("/api/sicherung/liste").json()["eintraege"]
    assert [e["name"] for e in eintraege] == [name]
    assert eintraege[0]["art"] == "update"
    modul = klient.get("/api/server/storage/backups").json()["backups"]
    assert [(e["name"], e["kind"], e["readable"]) for e in modul] == [(name, "update", True)]


# --- Die Frage im Fenster „Wiederherstellen“ (sicherung 1.0.1, E38) -------- #


def _hochgeladen_mit_adresse(klient, archiv_adresse: str, jetzt: str) -> str:
    """Ein schlankes, verschlüsseltes Archiv dieses Servers mit ``archiv_adresse``, wieder hochgeladen, während der
    Server danach ``jetzt`` als öffentliche Adresse hat. Gibt den Namen in der Liste zurück."""
    import base64

    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", archiv_adresse)
    name = klient.post("/api/server/storage/backups", json={}).json()["name"]
    datei = klient.post(
        f"/api/server/storage/backups/{name}/download",
        json={"password": "sehr-geheim-123", "archive_password": ARCHIVPASSWORT},
    )
    assert datei.status_code == 200, datei.text
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", jetzt)
    oben = klient.post(
        "/api/server/storage/backups/upload",
        content=datei.content,
        headers={"x-backup-password": base64.b64encode(b"sehr-geheim-123").decode("ascii")},
    )
    assert oben.status_code in (200, 201), oben.text
    return oben.json()["name"]


def test_die_pruefung_nennt_die_rueckkehradressen_beider_adressen(klient):
    """Die alte Seite nannte je Anmeldeanbieter die Adresse, die bei ihm stehen muss; das Fenster des Moduls zeigt sie
    über ``details``, für die jetzige Adresse und für die aus dem Archiv."""
    from app.models import OidcAnbieter

    einrichten(klient)
    with SessionLocal() as db:
        db.add(OidcAnbieter(kuerzel="pocket", anzeigename="Pocket ID", issuer="https://id.example.com", client_id="nexmail"))
        db.commit()
    neu = _hochgeladen_mit_adresse(klient, "https://alt.example.com", "https://neu.example.com")
    befund = klient.post(f"/api/server/storage/backups/{neu}/check", json={"archive_password": ARCHIVPASSWORT})
    assert befund.status_code == 200, befund.text
    details = befund.json()["details"]
    assert details["adresse_im_archiv"] == "https://alt.example.com"
    assert details["adresse_weicht_ab"] is True
    (anbieter,) = details["oidc_anbieter"]
    assert anbieter["anzeigename"] == "Pocket ID"
    # Ohne eigenen ``redirect_path`` (NULL) kennt der Anbieter den Weg von 0.21 (``rueckleitpfad``).
    assert anbieter["rueckkehr_adresse"] == "https://neu.example.com/api/oidc/pocket/zurueck"
    assert anbieter["rueckkehr_adresse_archiv"] == "https://alt.example.com/api/oidc/pocket/zurueck"


@pytest.mark.parametrize(
    ("antwort", "danach"),
    [({"address": True}, "https://alt.example.com"), ({"address": False}, "https://neu.example.com"), (None, "https://neu.example.com")],
)
def test_wiederherstellen_uebernimmt_die_adresse_nur_auf_wunsch(klient, antwort, danach):
    """Wie der alte Weg: die Adresse aus dem Archiv, wenn der Betreiber es ankreuzt, sonst bleibt die jetzige."""
    einrichten(klient)
    neu = _hochgeladen_mit_adresse(klient, "https://alt.example.com", "https://neu.example.com")
    rumpf = {"password": "sehr-geheim-123", "archive_password": ARCHIVPASSWORT}
    if antwort is not None:
        rumpf["options"] = antwort
    zurueck = klient.post(f"/api/server/storage/backups/{neu}/restore", json=rumpf)
    assert zurueck.status_code == 200, zurueck.text
    with SessionLocal() as db:
        assert einstellung_lesen(db, "oeffentliche_adresse") == danach


def test_eine_eigene_sicherung_behaelt_die_jetzige_adresse_ausser_auf_wunsch(klient):
    """Auch eine Sicherung aus der eigenen Liste (ZIP des Moduls): ohne Haken bleibt die jetzige Adresse."""
    einrichten(klient)
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://alt.example.com")
    name = klient.post("/api/server/storage/backups", json={}).json()["name"]
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://neu.example.com")
    rumpf = {"password": "sehr-geheim-123"}
    assert klient.post(f"/api/server/storage/backups/{name}/restore", json=rumpf).status_code == 200
    with SessionLocal() as db:
        assert einstellung_lesen(db, "oeffentliche_adresse") == "https://neu.example.com"
    einrichten_wieder = klient.post("/api/auth/anmelden", json={"benutzername": "betreiber", "passwort": "sehr-geheim-123"})
    assert einrichten_wieder.status_code == 200, einrichten_wieder.text
    rumpf["options"] = {"address": True}
    assert klient.post(f"/api/server/storage/backups/{name}/restore", json=rumpf).status_code == 200
    with SessionLocal() as db:
        assert einstellung_lesen(db, "oeffentliche_adresse") == "https://alt.example.com"


def test_eine_fremde_frage_wird_abgewiesen(klient):
    einrichten(klient)
    name = klient.post("/api/server/storage/backups", json={}).json()["name"]
    antwort = klient.post(
        f"/api/server/storage/backups/{name}/restore", json={"password": "sehr-geheim-123", "options": {"schluessel": True}}
    )
    assert antwort.status_code == 422


# --- Anlegen über den alten Weg, wie der Vertragstest des Moduls (E53, 6edff85) ------------------------------------- #


def test_alter_weg_notiz_ueber_200_zeichen_422_und_nichts_entsteht(klient):
    einrichten(klient)
    vorher = len(nexsicherung.archives.entries())
    assert klient.post("/api/sicherung/liste", json={"kommentar": "x" * 201}).status_code == 422
    assert len(nexsicherung.archives.entries()) == vorher
    assert klient.post("/api/sicherung/liste", json={"kommentar": "x" * 200}).status_code == 201


def test_alter_weg_ohne_sitzung_401_mit_und_ohne_rumpf(klient):
    from fastapi.testclient import TestClient

    from app.main import app

    einrichten(klient)
    vorher = len(nexsicherung.archives.entries())
    fremd = TestClient(app)
    assert fremd.post("/api/sicherung/liste").status_code == 401
    assert fremd.post("/api/sicherung/liste", json={"kommentar": "x"}).status_code == 401
    assert len(nexsicherung.archives.entries()) == vorher
