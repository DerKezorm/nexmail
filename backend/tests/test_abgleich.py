"""Der Abgleich — gegen einen IMAP-Doppelgänger.

⚠️ **Kein echter Server.** Ein Testlauf, der an einem fremden Postfach hängt,
ist irgendwann rot, ohne dass jemand etwas kaputt gemacht hat.

Der Doppelgänger bildet genau die Muschelschalen von ``IMAPClient`` nach, die
der Abgleich benutzt — und er kann die beiden Dinge, die im Betrieb wehtun:
**``UIDVALIDITY`` ändern** und **Nachrichten verschwinden lassen.**
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import event
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
        # ⚠️ Ob der Server eigene Keywords erlaubt (PERMANENTFLAGS mit \*).
        # Der Doppelgaenger kann beides — wie ein echter Server: iCloud
        # erlaubt Keywords, mancher Ordner anderswo nicht.
        self.eigene_keywords = True

    def anlegen(self, pfad: str, uidvalidity: int = 100, kennzeichen: tuple[bytes, ...] = ()):
        self.ordner[pfad] = {
            "uidvalidity": uidvalidity,
            "nachrichten": {},
            # SPECIAL-USE, wie ein Server es meldet: ``(rb"\Archive",)``.
            "kennzeichen": tuple(kennzeichen),
        }

    # ⚠️ **Der Doppelgaenger nennt seine Ordner, wie ein echter Server.** Seit
    # dem 18.09.2026 zieht jeder Abgleich die Ordnerliste nach. Ein
    # Doppelgaenger ohne ``LIST`` haette jeden Test hier umgeworfen; einer,
    # der immer dieselbe Liste nennt, haette das Nachziehen nie geprueft.
    #: Gesetzt heisst: ``LIST`` scheitert, wie bei einem Server, der klemmt.
    liste_klemmt = False
    #: Gesetzt heisst: ``LIST`` antwortet, aber ohne jeden Ordner.
    liste_leer = False

    def list_folders(self):
        if self.liste_klemmt:
            from imapclient.exceptions import IMAPClientError

            raise IMAPClientError("LIST failed")
        if self.liste_leer:
            return []
        return [
            ((rb"\HasNoChildren", *e.get("kennzeichen", ())), b"/", pfad)
            for pfad, e in self.ordner.items()
        ]

    def list_sub_folders(self):
        if self.liste_leer:
            return []
        return [((), b"/", pfad) for pfad in self.ordner]

    def einwerfen(
        self,
        pfad: str,
        uid: int,
        betreff: str,
        gelesen=False,
        roh: bytes | None = None,
        kopfzeilen: dict[str, str] | None = None,
        schlagworte: list[str] | None = None,
        struktur=None,
        von: str = "Anja Kessler <anja@example.org>",
    ):
        self.ordner[pfad]["nachrichten"][uid] = {
            "betreff": betreff,
            "von": von,
            "gelesen": gelesen,
            "markiert": False,
            "roh": roh,
            # Kopfzeilen, die ein HEADER.FIELDS-Abruf liefern soll — z. B.
            # References, Importance oder X-Priority. Namen wie in der Mail.
            "kopfzeilen": kopfzeilen or {},
            # IMAP-Keywords an der Nachricht — z. B. von Thunderbird gesetzt.
            "schlagworte": list(schlagworte or []),
            # Was BODYSTRUCTURE melden soll. Ohne Angabe: eine einfache
            # Textmail. Wer einen Kalenderteil braucht, gibt ihn hier mit.
            "struktur": struktur,
        }

    # --- die Muschelschalen von IMAPClient ---------------------------- #

    def select_folder(self, pfad: str, readonly: bool = False):  # noqa: ARG002
        self._aktuell = pfad
        # PERMANENTFLAGS wie bei einem echten Server: mit \* duerfen Clients
        # eigene Keywords anlegen, ohne nicht.
        dauerhaft = (rb"\Seen", rb"\Flagged", rb"\Answered", rb"\Deleted", rb"\Draft")
        if self.eigene_keywords:
            dauerhaft = (*dauerhaft, rb"\*")
        return {
            b"UIDVALIDITY": self.ordner[pfad]["uidvalidity"],
            b"PERMANENTFLAGS": dauerhaft,
            # Seit Issue #9 der Maßstab, an dem der Abgleich eine gekappte
            # Suche erkennt.
            b"EXISTS": len(self.ordner[pfad]["nachrichten"]),
        }

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
            for keyword in eintrag.get("schlagworte", []):
                flags.append(keyword.encode())

            zeile: dict = {b"FLAGS": tuple(flags)}
            if any("ENVELOPE" in str(f) for f in felder):
                zeile[b"ENVELOPE"] = Umschlag(
                    eintrag["betreff"],
                    eintrag.get("von", "Anja Kessler <anja@example.org>"),
                    datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
                )
                # ⚠️ **Trägt die Mail eine Message-ID, steht DIE im Umschlag**,
                # wie bei einem echten Server. Der erfundene Wert aus dem
                # Betreff verdeckte am 27.09.2026, dass ein Rückweg über zwei
                # Postfächer seine Mails nicht wiederfand.
                kennung = re.search(rb"^Message-ID:\s*(\S+)", eintrag.get("roh") or b"",
                                    re.MULTILINE | re.IGNORECASE)
                if kennung:
                    zeile[b"ENVELOPE"].message_id = kennung.group(1)
                zeile[b"RFC822.SIZE"] = 4096
                zeile[b"BODYSTRUCTURE"] = eintrag.get("struktur") or (
                    "text",
                    "plain",
                    (),
                    None,
                    None,
                    "7bit",
                    100,
                )
                zeile[b"BODY[1]<0>"] = f"Vorschau zu {eintrag['betreff']}".encode()
            # ⚠️ **Der Doppelgänger antwortet nur auf ``BODY.PEEK[]``** —
            # genau wie iCloud. Auf ``RFC822`` gibt es nichts. Ein Server, der
            # beides beantwortet, hätte den Fehler vom 01.09.2026 nie gezeigt:
            # Bei iCloud blieb jede geöffnete Mail leer, bei All-Inkl nicht.
            if any("BODY.PEEK[]" == str(f) for f in felder):
                zeile[b"BODY[]"] = eintrag["roh"] or b""
            # Ein HEADER.FIELDS-Abruf bekommt genau die verlangten Kopfzeilen —
            # so wie ein echter Server, samt Schluessel ohne ``.PEEK``. Der
            # Abgleich holt darueber References und die Wichtigkeit.
            for feld in felder:
                name = feld.decode() if isinstance(feld, bytes) else str(feld)
                if not name.startswith("BODY.PEEK[HEADER.FIELDS"):
                    continue
                verlangt = {
                    w.upper() for w in name[name.index("(") + 1 : name.index(")")].split()
                }
                # Ein Wert darf eine Liste sein: mehrere Zeilen desselben
                # Namens, in der Reihenfolge der Mail (Authentication-Results).
                zeilen = [
                    f"{k}: {einzeln}"
                    for k, w in eintrag.get("kopfzeilen", {}).items()
                    if k.upper() in verlangt
                    for einzeln in (w if isinstance(w, list) else [w])
                ]
                schluessel = name.replace("BODY.PEEK[", "BODY[", 1).encode()
                zeile[schluessel] = ("\r\n".join(zeilen) + "\r\n\r\n").encode() if zeilen else b""
            return_ = zeile
            antwort[uid] = return_
        return antwort

    def logout(self):
        pass

    # Nach einem gescheiterten Ordner fragt der Abgleich, ob die Leitung noch
    # antwortet (``_verbindung_heilen``).
    def noop(self):
        return (b"NOOP completed", [])

    def shutdown(self):
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


def test_eine_taktrunde_ohne_aenderung_schreibt_nichts(db, konto):
    """⚠️ **Sonst schreibt jede Runde das ganze Fenster neu.**

    Der Flags-Nachzug lief bis zum 03.09.2026 je UID in ein ``UPDATE``, ohne
    den alten Wert anzusehen. Bei ``FLAGS_FENSTER = 2000`` sind das
    zweitausend Schreibvorgaenge je Ordner und Taktrunde, auch wenn sich seit
    zwei Minuten nichts getan hat. Gemessen 740,7 ms je Fenster gegen 16,8 ms
    mit Vergleich; bei fuenf Postfaechern und Takt 120 s rund 111 Sekunden
    Rechenzeit je Stunde, ohne dass jemand etwas tut.

    Gezaehlt werden die Schreibvorgaenge selbst, nicht die Laufzeit: Eine Zeit
    ist auf einem geteilten Rechner keine Zusicherung.
    """
    server = FalscherServer()
    server.anlegen("INBOX")
    for uid in range(1, 6):
        server.einwerfen("INBOX", uid, f"Nachricht {uid}")

    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    schreibvorgaenge = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def mitzaehlen(conn, cursor, anweisung, parameter, kontext, viele):  # noqa: ARG001
        if anweisung.lstrip().upper().startswith("UPDATE NACHRICHT"):
            schreibvorgaenge.append(anweisung)

    try:
        # Zweite Runde, am Server hat sich nichts getan.
        abgleich.ordner_abgleichen(server, db, konto, ordner)
        assert schreibvorgaenge == [], (
            f"{len(schreibvorgaenge)} Schreibvorgaenge, obwohl sich nichts geaendert hat."
        )

        # Und die Gegenprobe: EINE echte Aenderung schreibt auch genau eine Zeile.
        server.ordner["INBOX"]["nachrichten"][3]["gelesen"] = True
        abgleich.ordner_abgleichen(server, db, konto, ordner)
        assert len(schreibvorgaenge) == 1, (
            "Eine geaenderte Nachricht muss genau einen Schreibvorgang ergeben, "
            f"es waren {len(schreibvorgaenge)}."
        )
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", mitzaehlen)

    db.expire_all()
    assert db.query(Nachricht).filter(Nachricht.uid == 3).one().gelesen is True


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


# --- Große Postfächer (Issue #7) ------------------------------------------ #


def _drei_ordner(db, konto, server: FalscherServer) -> None:
    """INBOX plus zwei weitere, jeder mit einer Mail, auf Server und hier."""
    for pfad in ("INBOX", "Archiv", "Gesendet"):
        server.anlegen(pfad)
        server.einwerfen(pfad, 1, f"Mail in {pfad}")
        if pfad != "INBOX":
            db.add(Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle="eigen"))
    db.commit()
    db.refresh(konto)


def test_eine_search_zeile_ueber_ein_megabyte_wird_gelesen(monkeypatch):
    """⚠️ ``SEARCH ALL`` kommt als EINE Zeile, und ``imaplib`` brach ab Werk bei
    1.000.000 Byte ab: rund 125.000 Mails mit siebenstelligen UIDs. Geprüft
    über einen echten Socket und den echten Leser, nicht über den Doppelgänger,
    denn die Grenze sitzt genau dort."""
    import imaplib
    import socket
    import threading

    from imapclient import IMAPClient

    from app.services import imap  # noqa: F401 - setzt die Grenze

    anzahl = 140_000
    uids = b" ".join(str(i).encode() for i in range(1_000_000, 1_000_000 + anzahl))
    assert len(uids) > 1_000_000  # Bodenschwelle: sonst prüft der Test nichts

    lauscher = socket.create_server(("127.0.0.1", 0))

    def server():
        verbindung, _ = lauscher.accept()
        with verbindung, verbindung.makefile("rwb") as leitung:
            def sag(zeile: bytes) -> None:
                leitung.write(zeile)
                leitung.flush()

            sag(b"* OK bereit\r\n")
            while zeile := leitung.readline():
                kennung, befehl = zeile.split()[:2]
                fertig = kennung + b" OK erledigt\r\n"
                if befehl.upper() == b"CAPABILITY":
                    sag(b"* CAPABILITY IMAP4rev1\r\n" + fertig)
                elif befehl.upper() in (b"SELECT", b"EXAMINE"):
                    sag(b"* 1 EXISTS\r\n* OK [UIDVALIDITY 7] x\r\n" + fertig)
                elif befehl.upper() == b"UID":
                    sag(b"* SEARCH " + uids + b"\r\n" + fertig)
                elif befehl.upper() == b"LOGOUT":
                    sag(b"* BYE\r\n" + fertig)
                    return
                else:
                    sag(fertig)

    threading.Thread(target=server, daemon=True).start()
    # Ohne TLS: IMAPClients eigener Transport für ``ssl=False`` scheitert unter
    # Python 3.14 an ``self.file``. Die Zeile liest in beiden Fällen dasselbe
    # ``imaplib.IMAP4.readline``.
    monkeypatch.setattr(IMAPClient, "_create_IMAP4", lambda self: imaplib.IMAP4(self.host, self.port))
    klient = IMAPClient("127.0.0.1", port=lauscher.getsockname()[1], ssl=False)
    try:
        klient.login("jemand", "egal")
        klient.select_folder("INBOX", readonly=True)
        assert len(klient.search(["ALL"])) == anzahl
    finally:
        klient.logout()
        lauscher.close()


def test_eine_verdorbene_leitung_reisst_die_folgenden_ordner_nicht_mit(db, konto, monkeypatch):
    """⚠️ Bricht eine Antwort mittendrin ab, liegt ihr Rest noch in der Leitung,
    und jeder weitere Befehl darauf scheitert. Issue #7: Trash, All Mail und
    Sent scheiterten an den Resten der INBOX-Antwort. Danach muss neu
    verbunden werden."""
    import imaplib

    verbindungen: list[FalscherServer] = []
    gesehen: list[str] = []

    class Verdorben(FalscherServer):
        hin = False

        def _pruefen(self):
            if self.hin:
                raise imaplib.IMAP4.abort("unexpected response: b'1000123 1000124'")

        def select_folder(self, pfad, readonly=False):
            self._pruefen()
            gesehen.append(pfad)
            # Der erste Ordner überhaupt verdirbt die Leitung, egal welcher:
            # So hängt der Test nicht an der Reihenfolge der Ordner.
            if len(gesehen) == 1:
                self.hin = True
                raise imaplib.IMAP4.error("command: SEARCH => got more than 1000000 bytes")
            return super().select_folder(pfad, readonly)

        def search(self, kriterien):
            self._pruefen()
            return super().search(kriterien)

        def fetch(self, uids, felder):
            self._pruefen()
            return super().fetch(uids, felder)

        def noop(self):
            self._pruefen()
            return super().noop()

    def verbinden(*_a, **_k):
        neu = Verdorben()
        _drei_ordner_auf(neu)
        verbindungen.append(neu)
        return neu

    def _drei_ordner_auf(server):
        for pfad in ("INBOX", "Archiv", "Gesendet"):
            server.anlegen(pfad)
            server.einwerfen(pfad, 1, f"Mail in {pfad}")

    for pfad in ("Archiv", "Gesendet"):
        db.add(Ordner(konto_id=konto.id, pfad=pfad, name=pfad, rolle="eigen"))
    db.commit()
    db.refresh(konto)
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", verbinden)

    ergebnis = abgleich.konto_abgleichen(db, konto)

    assert len(gesehen) == 3  # Bodenschwelle: alle drei Ordner kamen dran
    assert len(verbindungen) == 2  # genau eine neue Verbindung, nicht je Ordner eine
    assert sorted(ergebnis) == sorted(gesehen[1:])
    assert db.query(Nachricht).count() == 2


def test_eine_gesperrte_sitzung_reisst_die_folgenden_ordner_nicht_mit(db, konto, monkeypatch):
    """Scheitert ein Ordner beim Festschreiben, ist die Sitzung gesperrt, bis
    jemand zurückrollt. Ohne das scheiterten alle folgenden Ordner und am Ende
    das Konto selbst."""
    server = FalscherServer()
    _drei_ordner(db, konto, server)
    monkeypatch.setattr(abgleich.imapdienst, "verbinden", lambda *a, **k: server)

    echt = abgleich.ordner_abgleichen
    aufrufe: list[str] = []

    def erster_platzt(klient, db_, konto_, ordner):
        aufrufe.append(ordner.pfad)
        if len(aufrufe) == 1:
            # Ein Doppel auf ``uq_ordner_pfad``: scheitert beim Festschreiben.
            db_.add(Ordner(konto_id=konto_.id, pfad=ordner.pfad, name="x", rolle="eigen"))
            db_.commit()
        return echt(klient, db_, konto_, ordner)

    monkeypatch.setattr(abgleich, "ordner_abgleichen", erster_platzt)

    abgleich.konto_abgleichen(db, konto)

    assert len(aufrufe) == 3
    assert db.query(Nachricht).count() == 2
    db.refresh(konto)
    assert konto.zuletzt_geprueft is not None


def test_ein_abgerissener_erstabgleich_macht_dort_weiter(db, konto, monkeypatch):
    """⚠️ Ein Erstabgleich mit 100.000 Mails läuft Stunden. Reißt er mittendrin
    ab, gilt der Fortschritt der fertigen Blöcke, und der nächste Lauf holt
    nur den Rest. Vorher stand ``hoechste_uid`` erst am Ende fest: Der nächste
    Lauf wollte alles noch einmal anlegen und scheiterte für immer an
    ``uq_nachricht_uid``."""
    monkeypatch.setattr(abgleich, "BLOCK", 2)
    server = FalscherServer()
    server.anlegen("INBOX")
    for uid in range(1, 6):
        server.einwerfen("INBOX", uid, f"Mail {uid}")
    ordner = _posteingang(db, konto)

    echt = server.fetch
    bloecke: list[list[int]] = []
    abriss = {"bei": 2}

    def mit_abriss(uids, felder):
        # Nur der Abruf neuer Mails zählt; der Flags-Nachzug fragt ohne ENVELOPE.
        if any("ENVELOPE" in str(f) for f in felder):
            bloecke.append(sorted(uids))
            if len(bloecke) == abriss["bei"]:
                raise OSError("Verbindung abgerissen")
        return echt(uids, felder)

    server.fetch = mit_abriss
    with pytest.raises(OSError):
        abgleich.ordner_abgleichen(server, db, konto, ordner)
    db.rollback()

    assert db.query(Nachricht).count() == 2
    assert ordner.hoechste_uid == 2

    abriss["bei"] = 0
    bloecke.clear()
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert sorted(n.uid for n in db.query(Nachricht).all()) == [1, 2, 3, 4, 5]
    assert sorted(u for b in bloecke for u in b) == [3, 4, 5]
    assert ordner.hoechste_uid == 5


def test_was_schon_da_ist_wird_nicht_noch_einmal_angelegt(db, konto):
    """Der Zustand, den ältere Fassungen nach einem Abriss hinterließen: Zeilen
    da, ``hoechste_uid`` noch auf 0. Er muss von selbst heilen, sonst hängt
    jedes betroffene Postfach weiter fest."""
    server = FalscherServer()
    server.anlegen("INBOX")
    for uid in range(1, 4):
        server.einwerfen("INBOX", uid, f"Mail {uid}")
    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    ordner.hoechste_uid = 0
    db.commit()
    server.einwerfen("INBOX", 4, "Mail 4")

    abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert sorted(n.uid for n in db.query(Nachricht).all()) == [1, 2, 3, 4]
    assert ordner.hoechste_uid == 4


# --- Wichtigkeit ----------------------------------------------------------- #


def test_wichtigkeit_wird_aus_beiden_kopfzeilen_gedeutet(db, konto):
    """Outlook schreibt ``Importance``, Thunderbird ``X-Priority`` — beide
    Wege muessen bei derselben Stufe ankommen."""
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Outlook hoch", kopfzeilen={"Importance": "high"})
    server.einwerfen("INBOX", 2, "Thunderbird hoch", kopfzeilen={"X-Priority": "1 (Highest)"})
    server.einwerfen("INBOX", 3, "Rundschreiben", kopfzeilen={"X-Priority": "5 (Lowest)"})
    server.einwerfen("INBOX", 4, "Outlook niedrig", kopfzeilen={"Importance": "low"})
    server.einwerfen("INBOX", 5, "Gewoehnlich")

    abgleich.ordner_abgleichen(server, db, konto, _posteingang(db, konto))

    stand = {n.betreff: n.wichtigkeit for n in db.query(Nachricht).all()}
    assert stand == {
        "Outlook hoch": "hoch",
        "Thunderbird hoch": "hoch",
        "Rundschreiben": "niedrig",
        "Outlook niedrig": "niedrig",
        "Gewoehnlich": "normal",
    }


def test_der_bestand_wird_einmal_nachgezogen(db, konto):
    """⚠️ ``wichtigkeit`` kam nach den ersten Abgleichen dazu. Ohne den
    einmaligen Nachzug blieben alle Zeilen von davor auf „normal", waehrend
    identische neue Mails ihr „!" bekamen — fuer immer."""
    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Alt und dringend", kopfzeilen={"Importance": "high"})
    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    # So sieht der Bestand von vor dem Update aus: Spalten-Vorgabe „normal",
    # Merker noch nicht gesetzt.
    db.query(Nachricht).one().wichtigkeit = "normal"
    ordner.wichtigkeit_nachgezogen = False
    db.commit()

    abgleich.ordner_abgleichen(server, db, konto, ordner)
    db.expire_all()

    assert db.query(Nachricht).one().wichtigkeit == "hoch", (
        "Die Bestandszeile blieb auf normal — der Nachzug fehlt."
    )
    assert _posteingang(db, konto).wichtigkeit_nachgezogen is True


