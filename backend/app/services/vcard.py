"""vCard-Text: lesen, entfalten, maskieren, und **eine Karte zeilenweise ändern**.

Die Rückfahrkarte ist der ganze Punkt. Eine Karte von iCloud trägt Foto,
Social-Profile, Messenger und ein Dutzend ``X-APPLE-…``; nexmail kennt einen
Teil davon. Wer beim Zurückschreiben die Karte aus seinen Feldern neu baut,
löscht dem Besitzer alles andere, und der merkt es, wenn das Foto weg ist.
``aktualisieren`` ersetzt deshalb genau die Zeilen, die zu den Feldern
gehören, die nexmail pflegt, und lässt jede andere stehen. Dieselbe Regel wie
``vevent.aktualisieren`` beim Kalender.

⚠️ **Nur was sich geändert hat, wird angefasst.** Eine Zeile, deren gelesener
Wert dem neuen Feld gleicht, bleibt wörtlich stehen, samt Apples Parametern
und Schreibweisen (``BDAY;value=date:``, ``type=IPHONE``). Wer jede Zeile neu
schreibt, macht aus jedem Speichern eine Änderung, die drüben auffällt.

⚠️ **Listen (TEL, EMAIL, ADR) werden am Wert wiedererkannt.** Die Karte hat
mehrere Nummern; die Zeile mit derselben Nummer bleibt und bekommt höchstens
neue Parameter, eine Nummer ohne Zeile kommt dazu, eine Zeile ohne Nummer
fällt samt ihrer Gruppe (``item1.X-ABLabel``). Verglichen werden Nummern
ohne Leerzeichen und Striche, Adressen ohne Groß und Klein, Anschriften Teil
für Teil.

⚠️ **Der Name schreibt FN und N.** Apple liest ihn aus ``N``; wer nur ``FN``
ändert, sieht am Telefon weiter den alten. Vorname und Nachname stehen in
``N`` an zweiter und erster Stelle; Zweitname, Anrede und Titel dahinter
bleiben, wie Apple sie geschrieben hat.

⚠️ **Beschriftungen gehen als Apples Gruppe hinaus** (``item2.TEL`` mit
``item2.X-ABLabel:Zweitbüro``). Das ist keine Norm, aber das, was iCloud
schreibt und Google liest; eine eigene Erfindung läse niemand.

⚠️ **Gefaltet wird beim Schreiben, entfaltet beim Lesen.** Zeilen über 75
Oktett müssen umgebrochen werden (RFC 6350 3.2); die Faltung ist dieselbe wie
beim Kalender und wird von dort geholt, eine Kopie liefe auseinander.
"""

from __future__ import annotations

import re
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


# --- Die Felder ------------------------------------------------------------ #

#: Die einwertigen Felder, die nexmail an einer Karte pflegt.
FELDER = (
    "vorname", "nachname", "spitzname", "firma", "abteilung", "titel",
    "geburtstag", "webseite", "notiz",
)
#: Die Listen: je Eintrag ein Wörterbuch, siehe ``_LEER_*``.
LISTEN = ("nummern", "adressen", "anschriften")

#: Was eine Nummer, eine Adresse, eine Anschrift sein darf.
ARTEN_NUMMER = ("cell", "home", "work", "main", "fax", "pager", "other", "")
ARTEN_ADRESSE = ("home", "work", "other", "")
ARTEN_ANSCHRIFT = ("home", "work", "other", "")

_LEER_NUMMER = {"nummer": "", "art": "", "beschriftung": "", "bevorzugt": False}
_LEER_ADRESSE = {"adresse": "", "art": "", "beschriftung": "", "bevorzugt": False}
_LEER_ANSCHRIFT = {
    "strasse": "", "plz": "", "ort": "", "region": "", "land": "",
    "postfach": "", "zusatz": "", "art": "", "beschriftung": "", "bevorzugt": False,
}

#: Apples Wörter in ``X-ABLabel`` und was sie hier heissen.
_APPLE_MARKE = re.compile(r"^_\$!<(.+)>!\$_$")
_APPLE_ARTEN = {
    "mobile": "cell", "iphone": "cell", "home": "home", "work": "work", "main": "main",
    "homefax": "fax", "workfax": "fax", "otherfax": "fax", "pager": "pager", "other": "other",
}
_ART_MARKE = {"other": "Other"}
#: Apples übrige Wörter: Sie kommen als Beschriftung an („School") und gehen
#: in Apples Form zurück, damit das Telefon sie weiter als seine eigenen
#: erkennt und übersetzt, statt eine eigene Beschriftung daraus zu machen.
_APPLE_WOERTER = {
    w.lower(): w
    for w in (
        "School", "Anniversary", "Mother", "Father", "Parent", "Brother", "Sister",
        "Child", "Friend", "Spouse", "Partner", "Assistant", "Manager", "HomePage",
    )
}


