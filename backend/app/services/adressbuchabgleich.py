"""Adressbücher mit ihrer Gegenstelle abgleichen. CardDAV, beide Richtungen.

Lieferung 1 (05.09.2026) holte nur. Lieferung 2 (11.09.2026) schreibt:
``hochschieben`` bringt eine geänderte oder neue Karte mit ``If-Match`` zum
Anbieter, ``wegnehmen`` löscht dort, ``fremde_fassung`` holt bei einem
Konflikt die andere Seite zum Ansehen. Das Vorbild ist
``kalenderabgleich``; die Regeln sind dieselben:

⚠️ **Erst der Server, dann die eigene Datenbank.** Was der Server ablehnt,
passiert hier gar nicht erst. Ein 412 heisst: Jemand hat dieselbe Karte am
Telefon geändert; das wird gefragt, nie überbügelt.

⚠️ **Geschrieben wird die geänderte Rohkarte, kein Nachbau.** Der
Zeilen-Editor in ``vcard.py`` ersetzt genau die Zeilen der fünf Felder; Foto,
Geburtstag und ``X-APPLE-…`` bleiben stehen.

⚠️ **Ein ins Buch verschobener Kontakt wird erst über seine Adresse gesucht,
dann angelegt.** Sonst entstünden Doppel beim Anbieter, sobald jemand eine
Person, die drüben längst steht, hier „ins Buch" schiebt. Kennt der Anbieter
die Adresse, gewinnt seine Karte (die Zeile hängt sich an sie); kennt er sie
nicht, wird die Karte aus der Zeile gebaut.

⚠️ **Das ``ctag`` spart den ganzen Abruf.** Ändert es sich nicht, hat sich in
dem Buch nichts getan. Beim Kalender ist es genauso, bei einem Postfach macht
das die ``UIDNEXT``.

⚠️ **Die Adresse ist der Schlüssel, und daran reibt sich ein fremdes Buch.**
``Kontakt`` ist je Benutzer auf die gefüllte Adresse eindeutig; das hält das
Einsammeln aus „Gesendet" sauber. Ein Buch bei iCloud hat Karten, deren
Adresse hier schon liegt. Drei Regeln, alle so gewählt, dass nichts still
überschrieben wird:

1. **Ein aufgeschnappter Eintrag wird von der Karte übernommen.** Der Mensch
   ist beim Anbieter gepflegt, hier steht nur ein Platzhalter aus dem
   ``From``. Die Zeile bleibt dieselbe: Gruppen und ``verwendet`` überleben.
2. **Ein gepflegter Eintrag bleibt stehen, die Karte wird übergangen** und
   gezählt (``belegt``). Wer „Oma" eingetragen hat, will nicht, dass der
   Abgleich daraus die Karte vom Telefon macht. Den Weg frei zu machen ist ein
   Klick, löschen oder ins Buch verschieben. Andersherum wäre es Datenverlust.
3. **Was in einem anderen verbundenen Buch liegt, bleibt dort.** Derselbe
   Mensch bei iCloud und bei Google passt in dieses Modell nur einmal; das
   zweite Buch zählt ihn als ``belegt``.

⚠️ **Eine Karte ohne E-Mail-Adresse ist trotzdem ein Kontakt.** Seit dem
05.09.2026 darf die Adresse fehlen: die Werkstatt, die Oma ohne Postfach. Sie
landen wie jede andere Karte, nur ohne die Frage nach einem Inhaber, denn ohne
Adresse gibt es nichts zu verwechseln. Der erste Bau überging sie, und das war
die Annahme „nexmail ist ein Mail-Programm", die mit CardDAV nicht mehr stimmt:
Wer die fehlenden Daten seiner Kontakte hier ergänzen oder eine Nummer fürs
Telefon anlegen will, braucht genau diese Karten.

⚠️ **Übergangene Karten werden erst wieder versucht, wenn sich beim Anbieter
etwas tut, oder mit ``erzwingen``.** Das ``ctag`` wird auch dann gemerkt, wenn
Karten übergangen wurden; sonst holte jeder Takt dieselben Karten noch einmal.
Der Knopf „Abgleichen" in der Oberfläche gehört deshalb auf ``erzwingen=True``:
Wer den lokalen Doppelgänger gerade gelöscht hat, will die Karte jetzt sehen,
nicht beim nächsten Geburtstag drüben.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .. import crypto
from ..meldung import Meldung
from ..models import Adressbuch, Benutzer, Kontakt, utcnow
from . import adressbuecher, caldav, carddav, vcard
from . import kontakte as kontaktdienst

logger = logging.getLogger("nexmail.adressbuchabgleich")


class AbgleichFehler(Meldung, RuntimeError):
    """Trägt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class Runde:
    """Was ein Abgleich bewegt hat, und was er liegen liess."""

    neu: int = 0
    geaendert: int = 0
    entfernt: int = 0
    #: Karten, deren Adresse hier ein gepflegter oder anderswo liegender
    #: Kontakt hält (Regeln 2 und 3). Nichts davon wurde angefasst.
    belegt: int = 0
    #: Zeilen, die auf ihre Karte warteten (ins Buch verschoben) und in
    #: dieser Runde zum Anbieter gingen.
    hochgeschoben: int = 0
    #: Wahr, wenn das ``ctag`` gleich war und nichts zu tun blieb.
    unveraendert: bool = False