def test_normale_prioritaet_und_unsinn_bleiben_normal():
    """⚠️ Eine kaputte Kopfzeile darf keine Mail rot anmalen."""
    from app.services.abgleich import _wichtigkeit_deuten

    assert _wichtigkeit_deuten(b"X-Priority: 3 (Normal)\r\n\r\n") == "normal"
    assert _wichtigkeit_deuten(b"X-Priority: sehr wichtig\r\n\r\n") == "normal"
    assert _wichtigkeit_deuten(b"Importance: dringend\r\n\r\n") == "normal"
    assert _wichtigkeit_deuten(b"") == "normal"
    assert _wichtigkeit_deuten(None) == "normal"


def test_importance_gewinnt_bei_widerspruch():
    """Es sagt woertlich, was gemeint ist — die Zahl braucht eine Deutung."""
    from app.services.abgleich import _wichtigkeit_deuten

    roh = b"Importance: low\r\nX-Priority: 1\r\n\r\n"
    assert _wichtigkeit_deuten(roh) == "niedrig"


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


def test_das_umschlag_datum_behaelt_seine_zeitzone():
    """⚠️ **Der Doppel-Versatz: +02:00 wurde als UTC gestempelt.**

    IMAPClient rechnete ab Werk jedes Datum in die Systemzeit um und gab es
    NAIV zurueck; der Abgleich stempelte UTC darauf, die Oberflaeche rechnete
    wieder in Ortszeit — auf einem +02:00-Rechner stand an jeder Mail 09:52
    statt 07:52. Im UTC-Container hob sich der Fehler zufaellig auf, weshalb
    er erst am 02.09.2026 im Entwicklungsbetrieb auffiel. Seit
    ``normalise_times=False`` kommt das Datum samt Zeitzone; hier steht fest,
    dass es korrekt nach UTC umgerechnet wird.
    """
    from datetime import datetime, timedelta, timezone

    from app.services.abgleich import _datum_aus_umschlag

    plus_zwei = timezone(timedelta(hours=2))
    wert = _datum_aus_umschlag(datetime(2026, 9, 2, 7, 52, 47, tzinfo=plus_zwei))
    assert wert == datetime(2026, 9, 2, 5, 52, 47, tzinfo=timezone.utc), (
        f"07:52+02:00 muss 05:52Z werden, wurde {wert.isoformat()}"
    )

    # Naiv heisst UTC — nie die Zeitzone des nexmail-Rechners raten.
    naiv = _datum_aus_umschlag(datetime(2026, 9, 2, 5, 52, 47))
    assert naiv == datetime(2026, 9, 2, 5, 52, 47, tzinfo=timezone.utc)

    # Ohne Datum: jetzt, damit die Mail oben auffaellt statt zu verschwinden.
    assert _datum_aus_umschlag(None).tzinfo is not None