def leere_nummer() -> dict:
    return dict(_LEER_NUMMER)


def leere_adresse() -> dict:
    return dict(_LEER_ADRESSE)


def leere_anschrift() -> dict:
    return dict(_LEER_ANSCHRIFT)


def nummer_kern(nummer: str) -> str:
    """Was von einer Nummer bleibt, wenn man Schreibweisen abzieht."""
    return re.sub(r"[\s\-/().]", "", nummer)


def _anschrift_kern(a: dict) -> tuple[str, ...]:
    return tuple((a.get(k) or "").strip().lower() for k in ("postfach", "zusatz", "strasse", "ort", "region", "plz", "land"))


def anzeigename(felder: dict) -> str:
    """Wie der Kontakt heisst: Vorname Nachname, sonst das Nächste, was ihn
    benennt. ⚠️ Die Firma vor Adresse und Nummer, wie überall."""
    name = " ".join(t for t in ((felder.get("vorname") or "").strip(), (felder.get("nachname") or "").strip()) if t)
    return name or (felder.get("firma") or "").strip() or (felder.get("adresse") or "").strip() or (felder.get("telefon") or "").strip()


def name_teilen(name: str) -> tuple[str, str]:
    """Vorname und Nachname aus einem Anzeigenamen, am letzten Leerzeichen.
    Ein einzelnes Wort ist ein Vorname. Das ist eine Annahme, und sie steht
    hier, damit sie nicht still altert; die Maske fragt seit dem Felder-Schritt
    beides getrennt ab, und dann wird nicht mehr geteilt."""
    teile = name.split()
    if not teile:
        return "", ""
    if len(teile) == 1:
        return teile[0], ""
    return " ".join(teile[:-1]), teile[-1]


def _bevorzugt(eintraege: list[dict], schluessel: str) -> str:
    """Welche von mehreren das eine Feld bekommt: die mit Stern, sonst die erste."""
    for e in eintraege:
        if e.get("bevorzugt"):
            return e.get(schluessel, "")
    return eintraege[0].get(schluessel, "") if eintraege else ""


def felder_normieren(felder: dict) -> dict:
    """Ein Feldersatz, wie ihn Schreiber und Datenbank brauchen: alle
    Schlüssel da, Listen als Listen, die Einzelfelder aus den Listen
    abgeleitet.

    Verträgt die alten Aufrufer: ein ``name`` ohne Vor- und Nachnamen wird
    geteilt, ein einzelnes ``telefon`` oder ``adresse`` wird zur Liste mit
    genau diesem Eintrag (oder ersetzt darin den bevorzugten), damit nichts
    verloren geht, was über den alten Weg kommt.
    """
    neu: dict = {}
    for f in FELDER:
        neu[f] = (felder.get(f) or "").strip()
    if not (neu["vorname"] or neu["nachname"]) and felder.get("name"):
        neu["vorname"], neu["nachname"] = name_teilen(felder["name"])

    nummern = _liste(felder.get("nummern"), _LEER_NUMMER, "nummer")
    adressen = _liste(felder.get("adressen"), _LEER_ADRESSE, "adresse")
    anschriften = _liste(felder.get("anschriften"), _LEER_ANSCHRIFT, None)
    for a in adressen:
        a["adresse"] = a["adresse"].lower()

    # Die alten Einzelfelder: ohne Liste die ganze Liste, mit Liste ein
    # Ersatz für den bevorzugten Eintrag (so bleibt PATCH {telefon} wirksam).
    if "nummern" not in felder and felder.get("telefon") is not None:
        nummern = _einzel_einmischen(nummern, "nummer", (felder.get("telefon") or "").strip(), nummer_kern)
    if "adressen" not in felder and felder.get("adresse") is not None:
        adressen = _einzel_einmischen(adressen, "adresse", (felder.get("adresse") or "").strip().lower(), str.lower)

    _einen_stern(nummern)
    _einen_stern(adressen)
    _einen_stern(anschriften)

    for a in nummern:
        if a["art"] not in ARTEN_NUMMER:
            a["art"] = ""
    for a in adressen:
        if a["art"] not in ARTEN_ADRESSE:
            a["art"] = ""
    for a in anschriften:
        if a["art"] not in ARTEN_ANSCHRIFT:
            a["art"] = ""

    neu["nummern"] = nummern
    neu["adressen"] = adressen
    neu["anschriften"] = anschriften
    neu["telefon"] = _bevorzugt(nummern, "nummer")
    neu["adresse"] = _bevorzugt(adressen, "adresse")
    neu["name"] = " ".join(t for t in (neu["vorname"], neu["nachname"]) if t)
    return neu


