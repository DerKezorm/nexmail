"""Die Abwesenheitsnotiz.

⚠️ **Das ist die einzige Stelle, an der nexmail von sich aus Post an Fremde
schickt.** Alles andere geht erst hinaus, wenn ein Mensch auf „Senden" drückt.
Deshalb steht hier mehr Vorsicht als Funktion, und deshalb ist die Vorgabe aus.

Was schiefgehen kann, wenn der Schleifenschutz nicht sitzt: Zwei
Abwesenheitsnotizen antworten einander, bis jemand es merkt. Eine Notiz geht an
eine Mailingliste und damit an alle. Ein Neustart holt drei Wochen Post nach und
beantwortet sie rückwirkend. Jede dieser drei Katastrophen hat hier ihre eigene
Wache.

⚠️ **nexmail antwortet nur, solange nexmail läuft.** iCloud und die meisten
Anbieter können das serverseitig und damit unabhängig davon. Das steht in der
Oberfläche, nicht nur hier — wer nexmail stoppt, soll es vorher wissen.

⚠️ **Und der Satz sagt „nexmail", nicht „der Rechner".** Am 02.09.2026 gemeldet:
Bei einem Server im Haus denkt man bei „Rechner" an den Laptop, von dem aus man
ihn bedient — und lässt den an, während der Container aus ist.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from email import message_from_bytes
from email.utils import getaddresses

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Abwesenheitsantwort, Konto, Nachricht, Ordner

logger = logging.getLogger("nexmail.abwesenheit")

#: Die Kopfzeilen, an denen man Massenpost und Automaten erkennt.
#:
#: ⚠️ **Nur bei eingeschalteter Abwesenheit geholt.** Der Abgleich läuft bei
#: jedem Postfach im Takt; eine vierte Kopfzeilen-Abfrage für alle wäre Aufwand
#: für die vielen, damit die wenigen eine Notiz verschicken können.
KOPFZEILEN = (
    "LIST-ID LIST-UNSUBSCRIBE LIST-POST PRECEDENCE AUTO-SUBMITTED "
    "RETURN-PATH X-AUTOREPLY X-AUTORESPONDER TO CC"
)

#: Was ``Precedence`` haben darf, ohne dass geantwortet wird.
STILLE_PRECEDENCE = {"bulk", "list", "junk", "auto_reply"}


def _heute(zeitzone: str) -> date:
    """Der heutige Kalendertag in der eingestellten Zeitzone.

    ⚠️ Über ``zeit.zone`` — die weicht zwar auch auf UTC aus, aber nicht
    stumm. Ein um einen halben Tag verschobener Abwesenheitszeitraum faellt
    sonst erst im Urlaub auf.
    """
    from . import zeit as zeitdienst

    return datetime.now(zeitdienst.zone(zeitzone)).date()


def _tag(wert: str) -> date | None:
    try:
        return date.fromisoformat(wert)
    except ValueError:
        return None


def laeuft(konto: Konto, zeitzone: str = "UTC") -> bool:
    """Gilt die Abwesenheit gerade?

    ⚠️ **„Bis" ist einschließlich.** Wer den 14. einträgt, meint den 14. mit.
    Ein „bis 14." wäre am 14. schon aus, und das merkt man erst hinterher.
    """
    if not konto.abwesenheit_aktiv:
        return False
    heute = _heute(zeitzone)
    von = _tag(konto.abwesenheit_von or "")
    bis = _tag(konto.abwesenheit_bis or "")
    if von and heute < von:
        return False
    if bis and heute > bis:
        return False
    return True


def _eigene_adressen(konto: Konto) -> set[str]:
    return {a.lower() for a in (konto.adresse, konto.smtp_benutzer, konto.imap_benutzer) if a}


def antwort_faellig(
    konto: Konto,
    nachricht: Nachricht,
    kopf: bytes,
    schon_beantwortet: set[str],
) -> str | None:
    """Soll auf diese Nachricht geantwortet werden? Gibt den Grund zurück.

    Rückgabe ``None`` heißt: antworten. Sonst steht dort, warum nicht — das
    landet im Protokoll, denn „es passiert nichts" ist die Meldung, bei der
    man sonst den Fehler bei sich sucht.
    """
    absender = (nachricht.von_adresse or "").strip().lower()
    if not absender:
        return "ohne_absender"
    if absender in _eigene_adressen(konto):
        return "eigene_adresse"
    if absender in schon_beantwortet:
        return "schon_beantwortet"

    teil = message_from_bytes(kopf)

    # ⚠️ **Unzustellbarkeitsmeldungen haben einen leeren Rückweg.** Wer denen
    # antwortet, schickt Post an ``<>`` — im besten Fall unzustellbar, im
    # schlechteren an einen Verteiler, der sie weiterreicht.
    rueckweg = (teil.get("Return-Path") or "").strip()
    if rueckweg in ("<>", "< >"):
        return "unzustellbarkeit"

    # RFC 3834: Automaten kennzeichnen sich. Alles ausser ``no`` heisst
    # „automatisch erzeugt" — und darauf antwortet man nie.
    auto = (teil.get("Auto-Submitted") or "no").strip().lower()
    if auto and not auto.startswith("no"):
        return "automat"

    if teil.get("X-Autoreply") or teil.get("X-Autoresponder"):
        return "automat"

    # Mailinglisten: Eine Notiz an die Liste geht an alle darauf.
    if teil.get("List-Id") or teil.get("List-Unsubscribe") or teil.get("List-Post"):
        return "verteiler"

    vorrang = (teil.get("Precedence") or "").strip().lower()
    if vorrang in STILLE_PRECEDENCE:
        return "massenpost"

    # ⚠️ **Nur, wenn die Mail wirklich an mich ging.** Steht die eigene
    # Adresse weder in ``To`` noch in ``Cc``, ist es Verteilerpost oder eine
    # Blindkopie — beides kein Anlass, sich zu Wort zu melden.
    empfaenger = {
        a.lower()
        for _, a in getaddresses(
            [teil.get("To") or "", teil.get("Cc") or ""]
        )
        if a
    }
    if empfaenger and not (empfaenger & _eigene_adressen(konto)):
        return "nicht_an_mich"

    return None


def notiz_bauen(konto: Konto, nachricht: Nachricht, message_id: str = ""):
    """Den Entwurf der Notiz — reiner Text, mit den Kennzeichen eines Automaten."""
    from . import konten as kontendienst, verfassen

    betreff = (konto.abwesenheit_betreff or "").strip() or "Abwesenheitsnotiz"
    return verfassen.Entwurf(
        von_name=kontendienst.absendername(konto),
        von_adresse=konto.adresse,
        an=[nachricht.von_adresse],
        betreff=betreff,
        text=konto.abwesenheit_text or "",
        # ⚠️ **Kein HTML.** Siehe Modulkommentar und das Feld am Konto.
        html="",
        in_reply_to=message_id,
        references=[message_id] if message_id else [],
        auto_antwort=True,
    )


def erledigen(klient, db: Session, konto: Konto, ordner: Ordner, neue: list[Nachricht]) -> int:
    """Nach dem Abgleich: auf neue Post im Posteingang antworten.

    ⚠️ **Nur der Posteingang.** Was eine Regel schon in einen Ordner geschoben
    hat oder was im Junk liegt, verlangt keine Antwort.

    ⚠️ **Nur Post, die WÄHREND der Abwesenheit ankam.** Ohne diese Wache holt
    ein Neustart drei Wochen Post nach und beantwortet sie rückwirkend — die
    peinlichste der drei Katastrophen, weil sie auf einen Schlag passiert.
    """
    from ..config import get_settings
    from ..db import einstellung_lesen
    from ..routers.einstellungen import SCHLUESSEL_ZEITZONE

    zeitzone = einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone
    if ordner.rolle != "posteingang" or not laeuft(konto, zeitzone):
        return 0

    von = _tag(konto.abwesenheit_von or "")
    kandidaten = [
        n
        for n in neue
        if n.von_adresse
        and (von is None or (n.datum is not None and n.datum.date() >= von))
    ]
    if not kandidaten:
        return 0

    schon = {
        a.lower()
        for a in db.scalars(
            select(Abwesenheitsantwort.adresse).where(
                Abwesenheitsantwort.konto_id == konto.id
            )
        )
    }

    koepfe = klient.fetch(
        [n.uid for n in kandidaten],
        [f"BODY.PEEK[HEADER.FIELDS ({KOPFZEILEN})]".encode()],
    )
    schluessel = f"BODY[HEADER.FIELDS ({KOPFZEILEN})]".encode()

    from . import senden as sendedienst

    verschickt = 0
    for n in kandidaten:
        kopf = (koepfe.get(n.uid) or {}).get(schluessel) or b""
        grund = antwort_faellig(konto, n, kopf, schon)
        if grund is not None:
            logger.debug("No auto-reply for one message (%s).", grund)
            continue
        try:
            sendedienst.einreihen(db, konto, notiz_bauen(konto, n, n.message_id or ""))
        except Exception:  # noqa: BLE001
            # ⚠️ **Ein Fehlschlag darf den Abgleich nicht mitreissen.** Post
            # holen ist wichtiger als Post beantworten.
            logger.exception("An out-of-office reply could not be queued.")
            continue
        adresse = n.von_adresse.strip().lower()
        db.add(Abwesenheitsantwort(konto_id=konto.id, adresse=adresse))
        schon.add(adresse)
        verschickt += 1

    if verschickt:
        db.commit()
        logger.info("%s out-of-office repl(ies) were queued.", verschickt)
    return verschickt


def zuruecksetzen(db: Session, konto: Konto) -> None:
    """Die Merkliste leeren — beim Einschalten einer neuen Abwesenheit.

    ⚠️ **„Je Absender einmal" gilt je Abwesenheit, nicht je Lebenszeit des
    Postfachs.** Sonst bekäme beim nächsten Urlaub niemand mehr eine Notiz,
    der beim vorigen schon eine hatte.
    """
    for zeile in db.scalars(
        select(Abwesenheitsantwort).where(Abwesenheitsantwort.konto_id == konto.id)
    ):
        db.delete(zeile)
