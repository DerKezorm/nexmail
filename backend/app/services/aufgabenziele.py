"""Wer eine Aufgabe verwaltet: nexmail selbst oder eine verbundene Todo-App.

⚠️ **Eine Mail, eine Aufgabe — ueber alle Ziele hinweg.** Wer eine Mail
zweimal zur Aufgabe macht, bekommt die vorhandene zurueck, egal wo sie liegt.
Dieselbe Regel wie bei „Zu Aufgabe machen" seit jeher: Ein Doppel muesste man
zweimal abhaken, in zwei Programmen sogar.

⚠️ **Liegt die Aufgabe in einer Todo-App, gehoert ihr der Haken.** nexmail
merkt sich die Aufgabe trotzdem (an der Mail und in der Liste) und zieht im
Abgleich nach, was die App sagt: erledigt, wieder offen, geloescht, neues
Datum. Abhaken in nexmail geht zuerst zur App; was sie ablehnt, aendert hier
nichts.

⚠️ **Hinaus geht nur, was der Mensch im Fenster sieht:** Titel, Faelligkeit,
Absender und ein Link zurueck zur Mail. Der Text der Mail bleibt hier — mit
einer Ausnahme: ein Webhook, an dem der Benutzer es eingeschaltet und der
Betreiber es erlaubt hat (``webhook.py``).

⚠️ **Ein Webhook ist die andere Richtung.** Er laesst sich nicht fragen, also
gehoert der Haken dort nexmail: Abhaken hier geht als Ereignis hinaus, und der
Abgleich laesst Webhooks aus. Zurueck kommt ein Haken nur ueber ``/api/v1``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import crypto
from ..config import get_settings
from ..db import einstellung_lesen
from ..meldung import Meldung
from ..models import Aufgabe, Aufgabenverbindung, Benutzer, Konto, Nachricht, neue_id
from . import adresse as adressdienst
from . import aufgaben, bereinigen, todoist, webhook

logger = logging.getLogger("nexmail.aufgabenziele")

#: Die Arten, die es gibt. Weitere kommen als eigener Dienst dazu.
ARTEN = ("todoist", "webhook")

#: Was ein Fehler einer Todo-App sein kann. Beide tragen eine Kennung.
AppFehler = (todoist.TodoistFehler, webhook.WebhookFehler)

#: ⚠️ **Ein Deckel fuer den Text der Mail**, je Feld. Ein Newsletter mit
#: eingebetteten Bildern kommt sonst als mehrere Megabyte JSON beim Empfaenger
#: an; was abgeschnitten ist, sagt ``text_truncated``.
MAX_MAILTEXT = 500_000

#: ⚠️ **Erledigte werden noch so lange nachgesehen**, damit ein Wieder-Oeffnen
#: in der App auch hier ankommt. Danach gilt der letzte Stand; sonst fragte
#: jeder Abgleich nach Jahren an Erledigtem.
NACHSEHEN_ERLEDIGTE = timedelta(days=30)

#: Ein Abgleich beim Oeffnen der Liste kommt hoechstens so oft. Der Takt
#: laeuft ohnehin; das hier ist nur der schnelle Blick dazwischen.
OEFFNEN_PAUSE = 15.0
_zuletzt_beim_oeffnen: dict[str, float] = {}


class ZielFehler(Meldung):
    """Mit einer Kennung, die man zeigen kann."""


@dataclass
class Liste:
    #: ``<verbindung>:<liste>``, so wie es beim Anlegen zurueckkommt.
    ziel: str
    name: str


@dataclass
class Gruppe:
    verbindung_id: str
    art: str
    name: str
    #: Leer, wenn die Listen kamen. Sonst die Kennung, warum nicht.
    fehler: str = ""
    listen: list[Liste] = field(default_factory=list)


def _kontext(verbindung_id: str) -> str:
    return f"aufgabenverbindung:{verbindung_id}:zugang"


def _zugang(v: Aufgabenverbindung) -> str:
    return crypto.entschluesseln(v.zugang, _kontext(v.id))


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _fehler_merken(v: Aufgabenverbindung, fehler: Meldung) -> None:
    v.letzter_fehler = fehler.kennung[:80]


# --- Verbindungen ---------------------------------------------------------- #


def verbindungen(db: Session, person: Benutzer) -> list[Aufgabenverbindung]:
    return list(
        db.scalars(
            select(Aufgabenverbindung)
            .where(Aufgabenverbindung.benutzer_id == person.id)
            .order_by(Aufgabenverbindung.angelegt, Aufgabenverbindung.id)
        )
    )


def eine_verbindung(db: Session, person: Benutzer, verbindung_id: str) -> Aufgabenverbindung:
    v = db.get(Aufgabenverbindung, verbindung_id)
    if v is None or v.benutzer_id != person.id:
        raise ZielFehler("aufgabenverbindung_unbekannt")
    return v


def verbinden(db: Session, person: Benutzer, art: str, zugang: str, name: str = "") -> Aufgabenverbindung:
    """Eine Todo-App verbinden — erst pruefen, dann speichern.

    ⚠️ **Ein Token, den die App ablehnt, wird nie gespeichert.** Sonst stuende
    eine Verbindung da, die beim ersten Handgriff scheitert, und der Fehler
    zeigte sich weit weg von der Stelle, an der er entstand.

    ⚠️ **Nur Apps mit Token.** Ein Webhook braucht eine Adresse und ein
    Geheimnis statt eines Tokens und kommt ueber ``webhook_verbinden``.
    """
    if art != "todoist":
        raise ZielFehler("aufgabenart_unbekannt")
    zugang = zugang.strip()
    todoist.listen(zugang)

    v = Aufgabenverbindung(id=neue_id(), benutzer_id=person.id, art=art, name=name.strip()[:80])
    v.zugang = crypto.verschluesseln(zugang, _kontext(v.id))
    db.add(v)
    db.commit()
    logger.info("A to-do app was connected (%s).", art)
    return v


def trennen(db: Session, person: Benutzer, verbindung_id: str) -> None:
    """Die Verbindung loesen. ⚠️ **In der App bleibt alles, wie es ist.**

    Die Aufgaben hier behalten Abzug und Link, nur abgeglichen wird nicht
    mehr. Zeigt der Standard auf diese Verbindung, gilt wieder die eigene
    Liste.
    """
    v = eine_verbindung(db, person, verbindung_id)
    for a in db.scalars(select(Aufgabe).where(Aufgabe.verbindung_id == v.id)):
        a.verbindung_id = None
    if person.aufgaben_standard.split(":", 1)[0] == v.id:
        person.aufgaben_standard = ""
    db.delete(v)
    db.commit()
    logger.info("A to-do app was disconnected.")


# --- Webhook ----------------------------------------------------------------- #


@dataclass
class WebhookStand:
    url: str
    nur_senden: bool
    mit_text: bool


def _webhook(db: Session, person: Benutzer, verbindung_id: str) -> Aufgabenverbindung:
    v = eine_verbindung(db, person, verbindung_id)
    if v.art != "webhook":
        raise ZielFehler("aufgabenverbindung_unbekannt")
    return v


def _ping(zugang: webhook.Zugang, name: str) -> None:
    """⚠️ **Erst ein ``ping``, dann speichern**, wie beim Todoist-Token: Eine
    Adresse, die nicht mit 2xx antwortet, stuende sonst als Verbindung da und
    scheiterte erst beim ersten „Zu Aufgabe machen"."""
    webhook.senden(zugang, "ping", {"connection": {"name": name}})