def test_die_verbindung_laesst_die_zeitzone_am_datum(monkeypatch):
    """Die Verdrahtung zur Umrechnung: ``normalise_times=False`` beim Verbinden.

    ⚠️ Ohne diesen Schalter kommt das Datum bereits NAIV aus der Bibliothek —
    dann rechnet die beste Umrechnung nichts mehr richtig, denn die Zeitzone
    ist zu dem Zeitpunkt schon weggeworfen. Der Test darueber prueft die
    Mathematik, dieser hier, dass sie ueberhaupt etwas zu rechnen bekommt.
    """
    from app.services import imap as imapdienst

    # ⚠️ **Die Attrappe nimmt KEIN **kwargs.** Eine, die alles schluckt,
    # verdeckt genau den Fehler, der hier schon passiert ist: normalise_times
    # als Konstruktor-Argument uebergeben, das der echte Konstruktor nicht
    # kennt - TypeError bei jedem Verbindungsaufbau, und diese Attrappe blieb
    # gruen. Die Signatur hier ist deshalb die der echten Bibliothek.
    class Attrappe:
        def __init__(self, host, port=None, ssl=True, timeout=None):
            self.normalise_times = True  # Werkseinstellung der Bibliothek

        def login(self, *a):
            pass

    monkeypatch.setattr(imapdienst, "IMAPClient", Attrappe)
    klient = imapdienst.verbinden("imap.example.com", 993, "ssl", "wer", "geheim")

    assert klient.normalise_times is False, (
        "Ohne normalise_times=False liefert die Bibliothek naive Ortszeit — "
        "der Doppel-Versatz von +2 Stunden kaeme zurueck."
    )


