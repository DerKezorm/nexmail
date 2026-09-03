"""Web Push — Meldungen, wenn nexmail gar nicht offen ist.

Zwei Anlaesse: eine faellige Terminerinnerung und neue Post. Beide gehen
denselben Weg — verschluesselt an die Adresse, die der Browser beim Push-Dienst
seines Herstellers gezogen hat (Mozilla, Google, Apple).

⚠️ **Das ist die einzige Stelle neben der Abwesenheitsnotiz, an der nexmail von
sich aus etwas hinausschickt.** Anders als dort geht es aber nicht an Fremde,
sondern an Geraete, die sich selbst angemeldet haben. Der Schaden bei einem
Fehler ist deshalb kein Verteiler voller Antworten, sondern ein klingelndes
Telefon — laestig, nicht peinlich. Trotzdem gilt dieselbe Haltung: lieber eine
Meldung zu wenig als eine falsche.

Zwei Normen, und beide sind Pflicht, nicht Kuer:

* **RFC 8291** — der Rumpf ist mit einem Schluessel verschluesselt, den nur der
  Browser hat. Der Push-Dienst leitet weiter, ohne mitzulesen. Deshalb steht in
  einer Meldung auch ruhig ein Betreff.
* **RFC 8292** — nexmail weist sich beim Push-Dienst mit einer Unterschrift
  aus (VAPID). Der Browser hat das Abonnement mit unserem oeffentlichen
  Schluessel angelegt; eine Meldung ohne die passende Unterschrift nimmt der
  Dienst gar nicht erst an.

⚠️ **Der private VAPID-Schluessel ist das einzige echte Geheimnis hier.** Er
liegt verschluesselt in den Einstellungen (Kontext ``push-vapid``). Wer ihn
verliert, verliert alle Abonnements auf einmal: Sie haengen am oeffentlichen
Gegenstueck, und ein neues Paar heisst, dass sich jedes Geraet neu anmelden
muss. Er wird deshalb **einmal** erzeugt und danach nie wieder angefasst.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..db import SessionLocal, einstellung_lesen, einstellung_schreiben
from ..models import Benutzer, Konto, Nachricht, Ordner, PushAnmeldung, utcnow
from .zeit import zone_der_anwendung

logger = logging.getLogger("nexmail.push")

#: Wie oft der Faden nachsieht, ob eine Erinnerung faellig ist.
#:
#: ⚠️ **Enger als der Post-Takt, und das muss so sein.** Eine Erinnerung „fuenf
#: Minuten vorher" bei einem Nachsehen alle zehn Minuten ist im schlechtesten
#: Fall fuenf Minuten zu spaet, also nach dem Termin. Eine Minute kostet
#: nichts: Wer nichts angemeldet hat, wird uebersprungen, bevor irgendetwas
#: gerechnet wird.
NACHSEHEN_SEKUNDEN = 60

#: Der Kanalname in ``Erinnerungszustellung``. ⚠️ Er steht im eindeutigen
#: Schluessel — wer ihn aendert, stellt jede schon gemeldete Erinnerung erneut
#: zu.
KANAL = "push"

#: Wie lange der Push-Dienst eine Meldung aufheben soll, wenn das Geraet gerade
#: aus ist. ⚠️ **Nicht laenger.** Eine Terminerinnerung, die zwoelf Stunden
#: spaeter aufpoppt, ist keine Erinnerung mehr, sondern Verwirrung.
TTL_SEKUNDEN = 3600

#: Der Schluessel in der Einstellungstabelle, unter dem das VAPID-Paar liegt.
SCHLUESSEL = "push_vapid_privat"

#: ⚠️ **Der Rumpf ist gedeckelt.** Die Push-Dienste nehmen rund 4 kB an, und
#: was darueber liegt, weisen sie mit 413 ab — nicht mit einer Meldung, die
#: irgendwo auffiele. Ein Betreff kann beliebig lang sein, deshalb wird hier
#: gekuerzt und nicht gehofft.
RUMPF_GRENZE = 3000

#: Ein Betreff laenger als das liest auf einem Sperrbildschirm ohnehin niemand.
TEXT_GRENZE = 120

_schloss = threading.Lock()


class Zustellfehler(RuntimeError):
    """Der Push-Dienst hat die Meldung nicht angenommen."""


@dataclass(frozen=True)
class Meldung:
    """Was auf dem Bildschirm erscheint."""

    titel: str
    text: str
    #: Wohin ein Klick fuehrt, relativ zur Anwendung.
    ziel: str
    #: Ersetzt eine gleichnamige Meldung, statt sie daneben zu stellen.
    marke: str


# --------------------------------------------------------------------------- #
# Der Schluessel
# --------------------------------------------------------------------------- #


def _paar(db: Session) -> Vapid02:
    """Das VAPID-Paar, beim ersten Aufruf erzeugt.

    ⚠️ **Unter einem Schloss.** Zwei Anfragen zugleich beim allerersten Mal
    erzeugten sonst zwei Paare, und das zweite ueberschriebe das erste — jedes
    Geraet, das sich in der Zwischenzeit angemeldet hat, waere still taub.
    """
    with _schloss:
        verpackt = einstellung_lesen(db, SCHLUESSEL)
        if verpackt:
            pem = crypto.entschluesseln(verpackt, "push-vapid").encode()
            return Vapid02.from_pem(pem)

        frisch = Vapid02()
        frisch.generate_keys()
        pem = frisch.private_pem()
        einstellung_schreiben(
            db, SCHLUESSEL, crypto.verschluesseln(pem.decode(), "push-vapid")
        )
        db.commit()
        logger.info("A new VAPID key pair was generated for web push.")
        return frisch


def oeffentlicher_schluessel(db: Session) -> str:
    """Was der Browser als ``applicationServerKey`` braucht.

    ⚠️ **Der rohe Punkt, nicht das PEM.** Die Push-API des Browsers will die
    65 Byte des unkomprimierten P-256-Punktes in base64url ohne Polster. Wer
    hier ein PEM oder DER hinschickt, bekommt vom Browser ein
    ``InvalidCharacterError`` — und das liest sich wie ein Fehler im eigenen
    JavaScript.
    """
    punkt = _paar(db).public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(punkt).rstrip(b"=").decode()


# --------------------------------------------------------------------------- #
# Zustellen
# --------------------------------------------------------------------------- #


def _absender(db: Session) -> str:
    """Der ``sub``-Anspruch der Unterschrift: wer im Zweifel erreichbar ist.

    RFC 8292 laesst dafuer ``mailto:`` oder ``https:`` zu, und der Push-Dienst
    will damit einen Betreiber erreichen koennen, wenn eine Installation ihn
    zumuellt.

    ⚠️ **Nur die Herkunft, ohne Pfad.** Die Pruefung in ``py_vapid`` verankert
    ihre Regex am Ende des Hostnamens; ``https://beispiel.de/nexmail`` faellt
    damit durch, und die Meldung („Missing 'sub' from claims") zeigt auf ein
    fehlendes Feld statt auf ein zu langes. nexmail laeuft ausdruecklich auch
    unter einem Unterpfad, das trifft also nicht nur Sonderfaelle.

    ⚠️ **Keine Adresse eines Menschen.** nexmail speichert am Konto ohnehin
    keine, und eine erfundene gehoert nicht in eine Kopfzeile, die an Google
    und Mozilla geht. Die Herkunft der Installation ist beides: echt und
    unpersoenlich. Steht keine, ist die Installation nicht oeffentlich
    erreichbar — dann sagt ``localhost`` genau das.
    """
    adresse = (einstellung_lesen(db, "oeffentliche_adresse") or "").strip()
    if adresse.startswith("https://"):
        herkunft = httpx.URL(adresse)
        if herkunft.host:
            return f"https://{herkunft.netloc.decode()}"
    return "mailto:admin@localhost"


def _rumpf(meldung: Meldung) -> bytes:
    daten = json.dumps(
        {
            "titel": meldung.titel[:TEXT_GRENZE],
            "text": meldung.text[:TEXT_GRENZE],
            "ziel": meldung.ziel,
            "marke": meldung.marke,
        },
        ensure_ascii=False,
    ).encode()
    return daten[:RUMPF_GRENZE]


def zustellen(db: Session, anmeldung: PushAnmeldung, meldung: Meldung) -> None:
    """Eine Meldung an genau ein Geraet.

    Wirft ``Zustellfehler`` bei einem voruebergehenden Problem — Netz weg,
    Push-Dienst ueberlastet. **Ist das Abonnement dagegen erloschen (404 oder
    410), wird die Zeile geloescht und nichts geworfen:** Das ist kein Fehler,
    sondern der vorgesehene Weg, auf dem ein geloeschter Browserzustand hier
    ankommt. Wer beides gleich behandelt, raeumt entweder nie auf oder
    versucht es ewig weiter.
    """
    fluechtig = ec.generate_private_key(ec.SECP256R1())
    verschluesselt = http_ece.encrypt(
        _rumpf(meldung),
        private_key=fluechtig,
        dh=_roh(anmeldung.p256dh),
        auth_secret=_roh(anmeldung.auth),
        version="aes128gcm",
    )

    herkunft = httpx.URL(anmeldung.endpunkt)
    kopf = _paar(db).sign(
        {
            "aud": f"{herkunft.scheme}://{herkunft.netloc.decode()}",
            "sub": _absender(db),
            "exp": int(utcnow().timestamp()) + 12 * 3600,
        }
    )
    kopf.update(
        {
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_SEKUNDEN),
            "Urgency": "normal",
        }
    )

    try:
        with httpx.Client(timeout=10.0) as klient:
            antwort = klient.post(anmeldung.endpunkt, content=verschluesselt, headers=kopf)
    except httpx.HTTPError as fehler:
        raise Zustellfehler(str(fehler)) from fehler

    if antwort.status_code in (404, 410):
        # ⚠️ Der Browser hat sein Abonnement weggeworfen. Nur diese beiden
        # Nummern heissen das; ein 403 heisst „falsche Unterschrift" und waere
        # ein Fehler bei uns, den wir nicht wegraeumen duerfen.
        logger.info("A push subscription is gone (%s); removing it.", antwort.status_code)
        db.delete(anmeldung)
        db.commit()
        return

    if antwort.status_code >= 400:
        raise Zustellfehler(f"HTTP {antwort.status_code}: {antwort.text[:200]}")

    anmeldung.zuletzt_erreicht = utcnow()
    db.commit()


def _roh(base64url: str) -> bytes:
    """base64url ohne Polster, wie der Browser es liefert."""
    return base64.urlsafe_b64decode(base64url + "=" * (-len(base64url) % 4))


def an_benutzer(db: Session, person: Benutzer, meldung: Meldung) -> bool:
    """An alle Geraete dieses Benutzers. Wahr, wenn mindestens eines es nahm.

    ⚠️ **Ein stummes Geraet darf die anderen nicht aufhalten.** Dieselbe Lehre
    wie in der Aufraeumrunde: Der Fehler beim k-ten riss sonst alle folgenden
    mit — und hier heisst das, dass das Telefon schweigt, weil ein alter
    Browser auf dem Zweitrechner klemmt.
    """
    angekommen = False
    for anmeldung in list(person.push_anmeldungen):
        try:
            zustellen(db, anmeldung, meldung)
            angekommen = True
        except Zustellfehler as fehler:
            db.rollback()
            logger.info("Push delivery failed for one device: %s", fehler)
    return angekommen


# --------------------------------------------------------------------------- #
# Ruhezeit
# --------------------------------------------------------------------------- #


def _uhr(wert: str, vorgabe: time) -> time:
    try:
        stunde, minute = wert.split(":")
        return time(int(stunde), int(minute))
    except (ValueError, AttributeError):
        # ⚠️ Eine krumme Uhrzeit darf keine Meldung kosten. Sie kann nur durch
        # eine alte Zeile oder einen Eingriff von Hand entstehen.
        return vorgabe


def ruhezeit_jetzt(db: Session, person: Benutzer, jetzt: datetime | None = None) -> bool:
    """Ob gerade Ruhe herrscht.

    ⚠️ **In der Zone des Betreibers, nicht in UTC.** „Ab 22 Uhr" ist eine
    Aussage ueber die Uhr an der Wand. In UTC gerechnet begaenne die Ruhe im
    Sommer um 23 Uhr Ortszeit, und niemand braechte das mit der
    Zeitumstellung in Verbindung.

    ⚠️ **Der Zeitraum geht ueber Mitternacht**, und das ist der Normalfall:
    22:00 bis 07:00. Ein Vergleich ``von <= jetzt <= bis`` waere fuer genau
    diesen Fall falsch und fuer den seltenen richtig.
    """
    if not person.push_ruhezeit:
        return False
    ortszeit = (jetzt or utcnow()).astimezone(zone_der_anwendung(db)).time()
    von = _uhr(person.push_ruhezeit_von, time(22, 0))
    bis = _uhr(person.push_ruhezeit_bis, time(7, 0))
    if von == bis:
        return False
    if von < bis:
        return von <= ortszeit < bis
    return ortszeit >= von or ortszeit < bis


# --------------------------------------------------------------------------- #
# Anlass 1: Terminerinnerungen
# --------------------------------------------------------------------------- #


def _uhrzeit(beginn: datetime, ganztaegig: bool, db: Session) -> str:
    if ganztaegig:
        return ""
    return beginn.astimezone(zone_der_anwendung(db)).strftime("%H:%M")


def erinnerungen_runde() -> int:
    """Eine Runde ueber alle, die Terminmeldungen wollen."""
    hinaus = 0
    with SessionLocal() as db:
        leute = db.scalars(
            select(Benutzer).where(Benutzer.push_termine.is_(True))
        ).all()
        for person in leute:
            # Der Name VOR der Arbeit, wie in der Aufraeumrunde: Ist die
            # Sitzung nach einem Fehler gesperrt, wirft schon der Zugriff
            # darauf erneut — mitten im ``except``.
            wer = person.benutzername
            try:
                hinaus += _erinnerungen_fuer(db, person)
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("Reminder push failed for %s.", wer)
                continue
    return hinaus


def _erinnerungen_fuer(db: Session, person: Benutzer) -> int:
    from . import erinnerungen as erinnerungsdienst

    # ⚠️ **Vor ``faellige``, nicht danach.** Der Rechner bucht die Zustellung
    # beim Ermitteln, nicht beim Senden. Wer ohne angemeldetes Geraet fragt,
    # verbraucht damit Erinnerungen, die nie irgendwo ankamen — und wer sich
    # eine Minute spaeter anmeldet, bekommt sie nie.
    if not person.push_anmeldungen:
        return 0

    faellig = erinnerungsdienst.faellige(db, person, kanal=KANAL, nur_einmal=True)
    if not faellig:
        return 0

    ruhig = ruhezeit_jetzt(db, person)
    hinaus = 0
    for eintrag in faellig:
        # ⚠️ **Vorlauf 0 kommt durch die Ruhezeit.** „Jetzt gleich" ist keine
        # Vorwarnung, sondern der Termin selbst; wer den verschlaeft, hatte
        # von der Ruhezeit keinen Gewinn. Alles andere wird **verschluckt**,
        # nicht aufgeschoben: Eine Erinnerung, die um sieben Uhr nachgereicht
        # wird, meldet einen Termin, der um elf Uhr abends war.
        if ruhig and eintrag.vorlauf != 0:
            continue

        uhr = _uhrzeit(eintrag.beginn, eintrag.ganztaegig, db)
        teile = [t for t in (uhr, eintrag.ort) if t]
        angekommen = an_benutzer(
            db,
            person,
            Meldung(
                titel=eintrag.titel,
                text=" · ".join(teile) or eintrag.kalender,
                ziel="/kalender",
                marke=f"termin-{eintrag.termin_id}-{int(eintrag.beginn.timestamp())}",
            ),
        )
        if angekommen:
            hinaus += 1
        else:
            _buchung_zuruecknehmen(db, person, eintrag.id)
    return hinaus


def _buchung_zuruecknehmen(db: Session, person: Benutzer, zustellung_id: int) -> None:
    """Nach einem misslungenen Versuch: die Buchung wieder loeschen.

    ⚠️ **Der Rechner bucht beim Ermitteln, nicht beim Senden.** ``faellige``
    schreibt die Zustellung und schreibt sie fest, bevor hier auch nur ein
    Byte hinausgeht — das muss es, sonst stellten zwei Runden nebeneinander
    doppelt zu. Faellt der Push-Dienst also fuer eine Minute aus, waere die
    Erinnerung ohne diese Stelle **still verloren**: ``nur_einmal`` uebergeht
    sie beim naechsten Mal, und niemand erfaehrt davon.

    ⚠️ **Nur, solange noch ein Geraet dasteht.** Sind alle Abonnements gerade
    mit 404 herausgefallen, gibt es nichts zu wiederholen — die Buchung bleibt
    dann stehen, statt jede Minute erneut ins Leere zu laufen.
    """
    from ..models import Erinnerungszustellung

    if not person.push_anmeldungen:
        return
    zeile = db.get(Erinnerungszustellung, zustellung_id)
    if zeile is not None:
        db.delete(zeile)
        db.commit()


# --------------------------------------------------------------------------- #
# Anlass 2: neue Post
# --------------------------------------------------------------------------- #

#: Ordnerrollen, die nie melden. ⚠️ Junk und Papierkorb sind selbsterklaerend;
#: „gesendet" und „entwuerfe" fuellt man selbst.
STUMME_ROLLEN = ("junk", "papierkorb", "gesendet", "entwuerfe")


def neue_mail_melden(
    db: Session,
    konto: Konto,
    kennungen: list[int],
    neu_aufgebaute_pfade: set[str],
) -> None:
    """Meldet, was der Abgleich gerade wirklich neu geholt hat.

    ⚠️ **Aufgerufen NACH den Regeln, nicht davor.** Eine Regel raeumt eine
    Sekunde spaeter ins Archiv oder in den Junk; wer vorher meldet, sagt „neu
    im Posteingang" ueber eine Mail, die dort nie lag. Deshalb wird der Ordner
    hier auch frisch aus der Zeile gelesen und nicht aus dem Abgleich
    uebernommen.

    ⚠️ **Und der Aufrufer faengt jeden Fehler.** Eine misslungene Meldung darf
    keine Post aufhalten — dieselbe Haltung wie bei ``_regeln_laufen_lassen``
    daneben.
    """
    person = db.get(Benutzer, konto.benutzer_id)
    if person is None or not person.push_mail or not person.push_anmeldungen:
        return
    if ruhezeit_jetzt(db, person):
        return

    nachrichten = [n for n in (db.get(Nachricht, k) for k in kennungen) if n is not None]
    treffer = [
        n for n in nachrichten if _meldenswert(db, n, person, neu_aufgebaute_pfade)
    ]
    if not treffer:
        return

    if person.push_mail_buendeln and len(treffer) > 1:
        an_benutzer(
            db,
            person,
            Meldung(
                titel=f"{len(treffer)} neue Nachrichten",
                text=konto.adresse,
                ziel="/",
                marke=f"mail-{konto.id}",
            ),
        )
        return

    for nachricht in treffer:
        an_benutzer(
            db,
            person,
            Meldung(
                titel=nachricht.von_name or nachricht.von_adresse or konto.adresse,
                text=nachricht.betreff or "(kein Betreff)",
                ziel="/",
                marke=f"mail-{nachricht.id}",
            ),
        )


def _meldenswert(
    db: Session,
    nachricht: Nachricht,
    person: Benutzer,
    neu_aufgebaute_pfade: set[str],
) -> bool:
    if person.push_mail_nur_ungelesen and nachricht.gelesen:
        return False

    # ⚠️ **Frisch aus der Zeile gelesen, nicht aus dem Abgleich uebernommen.**
    # Zwischen dem Abgleich und dieser Stelle sind die Regeln gelaufen; die
    # Mail kann inzwischen woanders liegen.
    ordner = db.get(Ordner, nachricht.ordner_id)
    if ordner is None:
        return False

    # ⚠️ **Ein neu aufgebauter Ordner ist komplett „neu".** Wechselt die
    # UIDVALIDITY, wirft der Abgleich den ganzen Ordner weg und holt ihn
    # wieder; jede Zeile darin ist frisch, obwohl sich beim Anbieter nichts
    # getan hat.
    if ordner.pfad in neu_aufgebaute_pfade:
        return False

    # ⚠️ **Der Wiedervorlage-Ordner meldet sich nie.** Was dort liegt, hat ein
    # Mensch bewusst weggelegt — auch von einem anderen Geraet aus. Fuer den
    # Abgleich ist es dann „neu". Dieselbe Ausnahme wie bei den Regeln, und
    # dort steht die lange Begruendung.
    from .wiedervorlage import ORDNER_NAME as wiedervorlage_ordner

    if ordner.pfad == wiedervorlage_ordner:
        return False

    if person.push_mail_alle_ordner:
        return ordner.rolle not in STUMME_ROLLEN
    return ordner.rolle == "posteingang"