def webhook_verbinden(
    db: Session,
    person: Benutzer,
    url: str,
    *,
    name: str = "",
    geheimnis: str = "",
    nur_senden: bool = False,
    mit_text: bool = False,
) -> tuple[Aufgabenverbindung, str]:
    """Einen Webhook verbinden. Gibt die Verbindung und das Geheimnis zurueck.

    ⚠️ **Das Geheimnis kommt genau einmal heraus**, wie ein API-Schluessel.
    Ohne eigenes erzeugt nexmail eins. Wer es verliert, trennt und verbindet
    neu.
    """
    url = webhook.adresse_bereinigen(url)
    geheimnis = geheimnis.strip() or webhook.neues_geheimnis()
    if len(geheimnis) > webhook.MAX_GEHEIMNIS:
        raise ZielFehler("webhook_geheimnis_zu_lang", max=webhook.MAX_GEHEIMNIS)
    zugang = webhook.Zugang(url=url, geheimnis=geheimnis)
    name = name.strip()[:80]
    _ping(zugang, name)

    v = Aufgabenverbindung(
        id=neue_id(),
        benutzer_id=person.id,
        art="webhook",
        name=name,
        nur_senden=nur_senden,
        mit_text=mit_text,
    )
    v.zugang = crypto.verschluesseln(webhook.zugang_schreiben(zugang), _kontext(v.id))
    db.add(v)
    db.commit()
    logger.info("A webhook was connected.")
    return v, geheimnis


