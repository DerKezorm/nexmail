"""Der Waechter vor dem Veroeffentlichen: nichts Persoenliches, nichts Geheimes.

Geprueft wird, was Git wirklich kennt (``git ls-files``), nicht das
Arbeitsverzeichnis: ``.gitignore`` greift bei bereits verfolgten Dateien
**nicht**.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent.parent


def _verfolgte_dateien() -> list[Path]:
    """Alles, was bei einem ``git add -A`` mit hinausginge.

    ⚠️ **``--others`` ist der wichtigste Schalter hier.** Ohne ihn zeigt
    ``git ls-files`` nur **schon verfolgte** Dateien; eine **neue** Datei
    bliebe ungeprueft, bis ``git add -A`` sie mitnimmt. Ob man vor oder nach
    ``git add`` prueft, darf kein Unterschied sein; mit
    ``--others --exclude-standard`` ist es keiner.

    ``--exclude-standard`` haelt dabei ``.gitignore`` in Kraft: Was ohnehin
    ignoriert wird, geht auch nicht hinaus und gehoert nicht in die Pruefung.
    """
    ergebnis = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=WURZEL,
        capture_output=True,
        text=True,
        check=False,
    )
    if ergebnis.returncode != 0:
        pytest.skip("Kein Git-Verzeichnis - hier gibt es nichts zu pruefen.")
    # ⚠️ Eine Datei kann in beiden Listen stehen (veraendert und verfolgt).
    # Doppelte Treffer sind nur Laerm im Fehlerbericht.
    return [WURZEL / z for z in dict.fromkeys(ergebnis.stdout.splitlines()) if z.strip()]


def _lesbar(datei: Path) -> str:
    if not datei.is_file():
        return ""
    if datei.suffix.lower() in {".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".gz", ".zip"}:
        return ""
    try:
        return datei.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


#: ⚠️ **Die verbotenen Woerter stehen NICHT hier.**
#:
#: Ein Waechter, der die Namen mitliefert, die er verbieten soll, ist in einem
#: oeffentlichen Repo selbst die Leckstelle.
#:
#: Sie stehen in ``.veroeffentlichung-tabu`` neben dieser Datei; die Datei
#: bleibt lokal und wird nicht verfolgt. Fehlt sie, ueberspringt sich der Test
#: **mit Hinweis** — er schweigt nicht.
TABU_DATEI = WURZEL / ".veroeffentlichung-tabu"

#: Was sich ohne Namensliste pruefen laesst: Formen, keine Woerter.
FORMEN = {
    "ein Rechner aus dem Heimnetz": re.compile(r"\b(10\.10\.10|192\.168)\.\d{1,3}\.\d{1,3}\b"),
    "ein Pfad vom Rechner des Betreibers": re.compile(r"[Cc]:[\\/]Users[\\/]", re.IGNORECASE),
    "ein OneDrive-Pfad": re.compile(r"OneDrive[\\/]", re.IGNORECASE),
}

#: ⚠️ **Nur was nachweislich harmlos ist.** Jede Ausnahme mit Grund — eine
#: Ausnahmeliste ohne Begruendung waechst, bis der Waechter nichts mehr sagt.
AUSNAHMEN = {
    # Die Anbieter-Tabellen nennen oeffentliche Maildienste (icloud.com, gmx.de).
    # Das sind keine persoenlichen Angaben, sondern der Zweck der Datei.
    "backend/app/services/anbieter.py",
    "frontend/src/lib/anbieter.ts",
}


def _tabu_woerter() -> list[str]:
    if not TABU_DATEI.is_file():
        return []
    return [
        z.strip().lower()
        for z in TABU_DATEI.read_text(encoding="utf-8").splitlines()
        if z.strip() and not z.startswith("#")
    ]


def test_nichts_persoenliches_im_repo():
    """⚠️ **Der Waechter, den es vor jedem Push braucht.**

    Er liest jede Datei, die Git kennt, und schlaegt an, sobald ein Rechnername
    aus dem Heimnetz, ein Pfad vom Rechner des Betreibers oder eines der Woerter
    aus ``.veroeffentlichung-tabu`` darin steht.
    """
    woerter = _tabu_woerter()
    if not woerter:
        pytest.skip(
            "Keine .veroeffentlichung-tabu neben dem Projekt - die Namenspruefung "
            "kann nicht laufen. Fuer eine Veroeffentlichung anlegen."
        )

    treffer: list[str] = []
    for datei in _verfolgte_dateien():
        rel = datei.relative_to(WURZEL).as_posix()
        if rel in AUSNAHMEN or rel == ".veroeffentlichung-tabu":
            continue
        inhalt = _lesbar(datei)
        if not inhalt:
            continue
        klein = inhalt.lower()
        for wort in woerter:
            if wort in klein:
                # ⚠️ Das gefundene Wort steht **nicht** in der Meldung — sonst
                # landet es im Testprotokoll, und das wandert in Fehlerberichte.
                treffer.append(f"{rel}: ein Wort aus der Tabu-Liste (Stelle {klein.index(wort)})")
                break
        for was, muster in FORMEN.items():
            if muster.search(inhalt):
                treffer.append(f"{rel}: {was}")

    assert treffer == [], "Im Repo steht Persönliches:\n  " + "\n  ".join(treffer)


def test_keine_betriebsdaten_im_repo():
    """⚠️ **``secret.key`` oeffnet jedes hinterlegte Postfach.**

    Datenbank, Schluessel, Anhaenge und Protokolle gehoeren nie ins Repo — auch
    nicht „nur zum Ansehen".
    """
    verboten = re.compile(
        r"(^|/)(data|data-dev\d*)/|secret\.key$|\.db(-wal|-shm)?$|(^|/)blobs/|(^|/)logs/"
    )
    treffer = [
        d.relative_to(WURZEL).as_posix()
        for d in _verfolgte_dateien()
        if verboten.search(d.relative_to(WURZEL).as_posix())
    ]
    assert treffer == [], f"Betriebsdaten im Repo: {treffer}"


def test_lokale_dateien_bleiben_lokal():
    """⚠️ Die Pruefstaende und die Tabu-Liste gehoeren nicht ins Repo.

    ``.gitignore`` allein haelt eine schon verfolgte Datei nicht auf; deshalb
    wird hier geprueft, was Git tatsaechlich kennt.
    """
    verfolgt = {d.relative_to(WURZEL).as_posix() for d in _verfolgte_dateien()}
    assert not any(p.startswith("pruefstand/") for p in verfolgt)
    assert ".veroeffentlichung-tabu" not in verfolgt


def test_keine_geheimnisse_im_repo():
    """Zugangsdaten, die versehentlich stehengeblieben sind."""
    muster = {
        "ein privater Schluessel": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "ein GitHub-Token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
        "ein AWS-Schluessel": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    }
    treffer: list[str] = []
    for datei in _verfolgte_dateien():
        inhalt = _lesbar(datei)
        for was, m in muster.items():
            if m.search(inhalt):
                treffer.append(f"{datei.relative_to(WURZEL).as_posix()}: {was}")
    assert treffer == [], "Geheimnisse im Repo:\n  " + "\n  ".join(treffer)
