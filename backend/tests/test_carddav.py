"""CardDAV gegen einen Doppelgänger, der sich benimmt wie die echten Server.

⚠️ **Ein Doppelgänger, der freundlicher ist als der echte Server, macht den
Test hohl.** Beim Kalender ist das zweimal passiert: Einer gab die Adresse
unabhängig vom Anfragerumpf zurück, ein anderer kodierte den Pfad nicht so
zurück wie Google. Beide Mutationsproben liefen auf Rückgabecode 0. Die
Doppelgänger hier sind deshalb absichtlich zickig.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import carddav as dienst

CARD = "urn:ietf:params:xml:ns:carddav"

# ⚠️ Googles echte Antwort auf die Principal-Frage: ein sauberes 207 mit
# ``404 Not Found`` im ``propstat`` — und der Adresse gleich daneben.
GOOGLE_ANTWORT = f"""<?xml version="1.0" encoding="UTF-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">
 <d:response>
  <d:href>/carddav/v2/</d:href>
  <d:propstat><d:status>HTTP/1.1 404 Not Found</d:status>
   <d:prop><d:current-user-principal/></d:prop></d:propstat>
  <d:propstat><d:status>HTTP/1.1 200 OK</d:status>
   <d:prop><c:addressbook-home-set>
     <d:href>/carddav/v2/wer%40example.com/lists/</d:href>
   </c:addressbook-home-set></d:prop></d:propstat>
 </d:response>
</d:multistatus>"""

BUECHER = f"""<?xml version="1.0" encoding="UTF-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}" xmlns:cs="http://calendarserver.org/ns/">
 <d:response>
  <d:href>/dav/heim/</d:href>
  <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
   <d:displayname>Heim</d:displayname></d:prop></d:propstat>
 </d:response>
 <d:response>
  <d:href>/dav/heim/privat/</d:href>
  <d:propstat><d:prop>
   <d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>
   <d:displayname>D&amp;amp;M</d:displayname>
   <cs:getctag>"ct-1"</cs:getctag></d:prop></d:propstat>
 </d:response>
 <d:response>
  <d:href>/dav/heim/aufgaben/</d:href>
  <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
   <d:displayname>Keine Kontakte</d:displayname></d:prop></d:propstat>
 </d:response>
</d:multistatus>"""


def _zugang(handler, url="https://dav.example.com/dav/heim/privat/"):
    return dienst.Zugang(
        url=url, benutzer="wer", passwort="geheim",
        transport=httpx.MockTransport(handler),
    )


# --- Bücher finden -------------------------------------------------------- #


def test_die_buecher_werden_gefunden():
    def antworten(a: httpx.Request) -> httpx.Response:
        if a.method == "PROPFIND" and a.url.path.endswith("/heim/"):
            return httpx.Response(207, text=BUECHER)
        return httpx.Response(
            207,
            text=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
            "<d:response><d:href>/</d:href><d:propstat><d:prop>"
            "<c:addressbook-home-set><d:href>/dav/heim/</d:href></c:addressbook-home-set>"
            "</d:prop></d:propstat></d:response></d:multistatus>",
        )

    raus = dienst.buecher_finden(_zugang(antworten, "https://dav.example.com/"))
    assert [b.name for b in raus] == ["D&M"]
    assert raus[0].ctag == '"ct-1"'


def test_was_kein_adressbuch_ist_faellt_weg():
    """⚠️ Die Sammlung selbst und alles andere unter demselben Heim. Sie als
    leere Bücher anzuzeigen wäre eine Falschaussage."""
    def antworten(a):
        if a.url.path.endswith("/heim/"):
            return httpx.Response(207, text=BUECHER)
        return httpx.Response(
            207,
            text=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
            "<d:response><d:href>/</d:href><d:propstat><d:prop>"
            "<c:addressbook-home-set><d:href>/dav/heim/</d:href></c:addressbook-home-set>"
            "</d:prop></d:propstat></d:response></d:multistatus>",
        )

    namen = [b.name for b in dienst.buecher_finden(_zugang(antworten, "https://dav.example.com/"))]
    assert "Heim" not in namen and "Keine Kontakte" not in namen


def test_der_name_wird_doppelt_entmaskiert():
    """⚠️ iCloud liefert ``D&amp;amp;M`` für ein Buch namens „D&M". Der
    XML-Leser löst eine Ebene auf, die zweite muss von Hand."""
    def antworten(a):
        if a.url.path.endswith("/heim/"):
            return httpx.Response(207, text=BUECHER)
        return httpx.Response(
            207,
            text=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
            "<d:response><d:href>/</d:href><d:propstat><d:prop>"
            "<c:addressbook-home-set><d:href>/dav/heim/</d:href></c:addressbook-home-set>"
            "</d:prop></d:propstat></d:response></d:multistatus>",
        )

    assert dienst.buecher_finden(_zugang(antworten, "https://dav.example.com/"))[0].name == "D&M"


def test_google_antwortet_nicht_auf_wer_bin_ich():
    """⚠️ **Der Fall, an dem der Weg laut RFC endet.** Google meldet
    ``current-user-principal`` mit 404 im ``propstat`` und liefert die Adresse
    direkt daneben. Wer nacheinander fragt, sagt „kein Adressbuch-Server",
    obwohl das Buch einen Schritt weiter liegt."""
    gesehen: list[str] = []

    def antworten(a):
        gesehen.append(a.url.path)
        if a.url.path.endswith("/lists/"):
            return httpx.Response(207, text=BUECHER.replace("/dav/heim/", "/carddav/v2/x/lists/"))
        return httpx.Response(207, text=GOOGLE_ANTWORT)

    raus = dienst.buecher_finden(_zugang(antworten, "https://apidata.example.com/carddav/v2/"))
    assert [b.name for b in raus] == ["D&M"]
    # ⚠️ Kein zweiter Anlauf über einen Principal — den gibt es dort nicht.
    assert not any("principal" in p for p in gesehen)


def test_falsche_zugangsdaten_verschwinden_nicht_in_kein_server():
    """⚠️ Die häufigste echte Ursache. Als „kein Adressbuch-Server" gemeldet,
    sucht der Betreiber die Adresse, die längst stimmt."""
    with pytest.raises(Exception) as f:
        dienst.buecher_finden(
            _zugang(lambda a: httpx.Response(401, text="nope"), "https://dav.example.com/")
        )
    assert "abgewiesen" in str(f.value)


# --- ETags ---------------------------------------------------------------- #

ETAGS = """<?xml version="1.0" encoding="UTF-8"?>
<d:multistatus xmlns:d="DAV:">
 <d:response><d:href>/dav/heim/privat/</d:href>
  <d:propstat><d:prop><d:getetag>"sammlung"</d:getetag></d:prop></d:propstat></d:response>
 <d:response><d:href>/dav/heim/privat/eins.vcf</d:href>
  <d:propstat><d:prop><d:getetag>"e1"</d:getetag></d:prop></d:propstat></d:response>
 <d:response><d:href>/dav/heim/privat/zwei%40x.vcf</d:href>
  <d:propstat><d:prop><d:getetag>"e2"</d:getetag></d:prop></d:propstat></d:response>
