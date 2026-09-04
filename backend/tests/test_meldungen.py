"""Der Server benennt, die Oberfläche übersetzt — und ein Wächter hält es fest.

⚠️ **Am 03.09.2026 gezählt: 142 deutsche Sätze in 34 Dateien** gingen als
``detail`` in die Oberfläche und wurden dort wörtlich angezeigt. Auf Englisch
blieben sie deutsch, obwohl nexmails eigene Regel „nach außen ist alles
Englisch" lautet. Der Umbau ist billig; ihn ein zweites Mal zu machen wäre es
nicht.

Drei Zusicherungen, und jede fängt einen anderen Rückfall:

1. **Kein Satz für Menschen im Server.** Wer wieder einen schreibt, wird rot.
2. **Jede Kennung steht im Katalog**, in beiden Sprachen. Eine, die fehlt,
   erscheint dem Benutzer als rohe Kennung — schlimmer als ein hässlicher Satz.
3. **Kein Eintrag im Katalog ohne Kennung im Server.** Sonst wächst er mit
   Leichen, und niemand traut sich mehr, etwas daraus zu entfernen.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
I18N = APP.parent.parent / "frontend" / "src" / "i18n"

KENNUNG = re.compile(r"^[a-z][a-z0-9_]*$")


def _texte(knoten: ast.AST) -> list[str]:
    return [
        k.value
        for k in ast.walk(knoten)
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    ]


def _stellen() -> list[tuple[str, int, str]]:
    """Jede Stelle, an der der Server eine Meldung nach außen gibt.

    ⚠️ **Je Fundstelle, nicht je Zeichenkette.** Ein f-String zerfällt im Baum
    in mehrere Konstanten; wer die einzeln zählt, meldet 196 statt 142 und
    verliert das Vertrauen in die Zahl.
    """
    raus: list[tuple[str, int, str]] = []
    for datei in sorted(APP.rglob("*.py")):
        if "__pycache__" in datei.parts:
            continue
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        rel = datei.relative_to(APP.parent).as_posix()

        for k in ast.walk(baum):
            gefunden: list[list[str]] = []

            if isinstance(k, ast.Call):
                for kw in k.keywords:
                    if kw.arg == "detail":
                        gefunden.append(_texte(kw.value))
                name = getattr(k.func, "id", None) or getattr(k.func, "attr", None) or ""
                if name == "MeldungHttp" and len(k.args) >= 2:
                    gefunden.append(_texte(k.args[1]))

            if isinstance(k, ast.Raise) and isinstance(k.exc, ast.Call):
                name = getattr(k.exc.func, "id", None) or getattr(k.exc.func, "attr", None) or ""
                # ⚠️ **OidcFehler ist ausgenommen, und zwar begründet.** Er trägt
                # Kennung *und* Satz; nur die Kennung geht in die Oberfläche
                # (``?oidc_fehler=…``), den Satz sieht ausschließlich das
                # Protokoll. Dort gilt „englisch", nicht „übersetzt".
                if name.endswith("Fehler") and name != "OidcFehler" and k.exc.args:
                    gefunden.append(_texte(k.exc.args[0]))

            for teile in gefunden:
                ganz = " ".join(t for t in teile if t).strip()
                if ganz:
                    raus.append((rel, k.lineno, ganz))
    return raus


def test_kein_satz_fuer_menschen_im_server():
    """⚠️ **Der eigentliche Wächter.** Was hier steht, steht in der Oberfläche.

    Erkannt wird an der **Form**, nicht am Wortschatz: Eine Kennung ist
    snake_case ohne Leerzeichen. Damit fällt auch ein englischer Satz auf —
    richtig so, denn übersetzen kann die Oberfläche nur, was sie benennen
    kann. „Sorry, something went wrong" bleibt auf Deutsch englisch.
    """
    quellen = {
        datei: (APP.parent / datei).read_text(encoding="utf-8").split("\n")
        for datei, _, _ in _stellen()
    }
    saetze = [
        f"{datei}:{zeile}  {text[:70]}"
        for datei, zeile, text in _stellen()
        if not KENNUNG.match(text)
        # ⚠️ **Eine Ausnahme, und sie muss an ihrer Stelle stehen.** Eine Liste
        # von Dateinamen hier oben altert lautlos; ein Vermerk am Aufruf steht
        # neben der Begründung und fällt beim Lesen auf. Heute betrifft das
        # genau eine Stelle: den Startabbruch bei falschem NEXMAIL_SECRET_KEY,
        # der nie eine Oberfläche erreicht.
        and "NXM001" not in quellen[datei][zeile - 1]
    ]
    assert not saetze, (
        "Diese Stellen geben einen fertigen Satz heraus statt einer Kennung:\n  "
        + "\n  ".join(saetze)
        + "\n\nDer Server benennt, die Oberflaeche uebersetzt: Kennung hier, Text "
        "in frontend/src/i18n/*.json unter 'serverfehler'."
    )


def _katalog(sprache: str) -> dict[str, str]:
    daten = json.loads((I18N / f"{sprache}.json").read_text(encoding="utf-8"))
    return daten.get("serverfehler", {})


def test_jede_kennung_steht_im_katalog():
    """Eine Kennung ohne Eintrag erscheint dem Benutzer roh.

    ⚠️ **In beiden Sprachen.** Nur eine zu pflegen heisst: In der anderen steht
    ``ordner_name_fehlt`` auf dem Bildschirm.
    """
    genannt = {text for _, _, text in _stellen() if KENNUNG.match(text)}
    de, en = _katalog("de"), _katalog("en")

    fehlt_de = sorted(genannt - set(de))
    fehlt_en = sorted(genannt - set(en))
    assert not fehlt_de, f"Ohne deutschen Text: {fehlt_de}"
    assert not fehlt_en, f"Ohne englischen Text: {fehlt_en}"


def test_der_katalog_traegt_keine_leichen():
    """Was niemand mehr nennt, gehört heraus.

    ⚠️ **Sonst traut sich niemand mehr, etwas zu löschen.** Ein Katalog, in dem
    die Hälfte tot ist, wird nur noch ergänzt.
    """
    genannt = {text for _, _, text in _stellen() if KENNUNG.match(text)}
    uebrig = sorted(set(_katalog("de")) - genannt)
    assert not uebrig, f"Im Katalog, aber im Server nirgends genannt: {uebrig}"


def test_beide_sprachen_kennen_dieselben_kennungen():
    de, en = set(_katalog("de")), set(_katalog("en"))
    assert de == en, f"Nur in einer Sprache: {sorted(de ^ en)}"


def test_werte_im_text_haben_einen_platzhalter():
    """Ein Wert ohne Platzhalter im Satz geht verloren.

    ⚠️ **Der teuerste stille Fehler dieses Umbaus.** ``ordner_name_zu_lang``
    mit ``max=40`` und dem Text „Der Name ist zu lang" verliert die 40 — der
    Benutzer erfährt nicht mehr, ab wann. Vorher stand sie im Satz und konnte
    gar nicht verlorengehen.
    """
    mit_werten: dict[str, set[str]] = {}
    for datei in sorted(APP.rglob("*.py")):
        if "__pycache__" in datei.parts:
            continue
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for k in ast.walk(baum):
            if isinstance(k, ast.Raise) and isinstance(k.exc, ast.Call):
                name = getattr(k.exc.func, "id", None) or ""
                if not name.endswith("Fehler") or name == "OidcFehler" or not k.exc.args:
                    continue
                erst = k.exc.args[0]
                if not (isinstance(erst, ast.Constant) and isinstance(erst.value, str)):
                    continue
                schl = {kw.arg for kw in k.exc.keywords if kw.arg}
                if schl:
                    mit_werten.setdefault(erst.value, set()).update(schl)
            if isinstance(k, ast.Call) and getattr(k.func, "id", "") == "MeldungHttp":
                if len(k.args) >= 3 and isinstance(k.args[1], ast.Constant):
                    if isinstance(k.args[2], ast.Dict):
                        schl = {
                            s.value
                            for s in k.args[2].keys
                            if isinstance(s, ast.Constant) and isinstance(s.value, str)
                        }
                        if schl:
                            mit_werten.setdefault(k.args[1].value, set()).update(schl)

    de = _katalog("de")
    verloren = []
    for kennung, schluessel in sorted(mit_werten.items()):
        text = de.get(kennung, "")
        for s in sorted(schluessel):
            if f"{{{{{s}}}}}" not in text:
                verloren.append(f"{kennung}: Wert {s!r} kommt im Text nicht vor")
    assert not verloren, "\n  " + "\n  ".join(verloren)