def webhook_stand(db: Session, person: Benutzer, verbindung_id: str) -> WebhookStand:
    v = _webhook(db, person, verbindung_id)
    return WebhookStand(
        url=webhook.zugang_lesen(_zugang(v)).url, nur_senden=v.nur_senden, mit_text=v.mit_text
    )


def webhook_aendern(
    db: Session, person: Benutzer, verbindung_id: str, *, url: str, nur_senden: bool, mit_text: bool
) -> WebhookStand:
    """⚠️ **Eine neue Adresse bekommt erst ihr ``ping``**, sonst bleibt die alte.
    Das Geheimnis bleibt dasselbe; der Empfaenger muss nichts nachtragen."""
    v = _webhook(db, person, verbindung_id)
    zugang = webhook.zugang_lesen(_zugang(v))
    url = webhook.adresse_bereinigen(url)
    if url != zugang.url:
        neu = webhook.Zugang(url=url, geheimnis=zugang.geheimnis)
        _ping(neu, v.name)
        v.zugang = crypto.verschluesseln(webhook.zugang_schreiben(neu), _kontext(v.id))
        v.letzter_fehler = ""
    v.nur_senden = nur_senden
    v.mit_text = mit_text
    db.commit()
    return WebhookStand(url=url, nur_senden=v.nur_senden, mit_text=v.mit_text)


def webhook_testen(db: Session, person: Benutzer, verbindung_id: str) -> None:
    """Der Knopf „Test senden". Der Fehler steht danach auch an der Verbindung."""
    v = _webhook(db, person, verbindung_id)
    try:
        _ping(webhook.zugang_lesen(_zugang(v)), v.name)
    except webhook.WebhookFehler as fehler:
        _fehler_merken(v, fehler)
        db.commit()
        raise
    v.letzter_fehler = ""
    db.commit()


# --- Ziele ----------------------------------------------------------------- #


def ziele(db: Session, person: Benutzer) -> list[Gruppe]:
    """Je Verbindung ihre Listen, live geholt.

    ⚠️ **Eine Verbindung, die klemmt, nimmt die anderen nicht mit.** Sie steht
    mit ihrer Kennung da und ohne Listen; die eigene Liste und die anderen Apps
    bleiben waehlbar.
    """
    heraus: list[Gruppe] = []
    for v in verbindungen(db, person):
        gruppe = Gruppe(verbindung_id=v.id, art=v.art, name=v.name)
        if v.art == "webhook":
            # Ein Webhook hat genau eine Liste, und fragen laesst er sich nicht:
            # Sie heisst nach dem Rechner, an den gesendet wird.
            try:
                url = webhook.zugang_lesen(_zugang(v)).url
            except (webhook.WebhookFehler, crypto.SchluesselFehler) as fehler:
                gruppe.fehler = fehler.kennung
            else:
                gruppe.listen = [Liste(ziel=f"{v.id}:{webhook.LISTE}", name=webhook.ziel_name(url))]
            heraus.append(gruppe)
            continue
        try:
            gruppe.listen = [
                Liste(ziel=f"{v.id}:{l.id}", name=l.name) for l in todoist.listen(_zugang(v))
            ]
            v.letzter_fehler = ""
        except todoist.TodoistFehler as fehler:
            gruppe.fehler = fehler.kennung
            _fehler_merken(v, fehler)
        heraus.append(gruppe)
    db.commit()
    return heraus


