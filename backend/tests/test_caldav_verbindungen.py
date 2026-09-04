"""Wie viele Verbindungen ein Abgleich aufmacht — und wie ein Name ankommt.

⚠️ **Beides am 03.09.2026 aus dem Betrieb gemeldet, beides an einem echten
iCloud-Konto gemessen.**

Sechs iCloud-Kalender liessen sich finden und verbinden, und danach scheiterte
jeder einzelne Abgleich mit ``caldav_nicht_erreichbar`` — exakt 31 Sekunden
auseinander, also in der Zeitgrenze von 30. Der einzelne Google-Kalender lief
die ganze Zeit durch.

Vier Messungen schlossen Code, Netz und Zeitgrenze aus: dieselben Abfragen
liefen von Hand in 0,3 Sekunden durch, im selben Container, mit denselben
gespeicherten Zugangsdaten. Uebrig blieb die Zahl der Verbindungen. nexmail
baute je Aufruf eine eigene auf: ctag, ETags und ein Block je 50 Termine, macht
bei 429 Terminen in sechs Kalendern **25 TLS-Handschlaege in einem Schwung**.
iCloud laesst je Konto nur eine zu und beantwortet die ueberzaehligen nicht.

⚠️ **Gezaehlt werden Verbindungen, nicht Sekunden.** Eine Zeit ist auf einem
geteilten Rechner keine Zusicherung, und gegen einen Doppelgaenger schon gar
nicht. Die Zahl der aufgebauten Verbindungen ist es.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import caldav

WURZEL = "https://caldav.example.com"
KAL = f"{WURZEL}/dav/anja/kalender/privat/"


class Zaehlend(httpx.BaseTransport):
    """Ein Transport, der mitzaehlt, wie oft er **geoeffnet** wird.

    ⚠️ **`httpx.Client` ruft `close()` beim Verlassen des `with`.** Genau daran
    haengt die Zusicherung: Ein Klient je Aufruf schliesst sechsmal, ein Klient
    je Abgleich einmal. Wer nur Anfragen zaehlt, misst das Falsche — die
    Anfragen bleiben ja gleich viele.
    """

    def __init__(self, antworten) -> None:
        self._antworten = antworten
        self.geschlossen = 0
        self.anfragen: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.anfragen.append(f"{request.method} {request.url.path}")
        return self._antworten(request)

    def close(self) -> None:
        self.geschlossen += 1


def _xml(inhalt: str) -> httpx.Response:
    return httpx.Response(207, content=inhalt.encode("utf-8"))


CTAG = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/">
<d:response><d:href>/dav/anja/kalender/privat/</d:href><d:propstat><d:prop>
<cs:getctag>abc</cs:getctag></d:prop></d:propstat></d:response></d:multistatus>"""


def _etags(anzahl: int) -> str:
    zeilen = "".join(
        f"<d:response><d:href>/dav/anja/kalender/privat/{i}.ics</d:href>"
        f"<d:propstat><d:prop><d:getetag>&quot;e{i}&quot;</d:getetag></d:prop>"
        f"</d:propstat></d:response>"
        for i in range(anzahl)
    )
    return f'<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">{zeilen}</d:multistatus>'


def _inhalte(hrefs: list[str]) -> str:
    zeilen = "".join(
        f"<d:response><d:href>{h}</d:href><d:propstat><d:prop>"
        f"<d:getetag>&quot;e&quot;</d:getetag>"
        f"<c:calendar-data>BEGIN:VCALENDAR\nEND:VCALENDAR</c:calendar-data>"
        f"</d:prop></d:propstat></d:response>"
        for h in hrefs
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        f"{zeilen}</d:multistatus>"
    )


