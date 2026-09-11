"""Die Adressen der Adressbücher, Beta.

⚠️ **Der teuerste Fehler wäre ein Weg, auf dem nexmail beim Anbieter etwas
löscht, ohne dass es jemand wollte.** Der Doppelgänger zählt deshalb jede
Anfrage samt Kopfzeilen: Verbinden, Abgleichen und Trennen sehen nur
``PROPFIND`` und ``REPORT``; geschrieben wird nur, was ein Mensch an einem
Kontakt geändert hat, und jedes ``PUT`` und ``DELETE`` trägt sein ``If-Match``.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from sqlalchemy import select

from app.models import Adressbuch, Benutzer, Kontakt, Kontaktgruppe, KontaktgruppeMitglied, OauthZugang
from app.services import adressbuchabgleich, carddav, kalenderabgleich, mailoauth, takt
from app.services import kontakte as kontaktdienst
from conftest import einrichten
from test_adressbuchabgleich import BUCH, PFAD, VOLL, Buchserver, _karte

LESEND = {"PROPFIND", "REPORT"}


@pytest.fixture
def welt(klient, db, monkeypatch):
    einrichten(klient)
    person = db.query(Benutzer).one()
    server = Buchserver()
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    echt = adressbuchabgleich.zugang

    def mit_transport(b, db=None):
        z = echt(b, db)
        z.transport = server.transport()
        return z

    monkeypatch.setattr(adressbuchabgleich, "zugang", mit_transport)
    # ⚠️ Das Finden ginge sonst ins Netz. Der Doppelgänger kennt genau ein Buch.
    monkeypatch.setattr(
        adressbuchabgleich,
        "finden",
        lambda art, adresse, benutzer, passwort, token="": [
            carddav.FernBuch(url=BUCH, name="Privat", ctag="ct-1")
        ],
    )
    return person, server


def _verbinden(klient) -> dict:
    antwort = klient.post(
        "/api/adressbuecher/verbinden",
        json={
            "art": "icloud",
            "benutzer": "vera",
            "passwort": "geheim",
            "auswahl": [{"url": BUCH, "name": "Privat"}],
        },
    )
    assert antwort.status_code == 200, antwort.text
    return antwort.json()[0]


def _verbunden_id(klient) -> str:
    return next(b["id"] for b in klient.get("/api/adressbuecher").json() if not b["ist_lokal"])


# --- Bücher --------------------------------------------------------------- #


def test_das_lokale_buch_steht_immer_in_der_liste(klient, welt):
    liste = klient.get("/api/adressbuecher").json()
    assert len(liste) == 1
    assert liste[0]["ist_lokal"] is True and liste[0]["art"] == ""
    assert liste[0]["kontakte"] == 0


def test_pruefen_nennt_was_schon_verbunden_ist(klient, welt):
    """Ein Eintrag, dessen Auswahl nur in eine Absage führt, ist eine Sackgasse."""
    wunsch = {"art": "icloud", "benutzer": "vera", "passwort": "geheim"}
    vorher = klient.post("/api/adressbuecher/pruefen", json=wunsch).json()
    assert vorher == [{"url": BUCH, "name": "Privat", "schon_verbunden": False}]

    _verbinden(klient)

    nachher = klient.post("/api/adressbuecher/pruefen", json=wunsch).json()
    assert nachher[0]["schon_verbunden"] is True


def test_ein_buch_ohne_namen_heisst_nach_seinem_anbieter(klient, welt, monkeypatch):
    """⚠️ iCloud nennt sein Buch nicht; im Pfad heisst es ``card``, und so stand
    es am 05.09.2026 in der Spalte."""
    monkeypatch.setattr(
        adressbuchabgleich, "finden",
        lambda art, adresse, benutzer, passwort, token="": [
            carddav.FernBuch(url=BUCH, name="card", benannt=False)
        ],
    )
    (buch,) = klient.post(
        "/api/adressbuecher/pruefen", json={"art": "icloud", "benutzer": "vera", "passwort": "x"}
    ).json()
    assert buch["name"] == "iCloud"


def test_verbinden_holt_die_kontakte_sofort(klient, welt):
    buch = _verbinden(klient)
    assert buch["herkunft"] == "iCloud" and buch["art"] == "carddav"
    assert buch["kontakte"] == 1

    kontakte = klient.get("/api/kontakte").json()
    assert len(kontakte) == 1
    assert kontakte[0]["adressbuch_id"] == buch["id"]
    # Seit Lieferung 2 gibt es kein „nur lesen" mehr; die Zeile trägt die
    # Nummern und Adressen der Karte, sonst nichts Besonderes.
    assert "nur_lesen" not in kontakte[0]


def test_zweimal_verbinden_gibt_eine_kennung(klient, welt):
    _verbinden(klient)
    antwort = klient.post(
        "/api/adressbuecher/verbinden",
        json={"art": "icloud", "benutzer": "vera", "passwort": "geheim",
              "auswahl": [{"url": BUCH, "name": "Privat"}]},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "adressbuch_schon_verbunden"
    assert klient.get("/api/adressbuecher").json()[1]["kontakte"] == 1


def test_ohne_auswahl_wird_nichts_verbunden(klient, welt):
    antwort = klient.post(
        "/api/adressbuecher/verbinden",
        json={"art": "icloud", "benutzer": "vera", "passwort": "geheim", "auswahl": []},
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "adressbuch_keine_auswahl"


def test_der_knopf_gleicht_mit_erzwingen_ab(klient, welt, monkeypatch):
    """⚠️ Der Knopf ist der Weg, übergangene Karten nachzuholen, obwohl sich
    das ``ctag`` drüben nicht geändert hat."""
    _verbinden(klient)
    gesehen: list[bool] = []
    echt = adressbuchabgleich.abgleichen

    def merken(db_, buch, erzwingen=False):
        gesehen.append(erzwingen)
        return echt(db_, buch, erzwingen)

    monkeypatch.setattr(adressbuchabgleich, "abgleichen", merken)

    antwort = klient.post("/api/adressbuecher/abgleichen")

    assert antwort.status_code == 200, antwort.text
    assert gesehen == [True]
    assert antwort.json() == {"neu": 0, "geaendert": 0, "entfernt": 0, "belegt": 0, "fehler": {}}


def test_der_bericht_nennt_belegte_karten_und_fehler(klient, db, welt):
    person, server = welt
    kontaktdienst.anlegen(db, person, "vera@example.org", name="Oma")
    buch = _verbinden(klient)
    assert klient.post("/api/adressbuecher/abgleichen").json()["belegt"] == 1

    zeile = db.get(Adressbuch, buch["id"])
    zeile.letzter_fehler = "caldav_abgewiesen"
    db.commit()
    liste = klient.get("/api/adressbuecher").json()
    assert [b["letzter_fehler"] for b in liste if b["id"] == buch["id"]] == ["caldav_abgewiesen"]


def test_sichtbarkeit_und_name_lassen_sich_aendern(klient, welt):
    buch = _verbinden(klient)
    antwort = klient.patch(
        f"/api/adressbuecher/{buch['id']}", json={"name": "Familie", "sichtbar": False}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["name"] == "Familie" and antwort.json()["sichtbar"] is False
    # Nicht mitgeschickt heisst unveraendert.
    assert klient.patch(f"/api/adressbuecher/{buch['id']}", json={"farbe": 3}).json()["name"] == "Familie"


def test_trennen_nimmt_nur_die_kopie(klient, db, welt):
    """⚠️ **Der Kern der Beta.** Trennen entfernt das Buch und seine Kontakte
    hier. Beim Anbieter kommt kein einziger schreibender Befehl an, über den
    ganzen Weg: verbinden, abgleichen, ändern, trennen."""
    person, server = welt
    buch = _verbinden(klient)
    klient.post("/api/adressbuecher/abgleichen")
    klient.patch(f"/api/adressbuecher/{buch['id']}", json={"sichtbar": False})

    antwort = klient.delete(f"/api/adressbuecher/{buch['id']}")

    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"kontakte": 1}
    assert db.query(Kontakt).count() == 0
    assert db.query(Adressbuch).filter(Adressbuch.art == "carddav").count() == 0
    assert server.karten, "Beim Anbieter ist nichts verschwunden."
    verben = {a[0] for a in server.anfragen}
    assert verben and verben <= LESEND, f"Ein schreibender Befehl ging hinaus: {verben - LESEND}"


def test_das_lokale_buch_laesst_sich_nicht_trennen(klient, welt):
    lokal = klient.get("/api/adressbuecher").json()[0]
    antwort = klient.delete(f"/api/adressbuecher/{lokal['id']}")
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "adressbuch_lokal_bleibt"


def test_ein_fremdes_buch_gibt_es_nicht(klient, welt):
    assert klient.delete("/api/adressbuecher/gibt-es-nicht").status_code == 404
    assert klient.patch("/api/adressbuecher/gibt-es-nicht", json={"name": "x"}).status_code == 404


# --- Nur lesen ------------------------------------------------------------ #


def test_eine_aenderung_geht_als_put_mit_if_match_hinaus(klient, db, welt):
    """⚠️ Erst der Server, dann die eigene Datenbank — und die Rohkarte bleibt
    ganz: Foto, Geburtstag und Apples Zeilen stehen nach der Änderung noch da.
    Geändert wird die TEL-Zeile, die das Feld zeigte, samt ihren Parametern."""
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()

    antwort = klient.patch(
        f"/api/kontakte/{kontakt['id']}", json={"name": "Vera Muster", "telefon": "+49 30 999"}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["name"] == "Vera Muster"
    assert [n["nummer"] for n in antwort.json()["nummern"]] == ["+49 30 999"]

    puts = [(i, a) for i, a in enumerate(server.anfragen) if a[0] == "PUT"]
    assert len(puts) == 1
    i, (_, pfad) = puts[0]
    assert unquote(pfad) == f"{PFAD}k1.vcf"
    assert server.koepfe[i].get("if-match") == '"e1"'
    # Das ETag stand im Kopf der Antwort; es danach noch einmal über die Liste
    # zu holen, wäre eine Runde über das Netz für nichts.
    assert server.anfragen[i + 1:] == [], "Nach dem PUT wurde noch einmal nachgeschlagen."
    etag, karte = server.karten[f"{PFAD}k1.vcf"]
    assert "FN:Vera Muster" in karte and "N:Muster;Vera;;;" in karte
    assert "TEL;type=CELL;type=VOICE:+49 30 999" in karte and "+49 30 123456" not in karte
    for fremd in ("PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRg", "BDAY:1980-01-01", "X-APPLE-SUBLOCALITY:Mitte"):
        assert fremd in karte, fremd
    zeile = db.query(Kontakt).one()
    assert zeile.name == "Vera Muster" and zeile.telefon == "+49 30 999"
    assert zeile.etag == etag and zeile.roh == karte and zeile.schmutzig is False


def test_ohne_etag_im_kopf_wird_es_nachgeschlagen(klient, db, welt):
    """Google schickt zum PUT kein ETag (beim Kalender am 03.09.2026 gemessen).
    Ohne Nachschlagen liefe der zweite Schreibvorgang mit dem alten ``If-Match``
    in einen Konflikt, den es gar nicht gibt."""
    person, server = welt
    server.etag_im_kopf = False
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()

    erste = klient.patch(f"/api/kontakte/{kontakt['id']}", json={"name": "Vera Eins"})
    assert erste.status_code == 200, erste.text
    etag, _ = server.karten[f"{PFAD}k1.vcf"]
    assert db.query(Kontakt).one().etag == etag
    zweite = klient.patch(f"/api/kontakte/{kontakt['id']}", json={"name": "Vera Zwei"})
    assert zweite.status_code == 200, "Der zweite Schreibvorgang lief mit veraltetem If-Match in einen Konflikt."


def test_die_listen_gehen_als_zeilen_hinaus_und_kommen_zurueck(klient, db, welt):
    """Der Felder-Schritt über die Adresse: Nummern mit Art und eigener
    Beschriftung, Anschrift, Geburtstag. Die Karte trägt danach genau diese
    Zeilen, und die Zeile liest sie wieder so."""
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()
    assert (kontakt["vorname"], kontakt["nachname"]) == ("Vera", "Beispiel")

    antwort = klient.patch(
        f"/api/kontakte/{kontakt['id']}",
        json={
            "vorname": "Vera", "nachname": "Muster", "abteilung": "Einkauf", "geburtstag": "1981-02-03",
            "nummern": [
                {"nummer": "+49 30 123456", "art": "cell", "bevorzugt": True},
                {"nummer": "030 999", "art": "", "beschriftung": "Zweitbüro"},
            ],
            "adressen": [{"adresse": "vera@example.org", "art": "home", "bevorzugt": True}],
            "anschriften": [{"strasse": "Beispielstraße 12", "plz": "10115", "ort": "Berlin", "land": "Deutschland", "art": "home"}],
        },
    )
    assert antwort.status_code == 200, antwort.text
    zeile = antwort.json()
    assert [(n["nummer"], n["art"], n["beschriftung"]) for n in zeile["nummern"]] == [
        ("+49 30 123456", "cell", ""), ("030 999", "", "Zweitbüro"),
    ]
    assert zeile["anschriften"][0]["ort"] == "Berlin" and zeile["geburtstag"] == "1981-02-03"
    assert zeile["name"] == "Vera Muster" and zeile["telefon"] == "+49 30 123456"

    _, karte = server.karten[f"{PFAD}k1.vcf"]
    for erwartet in (
        "N:Muster;Vera;;;", "ORG:Beispiel GmbH;Einkauf", "BDAY:1981-02-03",
        "TEL;TYPE=CELL:+49 30 123456", "X-ABLabel:Zweitbüro",
        "ADR;type=HOME:;;Beispielstraße 12;Berlin;;10115;Deutschland",
        "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRg",
    ):
        assert erwartet in karte, erwartet
    # Und die Suche findet die eigene Beschriftung, Umlaut inklusive.
    assert [k["id"] for k in klient.get("/api/kontakte?suche=zweitbüro").json()] == [kontakt["id"]]
    assert [k["id"] for k in klient.get("/api/kontakte?suche=030 999").json()] == [kontakt["id"]]


def test_die_fremde_fassung_traegt_die_listen(klient, db, welt):
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()
    server.karten[f"{PFAD}k1.vcf"] = (
        "e2", _karte(name="Vera Telefon", extra="TEL;type=CELL:+49 170 1\r\nTEL;type=HOME:030 2\r\n"),
    )
    bild = klient.get(f"/api/kontakte/{kontakt['id']}/konflikt").json()
    assert [(n["nummer"], n["art"], n["bevorzugt"]) for n in bild["fremd"]["nummern"]] == [
        ("+49 170 1", "cell", True), ("030 2", "home", False),
    ]
    assert (bild["fremd"]["vorname"], bild["fremd"]["nachname"]) == ("Vera", "Telefon")


def test_loeschen_nimmt_die_karte_beim_anbieter_mit_if_match(klient, db, welt):
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()

    assert klient.delete(f"/api/kontakte/{kontakt['id']}").status_code == 204

    i = next(i for i, a in enumerate(server.anfragen) if a[0] == "DELETE")
    assert server.koepfe[i].get("if-match") == '"e1"'
    assert server.karten == {}
    assert db.query(Kontakt).count() == 0


def test_was_der_server_ablehnt_passiert_hier_nicht(klient, db, welt):
    """Der Doppelgänger nimmt kein PUT und kein DELETE an (405): Die Zeile
    bleibt, wie sie war, und die Kennung sagt, dass es der Anbieter war."""
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()
    server.nur_lesen = True

    antwort = klient.patch(f"/api/kontakte/{kontakt['id']}", json={"name": "Anders"})
    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "carddav_schreiben_gescheitert"
    assert db.query(Kontakt).one().name == "Vera Beispiel"

    geloescht = klient.delete(f"/api/kontakte/{kontakt['id']}")
    assert geloescht.status_code == 502
    assert geloescht.json()["detail"] == "carddav_loeschen_gescheitert"
    assert db.query(Kontakt).count() == 1


def test_ein_konflikt_wird_gefragt_nicht_ueberbuegelt(klient, db, welt):
    """⚠️ Jemand hat die Karte am Telefon geändert (neues ETag drüben). Die
    eigene Änderung wird nicht geschrieben; die andere Fassung lässt sich
    ansehen — und „meine gewinnt" schreibt auf der FRISCHEN Karte, samt der
    Zeile, die drüben inzwischen dazukam."""
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()
    server.karten[f"{PFAD}k1.vcf"] = (
        "e2",
        _karte(name="Vera Telefon", extra="NOTE:Kennt den Weg\r\nX-NEU:vom Telefon\r\n"),
    )

    antwort = klient.patch(f"/api/kontakte/{kontakt['id']}", json={"name": "Vera Rechner"})
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "kontakt_konflikt"
    assert db.query(Kontakt).one().name == "Vera Beispiel"
    assert server.karten[f"{PFAD}k1.vcf"][0] == "e2", "Der Konflikt hat drüben etwas überschrieben."

    bild = klient.get(f"/api/kontakte/{kontakt['id']}/konflikt").json()
    assert bild["vorhanden"] is True and bild["fremd"]["name"] == "Vera Telefon"
    assert db.query(Kontakt).one().name == "Vera Beispiel", "Ansehen hat die Zeile angefasst."

    antwort = klient.patch(
        f"/api/kontakte/{kontakt['id']}", json={"name": "Vera Rechner", "erzwingen": True}
    )
    assert antwort.status_code == 200, antwort.text
    assert any(
        a[0] == "PUT" and server.koepfe[i].get("if-match") == '"e2"'
        for i, a in enumerate(server.anfragen)
    ), "Meine Fassung schrieb nicht auf der frischen Karte."
    _, karte = server.karten[f"{PFAD}k1.vcf"]
    assert "FN:Vera Rechner" in karte
    assert "X-NEU:vom Telefon" in karte, "Die fremde Zeile der frischen Karte ging verloren."
    assert db.query(Kontakt).one().name == "Vera Rechner"


def test_die_andere_fassung_laesst_sich_uebernehmen(klient, db, welt):
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()
    server.karten[f"{PFAD}k1.vcf"] = ("e2", _karte(name="Vera Telefon"))

    antwort = klient.post(f"/api/kontakte/{kontakt['id']}/konflikt")
    assert antwort.status_code == 200 and antwort.json()["name"] == "Vera Telefon"
    zeile = db.query(Kontakt).one()
    assert zeile.name == "Vera Telefon" and zeile.etag == "e2"
    assert {a[0] for a in server.anfragen} <= LESEND, "Übernehmen darf nichts schreiben."


def test_drueben_geloescht_ist_ein_eigener_fall(klient, welt):
    person, server = welt
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()
    server.karten.clear()

    assert klient.get(f"/api/kontakte/{kontakt['id']}/konflikt").json() == {
        "vorhanden": False, "fremd": None,
    }
    antwort = klient.post(f"/api/kontakte/{kontakt['id']}/konflikt")
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "kontakt_drueben_geloescht"

    # „Meine Fassung" legt die Karte wieder an — als neue, nicht mit einem
    # If-Match auf etwas, das es nicht mehr gibt.
    antwort = klient.patch(
        f"/api/kontakte/{kontakt['id']}", json={"name": "Vera Zurueck", "erzwingen": True}
    )
    assert antwort.status_code == 200, antwort.text
    i = next(i for i, a in enumerate(server.anfragen) if a[0] == "PUT")
    assert server.koepfe[i].get("if-none-match") == "*"
    assert unquote(server.anfragen[i][1]) == f"{PFAD}k1.vcf"
    assert "FN:Vera Zurueck" in server.karten[f"{PFAD}k1.vcf"][1]


def test_ein_neuer_kontakt_im_verbundenen_buch_entsteht_zuerst_beim_anbieter(klient, db, welt):
    person, server = welt
    buch = _verbinden(klient)

    antwort = klient.post(
        "/api/kontakte",
        json={"adresse": "jonas@example.org", "name": "Jonas Keller", "telefon": "0170 1",
              "adressbuch_id": buch["id"]},
    )
    assert antwort.status_code == 201, antwort.text

    i = next(i for i, a in enumerate(server.anfragen) if a[0] == "PUT")
    assert server.koepfe[i].get("if-none-match") == "*"
    pfad = unquote(server.anfragen[i][1])
    assert pfad.startswith(PFAD) and pfad.endswith(".vcf")
    etag, karte = server.karten[pfad]
    assert "FN:Jonas Keller" in karte and "N:Keller;Jonas;;;" in karte
    zeile = db.query(Kontakt).filter_by(adresse="jonas@example.org").one()
    assert zeile.adressbuch_id == buch["id"] and zeile.uid and zeile.roh == karte
    assert carddav.ortsschluessel(zeile.href) == pfad and zeile.etag == etag
    # Und beim nächsten Abgleich ist er weder doppelt noch weg.
    klient.post("/api/adressbuecher/abgleichen")
    assert db.query(Kontakt).count() == 2


def test_ein_abgelehnter_neuer_kontakt_hinterlaesst_keine_zeile(klient, db, welt):
    person, server = welt
    buch = _verbinden(klient)
    server.nur_lesen = True

    antwort = klient.post("/api/kontakte", json={"name": "Jonas", "adressbuch_id": buch["id"]})
    assert antwort.status_code == 502
    assert db.query(Kontakt).count() == 1


def test_verschieben_ins_buch_haengt_sich_an_die_vorhandene_karte(klient, db, welt):
    """⚠️ Erst suchen, dann anlegen. Der lokale Eintrag „Oma" mit Veras Adresse
    hielt die Karte draussen (belegt). Ins Buch verschoben, erkennt ihn der
    Abgleich an der Adresse: Die Karte gewinnt, drüben entsteht kein Doppel."""
    person, server = welt
    lokal = klient.post("/api/kontakte", json={"adresse": "vera@example.org", "name": "Oma"}).json()
    buch = _verbinden(klient)
    assert db.query(Kontakt).count() == 1

    antwort = klient.post(
        f"/api/kontakte/{lokal['id']}/verschieben", json={"adressbuch_id": buch["id"]}
    )
    assert antwort.status_code == 200, antwort.text
    zeile = db.query(Kontakt).one()
    assert zeile.id == lokal["id"] and zeile.adressbuch_id == buch["id"]
    assert zeile.name == "Vera Beispiel" and zeile.href.endswith("k1.vcf")
    assert zeile.schmutzig is False
    assert not any(a[0] == "PUT" for a in server.anfragen), "Es wurde eine zweite Karte angelegt."
    assert len(server.karten) == 1


def test_verschieben_ins_buch_legt_sonst_eine_karte_an(klient, db, welt):
    person, server = welt
    lokal = klient.post(
        "/api/kontakte", json={"adresse": "jonas@example.org", "name": "Jonas Keller"}
    ).json()
    buch = _verbinden(klient)

    antwort = klient.post(
        f"/api/kontakte/{lokal['id']}/verschieben", json={"adressbuch_id": buch["id"]}
    )
    assert antwort.status_code == 200, antwort.text
    zeile = db.get(Kontakt, lokal["id"])
    assert zeile.adressbuch_id == buch["id"] and zeile.href and zeile.schmutzig is False
    assert any(a[0] == "PUT" for a in server.anfragen)
    assert len(server.karten) == 2
    assert any("FN:Jonas Keller" in k for _, k in server.karten.values())


def test_verschieben_aus_dem_buch_loescht_drueben(klient, db, welt):
    """Ein Kontakt, der iCloud verlässt, lebt dort nicht weiter — sonst käme er
    beim nächsten Abgleich als neue Zeile zurück, und der Umzug wäre eine Kopie.
    Die Rohkarte kommt mit: Foto und Geburtstag gehören dem Menschen."""
    person, server = welt
    _verbinden(klient)
    lokal = next(b["id"] for b in klient.get("/api/adressbuecher").json() if b["ist_lokal"])
    (kontakt,) = klient.get("/api/kontakte").json()

    antwort = klient.post(f"/api/kontakte/{kontakt['id']}/verschieben", json={"adressbuch_id": lokal})
    assert antwort.status_code == 200, antwort.text
    assert server.karten == {}
    zeile = db.query(Kontakt).one()
    assert zeile.adressbuch_id == lokal and zeile.href == "" and zeile.schmutzig is False
    assert "BDAY:1980-01-01" in zeile.roh
    klient.post("/api/adressbuecher/abgleichen")
    assert db.query(Kontakt).count() == 1


def test_ein_verbundener_kontakt_nennt_alle_nummern(klient, welt):
    """Das Modell kennt eine Nummer, die Karte viele; die Zeile trägt sie alle,
    ein lokaler Kontakt nur seine Felder."""
    person, server = welt
    server.karten[f"{PFAD}k1.vcf"] = (
        "e1",
        _karte(
            extra="TEL;type=HOME;type=pref:0241 111\r\n"
            "item1.TEL;type=CELL:+49 170 222\r\nitem1.X-ABLabel:_$!<Mobile>!$_\r\n",
        ),
    )
    _verbinden(klient)
    klient.post("/api/kontakte", json={"adresse": "jonas@example.org", "name": "Jonas", "telefon": "1"})

    zeilen = {z["name"]: z for z in klient.get("/api/kontakte").json()}
    verbunden, lokal = zeilen["Vera Beispiel"], zeilen["Jonas"]
    assert verbunden["telefon"] == "+49 170 222"
    assert [(n["nummer"], n["art"], n["bevorzugt"]) for n in verbunden["nummern"]] == [
        ("0241 111", "home", False),
        ("+49 170 222", "cell", True),
    ]
    assert (verbunden["vorname"], verbunden["nachname"]) == ("Vera", "Beispiel")
    assert lokal["nummern"] == [{"nummer": "1", "art": "", "beschriftung": "", "bevorzugt": True}]
    assert lokal["telefon"] == "1" and lokal["weiteres"] == []


def test_ein_lokaler_kontakt_bleibt_bearbeitbar(klient, welt):
    _verbinden(klient)
    neu = klient.post("/api/kontakte", json={"adresse": "jonas@example.org", "name": "Jonas"}).json()
    assert neu["adressbuch_id"] != _verbunden_id(klient)
    assert klient.patch(f"/api/kontakte/{neu['id']}", json={"name": "Jonas K."}).status_code == 200
    assert klient.delete(f"/api/kontakte/{neu['id']}").status_code == 204


def test_der_import_fasst_verbundene_kontakte_nicht_an(klient, db, welt):
    """Was hier ergänzt würde, überschriebe der nächste Abgleich, ohne dass es
    jemand sähe."""
    person, _ = welt
    _verbinden(klient)
    karte = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Vera\r\nEMAIL:vera@example.org\r\nNOTE:lokal\r\nEND:VCARD\r\n"

    assert kontaktdienst.aus_vcard(db, person, karte) == {"neu": 0, "ergaenzt": 0}
    assert db.query(Kontakt).one().notiz == "Kennt den Weg"


# --- Zustimmung und Takt -------------------------------------------------- #


def test_die_zustimmung_zaehlt_ihre_buecher_und_nimmt_sie_mit(klient, db, welt):
    """⚠️ Ohne Zustimmung meldete das Buch bei jedem Takt „Zustimmung fehlt",
    und niemand brächte das mit dem Trennen in Verbindung."""
    person, _ = welt
    zugang = OauthZugang(
        benutzer_id=person.id, art="google", adresse="wer@example.org",
        bereich="https://mail.google.com/ https://www.googleapis.com/auth/carddav",
    )
    db.add(zugang)
    db.flush()
    buch = Adressbuch(
        benutzer_id=person.id, name="Google", art="carddav", herkunft="Google",
        url="https://www.googleapis.com/carddav/v1/principals/wer%40example.org/lists/default/",
        oauth_zugang_id=zugang.id,
    )
    db.add(buch)
    db.flush()
    drin = Kontakt(benutzer_id=person.id, name="Drin", adresse="drin@example.org", adressbuch_id=buch.id)
    db.add(drin)
    gruppe = Kontaktgruppe(benutzer_id=person.id, name="Verein")
    db.add(gruppe)
    db.flush()
    db.add(KontaktgruppeMitglied(benutzer_id=person.id, gruppe_id=gruppe.id, kontakt_id=drin.id))
    db.commit()

    (zeile,) = klient.get("/api/mailoauth/zugaenge").json()
    assert zeile["adressbuecher"] == 1
    assert zeile["kann_adressbuch"] is True

    mailoauth.entfernen(db, person, zugang.id)

    assert db.get(Adressbuch, buch.id) is None
    assert db.query(Kontakt).count() == 0
    assert db.query(KontaktgruppeMitglied).count() == 0


def test_eine_alte_zustimmung_reicht_nicht_bis_zu_den_kontakten(klient, db, welt):
    """Eine Google-Zustimmung von vor der Beta hat den CardDAV-Bereich nicht.
    Das Fenster sperrt sie und sagt es, statt Google 403 sagen zu lassen."""
    person, _ = welt
    db.add(OauthZugang(
        benutzer_id=person.id, art="google", adresse="alt@example.org",
        bereich="https://mail.google.com/ https://www.googleapis.com/auth/calendar",
    ))
    db.commit()
    (zeile,) = klient.get("/api/mailoauth/zugaenge").json()
    assert zeile["kann_adressbuch"] is False


def test_google_bittet_jetzt_auch_um_die_kontakte():
    assert "https://www.googleapis.com/auth/carddav" in mailoauth.ARTEN["google"].bereiche


def test_der_takt_nimmt_die_buecher_mit(db, welt, monkeypatch):
    """⚠️ Die Bücher hängen am Kalender-Takt. Ein Buch, das niemand abgleicht,
    zeigt beim nächsten Öffnen den Stand von der Verbindung."""
    person, _ = welt
    gerufen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        kalenderabgleich, "alle_abgleichen",
        lambda db_, p: gerufen.append(("kalender", p.id)) or {},
    )
    monkeypatch.setattr(
        adressbuchabgleich, "alle_abgleichen",
        lambda db_, p, erzwingen=False: gerufen.append(("buecher", p.id)) or {},
    )

    takt.kalender_runde(db)

    assert ("kalender", person.id) in gerufen
    assert ("buecher", person.id) in gerufen


def test_die_bucherliste_zaehlt_je_buch(klient, db, welt):
    person, _ = welt
    kontaktdienst.anlegen(db, person, "", "Werkstatt", telefon="1")
    _verbinden(klient)
    liste = klient.get("/api/adressbuecher").json()
    assert [(b["ist_lokal"], b["kontakte"]) for b in liste] == [(True, 1), (False, 1)]
    assert db.scalar(select(Kontakt.adresse).where(Kontakt.name == "Werkstatt")) == ""


def test_eine_zweite_karte_kommt_beim_abgleich_dazu(klient, welt):
    person, server = welt
    buch = _verbinden(klient)
    server.karten[f"{PFAD}k2.vcf"] = ("e2", _karte("k2", "Jonas Keller", "jonas@example.org"))
    server.ctag = "ct-2"

    bericht = klient.post("/api/adressbuecher/abgleichen").json()

    assert bericht["neu"] == 1
    assert [b["kontakte"] for b in klient.get("/api/adressbuecher").json() if b["id"] == buch["id"]] == [2]
