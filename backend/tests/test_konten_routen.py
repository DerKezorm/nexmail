"""Die Routen des Kontenmoduls in nexmail: was nur nexmail hat (Feldnamen, Kennungen, Postausgang, Bremse,
Notfallbefehl). Die Ablaeufe selbst pruefen die Vertragstests in ``tests/nexkonten`` gegen nexmails Store."""

from __future__ import annotations

import re

import pytest

from app.db import SessionLocal, einstellung_schreiben
from app.models import Benutzer, FruehererName
from app.services import anmeldebremse, systempost
from app.vendor.nexkonten import brake
from conftest import EINRICHTUNGSCODE, einrichten

PASSWORT = "sehr-geheim-123"


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def adresse_der_app():
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")


@pytest.fixture
def post(adresse_der_app, monkeypatch):
    """Ein Postausgang ist eingetragen; was hinausginge, landet in der Liste."""
    gesendet: list[dict] = []

    def senden(db, an, betreff, text, html=""):  # noqa: ARG001
        gesendet.append({"an": an, "betreff": betreff, "text": text})

    with SessionLocal() as db:
        einstellung_schreiben(db, systempost.S_SERVER, "smtp.example.com")
        einstellung_schreiben(db, systempost.S_ABSENDER, "nexmail@example.com")
    monkeypatch.setattr(systempost, "senden", senden)
    return gesendet


def _link(mail: dict, pfad: str) -> str:
    treffer = re.search(rf"https://mail\.example\.com/{pfad}/(\S+)", mail["text"])
    assert treffer, mail["text"]
    return treffer.group(1)


def _mitglied(klient, zweiter_klient, name: str = "anna", adresse: str = "anna@example.com", post=None) -> str:
    """Ein zweites Konto ueber eine Einladung (ohne Postausgang: der Link kommt in der Antwort)."""
    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", "https://mail.example.com")
    link = klient.post(
        "/api/benutzer/einladungen", json={"adresse": adresse, "anzeigename": name.capitalize()}
    ).json()["link"]
    schluessel = link.rsplit("/", 1)[1] if link else _link(post[-1], "einladung")
    antwort = zweiter_klient.post(
        f"/api/einladung/{schluessel}",
        json={"anzeigename": name.capitalize(), "benutzername": name, "kontaktadresse": adresse, "passwort": "annas-passwort-1"},
    )
    assert antwort.status_code == 201, antwort.text
    with SessionLocal() as db:
        return db.query(Benutzer).filter(Benutzer.benutzername == name).one().id


# --- Anmelden ----------------------------------------------------------------------------------------------------


def test_anmelden_mit_der_adresse_und_eine_meldung_fuer_alles(klient, zweiter_klient):
    einrichten(klient)
    _mitglied(klient, zweiter_klient)
    zweiter_klient.cookies.clear()
    gut = zweiter_klient.post("/api/auth/anmelden", json={"benutzername": "ANNA@example.com", "passwort": "annas-passwort-1"})
    assert gut.status_code == 200 and zweiter_klient.get("/api/auth/ich").json()["benutzername"] == "anna"
    for eingabe, passwort in (("anna", "falsch-falsch-1"), ("niemand", "annas-passwort-1"), ("x@example.com", "annas-passwort-1")):
        anmeldebremse.zuruecksetzen()
        falsch = klient.post("/api/auth/anmelden", json={"benutzername": eingabe, "passwort": passwort})
        assert falsch.status_code == 401 and falsch.json()["detail"] == "anmeldung_falsch"
    # Eine lange Adresse ist kein 422, sondern dieselbe Ablehnung.
    lang = klient.post("/api/auth/anmelden", json={"benutzername": "a" * 200 + "@example.com", "passwort": "x"})
    assert lang.status_code == 401


def test_die_bremse_zaehlt_name_und_adresse_zusammen(klient, zweiter_klient):
    """Entwurf, Entscheidung „Anmeldebremse“: ein Konto, ein Zaehler, egal was getippt wird."""
    einrichten(klient)
    _mitglied(klient, zweiter_klient)
    frei = brake.FREE["account"]
    codes = []
    for i in range(frei + 2):
        eingabe = "anna" if i % 2 else "anna@example.com"
        codes.append(klient.post("/api/auth/anmelden", json={"benutzername": eingabe, "passwort": "falsch-1234"}).status_code)
    # Die Bremse des Kontenmoduls (seit konten 0.3.3 auch an nexmails Anmeldung): beide Eingaben, ein Topf.
    assert codes == [401] * (frei + 1) + [429]


