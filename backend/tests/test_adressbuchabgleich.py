"""Adressbücher mit ihrer Gegenstelle abgleichen. Lieferung 1, lesend.

⚠️ **Der teuerste Fehler hier ist der stille Überschreiber.** Ein Kontakt, den
jemand von Hand gepflegt hat, darf nicht wortlos zur Karte vom Telefon werden;
und eine Karte, die beim Anbieter verschwindet, darf nicht hier stehen
bleiben. Beide Richtungen stehen unten, samt dem Doppelgänger, der sich
benimmt wie iCloud und Google, nicht freundlicher.
"""

from __future__ import annotations

import re
from urllib.parse import unquote
from xml.sax.saxutils import escape

import httpx
import pytest

from app.db import SessionLocal
from app.models import Adressbuch, Benutzer, Kontakt, Kontaktgruppe, KontaktgruppeMitglied
from app.services import adressbuchabgleich as dienst
from app.services import adressbuecher, carddav
from app.services import kontakte as kontaktdienst
from conftest import einrichten

CARD = "urn:ietf:params:xml:ns:carddav"
WURZEL = "https://carddav.example.com"
PFAD = "/dav/vera/buecher/privat/"
BUCH = f"{WURZEL}{PFAD}"
ZWEITER_PFAD = "/dav/vera/buecher/verein/"
ZWEITES_BUCH = f"{WURZEL}{ZWEITER_PFAD}"


def _karte(uid: str = "k1", name: str = "Vera Beispiel", adresse: str = "vera@example.org", extra: str = "") -> str:
    zeilen = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{uid}", f"FN:{name}"]
    if adresse:
        zeilen.append(f"EMAIL;TYPE=INTERNET:{adresse}")
    return "\r\n".join(zeilen) + "\r\n" + extra + "END:VCARD\r\n"


#: Eine Karte, wie iCloud sie liefert: mit allem, was nexmail nicht kennt.
VOLL = _karte(
    extra=(
        "TEL;TYPE=CELL:+49 30 123456\r\n"
        "ORG:Beispiel GmbH;Vertrieb\r\n"
        "NOTE:Kennt den Weg\r\n"
        "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRg\r\n"
        "BDAY:1980-01-01\r\n"
        "X-APPLE-SUBLOCALITY:Mitte\r\n"
    )
)


def _xml(inhalt: str) -> httpx.Response:
    return httpx.Response(207, content=inhalt.encode("utf-8"))