def _liste(roh, vorlage: dict, wert: str | None) -> list[dict]:
    aus: list[dict] = []
    for e in roh or []:
        if not isinstance(e, dict):
            continue
        eintrag = dict(vorlage)
        for k in vorlage:
            if k == "bevorzugt":
                eintrag[k] = bool(e.get(k))
            else:
                eintrag[k] = str(e.get(k) or "").strip()
        if wert is not None and not eintrag[wert]:
            continue
        if wert is None and not any(eintrag[k] for k in ("strasse", "plz", "ort", "land", "postfach", "zusatz", "region")):
            continue
        aus.append(eintrag)
    return aus


def _einzel_einmischen(liste: list[dict], schluessel: str, wert: str, kern) -> list[dict]:
    """Ein einzelnes altes Feld in die Liste bringen: Es ersetzt den Eintrag
    mit Stern (oder den ersten), fehlt es, nimmt es den heraus."""
    if not liste:
        if not wert:
            return []
        vorlage = _LEER_NUMMER if schluessel == "nummer" else _LEER_ADRESSE
        return [{**vorlage, schluessel: wert, "bevorzugt": True}]
    ziel = next((e for e in liste if e.get("bevorzugt")), liste[0])
    if not wert:
        return [e for e in liste if e is not ziel]
    if kern(ziel[schluessel]) != kern(wert):
        ziel[schluessel] = wert
    ziel["bevorzugt"] = True
    return liste


#: Für die Aufrufer, die ein einzelnes altes Feld in eine Liste bringen.
einzel_einmischen = _einzel_einmischen
bevorzugte = _bevorzugt


def _einen_stern(liste: list[dict]) -> None:
    """Genau ein Eintrag trägt den Stern: der erste markierte, sonst der erste."""
    if not liste:
        return
    stern = next((e for e in liste if e.get("bevorzugt")), liste[0])
    for e in liste:
        e["bevorzugt"] = e is stern


# --- Lesen ----------------------------------------------------------------- #


def _zerlegen(zeile: str) -> tuple[str, str, list[str], str] | None:
    """Eine Zeile in Gruppe, Name (gross), Parameter und Wert."""
    if ":" not in zeile:
        return None
    kopf, wert = zeile.split(":", 1)
    teile = kopf.split(";")
    name = teile[0].strip()
    gruppe = ""
    if "." in name:
        gruppe, name = name.rsplit(".", 1)
    return gruppe, name.upper(), [p for p in teile[1:] if p.strip()], wert


def _typen(params: list[str]) -> list[str]:
    typen: list[str] = []
    for p in params:
        schluessel, _, werte = p.partition("=")
        if not werte:
            typen.append(schluessel.strip().lower())  # vCard 2.1: TEL;CELL
        elif schluessel.strip().upper() == "TYPE":
            typen.extend(t.strip().lower() for t in werte.split(","))
    return typen


def _ist_pref(params: list[str]) -> bool:
    if "pref" in _typen(params):
        return True
    return any(p.partition("=")[0].strip().upper() == "PREF" for p in params)


def _art_aus_typen(typen: list[str], fuer: str) -> str:
    if fuer == "TEL":
        for t in typen:
            if t in ("cell", "iphone", "mobile"):
                return "cell"
        for wahl in ("fax", "pager", "main", "work", "home"):
            if wahl in typen:
                return wahl
        return ""
    for wahl in ("work", "home"):
        if wahl in typen:
            return wahl
    return ""


def _beschriftung_lesen(marke: str) -> tuple[str, str]:
    """Aus ``X-ABLabel`` die Art (Apples Wort) oder die eigene Beschriftung."""
    treffer = _APPLE_MARKE.match(marke.strip())
    if treffer:
        wort = treffer.group(1)
        return _APPLE_ARTEN.get(wort.lower(), ""), ("" if wort.lower() in _APPLE_ARTEN else wort)
    return "", entmaskieren(marke).strip()


def _geburtstag_lesen(wert: str, ohne_jahr: str) -> str:
    wert = wert.strip()
    treffer = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?", wert)
    if treffer:
        jahr, monat, tag = treffer.groups()
        if ohne_jahr and jahr == ohne_jahr.strip():
            return f"--{monat}-{tag}"
        return f"{jahr}-{monat}-{tag}"
    if re.fullmatch(r"--\d{2}-?\d{2}", wert):
        return f"--{wert[2:4]}-{wert[-2:]}"
    return wert