# --- Passwort vergessen und der Link vom Betreiber ---------------------------------------------------------------


def test_ohne_postausgang_bietet_die_seite_keinen_link_per_mail(klient, adresse_der_app, monkeypatch):
    einrichten(klient)
    gesendet = []
    monkeypatch.setattr(systempost, "senden", lambda *a, **k: gesendet.append(a))
    assert klient.get("/api/auth/kennwort-vergessen").json() == {"per_mail": False}
    assert klient.post("/api/auth/kennwort-vergessen", json={"benutzername": "betreiber"}).status_code == 202
    assert gesendet == []


def test_der_betreiber_erstellt_einen_link_zum_weitergeben(klient, zweiter_klient):
    einrichten(klient)
    anna = _mitglied(klient, zweiter_klient)
    ohne = klient.post(f"/api/benutzer/{anna}/passwort-link", json={"passwort": "falsch-falsch-1"})
    assert ohne.status_code == 401 and ohne.json()["detail"] == "kennwort_falsch"
    selbst = klient.get("/api/auth/ich").json()["id"]
    assert klient.post(f"/api/benutzer/{selbst}/passwort-link", json={"passwort": PASSWORT}).json()["detail"] == "use_account_page"
    falsche_tage = klient.post(f"/api/benutzer/{anna}/passwort-link", json={"passwort": PASSWORT, "tage": 2})
    assert falsche_tage.json()["detail"] == "invalid_days"

    antwort = klient.post(f"/api/benutzer/{anna}/passwort-link", json={"passwort": PASSWORT, "tage": 7})
    assert antwort.status_code == 200, antwort.text
    link = antwort.json()["link"]
    assert link.startswith("https://mail.example.com/kennwort/") and antwort.json()["an"] == ""
    schluessel = link.rsplit("/", 1)[1]
    assert zweiter_klient.get(f"/api/auth/kennwort-neu/{schluessel}").json()["benutzername"] == "anna"
    assert zweiter_klient.post("/api/auth/kennwort-neu", json={"schluessel": schluessel, "passwort": "ganz-neues-pw-1"}).status_code == 204
    anmeldebremse.zuruecksetzen()
    assert zweiter_klient.post("/api/auth/anmelden", json={"benutzername": "anna", "passwort": "ganz-neues-pw-1"}).status_code == 200
    assert zweiter_klient.get("/api/auth/ich").json()["neues_passwort"] == "operator"


def test_mit_postausgang_geht_der_link_des_betreibers_per_mail(klient, zweiter_klient, post):
    einrichten(klient)
    anna = _mitglied(klient, zweiter_klient, post=post)
    post.clear()
    antwort = klient.post(f"/api/benutzer/{anna}/passwort-link", json={"passwort": PASSWORT})
    assert antwort.json()["an"] == "anna@example.com" and antwort.json()["link"] == ""
    assert [m["an"] for m in post] == ["anna@example.com"] and "/kennwort/" in post[0]["text"]


def test_der_notfallbefehl_macht_einen_link_ohne_anmeldung(klient, adresse_der_app, capsys):
    from app import notfall

    einrichten(klient)
    assert notfall.main(["reset-link", "BETREIBER"]) == 0
    ausgabe = capsys.readouterr().out
    schluessel = re.search(r"https://mail\.example\.com/kennwort/(\S+)", ausgabe).group(1)
    assert klient.get(f"/api/auth/kennwort-neu/{schluessel}").json()["benutzername"] == "betreiber"
    assert notfall.main(["reset-link", "niemand"]) == 1


# --- Profil -------------------------------------------------------------------------------------------------------


