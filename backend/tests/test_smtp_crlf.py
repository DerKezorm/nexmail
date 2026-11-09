"""Zeilenenden beim Senden (Issue #20).

Strato und andere strenge Server weisen eine Mail mit blossem LF ab:
``554 5.6.0 SMTP protocol violation: A header line must be terminated by
CRLF``. ``bauen`` liefert LF, und ``smtplib.sendmail`` reicht Bytes
unverändert durch. Bis 0.29.0 ging deshalb jede Mail mit LF hinaus.

⚠️ **Hier spricht das echte ``smtplib`` mit einem echten Socket.** Eine
Leitung, die ``sendmail`` nur mitschreibt, sähe nicht, was ``smtplib`` aus den
Bytes macht, und genau dort lag die Annahme, die nicht stimmte.
"""

from __future__ import annotations

import smtplib
import socket
import threading
from email import message_from_bytes
from types import SimpleNamespace

import pytest

from app.services import senden
from test_verfassen import _entwurf


class StrengerServer:
    """Ein SMTP-Server, der wie Strato jedes blosse LF in DATA abweist."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.daten: bytes | None = None
        self.abgewiesen = False
        self.faden = threading.Thread(target=self._bedienen, daemon=True)
        self.faden.start()

    def _bedienen(self) -> None:
        verbindung, _ = self.sock.accept()
        with verbindung:
            datei = verbindung.makefile("rb")

            def antworten(zeile: str) -> None:
                verbindung.sendall(zeile.encode("ascii") + b"\r\n")

            antworten("220 strict.test ESMTP")
            while True:
                zeile = datei.readline()
                if not zeile:
                    return
                befehl = zeile.strip().upper()
                if befehl.startswith((b"EHLO", b"HELO")):
                    antworten("250 strict.test")
                elif befehl.startswith((b"MAIL", b"RCPT")):
                    antworten("250 OK")
                elif befehl == b"DATA":
                    antworten("354 go ahead")
                    teile = []
                    while True:
                        stueck = datei.readline()
                        if stueck in (b".\r\n", b".\n", b""):
                            break
                        teile.append(stueck)
                    self.daten = b"".join(teile)
                    zeilen = self.daten.split(b"\n")[:-1]
                    if any(not z.endswith(b"\r") for z in zeilen):
                        self.abgewiesen = True
                        antworten(
                            "554 5.6.0 SMTP protocol violation: "
                            "A header line must be terminated by CRLF"
                        )
                    else:
                        antworten("250 queued")
                elif befehl == b"QUIT":
                    antworten("221 bye")
                    return
                else:
                    antworten("250 OK")


@pytest.fixture
def server(monkeypatch):
    strenger = StrengerServer()

    class OhneTls(smtplib.SMTP):
        """Dieselbe Bibliothek, nur ohne TLS und Anmeldung zum Prüfserver."""

        def __init__(self, host, port, timeout=None):  # noqa: ARG002
            super().__init__("127.0.0.1", strenger.port, timeout=timeout)

        def starttls(self, *a, **k):  # noqa: ARG002
            return (220, b"ready")

        def login(self, *a, **k):  # noqa: ARG002
            return (235, b"ok")

    monkeypatch.setattr(senden.smtplib, "SMTP", OhneTls)
    yield strenger
    strenger.sock.close()


def _konto():
    return SimpleNamespace(
        adresse="anna@example.com",
        smtp_server="smtp.example",
        smtp_port=587,
        smtp_sicherheit="starttls",
        smtp_benutzer="anna@example.com",
    )


def test_eine_gebaute_mail_geht_mit_crlf_hinaus(server):
    roh, _ = senden.bauen(
        _entwurf(von_adresse="anna@example.com", text="Erste Zeile\nZweite Zeile")
    )
    assert b"\n" in roh.replace(b"\r\n", b"")  # Voraussetzung: bauen liefert LF

    senden._smtp_senden(_konto(), "geheim", ["anja@example.org"], roh)

    assert not server.abgewiesen
    assert server.daten is not None
    assert b"\n" not in server.daten.replace(b"\r\n", b"")
    hinaus = message_from_bytes(server.daten)
    assert hinaus["Subject"] == "Wochenende"
    assert hinaus["To"] == "anja@example.org"


def test_eine_alte_datei_aus_der_warteschlange_geht_auch(server):
    """Was vor dem Update eingereiht wurde, liegt mit LF auf der Platte."""
    roh = (
        b"From: anna@example.com\nTo: anja@example.org\n"
        b"Subject: Alt\n\nZeile eins\nZeile zwei\n"
    )

    senden._smtp_senden(_konto(), "geheim", ["anja@example.org"], roh)

    assert not server.abgewiesen
    assert server.daten == (
        b"From: anna@example.com\r\nTo: anja@example.org\r\n"
        b"Subject: Alt\r\n\r\nZeile eins\r\nZeile zwei\r\n"
    )


def test_ohne_umwandlung_weist_der_strenge_server_ab(server):
    """Gegenprobe: Der Prüfserver erkennt den Fehler aus Issue #20 wirklich."""
    verbindung = smtplib.SMTP("127.0.0.1", server.port, timeout=10)
    with pytest.raises(smtplib.SMTPDataError) as fehler:
        verbindung.sendmail("anna@example.com", ["anja@example.org"], b"Subject: x\n\ny\n")
    verbindung.quit()
    assert fehler.value.smtp_code == 554
    assert server.abgewiesen


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        (b"a\nb\n", b"a\r\nb\r\n"),
        (b"a\r\nb\r\n", b"a\r\nb\r\n"),  # schon richtig: nichts verdoppelt
        (b"a\r\nb\nc\rd", b"a\r\nb\r\nc\r\nd"),  # gemischt, blosses CR
        (b"a\r\r\nb", b"a\r\n\r\nb"),
        (b"", b""),
    ],
)
def test_mit_crlf(roh, erwartet):
    assert senden.mit_crlf(roh) == erwartet
    assert senden.mit_crlf(erwartet) == erwartet
