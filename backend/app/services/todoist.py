"""Todoist — die Schnittstelle, sonst nichts.

Was eine Verbindung ist, wem sie gehoert und wann abgeglichen wird, steht in
``aufgabenziele.py``. Hier steht nur, wie man mit Todoist spricht.

⚠️ **Nur die vereinheitlichte API v1** (``/api/v1``). REST v2 und Sync v9 sind
abgeschaltet und antworten mit 410; wer eine Anleitung von vor 2025 abschreibt,
landet dort. Felder und Pfade sind gegen Todoists eigenes Python-SDK gelesen
(``todoist-api-python``, Stand 27.10.2026), weil die Dokumentationsseite zu
lang zum Ausliefern ist.

⚠️ **Der persoenliche Token, kein OAuth.** Er steht in Todoist unter
Einstellungen → Integrationen → Entwickler. OAuth hiesse: Der Betreiber
registriert eine App bei Todoist, und nexmail braeuchte eine aus dem Netz
erreichbare Rueckkehr-Adresse — beides fuer einen Vorteil, den hier niemand
braucht.

⚠️ **Kein Rumpf einer Todoist-Antwort geht ins Protokoll**, nur Status und
Art des Fehlers. Darin koennen Aufgabentexte stehen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx

from ..meldung import Meldung

logger = logging.getLogger("nexmail.todoist")

BASIS = "https://api.todoist.com/api/v1"
#: Wohin der Link zu einer Aufgabe fuehrt. Todoist leitet die blosse Kennung
#: selbst auf die Adresse mit Titel weiter.
AUFGABE_URL = "https://app.todoist.com/app/task/"

#: ⚠️ **Kurz, anders als Todoists SDK (60 s).** Hier wartet ein Mensch vor
#: einem Fenster; was in 20 Sekunden nicht kommt, kommt in der Regel gar nicht.
ZEITGRENZE = 20.0

#: Wie viele Eintraege eine Seite traegt (Todoists Hoechstwert).
SEITE = 200
#: ⚠️ **Ein Deckel fuer die Seiten.** Ein Cursor, der nie leer wird, liesse
#: die Schleife sonst ewig laufen; 20 Seiten sind 4000 Projekte.
MAX_SEITEN = 20
#: Wie viele Kennungen eine Abfrage ``?ids=`` traegt. Die Adresse soll kurz
#: bleiben; Todoist-Kennungen sind rund 16 Zeichen lang.
IDS_JE_ABFRAGE = 100

#: Fuer die Tests: ``httpx.MockTransport``. Im Betrieb immer ``None``.
TRANSPORT: httpx.BaseTransport | None = None


class TodoistFehler(Meldung, RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class Liste:
    id: str
    #: Mit den Eltern davor („Arbeit › Kunden"), damit gleichnamige
    #: Unterprojekte unterscheidbar bleiben.
    name: str
    eingang: bool = False


@dataclass
class FernStand:
    """Wie Todoist eine Aufgabe gerade sieht."""

    id: str
    erledigt: datetime | None
    faellig: date | None
    url: str


def _kopf(zugang: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {zugang}"}


def _anfrage(
    methode: str,
    pfad: str,
    zugang: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    fehlt_ist_none: bool = False,
) -> httpx.Response | None:
    """Eine Anfrage, und jeder Fehler als Kennung.

    ⚠️ **401 und 403 heissen „Token gilt nicht mehr", nie „du bist
    abgemeldet".** Die Oberflaeche wirft bei 401 aus nexmail hinaus; deshalb
    wird daraus hier eine eigene Kennung, die der Router als 409 weitergibt.
    """
    if not zugang:
        raise TodoistFehler("todoist_zugang_fehlt")
    try:
        with httpx.Client(timeout=ZEITGRENZE, transport=TRANSPORT) as klient:
            antwort = klient.request(
                methode,
                f"{BASIS}/{pfad}",
                params=params,
                json=json,
                headers=_kopf(zugang),
            )
    except httpx.TimeoutException as fehler:
        logger.info("Todoist did not answer in time: %s", type(fehler).__name__)
        raise TodoistFehler("todoist_zeitueberschreitung", sekunden=int(ZEITGRENZE)) from fehler
    except httpx.HTTPError as fehler:
        logger.info("Todoist was unreachable: %s", type(fehler).__name__)
        raise TodoistFehler("todoist_nicht_erreichbar") from fehler

    if antwort.status_code == 404 and fehlt_ist_none:
        return None
    if antwort.status_code in (401, 403):
        logger.info("Todoist refused the token (HTTP %s).", antwort.status_code)
        raise TodoistFehler("todoist_zugang_ungueltig")
    if antwort.status_code == 429:
        logger.info("Todoist asked to slow down (HTTP 429).")
        raise TodoistFehler("todoist_zu_viele_anfragen")
    if antwort.status_code >= 400:
        logger.info("Todoist answered HTTP %s on %s %s.", antwort.status_code, methode, pfad.split("/")[0])
        raise TodoistFehler("todoist_fehler", status=antwort.status_code)
    return antwort


def _json(antwort: httpx.Response) -> dict:
    try:
        daten = antwort.json()
    except ValueError as fehler:
        raise TodoistFehler("todoist_antwort_unlesbar") from fehler
    if not isinstance(daten, dict):
        raise TodoistFehler("todoist_antwort_unlesbar")
    return daten


def _seiten(pfad: str, zugang: str, params: dict | None = None) -> list[dict]:
    """Alle Seiten einer Liste (``results`` plus ``next_cursor``)."""
    heraus: list[dict] = []
    cursor = ""
    for _ in range(MAX_SEITEN):
        abfrage = dict(params or {}, limit=SEITE)
        if cursor:
            abfrage["cursor"] = cursor
        daten = _json(_anfrage("GET", pfad, zugang, params=abfrage))
        zeilen = daten.get("results")
        if not isinstance(zeilen, list):
            raise TodoistFehler("todoist_antwort_unlesbar")
        heraus.extend(z for z in zeilen if isinstance(z, dict))
        cursor = daten.get("next_cursor") or ""
        if not cursor:
            return heraus
    logger.warning("Todoist kept paging past %s pages; the rest was left out.", MAX_SEITEN)
    return heraus


def _datum(due: object) -> date | None:
    """Das Faelligkeitsdatum, ohne Uhrzeit — nexmails Aufgaben kennen keine."""
    if not isinstance(due, dict):
        return None
    wert = due.get("date")
    if not isinstance(wert, str) or len(wert) < 10:
        return None
    try:
        return date.fromisoformat(wert[:10])
    except ValueError:
        return None


def _zeitpunkt(wert: object) -> datetime | None:
    if not isinstance(wert, str) or not wert:
        return None
    try:
        zeit = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None
    return zeit if zeit.tzinfo else zeit.replace(tzinfo=timezone.utc)


def _stand(daten: dict) -> FernStand:
    kennung = str(daten.get("id") or "")
    if not kennung:
        raise TodoistFehler("todoist_antwort_unlesbar")
    erledigt = _zeitpunkt(daten.get("completed_at"))
    if erledigt is None and daten.get("checked") is True:
        # Abgehakt, aber ohne Zeitpunkt: dann eben jetzt. Offen ist sie nicht.
        erledigt = datetime.now(timezone.utc)
    return FernStand(
        id=kennung,
        erledigt=erledigt,
        faellig=_datum(daten.get("due")),
        url=AUFGABE_URL + kennung,
    )


# --- Was nexmail braucht -------------------------------------------------- #


def listen(zugang: str) -> list[Liste]:
    """Die Projekte, Eingang zuerst, dann in Todoists Reihenfolge.

    ⚠️ **Das ist zugleich die Pruefung des Tokens.** Kommt die Liste, gilt er
    — ein eigener Knopf „Verbindung testen" pruefte dasselbe noch einmal.
    """
    zeilen = [
        z
        for z in _seiten("projects", zugang)
        if not z.get("is_archived") and not z.get("is_deleted") and z.get("id")
    ]
    nach_id = {str(z["id"]): z for z in zeilen}

    def pfad(z: dict) -> str:
        teile = [str(z.get("name") or "")]
        gesehen = {str(z["id"])}
        eltern = z.get("parent_id")
        # ⚠️ Gesehen-Menge gegen einen Kreis in den Daten.
        while eltern and str(eltern) in nach_id and str(eltern) not in gesehen:
            gesehen.add(str(eltern))
            teile.insert(0, str(nach_id[str(eltern)].get("name") or ""))
            eltern = nach_id[str(eltern)].get("parent_id")
        return " › ".join(teile)

    listen_ = [
        Liste(
            id=str(z["id"]),
            name=pfad(z),
            eingang=bool(z.get("inbox_project") or z.get("is_inbox_project")),
        )
        for z in zeilen
    ]
    # Stabil sortieren: Der Eingang nach oben, sonst bleibt Todoists Folge.
    return sorted(listen_, key=lambda l: not l.eingang)


def anlegen(
    zugang: str,
    *,
    titel: str,
    beschreibung: str,
    liste_id: str,
    faellig: date | None,
) -> FernStand:
    rumpf: dict = {"content": titel[:500], "description": beschreibung[:16000]}
    if liste_id:
        rumpf["project_id"] = liste_id
    if faellig is not None:
        rumpf["due_date"] = faellig.isoformat()
    antwort = _anfrage("POST", "tasks", zugang, json=rumpf)
    return _stand(_json(antwort))


def offene(zugang: str, ids: list[str]) -> dict[str, FernStand]:
    """Welche dieser Aufgaben noch offen sind, mit ihrem Stand.

    ⚠️ ``GET /tasks`` liefert nur **offene** Aufgaben. Was hier fehlt, ist
    erledigt oder geloescht — welches von beiden, sagt erst ``eine``.
    """
    heraus: dict[str, FernStand] = {}
    for start in range(0, len(ids), IDS_JE_ABFRAGE):
        teil = ids[start : start + IDS_JE_ABFRAGE]
        for zeile in _seiten("tasks", zugang, {"ids": ",".join(teil)}):
            stand = _stand(zeile)
            if stand.erledigt is None:
                heraus[stand.id] = stand
    return heraus


def eine(zugang: str, fern_id: str) -> FernStand | None:
    """Eine Aufgabe, auch eine erledigte. ``None`` heisst: geloescht."""
    antwort = _anfrage("GET", f"tasks/{fern_id}", zugang, fehlt_ist_none=True)
    if antwort is None:
        return None
    daten = _json(antwort)
    if daten.get("is_deleted") is True:
        return None
    return _stand(daten)


def schliessen(zugang: str, fern_id: str) -> None:
    _anfrage("POST", f"tasks/{fern_id}/close", zugang)


def oeffnen(zugang: str, fern_id: str) -> None:
    _anfrage("POST", f"tasks/{fern_id}/reopen", zugang)
