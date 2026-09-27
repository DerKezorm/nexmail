"""Das Bild vor einer Zeile: Kontaktfoto, sonst gepruefte Markenlogos (BIMI).

Gewuenscht in der Diskussion #4, so streng wie Apple Mail. ⚠️ **Die Tests
fassen kein Netz an.** DNS und Zertifikatsabruf werden ersetzt und gezaehlt.

Zwei Sorten Zertifikate:

* **Das echte von Revolut** (``daten/vmc-revolut.pem``), bis 24.08.2027
  gueltig. Geprueft wird mit festem Datum, sonst waere der Test eine
  Zeitbombe mit bekanntem Zuendtag.
* **Selbst gebaute Ketten** fuer jede Absage: fremde Wurzel, falscher Zweck,
  falsche Domain, abgelaufen, Skript im Logo. Dafuer wird eine Test-Wurzel
  neben die echten gelegt.
"""

from __future__ import annotations

import base64
import gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from app.models import Absenderlogo, Benutzer, Kontakt, utcnow
from app.services import absenderbild, bildvermittler
from conftest import einrichten, zweiten_benutzer_anlegen

REVOLUT = (Path(__file__).parent / "daten" / "vmc-revolut.pem").read_bytes()
HEUTE = datetime(2026, 10, 1, tzinfo=timezone.utc)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" baseProfile="tiny-ps" version="1.2" viewBox="0 0 10 10">'
    b"<title>Bank</title><circle cx=\"5\" cy=\"5\" r=\"5\" fill=\"#123456\"/></svg>"
)


# --- Selbst gebaute Ketten --------------------------------------------------- #


def _der(kennung: int, inhalt: bytes) -> bytes:
    laenge = len(inhalt)
    if laenge < 0x80:
        return bytes([kennung, laenge]) + inhalt
    roh = laenge.to_bytes((laenge.bit_length() + 7) // 8, "big")
    return bytes([kennung, 0x80 | len(roh)]) + roh + inhalt


def _logotype(svg: bytes) -> x509.UnrecognizedExtension:
    """Wie DigiCert es macht: gzip, base64, als ``data:``-Adresse im DER."""
    adresse = b"data:image/svg+xml;base64," + base64.b64encode(gzip.compress(svg))
    return x509.UnrecognizedExtension(
        x509.ObjectIdentifier(absenderbild.LOGOTYPE), _der(0x30, _der(0xA2, _der(0x16, adresse)))
    )


def _name(text: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])


def _zertifikat(betreff, schluessel, aussteller, aussteller_schluessel, *, ca, zwecke=None,
                namen=None, logo=None, von=HEUTE - timedelta(days=30), bis=HEUTE + timedelta(days=300)):
    bau = (
        x509.CertificateBuilder()
        .subject_name(_name(betreff))
        .issuer_name(_name(aussteller))
        .public_key(schluessel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(von)
        .not_valid_after(bis)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if zwecke:
        bau = bau.add_extension(x509.ExtendedKeyUsage([x509.ObjectIdentifier(z) for z in zwecke]), critical=False)
    if namen:
        bau = bau.add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in namen]), critical=False)
    if logo is not None:
        bau = bau.add_extension(_logotype(logo), critical=False)
    return bau.sign(aussteller_schluessel, hashes.SHA256())


@pytest.fixture
def test_wurzel(monkeypatch):
    """Eine Test-Wurzel, fuer die Dauer des Tests neben den echten."""
    schluessel = ec.generate_private_key(ec.SECP256R1())
    wurzel = _zertifikat("Test Mark Root", schluessel, "Test Mark Root", schluessel, ca=True,
                         bis=HEUTE + timedelta(days=3000))
    monkeypatch.setattr(absenderbild, "WURZELN", [*absenderbild.WURZELN, wurzel])
    return wurzel, schluessel


def _kette(wurzel, wurzel_schluessel, *, zwecke=(absenderbild.ZWECK_BIMI,), namen=("bank.example",),
           logo=SVG, bis=HEUTE + timedelta(days=300), zwischen_ca=True) -> bytes:
    zs = ec.generate_private_key(ec.SECP256R1())
    zwischen = _zertifikat("Test Mark CA1", zs, "Test Mark Root", wurzel_schluessel, ca=zwischen_ca,
                           zwecke=[absenderbild.ZWECK_BIMI])
    bs = ec.generate_private_key(ec.SECP256R1())
    blatt = _zertifikat("Bank", bs, "Test Mark CA1", zs, ca=False, zwecke=zwecke, namen=namen,
                        logo=logo, bis=bis)
    return b"".join(z.public_bytes(Encoding.PEM) for z in (blatt, zwischen, wurzel))