class Buchserver:
    """Ein CardDAV-Server, den man steuern kann.

    ⚠️ **Absichtlich zickig.** Die Sammlung selbst steht mit in der
    ETag-Liste (iCloud), und mit ``kodiert_zurueck`` nennt die Liste ein ``@``
    als ``%40``, während der Inhalt entschlüsselt zurückkommt (Google). Ein
    Doppelgänger, der freundlicher ist als der echte Server, macht den Test
    hohl; das ist beim Kalender zweimal passiert.
    """

    def __init__(self) -> None:
        #: Pfad (entschlüsselt) -> (ETag, vCard). Mehrere Bücher zugleich,
        #: unterschieden am Pfad.
        self.karten: dict[str, tuple[str, str]] = {}
        self.anfragen: list[tuple[str, str]] = []
        #: Die Kopfzeilen jeder Anfrage, in derselben Reihenfolge — für die
        #: Frage, ob ``If-Match`` wirklich mitfuhr.
        self.koepfe: list[dict[str, str]] = []
        self.ctag = "ct-1"
        self.kodiert_zurueck = False
        #: Google schickt zum PUT kein ETag zurück; dann muss nexmail es
        #: nachschlagen. Ab Werk wie iCloud: mit.
        self.etag_im_kopf = True
        #: Wahr heisst: Der Server nimmt kein PUT und kein DELETE an (405).
        self.nur_lesen = False
        self._laufnummer = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._antworten)

    def _gelistet(self, pfad: str) -> str:
        return pfad.replace("@", "%40") if self.kodiert_zurueck else pfad

    def _antworten(self, a: httpx.Request) -> httpx.Response:
        pfad = a.url.path
        self.anfragen.append((a.method, pfad))
        self.koepfe.append({k.lower(): v for k, v in a.headers.items()})

        if a.method in ("PUT", "DELETE") and self.nur_lesen:
            return httpx.Response(405)

        if a.method == "PUT":
            # ⚠️ So zickig wie iCloud: ``If-Match`` muss zum ETag passen,
            # ``If-None-Match: *`` scheitert an einer vorhandenen Karte.
            pfad = unquote(pfad)
            vorhanden = self.karten.get(pfad)
            wenn = a.headers.get("if-match", "").strip('"')
            keins = a.headers.get("if-none-match", "")
            if keins == "*" and vorhanden is not None:
                return httpx.Response(412)
            if wenn and (vorhanden is None or vorhanden[0] != wenn):
                return httpx.Response(412)
            self._laufnummer += 1
            etag = f"e{self._laufnummer + 10}"
            self.karten[pfad] = (etag, a.content.decode("utf-8"))
            self.ctag = f"ct-{self._laufnummer + 10}"
            kopf = {"etag": f'"{etag}"'} if self.etag_im_kopf else {}
            return httpx.Response(201 if vorhanden is None else 204, headers=kopf)

        if a.method == "DELETE":
            pfad = unquote(pfad)
            vorhanden = self.karten.get(pfad)
            if vorhanden is None:
                return httpx.Response(404)
            wenn = a.headers.get("if-match", "").strip('"')
            if wenn and vorhanden[0] != wenn:
                return httpx.Response(412)
            del self.karten[pfad]
            self._laufnummer += 1
            self.ctag = f"ct-{self._laufnummer + 10}"
            return httpx.Response(204)

        if a.method == "PROPFIND":
            return _xml(
                '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
                'xmlns:cs="http://calendarserver.org/ns/">'
                f"<d:response><d:href>{pfad}</d:href><d:propstat><d:prop>"
                f"<cs:getctag>{self.ctag}</cs:getctag>"
                "</d:prop></d:propstat></d:response></d:multistatus>"
            )

        if a.method == "REPORT":
            rumpf = a.content.decode()
            im_buch = {p: k for p, k in self.karten.items() if p.startswith(pfad)}
            if "addressbook-multiget" in rumpf:
                gefragt = {unquote(h) for h in re.findall(r"<d:href>([^<]+)</d:href>", rumpf)}
                zeilen = [
                    f"<d:response><d:href>{p}</d:href><d:propstat><d:prop>"
                    f'<d:getetag>"{etag}"</d:getetag>'
                    f"<c:address-data>{escape(vcf)}</c:address-data>"
                    "</d:prop></d:propstat></d:response>"
                    for p, (etag, vcf) in im_buch.items()
                    if p in gefragt
                ]
                return _xml(
                    f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="{CARD}">'
                    + "".join(zeilen)
                    + "</d:multistatus>"
                )
            zeilen = [
                f"<d:response><d:href>{pfad}</d:href><d:propstat><d:prop>"
                '<d:getetag>"sammlung"</d:getetag></d:prop></d:propstat></d:response>'
            ]
            zeilen += [
                f"<d:response><d:href>{self._gelistet(p)}</d:href><d:propstat><d:prop>"
                f'<d:getetag>"{etag}"</d:getetag></d:prop></d:propstat></d:response>'
                for p, (etag, _) in im_buch.items()
            ]
            return _xml(
                '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
                + "".join(zeilen)
                + "</d:multistatus>"
            )

        return httpx.Response(405)


def _buch(db, person, name: str, url: str) -> Adressbuch:
    buch = Adressbuch(
        benutzer_id=person.id, name=name, farbe=2, art="carddav",
        herkunft=name, url=url, benutzer_name="vera",
    )
    db.add(buch)
    db.flush()
    dienst.passwort_schreiben(buch, "geheim")
    db.commit()
    return buch


@pytest.fixture
def welt(klient, db, monkeypatch):
    einrichten(klient)
    person = db.query(Benutzer).one()
    server = Buchserver()
    buch = _buch(db, person, "iCloud", BUCH)

    # ⚠️ Der Zugang bekommt den falschen Server untergeschoben, sonst ginge
    # jeder Test ins echte Netz.
    echt = dienst.zugang

    def mit_transport(b, db=None):
        z = echt(b, db)
        z.transport = server.transport()
        return z

    monkeypatch.setattr(dienst, "zugang", mit_transport)
    return person, buch, server


def _zweiter_benutzer(db) -> Benutzer:
    zweiter = Benutzer(
        id="z" * 32, benutzername="zweiter", anzeigename="Zweiter", passwort_hash="x"
    )
    db.add(zweiter)
    db.commit()
    return zweiter


