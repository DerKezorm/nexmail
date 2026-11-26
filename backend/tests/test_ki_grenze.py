"""Neuere OpenAI-Modelle wollen die Grenze als ``max_completion_tokens``.

gpt-5 und gpt-6 weisen ``max_tokens`` mit 400 ab und nennen den neuen Namen,
danach jede Temperatur außer 1 (gemessen vom Melder in nexdiary Issue #3).
nexmail schickt die Grenze dann unter dem neuen Namen, mit Platz für die
Gedanken des Modells und ``reasoning_effort: "low"``; ältere Modelle bekommen
weiter ``max_tokens`` in einer einzigen Anfrage.

⚠️ **Nichts geht ins echte Netz.** Der Dienst ist ein Doppelgänger, der so
antwortet wie OpenAI, und die Namensauflösung kommt aus der Tabelle in
``test_ki_nachdenken``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import kidienst as dienst
from test_ki_nachdenken import (  # noqa: F401  (Fixtures)
    DRAUSSEN,
    LOKAL,
    _bearbeiten,
    _bereit,
    _fassen,
    bremse_frei,
    namen,
    person,
)
from test_kidienst import TextDoppelgaenger

#: Modul ki 0.1.0: eine Installation von vorher („Jedes Konto selbst“, Rechner auf der Liste, DNS der Tests).
pytestmark = pytest.mark.usefixtures("ki_wie_vorher")

#: Die Sätze, wie OpenAI sie schreibt.
GRENZE = (
    "Unsupported parameter: 'max_tokens' is not supported with this model. "
    "Use 'max_completion_tokens' instead."
)
TEMPERATUR = (
    "Unsupported value: 'temperature' does not support 0.2 with this model. "
    "Only the default (1) value is supported."
)
NIEDRIG = "Unsupported value: 'reasoning_effort' does not support 'low' with this model."


class NeuesModell(TextDoppelgaenger):
    """Antwortet wie gpt-5 bei OpenAI: ``max_tokens`` und eine Temperatur
    außer 1 gehen nicht, ``"low"`` je nach Modell nicht."""

    def __init__(self, low_geht: bool = True, nachdenken_geht: bool = True, **kw):
        super().__init__(**kw)
        self.low_geht = low_geht
        self.nachdenken_geht = nachdenken_geht

    def transport(self):
        weiter = super().transport()

        def antworten(anfrage: httpx.Request) -> httpx.Response:
            rumpf = json.loads(anfrage.content or b"{}")

            def absage(satz: str) -> httpx.Response:
                self.anfragen.append((str(anfrage.url), {}, rumpf))
                return httpx.Response(400, json={"error": {"message": satz}})

            if not self.nachdenken_geht and "reasoning_effort" in rumpf:
                return absage("Unrecognized request argument supplied: reasoning_effort")
            if "max_tokens" in rumpf:
                return absage(GRENZE)
            if rumpf.get("temperature", 1) != 1:
                return absage(TEMPERATUR)
            if not self.low_geht and rumpf.get("reasoning_effort") == "low":
                return absage(NIEDRIG)
            return weiter.handle_request(anfrage)

        return httpx.MockTransport(antworten)


def _ruempfe(server) -> list[dict]:
    return [rumpf for _, _, rumpf in server.anfragen]


def test_neues_modell_bekommt_die_grenze_unter_neuem_namen(db, person):
    _bereit(db, person, DRAUSSEN)
    server = NeuesModell(inhalt="<p>Korrigiert.</p>")
    assert _bearbeiten(db, person, server.transport()) == "<p>Korrigiert.</p>"
    erste, zweite, dritte = _ruempfe(server)
    assert erste["max_tokens"] == dienst.MAX_TOKEN and "max_completion_tokens" not in erste
    # Zweite: neuer Name, Platz für die Gedanken, kurz fassen; Temperatur noch da.
    assert "max_tokens" not in zweite
    assert zweite["max_completion_tokens"] == dienst.MAX_TOKEN + dienst.NACHDENKEN_ZUSCHLAG
    assert zweite["reasoning_effort"] == "low"
    assert zweite["temperature"] == 0.2
    # Dritte: die Temperatur fällt, wie bisher.
    assert "temperature" not in dritte
    assert {k: v for k, v in zweite.items() if k != "temperature"} == dritte
    # In „Was hinausging" stehen seit dem Modul ki Anweisungen und Text (K5), nicht die Felder der Anfrage.
    gemerkt = dienst.vorgaenge_lesen(db, person)[0]["rumpf"]
    assert gemerkt["messages"] == dritte["messages"]


def test_auch_beim_zusammenfassen(db, person):
    """⚠️ **Der zweite Weg** (eingegangene Post) baut seinen Rumpf selbst und
    hat die knappste Grenze: 1.000 plus der Zuschlag."""
    _bereit(db, person, DRAUSSEN)
    server = NeuesModell(inhalt="Eine Rechnung ist offen.")
    assert _fassen(db, person, server.transport()) == ("Eine Rechnung ist offen.", False)
    letzte = _ruempfe(server)[-1]
    assert letzte["max_completion_tokens"] == (
        dienst.MAX_TOKEN_ZUSAMMENFASSUNG + dienst.NACHDENKEN_ZUSCHLAG
    )
    assert letzte["reasoning_effort"] == "low"
    assert "max_tokens" not in letzte and "temperature" not in letzte
    assert len(server.anfragen) == 3


def test_ein_aelteres_modell_bleibt_bei_einer_anfrage(db, person):
    _bereit(db, person, DRAUSSEN)
    server = TextDoppelgaenger()
    _bearbeiten(db, person, server.transport())
    _fassen(db, person, server.transport())
    assert len(server.anfragen) == 2
    for rumpf in _ruempfe(server):
        assert "max_tokens" in rumpf
        assert "max_completion_tokens" not in rumpf and "reasoning_effort" not in rumpf


def test_wer_low_ablehnt_wird_einmal_ohne_gefragt(db, person):
    _bereit(db, person, DRAUSSEN)
    server = NeuesModell(low_geht=False, inhalt="<p>Gut.</p>")
    assert _bearbeiten(db, person, server.transport()) == "<p>Gut.</p>"
    ruempfe = _ruempfe(server)
    assert len(ruempfe) == 4
    assert ruempfe[-2]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in ruempfe[-1]
    assert ruempfe[-1]["max_completion_tokens"] == dienst.MAX_TOKEN + dienst.NACHDENKEN_ZUSCHLAG


def test_im_eigenen_netz_bleibt_none(db, person):
    """Ein Dienst im eigenen Netz, der den neuen Namen verlangt, soll weiter
    nicht nachdenken: ``"none"`` bleibt, aus ihm wird kein ``"low"``."""
    _bereit(db, person, LOKAL)
    server = NeuesModell()
    _bearbeiten(db, person, server.transport())
    ruempfe = _ruempfe(server)
    assert all(r["reasoning_effort"] == "none" for r in ruempfe)
    assert ruempfe[-1]["max_completion_tokens"] == dienst.MAX_TOKEN + dienst.NACHDENKEN_ZUSCHLAG


def test_ein_abgelehntes_nachdenken_kommt_nicht_wieder(db, person):
    """Hat der Dienst ``reasoning_effort`` schon abgelehnt, bringt der neue
    Name es nicht als ``"low"`` zurück: jedes Feld höchstens einmal."""
    _bereit(db, person, LOKAL)
    server = NeuesModell(nachdenken_geht=False)
    _bearbeiten(db, person, server.transport())
    ruempfe = _ruempfe(server)
    assert len(ruempfe) == 4  # ohne Nachdenken, neuer Name, ohne Temperatur, Antwort
    assert all("reasoning_effort" not in r for r in ruempfe[1:])
    assert "max_completion_tokens" in ruempfe[-1]


@pytest.mark.parametrize(
    "satz",
    [
        "max_tokens is too large: 9000. This model supports at most 4096 completion tokens.",
        "Invalid 'max_tokens': integer below minimum value.",
    ],
)
def test_eine_400_ueber_max_tokens_allein_benennt_nicht_um(db, person, satz):
    """Wer nur sagt, die Grenze sei zu hoch, will keinen anderen Namen."""
    _bereit(db, person, DRAUSSEN)
    server = TextDoppelgaenger(code=400, roh={"error": {"message": satz}})
    with pytest.raises(dienst.KiFehler) as f:
        _bearbeiten(db, person, server.transport())
    assert len(server.anfragen) == 1
    assert f.value.kennung == "ki_dienst_sagt"


def test_umbenannt_wird_hoechstens_einmal(db, person):
    """Ein Dienst, der den neuen Namen auch danach noch verlangt, bekommt
    keine dritte Anfrage."""
    _bereit(db, person, DRAUSSEN)
    anfragen = []

    def stur(anfrage):
        anfragen.append(json.loads(anfrage.content))
        return httpx.Response(400, json={"error": {"message": GRENZE}})

    with pytest.raises(dienst.KiFehler) as f:
        _bearbeiten(db, person, httpx.MockTransport(stur))
    assert len(anfragen) == 2
    assert "max_completion_tokens" in anfragen[1]
    assert f.value.kennung == "ki_dienst_sagt"


def test_aufgebraucht_nach_dem_umbenennen(db, person):
    """Hat das Modell den ganzen Platz verdacht, sagt nexmail das, auch unter
    dem neuen Namen (``finish_reason`` bleibt ``length``)."""
    _bereit(db, person, DRAUSSEN)
    server = NeuesModell(
        roh={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    )
    with pytest.raises(dienst.KiFehler) as f:
        _bearbeiten(db, person, server.transport())
    assert f.value.kennung == "ki_antwort_aufgebraucht"
    assert "max_completion_tokens" in _ruempfe(server)[-1]