def lesen(roh: str) -> dict:
    """Alles, was nexmail von einer Karte kennt, als Feldersatz.

    ⚠️ **Eine Karte, nicht eine Datei.** ``BEGIN`` bis ``END``, so wie
    CardDAV sie je Adresse liefert. Was hier nicht herauskommt (Foto,
    ``X-APPLE-…``), liegt weiter in der Karte und bleibt beim Schreiben
    stehen; ``weiteres`` zählt davon auf, was ein Mensch sehen soll.
    """
    felder: dict = {f: "" for f in FELDER}
    felder.update({"uid": "", "name": "", "nummern": [], "adressen": [], "anschriften": [], "weiteres": []})
    marken: dict[str, str] = {}
    gruppen: dict[str, list[dict]] = {}
    ohne_jahr = ""
    fn = ""
    urls: list[tuple[bool, str]] = []
    for zeile in entfalten(roh):
        z = _zerlegen(zeile)
        if z is None:
            continue
        gruppe, name, params, wert = z
        wert = wert.strip()
        if name in ("BEGIN", "END", "VERSION"):
            continue
        typen = _typen(params)
        pref = _ist_pref(params)
        if name == "X-ABLABEL":
            marken[gruppe] = wert
        elif name == "FN":
            fn = entmaskieren(wert)
        elif name == "N":
            teile = [t.strip() for t in felder_trennen(wert)] + ["", ""]
            felder["nachname"], felder["vorname"] = teile[0], teile[1]
        elif name == "NICKNAME" and not felder["spitzname"]:
            felder["spitzname"] = entmaskieren(wert)
        elif name == "TITLE" and not felder["titel"]:
            felder["titel"] = entmaskieren(wert)
        elif name == "ORG":
            teile = felder_trennen(wert) + [""]
            felder["firma"], felder["abteilung"] = teile[0].strip(), teile[1].strip()
        elif name == "NOTE":
            felder["notiz"] = entmaskieren(wert)
        elif name == "UID" and not felder["uid"]:
            felder["uid"] = wert
        elif name == "BDAY":
            felder["geburtstag"] = wert
        elif name == "X-APPLE-OMIT-YEAR":
            ohne_jahr = wert
        elif name == "URL" and wert:
            urls.append((pref, entmaskieren(wert)))
        elif name == "TEL" and wert:
            e = {**_LEER_NUMMER, "nummer": entmaskieren(wert), "art": _art_aus_typen(typen, "TEL"), "bevorzugt": pref}
            felder["nummern"].append(e)
            gruppen.setdefault(gruppe, []).append(e)
        elif name == "EMAIL" and wert:
            e = {**_LEER_ADRESSE, "adresse": entmaskieren(wert).lower(), "art": _art_aus_typen(typen, "EMAIL"), "bevorzugt": pref}
            felder["adressen"].append(e)
            gruppen.setdefault(gruppe, []).append(e)
        elif name == "ADR":
            teile = [t.strip() for t in felder_trennen(wert)] + [""] * 7
            e = {
                **_LEER_ANSCHRIFT,
                "postfach": teile[0], "zusatz": teile[1], "strasse": teile[2], "ort": teile[3],
                "region": teile[4], "plz": teile[5], "land": teile[6],
                "art": _art_aus_typen(typen, "ADR"), "bevorzugt": pref,
            }
            if any(e[k] for k in ("strasse", "plz", "ort", "land", "postfach", "zusatz", "region")):
                felder["anschriften"].append(e)
                gruppen.setdefault(gruppe, []).append(e)
        elif name in ("X-SOCIALPROFILE", "IMPP", "X-ABDATE", "X-ABRELATEDNAMES"):
            felder["weiteres"].append({"art": name, "gruppe": gruppe, "typen": typen, "text": entmaskieren(wert), "params": params})

    # Beschriftungen an ihre Gruppen: Apples Wort wird zur Art, alles andere
    # steht als eigene Beschriftung; ohne Gruppe (Apple ohne Marke) bleibt die
    # Art aus den Typen.
    for gruppe, eintraege in gruppen.items():
        if not gruppe or gruppe not in marken:
            continue
        art, eigen = _beschriftung_lesen(marken[gruppe])
        for e in eintraege:
            if eigen:
                e["beschriftung"] = eigen
            elif art:
                e["art"] = art
    felder["weiteres"] = _weiteres(felder["weiteres"], marken)

    felder["geburtstag"] = _geburtstag_lesen(felder["geburtstag"], ohne_jahr) if felder["geburtstag"] else ""
    urls.sort(key=lambda u: not u[0])
    felder["webseite"] = urls[0][1] if urls else ""
    # ⚠️ Apple schreibt ``FN:`` leer und den Namen nur in ``N``; ein leeres
    # FN gilt als fehlend (05.09.2026, 149 von 185 Karten ohne Namen).
    felder["name"] = fn or " ".join(t for t in (felder["vorname"], felder["nachname"]) if t)
    if fn and not (felder["vorname"] or felder["nachname"]) and fn.strip() != felder["firma"].strip():
        # Eine Karte mit FN, aber leerem N (etwa aus einem Import): Der Name
        # wird geteilt wie beim Schreiben, damit Leser und Schreiber dasselbe
        # sehen. ⚠️ Nicht bei einem Firmen-Kontakt: Dort ist FN die Firma,
        # und „Polizei Beispielstadt" ist kein Vor- und Nachname.
        felder["vorname"], felder["nachname"] = name_teilen(fn)
    # Der Stern: welchen Eintrag nexmail zeigt. ⚠️ Erst die Sorte, die
    # nexmail lieber hat (die Handynummer), dann die vom Anbieter als ``pref``
    # markierte, sonst die erste. Bei Apple steht vorn gern das Festnetz, und
    # ``pref`` trägt die zuerst eingetragene Nummer. Genau einer je Liste.
    _stern_setzen(felder["nummern"], ("cell",))
    _stern_setzen(felder["adressen"], ())
    _stern_setzen(felder["anschriften"], ())
    felder["telefon"] = _bevorzugt(felder["nummern"], "nummer")
    felder["adresse"] = _bevorzugt(felder["adressen"], "adresse")
    return felder