# --- Hereinholen ---------------------------------------------------------- #


def test_eine_karte_vom_server_landet_hier(db, welt):
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    runde = dienst.abgleichen(db, buch)

    assert runde.neu == 1
    zeile = db.query(Kontakt).one()
    assert zeile.name == "Vera Beispiel"
    assert zeile.adresse == "vera@example.org"
    assert zeile.firma == "Beispiel GmbH"
    assert zeile.telefon == "+49 30 123456"
    assert zeile.notiz == "Kennt den Weg"
    assert zeile.uid == "k1"
    assert zeile.etag == "e1"
    assert zeile.href == f"{BUCH}k1.vcf"
    # ⚠️ Im verbundenen Buch, nicht im lokalen. Und gepflegt, nicht aufgeschnappt.
    assert zeile.adressbuch_id == buch.id
    assert zeile.quelle == "hand"
    assert zeile.schmutzig is False


def test_das_original_wird_aufgehoben(db, welt):
    """⚠️ **Die Rückfahrkarte.** Foto, Geburtstag und ``X-APPLE-…`` kennt
    nexmail nicht. Beim Zurückschreiben in Lieferung 2 wären sie sonst weg,
    und der Besitzer merkt es, wenn das Foto fehlt."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    dienst.abgleichen(db, buch)

    roh = db.query(Kontakt).one().roh
    assert "PHOTO;ENCODING=b" in roh
    assert "BDAY:1980-01-01" in roh
    assert "X-APPLE-SUBLOCALITY:Mitte" in roh


def test_unveraendert_spart_den_abruf(db, welt):
    """⚠️ Das ``ctag`` ist der Grund, warum ein Abgleich nichts kostet, wenn
    sich nichts getan hat."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)

    server.anfragen.clear()
    runde = dienst.abgleichen(db, buch)

    assert runde.unveraendert is True
    assert not any(a[0] == "REPORT" for a in server.anfragen)


def test_ein_geaendertes_etag_holt_neu(db, welt):
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)

    server.karten[f"{PFAD}k1.vcf"] = ("e2", VOLL.replace("Vera Beispiel", "Vera Beispiel-Keller"))
    server.ctag = "ct-2"
    runde = dienst.abgleichen(db, buch)

    assert runde.geaendert == 1 and runde.neu == 0
    zeile = db.query(Kontakt).one()
    assert zeile.name == "Vera Beispiel-Keller"
    assert zeile.etag == "e2"


def test_nur_das_geaenderte_wird_geholt(db, welt):
    """⚠️ Erst die Kennungen, dann die Inhalte. Ein Buch mit tausend Karten
    samt Fotos wäre sonst bei jeder Runde ein Download von Megabyte."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    server.karten[f"{PFAD}k2.vcf"] = ("e2", _karte("k2", "Jonas Keller", "jonas@example.org"))
    dienst.abgleichen(db, buch)

    server.karten[f"{PFAD}k2.vcf"] = ("e3", _karte("k2", "Jonas Keller-Beispiel", "jonas@example.org"))
    server.ctag = "ct-2"
    server.anfragen.clear()
    dienst.abgleichen(db, buch)

    # Ein Multiget, und darin nur die eine geänderte Karte.
    # (Der Doppelgänger merkt sich nur Methode und Pfad; die Zahl der
    # Griffe zählt: ctag, Liste, ein Multiget.)
    assert [a[0] for a in server.anfragen] == ["PROPFIND", "REPORT", "REPORT"]


def test_was_dort_weg_ist_ist_auch_hier_weg(db, welt):
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)
    lokal = kontaktdienst.anlegen(db, person, "jonas@example.org", name="Jonas")
    drin = db.query(Kontakt).filter(Kontakt.adressbuch_id == buch.id).one()
    gruppe = Kontaktgruppe(benutzer_id=person.id, name="Verein")
    db.add(gruppe)
    db.flush()
    db.add(KontaktgruppeMitglied(benutzer_id=person.id, gruppe_id=gruppe.id, kontakt_id=drin.id))
    db.commit()

    server.karten.clear()
    server.ctag = "ct-2"
    runde = dienst.abgleichen(db, buch)

    assert runde.entfernt == 1
    # ⚠️ Der lokale Kontakt bleibt, und die Gruppe zählt keine Leiche mit.
    assert [k.id for k in db.query(Kontakt).all()] == [lokal.id]
    assert db.query(KontaktgruppeMitglied).count() == 0


def test_ein_anderes_buch_bleibt_unberuehrt(db, welt):
    """⚠️ Verglichen wird je Buch. Sonst hielte der Abgleich des zweiten die
    Karten des ersten für verschwunden."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)
    zweites = _buch(db, person, "Verein", ZWEITES_BUCH)
    server.karten[f"{ZWEITER_PFAD}k2.vcf"] = ("e2", _karte("k2", "Jonas Keller", "jonas@example.org"))

    runde = dienst.abgleichen(db, zweites)

    assert runde.neu == 1 and runde.entfernt == 0
    assert db.query(Kontakt).count() == 2
    assert db.query(Kontakt).filter(Kontakt.adressbuch_id == buch.id).count() == 1


