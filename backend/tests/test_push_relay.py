"""Mitteilungen für die iPhone-App, über den Push-Relay.

⚠️ **Nichts geht an den echten Relay.** ``Relay`` steht an der Stelle von
``httpx.Client`` und merkt sich, was hinausginge.

⚠️ **Der Prüfwert ist der Vertrag mit der Swift-Seite.** ``oeffnen`` steht
deshalb hier noch einmal ausgeschrieben und benutzt nichts aus ``push.py``: Rechnet
die App anders als der Server, sagt das nur ein Test, der nicht bei sich selbst
abschreibt.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.exc import OperationalError

from app.config import Settings, get_settings
from app.main import app
from app.models import Benutzer, Erinnerungszustellung, Konto, Nachricht, Ordner, Sitzung, utcnow
from app.services import anmeldebremse, push, termine
from conftest import einrichten, zweiten_benutzer_anlegen
from test_app_flaeche import abholen, koppeln

PFAD = "/api/app/1"

#: Aus dem Auftrag, wörtlich. Der iOS-Agent prüft dieselben Werte in Swift.
PRIVAT = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="
OEFFENTLICH = "B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw="
KLARTEXT = '{"titel":"Mia Beispiel","text":"Treffen am Samstag","id":4711}'
ENC = (
    "WGmv9FBUlzLLqu1eXfmzCm2jHLDldCutWtShp2jxpntkZWZnaGlqa2xtbm+KJ7WrJ2lMLF4NJgqKzA5wlc6S"
    "y8jmr90bY3TSa8XX60TCYREhDCK4Rp5kXErAhSb0EH+612qy7V2lTa72c7Fl0sMFsTc8tQFAe4h7s5g="
)

TICKET = "1.ticket-das-nie-im-protokoll-steht"


def oeffnen(enc: str, privat: str = PRIVAT) -> str:
    """Was die App auf dem Gerät rechnet, ausgeschrieben."""
    roh = base64.b64decode(enc, validate=True)
    wegwerf, nonce, geheim = roh[:32], roh[32:44], roh[44:]
    schluessel = X25519PrivateKey.from_private_bytes(base64.b64decode(privat))
    geteilt = schluessel.exchange(X25519PublicKey.from_public_bytes(wegwerf))
    aead = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"nexmail-push-v1")
    return ChaCha20Poly1305(aead.derive(geteilt)).decrypt(nonce, geheim, None).decode("utf-8")


class Relay:
    """Steht für ``httpx.Client``. Antworten der Reihe nach, danach 200."""

    def __init__(self, *antworten, web_status: int = 201) -> None:
        self.antworten = list(antworten)
        self.web_status = web_status
        self.sendungen: list[tuple[str, dict]] = []
        self.web: list[str] = []
        self.zeitlimit: float | None = None

    def __call__(self, *_a, timeout=None, **_kw):
        self.zeitlimit = timeout
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def post(self, url, json=None, **_kw):
        anfrage = httpx.Request("POST", url)
        if json is None:
            self.web.append(url)
            return httpx.Response(self.web_status, request=anfrage)
        self.sendungen.append((url, json))
        antwort = self.antworten.pop(0) if self.antworten else 200
        if isinstance(antwort, Exception):
            raise antwort
        return httpx.Response(antwort, request=anfrage)

    def inhalte(self, privat: str = PRIVAT) -> list[dict]:
        return [json.loads(oeffnen(r["enc"], privat)) for _, r in self.sendungen]


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


@pytest.fixture
def person(klient, db):
    einrichten(klient)
    p = db.query(Benutzer).one()
    p.push_mail = True
    p.push_mail_buendeln = False
    p.push_mail_nur_ungelesen = True
    p.push_mail_alle_ordner = False
    p.push_ruhezeit = False
    db.commit()
    return p


@pytest.fixture
def relay(monkeypatch):
    bote = Relay()
    monkeypatch.setattr(push.httpx, "Client", bote)
    return bote


@pytest.fixture
def antworten(monkeypatch):
    """Ein Relay mit vorgegebenen Antworten."""

    def bauen(*folge, **kw) -> Relay:
        bote = Relay(*folge, **kw)
        monkeypatch.setattr(push.httpx, "Client", bote)
        return bote

    return bauen


@pytest.fixture
def ohne_relay(monkeypatch):
    monkeypatch.setattr(get_settings(), "push_relay", "")


def geraet(db, person, ticket=TICKET, schluessel=OEFFENTLICH, art="geraet", tage=30) -> Sitzung:
    zeile = Sitzung(
        benutzer_id=person.id,
        token_hash=base64.b16encode(ticket.encode()).decode()[:64] + art,
        bestaetigt=True,
        geraet="iPhone",
        art=art,
        push_ticket=ticket,
        push_schluessel=schluessel,
        gueltig_bis=utcnow() + timedelta(days=tage),
    )
    db.add(zeile)
    db.commit()
    return zeile


def postfach(db, person, adresse="anna@example.org", rolle="posteingang") -> tuple[Konto, Ordner]:
    konto = (
        db.query(Konto).filter_by(benutzer_id=person.id, adresse=adresse).one_or_none()
        or Konto(
            benutzer_id=person.id,
            anzeigename="Privat",
            adresse=adresse,
            imap_server="imap.example.org",
            imap_port=993,
            imap_sicherheit="ssl",
            imap_benutzer="anna",
            smtp_server="smtp.example.org",
            smtp_port=587,
            smtp_sicherheit="starttls",
            smtp_benutzer="anna",
        )
    )
    db.add(konto)
    db.flush()
    ordner = Ordner(konto_id=konto.id, pfad=rolle.upper(), name=rolle, rolle=rolle)
    db.add(ordner)
    db.commit()
    return konto, ordner


def mail(
    db, person, konto, ordner, uid=1, gelesen=False, betreff="Treffen am Samstag", anreisser=""
) -> Nachricht:
    n = Nachricht(
        benutzer_id=person.id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=uid,
        betreff=betreff,
        anreisser=anreisser,
        von_name="Mia Beispiel",
        von_adresse="mia@example.org",
        datum=utcnow(),
        gelesen=gelesen,
    )
    db.add(n)
    db.commit()
    return n


def melden(db, person, meldung=None) -> bool:
    return push.an_benutzer(
        db,
        person,
        meldung or push.Meldung(titel="Mia", text="Hallo", ziel="/", marke="mail-1", kennung=1),
    )


# --- Die Verschlüsselung --------------------------------------------------- #


def test_der_pruefwert_laesst_sich_oeffnen():
    assert oeffnen(ENC) == KLARTEXT


def test_die_beiden_schluessel_des_pruefwerts_gehoeren_zusammen():
    privat = X25519PrivateKey.from_private_bytes(base64.b64decode(PRIVAT))
    roh = privat.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert base64.b64encode(roh).decode() == OEFFENTLICH


def test_der_eigene_code_ergibt_denselben_klartext_wie_der_pruefwert():
    meldung = push.Meldung(
        titel="Mia Beispiel", text="Treffen am Samstag", ziel="/", marke="m", kennung=4711
    )
    klar = push._klartext(meldung)
    assert klar.decode() == KLARTEXT
    assert oeffnen(push._versiegeln(klar, OEFFENTLICH)) == KLARTEXT


def test_umlaute_stehen_als_utf8_da_nicht_maskiert():
    klar = push._klartext(push.Meldung(titel="Jörg", text="Grüße", ziel="/", marke="m"))
    assert klar.decode("utf-8") == '{"titel":"Jörg","text":"Grüße","id":null}'


def test_wegwerfschluessel_und_nonce_sind_jedes_mal_neu():
    eins = base64.b64decode(push._versiegeln(b"gleich", OEFFENTLICH))
    zwei = base64.b64decode(push._versiegeln(b"gleich", OEFFENTLICH))
    assert eins[:32] != zwei[:32]
    assert eins[32:44] != zwei[32:44]
    assert eins[44:] != zwei[44:]


def test_das_format_stimmt_auf_das_byte():
    roh = base64.b64decode(push._versiegeln(b"12345", OEFFENTLICH), validate=True)
    assert len(roh) == 32 + 12 + 5 + 16


def test_titel_und_text_werden_vor_dem_verschluesseln_gekuerzt():
    klar = push._klartext(push.Meldung(titel="t" * 150, text="x" * 250, ziel="/", marke="m"))
    daten = json.loads(klar)
    assert len(daten["titel"]) == 100
    assert len(daten["text"]) == 200


@pytest.mark.parametrize("zeichen", ["😀", "\x01", '"'])
def test_auch_der_schlimmste_betreff_bleibt_unter_der_grenze(zeichen):
    """⚠️ Steuerzeichen werden im JSON sechs Byte lang, ein Emoji vier."""
    klar = push._klartext(push.Meldung(titel=zeichen * 500, text=zeichen * 500, ziel="/", marke="m"))
    assert len(push._versiegeln(klar, OEFFENTLICH)) <= 3000


def test_die_grenze_ist_genau_das_was_der_relay_nimmt():
    assert len(push._versiegeln(b"x" * push.APP_KLARTEXT_GRENZE, OEFFENTLICH)) <= 3000
    assert len(push._versiegeln(b"x" * (push.APP_KLARTEXT_GRENZE + 1), OEFFENTLICH)) > 3000


def test_die_vorschau_wird_gekuerzt_und_endet_nicht_mit_leerraum():
    def vorschau(wert):
        klar = push._klartext(push.Meldung(titel="t", text="x", ziel="/", marke="m", vorschau=wert))
        return json.loads(klar)["vorschau"]

    assert vorschau("v" * 300) == "v" * 120
    assert vorschau("v" * 119 + " danach") == "v" * 119


@pytest.mark.parametrize("wert", ["", "   ", "\n\t "])
def test_ohne_text_fehlt_das_feld(wert):
    klar = push._klartext(push.Meldung(titel="t", text="x", ziel="/", marke="m", vorschau=wert))
    assert "vorschau" not in json.loads(klar)


def test_die_grenze_zaehlt_byte_nicht_zeichen():
    """⚠️ Ein Steuerzeichen ist ein Zeichen und im JSON sechs Byte."""
    schwer = {"titel": "\x01" * 100, "text": "\x01" * 200}

    def klartext(vorschau):
        return push._klartext(push.Meldung(**schwer, ziel="/", marke="m", vorschau=vorschau))

    frei = push.APP_KLARTEXT_GRENZE - len(push._kompakt({**schwer, "id": None, "vorschau": ""}))
    passt = "\x01" * (frei // 6) + "v" * (frei % 6)

    assert len(passt) <= push.APP_VORSCHAU_GRENZE
    assert len(klartext(passt)) == push.APP_KLARTEXT_GRENZE
    assert "vorschau" not in json.loads(klartext(passt + "v"))


def test_was_nicht_passt_verliert_nur_die_vorschau(db, person, relay):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    n = mail(db, person, konto, eingang, betreff="\x01" * 200, anreisser="\x01" * 120)
    n.von_name = "\x01" * 100
    db.commit()

    push.neue_mail_melden(db, konto, [n.id], set())

    assert relay.inhalte() == [{"titel": "\x01" * 100, "text": "\x01" * 200, "id": n.id}]
    assert len(relay.sendungen[0][1]["enc"]) <= 3000


# --- Der Schlüssel --------------------------------------------------------- #


def test_ein_gueltiger_schluessel_geht_durch():
    assert push.schluessel_gueltig(OEFFENTLICH)


@pytest.mark.parametrize(
    "falsch",
    [
        "",
        "kein base64!",
        base64.b64encode(b"x" * 31).decode(),
        base64.b64encode(b"x" * 33).decode(),
        # Ein Punkt kleiner Ordnung: Das gemeinsame Geheimnis wäre null.
        base64.b64encode(b"\x00" * 32).decode(),
        "äöü",
        # ⚠️ Mit Fremdzeichen decodiert ein nachsichtiges base64 trotzdem 32 Byte,
        # und jede Meldung scheiterte später beim strengen Lesen.
        OEFFENTLICH[:10] + "!" + OEFFENTLICH[10:],
        OEFFENTLICH[:10] + "\n" + OEFFENTLICH[10:],
    ],
)
def test_ein_falscher_schluessel_faellt_durch(falsch):
    assert not push.schluessel_gueltig(falsch)


# --- Der Aufruf ------------------------------------------------------------ #


def test_der_rumpf_hat_genau_die_felder_des_relays(db, person, relay):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    mail(db, person, konto, eingang)

    assert melden(db, person, push.Meldung(titel="Mia", text="Hallo", ziel="/", marke="mail-7", kennung=7))

    url, rumpf = relay.sendungen[0]
    assert url == "https://push.nexapps.dev/v1/send"
    assert set(rumpf) == {"ticket", "enc", "collapse", "badge"}
    assert rumpf["ticket"] == TICKET
    assert rumpf["collapse"] == "mail-7"
    assert rumpf["badge"] == 1
    assert relay.zeitlimit == 8.0
    assert relay.inhalte() == [{"titel": "Mia", "text": "Hallo", "id": 7}]


def test_kein_wort_steht_im_klartext_im_rumpf(db, person, relay):
    geraet(db, person)
    melden(db, person, push.Meldung(titel="Mia Beispiel", text="Geheimer Betreff", ziel="/", marke="m"))
    roh = json.dumps(relay.sendungen[0][1])
    assert "Geheimer" not in roh
    assert "Mia" not in roh


def test_die_marke_wird_gekuerzt(db, person, relay):
    geraet(db, person)
    melden(db, person, push.Meldung(titel="a", text="b", ziel="/", marke="m" * 100))
    assert relay.sendungen[0][1]["collapse"] == "m" * 64


def test_die_adresse_kommt_aus_der_einstellung(db, person, relay, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_relay", "https://relay.example.org/")
    geraet(db, person)
    melden(db, person)
    assert relay.sendungen[0][0] == "https://relay.example.org/v1/send"


def test_die_zahl_zaehlt_nur_ungelesenes_im_posteingang_aller_postfaecher(db, person, relay):
    geraet(db, person)
    k1, e1 = postfach(db, person, "eins@example.org")
    k2, e2 = postfach(db, person, "zwei@example.org")
    _, archiv = postfach(db, person, "eins@example.org", rolle="archiv")
    mail(db, person, k1, e1, uid=1)
    mail(db, person, k1, e1, uid=2, gelesen=True)
    mail(db, person, k2, e2, uid=3)
    mail(db, person, k1, archiv, uid=4)

    andere, _ = zweiten_benutzer_anlegen(db)
    k3, e3 = postfach(db, andere, "fremd@example.org")
    mail(db, andere, k3, e3, uid=5)

    melden(db, person)

    assert relay.sendungen[0][1]["badge"] == 2


def test_ohne_zahl_fehlt_das_feld_lieber_als_dass_es_falsch_ist(db, person, relay, monkeypatch):
    geraet(db, person)
    echt = db.scalar

    def klemmt(abfrage, *a, **k):
        if "count" in str(abfrage):
            raise OperationalError("select", {}, Exception("database is locked"))
        return echt(abfrage, *a, **k)

    monkeypatch.setattr(db, "scalar", klemmt)

    assert melden(db, person)
    assert "badge" not in relay.sendungen[0][1]


# --- Die Antworten --------------------------------------------------------- #


def test_410_loescht_ticket_und_schluessel(db, person, antworten):
    zeile = geraet(db, person)
    antworten(410)

    assert melden(db, person) is False

    db.refresh(zeile)
    assert zeile.push_ticket == ""
    assert zeile.push_schluessel == ""


@pytest.mark.parametrize(
    "antwort",
    [429, 502, 500, 404, 400, 403, 301, httpx.ConnectError("weg"), httpx.ReadTimeout("zu spät")],
)
def test_alles_andere_behaelt_das_ticket_und_versucht_es_nicht_noch_einmal(
    db, person, antworten, antwort
):
    zeile = geraet(db, person)
    bote = antworten(antwort)

    assert melden(db, person) is False

    assert len(bote.sendungen) == 1
    db.refresh(zeile)
    assert zeile.push_ticket == TICKET


def test_ein_stummes_geraet_haelt_das_naechste_nicht_auf(db, person, antworten):
    geraet(db, person, "1.eins")
    geraet(db, person, "1.zwei")
    bote = antworten(httpx.ConnectError("weg"))

    assert melden(db, person) is True
    assert len(bote.sendungen) == 2


def test_ein_verbogener_schluessel_trifft_nur_sein_geraet(db, person, relay):
    geraet(db, person, "1.kaputt", schluessel="das ist keiner")
    geraet(db, person, "1.heil")

    assert melden(db, person) is True
    assert [r["ticket"] for _, r in relay.sendungen] == ["1.heil"]


def test_ein_browser_klemmt_das_telefon_nicht(db, person, antworten):
    from test_push import Browser

    Browser().anmelden(db, person)
    geraet(db, person)
    bote = antworten(web_status=500)

    assert melden(db, person) is True
    assert len(bote.web) == 1
    assert len(bote.sendungen) == 1


def test_ein_geraet_ohne_erfolg_nimmt_dem_browser_seinen_nicht(db, person, antworten):
    """⚠️ Sonst gälte eine zugestellte Erinnerung als gescheitert und käme wieder."""
    from test_push import Browser

    Browser().anmelden(db, person)
    geraet(db, person)
    antworten(410)

    assert melden(db, person) is True


# --- Wer bekommt etwas ----------------------------------------------------- #


def test_ohne_relay_geht_nichts_hinaus(db, person, relay, ohne_relay):
    geraet(db, person)
    assert melden(db, person) is False
    assert relay.sendungen == []
    assert push.hat_empfaenger(db, person) is False


def test_ein_geraet_ohne_ticket_bekommt_nichts(db, person, relay):
    geraet(db, person, ticket="")
    assert melden(db, person) is False
    assert relay.sendungen == []


def test_ein_abgelaufenes_geraet_bekommt_nichts(db, person, relay):
    geraet(db, person, tage=-1)
    assert melden(db, person) is False
    assert relay.sendungen == []


def test_eine_browsersitzung_mit_ticket_bekommt_nichts(db, person, relay):
    geraet(db, person, art="browser")
    assert melden(db, person) is False
    assert relay.sendungen == []


def test_die_geraete_anderer_leute_bekommen_nichts(db, person, relay):
    andere, _ = zweiten_benutzer_anlegen(db)
    geraet(db, andere)
    assert melden(db, person) is False
    assert relay.sendungen == []


# --- Neue Post ------------------------------------------------------------- #


def test_ein_geraet_zaehlt_wie_eine_anmeldung(db, person, relay):
    """⚠️ Der frühe Ausstieg ``not person.push_anmeldungen`` sperrte Geräte aus."""
    geraet(db, person)
    konto, eingang = postfach(db, person)
    n = mail(db, person, konto, eingang)

    push.neue_mail_melden(db, konto, [n.id], set())

    assert relay.inhalte() == [{"titel": "Mia Beispiel", "text": "Treffen am Samstag", "id": n.id}]
    assert relay.sendungen[0][1]["collapse"] == f"mail-{n.id}"


def test_die_mail_bringt_ihren_anfang_mit(db, person, relay):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    n = mail(db, person, konto, eingang, anreisser="Passt dir Samstag um zehn?")

    push.neue_mail_melden(db, konto, [n.id], set())

    assert relay.inhalte() == [
        {
            "titel": "Mia Beispiel",
            "text": "Treffen am Samstag",
            "id": n.id,
            "vorschau": "Passt dir Samstag um zehn?",
        }
    ]
    assert "Samstag" not in json.dumps(relay.sendungen[0][1])


def test_der_browser_bekommt_die_vorschau_nicht():
    meldung = push.Meldung(titel="t", text="x", ziel="/", marke="m", vorschau="geheim genug")
    assert "vorschau" not in json.loads(push._rumpf(meldung))


def test_ein_buendel_traegt_keine_kennung(db, person, relay):
    person.push_mail_buendeln = True
    db.commit()
    geraet(db, person)
    konto, eingang = postfach(db, person)
    a = mail(db, person, konto, eingang, uid=1, anreisser="Passt dir Samstag?")
    b = mail(db, person, konto, eingang, uid=2, anreisser="Passt dir Sonntag?")

    push.neue_mail_melden(db, konto, [a.id, b.id], set())

    assert relay.inhalte() == [{"titel": "2 neue Nachrichten", "text": konto.adresse, "id": None}]


def test_die_regeln_gelten_auch_fuers_geraet(db, person, relay, monkeypatch):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    _, archiv = postfach(db, person, rolle="archiv")
    gelesen = mail(db, person, konto, eingang, uid=1, gelesen=True)
    abgelegt = mail(db, person, konto, archiv, uid=2)
    neu = mail(db, person, konto, eingang, uid=3)

    push.neue_mail_melden(db, konto, [gelesen.id, abgelegt.id], set())
    assert relay.sendungen == []

    push.neue_mail_melden(db, konto, [neu.id], {eingang.pfad})
    assert relay.sendungen == []

    person.push_mail = False
    db.commit()
    push.neue_mail_melden(db, konto, [neu.id], set())
    assert relay.sendungen == []

    person.push_mail = True
    db.commit()
    monkeypatch.setattr(push, "ruhezeit_jetzt", lambda *a, **k: True)
    push.neue_mail_melden(db, konto, [neu.id], set())
    assert relay.sendungen == []


def test_ein_fehler_beim_relay_haelt_keine_post_auf(db, person, antworten):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    n = mail(db, person, konto, eingang)
    antworten(httpx.ConnectError("weg"))

    push.neue_mail_melden(db, konto, [n.id], set())


def test_ohne_relay_und_ohne_browser_faellt_der_abgleich_frueh_aus(db, person, relay, ohne_relay):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    n = mail(db, person, konto, eingang)

    push.neue_mail_melden(db, konto, [n.id], set())

    assert relay.sendungen == []


# --- Terminerinnerungen ---------------------------------------------------- #


@pytest.fixture
def kalender(db, person):
    person.push_termine = True
    db.commit()
    return termine.kalender_anlegen(db, person, "Privat")


def _termin_gleich(db, person, kalender, vorlauf=15):
    from test_push import _termin_gleich as bauen

    return bauen(db, person, kalender, vorlauf)


def test_eine_erinnerung_erreicht_das_geraet_ohne_kennung(db, person, kalender, relay):
    geraet(db, person)
    _termin_gleich(db, person, kalender)

    assert push.erinnerungen_runde() == 1

    inhalt = relay.inhalte()[0]
    assert inhalt["id"] is None
    assert inhalt["titel"]
    assert relay.sendungen[0][1]["collapse"].startswith("termin-")


def test_ohne_empfaenger_wird_keine_erinnerung_verbraucht(db, person, kalender, relay, ohne_relay):
    """⚠️ ``faellige`` bucht beim Ermitteln."""
    geraet(db, person)
    _termin_gleich(db, person, kalender)

    assert push.erinnerungen_runde() == 0
    assert db.query(Erinnerungszustellung).count() == 0


def test_eine_misslungene_erinnerung_bleibt_faellig(db, person, kalender, antworten):
    geraet(db, person)
    _termin_gleich(db, person, kalender)
    antworten(502)

    assert push.erinnerungen_runde() == 0
    assert db.query(Erinnerungszustellung).count() == 0


def test_ein_erloschenes_ticket_laesst_die_erinnerung_nicht_kreisen(db, person, kalender, antworten):
    geraet(db, person)
    _termin_gleich(db, person, kalender)
    antworten(410)

    assert push.erinnerungen_runde() == 0
    assert db.query(Erinnerungszustellung).count() == 1


# --- Die Adressen ---------------------------------------------------------- #


@pytest.fixture
def kein_cookie():
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def bearer(klient, kein_cookie, person):
    schluessel = abholen(kein_cookie, koppeln(klient)).json()["key"]
    return {"Authorization": f"Bearer {schluessel}"}


def setzen(c, bearer, ticket=TICKET, schluessel=OEFFENTLICH):
    return c.put(f"{PFAD}/push", headers=bearer, json={"ticket": ticket, "schluessel": schluessel})


def eigenes_geraet(db) -> Sitzung:
    db.expire_all()
    return db.query(Sitzung).filter_by(art="geraet").one()


def test_put_merkt_beides_am_geraet(db, kein_cookie, bearer):
    antwort = setzen(kein_cookie, bearer)

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}
    zeile = eigenes_geraet(db)
    assert zeile.push_ticket == TICKET
    assert zeile.push_schluessel == OEFFENTLICH


def test_put_ist_wiederholbar_und_nimmt_das_neue_ticket(db, kein_cookie, bearer):
    setzen(kein_cookie, bearer)
    assert setzen(kein_cookie, bearer).status_code == 200
    setzen(kein_cookie, bearer, ticket="1.neu")
    assert eigenes_geraet(db).push_ticket == "1.neu"


def test_delete_vergisst_beides_und_das_geraet_bleibt(db, kein_cookie, bearer):
    setzen(kein_cookie, bearer)

    antwort = kein_cookie.delete(f"{PFAD}/push", headers=bearer)

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}
    zeile = eigenes_geraet(db)
    assert (zeile.push_ticket, zeile.push_schluessel) == ("", "")
    assert kein_cookie.get(f"{PFAD}/me", headers=bearer).status_code == 200


@pytest.mark.parametrize("falsch", ["kein base64!", "", base64.b64encode(b"x" * 31).decode(), "A" * 500])
def test_ein_falscher_schluessel_gibt_seine_kennung(db, kein_cookie, bearer, falsch):
    antwort = setzen(kein_cookie, bearer, schluessel=falsch)

    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "kein_gueltiger_schluessel"
    assert eigenes_geraet(db).push_ticket == ""


def test_das_ticket_hat_eine_grenze(kein_cookie, bearer):
    assert setzen(kein_cookie, bearer, ticket="x" * 1024).status_code == 200
    assert setzen(kein_cookie, bearer, ticket="x" * 1025).status_code == 422


def test_ein_cookie_oeffnet_die_adresse_nicht(klient, person):
    antwort = klient.put(f"{PFAD}/push", json={"ticket": TICKET, "schluessel": OEFFENTLICH})
    assert antwort.status_code == 401


def test_ohne_anmeldung_geht_nichts(kein_cookie):
    assert kein_cookie.delete(f"{PFAD}/push").status_code == 401


def test_ein_geraet_aendert_nur_sich_selbst(db, kein_cookie, bearer, person):
    andere, _ = zweiten_benutzer_anlegen(db)
    fremd = geraet(db, andere, "1.fremd")

    setzen(kein_cookie, bearer, ticket="1.fremd")
    kein_cookie.delete(f"{PFAD}/push", headers=bearer)

    db.refresh(fremd)
    assert fremd.push_ticket == "1.fremd"


def test_neu_gekoppelt_kommt_nichts_doppelt(db, klient, kein_cookie, bearer, relay, person):
    """⚠️ Eine Neuinstallation bringt ihr Ticket mit, die alte Sitzung steht noch."""
    setzen(kein_cookie, bearer)
    zweiter = abholen(kein_cookie, koppeln(klient, "Neu")).json()["key"]
    setzen(kein_cookie, {"Authorization": f"Bearer {zweiter}"})

    melden(db, person)

    assert len(relay.sendungen) == 1


def test_die_faehigkeit_haengt_am_relay(kein_cookie, bearer, monkeypatch):
    assert "push" in kein_cookie.get(f"{PFAD}/me", headers=bearer).json()["faehigkeiten"]

    monkeypatch.setattr(get_settings(), "push_relay", "  ")

    assert "push" not in kein_cookie.get(f"{PFAD}/me", headers=bearer).json()["faehigkeiten"]


def test_die_einstellung_laesst_sich_leer_setzen(monkeypatch):
    """⚠️ Leer heißt aus, nicht „die Vorgabe": Betreiber wollen nichts nach außen."""
    monkeypatch.setenv("NEXMAIL_PUSH_RELAY", "")
    assert Settings().push_relay == ""


