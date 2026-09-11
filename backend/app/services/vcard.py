"""vCard-Text: entfalten, maskieren, und **eine Karte zeilenweise ändern**.

Die Rückfahrkarte ist der ganze Punkt. Eine Karte von iCloud trägt Foto,
Geburtstag, mehrere Anschriften und ein Dutzend ``X-APPLE-…``; nexmail kennt
fünf Felder. Wer beim Zurückschreiben die Karte aus seinen Feldern neu baut,
löscht dem Besitzer alles andere, und der merkt es, wenn das Foto weg ist.
``aktualisieren`` ersetzt deshalb genau die Zeilen, die zu den geänderten
Feldern gehören, und lässt jede andere stehen. Dieselbe Regel wie
``vevent.aktualisieren`` beim Kalender.

⚠️ **Welche TEL-Zeile gemeint ist, sagt der ALTE Wert.** Die Karte hat mehrere
Nummern, das Feld zeigt eine (die Handynummer, siehe ``kontakte._bevorzugt``).
Geändert wird die Zeile, deren Wert dem alten Feld entspricht; steht die alte
nicht mehr in der Karte, kommt eine neue Zeile dazu, statt irgendeine zu
treffen. Ein leeres neues Feld nimmt genau diese Zeile heraus. Für ``EMAIL``
gilt dasselbe, verglichen ohne Groß und Klein.

⚠️ **Der Name schreibt FN und N.** Apple liest den Namen aus ``N``; wer nur
``FN`` ändert, sieht am Telefon weiter den alten. ``N`` wird am letzten
Leerzeichen geteilt: „Anna Beispiel" wird ``Beispiel;Anna;;;``, ein einzelnes
Wort ein Vorname. Das ist eine Annahme, und sie steht hier, damit sie nicht
still altert. ``N`` wird nur angefasst, wenn sich der Name geändert hat; Apples
eigene Teilung bleibt sonst stehen.

⚠️ **Gefaltet wird beim Schreiben, entfaltet beim Lesen.** Zeilen über 75
Oktett müssen umgebrochen werden (RFC 6350 3.2); die Faltung ist dieselbe wie
beim Kalender und wird von dort geholt, eine Kopie liefe auseinander.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# ⚠️ Import über den Unterstrich hinweg, mit Absicht: RFC 6350 faltet genau
# wie RFC 5545, und beim Kalender ist die Faltung an Umlauten schon einmal
# gerissen (03.09.2026). Zwei Fassungen hiessen, dass die nächste Behebung
# nur an einer landet.
from .vevent import _falten as falten

# --- Text ------------------------------------------------------------------ #


def maskieren(wert: str) -> str:
    """⚠️ Komma, Semikolon und Zeilenumbruch sind in vCard **Trennzeichen**.

    Ein Name wie „Müller, Gertrud" zerlegt die Datei sonst in Felder, die
    niemand mehr zusammensetzt.
    """
    return (
        wert.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def entmaskieren(wert: str) -> str:
    ergebnis = []
    schraege = False
    for zeichen in wert:
        if schraege:
            ergebnis.append({"n": "\n", "N": "\n"}.get(zeichen, zeichen))
            schraege = False
        elif zeichen == "\\":
            schraege = True
        else:
            ergebnis.append(zeichen)
    return "".join(ergebnis)


def felder_trennen(roh: str) -> list[str]:
    r"""Einen strukturierten vCard-Wert an den **unmaskierten** Semikola teilen.

    ⚠️ **Die Reihenfolge ist der ganze Punkt.** ``ORG`` und ``N`` bestehen aus
    mehreren Teilen, getrennt durch ``;``, aber ein Semikolon *im* Wert steht
    als ``\;`` da. Wer zuerst entmaskiert und dann trennt, zerschneidet genau
    das Zeichen, das die Maskierung schützen sollte: Aus „Meier; Söhne" wird
    „Meier". Beim Rundlauf-Test aufgefallen, nicht beim Nachdenken.
    """
    teile: list[str] = []
    aktuell: list[str] = []
    schraege = False
    for zeichen in roh:
        if schraege:
            aktuell.append("\n" if zeichen in ("n", "N") else zeichen)
            schraege = False
        elif zeichen == "\\":
            schraege = True
        elif zeichen == ";":
            teile.append("".join(aktuell))
            aktuell = []
        else:
            aktuell.append(zeichen)
    teile.append("".join(aktuell))
    return teile


def entfalten(inhalt: str) -> list[str]:
    """Gefaltete Zeilen zusammensetzen.

    ⚠️ **Zuerst, immer.** vCard bricht lange Werte nach 75 Zeichen um und
    rückt die Fortsetzung ein; wer Zeile für Zeile liest, bekommt
    abgeschnittene Namen und verliert lange Notizen.
    """
    zeilen: list[str] = []
    for roh in inhalt.replace("\r\n", "\n").split("\n"):
        if roh[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += roh[1:]
        else:
            zeilen.append(roh)
    return zeilen


# --- Die Karte zeilenweise ändern ------------------------------------------ #

#: Die Felder, die nexmail an einer Karte pflegt, in der Reihenfolge, in der
#: eine neue Karte sie trägt.
FELDER = ("name", "adresse", "firma", "telefon", "notiz")


def _name_von(zeile: str) -> str:
    """Der Eigenschaftsname einer Zeile, ohne Gruppe und Parameter, gross.
    Leer, wenn es keine Eigenschaftszeile ist."""
    if ":" not in zeile:
        return ""
    kopf = zeile.split(":", 1)[0]
    name = kopf.split(";", 1)[0].strip()
    if "." in name:
        name = name.rsplit(".", 1)[1]
    return name.upper()


def _wert_von(zeile: str) -> str:
    return zeile.split(":", 1)[1] if ":" in zeile else ""


def _mit_wert(zeile: str, wert: str) -> str:
    """Dieselbe Zeile mit anderem Wert; Gruppe und Parameter bleiben."""
    return zeile.split(":", 1)[0] + ":" + wert


def _n_wert(name: str) -> str:
    """``Nachname;Vorname;;;`` aus einem Anzeigenamen, siehe Kopf der Datei."""
    teile = name.split()
    if not teile:
        return ";;;;"
    if len(teile) == 1:
        return f";{maskieren(teile[0])};;;"
    return f"{maskieren(teile[-1])};{maskieren(' '.join(teile[:-1]))};;;"


def _jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class _Karte:
    """Die Zeilen einer Karte, mit den Handgriffen, die ``aktualisieren`` braucht."""

    def __init__(self, roh: str) -> None:
        zeilen = [z for z in entfalten(roh) if z.strip()] if roh.strip() else []
        if not any(_name_von(z) == "BEGIN" for z in zeilen):
            zeilen = ["BEGIN:VCARD", "VERSION:3.0", "END:VCARD"]
        if not any(z.strip().upper() == "END:VCARD" for z in zeilen):
            zeilen.append("END:VCARD")
        self.zeilen = zeilen

    def _ende(self) -> int:
        for i in range(len(self.zeilen) - 1, -1, -1):
            if self.zeilen[i].strip().upper() == "END:VCARD":
                return i
        return len(self.zeilen)

    def finde(self, name: str, passt=None) -> int | None:
        for i, zeile in enumerate(self.zeilen):
            if _name_von(zeile) == name and (passt is None or passt(_wert_von(zeile))):
                return i
        return None

    def setze(self, name: str, wert: str, vorlage: str) -> None:
        """Den Wert der ersten Zeile dieses Namens setzen, sonst eine anhängen."""
        i = self.finde(name)
        if i is None:
            self.zeilen.insert(self._ende(), vorlage + wert)
        else:
            self.zeilen[i] = _mit_wert(self.zeilen[i], wert)

    def entferne(self, i: int) -> None:
        del self.zeilen[i]

    def uid_sichern(self, uid: str) -> None:
        if self.finde("UID") is not None:
            return
        # Hinter VERSION, wo jede Karte sie erwartet; sonst gleich hinter BEGIN.
        stelle = self.finde("VERSION")
        stelle = (stelle + 1) if stelle is not None else 1
        self.zeilen.insert(stelle, "UID:" + (uid or f"{uuid.uuid4()}@nexmail"))

    def wert_ersetzen(
        self, name: str, alt: str, neu: str, vorlage: str, ohne_gross_klein: bool
    ) -> None:
        """Die Zeile mit dem alten Wert bekommt den neuen; ohne alte kommt eine
        neue dazu; ein leerer neuer Wert nimmt die alte heraus."""
        alt = alt.strip()
        neu = neu.strip()
        if alt == neu:
            return

        def passt(wert: str) -> bool:
            w = entmaskieren(wert).strip()
            return w.lower() == alt.lower() if ohne_gross_klein else w == alt

        i = self.finde(name, passt) if alt else None
        if i is not None:
            if neu:
                self.zeilen[i] = _mit_wert(self.zeilen[i], maskieren(neu))
            else:
                self.entferne(i)
        elif neu:
            self.zeilen.insert(self._ende(), vorlage + maskieren(neu))

    def text(self) -> str:
        raus: list[str] = []
        for zeile in self.zeilen:
            raus.extend(falten(zeile))
        # ⚠️ CRLF ist vorgeschrieben (RFC 6350 3.2). Manche Programme sind
        # nachsichtig, Outlook ist es nicht.
        return "\r\n".join(raus) + "\r\n"


def aktualisieren(roh: str, vorher: dict, nachher: dict, uid: str = "") -> str:
    """Die fünf Felder in eine bestehende Karte schreiben, den Rest lassen.

    ``vorher`` sind die Werte, die die Zeile bis eben trug (aus ihnen wird die
    betroffene ``TEL``- und ``EMAIL``-Zeile erkannt), ``nachher`` die neuen.
    Fehlende Schlüssel gelten als leer. Ohne ``roh`` entsteht eine neue Karte.
    """
    karte = _Karte(roh)
    alt = {f: (vorher.get(f) or "").strip() for f in FELDER}
    neu = {f: (nachher.get(f) or "").strip() for f in FELDER}

    karte.uid_sichern(uid)

    # Der Name: FN ist Pflicht und trägt das Nächste, was den Menschen benennt,
    # wenn kein Name da ist. ⚠️ Die Firma vor Adresse und Nummer, wie überall.
    anzeige = neu["name"] or neu["firma"] or neu["adresse"] or neu["telefon"]
    fn = karte.finde("FN")
    if fn is None or neu["name"] != alt["name"] or not _wert_von(karte.zeilen[fn]).strip():
        karte.setze("FN", maskieren(anzeige), "FN:")
    if neu["name"] != alt["name"] or karte.finde("N") is None:
        karte.setze("N", _n_wert(neu["name"]), "N:")

    karte.wert_ersetzen("EMAIL", alt["adresse"], neu["adresse"], "EMAIL;TYPE=INTERNET:", True)
    karte.wert_ersetzen("TEL", alt["telefon"], neu["telefon"], "TEL:", False)

    if neu["firma"] != alt["firma"]:
        i = karte.finde("ORG")
        if i is None:
            if neu["firma"]:
                karte.zeilen.insert(karte._ende(), "ORG:" + maskieren(neu["firma"]))
        else:
            # ORG ist Firma;Abteilung;… — nur der erste Teil gehört nexmail.
            teile = felder_trennen(_wert_von(karte.zeilen[i]))
            teile[0] = neu["firma"]
            if any(t.strip() for t in teile):
                karte.zeilen[i] = _mit_wert(karte.zeilen[i], ";".join(maskieren(t) for t in teile))
            else:
                karte.entferne(i)

    if neu["notiz"] != alt["notiz"]:
        i = karte.finde("NOTE")
        if neu["notiz"]:
            karte.setze("NOTE", maskieren(neu["notiz"]), "NOTE:")
        elif i is not None:
            karte.entferne(i)

    # Wann zuletzt geändert: Andere Programme lesen es, wir schreiben es mit.
    karte.setze("REV", _jetzt(), "REV:")
    return karte.text()


def neu_bauen(felder: dict, uid: str = "") -> str:
    """Eine frische Karte aus den fünf Feldern."""
    return aktualisieren("", {}, felder, uid)