def test_ein_kodierter_pfad_erzeugt_kein_doppel(db, welt):
    """⚠️ **Der Fehler, der beim Kalender jeden neuen Termin bei der nächsten
    Runde verschwinden liess.** Google nennt ``@`` in der Liste als ``%40``
    und liefert den Inhalt entschlüsselt. Wörtlich verglichen ist das ein
    unbekannter Eintrag UND eine verschwundene Zeile, bei jeder Runde."""
    person, buch, server = welt
    server.kodiert_zurueck = True
    server.karten[f"{PFAD}vera@example.org.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)
    kennung = db.query(Kontakt).one().id

    for _ in range(2):
        server.ctag = f"ct-{kennung}-{_}"
        runde = dienst.abgleichen(db, buch)
        assert runde.neu == 0 and runde.entfernt == 0

    uebrig = db.query(Kontakt).all()
    assert len(uebrig) == 1, "Die Karte wurde doppelt angelegt."
    assert uebrig[0].id == kennung, "Die Karte bekam eine neue Kennung."


def test_ein_kaputter_server_hinterlaesst_eine_kennung(db, welt, monkeypatch):
    """⚠️ Die Kennung, nicht der Satz. Die Oberfläche übersetzt."""
    person, buch, server = welt

    monkeypatch.setattr(
        dienst, "zugang",
        lambda b, db=None: carddav.Zugang(
            b.url, "a", "b", transport=httpx.MockTransport(lambda a: httpx.Response(401))
        ),
    )
    runde = dienst.abgleichen(db, buch)

    db.refresh(buch)
    assert buch.letzter_fehler == "caldav_abgewiesen"
    assert buch.zuletzt_geprueft is not None
    assert runde == dienst.Runde()


def test_der_fehler_verschwindet_wieder(db, welt, monkeypatch):
    person, buch, server = welt
    buch.letzter_fehler = "caldav_abgewiesen"
    db.commit()

    dienst.abgleichen(db, buch)

    db.refresh(buch)
    assert buch.letzter_fehler == ""


def test_das_lokale_buch_wird_nicht_abgeglichen(db, welt):
    person, buch, server = welt
    lokal = adressbuecher.lokales(db, person)

    runde = dienst.abgleichen(db, lokal)

    assert runde == dienst.Runde()
    assert server.anfragen == []
    # ⚠️ Und es wird nicht einmal angefasst. Ein lokales Buch mit Prüfzeit
    # und Fehlerkennung sähe in der Spalte aus wie ein kaputt verbundenes.
    db.refresh(lokal)
    assert lokal.zuletzt_geprueft is None and lokal.letzter_fehler == ""


# --- Die Adresse ist der Schlüssel ---------------------------------------- #


def test_eine_karte_ohne_adresse_landet_hier(db, welt):
    """⚠️ Seit dem 05.09.2026 kein Sonderfall mehr. Die Werkstatt hat eine
    Nummer und kein Postfach; der erste Bau überging sie, und dem Adressbuch
    fehlte ein Drittel der Telefonliste. Zwei davon stehen nebeneinander, ohne
    an der Eindeutigkeit zu scheitern."""
    person, buch, server = welt
    # ⚠️ Ein lokaler Kontakt ohne Adresse steht schon da. Er ist kein
    # „Inhaber" von irgendetwas; ohne Adresse gibt es nichts zu verwechseln.
    kontaktdienst.anlegen(db, person, "", "Werkstatt lokal", telefon="1")
    server.karten[f"{PFAD}k1.vcf"] = (
        "e1", _karte("k1", "Werkstatt Beispiel", adresse="", extra="TEL:030 1234\r\n")
    )
    server.karten[f"{PFAD}k2.vcf"] = ("e2", _karte("k2", "Oma", adresse="", extra="TEL:030 9999\r\n"))

    runde = dienst.abgleichen(db, buch)

    assert runde.neu == 2 and runde.belegt == 0
    zeilen = {z.name: z for z in db.query(Kontakt).all()}
    assert len(zeilen) == 3
    assert zeilen["Werkstatt Beispiel"].adresse == ""
    assert zeilen["Werkstatt Beispiel"].telefon == "030 1234"
    assert zeilen["Oma"].adressbuch_id == buch.id
    assert zeilen["Werkstatt lokal"].adressbuch_id != buch.id


def test_zwei_karten_mit_derselben_adresse_werfen_die_runde_nicht_um(db, welt):
    """⚠️ Bei iCloud nach einem Zusammenführen ganz gewöhnlich. Die zweite
    Karte ist belegt, die Runde läuft durch. Ohne den Flush nach jeder neuen
    Zeile sähe die zweite Karte die erste nicht, beide würden angelegt, und
    der Commit stürbe an der Eindeutigkeit, bei jedem Takt aufs Neue."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    server.karten[f"{PFAD}k2.vcf"] = ("e2", _karte("k2", "Vera Doppel", "vera@example.org"))

    runde = dienst.abgleichen(db, buch)

    assert runde.neu == 1 and runde.belegt == 1
    assert db.query(Kontakt).count() == 1
    db.refresh(buch)
    assert buch.letzter_fehler == ""


def test_eine_kaputte_adresse_gilt_als_keine(db, welt):
    """Die Karte kommt trotzdem an; nur adressieren lässt sie sich nicht."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", _karte("k1", "Vera Beispiel", adresse="kein-postfach"))

    runde = dienst.abgleichen(db, buch)

    assert runde.neu == 1
    assert db.query(Kontakt).one().adresse == ""


