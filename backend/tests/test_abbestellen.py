"""Von einer Liste abmelden.

⚠️ **Hier schickt nexmails Server auf Knopfdruck etwas an eine Adresse, die ein
Fremder in seine Mail geschrieben hat.** Geprüft wird deshalb vor allem, was
NICHT hinausgeht: nichts ins eigene Netz, nichts ohne bestandene Prüfung,
nichts aus dem Junk-Ordner, und nichts ein zweites Mal.

⚠️ **Nichts geht ins echte Netz.** Die Adressen sind IP-Adressen, damit keine
Namensauflösung nötig ist, und der Transport ist ein Doppelgänger.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.models import Nachricht, Ordner, utcnow
from app.services import abbestellen as dienst
from app.services import anmeldebremse
from conftest import anmelden, zweiten_benutzer_anlegen
from test_abgleich import FalscherServer, konto  # noqa: F401 - Fixture

#: Eine öffentliche Adresse ohne Namen.
DRAUSSEN = "https://93.184.216.34/ab?k=1"


@pytest.fixture(autouse=True)
def bremse_frei():
    anmeldebremse.zuruecksetzen()
    yield
    anmeldebremse.zuruecksetzen()


def kopf(*zeilen: str) -> bytes:
    return ("\r\n".join(("From: a@example.org", *zeilen)) + "\r\n").encode()


class Gegenstelle:
    """Ein fremder Server, der mitschreibt."""

    def __init__(self, code=200, weiter=""):
        self.code = code
        self.weiter = weiter
        self.anfragen: list[httpx.Request] = []

    def transport(self):
        def antworten(anfrage: httpx.Request) -> httpx.Response:
            self.anfragen.append(anfrage)
            kopfzeilen = {"location": self.weiter} if self.weiter else {}
            return httpx.Response(self.code, headers=kopfzeilen)

        return httpx.MockTransport(antworten)


# --- Die Kopfzeile lesen --------------------------------------------------- #


def test_ohne_kopfzeile_gibt_es_nichts():
    assert dienst.lesen(kopf("Subject: Hallo")) == ""


def test_die_reihenfolge_des_absenders_bleibt():
    """RFC 2369 legt die Rangfolge in die Hand des Absenders."""
    roh = dienst.lesen(kopf("List-Unsubscribe: <mailto:ab@example.org>, <https://example.org/ab>"))
    assert json.loads(roh) == {
        "ziele": ["mailto:ab@example.org", "https://example.org/ab"],
        "einklick": False,
    }


def test_eine_gefaltete_kopfzeile_wird_gelesen():
    """So schreiben es die grossen Versender: jede Adresse auf eigener Zeile."""
    roh = dienst.lesen(
        kopf(
            "List-Unsubscribe: <https://example.org/ab>,",
            " <mailto:ab@example.org>",
            "List-Unsubscribe-Post: List-Unsubscribe=One-Click",
        )
    )
    daten = json.loads(roh)
    assert daten["ziele"] == ["https://example.org/ab", "mailto:ab@example.org"]
    assert daten["einklick"] is True


@pytest.mark.parametrize(
    "schlecht",
    ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", "ftp://example.org/ab"],
)
def test_nur_drei_schemata_kommen_durch(schlecht):
    """⚠️ **Die Adresse landet in einem Link.** Ein ``javascript:`` hätte dort
    nexmails eigene Herkunft."""
    assert dienst.lesen(kopf(f"List-Unsubscribe: <{schlecht}>")) == ""


def test_eine_ueberlange_adresse_wird_verworfen():
    lang = "https://example.org/" + "a" * dienst.MAX_ADRESSE
    assert dienst.lesen(kopf(f"List-Unsubscribe: <{lang}>")) == ""


def test_einklick_verlangt_den_genauen_wert():
    """⚠️ Der Kopf sagt, dass ein blosses ``POST`` genügt. Ein anderer Wert sagt
    das nicht, und dann geht die Seite im Browser auf."""
    roh = dienst.lesen(
        kopf("List-Unsubscribe: <https://example.org/ab>", "List-Unsubscribe-Post: irgendwas")
    )
    assert json.loads(roh)["einklick"] is False


# --- Welcher Weg gilt ------------------------------------------------------ #


@pytest.fixture
def mail(db, konto):  # noqa: F811
    """Eine geöffnete Mail im Posteingang, die die Prüfung bestanden hat."""
    ordner = db.query(Ordner).filter_by(konto_id=konto.id, rolle="posteingang").one()
    n = Nachricht(
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=1,
        betreff="Newsletter",
        von_adresse="post@example.org",
        datum=utcnow(),
        koerper_geholt=utcnow(),
        koerper_text="Hallo",
        pruefer="mx.example",
        dmarc_bestanden=True,
        abbestellen=json.dumps({"ziele": [DRAUSSEN], "einklick": True}),
    )
    db.add(n)
    db.commit()
    return n


VERTRAUT = "mx.example"


def test_einklick_nach_bestandener_pruefung(mail):
    weg = dienst.weg(mail, {mail.konto_id: VERTRAUT})
    assert (weg.art, weg.ziel, weg.stelle) == ("einklick", DRAUSSEN, "93.184.216.34")


def test_ohne_pruefung_geht_die_seite_auf_statt_eines_posts(mail):
    """⚠️ **Der Kern.** Sonst liesse jede gefälschte Mail nexmails Server auf
    Knopfdruck an eine Adresse ihrer Wahl schreiben."""
    weg = dienst.weg(mail, {})
    assert (weg.art, weg.ziel) == ("seite", DRAUSSEN)


def test_ein_fremder_pruefer_zaehlt_nicht(mail):
    assert dienst.weg(mail, {mail.konto_id: "anderer.example"}).art == "seite"


def test_einklick_braucht_https(mail):
    mail.abbestellen = json.dumps({"ziele": ["http://example.org/ab"], "einklick": True})
    assert dienst.weg(mail, {mail.konto_id: VERTRAUT}).art == "seite"


def test_der_erste_weg_des_absenders_gilt(mail):
    mail.abbestellen = json.dumps(
        {"ziele": ["mailto:ab@example.org?subject=weg", "https://example.org/ab"], "einklick": False}
    )
    weg = dienst.weg(mail, {})
    assert (weg.art, weg.stelle) == ("mail", "ab@example.org")


def test_im_junk_gibt_es_keinen_weg(db, mail):
    """⚠️ Eine Abmeldung bestätigt dem Absender, dass die Adresse gelesen wird."""
    mail.ordner.rolle = "junk"
    db.commit()
    assert dienst.weg(mail, {mail.konto_id: VERTRAUT}) is None


def test_kaputter_inhalt_ist_kein_absturz(mail):
    mail.abbestellen = "{kein json"
    assert dienst.weg(mail, {}) is None


# --- Das POST -------------------------------------------------------------- #


def test_das_post_ist_wie_rfc_8058_es_verlangt():
    gegen = Gegenstelle()
    dienst.einklick_senden(DRAUSSEN, transport=gegen.transport())

    anfrage = gegen.anfragen[0]
    assert anfrage.method == "POST"
    assert anfrage.content == b"List-Unsubscribe=One-Click"
    assert anfrage.headers["content-type"] == "application/x-www-form-urlencoded"
    assert "cookie" not in anfrage.headers
    assert "authorization" not in anfrage.headers


@pytest.mark.parametrize(
    "ziel",
    [
        "https://127.0.0.1/ab",
        "https://172.16.0.10/ab",
        "https://169.254.169.254/latest",
        "https://100.64.0.1/ab",
        "https://[::1]/ab",
    ],
)
def test_ins_eigene_netz_geht_nichts(ziel):
    gegen = Gegenstelle()
    with pytest.raises(dienst.AbbestellFehler) as f:
        dienst.einklick_senden(ziel, transport=gegen.transport())
    assert str(f.value) == "abbestellen_adresse_unerlaubt"
    assert gegen.anfragen == []


def test_ohne_https_geht_nichts():
    gegen = Gegenstelle()
    with pytest.raises(dienst.AbbestellFehler):
        dienst.einklick_senden("http://93.184.216.34/ab", transport=gegen.transport())
    assert gegen.anfragen == []


def test_eine_weiterleitung_ins_eigene_netz_wird_nicht_verfolgt():
    """⚠️ **Die Wache steht vor jedem Sprung.** Sonst stünde sie nur vor dem
    ersten, und den schreibt der Absender harmlos."""
    gegen = Gegenstelle(code=307, weiter="https://172.16.0.10/intern")
    with pytest.raises(dienst.AbbestellFehler) as f:
        dienst.einklick_senden(DRAUSSEN, transport=gegen.transport())
    assert str(f.value) == "abbestellen_adresse_unerlaubt"
    assert len(gegen.anfragen) == 1


def test_307_wird_verfolgt_und_endet():
    """Nur 307 und 308 behalten das ``POST``."""
    aufrufe = []

    def antworten(anfrage):
        aufrufe.append(str(anfrage.url))
        if len(aufrufe) == 1:
            return httpx.Response(307, headers={"location": "https://93.184.216.35/weiter"})
        return httpx.Response(200)

    dienst.einklick_senden(DRAUSSEN, transport=httpx.MockTransport(antworten))
    assert aufrufe == [DRAUSSEN, "https://93.184.216.35/weiter"]


def test_eine_endlose_weiterleitung_endet():
    gegen = Gegenstelle(code=307, weiter=DRAUSSEN)
    with pytest.raises(dienst.AbbestellFehler):
        dienst.einklick_senden(DRAUSSEN, transport=gegen.transport())
    assert len(gegen.anfragen) == dienst.MAX_SPRUENGE + 1


def test_eine_dankeseite_zaehlt_als_erledigt_und_wird_nicht_besucht():
    """Ein 302 heisst: angekommen, hier geht es zur Seite für Menschen."""
    gegen = Gegenstelle(code=302, weiter="https://172.16.0.10/danke")
    dienst.einklick_senden(DRAUSSEN, transport=gegen.transport())
    assert len(gegen.anfragen) == 1


def test_eine_absage_wird_benannt():
    with pytest.raises(dienst.AbbestellFehler) as f:
        dienst.einklick_senden(DRAUSSEN, transport=Gegenstelle(code=500).transport())
    assert str(f.value) == "abbestellen_abgewiesen"
    assert f.value.werte == {"code": 500}


def test_ein_stummer_server_wird_benannt():
    def platzen(_anfrage):
        raise httpx.ConnectError("weg")

    with pytest.raises(dienst.AbbestellFehler) as f:
        dienst.einklick_senden(DRAUSSEN, transport=httpx.MockTransport(platzen))
    assert str(f.value) == "abbestellen_nicht_erreichbar"


# --- Die Adresse ----------------------------------------------------------- #


@pytest.fixture
def geprueft(db, mail, monkeypatch):
    """Die Absenderprüfung als bestanden, ohne fünf Mails anzulegen."""
    from app.services import absenderpruefung

    monkeypatch.setattr(
        absenderpruefung, "vertraute_pruefer", lambda _db, ids: {k: VERTRAUT for k in ids}
    )
    return mail


@pytest.fixture
def geschickt(monkeypatch):
    aufrufe: list[str] = []
    monkeypatch.setattr(dienst, "einklick_senden", lambda url: aufrufe.append(url))
    return aufrufe


def test_die_anzeige_verraet_das_ziel_eines_klicks_nicht(klient, geprueft):
    """Die Oberfläche braucht es nicht; sie nennt die Domain."""
    weg = klient.get(f"/api/nachrichten/{geprueft.id}").json()["abbestellen"]
    assert weg == {"art": "einklick", "ziel": "", "stelle": "93.184.216.34", "erledigt": False}


def test_der_klick_schickt_die_gespeicherte_adresse(klient, db, geprueft, geschickt):
    antwort = klient.post(f"/api/nachrichten/{geprueft.id}/abbestellen", json={})

    assert antwort.status_code == 200
    assert antwort.json()["erledigt"] is True
    assert geschickt == [DRAUSSEN]
    db.refresh(geprueft)
    assert geprueft.abbestellt_am is not None


def test_die_anfrage_kann_keine_adresse_unterschieben(klient, geprueft, geschickt):
    """⚠️ **Sonst wäre die Route ein offener Vermittler.**"""
    klient.post(
        f"/api/nachrichten/{geprueft.id}/abbestellen", json={"ziel": "https://evil.example/"}
    )
    assert geschickt == [DRAUSSEN]


def test_ein_zweiter_klick_schickt_nichts_mehr(klient, geprueft, geschickt):
    klient.post(f"/api/nachrichten/{geprueft.id}/abbestellen", json={})
    zweite = klient.post(f"/api/nachrichten/{geprueft.id}/abbestellen", json={})

    assert zweite.status_code == 200
    assert geschickt == [DRAUSSEN]


def test_eine_gescheiterte_abmeldung_gilt_nicht_als_erledigt(klient, db, geprueft, monkeypatch):
    def scheitern(_url):
        raise dienst.AbbestellFehler("abbestellen_nicht_erreichbar")

    monkeypatch.setattr(dienst, "einklick_senden", scheitern)
    antwort = klient.post(f"/api/nachrichten/{geprueft.id}/abbestellen", json={})

    assert antwort.status_code == 502
    assert antwort.json()["detail"] == "abbestellen_nicht_erreichbar"
    db.refresh(geprueft)
    assert geprueft.abbestellt_am is None


def test_ohne_pruefung_antwortet_die_adresse_mit_nein(klient, mail, geschickt):
    """Der Knopf fehlt dann, aber ein Knopf ist keine Zusicherung."""
    antwort = klient.post(f"/api/nachrichten/{mail.id}/abbestellen", json={})

    assert antwort.status_code == 409
    assert antwort.json()["detail"] == "abbestellen_nicht_moeglich"
    assert geschickt == []


def test_eine_fremde_mail_gibt_es_nicht(db, zweiter_klient, geprueft, geschickt):
    person, geheimnis = zweiten_benutzer_anlegen(db)
    anmelden(zweiter_klient, person.benutzername, "auch-geheim-456", geheimnis)

    antwort = zweiter_klient.post(f"/api/nachrichten/{geprueft.id}/abbestellen", json={})

    assert antwort.status_code == 404
    assert geschickt == []


def test_die_adresse_verlangt_eine_anmeldung(db, geprueft, zweiter_klient, geschickt):
    antwort = zweiter_klient.post(f"/api/nachrichten/{geprueft.id}/abbestellen", json={})
    assert antwort.status_code == 401
    assert geschickt == []


# --- Beim Holen der Mail --------------------------------------------------- #


def test_beim_oeffnen_wird_die_kopfzeile_gelesen(db, konto):  # noqa: F811
    from app.services import abgleich

    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen(
        "INBOX",
        1,
        "Newsletter",
        roh=(
            b"From: post@example.org\r\n"
            b"Subject: Newsletter\r\n"
            b"List-Unsubscribe: <https://example.org/ab>\r\n"
            b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
            b"Content-Type: text/plain\r\n\r\nHallo\r\n"
        ),
    )
    ordner = db.query(Ordner).filter_by(konto_id=konto.id, rolle="posteingang").one()
    n = Nachricht(
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=1,
        betreff="Newsletter",
        datum=utcnow(),
    )
    db.add(n)
    db.commit()

    abgleich.koerper_holen(server, db, n)

    assert json.loads(n.abbestellen) == {"ziele": ["https://example.org/ab"], "einklick": True}


def test_der_text_der_mail_zaehlt_nicht_als_kopfzeile(db, konto):  # noqa: F811
    """⚠️ Nur der Kopfteil, dieselbe Regel wie bei der Wichtigkeit: Eine Mail
    über Mailinglisten kann die Zeile im Text zitieren."""
    from app.services import abgleich

    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen(
        "INBOX",
        1,
        "Frage",
        roh=(
            b"From: post@example.org\r\nSubject: Frage\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"List-Unsubscribe: <https://example.org/ab>\r\n"
        ),
    )
    ordner = db.query(Ordner).filter_by(konto_id=konto.id, rolle="posteingang").one()
    n = Nachricht(
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=1,
        betreff="Frage",
        datum=utcnow(),
    )
    db.add(n)
    db.commit()

    abgleich.koerper_holen(server, db, n)

    assert n.abbestellen == ""