def _zerlegen(db: Session, person: Benutzer, ziel: str) -> tuple[Aufgabenverbindung, str]:
    verbindung_id, _, liste_id = ziel.partition(":")
    if not verbindung_id or not liste_id:
        raise ZielFehler("aufgabenziel_unbekannt")
    return eine_verbindung(db, person, verbindung_id), liste_id


def standard_von(db: Session, person: Benutzer) -> str:
    ziel = person.aufgaben_standard or ""
    if not ziel:
        return ""
    v = db.get(Aufgabenverbindung, ziel.split(":", 1)[0])
    return ziel if v is not None and v.benutzer_id == person.id else ""


def standard_setzen(db: Session, person: Benutzer, ziel: str) -> str:
    """⚠️ Die Liste selbst wird nicht live geprueft: Das kostete eine Anfrage
    bei der App fuer eine Wahl, die eben aus deren Liste kam. Verschwindet sie
    dort, sagt es der erste Handgriff."""
    ziel = ziel.strip()
    if ziel:
        _zerlegen(db, person, ziel)
    person.aufgaben_standard = ziel
    db.commit()
    return ziel


# --- Anlegen ----------------------------------------------------------------- #


def mail_link(db: Session, message_id: str, vom_browser: str = "") -> str:
    """Der Weg zurueck zur Mail, oder leer.

    ⚠️ **Ueber die ``Message-ID``, nie ueber die Zeilennummer.** Die Zeile
    wechselt, sobald die Mail vom Telefon aus in einen anderen Ordner wandert;
    ein Link, der monatelang in einer Todo-App steht, fuehrte dann ins Leere.

    ⚠️ **Die oeffentliche Adresse geht vor**, wie beim QR-Code der App: Wer
    nexmail zu Hause ueber eine IP aufruft, will in Todoist trotzdem den Link,
    der auch unterwegs geht.
    """
    if not message_id:
        return ""
    eingestellt = adressdienst.fuer_modul(
        einstellung_lesen(db, "oeffentliche_adresse"), get_settings().url_base
    )
    for kandidat in (eingestellt, vom_browser.strip().rstrip("/")):
        teile = urlsplit(kandidat)
        if teile.scheme in ("http", "https") and teile.netloc:
            return f"{kandidat}/?mail={quote(message_id, safe='')}"
    return ""


def _beschreibung(nachricht: Nachricht, link: str) -> str:
    """⚠️ **Ohne Worte in einer Sprache.** Der Text steht in Todoist, das in
    jeder Sprache laufen kann; „Absender:" waere fuer die Haelfte falsch."""
    zeilen = []
    if nachricht.von_name and nachricht.von_adresse:
        zeilen.append(f"{nachricht.von_name} <{nachricht.von_adresse}>")
    elif nachricht.von_adresse or nachricht.von_name:
        zeilen.append(nachricht.von_adresse or nachricht.von_name)
    if link:
        zeilen.append(f"[nexmail ↗]({link})")
    elif nachricht.message_id:
        zeilen.append(f"Message-ID: {nachricht.message_id}")
    return "\n".join(zeilen)


def _vorhanden(db: Session, person: Benutzer, nachricht: Nachricht) -> Aufgabe | None:
    if not nachricht.message_id:
        return None
    return db.scalars(
        select(Aufgabe).where(
            Aufgabe.benutzer_id == person.id, Aufgabe.message_id == nachricht.message_id
        )
    ).first()


def _als_zeitpunkt(tag: date | None) -> datetime | None:
    # Dieselbe Form, in der die Oberflaeche ein Datum schickt: Mitternacht UTC.
    return datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc) if tag else None


