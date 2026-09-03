"""Web Push — was still falsch sein kann.

⚠️ **Hier scheitert nichts laut.** Eine falsch verschlüsselte Meldung wird vom
Push-Dienst angenommen und geht auf dem Telefon nur nicht auf. Ein zu
großzügiger Filter meldet den halben Posteingang. Ein zu strenger meldet nie,
und man merkt es an einem verpassten Termin.

Deshalb prüft diese Datei drei Sorten Aussage getrennt:

* **Die Kryptografie wirklich rückwärts.** Nicht „es kommen Bytes heraus",
  sondern: der Browser kann sie mit seinem privaten Schlüssel wieder lesen.
* **Wer gemeldet wird und wer nicht** — Erstabgleich, neu aufgebauter Ordner,
  Wiedervorlage, Ordnerwahl, gelesen.
* **Dass eine misslungene Zustellung die Erinnerung nicht verschluckt.**
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.models import Benutzer, Erinnerungszustellung, Konto, Nachricht, Ordner, PushAnmeldung
from app.services import push, termine
from conftest import einrichten

JETZT = datetime(2026, 9, 17, 13, 45, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Ein Browser, der wirklich entschlüsseln kann
# --------------------------------------------------------------------------- #


class Browser:
    """Ein Abonnement mit echten Schlüsseln — und der Fähigkeit, mitzulesen.

    ⚠️ **Ohne die zweite Hälfte wäre jeder Test hier hohl.** Ein Doppelgänger,
    der nur ``201`` sagt, bestätigt, dass irgendwelche Bytes hinausgingen. Ob
    sie sich entschlüsseln lassen, sagt er nicht — und genau das ist der
    Unterschied zwischen einer Meldung und einer, die auf dem Telefon nicht
    aufgeht.
    """

    def __init__(self, endpunkt: str = "https://push.example.com/abo/1") -> None:
        self.endpunkt = endpunkt
        self._privat = ec.generate_private_key(ec.SECP256R1())
        self._auth = b"0123456789abcdef"

    @property
    def p256dh(self) -> str:
        punkt = self._privat.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return base64.urlsafe_b64encode(punkt).rstrip(b"=").decode()

    @property
    def auth(self) -> str:
        return base64.urlsafe_b64encode(self._auth).rstrip(b"=").decode()

    def lesen(self, rumpf: bytes) -> dict:
        klar = http_ece.decrypt(
            rumpf,
            private_key=self._privat,
            auth_secret=self._auth,
            version="aes128gcm",
        )
        return json.loads(klar)

    def anmelden(self, db, person: Benutzer) -> PushAnmeldung:
        zeile = PushAnmeldung(
            benutzer_id=person.id,
            endpunkt=self.endpunkt,
            p256dh=self.p256dh,
            auth=self.auth,
            geraet="Prüfbrowser",
        )
        db.add(zeile)
        db.commit()
        return zeile


class Postbote:
    """Fängt ab, was `zustellen` hinausschicken will."""

    def __init__(self, status: int = 201, wirft: Exception | None = None) -> None:
        self.status = status
        self.wirft = wirft
        self.sendungen: list[tuple[str, bytes, dict]] = []

    def __call__(self, *_a, **_kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def post(self, url, content=None, headers=None):
        if self.wirft is not None:
            raise self.wirft
        self.sendungen.append((url, content, dict(headers or {})))
        return httpx.Response(self.status, request=httpx.Request("POST", url))


@pytest.fixture
def welt(klient, db):
    einrichten(klient)
    person = db.query(Benutzer).one()
    return person


@pytest.fixture
def postbote(monkeypatch):
    bote = Postbote()
    monkeypatch.setattr(push.httpx, "Client", bote)
    return bote


# --------------------------------------------------------------------------- #
# Der Schlüssel
# --------------------------------------------------------------------------- #


def test_der_oeffentliche_schluessel_ist_ein_roher_punkt(welt, db):
    """65 Byte unkomprimierter P-256-Punkt, base64url ohne Polster.

    ⚠️ Ein PEM oder DER an dieser Stelle lässt den Browser mit einem
    ``InvalidCharacterError`` stehen, und das liest sich wie ein Fehler im
    eigenen JavaScript.
    """
    schluessel = push.oeffentlicher_schluessel(db)
    roh = base64.urlsafe_b64decode(schluessel + "=" * (-len(schluessel) % 4))

    assert "=" not in schluessel
    assert len(roh) == 65
    assert roh[0] == 0x04  # unkomprimiert


def test_das_paar_wird_nur_einmal_erzeugt(welt, db):
    """Sonst wäre nach jedem Neustart jedes Gerät stumm."""
    erst = push.oeffentlicher_schluessel(db)
    assert push.oeffentlicher_schluessel(db) == erst


def test_der_private_teil_liegt_verschluesselt(welt, db):
    from app.db import einstellung_lesen

    push.oeffentlicher_schluessel(db)
    gespeichert = einstellung_lesen(db, push.SCHLUESSEL)

    assert gespeichert
    assert "PRIVATE KEY" not in gespeichert
    assert gespeichert.startswith("v1:")


# --------------------------------------------------------------------------- #
# Die Verschlüsselung, rückwärts geprüft
# --------------------------------------------------------------------------- #


def test_der_browser_kann_die_meldung_wirklich_lesen(welt, db, postbote):
    """Die eigentliche Zusicherung: hin verschlüsseln, zurück entschlüsseln."""
    browser = Browser()
    anmeldung = browser.anmelden(db, welt)

    push.zustellen(
        db,
        anmeldung,
        push.Meldung(titel="Zahnarzt", text="14:30 · Praxis", ziel="/kalender", marke="t-1"),
    )

    assert len(postbote.sendungen) == 1
    url, rumpf, kopf = postbote.sendungen[0]
    assert url == browser.endpunkt
    assert kopf["Content-Encoding"] == "aes128gcm"
    assert kopf["Authorization"].startswith("vapid t=")

    gelesen = browser.lesen(rumpf)
    assert gelesen["titel"] == "Zahnarzt"
    assert gelesen["text"] == "14:30 · Praxis"
    assert gelesen["ziel"] == "/kalender"


def test_ein_langer_betreff_sprengt_den_rumpf_nicht(welt, db, postbote):
    """⚠️ Über rund 4 kB weist der Push-Dienst mit 413 ab, und das fällt nirgends auf."""
    browser = Browser()
    anmeldung = browser.anmelden(db, welt)

    push.zustellen(
        db,
        anmeldung,
        push.Meldung(titel="A" * 5000, text="B" * 5000, ziel="/", marke="m"),
    )

    _, rumpf, _ = postbote.sendungen[0]
    assert len(rumpf) < 4096
    gelesen = browser.lesen(rumpf)
    assert len(gelesen["titel"]) == push.TEXT_GRENZE


def test_ein_erloschenes_abonnement_wird_geloescht(welt, db, monkeypatch):
    """410 heißt: Der Browser hat sein Abonnement weggeworfen."""
    browser = Browser()
    browser.anmelden(db, welt)
    monkeypatch.setattr(push.httpx, "Client", Postbote(status=410))

    push.zustellen(db, db.query(PushAnmeldung).one(), _meldung())

    assert db.query(PushAnmeldung).count() == 0


def test_ein_abgewiesener_schluessel_loescht_nichts(welt, db, monkeypatch):
    """⚠️ 403 heißt „falsche Unterschrift" — ein Fehler bei uns.

    Wer ihn wie 410 behandelt, räumt bei jedem eigenen Fehler die Abonnements
    aller Benutzer weg, und niemand findet heraus, warum plötzlich niemand
    mehr Meldungen bekommt.
    """
    browser = Browser()
    browser.anmelden(db, welt)
    monkeypatch.setattr(push.httpx, "Client", Postbote(status=403))

    with pytest.raises(push.Zustellfehler):
        push.zustellen(db, db.query(PushAnmeldung).one(), _meldung())

    assert db.query(PushAnmeldung).count() == 1


def test_ein_stummes_geraet_haelt_die_anderen_nicht_auf(welt, db, monkeypatch):
    """⚠️ Zwei Geräte, das erste platzt. Mit nur einem wäre der Test grün,
    egal wie der Code aussieht — dieselbe Lehre wie in der Aufräumrunde."""
    Browser("https://push.example.com/abo/kaputt").anmelden(db, welt)
    zweiter = Browser("https://push.example.com/abo/heil")
    zweiter.anmelden(db, welt)

    class Waehlerisch(Postbote):
        def post(self, url, content=None, headers=None):
            if "kaputt" in url:
                raise httpx.ConnectError("weg")
            return super().post(url, content=content, headers=headers)

    bote = Waehlerisch()
    monkeypatch.setattr(push.httpx, "Client", bote)

    assert push.an_benutzer(db, welt, _meldung()) is True
    assert [u for u, _, _ in bote.sendungen] == [zweiter.endpunkt]


# --------------------------------------------------------------------------- #
# Ruhezeit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("stunde", "erwartet"),
    [
        (23, True),   # nach 22:00
        (3, True),    # nach Mitternacht, vor 07:00
        (12, False),  # mitten am Tag
        (7, False),   # genau die Grenze: ab hier wieder wach
    ],
)
def test_die_ruhezeit_geht_ueber_mitternacht(welt, db, stunde, erwartet):
    """⚠️ ``von <= jetzt <= bis`` wäre für 22:00–07:00 genau falsch herum."""
    welt.push_ruhezeit = True
    db.commit()
    # Die Prüfdatenbank steht auf UTC, deshalb ist Ortszeit gleich UTC.
    jetzt = datetime(2026, 9, 17, stunde, 30, tzinfo=timezone.utc)
    assert push.ruhezeit_jetzt(db, welt, jetzt) is erwartet


def test_ohne_ruhezeit_ist_nie_ruhe(welt, db):
    assert welt.push_ruhezeit is False
    assert push.ruhezeit_jetzt(db, welt, datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)) is False


# --------------------------------------------------------------------------- #
# Erinnerungen
# --------------------------------------------------------------------------- #


@pytest.fixture
def kalenderwelt(welt, db):
    kalender = termine.kalender_anlegen(db, welt, "Privat")
    return welt, kalender


def _termin_gleich(db, person, kalender, vorlauf: int):
    """Ein Termin, dessen Erinnerung genau jetzt fällig ist."""
    from app.services import zeit

    beginn = push.utcnow() + timedelta(minutes=vorlauf)
    return termine.anlegen(
        db,
        person,
        kalender.id,
        titel="Zahnarzt",
        beginn=beginn,
        ende=beginn + timedelta(hours=1),
        zeitzone=zeit.zonenname_der_anwendung(db),
        erinnerung=vorlauf,
    )


def test_eine_faellige_erinnerung_geht_hinaus(kalenderwelt, db, postbote):
    person, kalender = kalenderwelt
    Browser().anmelden(db, person)
    _termin_gleich(db, person, kalender, 15)

    assert push.erinnerungen_runde() == 1
    assert len(postbote.sendungen) == 1


def test_ohne_angemeldetes_geraet_wird_nichts_verbucht(kalenderwelt, db, postbote):
    """⚠️ ``faellige`` bucht beim ERMITTELN, nicht beim Senden.

    Wer ohne Gerät fragt, verbraucht damit Erinnerungen, die nirgends ankamen
    — und wer sich eine Minute später anmeldet, bekommt sie nie. Deshalb steht
    die Abfrage nach den Geräten **vor** dem Rechner.
    """
    person, kalender = kalenderwelt
    _termin_gleich(db, person, kalender, 15)

    assert push.erinnerungen_runde() == 0
    assert db.query(Erinnerungszustellung).filter_by(kanal="push").count() == 0


def test_dieselbe_erinnerung_feuert_nur_einmal(kalenderwelt, db, postbote):
    person, kalender = kalenderwelt
    Browser().anmelden(db, person)
    _termin_gleich(db, person, kalender, 15)

    assert push.erinnerungen_runde() == 1
    assert push.erinnerungen_runde() == 0
    assert len(postbote.sendungen) == 1


def test_eine_misslungene_zustellung_verschluckt_die_erinnerung_nicht(
    kalenderwelt, db, monkeypatch
):
    """⚠️ Der wichtigste Test dieser Datei.

    Die Buchung steht fest, bevor ein Byte hinausgeht. Fällt der Push-Dienst
    für eine Minute aus, wäre die Erinnerung ohne die Rücknahme **still
    verloren**: ``nur_einmal`` übergeht sie beim nächsten Mal, und niemand
    erfährt davon.
    """
    person, kalender = kalenderwelt
    Browser().anmelden(db, person)
    _termin_gleich(db, person, kalender, 15)

    monkeypatch.setattr(push.httpx, "Client", Postbote(wirft=httpx.ConnectError("weg")))
    assert push.erinnerungen_runde() == 0
    assert db.query(Erinnerungszustellung).filter_by(kanal="push").count() == 0

    bote = Postbote()
    monkeypatch.setattr(push.httpx, "Client", bote)
    assert push.erinnerungen_runde() == 1
    assert len(bote.sendungen) == 1


def test_die_ruhezeit_verschluckt_die_vorwarnung_aber_nicht_den_termin(
    kalenderwelt, db, postbote, monkeypatch
):
    """„Jetzt gleich" ist keine Vorwarnung, sondern der Termin selbst."""
    person, kalender = kalenderwelt
    Browser().anmelden(db, person)
    person.push_ruhezeit = True
    db.commit()
    monkeypatch.setattr(push, "ruhezeit_jetzt", lambda *a, **k: True)

    _termin_gleich(db, person, kalender, 15)
    _termin_gleich(db, person, kalender, 0)

    assert push.erinnerungen_runde() == 1
    assert len(postbote.sendungen) == 1


