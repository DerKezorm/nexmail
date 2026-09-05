"""Die Adressen der Adressbücher, Beta.

⚠️ **Der teuerste Fehler wäre ein Weg, auf dem nexmail beim Anbieter etwas
löscht.** Der Doppelgänger zählt deshalb jede Anfrage: In keiner Prüfung hier
darf etwas anderes als ``PROPFIND`` und ``REPORT`` vorkommen, und ein Test
hält das über verbinden, abgleichen, ändern und trennen hinweg fest.
"""

from __future__ import annotations

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


def test_verbinden_holt_die_kontakte_sofort(klient, welt):
    buch = _verbinden(klient)
    assert buch["herkunft"] == "iCloud" and buch["art"] == "carddav"
    assert buch["kontakte"] == 1

    kontakte = klient.get("/api/kontakte").json()
    assert len(kontakte) == 1
    assert kontakte[0]["adressbuch_id"] == buch["id"]
    # ⚠️ Beta: verbundene Bücher werden nur gelesen, und die Zeile sagt es.
    assert kontakte[0]["nur_lesen"] is True


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


def test_ein_verbundener_kontakt_ist_nur_lesen(klient, db, welt):
    """⚠️ Geändert würde er beim nächsten Abgleich überschrieben, gelöscht
    käme er wieder. Beides sähe aus wie ein Fehler; der Server sagt es statt
    dessen, und die Oberfläche sperrt das Formular."""
    _verbinden(klient)
    (kontakt,) = klient.get("/api/kontakte").json()

    geaendert = klient.patch(f"/api/kontakte/{kontakt['id']}", json={"name": "Anders"})
    assert geaendert.status_code == 400
    assert geaendert.json()["detail"] == "kontakt_nur_lesen"

    geloescht = klient.delete(f"/api/kontakte/{kontakt['id']}")
    assert geloescht.status_code == 400
    assert geloescht.json()["detail"] == "kontakt_nur_lesen"

    assert db.query(Kontakt).one().name == "Vera Beispiel"


def test_ein_lokaler_kontakt_bleibt_bearbeitbar(klient, welt):
    _verbinden(klient)
    neu = klient.post("/api/kontakte", json={"adresse": "jonas@example.org", "name": "Jonas"}).json()
    assert neu["nur_lesen"] is False
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