def anlegen(
    db: Session,
    person: Benutzer,
    nachricht_id: int,
    *,
    ziel: str,
    titel: str = "",
    liste_name: str = "",
    faellig: date | None = None,
    vom_browser: str = "",
    koerper: Callable[[Nachricht], None] | None = None,
) -> tuple[Aufgabe, bool]:
    """Eine Aufgabe aus einer Mail, dort, wo der Mensch sie haben will.

    Gibt die Aufgabe zurueck und ob sie neu ist. ⚠️ **Gibt es zu dieser Mail
    schon eine, kommt die zurueck** — auch wenn sie woanders liegt als das
    gewaehlte Ziel. Kein Fehler, kein Doppel.

    ``koerper`` holt den Text der Mail nach, wenn er noch nie geholt wurde;
    gebraucht nur von einem Webhook mit Mailtext. Der Router reicht seinen
    eigenen Weg herein, weil der die Frist der App kennt.
    """
    nachricht = db.get(Nachricht, nachricht_id)
    if nachricht is None or nachricht.benutzer_id != person.id:
        raise aufgaben.AufgabenFehler("nachricht_unbekannt")

    schon = _vorhanden(db, person, nachricht)
    if schon is not None:
        return schon, False

    titel = " ".join(titel.split())[:500] or nachricht.betreff or ""

    if not ziel:
        aufgabe = aufgaben.anlegen(db, person, nachricht_id)
        aufgabe.betreff = titel
        aufgabe.faellig = _als_zeitpunkt(faellig)
        db.commit()
        return aufgabe, True

    v, liste_id = _zerlegen(db, person, ziel)
    if v.art == "webhook":
        return _per_webhook(
            db,
            person,
            nachricht,
            v,
            titel=titel,
            liste_name=liste_name,
            faellig=faellig,
            link=mail_link(db, nachricht.message_id, vom_browser),
            koerper=koerper,
        )
    try:
        stand = todoist.anlegen(
            _zugang(v),
            titel=titel or "(no subject)",
            beschreibung=_beschreibung(nachricht, mail_link(db, nachricht.message_id, vom_browser)),
            liste_id=liste_id,
            faellig=faellig,
        )
    except todoist.TodoistFehler as fehler:
        _fehler_merken(v, fehler)
        db.commit()
        raise

    kleinste = db.scalar(
        select(Aufgabe.reihenfolge)
        .where(Aufgabe.benutzer_id == person.id)
        .order_by(Aufgabe.reihenfolge)
        .limit(1)
    )
    aufgabe = Aufgabe(
        benutzer_id=person.id,
        konto_id=nachricht.konto_id,
        nachricht_id=nachricht.id,
        message_id=nachricht.message_id,
        betreff=titel,
        von_name=nachricht.von_name,
        von_adresse=nachricht.von_adresse,
        mail_datum=nachricht.datum,
        faellig=_als_zeitpunkt(stand.faellig),
        reihenfolge=(kleinste if kleinste is not None else 0) - 1,
        fern_art=v.art,
        verbindung_id=v.id,
        fern_id=stand.id,
        fern_url=stand.url,
        fern_liste=liste_name.strip()[:200],
    )
    v.letzter_fehler = ""
    db.add(aufgabe)
    try:
        db.commit()
    except IntegrityError:
        # ⚠️ Zwei Anfragen zugleich fuer dieselbe Mail: Die zweite verliert
        # hier und bekommt die erste zurueck. In der App steht dann ein Doppel;
        # das sagt das Protokoll, denn wegraeumen kann es nur der Mensch.
        db.rollback()
        logger.warning("A to-do app got the same message twice; one task there is a duplicate.")
        schon = _vorhanden(db, person, nachricht)
        if schon is None:
            raise
        return schon, False
    logger.info("A message was turned into a task in a to-do app (%s).", v.art)
    return aufgabe, True


# --- Was ein Webhook bekommt --------------------------------------------------- #
#
# ⚠️ **Feldnamen englisch**, wie unter ``/api/v1``: Sie gehoeren fremden
# Programmen. Die Form steht in der README; wer hier ein Feld umbenennt, bricht
# jeden Empfaenger da draussen.


