"""Jedes Paket aus ``requirements.txt`` steht in THIRD-PARTY.md.

⚠️ Bis 0.22.2 fehlten py-vapid (MPL-2.0), http-ece und dnspython: drei
Pakete, die seit Web Push und BIMI im Abbild liegen. Eine Liste, die beim
Hinzufügen niemand mitzieht, altert lautlos.
"""

from __future__ import annotations

import pathlib
import re

WURZEL = pathlib.Path(__file__).resolve().parent.parent.parent


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pakete() -> list[str]:
    pakete = []
    for zeile in (WURZEL / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        zeile = zeile.split("#", 1)[0].strip()
        if not zeile:
            continue
        name = re.split(r"[\[=<>~!;\s]", zeile, maxsplit=1)[0]
        pakete.append(_norm(name))
    return pakete


def test_jedes_paket_steht_in_der_lizenzliste() -> None:
    pakete = _pakete()
    assert len(pakete) >= 15, "Bodenschwelle: requirements.txt wurde nicht gelesen."
    liste = _norm((WURZEL / "THIRD-PARTY.md").read_text(encoding="utf-8"))
    fehlen = [p for p in pakete if not re.search(rf"(?<![a-z0-9-]){re.escape(p)}(?![a-z0-9-])", liste)]
    assert not fehlen, f"In THIRD-PARTY.md fehlen: {fehlen}"