# --- Das Zertifikat ------------------------------------------------------------- #


def test_das_echte_zertifikat_von_revolut_traegt_sein_logo():
    svg = absenderbild.zertifikat_pruefen(REVOLUT, "revolut.com", jetzt=HEUTE)
    assert b'baseProfile="tiny-ps"' in svg
    # Auch eine Unterdomain, ueber die Organisationsdomain im Zertifikat.
    assert absenderbild.zertifikat_pruefen(REVOLUT, "news.revolut.com", jetzt=HEUTE) == svg


def test_das_echte_zertifikat_gilt_nicht_fuer_eine_andere_domain():
    with pytest.raises(absenderbild.NichtVerifiziert, match="name the domain"):
        absenderbild.zertifikat_pruefen(REVOLUT, "bank.example", jetzt=HEUTE)


def test_das_echte_zertifikat_nach_seinem_ablauf():
    with pytest.raises(absenderbild.NichtVerifiziert, match="validity"):
        absenderbild.zertifikat_pruefen(REVOLUT, "revolut.com", jetzt=datetime(2027, 9, 1, tzinfo=timezone.utc))


def test_eine_selbst_gebaute_kette_mit_passender_wurzel(test_wurzel):
    assert absenderbild.zertifikat_pruefen(_kette(*test_wurzel), "bank.example", jetzt=HEUTE) == SVG


def test_eine_wurzel_in_der_datei_zaehlt_nicht():
    """⚠️ Wer seine eigene Wurzel mitschickt, bekommt kein Logo: Geglaubt wird
    allein den festen Wurzeln, egal was die Datei enthaelt."""
    schluessel = ec.generate_private_key(ec.SECP256R1())
    fremde = _zertifikat("Test Mark Root", schluessel, "Test Mark Root", schluessel, ca=True)
    with pytest.raises(absenderbild.NichtVerifiziert, match="does not reach"):
        absenderbild.zertifikat_pruefen(_kette(fremde, schluessel), "bank.example", jetzt=HEUTE)


def test_ohne_markenzweck_kein_logo(test_wurzel):
    """Ein gewoehnliches Zertifikat derselben Firma ist kein Markenzertifikat."""
    pem = _kette(*test_wurzel, zwecke=("1.3.6.1.5.5.7.3.1",))
    with pytest.raises(absenderbild.NichtVerifiziert, match="BIMI"):
        absenderbild.zertifikat_pruefen(pem, "bank.example", jetzt=HEUTE)


def test_ein_zwischenglied_ohne_ausstellerrecht(test_wurzel):
    pem = _kette(*test_wurzel, zwischen_ca=False)
    with pytest.raises(absenderbild.NichtVerifiziert, match="does not reach"):
        absenderbild.zertifikat_pruefen(pem, "bank.example", jetzt=HEUTE)


def test_ein_abgelaufenes_blatt(test_wurzel):
    pem = _kette(*test_wurzel, bis=HEUTE - timedelta(days=1))
    with pytest.raises(absenderbild.NichtVerifiziert, match="validity"):
        absenderbild.zertifikat_pruefen(pem, "bank.example", jetzt=HEUTE)


def test_ein_logo_mit_skript_wird_nicht_ausgeliefert(test_wurzel):
    """⚠️ Auch ein echtes Zertifikat macht ein Skript nicht harmlos: Es laege
    unter nexmails eigener Adresse."""
    boese = SVG.replace(b"</svg>", b"<script>alert(1)</script></svg>")
    with pytest.raises(absenderbild.NichtVerifiziert, match="not allowed"):
        absenderbild.zertifikat_pruefen(_kette(*test_wurzel, logo=boese), "bank.example", jetzt=HEUTE)