def _kontext(buch_id: str) -> str:
    return f"adressbuch:{buch_id}:passwort"


def passwort_lesen(buch: Adressbuch) -> str:
    return crypto.entschluesseln(buch.passwort, _kontext(buch.id))


def passwort_schreiben(buch: Adressbuch, klartext: str) -> None:
    buch.passwort = crypto.verschluesseln(klartext, _kontext(buch.id))


def zugang(buch: Adressbuch, db: Session | None = None) -> carddav.Zugang:
    """Wie sich nexmail bei diesem Buch ausweist.

    ⚠️ **Token schlägt Passwort.** Google lässt an seinen DAV-Endpunkten nur
    ``Bearer`` zu; Basic Auth wird abgewiesen, und die Meldung sieht aus wie
    ein falsches Passwort. Derselbe Zugang wie beim Kalender.
    """
    if buch.oauth_zugang_id and db is not None:
        from ..models import OauthZugang
        from . import mailoauth

        erlaubnis = db.get(OauthZugang, buch.oauth_zugang_id)
        if erlaubnis is None:
            raise AbgleichFehler("oauth_zustimmung_fehlt")
        return carddav.Zugang(
            url=buch.url,
            benutzer=buch.benutzer_name,
            passwort="",
            token=mailoauth.zugriffstoken(db, erlaubnis),
        )
    return carddav.Zugang(
        url=buch.url,
        benutzer=buch.benutzer_name,
        passwort=passwort_lesen(buch),
    )


# --- Verbinden ------------------------------------------------------------ #

#: Was hinter der Auswahl im Fenster steckt. ⚠️ **Die Adresse steht hier, nicht
#: in der Oberfläche**, sonst könnte man über das Formular jede beliebige
#: Adresse abrufen lassen, und „Anbieter: iCloud" wäre Zierde.
#:
#: ⚠️ **Beide ungemessen.** iCloud spricht CardDAV unter
#: ``contacts.icloud.com``; Google nur mit Token, und der Einstieg ist der
#: Principal mit der Kontoadresse im Pfad, so steht es in Googles
#: CardDAV-Beschreibung. Der erste Lauf gegen ein echtes Konto ist der
#: Massstab, nicht diese zwei Zeilen. Beta.
ANBIETER = {
    "icloud": "https://contacts.icloud.com",
    "google": "https://www.googleapis.com/carddav/v1/principals/{benutzer}/",
}


def _wurzel(art: str, adresse: str, benutzer: str) -> str:
    """Wo die Suche anfängt."""
    vorlage = ANBIETER.get(art)
    if not vorlage:
        return adresse.strip()
    if "{benutzer}" not in vorlage:
        return vorlage
    if not benutzer:
        raise AbgleichFehler("carddav_adresse_fehlt")
    return vorlage.format(benutzer=quote(benutzer, safe=""))


