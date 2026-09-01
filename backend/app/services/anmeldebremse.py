"""Die Bremse an jeder Tuer, hinter der ein Geheimnis geprueft wird.

Ohne sie kann eine Maschine Passwoerter durchprobieren, so schnell die
Verbindung hergibt. Bei nexmail sind das drei Tueren:

1. ``/api/auth/anmelden`` - das nexmail-Passwort.
2. ``/api/auth/code`` - der sechsstellige TOTP-Code. **Die wichtigste von
   allen**: Sechs Stellen sind eine Million Moeglichkeiten, und ohne Bremse
   ist das in Minuten durchprobiert.
3. ``/api/auth/wiederherstellung`` - die Wiederherstellungscodes.

⚠️ **Hier wird nicht geschlafen.** Der naheliegende Bau waere, die Antwort um
ein paar Sekunden zu verzoegern. Das waere ein neues Loch: nexmail faehrt mit
einem Arbeitsprozess, und vierzig gleichzeitige Anfragen, die alle acht
Sekunden schlafen, legen den Dienst lahm - ohne ein einziges Passwort zu
raten. Stattdessen sofort 429 mit ``Retry-After``. Fuer den Menschen davor ist
das dasselbe ("warte kurz"), fuer die Maschine auch - nur kostet es nichts.

⚠️ **Der Merkposten liegt im Arbeitsspeicher.** In der Datenbank waere er
schlimmer, nicht besser: Jeder Fehlversuch loeste dann einen Schreibzugriff
aus, den **jeder ohne Anmeldung** ausloesen kann - also genau der Hebel, den
die Bremse verhindern soll. Der Preis ist, dass ein Neustart die Zaehler
vergisst; Neustarts sind selten und liegen nicht in der Hand des Angreifers.

Uebernommen aus ``nexview/backend/app/services/anmeldebremse.py`` samt
Begruendungen - dort hat sich der Aufbau bewaehrt.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

from ..config import get_settings

logger = logging.getLogger("nexmail.anmeldebremse")

#: Die ersten Versuche kosten nichts - ein Mensch vertippt sich.
FREI_VERSUCHE = 3

#: Ab dem vierten Fehlversuch verdoppelt sich die Wartezeit: 1, 2, 4, 8 …
WARTE_BASIS_SEKUNDEN = 1.0
WARTE_MAX_SEKUNDEN = 60.0

#: Ab hier ist Schluss, und zwar fuer eine Viertelstunde. Sie geht **von
#: selbst** wieder auf: Eine Sperre, die den Betreiber braucht, sperrt in der
#: Praxis den Betreiber aus.
SPERRE_AB_VERSUCH = 10
SPERRE_SEKUNDEN = 900.0

#: Wer eine Stunde nichts falsch macht, faengt bei null an. Sonst summieren
#: sich Vertipper ueber Wochen zu einer Sperre.
GEDAECHTNIS_SEKUNDEN = 3600.0


@dataclass
class _Zaehler:
    versuche: int = 0
    zuletzt: float = 0.0
    frei_ab: float = 0.0


_zaehler: dict[str, _Zaehler] = {}


def _jetzt() -> float:
    return time.monotonic()


def _aufraeumen(jetzt: float) -> None:
    """Vergessene Zaehler wegwerfen, damit die Ablage nicht endlos waechst."""
    if len(_zaehler) < 512:
        return
    alt = [k for k, z in _zaehler.items() if jetzt - z.zuletzt > GEDAECHTNIS_SEKUNDEN]
    for k in alt:
        _zaehler.pop(k, None)


def adresse_von(request: Request) -> str:
    """Die Adresse des Anfragenden - oder nichts.

    ⚠️ **Es wird nicht geraten.** Ohne ``NEXMAIL_CLIENT_IP`` gibt diese
    Funktion einen leeren Wert zurueck, und dann zaehlt die Bremse nur nach
    Konto. Der Grund: Hinter einem Proxy sehen alle Anfragen aus wie dieselbe
    Adresse. Eine Sperre nach Adresse wuerde dort beim ersten Vertipper den
    ganzen Haushalt aussperren.
    """
    einstellungen = get_settings()
    if not einstellungen.client_ip:
        return ""

    if einstellungen.client_ip == "direct":
        return request.client.host if request.client else ""

    kette = request.headers.get("x-forwarded-for", "")
    if not kette:
        return request.client.host if request.client else ""

    # Von rechts zaehlen: Das rechteste Glied hat der naechste Proxy
    # angehaengt, dem wir vertrauen. Wie viele davon uns gehoeren, sagt die
    # Einstellung - alles links davon kann der Anfragende selbst erfunden haben.
    glieder = [t.strip() for t in kette.split(",") if t.strip()]
    tiefe = einstellungen.anzahl_proxys()
    if len(glieder) < tiefe:
        return ""
    kandidat = glieder[-tiefe] if tiefe <= len(glieder) else glieder[0]
    try:
        return str(ipaddress.ip_address(kandidat))
    except ValueError:
        return ""


@dataclass
class Torwaechter:
    """Ein Vorgang an einer Tuer. ``fehlgeschlagen()`` bei falschem Geheimnis."""

    schluessel: list[str] = field(default_factory=list)

    def fehlgeschlagen(self) -> None:
        jetzt = _jetzt()
        for k in self.schluessel:
            z = _zaehler.setdefault(k, _Zaehler())
            if jetzt - z.zuletzt > GEDAECHTNIS_SEKUNDEN:
                z.versuche = 0
            z.versuche += 1
            z.zuletzt = jetzt
            if z.versuche >= SPERRE_AB_VERSUCH:
                z.frei_ab = jetzt + SPERRE_SEKUNDEN
            elif z.versuche > FREI_VERSUCHE:
                warte = min(
                    WARTE_MAX_SEKUNDEN,
                    WARTE_BASIS_SEKUNDEN * (2 ** (z.versuche - FREI_VERSUCHE - 1)),
                )
                z.frei_ab = jetzt + warte

    def geschafft(self) -> None:
        for k in self.schluessel:
            _zaehler.pop(k, None)


def torwaechter(request: Request, tuer: str, kennung: str) -> Torwaechter:
    """Pruefen, ob gerade angeklopft werden darf - sonst 429.

    Gezaehlt wird nach Konto **und**, sofern bekannt, nach Adresse. Beide
    Zaehler sperren unabhaengig voneinander.
    """
    jetzt = _jetzt()
    _aufraeumen(jetzt)

    schluessel = [f"{tuer}:konto:{kennung.lower()}"]
    adresse = adresse_von(request)
    if adresse:
        schluessel.append(f"{tuer}:adresse:{adresse}")

    for k in schluessel:
        z = _zaehler.get(k)
        if z is not None and z.frei_ab > jetzt:
            rest = math.ceil(z.frei_ab - jetzt)
            logger.info("Rate limit hit at %s (%s attempts, %s s left).", tuer, z.versuche, rest)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(rest)},
            )

    return Torwaechter(schluessel=schluessel)


def zuruecksetzen() -> None:
    """Nur fuer Tests - der Merkposten ist prozessweit."""
    _zaehler.clear()