def test_eine_aufgeschnappte_adresse_wird_von_der_karte_uebernommen(db, welt):
    """Regel 1. Der Mensch ist beim Anbieter gepflegt, hier stand nur ein
    Platzhalter aus dem ``From``. ⚠️ **Dieselbe Zeile**, sonst verlöre er
    seine Gruppen und die Reihenfolge der Vorschläge."""
    person, buch, server = welt
    platzhalter = kontaktdienst.anlegen(
        db, person, "vera@example.org", name="vera@example.org", quelle="gesammelt"
    )
    platzhalter.verwendet = 7
    gruppe = Kontaktgruppe(benutzer_id=person.id, name="Verein")
    db.add(gruppe)
    db.flush()
    db.add(KontaktgruppeMitglied(benutzer_id=person.id, gruppe_id=gruppe.id, kontakt_id=platzhalter.id))
    db.commit()
    kennung = platzhalter.id
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    runde = dienst.abgleichen(db, buch)

    assert runde.neu == 1 and runde.belegt == 0
    zeile = db.query(Kontakt).one()
    assert zeile.id == kennung
    assert zeile.adressbuch_id == buch.id
    assert zeile.name == "Vera Beispiel"
    assert zeile.quelle == "hand"
    assert zeile.verwendet == 7
    assert zeile.href == f"{BUCH}k1.vcf" and zeile.etag == "e1"
    assert db.query(KontaktgruppeMitglied).count() == 1


def test_ein_gepflegter_eintrag_bleibt_stehen(db, welt):
    """Regel 2. Wer „Oma" eingetragen hat, will nicht, dass der Abgleich
    daraus die Karte vom Telefon macht. ⚠️ Übergangen UND gezählt."""
    person, buch, server = welt
    oma = kontaktdienst.anlegen(db, person, "vera@example.org", name="Oma", notiz="Sonntags anrufen")
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    runde = dienst.abgleichen(db, buch)

    assert runde.belegt == 1 and runde.neu == 0
    db.refresh(oma)
    assert oma.name == "Oma" and oma.notiz == "Sonntags anrufen"
    assert oma.adressbuch_id == adressbuecher.lokales(db, person).id
    assert oma.href == "" and oma.roh == ""
    assert db.query(Kontakt).count() == 1


