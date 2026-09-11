"""Eine vCard-Datei in ein verbundenes Buch einlesen: ein Vorgang mit Fortschritt.

Ins lokale Buch liest ``kontakte.aus_vcard`` eine Datei in einem Zug ein; das
ist ein paar Zeilen in der eigenen Datenbank. In einem verbundenen Buch gilt
„erst der Server, dann die eigene Datenbank": Jede Karte geht einzeln zum
Anbieter, und dreihundert ``PUT`` dauern Minuten. Das gehört nicht in eine
Anfrage, die ein Proxy nach dreißig Sekunden kappt, sondern in einen Faden,
dessen Stand die Oberfläche abfragt — dasselbe Muster wie der mbox-Import in
``austausch.py``, und aus demselben Grund.

⚠️ **Er lebt im Speicher, nicht in der Datenbank.** Ein Neustart beendet ihn;
was bis dahin angelegt wurde, steht beim Anbieter und hier, und ein zweiter
Anlauf mit derselben Datei überspringt es (Adresse, UID, Name samt Nummer).

⚠️ **Ein Konflikt beim Anbieter ist ein Überspringen, kein Fehler.** Trägt die
Karte eine UID, die drüben schon liegt, antwortet der Server auf
``If-None-Match: *`` mit 412 — die Karte ist da, und genau das wollte der
Import. Was der Anbieter sonst ablehnt, zählt als Fehler und hält den Vorgang
nicht an; erst zehn Fehlschläge hintereinander gelten als „die Verbindung ist
weg", wie beim mbox-Import.

⚠️ **Einer auf einmal je Benutzer.** Zwei Importe in dasselbe Buch sähen die
Zeilen des anderen nicht, bevor sie angelegt sind, und legten sie doppelt an.
"""

from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..meldung import Meldung

logger = logging.getLogger("nexmail.kontaktvorgang")

#: Wie lange ein beendeter Vorgang abrufbar bleibt, bevor er vergessen wird.
VORGANG_ALTER_SEKUNDEN = 3600
#: So viele Fehlschläge hintereinander heissen: Der Anbieter antwortet nicht
#: mehr sinnvoll; weiterzumachen brächte nur dieselbe Meldung dreihundertmal.
FEHLER_IN_FOLGE = 10
#: Höchstens so viele Kennungen werden gemerkt; die Zahl zählt weiter.
FEHLER_GEMERKT = 10


@dataclass
class Vorgang:
    id: str
    benutzer_id: str
    adressbuch_id: str
    dateiname: str
    gesamt: int = 0
    gelesen: int = 0
    neu: int = 0
    uebersprungen: int = 0
    fehler_gesamt: int = 0
    #: Die Kennungen der ersten Fehlschläge, für die Anzeige.
    fehler: list[str] = field(default_factory=list)
    laeuft: bool = True
    #: Die Kennung, an der der ganze Vorgang scheiterte. Leer heisst: lief.
    fehler_satz: str = ""
    abgebrochen: bool = False
    beendet: datetime | None = None
    halt: threading.Event = field(default_factory=threading.Event)
    #: Nur zum Abwarten in Tests; im Betrieb fragt die Oberfläche den Stand.
    faden: threading.Thread | None = None


_VORGAENGE: dict[str, Vorgang] = {}
_SCHLOSS = threading.Lock()


def _aufraeumen() -> None:
    grenze = datetime.now(timezone.utc).timestamp() - VORGANG_ALTER_SEKUNDEN
    for kennung, vorgang in list(_VORGAENGE.items()):
        if not vorgang.laeuft and vorgang.beendet and vorgang.beendet.timestamp() < grenze:
            del _VORGAENGE[kennung]


def laeuft_schon(benutzer_id: str) -> Vorgang | None:
    with _SCHLOSS:
        for vorgang in _VORGAENGE.values():
            if vorgang.laeuft and vorgang.benutzer_id == benutzer_id:
                return vorgang
    return None


def stand(kennung: str, benutzer_id: str) -> Vorgang | None:
    with _SCHLOSS:
        vorgang = _VORGAENGE.get(kennung)
    # Fremder Besitz wird behandelt wie „gibt es nicht".
    return vorgang if vorgang and vorgang.benutzer_id == benutzer_id else None


