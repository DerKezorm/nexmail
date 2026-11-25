"""Die Ruecksetzpunkte auf dem Server, wie nexmail sie bis zum Modul ``sicherung`` anlegte.

⚠️ **Seit dem Modul ``sicherung`` (bauplaene/sicherung 1.0.1) verwaltet das Modul die Liste**, den Zeitplan, das
Behalten, das Herunterladen und Wiederherstellen (``services/sicherung_haken.py``). Hier bleibt nur, was die alten
Rücksetzpunkte (``nexmail-YYYYMMDD-HHMMSS.db`` mit ``.json``) lesen lässt, die Schlüssel des Zeitplans und
``anlegen`` in der Form von vorher (für den Bestand und seine Tests). ``db._sichern`` legt vor einer Schemaänderung
weiter eine solche ``.db`` an.

⚠️ **Ein Ruecksetzpunkt und eine Sicherung sind zwei verschiedene Dinge**, und
sie zu verwechseln ist der Fehler, der im Ernstfall weh tut:

* Ein **Ruecksetzpunkt** liegt hier, neben der Datenbank, und ist **vollstaendig**
  - samt Nachrichten. Er ist fuer ein missglucktes Update oder einen
  versehentlich geloeschten Kontakt. Dass er auf demselben Volume liegt, ist
  fuer diesen Zweck kein Mangel: Wer ihn braucht, hat kein Plattenproblem,
  sondern ein Aenderungsproblem. Und ein Ruecksetzpunkt, der danach erst
  stundenlang abgleichen muss, taugt dafuer nichts.
* Eine **Sicherung** ist das, was heruntergeladen wird: verschluesselt,
  schlank, ohne Nachrichten (siehe ``sicherung._schlank_machen``). Sie ist fuer
  den Fall, in dem dieser Rechner nicht mehr da ist.

⚠️ **Stirbt das Volume, sind die Ruecksetzpunkte mit weg.** Deshalb sagt die
Oberflaeche an jeder Zeile beides, statt ein „Sicherung" zu behaupten, das
keine ist.

⚠️ **Die Kopien sind unverschluesselt.** Sie tragen damit die Postfach-Zugaenge
in derselben Form wie die laufende Datenbank - und der Schluessel liegt
ohnehin danebem in ``secret.key``. Wer Dateizugriff hat, hat die Postfaecher,
mit oder ohne diese Liste. Ein Passwort davorzusetzen wuerde nichts schuetzen
und einen Ruecksetzpunkt unbrauchbar machen, dessen Passwort man vergessen hat.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..config import get_settings
from . import sicherung

logger = logging.getLogger("nexmail.sicherung")

#: Wie die Dateien heissen. ``db.py`` legt sie beim Schemawechsel genauso an -
#: das Muster ist damit die **einzige** Verabredung zwischen beiden Stellen.
MUSTER = re.compile(r"^nexmail-(\d{8}-\d{6})\.db$")

#: Wie viele Ruecksetzpunkte hoechstens liegen bleiben, wenn der Zeitplan
#: aufraeumt. Der Betreiber stellt es ein; das hier ist die Vorgabe.
BEHALTEN_VORGABE = 5

TAKTE = ("aus", "taeglich", "woechentlich", "monatlich")

SCHLUESSEL_TAKT = "sicherung_takt"
SCHLUESSEL_BEHALTEN = "sicherung_behalten"
SCHLUESSEL_ZULETZT = "sicherung_zuletzt"


def _ordner() -> Path:
    ordner = get_settings().data_dir / "sicherungen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _beipack(datei: Path) -> Path:
    return datei.with_suffix(".json")


def _notiz_lesen(datei: Path) -> dict:
    """Was neben der Kopie steht — Art, Kommentar, Fassung.

    ⚠️ **Eine Kopie ohne Beipackzettel ist kein Fehler.** ``db.py`` legt beim
    Schemawechsel nur die ``.db`` an, und aeltere Installationen haben gar
    keine Zettel. Beides muss in der Liste erscheinen, sonst verschwinden
    genau die Ruecksetzpunkte, die vor einem Update entstanden sind.
    """
    zettel = _beipack(datei)
    if not zettel.exists():
        return {"art": "update", "kommentar": "", "version": ""}
    try:
        return json.loads(zettel.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"art": "update", "kommentar": "", "version": ""}


def _zeitpunkt(name: str) -> str:
    treffer = MUSTER.match(name)
    if not treffer:
        return ""
    roh = treffer.group(1)
    return datetime.strptime(roh, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).isoformat()


def liste() -> list[dict]:
    """Alle Ruecksetzpunkte, neueste zuerst."""
    eintraege = []
    for datei in sorted(_ordner().glob("nexmail-*.db"), reverse=True):
        if not MUSTER.match(datei.name):
            continue
        notiz = _notiz_lesen(datei)
        eintraege.append(
            {
                "name": datei.name,
                "groesse": datei.stat().st_size,
                "erstellt": _zeitpunkt(datei.name),
                "art": notiz.get("art", "update"),
                "kommentar": notiz.get("kommentar", ""),
                "version": notiz.get("version", ""),
            }
        )
    return eintraege


def anlegen(art: str = "manuell", kommentar: str = "") -> dict:
    """Einen Ruecksetzpunkt aus dem laufenden Stand.

    ⚠️ **Ueber SQLites Sicherungs-Schnittstelle**, nicht mit einer Dateikopie —
    dieselbe Begruendung wie in ``sicherung._konsistente_kopie``: Eine Kopie
    mitten in einem Schreibvorgang ist ein halber Zustand, und man merkt es
    erst beim Zurueckspielen.
    """
    stempel = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ziel = _ordner() / f"nexmail-{stempel}.db"

    # ⚠️ Zwei Anlagen in derselben Sekunde wuerden einander ueberschreiben.
    # Kommt beim Klicken nicht vor, beim Testen sehr wohl.
    zaehler = 0
    while ziel.exists():
        zaehler += 1
        ziel = _ordner() / f"nexmail-{stempel[:-1]}{zaehler}.db"

    sicherung._konsistente_kopie(ziel)
    _beipack(ziel).write_text(
        json.dumps(
            {"art": art, "kommentar": kommentar.strip()[:200], "version": __version__},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("A restore point was created (%s).", art)

    return {
        "name": ziel.name,
        "groesse": ziel.stat().st_size,
        "erstellt": _zeitpunkt(ziel.name),
        "art": art,
        "kommentar": kommentar.strip()[:200],
        "version": __version__,
    }
