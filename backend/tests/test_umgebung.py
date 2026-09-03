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
from datetime import timezone

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


def test_die_zeitzonen_sind_da():
    """⚠️ **Auch dieser Test ist aus Schaden entstanden.**

    Am 02.09.2026 kannte die Entwicklungsumgebung **keine einzige** Zeitzone:
    ``available_timezones()`` gab null zurück, und jede
    ``ZoneInfo("Europe/Berlin")`` scheiterte. Unter Windows bringt Python keine
    Zeitzonendatenbank mit; im Container liegt sie im System.

    nexmail fällt an solchen Stellen still auf UTC zurück. Die Uhrzeit im
    Ausdruck, das Aufräumdatum, der Zeitraum der Abwesenheitsnotiz und die Zeit
    einer Termin-Einladung waren hier damit um Stunden verschoben — und im
    Container richtig. Wer so etwas nicht misst, sucht den Fehler beim Nutzer.

    Behoben durch ``tzdata`` in den Abhängigkeiten. Dieser Test hält es fest.
    """
    from zoneinfo import ZoneInfo, available_timezones

    assert len(available_timezones()) > 100, (
        "Diese Umgebung kennt so gut wie keine Zeitzonen. Ohne sie rechnet "
        "nexmail still in UTC weiter, und jede angezeigte Uhrzeit kann um "
        "Stunden danebenliegen. Fehlt ``tzdata``?"
    )
    # Und die eine, an der es hier hängt, muss wirklich rechnen können.
    from datetime import datetime, timezone

    sommer = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
    assert sommer.astimezone(ZoneInfo("Europe/Berlin")).hour == 10


def test_eine_fehlende_zeitzone_bleibt_nicht_stumm(caplog, monkeypatch):
    """⚠️ **Ausweichen ist erlaubt, schweigen nicht.**

    Am 02.09.2026 wichen drei Stellen still auf UTC aus, als die Zeitzonen
    fehlten — Ausdruck, Abwesenheitszeitraum, Termin-Einladung. Alles um
    Stunden verschoben, und nirgends stand etwas. Wer den Fehler später sucht,
    soll ihn im Protokoll finden statt in der Uhrzeit.
    """
    import logging

    from app.services import zeit

    def kaputt(_name):
        raise KeyError("keine Zeitzonendatenbank")

    monkeypatch.setattr(zeit, "ZoneInfo", kaputt)
    monkeypatch.setattr(zeit, "_gewarnt", set())

    with caplog.at_level(logging.WARNING, logger="nexmail.zeit"):
        gefallen = zeit.zone("Europe/Berlin")

    assert gefallen == timezone.utc
    assert any("Europe/Berlin" in eintrag.message for eintrag in caplog.records), (
        "Der Ausweich auf UTC steht nicht im Protokoll."
    )
    assert any("tzdata" in eintrag.getMessage() for eintrag in caplog.records)


def test_gewarnt_wird_einmal_je_zone(caplog, monkeypatch):
    """Sonst füllt eine Ordnerspalte mit hundert Ordnern das Protokoll."""
    import logging

    from app.services import zeit

    monkeypatch.setattr(zeit, "ZoneInfo", lambda _n: (_ for _ in ()).throw(KeyError()))
    monkeypatch.setattr(zeit, "_gewarnt", set())

    with caplog.at_level(logging.WARNING, logger="nexmail.zeit"):
        for _ in range(5):
            zeit.zone("Europe/Berlin")

    assert len([e for e in caplog.records if "Europe/Berlin" in e.getMessage()]) == 1



def test_die_xml_bremse_haelt():
    """⚠️ **Ohne sie braucht CalDAV ein zusätzliches Paket.**

    Ein CalDAV-Server antwortet mit XML. Der Betreiber trägt ihn zwar selbst
    ein — aber er kann übernommen sein, und dann liest nexmails Container
    dessen Antwort. Drei Angriffe sind die üblichen:

    * **Billion Laughs** — verschachtelte Entitäten, die sich zu Gigabyte
      aufblasen und den Container am Speicher ersticken.
    * **XXE** — eine Entität, die eine lokale Datei einliest.
    * **SSRF über XXE** — eine, die eine Adresse im eigenen Netz abruft.

    Am 02.09.2026 gegen Python 3.14 (Entwicklung) **und** 3.13 im Container
    gemessen: Alle drei werden abgewiesen. Deshalb steht hier ``xml.etree`` und
    kein ``defusedxml``.

    ⚠️ **Die Bremse hängt an der Patch-Fassung**, nicht an 3.13 als solchem.
    Wer das Abbild auf ein älteres Python setzt, soll hier einen roten Lauf
    bekommen und nicht beim Nutzer.
    """
    import xml.etree.ElementTree as ET

    bombe = (
        '<?xml version="1.0"?>\n<!DOCTYPE lolz [\n <!ENTITY lol "lol">\n'
        + "".join(
            f' <!ENTITY lol{i} "{"&lol%d;" % (i - 1) * 10 if i > 1 else "&lol;" * 10}">\n'
            for i in range(1, 8)
        )
        + "]>\n<a>&lol7;</a>"
    )
    # ⚠️ **Auf den GRUND prüfen, nicht auf „irgendein Fehler".** Eine kaputt
    # zusammengebaute Bombe würde auch scheitern — und der Test wäre grün,
    # ohne die Bremse je berührt zu haben.
    with pytest.raises(ET.ParseError) as fehler:
        ET.fromstring(bombe)
    assert "amplification" in str(fehler.value), str(fehler.value)

    with pytest.raises(ET.ParseError):
        ET.fromstring(
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE a [ <!ENTITY x SYSTEM "file:///etc/passwd"> ]>\n<a>&x;</a>'
        )

    # ⚠️ Die Gegenprobe: Echtes CalDAV-XML muss durchgehen. Ohne sie wäre der
    # Test auch dann grün, wenn xml.etree gar nichts mehr läse.
    baum = ET.fromstring(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:"><d:response>'
        "<d:displayname>Privat</d:displayname></d:response></d:multistatus>"
    )
    assert [e.text for e in baum.iter("{DAV:}displayname")] == ["Privat"]
