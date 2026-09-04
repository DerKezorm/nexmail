"""Meldungen für Menschen — benannt, nicht ausformuliert.

⚠️ **Der Server benennt, die Oberfläche übersetzt.** Ein deutscher Satz aus dem
Server bleibt auf Englisch deutsch, und nexmails Regel lautet „nach außen ist
alles Englisch". Am 03.09.2026 gezählt: **142 deutsche Sätze in 34 Dateien**
gingen als ``detail`` in die Oberfläche und wurden dort wörtlich angezeigt.

Der Weg dorthin stand schon an drei Stellen richtig — OIDC, der Bildvermittler
und die Schlagworte melden längst Kennungen (``kalender_nur_lesen``,
``schlagworte_nicht_unterstuetzt``). Was fehlte, war eine gemeinsame Grundlage.

Zwei Dinge macht diese Datei:

* ``Meldung`` trägt eine **Kennung** und die **Werte** darin. Ihr ``str()`` ist
  die Kennung — damit läuft ``detail=str(fehler)`` in den Routern unverändert
  weiter, und die 118 Meldungen ohne Werte brauchten dort keine Änderung.
* ``MeldungHttp`` bringt die Werte mit hinaus. FastAPIs ``HTTPException``
  rendert nur ``{"detail": …}``; die 39 Meldungen mit Werten („Der Name ist
  länger als **40** Zeichen") brauchen ein zweites Feld.

⚠️ **Die Kennung ist ein Vertrag mit der Oberfläche.** Wer eine umbenennt,
ändert einen Schlüssel in ``de.json`` und ``en.json`` mit — sonst zeigt die
Oberfläche die rohe Kennung an. ``test_meldungen.py`` hält beide Richtungen
fest.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class Meldung(Exception):
    """Etwas, das ein Mensch lesen soll — als Kennung, nicht als Satz.

    ⚠️ **``str(self)`` ist die Kennung.** Daran hängt, dass die Router
    unverändert weiterlaufen: ``detail=str(fehler)`` liefert danach
    ``name_fehlt`` statt „Der Ordner braucht einen Namen."

    ⚠️ **Werte gehören in ``werte``, nicht in den Text.** „Der Name ist länger
    als 40 Zeichen" wird zu ``name_zu_lang`` mit ``{"max": 40}``; die
    Oberfläche setzt die Zahl in ihren eigenen Satz ein. Wer die Zahl in die
    Kennung schreibt (``name_zu_lang_40``), bekommt für jede Grenze einen
    eigenen Übersetzungsschlüssel.
    """

    #: Welchen HTTP-Status diese Sorte Meldung bedeutet, wenn niemand etwas
    #: anderes sagt. Die Router setzen ihn heute selbst; das hier ist die
    #: Vorgabe für den Weg über ``MeldungHttp.aus``.
    status = 400

    def __init__(self, kennung: str, /, **werte: Any) -> None:
        self.kennung = kennung
        self.werte = werte
        super().__init__(kennung)


class MeldungHttp(HTTPException):
    """Eine ``HTTPException``, die ihre Werte mitnimmt.

    ⚠️ **``detail`` bleibt eine Zeichenkette.** 73 Stellen in der Oberfläche
    lesen sie so; ein Objekt daraus zu machen hieße, alle 73 auf einmal
    umzubauen. Die Werte reisen deshalb in einem eigenen Feld daneben.
    """

    def __init__(self, status_code: int, kennung: str, werte: dict[str, Any] | None = None):
        super().__init__(status_code=status_code, detail=kennung)
        self.werte = werte or {}

    @classmethod
    def aus(cls, fehler: Meldung, status_code: int | None = None) -> "MeldungHttp":
        """Aus einer Dienst-Meldung eine Antwort machen."""
        return cls(status_code or fehler.status, fehler.kennung, fehler.werte)


async def als_antwort(_request, fehler: HTTPException) -> JSONResponse:
    """Der Handler: hängt ``werte`` an, wenn welche da sind.

    ⚠️ **Er ersetzt FastAPIs eigenen Handler für ``HTTPException``.** Ohne das
    fiele ``werte`` weg, denn Starlette rendert nur ``detail``. Kopfzeilen
    reicht er weiter — daran hängt unter anderem ``Retry-After`` bei der
    Anmeldebremse, und das leise zu verlieren wäre teuer.
    """
    inhalt: dict[str, Any] = {"detail": fehler.detail}
    werte = getattr(fehler, "werte", None)
    if werte:
        inhalt["werte"] = werte
    return JSONResponse(
        status_code=fehler.status_code,
        content=inhalt,
        headers=getattr(fehler, "headers", None),
    )