def abbrechen(kennung: str, benutzer_id: str) -> bool:
    vorgang = stand(kennung, benutzer_id)
    if vorgang is None or not vorgang.laeuft:
        return False
    vorgang.halt.set()
    return True


def vorgang_starten(benutzer_id: str, adressbuch_id: str, dateiname: str, inhalt: str) -> Vorgang:
    """Den Import in einem eigenen Faden anwerfen. Die Datei ist Text und
    höchstens ein paar Megabyte; sie reist im Speicher mit."""
    vorgang = Vorgang(
        id=secrets.token_urlsafe(12),
        benutzer_id=benutzer_id,
        adressbuch_id=adressbuch_id,
        dateiname=dateiname,
    )
    with _SCHLOSS:
        _aufraeumen()
        _VORGAENGE[vorgang.id] = vorgang
    vorgang.faden = threading.Thread(
        target=_lauf, args=(vorgang, inhalt), name=f"nexmail-vcard-{vorgang.id}", daemon=True
    )
    vorgang.faden.start()
    return vorgang


def _lauf(vorgang: Vorgang, inhalt: str) -> None:
    from ..db import SessionLocal
    from ..models import Adressbuch, Benutzer
    from . import adressbuchabgleich, caldav, carddav
    from . import kontakte as kontaktdienst

    db = SessionLocal()
    try:
        person = db.get(Benutzer, vorgang.benutzer_id)
        buch = db.get(Adressbuch, vorgang.adressbuch_id)
        if person is None or buch is None or not buch.art or buch.benutzer_id != person.id:
            vorgang.fehler_satz = "adressbuch_nicht_gefunden"
            return
        karten = kontaktdienst.karten_aus_datei(inhalt)
        vorgang.gesamt = len(karten)
        in_folge = 0
        # ⚠️ Eine Verbindung für den ganzen Vorgang, nicht eine je Karte —
        # iCloud lässt je Konto nur eine zu, und dreihundert Handschläge
        # dauern länger als dreihundert PUT.
        with carddav.sitzung(adressbuchabgleich.zugang(buch, db)) as klient:
            for felder, zeilen in karten:
                if vorgang.halt.is_set():
                    vorgang.abgebrochen = True
                    break
                vorgang.gelesen += 1
                try:
                    stand_der_karte = kontaktdienst.in_buch_einlesen(db, person, buch, felder, zeilen, klient)
                except carddav.KonfliktFehler:
                    # Die Karte liegt drüben schon (gleiche UID): genau das,
                    # was der Import wollte.
                    db.rollback()
                    vorgang.uebersprungen += 1
                    in_folge = 0
                    continue
                except (carddav.CarddavFehler, caldav.CaldavFehler) as f:
                    db.rollback()
                    vorgang.fehler_gesamt += 1
                    if len(vorgang.fehler) < FEHLER_GEMERKT:
                        vorgang.fehler.append(str(f))
                    in_folge += 1
                    if in_folge >= FEHLER_IN_FOLGE:
                        vorgang.fehler_satz = str(f)
                        break
                    continue
                in_folge = 0
                if stand_der_karte == "neu":
                    vorgang.neu += 1
                else:
                    vorgang.uebersprungen += 1
    except Exception as fehler:  # noqa: BLE001
        db.rollback()
        # Eine benannte Meldung reist als Kennung weiter; alles andere ist ein
        # Programmfehler und heisst für den Menschen „schreiben gescheitert".
        vorgang.fehler_satz = fehler.kennung if isinstance(fehler, Meldung) else "carddav_schreiben_gescheitert"
        logger.exception("vCard import %s into a connected book failed.", vorgang.id)
    finally:
        db.close()
        vorgang.beendet = datetime.now(timezone.utc)
        vorgang.laeuft = False
        logger.info(
            "vCard import into a connected book: %s new, %s skipped, %s failed of %s.",
            vorgang.neu, vorgang.uebersprungen, vorgang.fehler_gesamt, vorgang.gesamt,
        )
