"""Adressbücher mit ihrer Gegenstelle abgleichen. CardDAV, Lieferung 1: lesend.

⚠️ **Nur lesend, und das ist eine Entscheidung, keine Lücke.** Am 04.09.2026
abgestimmt: Der Abgleich geht in beide Richtungen, aber in zwei Lieferungen.
Diese hier holt. ``schmutzig`` wird gesetzt, aber nicht hinausgetragen. Wer
Lieferung 2 baut, nimmt ``kalenderabgleich.hochschieben`` als Vorbild, mit
``If-Match`` und demselben Konfliktfenster.

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
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .. import crypto
from ..meldung import Meldung
from ..models import Adressbuch, Benutzer, Kontakt, utcnow
from . import adressbuecher, caldav, carddav
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
        return _holen(db, buch, verbindung, klient, runde, erzwingen or wartende is not None)


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
    zeile.adresse = adresse
    zeile.name = felder.get("name", "")[:320]
    zeile.firma = felder.get("firma", "")[:320]
    zeile.telefon = felder.get("telefon", "")[:120]
    zeile.notiz = felder.get("notiz", "")
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