@pytest.mark.parametrize(
    "svg",
    [
        SVG.replace(b"<circle", b'<circle onload="x()"'),
        SVG.replace(b"<circle", b'<image href="https://tracker.example/p.png"/><circle'),
        SVG.replace(b'fill="#123456"', b'fill="url(https://tracker.example/x)"'),
        SVG.replace(b'baseProfile="tiny-ps"', b'baseProfile="full"'),
        b"<!DOCTYPE svg [<!ENTITY a 'b'>]>" + SVG,
        SVG + b" " * absenderbild.MAX_SVG,
    ],
    ids=["ereignis", "bild_von_aussen", "url_von_aussen", "anderes_profil", "dtd", "zu_gross"],
)
def test_das_svg_profil_ist_streng(svg):
    with pytest.raises(absenderbild.NichtVerifiziert):
        absenderbild.svg_pruefen(svg)


def test_ein_verweis_innerhalb_des_logos_ist_erlaubt():
    absenderbild.svg_pruefen(SVG.replace(b'fill="#123456"', b'fill="url(#verlauf)"'))


# --- Der Eintrag im DNS ------------------------------------------------------------ #


def test_der_eintrag_braucht_ein_zertifikat():
    assert absenderbild.eintrag_deuten("v=BIMI1; l=https://x.example/l.svg; a=https://x.example/a.pem") == "https://x.example/a.pem"
    assert absenderbild.eintrag_deuten("v=BIMI1; l=https://x.example/l.svg;") is None
    assert absenderbild.eintrag_deuten("v=BIMI1; l=; a=;") is None
    assert absenderbild.eintrag_deuten("v=BIMI1; a=http://x.example/a.pem") is None
    assert absenderbild.eintrag_deuten("v=spf1 -all") is None


class Netz:
    """Ersetzt DNS und Abruf und zaehlt, was nexmail wissen wollte."""

    def __init__(self):
        self.eintraege: dict[str, list[str]] = {}
        self.dateien: dict[str, bytes] = {}
        self.fragen: list[str] = []

    def txt(self, name):
        self.fragen.append(name)
        return self.eintraege.get(name, [])

    def datei_holen(self, url, max_bytes, zeitgrenze=None):  # noqa: ARG002
        self.fragen.append(url)
        if url not in self.dateien:
            raise bildvermittler.Abgelehnt("bild_nicht_erreichbar")
        return self.dateien[url]


@pytest.fixture
def netz(monkeypatch):
    n = Netz()
    monkeypatch.setattr(absenderbild, "_txt", n.txt)
    monkeypatch.setattr(bildvermittler, "datei_holen", n.datei_holen)
    return n


def _mit_revolut(netz, monkeypatch, regel="v=DMARC1; p=reject; rua=mailto:x@example.org"):
    netz.eintraege["_dmarc.revolut.com"] = [regel]
    netz.eintraege["default._bimi.revolut.com"] = ["v=BIMI1; l=https://vmc.example/r.svg; a=https://vmc.example/r.pem"]
    netz.dateien["https://vmc.example/r.pem"] = REVOLUT
    echt = absenderbild.zertifikat_pruefen
    monkeypatch.setattr(absenderbild, "zertifikat_pruefen", lambda pem, d, jetzt=None: echt(pem, d, jetzt=HEUTE))


def _mit_bank(netz, monkeypatch, test_wurzel):
    """Wie ``_mit_revolut``, aber mit selbst gebauter Kette fuer ``bank.test``.

    Fuer die Tests, die den Weg vom Absender bis zum Bild pruefen und dafuer eine
    Adresse brauchen. Eine echte Firmenadresse lehnt der Waechter vor dem Push ab.
    """
    netz.eintraege["_dmarc.bank.test"] = ["v=DMARC1; p=reject"]
    netz.eintraege["default._bimi.bank.test"] = ["v=BIMI1; l=https://vmc.example/b.svg; a=https://vmc.example/b.pem"]
    netz.dateien["https://vmc.example/b.pem"] = _kette(*test_wurzel, namen=("bank.test",))
    echt = absenderbild.zertifikat_pruefen
    monkeypatch.setattr(absenderbild, "zertifikat_pruefen", lambda pem, d, jetzt=None: echt(pem, d, jetzt=HEUTE))


def test_eine_unterdomain_findet_den_eintrag_der_organisation(db, netz, monkeypatch):
    _mit_revolut(netz, monkeypatch)
    assert absenderbild.logo(db, "news.revolut.com") is not None
    bimi = [f for f in netz.fragen if f.startswith("default._bimi.")]
    assert bimi == ["default._bimi.news.revolut.com", "default._bimi.revolut.com"]
    # ⚠️ Die ``l=``-Adresse wird nie geholt: Das Logo kommt aus dem Zertifikat.
    assert "https://vmc.example/r.svg" not in netz.fragen