def test_abgewiesene_zugangsdaten_setzen_die_stoerungsmarke(klient, db, monkeypatch):
    """⚠️ **Ein geaendertes Passwort heilt nie von selbst.**

    Der Takt versuchte es bis zum 02.09.2026 alle zwei Minuten stumm neu —
    wer sein Passwort beim Anbieter aenderte, merkte nur, dass keine Post
    mehr kam. Aufgefallen an einem echten iCloud-Postfach. Die Marke am
    Konto macht daraus den roten Banner.
    """
    import pytest as _pytest

    from app.services import abgleich, anbieter, imap as imapdienst, konten as kontendienst
    from conftest import einrichten
    from test_konten import _eingabe, _guter_befund

    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(kontendienst, "pruefen", lambda daten, wo="", token="": _guter_befund())
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]

    from app.models import Konto

    konto = db.get(Konto, konto_id)

    def abgewiesen(*a, **k):
        raise imapdienst.Verbindungsfehler(
            art=imapdienst.Fehlerart.ANMELDUNG, text="Anmeldung fehlgeschlagen.", roh="AUTHENTICATIONFAILED"
        )

    monkeypatch.setattr(imapdienst, "verbinden", abgewiesen)
    with _pytest.raises(imapdienst.Verbindungsfehler):
        abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    db.refresh(konto)
    assert konto.stoerung == "anmeldung"

    # Und die Oberflaeche bekommt es zu sehen.
    zeile = next(k for k in klient.get("/api/konten").json() if k["id"] == konto_id)
    assert zeile["stoerung"] == "anmeldung"