def test_was_in_einem_anderen_buch_liegt_bleibt_dort(db, welt):
    """Regel 3. Derselbe Mensch bei iCloud und bei Google passt in dieses
    Modell nur einmal; das zweite Buch zählt ihn als belegt."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)
    zweites = _buch(db, person, "Verein", ZWEITES_BUCH)
    server.karten[f"{ZWEITER_PFAD}v.vcf"] = ("e9", _karte("v", "Vera B.", "vera@example.org"))

    runde = dienst.abgleichen(db, zweites)

    assert runde.belegt == 1 and runde.neu == 0
    zeile = db.query(Kontakt).one()
    assert zeile.adressbuch_id == buch.id
    assert zeile.name == "Vera Beispiel"


def test_ein_aufgeschnappter_in_einem_anderen_buch_wird_nicht_gestohlen(db, welt):
    """⚠️ Regel 1 gilt nur aus dem lokalen Buch. Wer einen Aufgeschnappten
    bewusst in „Verein" gelegt hat, will ihn nicht bei iCloud wiederfinden."""
    person, buch, server = welt
    zweites = _buch(db, person, "Verein", ZWEITES_BUCH)
    k = kontaktdienst.anlegen(db, person, "vera@example.org", name="vera@example.org", quelle="gesammelt")
    adressbuecher.verschieben(db, person, k.id, zweites.id)
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    runde = dienst.abgleichen(db, buch)

    assert runde.belegt == 1
    db.refresh(k)
    assert k.adressbuch_id == zweites.id
    assert k.href == ""


def test_die_adresse_eines_anderen_benutzers_steht_nicht_im_weg(db, welt):
    """⚠️ Eindeutig ist die Adresse je Benutzer, nicht je Installation."""
    person, buch, server = welt
    zweiter = _zweiter_benutzer(db)
    kontaktdienst.anlegen(db, zweiter, "vera@example.org", name="Vera")
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    runde = dienst.abgleichen(db, buch)

    assert runde.neu == 1 and runde.belegt == 0
    assert db.query(Kontakt).filter(Kontakt.benutzer_id == person.id).count() == 1


def test_ein_verschobener_kontakt_wird_von_seiner_karte_wiedererkannt(db, welt):
    """Der Weg, einen Doppelgänger aufzulösen: den lokalen Eintrag ins Buch
    schieben. ⚠️ Und das muss OHNE geändertes ``ctag`` greifen, sonst wartet
    der Verschobene bis zur nächsten Änderung beim Anbieter."""
    person, buch, server = welt
    oma = kontaktdienst.anlegen(db, person, "vera@example.org", name="Oma")
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    assert dienst.abgleichen(db, buch).belegt == 1  # ctag ist jetzt gemerkt

    adressbuecher.verschieben(db, person, oma.id, buch.id)
    runde = dienst.abgleichen(db, buch)

    assert runde.unveraendert is False
    assert runde.geaendert == 1
    db.refresh(oma)
    assert oma.href == f"{BUCH}k1.vcf" and oma.etag == "e1" and oma.uid == "k1"
    assert oma.name == "Vera Beispiel"
    assert oma.schmutzig is False
    assert db.query(Kontakt).count() == 1


def test_erzwingen_holt_uebergangene_karten_nach(db, welt):
    """Der andere Weg: den Doppelgänger löschen. ⚠️ Danach ist das ``ctag``
    gleich, und ohne ``erzwingen`` passiert bis zur nächsten Änderung drüben
    nichts. Der Knopf „Abgleichen" gehört deshalb auf ``erzwingen=True``."""
    person, buch, server = welt
    oma = kontaktdienst.anlegen(db, person, "vera@example.org", name="Oma")
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    assert dienst.abgleichen(db, buch).belegt == 1

    kontaktdienst.entfernen(db, person, oma.id)
    assert dienst.abgleichen(db, buch).unveraendert is True
    assert db.query(Kontakt).count() == 0

    runde = dienst.abgleichen(db, buch, erzwingen=True)

    assert runde.neu == 1
    assert db.query(Kontakt).one().name == "Vera Beispiel"


def test_eine_karte_deren_neue_adresse_belegt_ist_bleibt_stehen(db, welt):
    """Drüben bekam die Karte eine Adresse, die hier ein gepflegter Kontakt
    hält. ⚠️ Nicht übernehmen, nicht abstürzen: Die Zeile bleibt auf dem
    alten Stand und wird beim nächsten vollen Vergleich wieder versucht."""
    person, buch, server = welt
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)
    dienst.abgleichen(db, buch)
    kontaktdienst.anlegen(db, person, "jonas@example.org", name="Jonas")

    server.karten[f"{PFAD}k1.vcf"] = ("e2", _karte("k1", "Vera Beispiel", "jonas@example.org"))
    server.ctag = "ct-2"
    runde = dienst.abgleichen(db, buch)

    assert runde.belegt == 1 and runde.geaendert == 0
    zeile = db.query(Kontakt).filter(Kontakt.adressbuch_id == buch.id).one()
    assert zeile.adresse == "vera@example.org" and zeile.etag == "e1"
    assert db.query(Kontakt).count() == 2