@pytest.fixture
def server():
    def antworten(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return _xml(CTAG)
        if request.method == "REPORT":
            koerper = request.content.decode()
            if "calendar-query" in koerper:
                return _xml(_etags(120))
            hrefs = [z.split("</d:href>")[0] for z in koerper.split("<d:href>")[1:]]
            return _xml(_inhalte(hrefs))
        return httpx.Response(404)

    return Zaehlend(antworten)


def _zugang(server: Zaehlend) -> caldav.Zugang:
    return caldav.Zugang(url=KAL, benutzer="anja", passwort="geheim", transport=server)


def test_ohne_sitzung_macht_jeder_aufruf_eine_eigene_verbindung(server):
    """Der Zustand vor dem 03.09.2026 — als Vergleichsmass, nicht als Wunsch."""
    z = _zugang(server)
    caldav.ctag_holen(z)
    caldav.etags_holen(z)

    assert server.geschlossen == 2


def test_eine_sitzung_traegt_den_ganzen_abgleich(server):
    """⚠️ **Die eigentliche Zusicherung.** 120 Termine sind drei Blöcke zu 50,
    macht mit ctag und ETags fünf Aufrufe — und trotzdem **eine** Verbindung.

    Ohne sie wären es fünf, und iCloud beantwortet ab der zweiten nicht mehr.
    """
    z = _zugang(server)
    with caldav.sitzung(z) as klient:
        caldav.ctag_holen(z, klient)
        fern = caldav.etags_holen(z, klient)
        caldav.inhalte_holen(z, [t.href for t in fern], klient)

    assert len(fern) == 120
    # Fünf Anfragen: ctag, ETags, drei Blöcke.
    assert len(server.anfragen) == 5
    assert server.geschlossen == 1


def test_die_sitzung_bleibt_offen_solange_sie_gereicht_wird(server):
    """Ein übergebener Klient darf von den Funktionen nicht geschlossen werden.

    Sonst wäre die zweite Anfrage im selben Abgleich wieder eine neue
    Verbindung — und der Fehler wäre zurück, ohne dass sich die Zahl der
    Aufrufe ändert.
    """
    z = _zugang(server)
    with caldav.sitzung(z) as klient:
        caldav.ctag_holen(z, klient)
        assert server.geschlossen == 0
        caldav.ctag_holen(z, klient)
        assert server.geschlossen == 0
    assert server.geschlossen == 1


# --------------------------------------------------------------------------- #
# Der doppelt maskierte Name
# --------------------------------------------------------------------------- #

NAMEN = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"
 xmlns:cs="http://calendarserver.org/ns/">
 <d:response><d:href>/dav/anja/kalender/</d:href><d:propstat><d:prop>
   <d:resourcetype><d:collection/></d:resourcetype>
 </d:prop></d:propstat></d:response>
 <d:response><d:href>/dav/anja/kalender/dm/</d:href><d:propstat><d:prop>
   <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
   <d:displayname>D&amp;amp;M</d:displayname>
   <c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>
 </d:prop></d:propstat></d:response>
 <d:response><d:href>/dav/anja/kalender/privat/</d:href><d:propstat><d:prop>
   <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
   <d:displayname>Privater</d:displayname>
   <c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>
 </d:prop></d:propstat></d:response>
</d:multistatus>"""

HEIM = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:response><d:href>/</d:href><d:propstat><d:prop>
<c:calendar-home-set><d:href>/dav/anja/kalender/</d:href></c:calendar-home-set>
</d:prop></d:propstat></d:response></d:multistatus>"""


def test_icloud_maskiert_den_namen_doppelt(monkeypatch):
    """„D&M" kommt als ``D&amp;amp;M`` an und muss als „D&M" ankommen.

    ⚠️ Am 03.09.2026 an einem echten iCloud-Konto gemessen, mit nexmails Code
    **und** mit httpx pur: In beiden Fällen stand ``D&amp;M`` in der Ausgabe.
    Der XML-Leser löst genau eine Ebene auf; iCloud hat zwei geschrieben.
    """
    def antworten(request: httpx.Request) -> httpx.Response:
        if request.headers.get("depth") == "0":
            return _xml(HEIM)
        return _xml(NAMEN)

    z = caldav.Zugang(
        url=WURZEL, benutzer="anja", passwort="geheim",
        transport=httpx.MockTransport(antworten),
    )
    gefunden = {k.name for k in caldav.kalender_finden(z)}

    assert "D&M" in gefunden
    assert "D&amp;M" not in gefunden
    # Ein Name ohne Sonderzeichen bleibt unangetastet.
    assert "Privater" in gefunden


# --------------------------------------------------------------------------- #
# Was die Entmaskierung NICHT anfassen darf
# --------------------------------------------------------------------------- #


def test_termininhalte_bleiben_unangetastet(server):
    """⚠️ **Entmaskiert wird der Anzeigename, nie das ICS.**

    Ein `calendar-data` ist kein HTML. Steht in der Beschreibung eines fremden
    Termins wörtlich ``&amp;`` — etwa weil jemand ein Stück HTML hineinkopiert
    hat —, dann gehört genau das dorthin. Wer die Entmaskierung von
    ``_anzeigename`` auf ``_text`` ausweitet, verändert stillschweigend die
    Inhalte fremder Kalender, und beim Zurückschreiben geht die Änderung
    hinaus.
    """
    def antworten(request: httpx.Request) -> httpx.Response:
        # ⚠️ Im XML steht `&amp;amp;`. Der XML-Leser löst eine Ebene auf, im
        # ICS steht danach wörtlich `&amp;` — und genau das gehört dorthin.
        ics = "BEGIN:VCALENDAR\nSUMMARY:Preis &amp;amp; Menge\nEND:VCALENDAR"
        return _xml(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:response><d:href>/dav/anja/kalender/privat/1.ics</d:href>"
            "<d:propstat><d:prop><d:getetag>&quot;e1&quot;</d:getetag>"
            f"<c:calendar-data>{ics}</c:calendar-data>"
            "</d:prop></d:propstat></d:response></d:multistatus>"
        )

    z = caldav.Zugang(
        url=KAL, benutzer="anja", passwort="geheim",
        transport=httpx.MockTransport(antworten),
    )
    (stueck,) = caldav.inhalte_holen(z, ["/dav/anja/kalender/privat/1.ics"])

    assert "&amp;" in stueck.roh
    assert "Preis &amp; Menge" in stueck.roh


# --------------------------------------------------------------------------- #
# Und dasselbe eine Ebene höher: der Abgleich als Ganzes
# --------------------------------------------------------------------------- #


def test_ein_ganzer_abgleich_macht_eine_verbindung(klient, db, monkeypatch):
    """⚠️ **Der Test, an dem der gemeldete Fehler wirklich hängt.**

    Die Zusicherungen weiter oben prüfen die Bausteine. Diese hier prüft, dass
    `_caldav_abgleichen` sie auch benutzt: Ohne die gemeinsame Sitzung öffnet
    ein Abgleich mit 120 Terminen fünf Verbindungen statt einer, und iCloud
    beantwortet ab der zweiten nicht mehr. Genau so kamen am 03.09.2026 sechs
    Kalender reihum als `caldav_nicht_erreichbar` zurück.
    """
    from app.models import Benutzer, Kalender
    from app.services import kalenderabgleich
    from conftest import einrichten

    einrichten(klient)
    person = db.query(Benutzer).one()

    def antworten(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return _xml(CTAG)
        koerper = request.content.decode()
        if "calendar-query" in koerper:
            return _xml(_etags(120))
        hrefs = [z.split("</d:href>")[0] for z in koerper.split("<d:href>")[1:]]
        return _xml(_inhalte(hrefs))

    server = Zaehlend(antworten)

    kalender = Kalender(
        benutzer_id=person.id, name="Familie", farbe=3, art="caldav",
        herkunft="iCloud", url=KAL, benutzer_name="anja",
    )
    db.add(kalender)
    db.flush()
    kalenderabgleich.passwort_schreiben(kalender, "geheim")
    db.commit()

    echt = kalenderabgleich.zugang

    def mit_transport(k, sitzung=None):
        z = echt(k, sitzung)
        z.transport = server
        return z

    monkeypatch.setattr(kalenderabgleich, "zugang", mit_transport)
    kalenderabgleich._caldav_abgleichen(db, kalender)

    # ctag, ETags und drei Blöcke zu 50 — fünf Anfragen, eine Verbindung.
    assert len(server.anfragen) == 5
    assert server.geschlossen == 1


# --------------------------------------------------------------------------- #
# Die Sammlung, die sich als Termin ausgibt
# --------------------------------------------------------------------------- #

#: ⚠️ **Wörtlich die Form, die iCloud liefert** — am 03.09.2026 an einem echten
#: Konto mitgeschnitten. Kein Präfix, Standard-Namensraum am `multistatus`, und
#: die **erste** `<response>` ist der Kalender selbst. Mit eigenem ETag: Sie ist
#: von einem Termin nicht zu unterscheiden, wenn man nur auf das ETag sieht.
ICLOUD_ETAGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<multistatus xmlns="DAV:">
  <response>
    <href>/222435680/calendars/435E/</href>
    <propstat><prop><getetag xmlns="DAV:">"ldoxvn76"</getetag></prop>
    <status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/222435680/calendars/435E/00653928.ics</href>
    <propstat><prop><getetag xmlns="DAV:">"lu14jj4h"</getetag></prop>
    <status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/222435680/calendars/435E/01A9FC88.ics</href>
    <propstat><prop><getetag xmlns="DAV:">"abc123"</getetag></prop>
    <status>HTTP/1.1 200 OK</status></propstat>
  </response>
</multistatus>"""


def test_die_sammlung_zaehlt_nicht_als_termin():
    """⚠️ **Der gemeldete Fehler, an seiner Wurzel.**

    iCloud liefert bei `Depth: 1` als erste `<response>` den Kalender selbst,
    samt eigenem ETag. Wer sie mitnimmt, fragt beim nächsten Schritt per
    `calendar-multiget` nach einem Kalender, als wäre er ein Termin — und
    **darauf antwortet iCloud gar nicht.** Kein 404, keine Absage, Stille bis
    in die Zeitgrenze von dreißig Sekunden.

    Es traf jede Runde, deshalb heilte es nie von selbst. Google fällt nicht
    auf, weil es die Sammlung nicht mitschickt; deshalb lief dort der einzige
    Google-Kalender durch, während alle sechs iCloud-Kalender hingen.
    """
    def antworten(request: httpx.Request) -> httpx.Response:
        return httpx.Response(207, content=ICLOUD_ETAGS.encode("utf-8"))

    z = caldav.Zugang(
        url="https://p142-caldav.example.com/222435680/calendars/435E/",
        benutzer="anja", passwort="geheim",
        transport=httpx.MockTransport(antworten),
    )
    fern = caldav.etags_holen(z)

    assert len(fern) == 2
    assert all(t.href.endswith(".ics") for t in fern)


def test_die_sammlung_faellt_auch_ohne_schraegstrich_weg():
    """⚠️ Verglichen wird über `ortsschluessel`, nicht wörtlich.

    Manche Server antworten mit absoluter Adresse, andere mit dem Pfad; der
    abschließende Schrägstrich ist nicht verlässlich. Ein wörtlicher Vergleich
    ließe die Sammlung genau dann durch, wenn ein Server sie anders schreibt
    als in der eigenen Adresse.
    """
    ohne = ICLOUD_ETAGS.replace(
        "<href>/222435680/calendars/435E/</href>",
        "<href>https://p142-caldav.example.com/222435680/calendars/435E</href>",
    )

    def antworten(request: httpx.Request) -> httpx.Response:
        return httpx.Response(207, content=ohne.encode("utf-8"))

    z = caldav.Zugang(
        url="https://p142-caldav.example.com/222435680/calendars/435E/",
        benutzer="anja", passwort="geheim",
        transport=httpx.MockTransport(antworten),
    )

    assert len(caldav.etags_holen(z)) == 2
