"""Der CalDAV-Client — gegen einen falschen Server.

⚠️ **Der teuerste Fehler hier ist der stille Überschreiber.** Wer ohne
``If-Match`` schreibt, löscht die Änderung vom Telefon, und niemand erfährt
davon. Deshalb prüft die halbe Datei, was in den Kopfzeilen steht.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import caldav

WURZEL = "https://caldav.example.com"
HEIM = f"{WURZEL}/dav/anja/kalender/"
PRIVAT = f"{HEIM}privat/"


def _xml(inhalt: str) -> httpx.Response:
    return httpx.Response(207, content=inhalt.encode("utf-8"))


PRINCIPAL_ANTWORT = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:"><d:response><d:href>/</d:href><d:propstat><d:prop>
<d:current-user-principal><d:href>/dav/anja/</d:href></d:current-user-principal>
</d:prop></d:propstat></d:response></d:multistatus>"""

HEIM_ANTWORT = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:response><d:href>/dav/anja/</d:href><d:propstat><d:prop>
<c:calendar-home-set><d:href>/dav/anja/kalender/</d:href></c:calendar-home-set>
</d:prop></d:propstat></d:response></d:multistatus>"""

KALENDER_ANTWORT = """<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"
 xmlns:cs="http://calendarserver.org/ns/" xmlns:a="http://apple.com/ns/ical/">
 <d:response><d:href>/dav/anja/kalender/</d:href><d:propstat><d:prop>
   <d:resourcetype><d:collection/></d:resourcetype>
 </d:prop></d:propstat></d:response>
 <d:response><d:href>/dav/anja/kalender/privat/</d:href><d:propstat><d:prop>
   <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
   <d:displayname>Privat</d:displayname>
   <cs:getctag>ctag-1</cs:getctag>
   <a:calendar-color>#FF2968</a:calendar-color>
   <c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>
 </d:prop></d:propstat></d:response>
 <d:response><d:href>/dav/anja/kalender/aufgaben/</d:href><d:propstat><d:prop>
   <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
   <d:displayname>Erinnerungen</d:displayname>
   <c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>
 </d:prop></d:propstat></d:response>
