"""Fällige Erinnerungen — kanalunabhängig.

⚠️ **Dieser Dienst kennt keinen Kanal.** Er sagt nur, was fällig ist; wer es
zustellt, entscheidet der Aufrufer. Heute gibt es genau einen Kanal („in der
App", der abholt); ein Web-Push oder eine Erinnerungsmail hängt sich später an
dieselbe Stelle, ohne dass hier etwas umgebaut wird. Dasselbe Muster wie „für
OIDC vorbereitet" in Stufe 0.

⚠️ **Gerechnet wird je VORKOMMEN, nicht je Termin.** Eine wöchentliche
Besprechung erinnerte sonst genau einmal — und danach nie wieder.

⚠️ **Was einmal zugestellt wurde, kommt nicht wieder.** Die Zeile in
``erinnerungszustellung`` ist der ganze Unterschied zwischen einer Erinnerung
und einem Dauerläuten. Sie bleibt auch nach dem Wegklicken stehen: gelöscht
käme die Erinnerung beim nächsten Abruf sofort erneut.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Erinnerungszustellung, Kalender, Termin, utcnow
from . import wiederholung

logger = logging.getLogger("nexmail.erinnerungen")

#: Wie weit voraus gesucht wird. ⚠️ Muss größer sein als der größte Vorlauf,
#: den die Oberfläche anbietet (ein Tag) — sonst fiele „einen Tag vorher"
#: durch das Raster, weil der Termin noch außerhalb des Fensters liegt.
VORAUS = timedelta(days=2)

#: Wie weit zurück. Wer nexmail abends öffnet, soll die Erinnerung von
#: nachmittags noch sehen — aber nicht die von vorletzter Woche.
ZURUECK = timedelta(hours=12)

#: Die Vorläufe, die die Oberfläche anbietet. Steht hier, damit Server und
#: Oberfläche nicht auseinanderlaufen.
VORLAEUFE = (0, 5, 10, 15, 30, 60, 120, 1440)

#: Das Schlummern. Kürzer als fünf Minuten wäre kein Schlummern mehr.
SCHLUMMER = (5, 15, 60)


@dataclass
class Faellig:
    """Eine fällige Erinnerung, wie die Oberfläche sie zeigt."""

    id: int
    termin_id: int
    titel: str
    ort: str
    kalender: str
    farbe: int
    beginn: datetime
    ganztaegig: bool
    #: Minuten vor dem Beginn, wie am Termin eingestellt.
    vorlauf: int


def faellige(
    db: Session,
    benutzer: Benutzer,
    *,
    jetzt: datetime | None = None,
    kanal: str = "app",
    nur_einmal: bool = False,
) -> list[Faellig]:
    """Was jetzt dran ist — und merkt sich, dass es herausgegangen ist.

    ⚠️ **Das Merken passiert hier, nicht beim Aufrufer.** Sonst hätte jeder
    Kanal seine eigene Buchführung, und zwei Kanäle nebeneinander stellten
    doppelt oder gar nicht zu.

    ⚠️ **``nur_einmal`` trennt die beiden Sorten Kanal.** Ein Fenster in der
    App **zeigt**, bis jemand handelt: Wer die Seite neu lädt, soll seine
    Erinnerung wiederfinden, nicht verloren haben. Ein Push dagegen **feuert**,
    und zwar genau einmal — ein zweites Mal wäre eine zweite Benachrichtigung
    auf dem Telefon. Derselbe Rechner, zwei Haltungen; ohne diese
    Unterscheidung müsste der zweite Kanal seine eigene bauen.
    """
    jetzt = jetzt or utcnow()
    von = jetzt - ZURUECK
    bis = jetzt + VORAUS

    kalender = {
        k.id: k
        for k in db.scalars(select(Kalender).where(Kalender.benutzer_id == benutzer.id))
    }
    if not kalender:
        return []

    # ⚠️ Eine Reihe kann VOR dem Fenster beginnen und hineinreichen — fuer
    # sie gibt es deshalb kein unteres Ende. Dieselbe Regel wie in der
    # Kalenderansicht.
    #
    # ⚠️ **Ein einzelner Termin dagegen ist erledigt, wenn er vorbei ist.**
    # Seine Erinnerung haengt am Beginn, und das Fenster reicht nur zwoelf
    # Stunden zurueck (``ZURUECK``). Ohne diese Grenze las jeder Aufruf den
    # gesamten Bestand — und die Oberflaeche fragt alle 30 Sekunden. Gemessen
    # bei 20.000 Terminen: 6.475 Zeilen statt 216.
    termine = list(
        db.scalars(
            select(Termin).where(
                Termin.kalender_id.in_(kalender),
                Termin.erinnerung >= 0,
                Termin.beginn <= bis,
                (Termin.rrule != "") | (Termin.beginn >= von),
            )
        )
    )
    if not termine:
        return []

    # Was schon herausging — in einem Zug, nicht je Vorkommen eine Abfrage.
    bekannt = {
        (z.termin_id, z.vorkommen.replace(tzinfo=timezone.utc), z.kanal): z
        for z in db.scalars(
            select(Erinnerungszustellung).where(
                Erinnerungszustellung.benutzer_id == benutzer.id,
                Erinnerungszustellung.kanal == kanal,
                Erinnerungszustellung.vorkommen >= von,
            )
        )
    }

    raus: list[Faellig] = []
    for termin in termine:
        for beginn in _vorkommen(termin, von, bis):
            weckzeit = beginn - timedelta(minutes=termin.erinnerung)
            if not (von <= weckzeit <= jetzt):
                continue

            schluessel = (termin.id, beginn, kanal)
            zeile = bekannt.get(schluessel)
            if zeile is None:
                zeile = Erinnerungszustellung(
                    termin_id=termin.id,
                    benutzer_id=benutzer.id,
                    vorkommen=beginn,
                    kanal=kanal,
                )
                db.add(zeile)
                db.flush()
            elif zeile.erledigt:
                continue
            elif zeile.schlummert_bis:
                if zeile.schlummert_bis > jetzt:
                    continue
            elif nur_einmal:
                # Schon gefeuert. Nur ein zeigender Kanal darf sie behalten.
                continue

            k = kalender[termin.kalender_id]
            raus.append(
                Faellig(
                    id=zeile.id,
                    termin_id=termin.id,
                    titel=termin.titel,
                    ort=termin.ort,
                    kalender=k.name,
                    farbe=k.farbe,
                    beginn=beginn,
                    ganztaegig=termin.ganztaegig,
                    vorlauf=termin.erinnerung,
                )
            )

    db.commit()
    raus.sort(key=lambda f: f.beginn)
    return raus


def _vorkommen(termin: Termin, von: datetime, bis: datetime) -> list[datetime]:
    """Die Beginn-Zeitpunkte dieses Termins im Fenster.

    ⚠️ **Das Fenster wird um den Vorlauf nach hinten erweitert.** Sonst fiele
    „einen Tag vorher" durch: Die Weckzeit läge im Fenster, der Termin selbst
    aber noch dahinter.
    """
    if not termin.rrule:
        return [termin.beginn] if von <= termin.beginn <= bis else []
    return [
        v.beginn
        for v in wiederholung.ausrechnen(
            termin.beginn, termin.ende, termin.rrule, termin.exdate,
            termin.zeitzone, von, bis,
        )
    ]


def erledigt(db: Session, benutzer: Benutzer, zustellung_id: int) -> None:
    """Weggeklickt. ⚠️ Die Zeile bleibt stehen — gelöscht käme die Erinnerung
    beim nächsten Abruf sofort wieder."""
    zeile = _meine(db, benutzer, zustellung_id)
    zeile.erledigt = True
    db.commit()


def schlummern(
    db: Session,
    benutzer: Benutzer,
    zustellung_id: int,
    minuten: int,
    *,
    jetzt: datetime | None = None,
) -> None:
    """Später noch einmal.

    ``jetzt`` gibt es nur, damit ein Test nicht auf die Uhr warten muss — im
    Betrieb ist es immer die Wanduhr.
    """
    if minuten not in SCHLUMMER:
        raise ErinnerungFehler("schlummer_unbekannt")
    zeile = _meine(db, benutzer, zustellung_id)
    zeile.schlummert_bis = (jetzt or utcnow()) + timedelta(minutes=minuten)
    zeile.erledigt = False
    db.commit()


class ErinnerungFehler(Exception):
    """Kennung, kein Satz — die Oberfläche formuliert."""


def _meine(db: Session, benutzer: Benutzer, zustellung_id: int) -> Erinnerungszustellung:
    zeile = db.get(Erinnerungszustellung, zustellung_id)
    if zeile is None or zeile.benutzer_id != benutzer.id:
        raise ErinnerungFehler("erinnerung_unbekannt")
    return zeile