# --------------------------------------------------------------------------- #
# Neue Post
# --------------------------------------------------------------------------- #


def _postfach(db, person: Benutzer) -> tuple[Konto, dict[str, Ordner]]:
    konto = Konto(
        benutzer_id=person.id,
        anzeigename="Pruefpostfach",
        adresse="pruefung@example.com",
        imap_server="imap.example.com",
        imap_port=993,
        smtp_server="smtp.example.com",
        smtp_port=465,
        smtp_benutzer="pruefung@example.com",
        imap_benutzer="pruefung@example.com",
        # Die Marke ist gesetzt: Der Erstabgleich ist der Sonderfall und
        # bekommt einen eigenen Test.
        erstabgleich_durch=True,
    )
    db.add(konto)
    db.flush()
    ordner = {}
    for pfad, rolle in (
        ("INBOX", "posteingang"),
        ("Archiv", "archiv"),
        ("Junk", "junk"),
        ("Wiedervorlage", "eigen"),
    ):
        o = Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle=rolle, abonniert=True)
        db.add(o)
        db.flush()
        ordner[pfad] = o
    db.commit()
    return konto, ordner


def _mail(db, person, konto, ordner, *, betreff="Rechnung", gelesen=False) -> Nachricht:
    n = Nachricht(
        benutzer_id=person.id,
        konto_id=konto.id,
        ordner_id=ordner.id,
        uid=db.query(Nachricht).count() + 1,
        von_name="Absender",
        von_adresse="wer@example.org",
        betreff=betreff,
        gelesen=gelesen,
    )
    db.add(n)
    db.commit()
    return n


