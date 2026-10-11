"""Jede Umgebungsvariable, die irgendwo genannt wird, gibt es auch.

⚠️ Bis 0.22.2 nannten das Hinweisfenster beim Einschalten des zweiten Faktors,
die Protokollzeile beim Start und ein Docstring den Notausgang
``NEXMAIL_2FA_AUS``. Die Variable heißt ``NEXMAIL_ZWEI_FAKTOR_AUS``. Wer
ausgesperrt war und der Meldung folgte, blieb ausgesperrt. Ebenso nannte die
Protokollzeile des Takts ``NEXMAIL_TAKT`` statt ``NEXMAIL_TAKT_SEKUNDEN``.
"""

from __future__ import annotations

import pathlib
import re

from app.config import Settings

WURZEL = pathlib.Path(__file__).resolve().parent.parent.parent
NAME = re.compile(r"\bNEXMAIL_([A-Z0-9_]+)\b")

# Keine Einstellungen des Servers: der Vite-Dev-Server liest NEXMAIL_API.
NICHT_DER_SERVER = {"API"}


def _quellen() -> list[pathlib.Path]:
    dateien = [WURZEL / "README.md", WURZEL / "docker-compose.yml"]
    dateien += sorted((WURZEL / "frontend" / "src" / "i18n").glob("*.json"))
    dateien += sorted((WURZEL / "backend" / "app").rglob("*.py"))
    return [d for d in dateien if "vendor" not in d.parts]


def test_every_named_variable_is_a_setting() -> None:
    felder = {f.upper() for f in Settings.model_fields}
    fremd = []
    for datei in _quellen():
        for zeile_nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            for name in NAME.findall(zeile):
                if name in felder or name in NICHT_DER_SERVER:
                    continue
                fremd.append(f"{datei.relative_to(WURZEL)}:{zeile_nr}: NEXMAIL_{name}")
    assert not fremd, "Variablen, die es nicht gibt:\n" + "\n".join(fremd)


def test_the_check_reads_the_message_of_the_emergency_exit() -> None:
    """Bodenschwelle: Der Wächter muss die Sprachdateien wirklich lesen."""
    texte = "".join(
        d.read_text(encoding="utf-8") for d in _quellen() if d.suffix == ".json"
    )
    assert "NEXMAIL_ZWEI_FAKTOR_AUS" in texte