def _stern_setzen(eintraege: list[dict], lieber: tuple[str, ...]) -> None:
    if not eintraege:
        return
    stern = next(
        (e for e in eintraege if e["art"] in lieber),
        next((e for e in eintraege if e["bevorzugt"]), eintraege[0]),
    )
    for e in eintraege:
        e["bevorzugt"] = e is stern


def _weiteres(roh: list[dict], marken: dict[str, str]) -> list[dict]:
    """Die Zeilen, die nexmail zeigt, aber nicht ändert — lesbar gemacht."""
    aus: list[dict] = []
    for e in roh:
        beschriftung = ""
        if e["gruppe"] in marken:
            art, eigen = _beschriftung_lesen(marken[e["gruppe"]])
            beschriftung = eigen or art
            treffer = _APPLE_MARKE.match(marken[e["gruppe"]].strip())
            if treffer and not eigen:
                beschriftung = treffer.group(1)
        text = e["text"]
        if e["art"] == "X-SOCIALPROFILE":
            dienst = next((p.partition("=")[2] for p in e["params"] if p.partition("=")[0].strip().upper() == "TYPE"), "")
            nutzer = next((p.partition("=")[2] for p in e["params"] if p.partition("=")[0].strip().upper() == "X-USER"), "")
            aus.append({"art": "social", "beschriftung": dienst, "text": nutzer or text})
        elif e["art"] == "IMPP":
            dienst = next((p.partition("=")[2] for p in e["params"] if p.partition("=")[0].strip().upper() == "X-SERVICE-TYPE"), "")
            aus.append({"art": "messenger", "beschriftung": dienst, "text": text.split(":", 1)[-1] if ":" in text else text})
        elif e["art"] == "X-ABDATE":
            aus.append({"art": "datum", "beschriftung": beschriftung, "text": _geburtstag_lesen(text, "")})
        elif e["art"] == "X-ABRELATEDNAMES":
            aus.append({"art": "verwandt", "beschriftung": beschriftung, "text": text})
    return aus


# --- Die Karte zeilenweise ändern ------------------------------------------ #


def _name_von(zeile: str) -> str:
    """Der Eigenschaftsname einer Zeile, ohne Gruppe und Parameter, gross.
    Leer, wenn es keine Eigenschaftszeile ist."""
    z = _zerlegen(zeile)
    return z[1] if z else ""


def _wert_von(zeile: str) -> str:
    return zeile.split(":", 1)[1] if ":" in zeile else ""


def _mit_wert(zeile: str, wert: str) -> str:
    """Dieselbe Zeile mit anderem Wert; Gruppe und Parameter bleiben."""
    return zeile.split(":", 1)[0] + ":" + wert


def _zusammensetzen(gruppe: str, name: str, params: list[str], wert: str) -> str:
    kopf = f"{gruppe}.{name}" if gruppe else name
    return ";".join([kopf, *params]) + ":" + wert