@pytest.mark.parametrize(
    "regel",
    ["v=DMARC1; p=none", "v=DMARC1; p=reject; pct=50", "v=spf1 -all"],
    ids=["keine_durchsetzung", "nur_teilweise", "kein_dmarc"],
)
def test_ohne_durchgesetztes_dmarc_kein_logo_und_kein_zertifikat(db, netz, monkeypatch, regel):
    """⚠️ BIMI verlangt, dass die Domain Faelschungen abweist. Sonst hilfe
    ihr Logo der Faelschung. Das Zertifikat wird dann gar nicht erst geholt."""
    _mit_revolut(netz, monkeypatch, regel=regel)
    assert absenderbild.logo(db, "revolut.com") is None
    assert "https://vmc.example/r.pem" not in netz.fragen


def test_eine_unterdomain_folgt_sp(db, netz, monkeypatch):
    """Fuer Unterdomains gilt ``sp=`` der Organisation, wenn es dasteht."""
    _mit_revolut(netz, monkeypatch, regel="v=DMARC1; p=reject; sp=none")
    assert absenderbild.logo(db, "news.revolut.com") is None
    assert absenderbild.dmarc_durchgesetzt("revolut.com") is True


def test_einmal_je_domain_auch_wenn_nichts_da_ist(db, netz):
    assert absenderbild.logo(db, "bank.example") is None
    vorher = len(netz.fragen)
    assert absenderbild.logo(db, "bank.example") is None
    assert len(netz.fragen) == vorher, "Die Domain wurde ein zweites Mal gefragt."


def test_nach_einer_woche_wird_neu_geprueft(db, netz, monkeypatch):
    _mit_revolut(netz, monkeypatch)
    absenderbild.logo(db, "revolut.com")
    vorher = len(netz.fragen)
    absenderbild.logo(db, "revolut.com", jetzt=utcnow() + absenderbild.FRISCH - timedelta(hours=1))
    assert len(netz.fragen) == vorher
    absenderbild.logo(db, "revolut.com", jetzt=utcnow() + absenderbild.FRISCH + timedelta(hours=1))
    assert len(netz.fragen) > vorher


# --- Was vor der Zeile steht ----------------------------------------------------------- #


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    p = db.query(Benutzer).one()
    p.absenderlogos_laden = True
    db.commit()
    return p


def _karte(adresse: str, zweitadresse: str = "") -> str:
    zeilen = ["BEGIN:VCARD", "VERSION:3.0", "FN:Vera", f"EMAIL:{adresse}"]
    if zweitadresse:
        zeilen.append(f"EMAIL:{zweitadresse}")
    zeilen.append("PHOTO;ENCODING=b;TYPE=PNG:" + base64.b64encode(PNG).decode())
    return "\r\n".join(zeilen + ["END:VCARD", ""])


def test_ohne_bestandene_pruefung_kein_logo_und_keine_frage(db, netz, person, monkeypatch, test_wurzel):
    """⚠️ Der Kern der Sache: Eine Mail, die die Absenderpruefung nicht
    bestanden hat, bekommt das Logo nie, auch wenn die Domain eins hat."""
    _mit_bank(netz, monkeypatch, test_wurzel)
    assert absenderbild.bild(db, person, "info@bank.test", mit_logo=False) is None
    assert netz.fragen == []


def test_mit_bestandener_pruefung_das_logo(db, netz, person, monkeypatch, test_wurzel):
    _mit_bank(netz, monkeypatch, test_wurzel)
    daten, art = absenderbild.bild(db, person, "info@bank.test", mit_logo=True)
    assert art == "image/svg+xml" and b"tiny-ps" in daten


def test_ohne_schalter_geht_nichts_hinaus(db, netz, person, monkeypatch, test_wurzel):
    _mit_bank(netz, monkeypatch, test_wurzel)
    person.absenderlogos_laden = False
    db.commit()
    assert absenderbild.bild(db, person, "info@bank.test", mit_logo=True) is None
    assert netz.fragen == []


