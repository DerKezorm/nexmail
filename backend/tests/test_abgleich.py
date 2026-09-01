"""Der Abgleich — gegen einen IMAP-Doppelgänger.

⚠️ **Kein echter Server.** Ein Testlauf, der an einem fremden Postfach hängt,
ist irgendwann rot, ohne dass jemand etwas kaputt gemacht hat.

Der Doppelgänger bildet genau die Muschelschalen von ``IMAPClient`` nach, die
der Abgleich benutzt — und er kann die beiden Dinge, die im Betrieb wehtun:
**``UIDVALIDITY`` ändern** und **Nachrichten verschwinden lassen.**
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from email.message import EmailMessage

from app.models import Konto, Nachricht, Ordner
from app.services import abgleich, konten
from conftest import einrichten

PASSWORT = "sehr-geheim-123"


class Umschlag:
    """Was IMAPClient als ENVELOPE liefert — die Felder, die benutzt werden."""

    def __init__(self, betreff: str, von: str, datum: datetime):
        name, _, rest = von.partition("<")
        adresse = rest.rstrip(">") or von
        postfach, _, wirt = adresse.partition("@")

        class Eintrag:
            def __init__(self, n, m, h):
                self.name = n.strip().encode() if n.strip() else None
                self.mailbox = m.encode()
                self.host = h.encode()

        self.subject = betreff.encode()
        self.from_ = [Eintrag(name, postfach, wirt)]
        self.to = [Eintrag("", "betreiber", "icloud.example")]
        self.cc = None
        self.date = datum
        self.message_id = f"<{betreff[:8]}@x.example>".encode()


class FalscherServer:
    """Ein IMAP-Server, den man steuern kann."""

    def __init__(self):
        self.ordner: dict[str, dict] = {}
        self.geholt: list[int] = []

    def anlegen(self, pfad: str, uidvalidity: int = 100):
        self.ordner[pfad] = {"uidvalidity": uidvalidity, "nachrichten": {}}

    def einwerfen(self, pfad: str, uid: int, betreff: str, gelesen=False, roh: bytes | None = None):
        self.ordner[pfad]["nachrichten"][uid] = {
            "betreff": betreff,
            "gelesen": gelesen,
            "markiert": False,
            "roh": roh,
        }

    # --- die Muschelschalen von IMAPClient ---------------------------- #

    def select_folder(self, pfad: str, readonly: bool = False):  # noqa: ARG002
        self._aktuell = pfad
        return {b"UIDVALIDITY": self.ordner[pfad]["uidvalidity"]}

    def search(self, _kriterien):
        return sorted(self.ordner[self._aktuell]["nachrichten"])

    def fetch(self, uids, felder):
        antwort = {}
        for uid in uids:
            eintrag = self.ordner[self._aktuell]["nachrichten"].get(uid)
            if eintrag is None:
                continue
            self.geholt.append(uid)
            flags = []
            if eintrag["gelesen"]:
                flags.append(rb"\Seen")
            if eintrag["markiert"]:
                flags.append(rb"\Flagged")

            zeile: dict = {b"FLAGS": tuple(flags)}
            if any("ENVELOPE" in str(f) for f in felder):
                zeile[b"ENVELOPE"] = Umschlag(
                    eintrag["betreff"],
                    "Anja Kessler <anja@example.org>",
                    datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
                )
                zeile[b"RFC822.SIZE"] = 4096
                zeile[b"BODYSTRUCTURE"] = ("text", "plain", (), None, None, "7bit", 100)
                zeile[b"BODY[1]<0>"] = f"Vorschau zu {eintrag['betreff']}".encode()
            # ⚠️ **Der Doppelgänger antwortet nur auf ``BODY.PEEK[]``** —
            # genau wie iCloud. Auf ``RFC822`` gibt es nichts. Ein Server, der
            # beides beantwortet, hätte den Fehler vom 01.09.2026 nie gezeigt:
            # Bei iCloud blieb jede geöffnete Mail leer, bei All-Inkl nicht.
            if any("BODY.PEEK[]" == str(f) for f in felder):
                zeile[b"BODY[]"] = eintrag["roh"] or b""
            return_ = zeile
            antwort[uid] = return_
        return antwort

    def logout(self):
        pass


@pytest.fixture
def konto(klient, db):
    """Ein Postfach in der Datenbank, ohne dass je ein Server gefragt wurde."""
    einrichten(klient)
    from app.models import Benutzer

    person = db.query(Benutzer).one()
    zugang = konten.Zugangsdaten(
        anzeigename="Privat",
        adresse="anna@icloud.example",
        imap_server="imap.example",
        imap_port=993,
        imap_sicherheit="ssl",
        imap_benutzer="betreiber",
        imap_passwort="geheim",
        smtp_server="smtp.example",
        smtp_port=587,
        smtp_sicherheit="starttls",
        smtp_benutzer="anna@icloud.example",
        smtp_passwort="geheim",
    )
    k = konten.anlegen(db, person, zugang)
    db.add(Ordner(konto_id=k.id, pfad="INBOX", name="INBOX", rolle="posteingang"))
    db.commit()
    db.refresh(k)
    return k


def _posteingang(db, konto: Konto) -> Ordner:
    return next(o for o in konto.ordner if o.pfad == "INBOX")


def test_neue_nachrichten_kommen_an(db, konto):
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Erste")
    server.einwerfen("INBOX", 2, "Zweite", gelesen=True)

    runde = abgleich.ordner_abgleichen(server, db, konto, _posteingang(db, konto))

    assert runde.neu == 2
    zeilen = db.query(Nachricht).order_by(Nachricht.uid).all()
    assert [z.betreff for z in zeilen] == ["Erste", "Zweite"]
    assert zeilen[0].gelesen is False
    assert zeilen[1].gelesen is True
    assert zeilen[0].von_adresse == "anja@example.org"
    assert "Vorschau zu Erste" in zeilen[0].anreisser


def test_zweiter_lauf_holt_nichts_doppelt(db, konto):
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Erste")

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    server.geholt.clear()

    zweite = abgleich.ordner_abgleichen(server, db, konto, ordner)
    assert zweite.neu == 0
    assert db.query(Nachricht).count() == 1


def test_uidvalidity_wechsel_baut_neu_auf(db, konto):
    """⚠️ **Der Fall, den fast jeder Eigenbau übersieht.**

    Ändert der Server die UIDVALIDITY, zeigen alle gespeicherten Nummern auf
    andere Nachrichten als gedacht. Wer das nicht prüft, zeigt irgendwann eine
    Mail an, die es so nie gab.
    """
    server = FalscherServer()
    server.anlegen("INBOX", uidvalidity=100)
    server.einwerfen("INBOX", 1, "Alte Nummer eins")
    server.einwerfen("INBOX", 2, "Alte Nummer zwei")

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    assert db.query(Nachricht).count() == 2

    # Der Server vergibt die Nummern neu - unter denselben UIDs stehen jetzt
    # ganz andere Nachrichten.
    server.ordner["INBOX"]["uidvalidity"] = 777
    server.ordner["INBOX"]["nachrichten"] = {}
    server.einwerfen("INBOX", 1, "Ganz andere Mail")

    runde = abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert runde.neu_aufgebaut is True
    betreffe = [n.betreff for n in db.query(Nachricht).all()]
    assert betreffe == ["Ganz andere Mail"]
    assert "Alte Nummer eins" not in betreffe
    db.refresh(ordner)
    assert ordner.uidvalidity == 777


def test_verschwundene_werden_entfernt(db, konto):
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Bleibt")
    server.einwerfen("INBOX", 2, "Verschwindet")

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    assert db.query(Nachricht).count() == 2

    del server.ordner["INBOX"]["nachrichten"][2]
    runde = abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert runde.entfernt == 1
    assert [n.betreff for n in db.query(Nachricht).all()] == ["Bleibt"]


def test_flags_werden_nachgezogen(db, konto):
    """Wer auf dem Telefon liest, soll hier nicht ungelesen sehen."""
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Erst ungelesen")

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    assert db.query(Nachricht).one().gelesen is False

    server.ordner["INBOX"]["nachrichten"][1]["gelesen"] = True
    server.ordner["INBOX"]["nachrichten"][1]["markiert"] = True
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    db.expire_all()
    zeile = db.query(Nachricht).one()
    assert zeile.gelesen is True
    assert zeile.markiert is True


def test_zaehler_stimmen(db, konto):
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "A")
    server.einwerfen("INBOX", 2, "B", gelesen=True)
    server.einwerfen("INBOX", 3, "C")

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    db.refresh(ordner)
    assert ordner.anzahl == 3
    assert ordner.ungelesen == 2


def test_kopfdaten_ohne_koerper(db, konto):
    """⚠️ Beim Abgleich wird der Text **nicht** geholt.

    Sonst dauert der erste Lauf bei vierzigtausend Mails Stunden.
    """
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Nur Kopfdaten")

    abgleich.ordner_abgleichen(server, db, konto, _posteingang(db, konto))

    zeile = db.query(Nachricht).one()
    assert zeile.koerper_geholt is None
    assert zeile.koerper_html == ""
    assert zeile.betreff == "Nur Kopfdaten"


def test_koerper_wird_auf_abruf_geholt_und_bereinigt(db, konto):
    """Und dabei laufen Bereinigung und Bildsperre."""
    m = EmailMessage()
    m["Subject"] = "Werbung"
    m["From"] = "shop@example.org"
    m.set_content("Nur Text")
    m.add_alternative(
        '<p>Kauf <script>alert(1)</script></p>'
        '<img src="https://absender.example/zaehl.gif">',
        subtype="html",
    )

    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Werbung", roh=m.as_bytes())

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    zeile = db.query(Nachricht).one()
    abgleich.koerper_holen(server, db, zeile)

    db.refresh(zeile)
    assert zeile.koerper_geholt is not None
    assert "<script" not in zeile.koerper_html
    assert zeile.geblockte_bilder == 1
    assert " src=" not in zeile.koerper_html
    assert "absender.example" in zeile.koerper_html


def test_anhang_landet_auf_der_platte(db, konto):
    from app.config import get_settings

    m = EmailMessage()
    m["Subject"] = "Rechnung"
    m["From"] = "a@b.example"
    m.set_content("Im Anhang.")
    m.add_attachment(b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="R.pdf")

    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Rechnung", roh=m.as_bytes())

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    zeile = db.query(Nachricht).one()
    abgleich.koerper_holen(server, db, zeile)

    db.refresh(zeile)
    assert len(zeile.anhaenge) == 1
    anhang = zeile.anhaenge[0]
    assert anhang.dateiname == "R.pdf"
    assert anhang.blob_hash
    assert (get_settings().blob_dir / anhang.blob_hash).is_file()
    assert zeile.hat_anhang is True


def test_derselbe_anhang_liegt_einmal_da(db, konto):
    """Nach Prüfsumme benannt — dieselbe Datei in zehn Mails kostet einmal Platz."""
    from app.config import get_settings

    def mail(betreff: str) -> bytes:
        m = EmailMessage()
        m["Subject"] = betreff
        m["From"] = "a@b.example"
        m.set_content("Text")
        m.add_attachment(b"immer derselbe inhalt", maintype="application", subtype="pdf",
                         filename="gleich.pdf")
        return m.as_bytes()

    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Eins", roh=mail("Eins"))
    server.einwerfen("INBOX", 2, "Zwei", roh=mail("Zwei"))

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    for zeile in db.query(Nachricht).all():
        abgleich.koerper_holen(server, db, zeile)

    hashes = {a.blob_hash for a in db.query(__import__("app.models", fromlist=["Anhang"]).Anhang).all()}
    assert len(hashes) == 1
    dateien = list(get_settings().blob_dir.glob("*"))
    assert len(dateien) == 1


def test_ein_kaputter_ordner_stoppt_nicht_alles(db, konto, monkeypatch):
    """⚠️ Sonst hält ein einziger klemmender Ordner das Postfach leer."""
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Kommt an")
    server.anlegen("Kaputt")

    db.add(Ordner(konto_id=konto.id, pfad="Kaputt", name="Kaputt", rolle="eigen"))
    db.commit()
    db.refresh(konto)

    echt = server.select_folder

    def manchmal_kaputt(pfad, readonly=False):
        if pfad == "Kaputt":
            raise RuntimeError("Der Server mag diesen Ordner nicht.")
        return echt(pfad, readonly)

    server.select_folder = manchmal_kaputt
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)

    abgleich.konto_abgleichen(db, konto)

    assert db.query(Nachricht).count() == 1


# --- Vorschau -------------------------------------------------------------- #


def test_der_anriss_wird_dekodiert():
    """⚠️ **Aus Schaden entstanden, 01.09.2026.**

    Ein Teilabruf (``BODY[1]<0.512>``) liefert die Bytes **so, wie sie in der
    Mail stehen** — der Server dekodiert nichts. In der Liste stand deshalb
    „f=C3=BCr deinen Apple=C2=A0Account" statt „für deinen Apple Account".
    """
    from app.services.abgleich import _anriss_aus_teil

    roh = b"Hallo Anna, f=C3=BCr deinen Apple=C2=A0Account"
    struktur = ("text", "plain", ("charset", "utf-8"), None, None, "quoted-printable", 100)

    assert _anriss_aus_teil(roh, struktur).startswith("Hallo Anna, für deinen Apple")


def test_base64_im_anriss():
    """Ein Teilabruf schneidet mitten in einer Gruppe ab — das darf nichts kosten."""
    import base64 as b64

    from app.services.abgleich import _anriss_aus_teil

    roh = b64.b64encode("Grüße aus dem Süden, hier ist alles gut.".encode())[:20]
    struktur = ("text", "plain", ("charset", "utf-8"), None, None, "base64", 100)

    ergebnis = _anriss_aus_teil(roh, struktur)
    assert ergebnis.startswith("Gr"), f"Nichts herausgekommen: {ergebnis!r}"


def test_ohne_struktur_bleibt_es_beim_rohtext():
    """Kein Absturz, wenn der Server keine Struktur mitschickt."""
    from app.services.abgleich import _anriss_aus_teil

    assert _anriss_aus_teil(b"Einfach nur Text", None) == "Einfach nur Text"


def test_ein_schon_gesetzter_anriss_wird_beim_oeffnen_verbessert(db, konto):  # noqa: F811
    """⚠️ Sonst bleibt eine einmal falsch gebaute Vorschau für immer stehen —
    auch nachdem der Fehler behoben ist."""
    ordner = _posteingang(db, konto)
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen(
        "INBOX",
        1,
        "Mit Text",
        roh=b"Subject: Mit Text\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nDer ganze Text.",
    )
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    nachricht = db.query(Nachricht).filter_by(uid=1).one()
    nachricht.anreisser = "f=C3=BCr kaputt"
    db.commit()

    abgleich.koerper_holen(server, db, nachricht)

    assert "=C3=" not in nachricht.anreisser, "Die kaputte Vorschau steht immer noch da."
