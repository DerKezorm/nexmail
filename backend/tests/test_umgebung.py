"""Läuft der Stapel überhaupt auf dieser Python-Fassung?

⚠️ **Dieser Test ist aus Schaden entstanden.** IMAPClient 3.0.1 lässt sich
unter Python 3.14 nicht einmal verbinden: ``imaplib`` hat ``file`` zu einer
Eigenschaft ohne Setter gemacht, IMAPClient weist dort aber noch zu. Der
Aufbau der Verbindung starb also mit einem ``AttributeError``, **bevor**
irgendeine Anmeldung stattfand — und nexmail meldete „Unerwartete Antwort des
Servers". Der Betreiber sucht den Fehler daraufhin bei seinem Anbieter,
während er im eigenen Haus liegt.

Keiner der übrigen Tests konnte das finden: Sie sprechen alle mit einem
Doppelgänger und rühren die echte Bibliothek nie an. Deshalb dieser hier — er
baut eine Verbindung zu einem Port auf, an dem garantiert nichts lauscht. Was
zurückkommen muss, ist ein **Netzwerkfehler** — welcher genau, ist egal und
hängt am Betriebssystem. Kommt dagegen INTERN oder UNERWARTET zurück, ist die
Bibliothek zerbrochen, bevor sie das Netzwerk erreicht hat.
"""

from __future__ import annotations

import socket

import pytest

from app.services.imap import Fehlerart, Verbindungsfehler, verbinden


def _toter_port() -> int:
    """Ein Port, auf dem sicher niemand antwortet."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_imapclient_passt_zur_python_fassung():
    with pytest.raises(Verbindungsfehler) as fehler:
        verbinden("127.0.0.1", _toter_port(), "ssl", "wer", "auch immer")

    # Welcher Netzwerkfehler es wird, entscheidet das Betriebssystem: Windows
    # weist die Verbindung ab (KEINE_ANTWORT), anderswo laeuft sie in die
    # Zeitgrenze. Beides ist recht. Nur INTERN und UNERWARTET duerfen es nicht
    # sein - die heissen, die Bibliothek ist vor dem Netzwerk zerbrochen.
    assert fehler.value.art not in (Fehlerart.INTERN, Fehlerart.UNERWARTET), (
        "IMAPClient kommt auf dieser Python-Fassung nicht bis zum Netzwerk. "
        f"Gemeldet wurde: {fehler.value.art} - {fehler.value.roh}"
    )


def test_ein_fehler_im_eigenen_haus_wird_nicht_dem_server_angelastet(monkeypatch):
    """Der Auffangfall darf nicht „der Server ist schuld" sagen."""
    import app.services.imap as modul

    def kaputt(*_a, **_k):
        raise AttributeError("property 'file' of 'IMAP4_TLS' object has no setter")

    monkeypatch.setattr(modul, "IMAPClient", kaputt)

    with pytest.raises(Verbindungsfehler) as fehler:
        verbinden("example.invalid", 993, "ssl", "wer", "auch immer")

    assert fehler.value.art == Fehlerart.INTERN
    assert "Server" not in fehler.value.text.split("nicht beim Server")[0]
    assert "nexmail selbst" in fehler.value.text