def test_neue_post_im_posteingang_meldet_sich(welt, db, postbote):
    Browser().anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    mail = _mail(db, welt, konto, ordner["INBOX"])

    push.neue_mail_melden(db, konto, [mail.id], set())

    assert len(postbote.sendungen) == 1


def test_was_eine_regel_ins_archiv_geraeumt_hat_meldet_sich_nicht(welt, db, postbote):
    """⚠️ Genau der Fall, für den die Meldung hinter den Regeln steht."""
    browser = Browser()
    browser.anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    mail = _mail(db, welt, konto, ordner["Archiv"])

    push.neue_mail_melden(db, konto, [mail.id], set())

    assert postbote.sendungen == []


def test_bei_alle_ordner_meldet_das_archiv_aber_nie_der_junk(welt, db, postbote):
    """⚠️ **Ohne abgeschaltete Buendelung waere dieser Test hohl.**

    Bei zwei Treffern geht eine gebuendelte Meldung hinaus, bei einem auch —
    ``len(sendungen) == 1`` stimmt dann in beiden Faellen. Die Mutationsprobe
    „Junk meldet trotzdem" lief genau deshalb auf Rueckgabecode 0. Einzeln
    gemeldet ist der Unterschied sichtbar, und der Betreff sagt zusaetzlich,
    **welche** Mail es war.
    """
    browser = Browser()
    browser.anmelden(db, welt)
    welt.push_mail_alle_ordner = True
    welt.push_mail_buendeln = False
    db.commit()
    konto, ordner = _postfach(db, welt)
    im_archiv = _mail(db, welt, konto, ordner["Archiv"], betreff="Aus dem Archiv")
    im_junk = _mail(db, welt, konto, ordner["Junk"], betreff="Aus dem Junk")

    push.neue_mail_melden(db, konto, [im_archiv.id, im_junk.id], set())

    assert len(postbote.sendungen) == 1
    assert browser.lesen(postbote.sendungen[0][1])["text"] == "Aus dem Archiv"