def _jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _params_fuer(name: str, art: str, pref_behalten: bool = False) -> list[str]:
    """Die Parameter einer neuen oder geänderten Zeile, in Apples Schreibweise.

    ⚠️ **Der Stern von nexmail wird nicht zu ``pref``.** Apple setzt ``pref``
    auf die zuerst eingetragene Nummer, meist das Festnetz; nexmails Stern
    sagt, welche Nummer die Liste zeigt, und die ist beim Lesen das Handy.
    Schriebe nexmail seinen Stern als ``pref``, wanderte bei jedem Speichern
    ein Parameter über die Karte, den niemand gesetzt hat. Ein ``pref``, das
    die Zeile schon trug, bleibt ihr.
    """
    if name == "TEL":
        params = {
            "cell": ["type=CELL", "type=VOICE"], "home": ["type=HOME", "type=VOICE"],
            "work": ["type=WORK", "type=VOICE"], "main": ["type=MAIN"], "fax": ["type=FAX"],
            "pager": ["type=PAGER"],
        }.get(art, ["type=VOICE"])
    elif name == "EMAIL":
        params = ["type=INTERNET"] + {"home": ["type=HOME"], "work": ["type=WORK"]}.get(art, [])
    else:
        params = {"home": ["type=HOME"], "work": ["type=WORK"]}.get(art, [])
    if pref_behalten:
        params.append("type=pref")
    return params


def _marke_fuer(eintrag: dict) -> str:
    """Was in ``X-ABLabel`` stehen muss: die eigene Beschriftung, Apples Wort
    für „Sonstige", sonst nichts (die Typen sagen es)."""
    if eintrag.get("beschriftung"):
        wort = eintrag["beschriftung"].strip()
        if wort.lower() in _APPLE_WOERTER:
            return f"_$!<{_APPLE_WOERTER[wort.lower()]}>!$_"
        return maskieren(wort)
    if eintrag.get("art") in _ART_MARKE:
        return f"_$!<{_ART_MARKE[eintrag['art']]}>!$_"
    return ""


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

    def alle(self, name: str) -> list[int]:
        return [i for i, z in enumerate(self.zeilen) if _name_von(z) == name]

    def setze(self, name: str, wert: str, vorlage: str) -> None:
        """Den Wert der ersten Zeile dieses Namens setzen, sonst eine anhängen."""
        i = self.finde(name)
        if i is None:
            self.zeilen.insert(self._ende(), vorlage + wert)
        else:
            self.zeilen[i] = _mit_wert(self.zeilen[i], wert)

    def entferne(self, i: int) -> None:
        del self.zeilen[i]

    def entferne_name(self, name: str) -> None:
        i = self.finde(name)
        if i is not None:
            self.entferne(i)

    def uid_sichern(self, uid: str) -> None:
        if self.finde("UID") is not None:
            return
        # Hinter VERSION, wo jede Karte sie erwartet; sonst gleich hinter BEGIN.
        stelle = self.finde("VERSION")
        stelle = (stelle + 1) if stelle is not None else 1
        self.zeilen.insert(stelle, "UID:" + (uid or f"{uuid.uuid4()}@nexmail"))

    # --- Gruppen ---------------------------------------------------------- #

    def gruppe_von(self, i: int) -> str:
        z = _zerlegen(self.zeilen[i])
        return z[0] if z else ""

    def neue_gruppe(self) -> str:
        hoechste = 0
        for z in self.zeilen:
            t = _zerlegen(z)
            if t and t[0]:
                treffer = re.fullmatch(r"item(\d+)", t[0], re.IGNORECASE)
                if treffer:
                    hoechste = max(hoechste, int(treffer.group(1)))
        return f"item{hoechste + 1}"

    def marke_setzen(self, i: int, marke: str) -> int:
        """Die ``X-ABLabel``-Zeile der Gruppe von Zeile ``i`` setzen oder
        entfernen. Gibt den (womöglich verschobenen) Index der Zeile zurück."""
        gruppe = self.gruppe_von(i)
        if marke and not gruppe:
            gruppe = self.neue_gruppe()
            z = _zerlegen(self.zeilen[i])
            assert z is not None
            self.zeilen[i] = _zusammensetzen(gruppe, z[1], z[2], z[3])
        if not gruppe:
            return i
        vorhanden = next(
            (j for j, z in enumerate(self.zeilen) if _name_von(z) == "X-ABLABEL" and self.gruppe_von(j) == gruppe),
            None,
        )
        if marke:
            if vorhanden is None:
                self.zeilen.insert(i + 1, f"{gruppe}.X-ABLabel:{marke}")
            else:
                self.zeilen[vorhanden] = _mit_wert(self.zeilen[vorhanden], marke)
        elif vorhanden is not None:
            self.entferne(vorhanden)
            if vorhanden < i:
                i -= 1
        return i

    def gruppe_entfernen(self, i: int) -> None:
        """Zeile ``i`` samt allen Zeilen ihrer Gruppe entfernen."""
        gruppe = self.gruppe_von(i)
        if not gruppe:
            self.entferne(i)
            return
        self.zeilen = [z for j, z in enumerate(self.zeilen) if not (j == i or self.gruppe_von(j) == gruppe)]

    # --- Listen ----------------------------------------------------------- #

    def liste_setzen(self, name: str, eintraege: list[dict], wert_von, kern_von, lesen_zeile) -> None:
        """Die Zeilen der Eigenschaft ``name`` an die Liste angleichen.

        Jeder Eintrag sucht sich die Zeile mit seinem Wert: gefunden, bleibt
        sie und bekommt nur bei geänderter Art, Beschriftung oder Stern neue
        Parameter; nicht gefunden, kommt eine neue Zeile hinter die letzte
        dieser Art. Zeilen ohne Eintrag fallen samt ihrer Gruppe.
        """
        vorhanden = self.alle(name)
        benutzt: set[int] = set()
        zuordnung: list[tuple[dict, int | None]] = []
        for e in eintraege:
            kern = kern_von(e)
            treffer = next(
                (i for i in vorhanden if i not in benutzt and kern_von(lesen_zeile(self.zeilen[i])) == kern),
                None,
            )
            if treffer is not None:
                benutzt.add(treffer)
            zuordnung.append((e, treffer))

        # Erst die überzähligen weg (von hinten, damit die Indizes halten),
        # dann die getroffenen angleichen, dann die neuen anhängen.
        for i in sorted((i for i in vorhanden if i not in benutzt), reverse=True):
            self.gruppe_entfernen(i)
            zuordnung = [(e, (t - 1 if t is not None and t > i else t)) for e, t in zuordnung]
            # Eine Gruppe kann mehrere Zeilen vor dem Treffer gekostet haben;
            # sicherer ist, die Treffer neu zu suchen.
        self._angleichen(name, zuordnung, wert_von, kern_von, lesen_zeile)

    def _angleichen(self, name, zuordnung, wert_von, kern_von, lesen_zeile) -> None:
        neue: list[dict] = []
        for e, _ in zuordnung:
            i = next(
                (i for i in self.alle(name) if kern_von(lesen_zeile(self.zeilen[i])) == kern_von(e)),
                None,
            )
            if i is None:
                neue.append(e)
                continue
            alt = lesen_zeile(self.zeilen[i])
            # Der Stern zählt hier nicht mit: Er ist nexmails Sache, nicht die
            # der Karte (siehe ``_params_fuer``).
            if (alt.get("art"), alt.get("beschriftung")) == (e.get("art"), e.get("beschriftung")):
                continue
            z = _zerlegen(self.zeilen[i])
            assert z is not None
            self.zeilen[i] = _zusammensetzen(
                z[0], z[1], _params_fuer(name, e.get("art", ""), _ist_pref(z[2])), z[3]
            )
            self.marke_setzen(i, _marke_fuer(e))
        for e in neue:
            stelle = (self.alle(name) or [self._ende() - 1])[-1] + 1
            zeile = _zusammensetzen("", name, _params_fuer(name, e.get("art", "")), wert_von(e))
            self.zeilen.insert(stelle, zeile)
            self.marke_setzen(stelle, _marke_fuer(e))

    def text(self) -> str:
        raus: list[str] = []
        for zeile in self.zeilen:
            raus.extend(falten(zeile))
        # ⚠️ CRLF ist vorgeschrieben (RFC 6350 3.2). Manche Programme sind
        # nachsichtig, Outlook ist es nicht.
        return "\r\n".join(raus) + "\r\n"