def test_eine_gelingende_anmeldung_raeumt_die_marke_weg(klient, db, monkeypatch):
    from app.services import abgleich, anbieter, imap as imapdienst, konten as kontendienst
    from conftest import einrichten
    from test_konten import _eingabe, _guter_befund

    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(kontendienst, "pruefen", lambda daten, wo="", token="": _guter_befund())
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]

    from app.models import Konto, Ordner

    konto = db.get(Konto, konto_id)
    konto.stoerung = "anmeldung"
    # Keine abonnierten Ordner: Der Abgleich verbindet nur und legt auf.
    for o in db.query(Ordner).filter(Ordner.konto_id == konto_id):
        o.abonniert = False
    db.commit()

    # ⚠️ Seit dem 18.09.2026 fragt jeder Abgleich nach der Ordnerliste. Diese
    # Attrappe nennt keine; dann bleibt der Bestand, wie er ist (siehe
    # ``test_ordnerliste.py``), und es bleibt bei „verbinden und auflegen".
    attrappe = FalscherServer()
    attrappe.liste_leer = True

    monkeypatch.setattr(imapdienst, "verbinden", lambda *a, **k: attrappe)
    abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    db.refresh(konto)
    assert konto.stoerung == ""


def test_ein_toter_server_loescht_die_marke_nicht(klient, db, monkeypatch):
    """⚠️ Sonst raeumt ein kurzer Netzausfall genau die Meldung weg, die den
    Betreiber zum neuen Passwort fuehren soll."""
    import pytest as _pytest

    from app.services import abgleich, anbieter, imap as imapdienst, konten as kontendienst
    from conftest import einrichten
    from test_konten import _eingabe, _guter_befund

    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(kontendienst, "pruefen", lambda daten, wo="", token="": _guter_befund())
    einrichten(klient)
    konto_id = klient.post("/api/konten", json=_eingabe()).json()["id"]

    from app.models import Konto

    konto = db.get(Konto, konto_id)
    konto.stoerung = "anmeldung"
    db.commit()

    def unerreichbar(*a, **k):
        raise imapdienst.Verbindungsfehler(
            art=imapdienst.Fehlerart.NICHT_ERREICHBAR, text="Der Server antwortet nicht.", roh=""
        )

    monkeypatch.setattr(imapdienst, "verbinden", unerreichbar)
    with _pytest.raises(imapdienst.Verbindungsfehler):
        abgleich.konto_abgleichen(db, konto, nur_posteingang=True)

    db.refresh(konto)
    assert konto.stoerung == "anmeldung", "Ein Netzausfall hat die Anmelde-Stoerung geloescht."


