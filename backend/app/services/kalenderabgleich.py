"""Kalender mit ihrer Gegenstelle abgleichen — CalDAV und ICS-Abos.

⚠️ **Erst der Server, dann die eigene Datenbank.** Dieselbe Regel wie bei jeder
Mail-Handlung: Wer einen Termin lokal ändert und erst später hochschiebt, hat
eine Anwendung, die nach jedem Handgriff lügt — und beim Konflikt muss er
raten, welche Fassung gilt. Deshalb geht eine Änderung in einem
CalDAV-Kalender **sofort** hinaus, und was der Server ablehnt, passiert hier
gar nicht erst.

⚠️ **Das ``ctag`` spart den ganzen Abruf.** Ändert es sich nicht, hat sich in
dem Kalender nichts getan. Bei einem Postfach macht das die ``UIDNEXT``.

⚠️ **Ein ICS-Abo hat kein ETag und keine Adresse je Termin.** Es ist eine
einzige Datei; abgeglichen wird sie, indem der ganze Bestand ersetzt wird.
Schreiben geht dorthin nie — das liegt am Format, nicht an Bequemlichkeit.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .. import crypto
from ..models import Benutzer, Kalender, Termin, utcnow
from . import caldav, vevent
from . import konten as kontendienst

logger = logging.getLogger("nexmail.kalenderabgleich")


class AbgleichFehler(RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class Runde:
    """Was ein Abgleich bewegt hat."""

    neu: int = 0
    geaendert: int = 0
    entfernt: int = 0
    hochgeladen: int = 0
    #: Wahr, wenn das ``ctag`` gleich war und nichts zu tun blieb.
    unveraendert: bool = False


def _kontext(kalender_id: str) -> str:
    return f"kalender:{kalender_id}:passwort"


def passwort_lesen(kalender: Kalender) -> str:
    return crypto.entschluesseln(kalender.passwort, _kontext(kalender.id))


def passwort_schreiben(kalender: Kalender, klartext: str) -> None:
    kalender.passwort = crypto.verschluesseln(klartext, _kontext(kalender.id))


def zugang(kalender: Kalender, db: Session | None = None) -> caldav.Zugang:
    """Wie sich nexmail bei diesem Kalender ausweist.

    ⚠️ **Token schlaegt Passwort.** Google laesst an seinem CalDAV-Endpunkt nur
    ``Bearer`` zu; Basic Auth wird abgewiesen, und die Meldung sieht aus wie
    ein falsches Passwort.
    """
    if kalender.oauth_zugang_id and db is not None:
        from ..models import OauthZugang
        from . import mailoauth

        erlaubnis = db.get(OauthZugang, kalender.oauth_zugang_id)
        if erlaubnis is None:
            raise AbgleichFehler("oauth_zustimmung_fehlt")
        return caldav.Zugang(
            url=kalender.url,
            benutzer=kalender.benutzer_name,
            passwort="",
            token=mailoauth.zugriffstoken(db, erlaubnis),
        )
    return caldav.Zugang(
        url=kalender.url,
        benutzer=kalender.benutzer_name,
        passwort=passwort_lesen(kalender),
    )


# --- Verbinden ------------------------------------------------------------ #

#: Was hinter der Auswahl im Fenster steckt. ⚠️ **Die Adresse steht hier, nicht
#: in der Oberflaeche** — sonst koennte man ueber das Formular jede beliebige
#: Adresse abrufen lassen, und „Anbieter: iCloud" waere Zierde.
ANBIETER = {
    "icloud": "https://caldav.icloud.com",
    # ⚠️ **Google spricht CalDAV nur mit einem Token.** Basic Auth an dieser
    # Adresse wird abgewiesen, und die Meldung sieht aus wie ein falsches
    # Passwort. Deshalb steht hier ``google`` nur zusammen mit einem Zugang.
    #
    # ⚠️ **Und die Adresse gehoert in den Pfad.** Anders als iCloud beantwortet
    # Google ein ``PROPFIND`` auf der blossen Wurzel nicht — dort kommt
    # ``caldav_abgewiesen`` zurueck, und das sieht aus wie eine fehlende
    # Zustimmung. Der Einstieg ist ``…/caldav/v2/<adresse>/user``; genau so
    # steht es in Googles eigener CalDAV-Beschreibung. Am 03.09.2026 an einem
    # echten Konto gemessen.
    "google": "https://apidata.googleusercontent.com/caldav/v2/{benutzer}/user",
}


def _wurzel(art: str, adresse: str, benutzer: str) -> str:
    """Wo die Suche anfaengt."""
    vorlage = ANBIETER.get(art)
    if not vorlage:
        return adresse.strip()
    if "{benutzer}" not in vorlage:
        return vorlage
    if not benutzer:
        # Ohne Adresse gibt es bei Google keinen Einstieg — und ein Aufruf
        # gegen ``…/v2//user`` endete in einer Absage, die nach falschem
        # Passwort aussieht.
        raise AbgleichFehler("caldav_adresse_fehlt")
    return vorlage.format(benutzer=quote(benutzer, safe=""))


def finden(
    art: str, adresse: str, benutzer: str, passwort: str, token: str = ""
) -> list[caldav.FernKalender]:
    """Welche Kalender liegen unter diesem Zugang?"""
    url = _wurzel(art, adresse, benutzer)
    if not url:
        raise AbgleichFehler("caldav_adresse_fehlt")
    gefunden = caldav.kalender_finden(
        caldav.Zugang(url=url, benutzer=benutzer, passwort=passwort, token=token)
    )
    # ⚠️ **Auch der Erfolg gehoert ins Protokoll.** „Es kam keine Frage nach
    # den Kalendern" liess sich am 03.09.2026 nicht beantworten: Ein gelungener
    # Suchlauf hinterliess keine Spur, und damit war nicht zu unterscheiden, ob
    # er lief und nichts fand oder gar nicht erst lief.
    logger.info("Calendar discovery at %s found %d collection(s).", url, len(gefunden))
    return gefunden


def verbinden(
    db: Session,
    person: Benutzer,
    *,
    herkunft: str,
    benutzer_name: str,
    passwort: str,
    auswahl: list[tuple[str, str]],
    farben: list[int] | None = None,
    oauth_zugang_id: str = "",
) -> list[Kalender]:
    """Die ausgewählten Fern-Kalender als eigene Zeilen anlegen.

    ``auswahl`` ist eine Liste aus (Adresse, Name).

    ⚠️ **Jede Zeile trägt ihre eigenen Zugangsdaten.** Sie zu teilen hiesse,
    eine zweite Tabelle einzufuehren — und ein geloeschter Kalender riesse
    dann die anderen mit.
    """
    from .termine import liste, naechste_farbe

    # ⚠️ **Was schon verbunden ist, wird nicht ein zweites Mal verbunden.**
    # Sonst steht derselbe Google-Kalender zweimal in der Spalte, jeder Termin
    # doppelt — und wer eine der beiden Zeilen entfernt, sieht danach den
    # Termin, den er gerade offen hatte, als „gibt es nicht mehr". Genau so am
    # 03.09.2026 aus dem Betrieb gemeldet.
    bekannt = {k.url for k in liste(db, person) if k.url}
    auswahl = [(url, name) for url, name in auswahl if url not in bekannt]
    if not auswahl:
        raise AbgleichFehler("kalender_schon_verbunden")

    raus: list[Kalender] = []
    for i, (url, name) in enumerate(auswahl):
        vorhanden = liste(db, person)
        kalender = Kalender(
            benutzer_id=person.id,
            name=(name or url).strip()[:120],
            farbe=(farben[i] if farben and i < len(farben) else 0) or naechste_farbe(vorhanden),
            reihenfolge=len(vorhanden),
            art="caldav",
            herkunft=herkunft[:120],
            url=url,
            benutzer_name=benutzer_name,
            oauth_zugang_id=oauth_zugang_id or None,
        )
        db.add(kalender)
        db.flush()
        # ⚠️ Bei OAuth gibt es kein Passwort — und es darf auch keines geben:
        # Ein leerer Chiffretext waere ein leeres Passwort, kein „keines".
        if not oauth_zugang_id:
            passwort_schreiben(kalender, passwort)
        raus.append(kalender)
    db.commit()
    logger.info("%s calendar(s) were connected.", len(raus))
    return raus


def abonnieren(
    db: Session, person: Benutzer, *, url: str, name: str, farbe: int = 0
) -> Kalender:
    """Einen veröffentlichten ICS-Link abonnieren. **Immer nur lesen.**"""
    from .termine import liste, naechste_farbe

    if not url.strip():
        raise AbgleichFehler("abo_adresse_fehlt")
    vorhanden = liste(db, person)
    # ⚠️ Dieselbe Regel wie beim Verbinden: Ein Abo, das zweimal dasteht, zeigt
    # jeden Feiertag doppelt.
    if any(k.url == url.strip() for k in vorhanden):
        raise AbgleichFehler("kalender_schon_verbunden")
    kalender = Kalender(
        benutzer_id=person.id,
        name=(name or url).strip()[:120],
        farbe=farbe if farbe in range(1, 7) else naechste_farbe(vorhanden),
        reihenfolge=len(vorhanden),
        art="ics",
        herkunft=url.split("/")[2][:120] if "//" in url else url[:120],
        url=url.strip(),
    )
    db.add(kalender)
    db.commit()
    logger.info("A calendar was subscribed.")
    return kalender


# --- Abgleichen ----------------------------------------------------------- #


def _uebernehmen(db: Session, kalender: Kalender, roh: str, href: str, etag: str) -> tuple[int, int]:
    """Die ``VEVENT`` einer Datei in die Datenbank. Rückgabe: neu, geändert.

    ⚠️ **Eine Datei kann mehrere Termine enthalten** — eine Reihe samt ihren
    überschriebenen Einzelterminen. Wer nur den ersten übernimmt, verliert die
    Ausnahmen.
    """
    neu = geaendert = 0
    gesehen: set[tuple[str, str]] = set()

    for daten in vevent.lesen(roh):
        if not daten["uid"] or daten["beginn"] is None:
            continue
        gesehen.add((daten["uid"], daten["recurrence_id"]))
        zeile = db.scalar(
            select(Termin).where(
                Termin.kalender_id == kalender.id,
                Termin.uid == daten["uid"],
                Termin.recurrence_id == daten["recurrence_id"],
            )
        )
        frisch = zeile is None
        if zeile is None:
            zeile = Termin(
                kalender_id=kalender.id,
                benutzer_id=kalender.benutzer_id,
                uid=daten["uid"],
                recurrence_id=daten["recurrence_id"],
            )
            db.add(zeile)
            neu += 1

        werte = {
            "href": href,
            "etag": etag,
            # ⚠️ **Das Original bleibt liegen.** Es ist die Rueckfahrkarte:
            # Alles, was nexmail nicht versteht — Alarme, Teilnehmer,
            # X-APPLE-… —, geht beim Zurueckschreiben sonst verloren.
            "roh": roh,
            **{
                feld: daten[feld]
                for feld in (
                    "titel", "beschreibung", "ort", "beginn", "ende", "ganztaegig",
                    "zeitzone", "rrule", "exdate", "sequenz", "status", "erinnerung",
                )
            },
            # ⚠️ Als JSON, weil die Zahl der Teilnehmer offen ist — und weil
            # nexmail sie nur anzeigt. Wer je danach sucht, hat den Punkt
            # erreicht, an dem sich eine eigene Tabelle lohnt.
            "organisator": json.dumps(daten["organisator"]) if daten["organisator"] else "",
            "teilnehmer": json.dumps(daten["teilnehmer"]) if daten["teilnehmer"] else "",
        }

        # ⚠️ **„Geaendert" heisst geaendert, nicht „noch einmal geschrieben".**
        # Vorher zaehlte jede bekannte Zeile mit — bei einem ICS-Abo also der
        # ganze Bestand, bei jedem Klick auf Aktualisieren. „53 geaendert" ohne
        # eine einzige Aenderung ist keine Auskunft, sondern ein Schrecken.
        # Am 03.09.2026 aus dem Betrieb gemeldet.
        anders = any(getattr(zeile, feld) != wert for feld, wert in werte.items())
        if not frisch and not anders:
            continue
        if not frisch:
            geaendert += 1
        for feld, wert in werte.items():
            setattr(zeile, feld, wert)
        zeile.schmutzig = False
        zeile.geaendert = utcnow()

    # Was unter dieser Adresse lag und nicht mehr in der Datei steht, ist weg.
    for alt in list(
        db.scalars(select(Termin).where(Termin.kalender_id == kalender.id, Termin.href == href))
    ):
        if (alt.uid, alt.recurrence_id) not in gesehen:
            db.delete(alt)
    return neu, geaendert


def hochschieben(db: Session, termin: Termin, alarm_ersetzen: bool = False) -> None:
    """Einen geänderten Termin zum Server bringen.

    ⚠️ **Das passiert sofort, nicht später.** Erst der Server, dann die eigene
    Datenbank — wer es andersherum macht, hat beim Konflikt zwei Fassungen und
    keine Regel, welche gilt.

    ⚠️ **Bei einem Konflikt wird NICHTS überschrieben.** Der Aufrufer bekommt
    ``caldav_konflikt`` und fragt.
    """
    kalender = termin.kalender
    if kalender.art != "caldav":
        return
    if not termin.href:
        # ⚠️ Der Dateiname folgt der UID — so findet auch ein anderer Client
        # den Termin wieder, wenn er die Sammlung durchsieht.
        sicher = "".join(c for c in termin.uid if c.isalnum() or c in "-_.@")[:120]
        termin.href = urljoin(kalender.url, f"{sicher or uuid.uuid4()}.ics")
    # ⚠️ **Der Alarm wird nur ersetzt, wenn jemand ihn angefasst hat.** Sonst
    # gilt die Rueckfahrkarte: nicht anfassen. Wer bei jedem Speichern die
    # Alarme neu schreibt, wirft einem fremden Termin seinen Alarm mit
    # E-Mail-Aktion oder festem Zeitpunkt weg.
    ics = vevent.aktualisieren(
        termin.roh, termin, datetime.now(timezone.utc), alarm_ersetzen=alarm_ersetzen
    )
    neues_etag = caldav.schreiben(zugang(kalender, db), termin.href, ics, termin.etag)
    termin.roh = ics
    termin.etag = neues_etag
    termin.schmutzig = False


def wegnehmen(db: Session, kalender: Kalender, href: str, etag: str) -> None:
    """Einen Termin beim Server löschen. ⚠️ Erst dort, dann hier."""
    if kalender.art != "caldav" or not href:
        return
    caldav.loeschen(zugang(kalender, db), href, etag)


def abgleichen(db: Session, kalender: Kalender) -> Runde:
    """Einen Kalender mit seiner Gegenstelle abgleichen."""
    runde = Runde()
    if not kalender.art:
        return runde

    # ⚠️ **Der Kalender kann waehrenddessen entfernt worden sein.** Der Abgleich
    # laeuft in einem eigenen Faden; wer im selben Moment auf „Entfernen"
    # drueckt, laesst irgendeinen dieser ``UPDATE``s auf null Zeilen laufen —
    # nicht nur den letzten, denn auch der Abgleich selbst schreibt zwischen-
    # durch. SQLAlchemy wirft dann ``StaleDataError`` und die Sitzung ist
    # gesperrt; ohne dieses Zurueckrollen reisst es die ganze Runde mit, samt
    # aller uebrigen Kalender. Am 03.09.2026 aus dem Betrieb gemeldet.
    kennung = kalender.id
    try:
        try:
            if kalender.art == "ics":
                runde = _abo_abgleichen(db, kalender)
            else:
                runde = _caldav_abgleichen(db, kalender)
            kalender.letzter_fehler = ""
        except (caldav.CaldavFehler, AbgleichFehler) as f:
            # ⚠️ **Die Kennung, nicht der Satz.** Die Oberflaeche uebersetzt —
            # ein deutscher Satz aus dem Server bliebe auf Englisch deutsch.
            kalender.letzter_fehler = str(f)
            logger.info("Sync of calendar %s failed: %s", kennung, f)
        kalender.zuletzt_geprueft = utcnow()
        db.commit()
    except StaleDataError:
        logger.info("Calendar %s vanished while it was being synced.", kennung)
        db.rollback()
    return runde


def _caldav_abgleichen(db: Session, kalender: Kalender) -> Runde:
    runde = Runde()
    verbindung = zugang(kalender, db)

    # 1. Erst hinaus, was hier geändert wurde.
    schmutzige = list(
        db.scalars(
            select(Termin).where(Termin.kalender_id == kalender.id, Termin.schmutzig.is_(True))
        )
    )
    for termin in schmutzige:
        try:
            hochschieben(db, termin)
            runde.hochgeladen += 1
        except caldav.Konflikt:
            # ⚠️ Stehen lassen. Der naechste Abruf holt die Serverfassung, und
            # die Oberflaeche zeigt beide — ueberschrieben wird nichts.
            logger.info("Event %s conflicts with the server; kept.", termin.id)
    if schmutzige:
        db.commit()

    # 2. Hat sich dort überhaupt etwas getan?
    ctag = caldav.ctag_holen(verbindung)
    if ctag and ctag == kalender.ctag and not schmutzige:
        runde.unveraendert = True
        return runde

    # 3. Was liegt dort, und in welcher Fassung?
    #
    # ⚠️ **Verglichen wird ueber ``ortsschluessel``, nicht woertlich.** Google
    # nimmt ein ``PUT`` auf ``…/<uid>@nexmail.ics`` an und meldet denselben
    # Termin danach als ``…/<uid>%40nexmail.ics``. Woertlich verglichen ist das
    # ein unbekannter Eintrag **und** eine verschwundene Zeile: Der Abgleich
    # legte den Termin neu an und loeschte den eigenen — **bei jeder Runde**.
    # „Sobald ich aktualisieren klicke ist alles weg oder verschoben", am
    # 03.09.2026 aus dem Betrieb gemeldet.
    fern_roh = caldav.etags_holen(verbindung)
    fern = {caldav.ortsschluessel(t.href): t.etag for t in fern_roh}
    adresse_zu = {caldav.ortsschluessel(t.href): t.href for t in fern_roh}
    hier = {
        caldav.ortsschluessel(z.href): z
        for z in db.scalars(select(Termin).where(Termin.kalender_id == kalender.id))
        if z.href
    }

    zu_holen = [
        adresse_zu[schluessel]
        for schluessel, etag in fern.items()
        if hier.get(schluessel) is None or hier[schluessel].etag != etag
    ]
    for stueck in caldav.inhalte_holen(verbindung, zu_holen):
        neu, geaendert = _uebernehmen(db, kalender, stueck.roh, stueck.href.rstrip("/"), stueck.etag)
        runde.neu += neu
        runde.geaendert += geaendert

    # 4. Was hier liegt und dort nicht mehr, ist weg.
    for schluessel, zeile in hier.items():
        if schluessel not in fern:
            db.delete(zeile)
            runde.entfernt += 1

    kalender.ctag = ctag
    db.commit()
    logger.info(
        "Calendar synced: %s new, %s changed, %s removed, %s uploaded.",
        runde.neu, runde.geaendert, runde.entfernt, runde.hochgeladen,
    )
    return runde


def _abo_abgleichen(db: Session, kalender: Kalender) -> Runde:
    """Ein ICS-Abo: eine Datei, ganzer Bestand.

    ⚠️ **Ersetzt statt zusammengeführt.** Ein Abo hat keine Adressen je Termin
    und kein ETag — was aus der Datei verschwunden ist, ist abgesagt worden,
    und ein Termin, der stehen bliebe, würde nie wieder verschwinden.
    """
    runde = Runde()
    # ⚠️ **Erst fragen, dann holen.** Ein Abo hat kein ``ctag``; die Marke aus
    # ``ETag``/``Last-Modified`` uebernimmt die Rolle. Antwortet der Server
    # 304, ist nichts zu tun — vorher lud nexmail bei jedem Takt die ganze
    # Datei und meldete danach „53 geaendert", obwohl sich nichts getan hatte.
    abo = caldav.abo_holen(kalender.url, marke=kalender.ctag)
    if abo.unveraendert:
        runde.unveraendert = True
        return runde
    neu, geaendert = _uebernehmen(db, kalender, abo.roh, kalender.url, "")
    runde.neu, runde.geaendert = neu, geaendert
    kalender.ctag = abo.marke
    db.commit()
    return runde


def alle_abgleichen(db: Session, person: Benutzer) -> dict[str, Runde]:
    """Jeden verbundenen Kalender einmal. ⚠️ Ein Kalender, der klemmt, hält
    die anderen nicht auf — sonst bringt eine falsche Adresse alles zum
    Stillstand."""
    raus: dict[str, Runde] = {}
    # ⚠️ **Erst die Liste, dann die Arbeit.** Ueber ein offenes Ergebnis zu
    # laufen heisst, bei jedem Schritt die Sitzung anzufassen — und die kann
    # inzwischen gesperrt sein. Die Ausnahme faellt dann in der ``for``-Zeile
    # an, also **ausserhalb** des ``try``, und die ganze Runde stirbt.
    kalender_alle = list(
        db.scalars(
            select(Kalender).where(Kalender.benutzer_id == person.id, Kalender.art != "")
        )
    )
    for kalender in kalender_alle:
        # Die Kennung vor der Arbeit merken: Nach einem gescheiterten
        # Schreibvorgang wirft schon das Lesen eines Feldes erneut.
        kennung = kalender.id
        try:
            raus[kennung] = abgleichen(db, kalender)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Sync of calendar %s failed unexpectedly.", kennung)
    return raus