# --- Die Runde über alle Bücher ------------------------------------------- #


def test_alle_abgleichen_nimmt_nur_verbundene_buecher(db, welt):
    person, buch, server = welt
    lokal = adressbuecher.lokales(db, person)
    server.karten[f"{PFAD}k1.vcf"] = ("e1", VOLL)

    raus = dienst.alle_abgleichen(db, person)

    assert set(raus) == {buch.id}
    assert lokal.id not in raus
    assert raus[buch.id].neu == 1


def test_ein_getrenntes_buch_haelt_die_runde_nicht_auf(db, welt, monkeypatch):
    """⚠️ **Der Abgleich läuft in einem eigenen Faden.** Wer im selben Moment
    auf „Trennen" drückt, lässt den abschliessenden ``UPDATE`` auf null Zeilen
    laufen: ``StaleDataError``, Sitzung gesperrt. Ohne Zurückrollen reisst es
    die ganze Runde mit. Beim Kalender am 03.09.2026 aus dem Betrieb."""
    person, buch, server = welt
    zweites = _buch(db, person, "Verein", ZWEITES_BUCH)

    # ⚠️ Aus einer ZWEITEN Sitzung, denn genau das ist der Fall: Die
    # Web-Anfrage löscht, der Takt-Faden schreibt weiter.
    echt = dienst._carddav_abgleichen
    geschlagen = buch.id

    def dazwischenfunken(db_, b, erzwingen):
        raus = echt(db_, b, erzwingen)
        if b.id == geschlagen:
            with SessionLocal() as andere:
                andere.execute(
                    Adressbuch.__table__.delete().where(Adressbuch.__table__.c.id == geschlagen)
                )
                andere.commit()
        return raus

    monkeypatch.setattr(dienst, "_carddav_abgleichen", dazwischenfunken)

    raus = dienst.alle_abgleichen(db, person)

    # ⚠️ Das zweite muss drankommen, und die Sitzung ist danach benutzbar.
    assert zweites.id in raus
    assert db.query(Adressbuch).filter(Adressbuch.art == "carddav").count() == 1


def test_ein_buch_das_klemmt_kostet_nur_ein_buch(db, welt, monkeypatch):
    """⚠️ Auch dann, wenn es die Sitzung gesperrt zurücklässt. Die Liste wird
    vorher geholt, und nach einem Fehlschlag wird zurückgerollt."""
    person, buch, server = welt
    zweites = _buch(db, person, "Verein", ZWEITES_BUCH)

    echt = dienst.abgleichen
    geschlagen = buch.id

    def sperren(db_, b, erzwingen=False):
        if b.id != geschlagen:
            return echt(db_, b, erzwingen)
        with SessionLocal() as andere:
            andere.execute(
                Adressbuch.__table__.delete().where(Adressbuch.__table__.c.id == geschlagen)
            )
            andere.commit()
        b.name = "weg"
        try:
            db_.commit()
        except Exception:  # noqa: BLE001
            pass  # absichtlich NICHT zurückgerollt; das macht die Runde
        raise RuntimeError("etwas ganz anderes")

    monkeypatch.setattr(dienst, "abgleichen", sperren)

    raus = dienst.alle_abgleichen(db, person)

    assert zweites.id in raus


# --- Zugang --------------------------------------------------------------- #


def test_das_passwort_haengt_am_buch(db, welt):
    """⚠️ Der Chiffretext trägt die Kennung des Buches als Zusatzdaten. Ohne
    das liesse sich ein verschlüsseltes Passwort von einem Buch auf ein
    anderes kopieren."""
    person, buch, server = welt
    zweites = _buch(db, person, "Verein", ZWEITES_BUCH)
    zweites.passwort = buch.passwort
    db.commit()

    assert dienst.passwort_lesen(buch) == "geheim"
    with pytest.raises(Exception):
        dienst.passwort_lesen(zweites)