def test_neue_zugangsdaten_raeumen_die_marke_sofort(klient, db, monkeypatch):
    """Der Banner darf nach dem Korrigieren nicht noch zwei Minuten stehen."""
    from app.services import anbieter, konten as kontendienst
    from conftest import einrichten
    from test_konten import _eingabe, _guter_befund

    monkeypatch.setattr(anbieter, "_holen", lambda url: None)
    monkeypatch.setattr(kontendienst, "pruefen", lambda daten, wo="", token="": _guter_befund())
    einrichten(klient)
    eingabe = _eingabe()
    konto_id = klient.post("/api/konten", json=eingabe).json()["id"]

    from app.models import Konto

    db.get(Konto, konto_id).stoerung = "anmeldung"
    db.commit()

    antwort = klient.put(f"/api/konten/{konto_id}", json=eingabe)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["stoerung"] == ""


def test_verwaiste_anhaenge_werden_beim_start_weggeraeumt(db, konto):
    """⚠️ **Geschrieben hat sie jemand, gelöscht bis zum 03.09.2026 niemand.**

    Verwaist eine Datei auf zwei Wegen, und beide passieren nur in der
    Datenbank: Beim Neuholen einer Nachricht räumt `nachricht.anhaenge.clear()`
    die Zeilen weg, beim Löschen einer Nachricht nimmt die Kaskade sie mit.
    Gemessen an `data-dev`: 6 von 13 Dateien ohne Zeile, 91,5 Prozent der Bytes.
    """
    from app.config import get_settings
    from app.models import Anhang

    blobs = get_settings().blob_dir
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / "verwaist").write_bytes(b"gehoert niemandem mehr")
    (blobs / "gebraucht").write_bytes(b"haengt an einer Nachricht")

    server = FalscherServer()
    server.anlegen("INBOX")
    server.einwerfen("INBOX", 1, "Mit Anhang")
    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    nachricht = db.query(Nachricht).one()
    nachricht.anhaenge.append(
        Anhang(teil_id="1", dateiname="a.txt", mime="text/plain", groesse=1, blob_hash="gebraucht")
    )
    db.commit()

    assert abgleich.blobs_aufraeumen(db) == 1

    assert not (blobs / "verwaist").exists(), "Die verwaiste Datei liegt noch da."
    assert (blobs / "gebraucht").exists(), (
        "Eine Datei mit Zeile wurde weggeworfen — das wäre Datenverlust."
    )