def _iso(wann: datetime | None) -> str | None:
    return wann.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if wann else None


def _aufgabe_daten(a: Aufgabe) -> dict:
    return {
        "id": str(a.id),
        # Was der Empfaenger auf ``task.created`` als ``id`` nannte.
        "external_id": a.fern_id or None,
        "title": a.betreff,
        "due_date": a.faellig.date().isoformat() if a.faellig else None,
        "completed_at": _iso(a.erledigt),
    }


def _mail_daten(db: Session, nachricht: Nachricht, link: str) -> dict:
    konto = db.get(Konto, nachricht.konto_id) if nachricht.konto_id else None
    return {
        "message_id": nachricht.message_id or None,
        "subject": nachricht.betreff or "",
        "from": nachricht.von_adresse or "",
        "from_name": nachricht.von_name or "",
        "date": _iso(nachricht.datum),
        "mailbox": konto.anzeigename if konto else "",
        "mailbox_address": konto.adresse if konto else "",
        "link": link or None,
    }


def _mailtext(nachricht: Nachricht, koerper: Callable[[Nachricht], None] | None) -> dict:
    """Der Text der Mail, und das HTML, wenn sie eins hat.

    ⚠️ **Das HTML ist das bereinigte**, das auch der Lesebereich zeigt: ohne
    Skripte und ohne nachgeladene Bilder. Was zu lang ist, faellt beim HTML
    ganz weg statt mitten in einer Marke zu enden.

    ⚠️ **Ohne Text kein stiller Versand.** Laesst sich die Mail nicht holen,
    scheitert das Anlegen; eine Aufgabe ohne den Text, den der Empfaenger
    braucht, faellt dort erst Tage spaeter auf.
    """
    if nachricht.koerper_geholt is None and koerper is not None:
        koerper(nachricht)
    if nachricht.koerper_geholt is None:
        raise ZielFehler("webhook_mailtext_fehlt")
    html = nachricht.koerper_html or ""
    text = nachricht.koerper_text or bereinigen.text_aus_html(html, laenge=MAX_MAILTEXT + 1)
    return {
        "text": text[:MAX_MAILTEXT],
        "html": html if html and len(html) <= MAX_MAILTEXT else None,
        "text_truncated": len(text) > MAX_MAILTEXT or len(html) > MAX_MAILTEXT,
    }


def _per_webhook(
    db: Session,
    person: Benutzer,
    nachricht: Nachricht,
    v: Aufgabenverbindung,
    *,
    titel: str,
    liste_name: str,
    faellig: date | None,
    link: str,
    koerper: Callable[[Nachricht], None] | None,
) -> tuple[Aufgabe, bool]:
    """``task.created`` an den Webhook, und die Zeile hier.

    ⚠️ **Die Zeile steht vor dem Senden**, anders als bei Todoist: Der
    Empfaenger bekommt nexmails Kennung mit, und die gibt es erst nach dem
    Speichern. Ohne 2xx wird sie wieder geloescht; nichts bleibt halb.
    Waehrend des Sendens die Schreibsperre der Datenbank zu halten, haette
    jeden Abgleich bis zu zehn Sekunden aufgehalten.
    """
    zugang = webhook.zugang_lesen(_zugang(v))
    mail = _mail_daten(db, nachricht, link)
    if v.mit_text and webhook.mailtext_erlaubt(db):
        mail.update(_mailtext(nachricht, koerper))

    kleinste = db.scalar(
        select(Aufgabe.reihenfolge)
        .where(Aufgabe.benutzer_id == person.id)
        .order_by(Aufgabe.reihenfolge)
        .limit(1)
    )
    aufgabe = Aufgabe(
        benutzer_id=person.id,
        konto_id=nachricht.konto_id,
        nachricht_id=nachricht.id,
        message_id=nachricht.message_id,
        betreff=titel,
        von_name=nachricht.von_name,
        von_adresse=nachricht.von_adresse,
        mail_datum=nachricht.datum,
        faellig=_als_zeitpunkt(faellig),
        reihenfolge=(kleinste if kleinste is not None else 0) - 1,
        fern_art="webhook",
        verbindung_id=v.id,
        fern_liste=liste_name.strip()[:200],
        nur_gesendet=v.nur_senden,
    )
    db.add(aufgabe)
    try:
        db.commit()
    except IntegrityError:
        # ⚠️ Zwei Anfragen zugleich: Die zweite sendet gar nicht erst.
        db.rollback()
        schon = _vorhanden(db, person, nachricht)
        if schon is None:
            raise
        return schon, False

    try:
        antwort = webhook.senden(
            zugang, "task.created", {"task": _aufgabe_daten(aufgabe), "message": mail}
        )
    except webhook.WebhookFehler as fehler:
        db.delete(aufgabe)
        _fehler_merken(v, fehler)
        db.commit()
        raise
    aufgabe.fern_id = antwort.id
    aufgabe.fern_url = antwort.url
    v.letzter_fehler = ""
    db.commit()
    logger.info("A message was sent to a webhook as a task%s.", " (send only)" if v.nur_senden else "")
    return aufgabe, True


