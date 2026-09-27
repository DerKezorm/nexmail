"""Hat die Mail die Absenderpruefung bestanden? Aus ``Authentication-Results``.

Gebraucht fuer das Markenlogo (BIMI, ``services/absenderbild.py``): Apple Mail
und Gmail zeigen ein Logo nur an einer Mail, die DMARC fuer ihre
Absenderdomain bestanden hat. Sonst bekaeme eine gefaelschte Mail im Namen
einer Bank deren Logo und saehe vertrauenswuerdiger aus als ohne.

nexmail prueft DMARC nicht selbst; das hat der empfangende Server schon getan
und sein Ergebnis oben in die Mail geschrieben (RFC 8601):

    Authentication-Results: mx.google.com; dkim=pass header.i=@revolut.com;
        spf=pass …; dmarc=pass (p=REJECT) header.from=revolut.com

⚠️ **Nur die oberste Zeile zaehlt.** Eine solche Zeile kann auch der
Absender in seine Mail schreiben. Sie steht dann aber weiter unten, denn der
empfangende Server setzt seine Zeilen oben davor.

⚠️ **Und auch die oberste nur, wenn sie vom gewohnten Pruefer stammt.**
Manche Anbieter schreiben gar keine Zeile. Dann waere die oberste die des
Faelschers. Deshalb lernt nexmail je Postfach, welcher Pruefer
(``authserv-id``) dort sonst unterschreibt (``vertraute_pruefer``), und
glaubt nur ihm. Wo es keinen gleichbleibenden gibt, gibt es kein Logo.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Nachricht

#: So viele juengste Mails eines Postfachs bestimmen den gewohnten Pruefer.
STICHPROBE = 200
#: Erst ab so vielen Mails mit Pruefzeile wird einem Pruefer geglaubt.
MINDESTENS = 5
#: Und nur, wenn er fast alle davon unterschrieben hat.
ANTEIL = 0.8

_ZEILE = re.compile(r"^authentication-results:", re.IGNORECASE)


def oberste_zeile(kopf: bytes | str) -> str:
    """Die oberste ``Authentication-Results``-Zeile, entfaltet, oder leer.

    ``kopf`` ist die Antwort auf ``HEADER.FIELDS (AUTHENTICATION-RESULTS)``;
    der Server liefert die Zeilen in der Reihenfolge der Mail.
    """
    text = kopf.decode("utf-8", "replace") if isinstance(kopf, bytes) else kopf
    zeilen: list[str] = []
    for roh in text.replace("\r\n", "\n").split("\n"):
        if _ZEILE.match(roh):
            if zeilen:
                break
            zeilen.append(roh.split(":", 1)[1])
        elif zeilen and roh[:1] in (" ", "\t"):
            zeilen.append(roh)
        elif zeilen:
            break
    return " ".join(z.strip() for z in zeilen)


def _ohne_kommentare(text: str) -> str:
    """RFC 8601 erlaubt Kommentare in Klammern, auch verschachtelt."""
    aus, tiefe = [], 0
    for zeichen in text:
        if zeichen == "(":
            tiefe += 1
        elif zeichen == ")" and tiefe:
            tiefe -= 1
        elif not tiefe:
            aus.append(zeichen)
    return "".join(aus)


def deuten(zeile: str, absender_domain: str) -> tuple[str, bool]:
    """Pruefer und ob die Mail fuer genau diese Absenderdomain bestanden hat.

    Zwei Wege, beide nach der Definition von DMARC (RFC 7489):

    * **Der Pruefer nennt DMARC** (``dmarc=pass``). Dann gilt sein Wort, und
      ``header.from`` muss die Domain der Mail sein: Ein ``pass`` fuer eine
      andere Domain (ein Weiterleiter, eine Liste) sagt ueber diese nichts.
      ⚠️ Nennt er ``fail``, bleibt es dabei, auch wenn DKIM bestanden hat.
    * **Er nennt es nicht, aber DKIM hat bestanden**, mit einer Unterschrift
      aus derselben Organisationsdomain wie der Absender. Genau das ist ein
      bestandenes DMARC. Gemessen am 27.09.2026: All-Inkl schreibt nur
      ``dkim=pass`` und nie ein ``dmarc=``; ohne diesen Weg bekaeme dort
      keine Mail je ein Logo.

    Ob die Domain DMARC auch durchsetzt (``p=quarantine`` oder ``reject``),
    fragt ``absenderbild`` vor dem Logo im DNS nach; BIMI verlangt es.
    """
    from .absenderbild import stammdomain

    if not zeile:
        return "", False
    teile = [t.strip() for t in _ohne_kommentare(zeile).split(";")]
    pruefer = teile[0].split()[0].lower() if teile and teile[0] else ""
    domain = absender_domain.lower().strip(".")
    if not domain:
        return pruefer, False
    dkim_passend = False
    for teil in teile[1:]:
        woerter = teil.split()
        if not woerter:
            continue
        methode, _, ergebnis = woerter[0].lower().partition("=")
        eigenschaften = {
            name.lower(): wert.lower().strip('"')
            for name, _, wert in (w.partition("=") for w in woerter[1:])
        }
        if methode == "dmarc":
            return pruefer, ergebnis == "pass" and eigenschaften.get("header.from") == domain
        if methode == "dkim" and ergebnis == "pass":
            unterschrift = eigenschaften.get("header.d") or eigenschaften.get("header.i", "").rpartition("@")[2]
            if unterschrift and stammdomain(unterschrift) == stammdomain(domain):
                dkim_passend = True
    return pruefer, dkim_passend


def vertraute_pruefer(db: Session, konto_ids: set[str]) -> dict[str, str]:
    """Je Postfach der Pruefer, der dort sonst unterschreibt, oder keiner.

    Gezaehlt ueber die juengsten Mails mit Pruefzeile. ⚠️ **Ein Faelscher
    kann den gewohnten Pruefer nicht verdraengen:** Wo der Anbieter selbst
    prueft, steht seine Zeile oben, und die gefaelschte zaehlt nie. Wo er es
    nicht tut, schreiben verschiedene Absender verschiedene Namen hinein, und
    keiner kommt auf den Anteil.
    """
    ergebnis: dict[str, str] = {}
    for konto_id in konto_ids:
        namen = db.execute(
            select(Nachricht.pruefer)
            .where(Nachricht.konto_id == konto_id, Nachricht.pruefer != "")
            .order_by(Nachricht.datum.desc())
            .limit(STICHPROBE)
        ).scalars().all()
        if len(namen) < MINDESTENS:
            continue
        haeufigster, anzahl = Counter(namen).most_common(1)[0]
        if anzahl / len(namen) >= ANTEIL:
            ergebnis[konto_id] = haeufigster
    return ergebnis


def geprueft(nachricht: Nachricht, vertraut: dict[str, str]) -> bool:
    """Darf diese Mail das Logo ihrer Absenderdomain tragen?"""
    return (
        nachricht.dmarc_bestanden
        and bool(nachricht.pruefer)
        and vertraut.get(nachricht.konto_id) == nachricht.pruefer
    )