def finden(
    art: str, adresse: str, benutzer: str, passwort: str, token: str = ""
) -> list[carddav.FernBuch]:
    """Welche Adressbücher liegen unter diesem Zugang? Es wird nichts angelegt."""
    url = _wurzel(art, adresse, benutzer)
    if not url:
        raise AbgleichFehler("carddav_adresse_fehlt")
    gefunden = carddav.buecher_finden(
        carddav.Zugang(url=url, benutzer=benutzer, passwort=passwort, token=token)
    )
    # ⚠️ Auch der Erfolg gehört ins Protokoll, sonst ist „es kam keine Frage
    # nach den Büchern" nicht von „er fand keine" zu unterscheiden.
    logger.info("Address book discovery at %s found %d collection(s).", url, len(gefunden))
    return gefunden


def verbinden(
    db: Session,
    person: Benutzer,
    *,
    herkunft: str,
    benutzer_name: str,
    passwort: str,
    auswahl: list[tuple[str, str]],
    oauth_zugang_id: str = "",
) -> list[Adressbuch]:
    """Die ausgewählten Bücher als eigene Zeilen anlegen. ``auswahl`` ist
    eine Liste aus (Adresse, Name).

    ⚠️ **Was schon verbunden ist, wird nicht ein zweites Mal verbunden.** Sonst
    steht dasselbe Buch zweimal in der Spalte, und jede Karte kollidiert mit
    sich selbst an der Eindeutigkeit der Adresse. Nur das Doppel fällt weg,
    nicht der ganze Vorgang; ist nichts übrig, sagt die Kennung es.

    ⚠️ **Jede Zeile trägt ihre eigenen Zugangsdaten**, wie beim Kalender.
    """
    bekannt = {b.url for b in adressbuecher.meine(db, person) if b.url}
    auswahl = [(url, name) for url, name in auswahl if url not in bekannt]
    if not auswahl:
        raise AbgleichFehler("adressbuch_schon_verbunden")

    raus: list[Adressbuch] = []
    for url, name in auswahl:
        vorhanden = adressbuecher.meine(db, person)
        buch = Adressbuch(
            benutzer_id=person.id,
            name=(name or url).strip()[:120],
            farbe=adressbuecher.naechste_farbe(vorhanden),
            reihenfolge=len(vorhanden),
            art="carddav",
            herkunft=herkunft[:120],
            url=url,
            benutzer_name=benutzer_name,
            oauth_zugang_id=oauth_zugang_id or None,
        )
        db.add(buch)
        db.flush()
        # ⚠️ Bei OAuth gibt es kein Passwort, und es darf auch keines geben:
        # Ein leerer Chiffretext wäre ein leeres Passwort, kein „keines".
        if not oauth_zugang_id:
            passwort_schreiben(buch, passwort)
        raus.append(buch)
    db.commit()
    logger.info("%s address book(s) were connected.", len(raus))
    return raus


# --- Abgleichen ----------------------------------------------------------- #


def abgleichen(db: Session, buch: Adressbuch, erzwingen: bool = False) -> Runde:
    """Ein Buch mit seiner Gegenstelle abgleichen.

    ``erzwingen`` holt die Liste auch bei gleichem ``ctag``. Das ist der Weg
    für übergangene Karten, siehe den Kopf dieser Datei.
    """
    runde = Runde()
    if buch.art != "carddav":
        return runde

    # ⚠️ **Das Buch kann währenddessen getrennt worden sein.** Der Abgleich
    # läuft in einem eigenen Faden; wer im selben Moment auf „Trennen" drückt,
    # lässt irgendeinen dieser ``UPDATE``s auf null Zeilen laufen. SQLAlchemy
    # wirft dann ``StaleDataError`` und die Sitzung ist gesperrt; ohne dieses
    # Zurückrollen reisst es die ganze Runde mit, samt aller übrigen Bücher.
    # Beim Kalender am 03.09.2026 aus dem Betrieb gemeldet.
    kennung = buch.id
    try:
        try:
            runde = _carddav_abgleichen(db, buch, erzwingen)
            buch.letzter_fehler = ""
        except (carddav.CarddavFehler, caldav.CaldavFehler, AbgleichFehler) as f:
            # ⚠️ **Die Kennung, nicht der Satz.** Die Oberfläche übersetzt.
            buch.letzter_fehler = str(f)
            logger.info("Sync of address book %s failed: %s", kennung, f)
        buch.zuletzt_geprueft = utcnow()
        db.commit()
    except StaleDataError:
        logger.info("Address book %s vanished while it was being synced.", kennung)
        db.rollback()
    return runde