def test_die_wiedervorlage_meldet_sich_nie(welt, db, postbote):
    """Was dort liegt, hat ein Mensch bewusst weggelegt."""
    Browser().anmelden(db, welt)
    welt.push_mail_alle_ordner = True
    db.commit()
    konto, ordner = _postfach(db, welt)
    mail = _mail(db, welt, konto, ordner["Wiedervorlage"])

    push.neue_mail_melden(db, konto, [mail.id], set())

    assert postbote.sendungen == []


def test_ein_neu_aufgebauter_ordner_meldet_nichts(welt, db, postbote):
    """⚠️ Wechselt die UIDVALIDITY, ist der ganze Ordner „neu"."""
    Browser().anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    mail = _mail(db, welt, konto, ordner["INBOX"])

    push.neue_mail_melden(db, konto, [mail.id], {"INBOX"})

    assert postbote.sendungen == []


def test_gelesene_post_meldet_sich_nicht(welt, db, postbote):
    """Am Telefon schon gelesen, am Rechner nicht noch einmal."""
    Browser().anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    mail = _mail(db, welt, konto, ordner["INBOX"], gelesen=True)

    push.neue_mail_melden(db, konto, [mail.id], set())

    assert postbote.sendungen == []


def test_mehrere_mails_werden_zu_einer_meldung(welt, db, postbote):
    browser = Browser()
    browser.anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    ids = [_mail(db, welt, konto, ordner["INBOX"], betreff=f"Nr {i}").id for i in range(4)]

    push.neue_mail_melden(db, konto, ids, set())

    assert len(postbote.sendungen) == 1
    gelesen = browser.lesen(postbote.sendungen[0][1])
    assert gelesen["titel"] == "4 neue Nachrichten"


