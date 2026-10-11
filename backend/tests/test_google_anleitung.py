"""Die Anleitung für die Google-App nennt jeden Bereich, den nexmail anfragt.

⚠️ Bis 0.22.2 nannte sie drei; angefragt wurden seit 0.10.0 vier
(``auth/carddav`` für die Kontakte). Wer der Anleitung folgte, trug den
vierten nicht ein, und Google zeigt beim Zustimmen dann nur, was eingetragen
ist.
"""

from __future__ import annotations

import json
import pathlib
from urllib.parse import urlsplit

from app.services.mailoauth import ARTEN

I18N = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "i18n"


def _kurz(bereich: str) -> str:
    """``https://www.googleapis.com/auth/calendar`` steht dort als ``.../auth/calendar``."""
    teile = urlsplit(bereich)
    return f"...{teile.path}" if teile.path not in ("", "/") else bereich


def test_die_anleitung_nennt_jeden_bereich_in_beiden_sprachen() -> None:
    bereiche = ARTEN["google"].bereiche
    assert len(bereiche) >= 4, "Bodenschwelle: die Liste wurde nicht gelesen."
    for sprache in ("de", "en"):
        text = json.loads((I18N / f"{sprache}.json").read_text(encoding="utf-8"))["oauth"]["g4_text"]
        fehlen = [b for b in bereiche if b not in text and _kurz(b) not in text]
        assert not fehlen, f"{sprache}: die Anleitung nennt {fehlen} nicht."