def test_der_anhang_kehrer_faellt_ohne_verzeichnis_nicht_um(db):
    """Beim allerersten Start gibt es das Verzeichnis noch gar nicht."""
    import shutil

    from app.config import get_settings

    shutil.rmtree(get_settings().blob_dir, ignore_errors=True)
    assert abgleich.blobs_aufraeumen(db) == 0


def _takt_freigeben(takt) -> None:
    """Die Halt-Marke des Takts zuruecknehmen.

    ⚠️ **Sonst laeuft ``einmal()`` gar nicht erst ueber ein Postfach.**
    ``anhalten()`` setzt ``_halt``, und das passiert am Ende **jedes**
    ``TestClient(app)`` — also in fast jedem Test dieser Reihe. ``starten()``
    raeumt die Marke zwar wieder weg, kehrt bei ``NEXMAIL_TAKT_SEKUNDEN=0``
    aber schon vorher um; und genau so laeuft die Testumgebung.

    Im Betrieb heilt das von selbst: Dort ist der Takt eingeschaltet, und der
    naechste ``starten()`` raeumt die Marke. Hier nicht, und ohne diese Zeile
    ist der Test allein gruen und in der Datei rot — mit einer Meldung, die auf
    den Abgleich zeigt statt auf die Marke.
    """
    takt._halt.clear()  # noqa: SLF001 - genau darum geht es hier

def test_der_takt_meldet_einen_programmfehler_nicht_als_uebersprungen(db, konto, monkeypatch, caplog):
    """⚠️ **Ein abgewiesenes Passwort ist etwas anderes als ein Fehler im Code.**

    Bis zum 03.09.2026 ging beides als INFO mit demselben Satz hinaus:
    ``Background sync skipped <Adresse>: <Fehler>``. In der Protokolldatei
    stand deshalb neun Mal ``module 'app.services.imap' has no attribute
    'ANMELDUNG'`` — ein ``AttributeError``, also ein Fehler im Programm — neben
    139 abgewiesenen Anmeldungen, ohne Rückverfolg und durch nichts davon zu
    unterscheiden.

    ⚠️ **Der Faden darf trotzdem nicht sterben.** Genau dafür wird hier
    gefangen; nur die Stufe und der Rückverfolg ändern sich.
    """
    import logging

    from app.services import takt

    def platzt(*_a, **_k):
        raise AttributeError("module 'app.services.imap' has no attribute 'ANMELDUNG'")

    monkeypatch.setattr(abgleich, "konto_abgleichen", platzt)
    _takt_freigeben(takt)

    with caplog.at_level(logging.INFO, logger="nexmail.takt"):
        stand = takt.einmal()

    assert stand["gescheitert"] == 1, "Der Faden hat den Fehler nicht überlebt."
    meldungen = [e.getMessage() for e in caplog.records]
    assert not any("skipped" in m for m in meldungen), (
        "Ein Programmfehler ging als gewöhnliche Absage durch: " + " | ".join(meldungen)
    )
    unerwartet = [e for e in caplog.records if e.levelno >= logging.ERROR]
    assert unerwartet, "Der Programmfehler steht nicht als Fehler im Protokoll."
    assert unerwartet[0].exc_info is not None, (
        "Ohne Rückverfolg ist nicht zu sehen, wo der Fehler herkommt."
    )


def test_eine_abgewiesene_anmeldung_bleibt_eine_gewoehnliche_absage(db, konto, monkeypatch, caplog):
    """Die Gegenprobe: Der erwartete Fall darf nicht zum Fehler werden.

    Ein falsches Passwort ist ein Betriebszustand. Würde er als ERROR mit
    Rückverfolg hinausgehen, wäre nach einer Woche jedes Protokoll voll damit
    und der echte Fehler darin unsichtbar.
    """
    import logging

    from app.services import imap as imapdienst
    from app.services import takt

    def abgewiesen(*_a, **_k):
        raise imapdienst.Verbindungsfehler(
            imapdienst.Fehlerart.ANMELDUNG, "Benutzername oder Passwort wurde abgewiesen."
        )

    monkeypatch.setattr(abgleich, "konto_abgleichen", abgewiesen)
    _takt_freigeben(takt)

    with caplog.at_level(logging.INFO, logger="nexmail.takt"):
        takt.einmal()

    assert any("skipped" in e.getMessage() for e in caplog.records), (
        "Die erwartete Absage fehlt im Protokoll."
    )
    assert not [e for e in caplog.records if e.levelno >= logging.ERROR], (
        "Ein falsches Passwort ist kein Programmfehler."
    )


# --- Gekappte Suche (Issue #9) -------------------------------------------- #