def _carddav_abgleichen(db: Session, buch: Adressbuch, erzwingen: bool) -> Runde:
    """Ein Buch abgleichen, über **eine** Verbindung.

    ⚠️ **Die Sitzung umschliesst den ganzen Abgleich.** iCloud lässt je Konto
    nur eine Verbindung zu; beim Kalender kosteten getrennte Verbindungen je
    Aufruf einen halben Tag Fehlersuche. Siehe ``caldav.sitzung``.

    ⚠️ **Was hier auf seine Karte wartet, hebelt das ``ctag`` aus.** Ein
    Kontakt, der in dieses Buch verschoben wurde, hat keine Adresse beim
    Anbieter (``href`` leer, ``schmutzig``). In Lieferung 1 geht er nicht
    hinaus. Kennt der Anbieter den Menschen aber längst, findet ihn der
    Abgleich über die Adresse wieder, und dafür muss er hinsehen. Dieselbe
    Rolle wie ``schmutzige`` beim Kalender.
    """
    runde = Runde()
    verbindung = zugang(buch, db)
    wartende = db.scalar(
        select(Kontakt.id)
        .where(Kontakt.adressbuch_id == buch.id, Kontakt.schmutzig.is_(True))
        .limit(1)
    )
    with carddav.sitzung(verbindung) as klient:
        runde = _holen(db, buch, verbindung, klient, runde, erzwingen or wartende is not None)
        # Was danach noch wartet, hat drüben keine Karte: hinaus damit.
        _wartende_hinaus(db, buch, klient, runde)
        return runde


def _holen(db, buch, verbindung, klient, runde: Runde, erzwingen: bool) -> Runde:
    ctag = carddav.ctag_holen(verbindung, klient)
    if ctag and ctag == buch.ctag and not erzwingen:
        runde.unveraendert = True
        return runde

    # ⚠️ **Verglichen wird über ``ortsschluessel``, nicht wörtlich.** Google
    # meldet einen Pfad anders kodiert zurück, als er geschrieben wurde;
    # wörtlich verglichen ist das ein unbekannter Eintrag UND eine
    # verschwundene Zeile, und der Abgleich legt bei jeder Runde neu an.
    fern_roh = carddav.etags_holen(verbindung, klient)
    fern = {carddav.ortsschluessel(k.url): k.etag for k in fern_roh}
    adresse_zu = {carddav.ortsschluessel(k.url): k.url for k in fern_roh}
    hier = {
        carddav.ortsschluessel(z.href): z
        for z in db.scalars(select(Kontakt).where(Kontakt.adressbuch_id == buch.id))
        if z.href
    }

    zu_holen = [
        adresse_zu[schluessel]
        for schluessel, etag in fern.items()
        if hier.get(schluessel) is None or hier[schluessel].etag != etag
    ]
    for karte in carddav.inhalte_holen(verbindung, zu_holen, klient).values():
        _uebernehmen(db, buch, hier, karte, runde)

    # Was hier liegt und dort nicht mehr, ist weg. Was noch keine Karte hat
    # (verschoben, wartet), steht nicht in ``hier`` und bleibt.
    weg = [zeile for schluessel, zeile in hier.items() if schluessel not in fern]
    if weg:
        kontaktdienst.mitgliedschaften_loesen(db, [z.id for z in weg])
        for zeile in weg:
            db.delete(zeile)
        runde.entfernt += len(weg)

    buch.ctag = ctag
    db.commit()
    logger.info(
        "Address book synced: %s new, %s changed, %s removed, %s held elsewhere.",
        runde.neu, runde.geaendert, runde.entfernt, runde.belegt,
    )
    return runde