</d:multistatus>"""


class Server:
    """Ein CalDAV-Server, den man steuern kann."""

    def __init__(self):
        self.termine: dict[str, tuple[str, str]] = {}  # href -> (etag, ics)
        self.anfragen: list[tuple[str, str, dict]] = []
        self.principal_unter_wurzel = True
        self.etag_zurueck = True
        #: Meldet der Server den Pfad prozentkodiert zurueck? Google tut es.
        self.kodiert_zurueck = False
        self.ctag = "ctag-1"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._antworten)

    def _antworten(self, anfrage: httpx.Request) -> httpx.Response:
        pfad = anfrage.url.path
        self.anfragen.append((anfrage.method, pfad, dict(anfrage.headers)))

        if anfrage.method == "PROPFIND":
            rumpf = anfrage.content.decode()
            if "current-user-principal" in rumpf:
                if pfad == "/.well-known/caldav" and self.principal_unter_wurzel:
                    return httpx.Response(404)
                if pfad != "/.well-known/caldav" and not self.principal_unter_wurzel:
                    return httpx.Response(404)
                return _xml(PRINCIPAL_ANTWORT)
            if "calendar-home-set" in rumpf:
                return _xml(HEIM_ANTWORT)
            if anfrage.headers.get("depth") == "0":
                return _xml(
                    KALENDER_ANTWORT.replace("ctag-1", self.ctag)
                )
            return _xml(KALENDER_ANTWORT.replace("ctag-1", self.ctag))

        if anfrage.method == "REPORT":
            rumpf = anfrage.content.decode()
            if "calendar-multiget" in rumpf:
                zeilen = []
                for href, (etag, ics) in self.termine.items():
                    if f"<d:href>{href}</d:href>" in rumpf:
                        zeilen.append(
                            f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>'
                            f'<d:getetag>"{etag}"</d:getetag>'
                            f"<c:calendar-data>{ics}</c:calendar-data>"
                            f"</d:prop></d:propstat></d:response>"
                        )
                return _xml(
                    '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
                    'xmlns:c="urn:ietf:params:xml:ns:caldav">' + "".join(zeilen) + "</d:multistatus>"
                )
            zeilen = [
                f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>'
                f'<d:getetag>"{etag}"</d:getetag></d:prop></d:propstat></d:response>'
                for href, (etag, _) in self.termine.items()
            ]
            return _xml(
                '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
                + "".join(zeilen)
                + "</d:multistatus>"
            )

        if anfrage.method == "PUT":
            # ⚠️ **Wie Google: Der Server meldet den Termin danach mit
            # prozentkodiertem Pfad zurueck.** Ein ``@`` im Dateinamen wird zu
            # ``%40``; woertlich verglichen sind das zwei Adressen.
            if self.kodiert_zurueck:
                pfad = pfad.replace("@", "%40")
            vorhanden = self.termine.get(pfad)
            wenn = anfrage.headers.get("if-match")
            wenn_nicht = anfrage.headers.get("if-none-match")
            if vorhanden and wenn and wenn.strip('"') != vorhanden[0]:
                return httpx.Response(412)
            if vorhanden and wenn_nicht == "*":
                return httpx.Response(412)
            neu = f"etag-{len(self.anfragen)}"
            self.termine[pfad] = (neu, anfrage.content.decode())
            kopf = {"etag": f'"{neu}"'} if self.etag_zurueck else {}
            return httpx.Response(201 if not vorhanden else 204, headers=kopf)

        if anfrage.method == "DELETE":
            vorhanden = self.termine.get(pfad)
            wenn = anfrage.headers.get("if-match")
            if vorhanden and wenn and wenn.strip('"') != vorhanden[0]:
                return httpx.Response(412)
            self.termine.pop(pfad, None)
            return httpx.Response(204)

        return httpx.Response(405)


@pytest.fixture
def server():
    return Server()


def _zugang(server: Server, url: str = WURZEL) -> caldav.Zugang:
    return caldav.Zugang(url=url, benutzer="anja", passwort="geheim", transport=server.transport())


# --- Finden --------------------------------------------------------------- #


def test_die_kalender_werden_gefunden(server):
    raus = caldav.kalender_finden(_zugang(server))
    assert [k.name for k in raus] == ["Privat"]
    assert raus[0].url == PRIVAT
    assert raus[0].ctag == "ctag-1"
    assert raus[0].farbe == "#FF2968"


def test_eine_aufgabenliste_ist_kein_kalender(server):
    """⚠️ Unter demselben Zugang liegen auch ``VTODO``-Sammlungen. Sie als
    leere Kalender anzuzeigen wäre eine Falschaussage."""
    namen = [k.name for k in caldav.kalender_finden(_zugang(server))]
    assert "Erinnerungen" not in namen


#: Wie Google auf die erste Frage antwortet: die Kalenderadresse steht schon
#: da, ``current-user-principal`` meldet **404 im propstat**. Wörtlich
#: abgeschrieben von ``apidata.googleusercontent.com`` am 03.09.2026.
HEIM_TEIL = """
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><caldav:calendar-home-set>
     <D:href>/dav/anja/kalender/</D:href>
   </caldav:calendar-home-set></D:prop>
  </D:propstat>"""

GOOGLE_ANTWORT = """<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
 <D:response>
  <D:href>/caldav/v2/anja%40example.com/user</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 404 Not Found</D:status>
   <D:prop><D:current-user-principal/></D:prop>
  </D:propstat>
""" + HEIM_TEIL + """
 </D:response>