def test_das_kontaktfoto_gewinnt_und_braucht_kein_netz(db, netz, person):
    db.add(Kontakt(benutzer_id=person.id, adresse="vera@example.com", roh=_karte("vera@example.com")))
    db.commit()
    assert absenderbild.bild(db, person, "Vera@Example.com", mit_logo=True) == (PNG, "image/png")
    assert netz.fragen == []


def test_das_kontaktfoto_gilt_auch_fuer_die_zweitadresse(db, netz, person):
    db.add(Kontakt(benutzer_id=person.id, adresse="vera@example.com",
                   adressen='[{"adresse": "vera@example.org"}]',
                   roh=_karte("vera@example.com", zweitadresse="vera@example.org")))
    db.commit()
    assert absenderbild.bild(db, person, "vera@example.org", mit_logo=False) == (PNG, "image/png")


def test_eine_aehnliche_adresse_ist_nicht_derselbe_kontakt(db, netz, person):
    """⚠️ Der LIKE ist nur Vorauswahl: ``a@example.com`` steckt auch in ``xa@example.com``."""
    db.add(Kontakt(benutzer_id=person.id, adresse="xvera@example.com",
                   adressen='[{"adresse": "xvera@example.com"}]', roh=_karte("xvera@example.com")))
    db.commit()
    assert absenderbild.bild(db, person, "vera@example.com", mit_logo=False) is None


def test_fremde_kontakte_zeigen_kein_foto(db, netz, person):
    zweiter, _ = zweiten_benutzer_anlegen(db)
    db.add(Kontakt(benutzer_id=zweiter.id, adresse="vera@example.com", roh=_karte("vera@example.com")))
    db.commit()
    assert absenderbild.bild(db, person, "vera@example.com", mit_logo=False) is None


# --- Die Adresse ------------------------------------------------------------------------ #


def test_die_adresse_liefert_das_logo_mit_schutz(klient, db, netz, person, monkeypatch, test_wurzel):
    _mit_bank(netz, monkeypatch, test_wurzel)

    antwort = klient.get("/api/absenderbild", params={"adresse": "info@bank.test", "logo": "true"})

    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("image/svg+xml")
    assert "nosniff" in antwort.headers["x-content-type-options"]
    # Zusaetzlich zur Regel der Middleware, nicht statt ihrer.
    regeln = antwort.headers.get_list("content-security-policy")
    assert any("sandbox" in r for r in regeln), regeln
    assert "private" in antwort.headers["cache-control"]


def test_ohne_logo_wunsch_ist_es_404(klient, db, netz, person, monkeypatch, test_wurzel):
    _mit_bank(netz, monkeypatch, test_wurzel)
    antwort = klient.get("/api/absenderbild", params={"adresse": "info@bank.test"})
    assert antwort.status_code == 404
    assert netz.fragen == []


def test_ohne_anmeldung_kein_bild(klient, db, netz):
    einrichten(klient)
    klient.post("/api/auth/abmelden")
    antwort = klient.get("/api/absenderbild", params={"adresse": "info@bank.test", "logo": "true"})
    assert antwort.status_code == 401
    assert netz.fragen == []


def test_der_schalter_laesst_den_anderen_stehen(klient, db, person):
    """⚠️ Nicht mitgeschickt heisst unveraendert."""
    klient.put("/api/einstellungen/bilder", json={"immer_laden": True})
    antwort = klient.put("/api/einstellungen/bilder", json={"logos": False})
    assert antwort.json()["immer_laden"] is True
    assert antwort.json()["logos"] is False
    assert klient.get("/api/auth/ich").json()["absenderlogos"] is False
    klient.put("/api/einstellungen/bilder", json={"logos": True})
    assert klient.get("/api/auth/ich").json()["absenderlogos"] is True


def test_die_schlanke_sicherung_laesst_den_zwischenspeicher_weg(db, tmp_path):
    import shutil
    import sqlite3

    from app.db import engine
    from app.services import sicherung

    db.add(Absenderlogo(domain="revolut.com", inhalt=SVG, typ="image/svg+xml"))
    db.commit()
    kopie = tmp_path / "kopie.db"
    shutil.copy(engine.url.database, kopie)

    sicherung._schlank_machen(kopie)

    with sqlite3.connect(kopie) as verbindung:
        assert verbindung.execute("select count(*) from absenderlogo").fetchone()[0] == 0