def _uebernehmen(
    db: Session, buch: Adressbuch, hier: dict[str, Kontakt], karte: carddav.FernKarte, runde: Runde
) -> None:
    """Eine Karte in die Datenbank, nach den drei Regeln aus dem Kopf."""
    felder = kontaktdienst.felder_aus_vcard(karte.roh)
    # ⚠️ Eine kaputte Adresse gilt als keine. Die Karte kommt trotzdem an,
    # denn der Rest ist etwas wert; nur adressieren lässt sie sich nicht.
    adresse = ""
    if felder.get("adresse"):
        try:
            adresse = kontaktdienst.adresse_pruefen(felder["adresse"])
        except kontaktdienst.KontaktFehler:
            adresse = ""

    zeile = hier.get(carddav.ortsschluessel(karte.url))
    # ⚠️ **Je Benutzer, nicht je Buch.** So weit reicht die Eindeutigkeit.
    # Ohne Adresse gibt es keinen Inhaber und nichts zu verwechseln.
    inhaber = (
        db.scalar(
            select(Kontakt).where(
                Kontakt.benutzer_id == buch.benutzer_id, Kontakt.adresse == adresse
            )
        )
        if adresse
        else None
    )
    if inhaber is not None and inhaber is not zeile:
        # Eine bekannte Karte, deren Adresse jetzt anderswo liegt, bleibt auf
        # dem alten Stand: ihr ETag wird nicht nachgezogen, der nächste volle
        # Vergleich versucht es wieder.
        if zeile is not None or not _uebernehmbar(db, buch, inhaber):
            runde.belegt += 1  # Regeln 2 und 3
            return
        zeile = inhaber  # Regel 1, oder ein Verschobener, der auf seine Karte wartet

    frisch = zeile is None or zeile.adressbuch_id != buch.id
    if zeile is None:
        zeile = Kontakt(benutzer_id=buch.benutzer_id, adresse=adresse)
        db.add(zeile)
        # ⚠️ **Sofort schreiben, nicht erst am Ende der Runde.** Die Sitzung
        # flusht nicht von selbst; ohne diese Zeile sähe die nächste Karte
        # diese Zeile nicht. Zwei Karten mit derselben Adresse in einem Buch,
        # bei iCloud nach einem Zusammenführen ganz gewöhnlich, würden beide
        # angelegt, und die ganze Runde stürbe beim Commit an der
        # Eindeutigkeit, bei jedem Takt aufs Neue.
        db.flush()

    zeile.adressbuch_id = buch.id
    # Alle Felder der Karte in die Zeile, dann die Adresse nach den Regeln
    # oben: Die Liste traegt, was die Karte sagt, die Spalte, was hier gilt.
    kontaktdienst.felder_anwenden(zeile, kontaktdienst.felder_pruefen_lose(felder))
    zeile.adresse = adresse
    zeile.uid = felder.get("uid", "")[:255]
    zeile.href = karte.url.rstrip("/")
    zeile.etag = karte.etag[:255]
    # ⚠️ **Das Original bleibt liegen.** Es ist die Rückfahrkarte: Foto,
    # Geburtstag, weitere Anschriften, ``X-APPLE-…``. ``felder_aus_vcard``
    # wirft all das weg, und beim Zurückschreiben wäre es sonst verloren.
    zeile.roh = karte.roh
    # Eine Karte vom Anbieter ist gepflegt, auch wenn hier vorher ein
    # Platzhalter stand. Sonst räumte „Aufgeschnapptes wegwerfen" sie mit ab.
    zeile.quelle = "hand"
    zeile.schmutzig = False
    if frisch:
        runde.neu += 1
    else:
        runde.geaendert += 1


def _uebernehmbar(db: Session, buch: Adressbuch, inhaber: Kontakt) -> bool:
    """Darf die Karte diese Zeile übernehmen?

    Nur, wenn die Zeile keine eigene Karte hat, und dann entweder schon in
    diesem Buch wartet (verschoben) oder ein Platzhalter im lokalen Buch ist.
    Alles andere hat ein Mensch so hingelegt, und das bleibt.
    """
    if inhaber.href:
        return False  # Regel 3: gehört einer Karte bei einem anderen Anbieter
    if inhaber.adressbuch_id == buch.id:
        return True  # verschoben, wartet auf seine Karte
    if inhaber.quelle != "gesammelt":
        return False  # Regel 2
    heim = db.get(Adressbuch, inhaber.adressbuch_id) if inhaber.adressbuch_id else None
    # ⚠️ Regel 1 gilt nur aus dem lokalen Buch. Ein Aufgeschnappter, den jemand
    # in ein anderes verbundenes Buch gelegt hat, gehört dorthin, nicht hierher.
    return heim is None or heim.ist_lokal