</d:multistatus>"""


def test_die_sammlung_selbst_faellt_weg():
    """⚠️ **Die Falle, die beim Kalender einen halben Tag gekostet hat.**
    iCloud liefert die Sammlung als erste Antwort, mit eigenem ETag. Wer sie
    mitnimmt, fragt danach nach einer Sammlung als Karte — und iCloud antwortet
    darauf gar nicht, bis in die Zeitgrenze."""
    raus = dienst.etags_holen(_zugang(lambda a: httpx.Response(207, text=ETAGS)))
    # ⚠️ Ohne Anführungszeichen, wie beim Kalender. Sonst hätte Lieferung 2
    # zwei Schreibweisen desselben ETags und einen Konflikt, den es nicht gibt.
    assert [k.etag for k in raus] == ["e1", "e2"]


def test_die_sammlung_faellt_auch_mit_schraegstrich_weg():
    """⚠️ Verglichen wird über ``ortsschluessel``, nicht wörtlich: Manche
    Server antworten mit absoluter Adresse, andere ohne den Schrägstrich."""
    text = ETAGS.replace(
        "<d:href>/dav/heim/privat/</d:href>",
        "<d:href>https://dav.example.com/dav/heim/privat</d:href>",
    )
    raus = dienst.etags_holen(_zugang(lambda a: httpx.Response(207, text=text)))
    assert len(raus) == 2


# --- Inhalte -------------------------------------------------------------- #


def test_im_rumpf_steht_der_pfad_nicht_die_ganze_adresse():
    """⚠️ RFC 6352 zeigt es so, und manche Server vergleichen wörtlich. Mit
    ``https://…`` findet der Abruf nichts und meldet trotzdem Erfolg."""
    gesehen: list[str] = []

    def antworten(a):
        gesehen.append(a.content.decode())
        return httpx.Response(
            207,
            text=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
            "<d:response><d:href>/dav/heim/privat/eins.vcf</d:href><d:propstat><d:prop>"
            '<d:getetag>"e1"</d:getetag>'
            "<c:address-data>BEGIN:VCARD\nFN:Vera\nEND:VCARD</c:address-data>"
            "</d:prop></d:propstat></d:response></d:multistatus>",
        )

    dienst.inhalte_holen(
        _zugang(antworten), ["https://dav.example.com/dav/heim/privat/eins.vcf"]
    )
    assert "<d:href>/dav/heim/privat/eins.vcf</d:href>" in gesehen[0]
    assert "https://dav.example.com" not in gesehen[0]