# --- Haken und Datum ----------------------------------------------------------- #


def _verwaltet(db: Session, aufgabe: Aufgabe) -> Aufgabenverbindung | None:
    """Die Verbindung, wenn die Aufgabe noch ueber eine App laeuft."""
    if not aufgabe.fern_art or not aufgabe.verbindung_id or aufgabe.fern_geloescht:
        return None
    return db.get(Aufgabenverbindung, aufgabe.verbindung_id)


def abhaken(db: Session, person: Benutzer, aufgabe_id: int, erledigt: bool) -> Aufgabe:
    """⚠️ **Erst die App, dann hier.** Lehnt sie ab, bleibt der Haken, wie er
    war — ein Haken, der hier sitzt und dort nicht, waere die eine Luege, die
    der Abgleich beim naechsten Mal still zuruecknaehme."""
    aufgabe = aufgaben.eine(db, person, aufgabe_id)
    v = _verwaltet(db, aufgabe)
    if v is not None and erledigt != (aufgabe.erledigt is not None):
        try:
            if v.art == "webhook":
                _haken_senden(db, v, aufgabe, erledigt)
            elif erledigt:
                todoist.schliessen(_zugang(v), aufgabe.fern_id)
            else:
                todoist.oeffnen(_zugang(v), aufgabe.fern_id)
        except AppFehler as fehler:
            _fehler_merken(v, fehler)
            db.commit()
            raise
        v.letzter_fehler = ""
    return aufgaben.abhaken(db, person, aufgabe_id, erledigt)


def _haken_senden(db: Session, v: Aufgabenverbindung, aufgabe: Aufgabe, erledigt: bool) -> None:
    """⚠️ **Der Stand nach dem Haken**, nicht der davor: ``completed_at`` ist
    beim Empfaenger sonst leer, gerade wenn er es braucht."""
    daten = _aufgabe_daten(aufgabe)
    daten["completed_at"] = _iso(datetime.now(timezone.utc)) if erledigt else None
    webhook.senden(
        webhook.zugang_lesen(_zugang(v)),
        "task.completed" if erledigt else "task.reopened",
        {
            "task": daten,
            "message": {
                "message_id": aufgabe.message_id or None,
                "link": mail_link(db, aufgabe.message_id) or None,
            },
        },
    )


def von_aussen_abhaken(db: Session, person: Benutzer, aufgabe: Aufgabe, erledigt: bool) -> Aufgabe:
    """Ein Haken ueber ``/api/v1``, vom Empfaenger eines Webhooks.

    ⚠️ **Kein Echo.** Kommt der Haken von dort, geht er nicht als
    ``task.completed`` wieder hinaus: Der Empfaenger weiss es schon, und ein
    Empfaenger, der auf jedes Ereignis mit einem Haken antwortet, liefe sonst
    im Kreis. Eine Todoist-Aufgabe geht dagegen den gewoehnlichen Weg, zuerst
    zu Todoist; dort gehoert ihr der Haken.
    """
    v = _verwaltet(db, aufgabe)
    if v is not None and v.art == "webhook":
        return aufgaben.abhaken(db, person, aufgabe.id, erledigt)
    return abhaken(db, person, aufgabe.id, erledigt)