def _zeile_lesen(zeile: str) -> dict:
    """Eine einzelne TEL-, EMAIL- oder ADR-Zeile als Eintrag (ohne Marke)."""
    gelesen = lesen("BEGIN:VCARD\r\n" + zeile + "\r\nEND:VCARD\r\n")
    for liste in LISTEN:
        if gelesen[liste]:
            return gelesen[liste][0]
    return {}


def _liste_lesen_mit_marken(karte: _Karte, name: str):
    """Ein Leser für ``liste_setzen``, der die Beschriftung der Gruppe kennt."""
    marken = {}
    for j, z in enumerate(karte.zeilen):
        if _name_von(z) == "X-ABLABEL":
            marken[karte.gruppe_von(j)] = _wert_von(z)

    def lesen_zeile(zeile: str) -> dict:
        e = _zeile_lesen(zeile)
        if not e:
            return e
        t = _zerlegen(zeile)
        gruppe = t[0] if t else ""
        if gruppe in marken:
            art, eigen = _beschriftung_lesen(marken[gruppe])
            if eigen:
                e["beschriftung"] = eigen
            elif art:
                e["art"] = art
        return e

    return lesen_zeile


def _anschrift_wert(a: dict) -> str:
    return ";".join(maskieren(a.get(k) or "") for k in ("postfach", "zusatz", "strasse", "ort", "region", "plz", "land"))