class GekappterServer(FalscherServer):
    """Ein Server mit Mengengrenze wie in RFC 9738: Jede Suche durchsucht nur
    die ``grenze`` höchsten UIDs ihres Bereichs und sagt nichts davon.

    ``von_unten`` zählt andersherum, für Server, die es so halten.
    ``nachfragen_klemmt`` lässt jede Suche nach einem UID-Bereich scheitern.
    """

    def __init__(self, grenze: int, von_unten: bool = False):
        super().__init__()
        self.grenze = grenze
        self.von_unten = von_unten
        self.nachfragen_klemmt = False
        self.suchen: list[list[str]] = []

    def search(self, kriterien):
        self.suchen.append(list(kriterien))
        alle = sorted(self.ordner[self._aktuell]["nachrichten"])
        if kriterien != ["ALL"]:
            assert kriterien[0] == "UID", kriterien
            if self.nachfragen_klemmt:
                from imapclient.exceptions import IMAPClientError

                raise IMAPClientError("SEARCH failed")
            unten, _, oben = kriterien[1].partition(":")
            hoechste = alle[-1] if alle else 0
            bis = hoechste if oben == "*" else int(oben)
            # ``n:*`` meint auch dann die höchste UID, wenn n darüber liegt.
            von = min(int(unten), hoechste) if oben == "*" else int(unten)
            alle = [u for u in alle if von <= u <= bis]
        return alle[: self.grenze] if self.von_unten else alle[-self.grenze :]


def _gekappt(anzahl: int, grenze: int, **art) -> GekappterServer:
    server = GekappterServer(grenze, **art)
    server.anlegen("INBOX")
    for uid in range(1, anzahl + 1):
        # Lücken wie bei einem echten Ordner, aus dem schon gelöscht wurde.
        server.einwerfen("INBOX", uid * 3, f"Mail {uid}")
    return server


def test_eine_gekappte_suche_holt_trotzdem_den_ganzen_ordner(db, konto):
    """Issue #9: Gmail lieferte von großen Ordnern nur die neuesten 1000 UIDs,
    ohne Fehler. Der Ordner blieb auf genau 1000 stehen."""
    server = _gekappt(25, grenze=10)
    ordner = _posteingang(db, konto)

    runde = abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert server.suchen[0] == ["ALL"]
    assert len(server.suchen) > 1  # Bodenschwelle: die Kappung griff wirklich
    assert db.query(Nachricht).count() == 25
    assert ordner.anzahl == 25
    assert runde.neu == 25


def test_ein_server_der_von_unten_kappt_wird_aufwaerts_gefragt(db, konto):
    server = _gekappt(25, grenze=10, von_unten=True)

    abgleich.ordner_abgleichen(server, db, konto, _posteingang(db, konto))

    assert db.query(Nachricht).count() == 25


def test_eine_vollstaendige_suche_kostet_keine_zweite_frage(db, konto):
    server = _gekappt(25, grenze=1000)

    abgleich.ordner_abgleichen(server, db, konto, _posteingang(db, konto))

    assert server.suchen == [["ALL"]]
    assert db.query(Nachricht).count() == 25


def test_was_in_einer_gekappten_liste_fehlt_wird_nicht_entfernt(db, konto):
    """⚠️ Der eigentliche Schaden aus Issue #9: Jede neue Mail drückte eine alte
    aus der Datenbank, weil sie aus dem Fenster der neuesten 1000 fiel. Lässt
    sich der Rest nicht nachfragen, darf nichts verschwinden."""
    server = _gekappt(25, grenze=1000)
    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    assert db.query(Nachricht).count() == 25

    server.grenze = 10
    server.nachfragen_klemmt = True
    server.einwerfen("INBOX", 1000, "Ganz neu")
    runde = abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert runde.entfernt == 0
    assert runde.neu == 1
    assert db.query(Nachricht).count() == 26


def test_was_wirklich_fehlt_wird_aus_der_vollstaendigen_liste_entfernt(db, konto):
    """Die Gegenprobe: Ist die Liste nach dem Nachfragen vollständig, wird
    Verschwundenes weiterhin entfernt."""
    server = _gekappt(25, grenze=1000)
    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)

    server.grenze = 10
    del server.ordner["INBOX"]["nachrichten"][3]
    runde = abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert runde.entfernt == 1
    assert db.query(Nachricht).count() == 24


def test_ein_haengengebliebener_ordner_holt_die_aeltere_post_nach(db, konto):
    """Wer schon mit gekappter Liste abgeglichen hat, steht mit ``hoechste_uid``
    ganz oben. Die ältere Post muss trotzdem kommen, aber als Nachgeholtes:
    Regeln, Abwesenheitsnotiz und Web Push sehen nur echte Neuankömmlinge."""
    server = _gekappt(25, grenze=10)
    server.nachfragen_klemmt = True
    ordner = _posteingang(db, konto)
    abgleich.ordner_abgleichen(server, db, konto, ordner)
    assert db.query(Nachricht).count() == 10  # der Zustand aus dem Issue
    marke = ordner.hoechste_uid

    server.nachfragen_klemmt = False
    server.einwerfen("INBOX", 1000, "Ganz neu")
    runde = abgleich.ordner_abgleichen(server, db, konto, ordner)

    assert db.query(Nachricht).count() == 26
    assert runde.nachgeholt == 15
    assert runde.neu == 1
    neu = db.get(Nachricht, runde.neue_ids[0])
    assert len(runde.neue_ids) == 1 and neu.uid > marke