def test_ein_und_zeichen_im_pfad_bricht_den_rumpf_nicht():
    """⚠️ Der Pfad wandert in XML. Ein ``&`` darin macht den Rumpf ungültig,
    und der Server antwortet mit 400 statt mit Karten. Dieselbe Wache wie
    ``_entschaerfen`` beim ``calendar-multiget``."""
    import xml.etree.ElementTree as ET

    gesehen: list[str] = []

    def antworten(a):
        gesehen.append(a.content.decode())
        return httpx.Response(207, text='<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"/>')

    dienst.inhalte_holen(_zugang(antworten), ["https://dav.example.com/dav/heim/privat/a&b.vcf"])

    assert "<d:href>/dav/heim/privat/a&amp;b.vcf</d:href>" in gesehen[0]
    ET.fromstring(gesehen[0])  # und der Rumpf bleibt lesbares XML


def test_der_schluessel_ist_der_ortsschluessel():
    """⚠️ **Google gibt anders kodiert zurück, als wir geschrieben haben.**
    Wörtlich verglichen wäre die Karte unbekannt — und der Abgleich legte sie
    bei jeder Runde neu an. Genau so ist es beim Kalender passiert."""
    def antworten(a):
        return httpx.Response(
            207,
            text=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
            "<d:response><d:href>/dav/heim/privat/x%40nexmail.vcf</d:href>"
            '<d:propstat><d:prop><d:getetag>"e9"</d:getetag>'
            "<c:address-data>BEGIN:VCARD\nFN:Wer\nEND:VCARD</c:address-data>"
            "</d:prop></d:propstat></d:response></d:multistatus>",
        )

    raus = dienst.inhalte_holen(
        _zugang(antworten), ["https://dav.example.com/dav/heim/privat/x@nexmail.vcf"]
    )
    # Geschrieben mit ``@``, zurueck mit ``%40`` — und trotzdem dieselbe Karte.
    assert dienst.ortsschluessel(
        "https://dav.example.com/dav/heim/privat/x@nexmail.vcf"
    ) in raus


def test_geholt_wird_blockweise():
    """⚠️ Ein Deckel, kein Geschwindigkeitsregler: Karten mit Portraitfoto
    haben hunderte Kilobyte."""
    griffe = 0

    def antworten(a):
        nonlocal griffe
        griffe += 1
        return httpx.Response(
            207, text='<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"/>'
        )

    dienst.inhalte_holen(
        _zugang(antworten),
        [f"https://dav.example.com/dav/heim/privat/{i}.vcf" for i in range(dienst.BLOCK * 2 + 1)],
    )
    assert griffe == 3


def test_ohne_adressen_geht_nichts_hinaus():
    def platzen(a):
        raise AssertionError("es haette gar nicht gefragt werden duerfen")

    assert dienst.inhalte_holen(_zugang(platzen), []) == {}


def test_ein_ctag_wird_gelesen():
    def antworten(a):
        return httpx.Response(
            207,
            text='<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
            'xmlns:cs="http://calendarserver.org/ns/"><d:response>'
            "<d:href>/dav/heim/privat/</d:href><d:propstat><d:prop>"
            "<cs:getctag>\"ct-7\"</cs:getctag></d:prop></d:propstat>"
            "</d:response></d:multistatus>",
        )

    assert dienst.ctag_holen(_zugang(antworten)) == '"ct-7"'


def test_manche_server_antworten_nur_unter_well_known():
    """⚠️ **Der Rückfall ist kein Beiwerk.** Manche Server geben unter der
    Wurzel gar keine DAV-Auskunft und nur unter ``/.well-known/carddav``;
    andere umgekehrt. Beides zu versuchen ist billiger als zu raten — und ohne
    diesen Test lief die Mutation „nur die Wurzel" glatt durch."""
    gesehen: list[str] = []

    def antworten(a):
        gesehen.append(a.url.path)
        if a.url.path == "/":
            # Kein DAV hier: ein gewoehnliches 200 ohne Multistatus.
            return httpx.Response(200, text="<html>nichts</html>")
        if a.url.path.endswith("/heim/"):
            return httpx.Response(207, text=BUECHER)
        return httpx.Response(
            207,
            text=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
            "<d:response><d:href>/</d:href><d:propstat><d:prop>"
            "<c:addressbook-home-set><d:href>/dav/heim/</d:href></c:addressbook-home-set>"
            "</d:prop></d:propstat></d:response></d:multistatus>",
        )

    raus = dienst.buecher_finden(_zugang(antworten, "https://dav.example.com/"))
    assert [b.name for b in raus] == ["D&M"]
    assert "/.well-known/carddav" in gesehen
