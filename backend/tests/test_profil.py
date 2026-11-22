"""Profil in den Einstellungen: Name, Mailadresse und Profilbild (wie nexnotes)."""

from __future__ import annotations

import io

from PIL import Image

from app.models import Benutzer
from app.services import profilbild
from conftest import anmelden, einrichten, zweiten_benutzer_anlegen


def _bild(art: str = "PNG", breite: int = 400, hoehe: int = 200, exif: bytes | None = None) -> bytes:
    raus = io.BytesIO()
    bild = Image.new("RGB", (breite, hoehe), (200, 40, 40))
    if exif is not None:
        bild.save(raus, art, exif=exif)
    else:
        bild.save(raus, art)
    return raus.getvalue()


# --- Name und Adresse ---------------------------------------------------- #


def test_profil_setzt_name_und_adresse(klient, db):
    einrichten(klient)
    antwort = klient.put(
        "/api/auth/ich/profil", json={"anzeigename": "  Anna Lena  ", "kontaktadresse": "m@example.com"}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["anzeigename"] == "Anna Lena"
    assert antwort.json()["kontaktadresse"] == "m@example.com"
    person = db.query(Benutzer).one()
    assert (person.anzeigename, person.kontaktadresse) == ("Anna Lena", "m@example.com")


def test_leerer_name_wird_zum_benutzernamen(klient):
    einrichten(klient, "betreiber")
    antwort = klient.put("/api/auth/ich/profil", json={"anzeigename": "   ", "kontaktadresse": ""})
    assert antwort.status_code == 200
    assert antwort.json()["anzeigename"] == "betreiber"


def test_falsche_adresse_aendert_auch_den_namen_nicht(klient, db):
    einrichten(klient)
    vorher = db.query(Benutzer).one().anzeigename
    antwort = klient.put(
        "/api/auth/ich/profil", json={"anzeigename": "Neu", "kontaktadresse": "keine-adresse"}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "adresse_ungueltig"
    db.expire_all()
    assert db.query(Benutzer).one().anzeigename == vorher


def test_profil_nur_angemeldet(klient):
    assert klient.put("/api/auth/ich/profil", json={"anzeigename": "x"}).status_code == 401


# --- Profilbild ---------------------------------------------------------- #


def test_bild_wird_quadratisches_webp_ohne_metadaten():
    exif = Image.Exif()
    exif[0x010F] = "Kamerahersteller"  # Make
    roh = _bild("JPEG", 400, 200, exif=exif.tobytes())
    raus = profilbild.zeichnen(roh)
    with Image.open(io.BytesIO(raus)) as bild:
        assert bild.format == "WEBP"
        assert bild.size == (profilbild.GROESSE, profilbild.GROESSE)
        assert not bild.getexif()
    assert b"Kamerahersteller" not in raus


def test_svg_und_unsinn_werden_abgewiesen():
    for daten in (b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\x00" * 100, b""):
        try:
            profilbild.zeichnen(daten)
        except profilbild.ProfilbildFehler as fehler:
            assert fehler.kennung == "profilbild_kein_bild"
        else:
            raise AssertionError(f"angenommen: {daten[:20]!r}")


def test_kaputtes_bild_mit_richtigem_kopf_wird_abgewiesen():
    try:
        profilbild.zeichnen(b"\x89PNG\r\n\x1a\n" + b"kaputt" * 20)
    except profilbild.ProfilbildFehler as fehler:
        assert fehler.kennung == "profilbild_kein_bild"
    else:
        raise AssertionError("kaputtes PNG angenommen")


def test_zu_grosse_datei_wird_nicht_geoeffnet(monkeypatch):
    monkeypatch.setattr(profilbild, "MAX_BYTES", 100)
    try:
        profilbild.zeichnen(_bild())
    except profilbild.ProfilbildFehler as fehler:
        assert fehler.kennung == "profilbild_zu_gross"
    else:
        raise AssertionError("zu große Datei angenommen")


def test_bild_setzen_holen_entfernen(klient):
    ich = einrichten(klient)
    assert klient.get("/api/auth/ich").json()["profilbild"] is None

    gesetzt = klient.put("/api/auth/ich/profilbild", content=_bild())
    assert gesetzt.status_code == 200, gesetzt.text
    stand = gesetzt.json()["profilbild"]
    assert stand

    benutzer_id = klient.get("/api/auth/ich").json()["id"]
    bild = klient.get(f"/api/auth/profilbild/{benutzer_id}?v={stand}")
    assert bild.status_code == 200
    assert bild.headers["content-type"] == "image/webp"
    assert "private" in bild.headers["cache-control"]

    weg = klient.delete("/api/auth/ich/profilbild")
    assert weg.json()["profilbild"] is None
    assert klient.get(f"/api/auth/profilbild/{benutzer_id}").status_code == 404
    assert ich is not None


def test_kein_bild_gibt_422_mit_kennung(klient):
    einrichten(klient)
    antwort = klient.put("/api/auth/ich/profilbild", content=b"<svg/>")
    assert antwort.status_code == 422
    assert antwort.json()["detail"] == "profilbild_kein_bild"


def test_fremdes_bild_sieht_nur_der_betreiber(klient, zweiter_klient, db):
    einrichten(klient)
    klient.put("/api/auth/ich/profilbild", content=_bild())
    betreiber_id = klient.get("/api/auth/ich").json()["id"]

    person, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, "zweiter", "auch-geheim-456", geheimnis)
    zweiter_klient.put("/api/auth/ich/profilbild", content=_bild())

    # Der zweite sieht das Bild des Betreibers nicht, wie ein fehlendes.
    assert zweiter_klient.get(f"/api/auth/profilbild/{betreiber_id}").status_code == 404
    # Der Betreiber sieht das des zweiten (seine Benutzerliste).
    assert klient.get(f"/api/auth/profilbild/{person.id}").status_code == 200


def test_bild_nur_angemeldet(klient):
    einrichten(klient)
    benutzer_id = klient.get("/api/auth/ich").json()["id"]
    klient.put("/api/auth/ich/profilbild", content=_bild())
    klient.post("/api/auth/abmelden")
    assert klient.get(f"/api/auth/profilbild/{benutzer_id}").status_code == 401
    assert klient.put("/api/auth/ich/profilbild", content=_bild()).status_code == 401