def alle_abgleichen(db: Session, person: Benutzer, erzwingen: bool = False) -> dict[str, Runde]:
    """Jedes verbundene Buch einmal. ``erzwingen`` ist der Knopf in der
    Oberfläche, der Takt ruft ohne.

    ⚠️ **Ein Buch, das klemmt, hält die anderen nicht auf.** Sonst bringt eine
    falsche Adresse alles zum Stillstand. Und erst die Liste, dann die Arbeit:
    Über ein offenes Ergebnis zu laufen fasst die Sitzung bei jedem Schritt an,
    und die kann inzwischen gesperrt sein. Die Ausnahme fiele dann in der
    ``for``-Zeile an, also ausserhalb des ``try``.
    """
    raus: dict[str, Runde] = {}
    buecher = list(
        db.scalars(
            select(Adressbuch).where(Adressbuch.benutzer_id == person.id, Adressbuch.art != "")
        )
    )
    for buch in buecher:
        # Die Kennung vor der Arbeit merken: Nach einem gescheiterten
        # Schreibvorgang wirft schon das Lesen eines Feldes erneut.
        kennung = buch.id
        try:
            raus[kennung] = abgleichen(db, buch, erzwingen)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Sync of address book %s failed unexpectedly.", kennung)
    return raus


# --- Schreiben (Lieferung 2) ------------------------------------------------ #


def _buch_von(db: Session, kontakt: Kontakt) -> Adressbuch | None:
    """Das verbundene Buch dieses Kontakts, sonst ``None``."""
    if not kontakt.adressbuch_id:
        return None
    buch = db.get(Adressbuch, kontakt.adressbuch_id)
    if buch is None or buch.art != "carddav":
        return None
    return buch


def hochschieben(
    db: Session, kontakt: Kontakt, roh_neu: str | None = None, klient=None
) -> None:
    """Einen geänderten oder neuen Kontakt zum Anbieter bringen. Ohne ``commit``.

    ⚠️ **Das passiert sofort, nicht später.** Erst der Server, dann die eigene
    Datenbank; wer es andersherum macht, hat beim Konflikt zwei Fassungen und
    keine Regel, welche gilt. Bei einem 412 kommt ``carddav.Konflikt`` zum
    Aufrufer, und der fragt.

    ``roh_neu`` ist die fertig geänderte Karte aus dem Zeilen-Editor. Fehlt
    sie, wird sie hier aus der Zeile gebaut: auf der Rohkarte, die ein
    verschobener Kontakt mitbringt (Foto und Geburtstag gehören dem Menschen,
    nicht dem alten Buch), sonst frisch.

    ⚠️ **Der Dateiname folgt der UID**, wie beim Kalender: So findet auch ein
    anderer Client die Karte wieder, wenn er die Sammlung durchsieht.
    """
    buch = _buch_von(db, kontakt)
    if buch is None:
        return
    if roh_neu is None:
        # Auf der Rohkarte, die ein verschobener Kontakt mitbringt (Foto und
        # Geburtstag gehoeren dem Menschen, nicht dem alten Buch), sonst frisch.
        roh_neu = vcard.aktualisieren(
            kontakt.roh or "", kontaktdienst.felder_der_zeile(kontakt), kontakt.uid
        )
    if not kontakt.uid:
        kontakt.uid = kontaktdienst.felder_aus_vcard(roh_neu).get("uid", "")[:255]
    if not kontakt.href:
        sicher = "".join(c for c in kontakt.uid if c.isalnum() or c in "-_.@")[:120]
        basis = buch.url if buch.url.endswith("/") else buch.url + "/"
        kontakt.href = urljoin(basis, f"{sicher or uuid.uuid4()}.vcf")
    neues_etag = carddav.schreiben(zugang(buch, db), kontakt.href, roh_neu, kontakt.etag, klient)
    kontakt.roh = roh_neu
    kontakt.etag = neues_etag[:255]
    kontakt.schmutzig = False