</D:multistatus>"""


def test_ein_server_ohne_principal_wird_trotzdem_gefunden():
    """⚠️ **Google beantwortet „wer bin ich" gar nicht.**

    Es meldet ``current-user-principal`` mit 404 im ``propstat`` und liefert
    die Kalenderadresse gleich mit. Der vorgeschriebene Weg — erst Principal,
    dann Heim — endete dort in „kein Kalender-Server", obwohl der Kalender
    einen Schritt weiter lag. Am 03.09.2026 an einem echten Konto gemessen;
    die Antwort unten ist wörtlich seine.
    """
    runden: list[str] = []

    def antworten(anfrage: httpx.Request) -> httpx.Response:
        runden.append(anfrage.url.path)
        rumpf = anfrage.content.decode()
        if "current-user-principal" in rumpf:
            # ⚠️ **Ein Server liefert nur, wonach gefragt wurde.** Die Antwort
            # unabhaengig vom Rumpf zu geben machte die Mutationsprobe hohl:
            # Wer das ``calendar-home-set`` aus der Anfrage entfernt, bekaeme
            # es trotzdem, und der Test bliebe gruen.
            if "calendar-home-set" not in rumpf:
                return _xml(GOOGLE_ANTWORT.replace(HEIM_TEIL, ""))
            return _xml(GOOGLE_ANTWORT)
        return _xml(KALENDER_ANTWORT)

    zugang = caldav.Zugang(
        WURZEL, "anja", "", token="tok", transport=httpx.MockTransport(antworten)
    )
    raus = caldav.kalender_finden(zugang)

    assert [k.name for k in raus] == ["Privat"]
    # ⚠️ **Und keine Runde zu viel.** Steht die Kalenderadresse schon in der
    # ersten Antwort, ist die zweite Frage beantwortet, bevor sie gestellt
    # wurde — bei Google liefe sie ohnehin ins Leere.
    assert len(runden) == 2


def test_auch_ueber_well_known(server):
    """⚠️ Manche Server antworten nur dort — beides zu versuchen ist billiger
    als zu raten."""
    server.principal_unter_wurzel = False
    raus = caldav.kalender_finden(_zugang(server))
    assert [k.name for k in raus] == ["Privat"]
    assert any(pfad == "/.well-known/caldav" for _, pfad, _ in server.anfragen)


def test_falsche_zugangsdaten_werden_benannt(server):
    def abweisen(anfrage):
        return httpx.Response(401)

    zugang = caldav.Zugang(WURZEL, "anja", "falsch", transport=httpx.MockTransport(abweisen))
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.kalender_finden(zugang)
    assert str(f.value) == "caldav_abgewiesen"


def test_kein_kalenderserver(server):
    def nichts(anfrage):
        return httpx.Response(200, content=b"<html>Hallo</html>")

    zugang = caldav.Zugang(WURZEL, "anja", "x", transport=httpx.MockTransport(nichts))
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.kalender_finden(zugang)
    assert str(f.value) == "caldav_kein_kalenderserver"


def test_das_eigene_netz_bleibt_zu():
    """⚠️ Sonst wäre nexmail eine Fernbedienung fürs Heimnetz — dieselbe
    Prüfung wie beim Bildvermittler."""
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.kalender_finden(caldav.Zugang("https://10.0.0.5/dav/", "a", "b"))
    assert str(f.value) == "caldav_adresse_im_eigenen_netz"


def test_eine_unlesbare_antwort_wird_benannt():
    def muell(anfrage):
        return httpx.Response(207, content=b"<das ist kein XML")

    zugang = caldav.Zugang(WURZEL, "a", "b", transport=httpx.MockTransport(muell))
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.kalender_finden(zugang)
    assert str(f.value) == "caldav_antwort_unlesbar"


# --- Holen ---------------------------------------------------------------- #


def test_erst_die_kennungen_dann_die_inhalte(server):
    """⚠️ Ein Kalender mit fünftausend Terminen wäre sonst bei jedem Abgleich
    ein Download von Megabyte."""
    server.termine["/dav/anja/kalender/privat/a.ics"] = ("e1", "BEGIN:VCALENDAR")
    server.termine["/dav/anja/kalender/privat/b.ics"] = ("e2", "BEGIN:VCALENDAR")

    zugang = _zugang(server, PRIVAT)
    kennungen = caldav.etags_holen(zugang)
    assert {t.etag for t in kennungen} == {"e1", "e2"}
    assert all(t.roh == "" for t in kennungen)

    inhalte = caldav.inhalte_holen(zugang, [kennungen[0].href])
    assert len(inhalte) == 1
    assert inhalte[0].roh.startswith("BEGIN:VCALENDAR")


def test_blockweise_holen(server, monkeypatch):
    monkeypatch.setattr(caldav, "BLOCK", 2)
    for i in range(5):
        server.termine[f"/dav/anja/kalender/privat/{i}.ics"] = (f"e{i}", "BEGIN:VCALENDAR")
    zugang = _zugang(server, PRIVAT)

    server.anfragen.clear()
    caldav.inhalte_holen(zugang, [t.href for t in caldav.etags_holen(zugang)])

    multiget = [a for a in server.anfragen if a[0] == "REPORT" and "multiget" in str(a)]
    assert len([a for a in server.anfragen if a[0] == "REPORT"]) == 4  # 1 etags + 3 Bloecke


def test_der_deckel_greift(server, monkeypatch):
    monkeypatch.setattr(caldav, "MAX_TERMINE", 3)
    for i in range(10):
        server.termine[f"/dav/anja/kalender/privat/{i}.ics"] = (f"e{i}", "X")
    assert len(caldav.etags_holen(_zugang(server, PRIVAT))) == 3


# --- Schreiben: der Konfliktschutz ---------------------------------------- #


def test_ein_neuer_termin_faehrt_mit_if_none_match(server):
    """⚠️ Sonst überschreibt ein zweiter Anlauf einen Termin, den jemand
    gerade unter derselben Adresse angelegt hat."""
    href = f"{PRIVAT}neu.ics"
    caldav.schreiben(_zugang(server, PRIVAT), href, "BEGIN:VCALENDAR")

    put = [a for a in server.anfragen if a[0] == "PUT"][-1]
    assert put[2].get("if-none-match") == "*"
    assert "if-match" not in put[2]


def test_ein_bekannter_termin_faehrt_mit_if_match(server):
    href = "/dav/anja/kalender/privat/a.ics"
    server.termine[href] = ("e1", "alt")

    caldav.schreiben(_zugang(server, PRIVAT), f"{WURZEL}{href}", "neu", etag="e1")

    put = [a for a in server.anfragen if a[0] == "PUT"][-1]
    assert put[2].get("if-match") == '"e1"'
    assert server.termine[href][1] == "neu"


def test_ein_konflikt_ueberschreibt_NICHT(server):
    """⚠️ **Der Test, um den es geht.** Jemand hat denselben Termin am Telefon
    geändert — nexmail darf ihn nicht überbügeln."""
    href = "/dav/anja/kalender/privat/a.ics"
    server.termine[href] = ("neuer-etag", "die Fassung vom Telefon")

    with pytest.raises(caldav.Konflikt):
        caldav.schreiben(_zugang(server, PRIVAT), f"{WURZEL}{href}", "meine", etag="alter-etag")

    assert server.termine[href][1] == "die Fassung vom Telefon"


def test_ohne_etag_in_der_antwort_wird_nachgeschlagen(server):
    """⚠️ Nicht jeder Server schickt eines zurück. Ohne Nachschlagen führe der
    nächste Schreibvorgang mit einem veralteten ``If-Match`` in einen Konflikt,
    den es gar nicht gibt."""
    server.etag_zurueck = False
    href = f"{PRIVAT}neu.ics"

    etag = caldav.schreiben(_zugang(server, PRIVAT), href, "BEGIN:VCALENDAR")

    assert etag
    assert etag == server.termine["/dav/anja/kalender/privat/neu.ics"][0]


def test_loeschen_faehrt_auch_mit_if_match(server):
    href = "/dav/anja/kalender/privat/a.ics"
    server.termine[href] = ("e1", "x")

    caldav.loeschen(_zugang(server, PRIVAT), f"{WURZEL}{href}", etag="e1")

    assert href not in server.termine


def test_loeschen_bei_konflikt_bricht_ab(server):
    href = "/dav/anja/kalender/privat/a.ics"
    server.termine[href] = ("neu", "x")
    with pytest.raises(caldav.Konflikt):
        caldav.loeschen(_zugang(server, PRIVAT), f"{WURZEL}{href}", etag="alt")
    assert href in server.termine


def test_ein_schon_geloeschter_termin_ist_kein_fehler(server):
    """Er sollte weg sein, und er ist es."""

    def weg(anfrage):
        return httpx.Response(404)

    zugang = caldav.Zugang(PRIVAT, "a", "b", transport=httpx.MockTransport(weg))
    caldav.loeschen(zugang, f"{PRIVAT}a.ics", etag="e1")


# --- ctag ----------------------------------------------------------------- #


def test_das_ctag_sagt_ob_sich_etwas_getan_hat(server):
    zugang = _zugang(server, PRIVAT)
    assert caldav.ctag_holen(zugang) == "ctag-1"
    server.ctag = "ctag-2"
    assert caldav.ctag_holen(zugang) == "ctag-2"


# --- ICS-Abo -------------------------------------------------------------- #


def _abo(inhalt: bytes, gesehen: list[str] | None = None):
    def antworten(anfrage):
        if gesehen is not None:
            gesehen.append(str(anfrage.url))
        return httpx.Response(200, content=inhalt)

    return httpx.MockTransport(antworten)


ABO_ICS = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR"


def test_ein_abo_wird_geholt():
    abo = caldav.abo_holen("https://calendar.example.com/f.ics", transport=_abo(ABO_ICS))
    assert abo.roh.startswith("BEGIN:VCALENDAR")
    assert not abo.unveraendert


def test_ein_riesiges_abo_wird_abgewiesen(monkeypatch):
    """⚠️ Ein Feiertagskalender hat Kilobyte. Wer eine Gigabyte-Datei
    verlinkt, soll den Container nicht umbringen."""
    monkeypatch.setattr(caldav, "MAX_ABO_BYTES", 100)
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.abo_holen("https://calendar.example.com/f.ics", transport=_abo(b"X" * 5000))
    assert str(f.value) == "abo_zu_gross"


def test_webcal_wird_zu_https():
    gesehen: list[str] = []
    caldav.abo_holen("webcal://calendar.example.com/f.ics", transport=_abo(ABO_ICS, gesehen))
    assert gesehen[0].startswith("https://")


def test_ein_abo_im_eigenen_netz_wird_abgewiesen():
    """Ohne Transport greift die Prüfung — wie im Betrieb."""
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.abo_holen("https://10.0.0.5/f.ics")
    assert str(f.value) == "caldav_adresse_im_eigenen_netz"


# --- Prozentkodierte Adressen --------------------------------------------- #


def test_ein_kodierter_pfad_meint_denselben_termin():
    """⚠️ **Google nimmt ``…/<uid>@nexmail.ics`` an und meldet
    ``…/<uid>%40nexmail.ics``.**

    Wörtlich verglichen ist das ein unbekannter Eintrag **und** eine
    verschwundene Zeile: Der Abgleich legte den Termin neu an und löschte den
    eigenen — bei jeder Runde. Am 03.09.2026 an einem echten Google-Kalender
    gemessen.
    """
    roh = "https://apidata.example.com/caldav/v2/a%40example.com/events/x@nexmail.ics"
    kodiert = "https://apidata.example.com/caldav/v2/a%40example.com/events/x%40nexmail.ics"

    assert caldav.ortsschluessel(roh) == caldav.ortsschluessel(kodiert)
    # Der Host gehört nicht dazu: Manche Server antworten mit absoluter
    # Adresse, andere nur mit dem Pfad.
    assert caldav.ortsschluessel(kodiert) == caldav.ortsschluessel(
        "/caldav/v2/a@example.com/events/x@nexmail.ics"
    )


def test_das_etag_wird_auch_bei_kodiertem_pfad_gefunden(server):
    """⚠️ **Google schickt zum ``PUT`` gar kein ETag** — gemessen: 201, kein
    Kopf. Nachgeschlagen wird es über die Liste, und dort steht der Pfad
    kodiert. Ohne Normierung bliebe das ETag leer, und der nächste
    Schreibvorgang führe ohne ``If-Match`` los."""
    server.etag_zurueck = False
    server.kodiert_zurueck = True
    href = f"{PRIVAT}x@nexmail.ics"

    etag = caldav.schreiben(_zugang(server, PRIVAT), href, "BEGIN:VCALENDAR")

    assert etag
    assert etag == server.termine["/dav/anja/kalender/privat/x%40nexmail.ics"][0]


# --- Anmeldung: Basic, notfalls Digest ------------------------------------ #


def test_ein_server_der_nur_digest_kann_wird_bedient():
    """⚠️ **Nicht jeder CalDAV-Server nimmt Basic.**

    All-Inkl antwortet auf seinem Kalender-Endpunkt mit
    ``WWW-Authenticate: Digest realm="NMMDav"`` und bietet Basic gar nicht an —
    am 03.09.2026 gegen ``webmail.all-inkl.com`` gemessen. Ein Client, der nur
    Basic kann, bekommt dort ein 401 und meldet „abgewiesen": dieselbe Meldung
    wie bei einem falschen Passwort, und der Betreiber tippt es zehnmal neu.
    """
    koepfe: list[str] = []

    def nur_digest(anfrage: httpx.Request) -> httpx.Response:
        kopf = anfrage.headers.get("authorization", "")
        koepfe.append(kopf.split(" ")[0] if kopf else "-")
        if not kopf.lower().startswith("digest "):
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Digest realm="NMMDav",qop="auth",'
                    'nonce="abc",opaque="def"'
                },
            )
        return _xml(PRINCIPAL_ANTWORT)

    zugang = caldav.Zugang(WURZEL, "anja", "geheim", transport=httpx.MockTransport(nur_digest))
    with caldav._klient(zugang) as klient:
        antwort = caldav._propfind(klient, WURZEL, caldav._PRINCIPAL, "0")

    assert antwort is not None
    # Erst Basic, dann Digest — und danach gleich Digest, ohne zweite Runde.
    assert koepfe[:2] == ["Basic", "Digest"]


def test_ein_server_der_basic_nimmt_bekommt_keine_zweite_runde():
    """Die Gegenprobe: Wer Basic annimmt, soll den Umweg nicht bezahlen."""
    koepfe: list[str] = []

    def mit_basic(anfrage: httpx.Request) -> httpx.Response:
        koepfe.append(anfrage.headers.get("authorization", "-").split(" ")[0])
        return _xml(PRINCIPAL_ANTWORT)

    zugang = caldav.Zugang(WURZEL, "anja", "geheim", transport=httpx.MockTransport(mit_basic))
    with caldav._klient(zugang) as klient:
        caldav._propfind(klient, WURZEL, caldav._PRINCIPAL, "0")

    assert koepfe == ["Basic"]


def test_ein_falsches_passwort_bleibt_ein_falsches_passwort():
    """⚠️ Ein 401 **ohne** Digest-Aufforderung darf nicht in einer zweiten
    Runde verpuffen — sonst würde aus „abgewiesen" ein stiller Fehlschlag."""

    def immer_nein(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"www-authenticate": 'Basic realm="x"'})

    zugang = caldav.Zugang(WURZEL, "anja", "falsch", transport=httpx.MockTransport(immer_nein))
    with pytest.raises(caldav.CaldavFehler) as f:
        caldav.kalender_finden(zugang)
    assert str(f.value) == "caldav_abgewiesen"