def aktualisieren(roh: str, felder: dict, uid: str = "", uid_ergaenzen: bool = True) -> str:
    """Die Felder von nexmail in eine bestehende Karte schreiben, den Rest lassen.

    ``felder`` ist ein Feldersatz wie aus ``felder_normieren`` (alte Aufrufer
    dürfen ``name``, ``telefon`` und ``adresse`` einzeln geben, die Normierung
    läuft hier). Ohne ``roh`` entsteht eine neue Karte. ``uid_ergaenzen``
    schaltet die erfundene UID ab — der Export braucht das, siehe dort.
    """
    neu = felder_normieren(felder)
    karte = _Karte(roh)
    alt = lesen(roh) if roh.strip() else lesen("")

    if uid_ergaenzen:
        karte.uid_sichern(uid)

    # FN ist Pflicht und trägt das Nächste, was den Menschen benennt.
    anzeige = anzeigename(neu)
    fn = karte.finde("FN")
    if fn is None or _wert_von(karte.zeilen[fn]).strip() == "" or entmaskieren(_wert_von(karte.zeilen[fn]).strip()) != anzeige:
        karte.setze("FN", maskieren(anzeige), "FN:")
    # N: Vorname und Nachname an ihre Stellen, Apples übrige Teile bleiben.
    if (alt["vorname"], alt["nachname"]) != (neu["vorname"], neu["nachname"]) or karte.finde("N") is None:
        n = karte.finde("N")
        teile = (felder_trennen(_wert_von(karte.zeilen[n])) + ["", "", "", "", ""])[:5] if n is not None else ["", "", "", "", ""]
        teile[0], teile[1] = neu["nachname"], neu["vorname"]
        karte.setze("N", ";".join(maskieren(t.strip()) for t in teile), "N:")

    for name, feld in (("NICKNAME", "spitzname"), ("TITLE", "titel"), ("NOTE", "notiz")):
        if alt[feld] != neu[feld]:
            if neu[feld]:
                karte.setze(name, maskieren(neu[feld]), name + ":")
            else:
                karte.entferne_name(name)

    if (alt["firma"], alt["abteilung"]) != (neu["firma"], neu["abteilung"]):
        # ORG ist Firma;Abteilung;… — die ersten beiden Teile gehören nexmail,
        # was Apple dahinter schreibt, bleibt. Leere Teile am Ende fallen weg.
        i = karte.finde("ORG")
        teile = felder_trennen(_wert_von(karte.zeilen[i])) if i is not None else []
        teile = (teile + ["", ""])[: max(2, len(teile))]
        teile[0], teile[1] = neu["firma"], neu["abteilung"]
        while teile and not teile[-1].strip():
            teile.pop()
        if teile:
            karte.setze("ORG", ";".join(maskieren(t) for t in teile), "ORG:")
        elif i is not None:
            karte.entferne(i)

    if alt["geburtstag"] != neu["geburtstag"]:
        if neu["geburtstag"]:
            karte.setze("BDAY", neu["geburtstag"], "BDAY;value=date:")
        else:
            karte.entferne_name("BDAY")

    if alt["webseite"] != neu["webseite"]:
        urls = karte.alle("URL")
        # Die erste (bevorzugte) URL gehört nexmail; weitere bleiben.
        ziel = next((i for i in urls if _ist_pref(_zerlegen(karte.zeilen[i])[2])), urls[0] if urls else None)
        if neu["webseite"]:
            if ziel is None:
                karte.zeilen.insert(karte._ende(), "URL:" + maskieren(neu["webseite"]))
            else:
                karte.zeilen[ziel] = _mit_wert(karte.zeilen[ziel], maskieren(neu["webseite"]))
        elif ziel is not None:
            karte.gruppe_entfernen(ziel)

    karte.liste_setzen(
        "TEL", neu["nummern"],
        lambda e: maskieren(e["nummer"]), lambda e: nummer_kern(e.get("nummer", "")),
        _liste_lesen_mit_marken(karte, "TEL"),
    )
    karte.liste_setzen(
        "EMAIL", neu["adressen"],
        lambda e: maskieren(e["adresse"]), lambda e: (e.get("adresse") or "").strip().lower(),
        _liste_lesen_mit_marken(karte, "EMAIL"),
    )
    karte.liste_setzen(
        "ADR", neu["anschriften"],
        _anschrift_wert, _anschrift_kern,
        _liste_lesen_mit_marken(karte, "ADR"),
    )

    # Wann zuletzt geändert: Andere Programme lesen es, wir schreiben es mit.
    karte.setze("REV", _jetzt(), "REV:")
    return karte.text()


def neu_bauen(felder: dict, uid: str = "") -> str:
    """Eine frische Karte aus den Feldern."""
    return aktualisieren("", felder, uid)