def wegnehmen(db: Session, kontakt: Kontakt) -> None:
    """Die Karte beim Anbieter löschen. ⚠️ Erst dort, dann hier."""
    buch = _buch_von(db, kontakt)
    if buch is None or not kontakt.href:
        return
    carddav.loeschen(zugang(buch, db), kontakt.href, kontakt.etag)


def fremde_fassung(db: Session, kontakt: Kontakt) -> carddav.FernKarte | None:
    """Was gerade beim Anbieter unter dieser Adresse steht, **ohne** zu ändern.

    Gibt ``None``, wenn dort nichts (mehr) liegt: Dann hat jemand die Karte
    drüben gelöscht, und das ist ein anderer Fall als „woanders geändert".
    """
    buch = _buch_von(db, kontakt)
    if buch is None or not kontakt.href:
        return None
    treffer = carddav.inhalte_holen(zugang(buch, db), [kontakt.href])
    return treffer.get(carddav.ortsschluessel(kontakt.href))


def fremde_fassung_uebernehmen(db: Session, kontakt: Kontakt) -> bool:
    """Die Fassung des Anbieters gewinnt: die eigene Änderung fällt weg.

    ⚠️ **Nur diesen einen Kontakt, nicht das ganze Buch.** Ein voller Abgleich
    dauert und fasst alles an; wer einen Konflikt auflöst, meint genau diese
    eine Zeile. Eine Adresse, die hier schon ein anderer Eintrag hält, bleibt
    beim anderen — dieselbe Eindeutigkeit wie beim Abgleich.
    """
    karte = fremde_fassung(db, kontakt)
    if karte is None:
        return False
    felder = kontaktdienst.felder_aus_vcard(karte.roh)
    adresse = ""
    if felder.get("adresse"):
        try:
            adresse = kontaktdienst.adresse_pruefen(felder["adresse"])
        except kontaktdienst.KontaktFehler:
            adresse = ""
    if adresse:
        anderer = db.scalar(
            select(Kontakt).where(
                Kontakt.benutzer_id == kontakt.benutzer_id,
                Kontakt.adresse == adresse,
                Kontakt.id != kontakt.id,
            )
        )
        if anderer is not None:
            adresse = kontakt.adresse
    kontaktdienst.felder_anwenden(kontakt, kontaktdienst.felder_pruefen_lose(felder))
    kontakt.adresse = adresse
    kontakt.roh = karte.roh
    kontakt.etag = karte.etag[:255]
    kontakt.schmutzig = False
    db.commit()
    logger.info("A contact conflict was resolved in favour of the server.")
    return True


def frisch_machen(db: Session, kontakt: Kontakt) -> bool:
    """Nur ``roh`` und ``etag`` nachziehen, für „meine Fassung gewinnt".

    ⚠️ **Die eigenen Felder bleiben.** Was nexmail verwaltet, gewinnt; alles
    andere aus der fremden Fassung (Foto, weitere Nummern, ``X-APPLE-…``)
    bleibt stehen, statt überbügelt zu werden. Ohne das frische ``roh`` sässe
    die Änderung auf einem veralteten Original und holte fremde Zeilen
    zurück, die drüben längst weg sind.
    """
    karte = fremde_fassung(db, kontakt)
    if karte is None:
        return False
    kontakt.roh = karte.roh
    kontakt.etag = karte.etag[:255]
    return True


def _wartende_hinaus(db: Session, buch: Adressbuch, klient, runde: Runde) -> None:
    """Zeilen dieses Buches, die nach dem Holen noch warten, zum Anbieter bringen.

    Das sind Kontakte, die ins Buch verschoben wurden und deren Adresse der
    Anbieter nicht kannte (sonst hätte ``_holen`` sie an ihre Karte gehängt).
    ⚠️ **Ein Konflikt hält die Runde nicht an**: Die Zeile bleibt schmutzig
    und kommt beim nächsten Takt wieder dran.
    """
    wartende = list(
        db.scalars(
            select(Kontakt).where(Kontakt.adressbuch_id == buch.id, Kontakt.schmutzig.is_(True))
        )
    )
    for zeile in wartende:
        try:
            hochschieben(db, zeile, klient=klient)
            runde.hochgeschoben += 1
        except carddav.KonfliktFehler:
            logger.info("A waiting contact met a conflict at the provider; it stays queued.")
    if wartende:
        db.commit()