def test_die_vorgabe_ist_der_relay(monkeypatch):
    monkeypatch.delenv("NEXMAIL_PUSH_RELAY", raising=False)
    assert Settings().push_relay == "https://push.nexapps.dev"


# --- Getrennt ist getrennt ------------------------------------------------- #


def test_ein_getrenntes_geraet_bekommt_nichts(db, kein_cookie, bearer, relay, person):
    setzen(kein_cookie, bearer)
    assert kein_cookie.delete(f"{PFAD}/device", headers=bearer).status_code == 204
    db.expire_all()

    assert melden(db, person) is False
    assert relay.sendungen == []


def test_ueberall_abmelden_nimmt_das_ticket_mit(db, klient, kein_cookie, bearer, relay, person):
    setzen(kein_cookie, bearer)
    assert klient.post("/api/sitzungen/alle-beenden").status_code == 200
    db.expire_all()

    assert melden(db, person) is False
    assert relay.sendungen == []


def test_die_probe_erreicht_auch_ein_geraet_allein(db, klient, person, relay):
    geraet(db, person)
    assert klient.post("/api/push/probe").status_code == 204
    assert len(relay.sendungen) == 1


def test_ohne_jeden_empfaenger_sagt_die_probe_es(klient, person, relay):
    antwort = klient.post("/api/push/probe")
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == "kein_geraet_angemeldet"