def test_den_eigenen_benutzernamen_aendern(klient, zweiter_klient):
    einrichten(klient)
    _mitglied(klient, zweiter_klient)
    falsch = zweiter_klient.put("/api/auth/ich/benutzername", json={"benutzername": "anna.b", "passwort": "nein-nein-nein"})
    assert falsch.status_code == 401
    belegt = zweiter_klient.put("/api/auth/ich/benutzername", json={"benutzername": "Betreiber", "passwort": "annas-passwort-1"})
    assert belegt.status_code == 409 and belegt.json()["detail"] == "benutzername_vergeben"
    regel = zweiter_klient.put("/api/auth/ich/benutzername", json={"benutzername": "-x", "passwort": "annas-passwort-1"})
    assert regel.status_code == 400 and regel.json()["detail"] == "benutzername_ungueltig"

    gut = zweiter_klient.put("/api/auth/ich/benutzername", json={"benutzername": "Anna.B", "passwort": "annas-passwort-1"})
    assert gut.status_code == 200 and gut.json()["benutzername"] == "anna.b"
    # Die Sitzung bleibt; anmelden geht nur noch mit dem neuen Namen, der alte bleibt reserviert.
    assert zweiter_klient.get("/api/auth/ich").status_code == 200
    anmeldebremse.zuruecksetzen()
    assert klient.post("/api/auth/anmelden", json={"benutzername": "anna", "passwort": "annas-passwort-1"}).status_code == 401
    anmeldebremse.zuruecksetzen()
    assert klient.post("/api/auth/anmelden", json={"benutzername": "anna.b", "passwort": "annas-passwort-1"}).status_code == 200
    with SessionLocal() as db:
        assert db.query(FruehererName).filter(FruehererName.benutzername == "anna").count() == 1


def test_der_anzeigename_zieht_nur_mit_wenn_er_der_alte_benutzername_ist(klient):
    einrichten(klient, anzeigename="betreiber")
    antwort = klient.put("/api/auth/ich/benutzername", json={"benutzername": "chef", "passwort": PASSWORT})
    assert (antwort.json()["benutzername"], antwort.json()["anzeigename"]) == ("chef", "chef")
    klient.put("/api/auth/ich/profil", json={"anzeigename": "Die Chefin"})
    antwort = klient.put("/api/auth/ich/benutzername", json={"benutzername": "chefin", "passwort": PASSWORT})
    assert antwort.json()["anzeigename"] == "Die Chefin"


def test_eine_neue_adresse_wartet_auf_ihren_link(klient, post):
    einrichten(klient)
    with SessionLocal() as db:
        db.query(Benutzer).one().kontaktadresse = "alt@example.com"
        db.commit()
    antwort = klient.put("/api/auth/ich/kontaktadresse", json={"adresse": "neu@example.com", "passwort": PASSWORT})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["kontaktadresse_wartet"] == "neu@example.com"
    assert [m["an"] for m in post] == ["neu@example.com"]
    erster = _link(post[0], "adresse")
    assert klient.post("/api/auth/ich/kontaktadresse/nochmal").status_code == 200
    zweiter = _link(post[1], "adresse")
    assert klient.get(f"/api/auth/adresse/{erster}").status_code == 404
    assert klient.get(f"/api/auth/adresse/{zweiter}").json() == {"adresse": "neu@example.com"}
    assert klient.post(f"/api/auth/adresse/{zweiter}").status_code == 200
    ich = klient.get("/api/auth/ich").json()
    assert (ich["kontaktadresse"], ich["kontaktadresse_wartet"]) == ("neu@example.com", "")
    # Die alte Adresse hoert davon, gekuerzt.
    assert post[-1]["an"] == "alt@example.com" and "n***@example.com" in post[-1]["text"]


def test_eine_wartende_adresse_laesst_sich_zuruecknehmen(klient, post):
    einrichten(klient)
    klient.put("/api/auth/ich/kontaktadresse", json={"adresse": "neu@example.com", "passwort": PASSWORT})
    assert klient.delete("/api/auth/ich/kontaktadresse/wartend").json()["kontaktadresse_wartet"] == ""


def test_die_sprache_reist_mit_dem_konto(klient):
    einrichten(klient)
    assert klient.put("/api/auth/ich/sprache", json={"sprache": "en"}).json()["sprache"] == "en"
    assert klient.put("/api/auth/ich/sprache", json={"sprache": "kein code!"}).json()["sprache"] == ""