def test_ohne_buendeln_meldet_jede_mail_einzeln(welt, db, postbote):
    Browser().anmelden(db, welt)
    welt.push_mail_buendeln = False
    db.commit()
    konto, ordner = _postfach(db, welt)
    ids = [_mail(db, welt, konto, ordner["INBOX"], betreff=f"Nr {i}").id for i in range(3)]

    push.neue_mail_melden(db, konto, ids, set())

    assert len(postbote.sendungen) == 3


def test_der_erste_abgleich_eines_postfachs_meldet_nichts(welt, db, postbote):
    """⚠️ Sonst wäre ein frisch eingerichtetes Postfach eine Meldung
    „8.000 neue Nachrichten" — und die Marke muss auch dann fallen, wenn
    der Abgleich gar nichts brachte."""
    from app.services.abgleich import _melden

    Browser().anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    konto.erstabgleich_durch = False
    db.commit()
    mail = _mail(db, welt, konto, ordner["INBOX"])

    _melden(db, konto, [mail.id], {})

    assert postbote.sendungen == []
    assert konto.erstabgleich_durch is True

    # Die zweite Runde meldet dann sehr wohl.
    zweite = _mail(db, welt, konto, ordner["INBOX"], betreff="Danach")
    _melden(db, konto, [zweite.id], {})
    assert len(postbote.sendungen) == 1


def test_eine_misslungene_meldung_haelt_keine_post_auf(welt, db, monkeypatch):
    """⚠️ Dieselbe Haltung wie bei den Regeln daneben."""
    from app.services.abgleich import _melden

    Browser().anmelden(db, welt)
    konto, ordner = _postfach(db, welt)
    mail = _mail(db, welt, konto, ordner["INBOX"])
    monkeypatch.setattr(
        push, "neue_mail_melden", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaputt"))
    )

    _melden(db, konto, [mail.id], {})  # darf nicht werfen


def _meldung() -> push.Meldung:
    return push.Meldung(titel="Titel", text="Text", ziel="/", marke="m")