def faelligkeit(db: Session, person: Benutzer, aufgabe_id: int, wann: datetime | None) -> Aufgabe:
    """⚠️ **Das Datum einer App-Aufgabe aendert man in der App.** Hier ist es
    nur ihr letzter Stand; eine Aenderung hier haette der Abgleich gleich
    wieder ueberschrieben."""
    aufgabe = aufgaben.eine(db, person, aufgabe_id)
    if _verwaltet(db, aufgabe) is not None:
        raise ZielFehler("aufgabe_datum_in_der_app")
    return aufgaben.faelligkeit(db, person, aufgabe_id, wann)


# --- Abgleich ------------------------------------------------------------------ #


def _eine_abgleichen(db: Session, v: Aufgabenverbindung) -> None:
    grenze = _jetzt() - NACHSEHEN_ERLEDIGTE
    zeilen = [
        a
        for a in db.scalars(
            select(Aufgabe).where(
                Aufgabe.verbindung_id == v.id,
                Aufgabe.fern_geloescht.is_(False),
                Aufgabe.fern_id != "",
            )
        )
        if a.erledigt is None or a.erledigt >= grenze
    ]
    if not zeilen:
        return
    zugang = _zugang(v)
    offen = todoist.offene(zugang, [a.fern_id for a in zeilen])
    for a in zeilen:
        stand = offen.get(a.fern_id)
        if stand is not None:
            a.erledigt = None
            a.faellig = _als_zeitpunkt(stand.faellig)
            continue
        if a.erledigt is not None:
            # ⚠️ Erledigt und weiter nicht offen: nichts zu fragen. Sonst
            # kostete jede erledigte Aufgabe bei jedem Lauf eine Anfrage.
            continue
        einzeln = todoist.eine(zugang, a.fern_id)
        if einzeln is None:
            a.fern_geloescht = True
        elif einzeln.erledigt is not None:
            a.erledigt = einzeln.erledigt
            a.faellig = _als_zeitpunkt(einzeln.faellig)


def abgleichen(db: Session, person: Benutzer, *, beim_oeffnen: bool = False) -> None:
    """Was die Apps zu den Aufgaben sagen, hier nachziehen.

    ⚠️ **Eine Verbindung, die scheitert, haelt die anderen nicht auf**, und
    ihr Fehler steht an ihr, nicht im Protokoll allein. Der Stand der Aufgaben
    bleibt dann der letzte bekannte.
    """
    if beim_oeffnen:
        jetzt = time.monotonic()
        if jetzt - _zuletzt_beim_oeffnen.get(person.id, -OEFFNEN_PAUSE) < OEFFNEN_PAUSE:
            return
        _zuletzt_beim_oeffnen[person.id] = jetzt

    for v in verbindungen(db, person):
        if v.art == "webhook":
            # ⚠️ Nichts zu fragen. Und ``letzter_fehler`` bleibt stehen: Er
            # sagt, dass das letzte Senden scheiterte, bis eins gelingt.
            continue
        try:
            _eine_abgleichen(db, v)
            v.letzter_fehler = ""
            v.zuletzt_abgeglichen = _jetzt()
        except (todoist.TodoistFehler, crypto.SchluesselFehler) as fehler:
            v.letzter_fehler = fehler.kennung[:80]
            logger.info("A to-do app could not be checked: %s", fehler.kennung)
        db.commit()


def alle_abgleichen(db: Session) -> None:
    """Fuer den Takt: jeder Benutzer mit mindestens einer Verbindung."""
    leute = db.scalars(
        select(Benutzer).where(
            Benutzer.id.in_(select(Aufgabenverbindung.benutzer_id).distinct())
        )
    )
    for person in list(leute):
        abgleichen(db, person)