def test_der_betreiber_aendert_namen_und_nimmt_die_adresse_weg(klient, zweiter_klient):
    einrichten(klient)
    anna = _mitglied(klient, zweiter_klient)
    neu = klient.put(f"/api/benutzer/{anna}/benutzername", json={"benutzername": "anna2", "passwort": PASSWORT})
    assert neu.status_code == 200 and neu.json()["benutzername"] == "anna2"
    anzeige = klient.put(f"/api/benutzer/{anna}/anzeigename", json={"anzeigename": "Anna Zwei", "passwort": PASSWORT})
    assert anzeige.json()["anzeigename"] == "Anna Zwei"
    weg = klient.post(f"/api/benutzer/{anna}/kontaktadresse-entfernen", json={"passwort": PASSWORT})
    assert weg.json()["kontaktadresse"] == ""
    fremd = zweiter_klient.put(f"/api/benutzer/{anna}/benutzername", json={"benutzername": "x2", "passwort": "annas-passwort-1"})
    assert fremd.status_code == 403


def test_doppelte_adressen_tragen_einen_hinweis(klient, zweiter_klient):
    einrichten(klient)
    anna = _mitglied(klient, zweiter_klient)
    with SessionLocal() as db:
        db.get(Benutzer, anna).kontaktadresse = "Gemeinsam@example.com"
        betreiber = db.query(Benutzer).filter(Benutzer.ist_betreiber.is_(True)).one()
        betreiber.kontaktadresse = "gemeinsam@example.com"
        db.commit()
    zeilen = {z["benutzername"]: z for z in klient.get("/api/benutzer").json()["benutzer"]}
    assert zeilen["anna"]["adresse_doppelt"] and zeilen["betreiber"]["adresse_doppelt"]


# --- Einrichtungscode ---------------------------------------------------------------------------------------------


def test_der_einrichtungscode_schuetzt_auch_das_einspielen_vor_der_einrichtung(klient):
    for pfad in ("/api/sicherung/pruefen-vor-einrichtung", "/api/sicherung/einspielen-vor-einrichtung"):
        ohne = klient.post(pfad, data={"passwort": "x"}, files={"datei": ("s.zip", b"PK", "application/zip")})
        assert ohne.status_code == 403 and ohne.json()["detail"] == "setup_code_wrong", pfad
    mit = klient.post(
        "/api/sicherung/pruefen-vor-einrichtung",
        data={"passwort": "x", "einrichtungscode": EINRICHTUNGSCODE},
        files={"datei": ("s.zip", b"PK", "application/zip")},
    )
    assert mit.status_code != 403  # am Code vorbei; ob das Archiv taugt, ist eine andere Frage
    assert klient.get("/api/setup/status").json()["code_noetig"] is True
    einrichten(klient)
    assert klient.get("/api/setup/status").json()["code_noetig"] is False


# --- konten 0.3.3: die Adresse eines Anbieters wird einem Konto mit Passwort nur angeboten -------------------------


def test_angebotene_adresse_uebernehmen_und_ablehnen(klient):
    from app.services.konten_store import KontenStore
    from app.vendor import nexkonten

    einrichten(klient)
    with SessionLocal() as db:
        person = db.query(Benutzer).one()
        assert (
            nexkonten.profiles.provider_email(KontenStore(db), person.id, "betrieb@id.example.com")
            == nexkonten.profiles.PROVIDER_EMAIL_OFFERED
        )
        db.commit()
    ich = klient.get("/api/auth/ich").json()
    assert ich["angebotene_adresse"] == "betrieb@id.example.com" and ich["kontaktadresse"] != "betrieb@id.example.com"

    falsch = klient.post("/api/auth/ich/angebotene-adresse", json={"passwort": "falsch-falsch-1"})
    assert falsch.status_code == 401
    assert klient.get("/api/auth/ich").json()["angebotene_adresse"] == "betrieb@id.example.com"

    weg = klient.delete("/api/auth/ich/angebotene-adresse")
    assert weg.status_code == 200 and weg.json()["angebotene_adresse"] == ""

    with SessionLocal() as db:
        nexkonten.profiles.provider_email(KontenStore(db), db.query(Benutzer).one().id, "betrieb@id.example.com")
        db.commit()
    genommen = klient.post("/api/auth/ich/angebotene-adresse", json={"passwort": "sehr-geheim-123"})
    assert genommen.status_code == 200, genommen.text
    daten = genommen.json()
    assert daten["angebotene_adresse"] == ""
    assert "betrieb@id.example.com" in (daten["kontaktadresse"], daten["kontaktadresse_wartet"])
