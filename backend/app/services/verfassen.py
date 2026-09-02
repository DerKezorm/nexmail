"""Eine Mail zusammenbauen — Antwort, Weiterleitung, neue Nachricht.

⚠️ **Das HTML aus dem Editor wird bereinigt, bevor es hinausgeht.** Nicht weil
dem eigenen Editor zu misstrauen wäre, sondern weil eine weitergeleitete Mail
fremdes HTML in den eigenen Entwurf trägt — und das ist dann genau der
Newsletter, dem man beim Lesen nicht getraut hat.

⚠️ **``In-Reply-To`` und ``References`` sind keine Zierde.** Ohne sie hängt
die Antwort beim Empfänger an keinem Strang, und in dessen Client steht sie
als neue Unterhaltung. Das ist der Unterschied zwischen einem Mail-Client und
einem Formular, das Mails verschickt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from . import bereinigen, mime

logger = logging.getLogger("nexmail.verfassen")


@dataclass
class Anlage:
    dateiname: str
    mime_typ: str
    inhalt: bytes
    #: Gesetzt bei Bildern, die im Text stehen sollen (``cid:``).
    cid: str = ""


@dataclass
class Entwurf:
    von_name: str
    von_adresse: str
    an: list[str]
    kopie: list[str] = field(default_factory=list)
    blindkopie: list[str] = field(default_factory=list)
    betreff: str = ""
    #: Was der Editor erzeugt hat. Wird hier bereinigt.
    html: str = ""
    #: Reiner Text. Fehlt er, wird er aus dem HTML gewonnen.
    text: str = ""
    anlagen: list[Anlage] = field(default_factory=list)
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    #: ``hoch`` | ``normal`` | ``niedrig``. Bei ``normal`` entsteht **keine**
    #: Kopfzeile — so machen es alle Clients, und eine ausdrueckliche
    #: „normal"-Zeile waere nur Rauschen.
    wichtigkeit: str = "normal"
    #: ⚠️ **Kennzeichnet die Mail als Antwort eines Automaten (RFC 3834).**
    #: Ohne das antwortet der Automat auf der anderen Seite zurueck, und zwei
    #: Abwesenheitsnotizen schaukeln sich auf, bis jemand es merkt. Gesetzt
    #: wird es ausschliesslich von ``services/abwesenheit.py``.
    auto_antwort: bool = False
    #: Eine ``.ics`` als zusaetzlicher Teil — fuer Antworten auf
    #: Termin-Einladungen. Der Wert ist der fertige Kalender, die Methode
    #: steht in ``kalender_methode``.
    kalender: str = ""
    kalender_methode: str = "REPLY"


def _adressen(roh: list[str]) -> list[str]:
    return [a.strip() for a in roh if a and a.strip()]


def bauen(entwurf: Entwurf) -> tuple[bytes, str]:
    """Aus einem Entwurf eine versandfertige Mail machen.

    Rückgabe: die rohen Bytes und die vergebene ``Message-ID``.
    """
    sauber = bereinigen.fuer_versand(entwurf.html) if entwurf.html else ""
    text = entwurf.text or (bereinigen.text_aus_html(sauber, laenge=100_000) if sauber else "")

    nachricht = EmailMessage()
    nachricht["From"] = formataddr((entwurf.von_name, entwurf.von_adresse))
    nachricht["To"] = ", ".join(_adressen(entwurf.an))
    if entwurf.kopie:
        nachricht["Cc"] = ", ".join(_adressen(entwurf.kopie))
    nachricht["Subject"] = entwurf.betreff
    nachricht["Date"] = formatdate(localtime=True)

    kennung = make_msgid(domain=entwurf.von_adresse.split("@")[-1] or None)
    nachricht["Message-ID"] = kennung

    # ⚠️ **Immer beide Kopfzeilen, nicht eine.** Outlook liest ``Importance``,
    # Thunderbird ``X-Priority`` — wer nur eine schreibt, ist fuer die Haelfte
    # der Empfaenger eine gewoehnliche Mail.
    if entwurf.wichtigkeit == "hoch":
        nachricht["Importance"] = "high"
        nachricht["X-Priority"] = "1"
    elif entwurf.wichtigkeit == "niedrig":
        nachricht["Importance"] = "low"
        nachricht["X-Priority"] = "5"

    if entwurf.auto_antwort:
        # RFC 3834 fuer alle, die sich daran halten ...
        nachricht["Auto-Submitted"] = "auto-replied"
        # ... und die Outlook-Welt, die es nicht tut.
        nachricht["X-Auto-Response-Suppress"] = "All"
        nachricht["Precedence"] = "auto_reply"

    if entwurf.in_reply_to:
        nachricht["In-Reply-To"] = entwurf.in_reply_to
    if entwurf.references:
        # ⚠️ Die Kette wächst, sie wird nicht ersetzt. Wer nur die letzte
        # Kennung einträgt, reißt den Strang beim dritten Hin und Her ab.
        nachricht["References"] = " ".join(entwurf.references)

    # ⚠️ **Blindkopie steht in keiner Kopfzeile.** Sie wird beim Versand als
    # Empfänger mitgegeben und sonst nirgends - sonst steht sie bei jedem
    # Empfänger in der Mail, und „blind" war sie nie.

    nachricht.set_content(text or " ")

    # ⚠️ **Der Kalenderteil steht NEBEN dem Text, nicht statt seiner.** Ein
    # Empfaenger ohne Kalenderunterstuetzung soll trotzdem lesen koennen, was
    # geantwortet wurde. Und die ``method`` gehoert an den Medientyp: Ohne sie
    # halten Outlook und Google die Antwort fuer eine neue Einladung.
    if entwurf.kalender:
        nachricht.add_alternative(
            entwurf.kalender,
            subtype="calendar",
            params={"method": entwurf.kalender_methode, "charset": "utf-8"},
        )

    if sauber:
        inline = [a for a in entwurf.anlagen if a.cid]
        nachricht.add_alternative(_html_seite(sauber), subtype="html")
        for anlage in inline:
            teil = nachricht.get_payload()[-1]
            haupt, _, unter = anlage.mime_typ.partition("/")
            teil.add_related(
                anlage.inhalt,
                maintype=haupt or "image",
                subtype=unter or "png",
                cid=f"<{anlage.cid}>",
                filename=anlage.dateiname,
            )

    for anlage in entwurf.anlagen:
        if anlage.cid:
            continue
        haupt, _, unter = anlage.mime_typ.partition("/")
        if haupt == "message" and unter.lower() == "rfc822":
            # ⚠️ **Als Nachricht anhängen, nicht als Bytes.** Rohe Bytes würde
            # der Inhaltsverwalter mit Base64 kodieren — und einen Base64-
            # kodierten ``message/rfc822``-Teil kann kaum ein Empfänger
            # öffnen, Pythons eigener Parser eingeschlossen (RFC 2046 erlaubt
            # dort nur 7bit/8bit/binary). Das Zerlegen mit ``compat32`` lässt
            # Kopfzeilen und Körper, wie sie sind; nur die Zeilenenden werden
            # auf die der umgebenden Mail vereinheitlicht.
            nachricht.add_attachment(
                message_from_bytes(anlage.inhalt), filename=anlage.dateiname
            )
            continue
        nachricht.add_attachment(
            anlage.inhalt,
            maintype=haupt or "application",
            subtype=unter or "octet-stream",
            filename=anlage.dateiname,
        )

    return nachricht.as_bytes(), kennung


def _html_seite(rumpf: str) -> str:
    """Ein vollständiges Dokument, damit alte Clients nicht raten müssen."""
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        f"<body>{rumpf}</body></html>"
    )


# --- Antworten und Weiterleiten ------------------------------------------ #

#: Wer eine eigene Adresse als Empfänger einer Antwort einträgt, schreibt sich
#: selbst. Die Liste kommt von außen — nexmail kennt die eigenen Postfächer.
def antwort_empfaenger(
    zerlegt: mime.Zerlegt, eigene: set[str], allen: bool
) -> tuple[list[str], list[str]]:
    """Wer bekommt die Antwort?

    ⚠️ **Die eigene Adresse fliegt heraus.** Sonst schickt man sich bei jedem
    „Allen antworten" eine Kopie an sich selbst - und in einem Verteiler
    verdoppelt sich das mit jeder Runde.
    """
    an = [zerlegt.von.adresse] if zerlegt.von.adresse else []
    if not allen:
        return an, []

    for person in zerlegt.an:
        if person.adresse and person.adresse.lower() not in eigene and person.adresse not in an:
            an.append(person.adresse)

    kopie = [
        p.adresse
        for p in zerlegt.kopie
        if p.adresse and p.adresse.lower() not in eigene and p.adresse not in an
    ]
    return an, kopie


def antwort_betreff(betreff: str) -> str:
    kern = mime.betreff_kern(betreff)
    return f"AW: {kern}" if kern else "AW:"


def weiterleitung_betreff(betreff: str) -> str:
    kern = mime.betreff_kern(betreff)
    return f"WG: {kern}" if kern else "WG:"


def weiterleitung_anhang_betreff(betreff: str) -> str:
    """Der Betreff beim Weiterleiten **als Anhang**: ``Fwd:`` vor dem Original.

    ⚠️ Bewusst der ganze Originalbetreff, nicht der Kern: Im Anhang steckt die
    Mail mit genau diesem Betreff — wer „AW: …" weiterreicht, will, dass der
    Empfänger dieselbe Zeile liest, die er selbst vor sich hat.
    """
    kern = (betreff or "").strip()
    return f"Fwd: {kern}" if kern else "Fwd:"


def zitat_text(zerlegt: mime.Zerlegt, sprache: str = "de") -> str:
    """Das eingerückte Zitat für die Textfassung.

    ⚠️ **Zweite Pflegestelle neben ``frontend/src/i18n/``** — wie
    ``_DRUCK_TEXTE`` in ``routers/nachrichten.py``: Eine dritte Sprache
    braucht hier einen eigenen Zweig, sonst bekommt sie den englischen Kopf.
    """
    kopf = (
        f"Am {zerlegt.datum:%d.%m.%Y um %H:%M} schrieb "
        f"{zerlegt.von.name or zerlegt.von.adresse}:"
        if sprache == "de"
        else f"On {zerlegt.datum:%Y-%m-%d %H:%M}, {zerlegt.von.name or zerlegt.von.adresse} wrote:"
    )
    zeilen = (zerlegt.text or bereinigen.text_aus_html(zerlegt.html, 100_000)).splitlines()
    return kopf + "\n" + "\n".join(f"> {z}" for z in zeilen)


def zitat_html(zerlegt: mime.Zerlegt, sprache: str = "de") -> str:
    """Dasselbe für die HTML-Fassung.

    ⚠️ Das Zitat wird **bereinigt**, bevor es in den Entwurf wandert. Es ist
    fremdes HTML, und daran ändert sich nichts dadurch, dass man es weiterreicht.
    """
    kopf = (
        f"Am {zerlegt.datum:%d.%m.%Y um %H:%M} schrieb "
        f"{zerlegt.von.name or zerlegt.von.adresse}:"
        if sprache == "de"
        else f"On {zerlegt.datum:%Y-%m-%d %H:%M}, {zerlegt.von.name or zerlegt.von.adresse} wrote:"
    )
    rumpf = (
        bereinigen.saeubern(zerlegt.html)
        if zerlegt.html
        else "<pre>" + _maskieren(zerlegt.text) + "</pre>"
    )
    return (
        f"<p>{_maskieren(kopf)}</p>"
        '<blockquote style="margin:0 0 0 12px;padding-left:12px;'
        'border-left:2px solid #ccc">' + rumpf + "</blockquote>"
    )


def weiterleitung_html(zerlegt: mime.Zerlegt) -> str:
    """Der Kopfblock, den weitergeleitete Mails tragen.

    ⚠️ **Die Trennzeile unten ist ein Vertrag mit der Oberfläche.**
    ``frontend/src/lib/anhang.ts`` (``ZITAT_MARKEN``) schneidet den eigenen
    Text genau an dieser Zeichenkette ab, bevor die Anhang-Erinnerung prüft.
    Wer sie umformuliert oder übersetzt, macht die Erinnerung bei jeder
    Weiterleitung zur Falschnachfrage — ``test_verfassen`` hält die beiden
    Seiten deshalb wörtlich aneinander.
    """
    zeilen = [
        ("Von", zerlegt.von.name and f"{zerlegt.von.name} <{zerlegt.von.adresse}>" or zerlegt.von.adresse),
        ("Datum", f"{zerlegt.datum:%d.%m.%Y %H:%M}"),
        ("Betreff", zerlegt.betreff),
        ("An", ", ".join(p.adresse for p in zerlegt.an)),
    ]
    kopf = "".join(f"<div><b>{n}:</b> {_maskieren(w)}</div>" for n, w in zeilen if w)
    rumpf = (
        bereinigen.saeubern(zerlegt.html)
        if zerlegt.html
        else "<pre>" + _maskieren(zerlegt.text) + "</pre>"
    )
    return (
        "<p>---------- Weitergeleitete Nachricht ----------</p>"
        + kopf
        + "<br>"
        + rumpf
    )


def _maskieren(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def references_fuer_antwort(zerlegt: mime.Zerlegt) -> list[str]:
    """Die Kette für die Antwort — vorhandene plus die beantwortete Kennung."""
    kette = list(zerlegt.references)
    if zerlegt.message_id and zerlegt.message_id not in kette:
        kette.append(zerlegt.message_id)
    # Lange Ketten kürzen, aber die Wurzel behalten: Sie hält den Strang
    # zusammen, die Mitte tut es nicht.
    if len(kette) > 20:
        kette = kette[:1] + kette[-19:]
    return kette
