"""Das Archiv traegt nur, was das Postfach nicht wieder hergibt.

⚠️ **Der Test, auf den es hier ankommt, ist ``test_der_uid_stand_faellt_auf_null``.**
Alles andere schlaegt beim Einspielen sofort sichtbar fehl. Ein
stehengebliebenes ``hoechste_uid`` dagegen laesst den Abgleich nur noch das
holen, was *neuer* ist als der weggeworfene Stand: Das Postfach bleibt halb
leer, nichts meldet einen Fehler, und es sieht aus wie ein geglueckter
Rundlauf.

Gemessen am 01.09.2026 an ``data-dev``: 1890 Nachrichten machen aus einer
0,36 MB grossen Datenbank eine von 2,79 MB. 87 % des Archivs waeren damit
etwas, das noch im Postfach auf dem Server liegt.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pyzipper
import pytest

from app.models import Nachricht, Ordner, Sitzung
from app.services import anbieter, konten
from conftest import einrichten
from test_konten import _eingabe, _guter_befund

ARCHIVPASSWORT = "archiv-passwort-1"


@pytest.fixture
def ohne_netz(monkeypatch):
    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(konten, "pruefen", lambda daten, wo="": _guter_befund())
    yield


@pytest.fixture
def welt(klient, ohne_netz, db):
    """Ein Postfach mit Nachrichten, einem UID-Stand und einer Sitzung."""
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]
    posteingang = (
        db.query(Ordner).filter(Ordner.konto_id == konto_id, Ordner.rolle == "posteingang").one()
    )
    for n in range(5):
        db.add(
            Nachricht(
                benutzer_id=posteingang.konto.benutzer_id,
                konto_id=konto_id,
                ordner_id=posteingang.id,
                uid=100 + n,
                message_id=f"<mail{n}@example.com>",
                betreff=f"Mail {n}",
                von_name="Wer Auch Immer",
                von_adresse="wer@example.com",
                datum=datetime(2026, 9, 1, 12, n, tzinfo=timezone.utc),
            )
        )
    posteingang.hoechste_uid = 104
    posteingang.uidvalidity = 42
    db.commit()
    return konto_id, posteingang.id


def _archiv(klient) -> bytes:
    antwort = klient.post("/api/sicherung/erstellen", json={"passwort": ARCHIVPASSWORT})
    assert antwort.status_code == 200, antwort.text
    return antwort.content


def _datenbank_im_archiv(daten: bytes):
    """Die Datenbank aus dem Archiv als offene Verbindung."""
    ordner = tempfile.mkdtemp()
    with pyzipper.AESZipFile(io.BytesIO(daten)) as zip_datei:
        zip_datei.setpassword(ARCHIVPASSWORT.encode())
        zip_datei.extract("nexmail.db", ordner)
    return sqlite3.connect(str(Path(ordner) / "nexmail.db"))


def _manifest(daten: bytes) -> dict:
    with pyzipper.AESZipFile(io.BytesIO(daten)) as zip_datei:
        zip_datei.setpassword(ARCHIVPASSWORT.encode())
        return json.loads(zip_datei.read("manifest.json").decode("utf-8"))


def test_die_nachrichten_bleiben_draussen(klient, welt, db):
    """Sie liegen noch im Postfach — das Archiv soll klein genug zum Laden sein."""
    assert db.query(Nachricht).count() == 5

    verbindung = _datenbank_im_archiv(_archiv(klient))
    try:
        assert verbindung.execute("select count(*) from nachricht").fetchone()[0] == 0
    finally:
        verbindung.close()

    # Und in der laufenden Installation stehen sie unveraendert.
    assert db.query(Nachricht).count() == 5


def test_der_uid_stand_faellt_auf_null(klient, welt):
    """⚠️ **Der Test, der die stille Variante verhindert.**

    Bliebe ``hoechste_uid`` bei 104, holte der Abgleich nach dem Einspielen
    nur noch UID 105 aufwaerts. Die fuenf Mails davor kaemen nie zurueck — und
    weil kein Fehler auftritt, sieht das aus wie ein geglueckter Rundlauf.
    """
    verbindung = _datenbank_im_archiv(_archiv(klient))
    try:
        stand = verbindung.execute(
            "select hoechste_uid, uidvalidity, anzahl, ungelesen from ordner"
        ).fetchall()
    finally:
        verbindung.close()

    assert stand, "Ohne Ordner prueft dieser Test nichts."
    for hoechste, gueltigkeit, anzahl, ungelesen in stand:
        assert hoechste == 0
        assert gueltigkeit == 0
        assert anzahl == 0
        assert ungelesen == 0


def test_der_suchindex_ist_wirklich_leer(klient, welt):
    """⚠️ Ein ``delete`` auf einer FTS5-Tabelle mit ``content='…'`` raeumt nicht auf.

    Beim ersten Versuch blieb der Index mit 1,03 MB stehen, obwohl die Tabelle
    ``nachricht_fts`` null Zeilen meldete — die Daten liegen in
    ``nachricht_fts_data``. Wer nur die sichtbare Tabelle zaehlt, haelt ein
    Archiv fuer schlank, das es nicht ist.
    """
    verbindung = _datenbank_im_archiv(_archiv(klient))
    try:
        # ⚠️ Gemessen wird die **Wirkung**, nicht eine Zeilenzahl.
        # ``nachricht_fts_data`` behaelt zwei Verwaltungszeilen, egal wie leer
        # der Index ist — wer dagegen prueft, prueft eine Zahl ohne Bedeutung.
        treffer = verbindung.execute(
            "select count(*) from nachricht_fts where nachricht_fts match 'Mail'"
        ).fetchone()[0]
        begriffe = verbindung.execute("select count(*) from nachricht_fts_idx").fetchone()[0]
    finally:
        verbindung.close()

    assert treffer == 0, "Ein Betreff aus dem Postfach ist im Archiv noch auffindbar."
    assert begriffe == 0, f"Der Suchindex traegt noch {begriffe} Begriffe."


def test_die_sitzungen_kommen_nicht_mit(klient, welt, db):
    """⚠️ Ein Archiv, das Anmelde-Token wiederbelebt, hebt jedes Abmelden auf."""
    assert db.query(Sitzung).count() >= 1

    verbindung = _datenbank_im_archiv(_archiv(klient))
    try:
        assert verbindung.execute("select count(*) from sitzung").fetchone()[0] == 0
    finally:
        verbindung.close()


def test_die_straenge_werden_neu_aufgebaut(klient, welt):
    """Ohne Nachrichten gibt es nichts zu ordnen — der Aufbau muss wieder laufen."""
    verbindung = _datenbank_im_archiv(_archiv(klient))
    try:
        zeile = verbindung.execute(
            "select count(*) from einstellung where schluessel = 'straenge_aufgebaut'"
        ).fetchone()[0]
    finally:
        verbindung.close()

    assert zeile == 0


def test_das_manifest_nennt_adresse_und_anbieter(klient, welt):
    """Beides braucht der Bericht beim Einspielen, **bevor** etwas ersetzt ist."""
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://alt.example"})

    manifest = _manifest(_archiv(klient))
    assert manifest["oeffentliche_adresse"] == "https://alt.example"
    assert manifest["nachrichten_entfernt"] == 5
    assert isinstance(manifest["oidc_anbieter"], list)


# --- Die oeffentliche Adresse -------------------------------------------- #


def test_pruefen_fasst_nichts_an(klient, welt):
    """⚠️ Der ganze Zweck des eigenen Schritts: erst sehen, dann entscheiden."""
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://alt.example"})
    archiv = _archiv(klient)
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://neu.example"})

    antwort = klient.post(
        "/api/sicherung/pruefen",
        files={"datei": ("s.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
    )
    assert antwort.status_code == 200, antwort.text

    # Nichts ersetzt: Die Einstellung von *nach* der Sicherung steht noch.
    assert (
        klient.get("/api/einstellungen").json()["oeffentliche_adresse"] == "https://neu.example"
    )


def test_eine_abweichende_adresse_wird_gemeldet(klient, welt):
    """Das Archiv kommt von woanders — genau der Fall, der sonst still bleibt."""
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://woanders.example"})
    archiv = _archiv(klient)

    befund = klient.post(
        "/api/sicherung/pruefen",
        files={"datei": ("s.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "hier.example"},
    ).json()

    assert befund["adresse_im_archiv"] == "https://woanders.example"
    assert befund["adresse_jetzt"] == "https://hier.example"
    assert befund["adresse_weicht_ab"] is True


def test_dieselbe_adresse_meldet_nichts(klient, welt):
    """⚠️ Ein Hinweis, der immer erscheint, wird nach dem zweiten Mal weggeklickt.

    Der haeufige Fall ist dieselbe Maschine — kaputte Platte, neuer Container.
    Dort darf nichts nachgefragt werden.
    """
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://hier.example"})
    archiv = _archiv(klient)

    befund = klient.post(
        "/api/sicherung/pruefen",
        files={"datei": ("s.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "hier.example"},
    ).json()

    assert befund["adresse_weicht_ab"] is False


def test_einspielen_kann_die_neue_adresse_uebernehmen(klient, welt):
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://alt.example"})
    archiv = _archiv(klient)

    antwort = klient.post(
        "/api/sicherung/einspielen",
        files={"datei": ("s.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT, "adresse": "https://neu.example"},
    )
    assert antwort.status_code == 200, antwort.text

    from app.db import SessionLocal, einstellung_lesen

    with SessionLocal() as frisch:
        assert einstellung_lesen(frisch, "oeffentliche_adresse") == "https://neu.example"


def test_ohne_angabe_bleibt_die_adresse_aus_dem_archiv(klient, welt):
    """Der haeufige Fall: dieselbe Maschine, nichts soll sich aendern."""
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://alt.example"})
    archiv = _archiv(klient)
    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://zwischendurch.example"})

    klient.post(
        "/api/sicherung/einspielen",
        files={"datei": ("s.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
    )

    from app.db import SessionLocal, einstellung_lesen

    with SessionLocal() as frisch:
        assert einstellung_lesen(frisch, "oeffentliche_adresse") == "https://alt.example"


def test_der_befund_nennt_die_rueckkehr_adresse(klient, welt, db):
    """⚠️ Die kann nexmail beim Anbieter nicht eintragen — also nennt es sie."""
    from app.models import OidcAnbieter

    db.add(
        OidcAnbieter(
            kuerzel="keycloak",
            anzeigename="Keycloak",
            issuer="https://auth.example/realms/haus",
            client_id="nexmail",
            client_secret="egal",
        )
    )
    db.commit()

    klient.put("/api/einstellungen", json={"oeffentliche_adresse": "https://alt.example"})
    archiv = _archiv(klient)

    befund = klient.post(
        "/api/sicherung/pruefen",
        files={"datei": ("s.zip", archiv, "application/zip")},
        data={"passwort": ARCHIVPASSWORT},
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "neu.example"},
    ).json()

    assert len(befund["oidc_anbieter"]) == 1
    anbieter = befund["oidc_anbieter"][0]
    assert anbieter["issuer"] == "https://auth.example/realms/haus"
    assert anbieter["rueckkehr_adresse"] == "https://neu.example/api/oidc/keycloak/zurueck"