# --- Das Ticket bleibt, wo es hingehört ------------------------------------ #


@pytest.mark.parametrize(
    "antwort", [200, 410, 429, 502, httpx.ConnectError("weg"), httpx.ReadTimeout("spät")]
)
def test_das_ticket_steht_in_keinem_protokoll(db, person, antworten, caplog, antwort):
    geraet(db, person)
    antworten(antwort)

    with caplog.at_level(logging.DEBUG):
        melden(db, person)

    assert TICKET not in caplog.text
    assert OEFFENTLICH not in caplog.text


@pytest.mark.parametrize("antwort", [200, 410, 502, httpx.ConnectError("weg")])
def test_die_vorschau_steht_in_keinem_protokoll(db, person, antworten, caplog, antwort):
    geraet(db, person)
    konto, eingang = postfach(db, person)
    n = mail(db, person, konto, eingang, anreisser="Passt dir Samstag um zehn?")
    antworten(antwort)

    with caplog.at_level(logging.DEBUG):
        push.neue_mail_melden(db, konto, [n.id], set())

    assert "Passt dir" not in caplog.text


def test_ein_fehlschlag_steht_genau_einmal_im_protokoll(db, person, antworten, caplog):
    geraet(db, person)
    antworten(502)

    with caplog.at_level(logging.INFO, logger="nexmail.push"):
        melden(db, person)

    zeilen = [r for r in caplog.records if r.name == "nexmail.push"]
    assert len(zeilen) == 1
    assert "502" in zeilen[0].getMessage()


def test_das_ticket_steht_in_keiner_antwort(klient, kein_cookie, bearer):
    setzen(kein_cookie, bearer)
    for antwort in (
        kein_cookie.get(f"{PFAD}/me", headers=bearer),
        klient.get("/api/sitzungen"),
        klient.get("/api/auth/ich"),
    ):
        assert antwort.status_code == 200
        assert TICKET not in antwort.text


def test_die_kennung_ist_uebersetzt():
    for sprache in ("de", "en"):
        pfad = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "frontend/src/i18n"
            / f"{sprache}.json"
        )
        assert "kein_gueltiger_schluessel" in json.loads(pfad.read_text(encoding="utf-8"))["serverfehler"]
