"""nextime — die Schnittstelle, sonst nichts (MAIL-1).

Was eine Verbindung ist, wem sie gehört und wie aus nextimes Terminen
nexmails ``TerminZeile`` wird, steht in ``nextimeverbindung.py``. Hier steht
nur, wie man mit nextime spricht: über dessen ``/api/v1`` mit einem Schlüssel
(``nt_api_…``), Beschreibung unter ``<nextime>/api/v1/docs`` (ab nextime 0.2.0).

⚠️ **Dieselben Riegel wie bei nextasks** (``nextasks.py``): Der Mensch tippt
die Adresse ein, also nichts im eigenen Netz, solange der Betreiber es nicht
freigibt (``netzfreigabe.py``), der eigene Rechner nie, keiner Weiterleitung
folgen, und die Adresse wird bei **jeder** Anfrage neu geprüft.

⚠️ **Kein ``Origin``-Kopf.** nextime lehnt Anfragen mit ``Origin`` ab, weil
dann eine Webseite im Namen des Schlüssels spräche.

⚠️ **Kein Rumpf einer Antwort geht ins Protokoll**, nur Status, Code und
Pfadart. Darin stehen Termintitel und Notizen.

⚠️ **Zeiten (Antwort nextime, 23.11.2026):** Termine mit Uhrzeit kommen in UTC
mit ``Z`` plus ``time_zone``; ganztägige als reines Datum, ``end`` ist dabei
der **letzte** Tag, nicht der Folgetag.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import NoReturn
from urllib.parse import urlsplit

import httpx

from . import netzfreigabe
from .bildvermittler import Abgelehnt, adresse_pruefen
from ..meldung import Meldung
from .webhook import _eigener_rechner

logger = logging.getLogger("nexmail.nextime")

#: ⚠️ **Kurz.** Hier wartet ein Mensch vor dem Kalender.
ZEITGRENZE = 15.0

MAX_ADRESSE = 500
MAX_TOKEN = 500
#: Was nextime als iCalendar annimmt (``ical_too_large`` darüber).
MAX_ICAL = 1_000_000
#: Das längste Fenster einer Abfrage, wie nextime es erlaubt.
MAX_TAGE = 400

#: Ohne diese Merkmale in ``/me`` ist nextime zu alt für nexmail (ab 0.2.0).
MERKMALE = ("calendars", "events", "write", "search", "calendar_groups", "uid_lookup", "answer",
            "ical_import", "state")

#: Wenn nextime bei 429 kein ``Retry-After`` nennt.
PAUSE_OHNE_ANGABE = 60

#: Für die Tests: ``httpx.MockTransport``. Im Betrieb immer ``None``.
TRANSPORT: httpx.BaseTransport | None = None


class NextimeFehler(Meldung, RuntimeError):
    """Trägt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class Zugang:
    #: Die Adresse, unter der nextime läuft, ohne Schrägstrich am Ende.
    url: str
    token: str
    #: Modul verbinden: das Konto einer per Klick gemachten Verbindung; dann geht jede Anfrage über
    #: ``nexverbinden.call`` statt mit einem API-Schlüssel (``token`` leer).
    ueber: str = ""


@dataclass
class Ich:
    name: str
    stufe: str
    version: str
    zeitzone: str
    merkmale: list[str] = field(default_factory=list)


# --- Zugang ------------------------------------------------------------------ #


def zugang_lesen(roh: str) -> Zugang:
    try:
        daten = json.loads(roh)
        return Zugang(url=str(daten["url"]), token=str(daten["token"]), ueber=str(daten.get("ueber") or ""))
    except (ValueError, TypeError, KeyError) as fehler:
        raise NextimeFehler("nextime_zugang_kaputt") from fehler


def zugang_schreiben(zugang: Zugang) -> str:
    if zugang.ueber:
        return json.dumps({"url": zugang.url, "token": "", "ueber": zugang.ueber})
    return json.dumps({"url": zugang.url, "token": zugang.token})


def adresse_bereinigen(url: str) -> str:
    """Die Form prüfen, ohne aufzulösen. Für das Speichern.

    ⚠️ **Mit Pfad erlaubt** (nextime hinter einem Unterpfad), ohne Abfrage und
    Anker: Daran hängt nexmail ``/api/v1/…`` an. Wer die Adresse samt
    ``/api/v1`` aus nextimes Einstellungen kopiert, bekommt sie ohne.
    """
    url = url.strip().rstrip("/")
    if url.lower().endswith("/api/v1"):
        url = url[: -len("/api/v1")]
    teile = urlsplit(url)
    if (
        len(url) > MAX_ADRESSE
        or teile.scheme not in ("http", "https")
        or not teile.hostname
        or teile.query
        or teile.fragment
    ):
        raise NextimeFehler("nextime_adresse_ungueltig")
    if teile.username or teile.password:
        # ⚠️ Zugangsdaten in der Adresse stünden später im Klartext da.
        raise NextimeFehler("nextime_adresse_ungueltig")
    # ⚠️ Eigener Satz für localhost: Im Container ist das nexmail selbst, nicht
    # der Rechner, auf dem nextime läuft.
    if _eigener_rechner(teile.hostname.lower()):
        raise NextimeFehler("nextime_adresse_localhost")
    return url


def _pruefen(url: str) -> None:
    """⚠️ Dieselbe Prüfung wie bei nextasks (``nextasks._pruefen``)."""
    adresse_bereinigen(url)
    try:
        adresse_pruefen(url)
        return
    except Abgelehnt as f:
        grund = f
    if str(grund) == "bild_adresse_im_eigenen_netz" and netzfreigabe.erlaubt_jetzt():
        try:
            adresse_pruefen(url, eigenes_netz=True)
            return
        except Abgelehnt as f:
            grund = f
    if str(grund) == "bild_adresse_im_eigenen_netz":
        raise NextimeFehler("nextime_adresse_im_eigenen_netz") from grund
    if str(grund) == "bild_adresse_unerlaubt":
        raise NextimeFehler("nextime_adresse_ungueltig") from grund
    raise NextimeFehler("nextime_nicht_erreichbar") from grund


# --- Anfragen ------------------------------------------------------------------ #


def _code(antwort: httpx.Response) -> str:
    """``detail.code`` aus einer Fehlerantwort."""
    try:
        daten = antwort.json()
    except ValueError:
        return ""
    detail = daten.get("detail") if isinstance(daten, dict) else None
    if not isinstance(detail, dict):
        return ""
    return str(detail.get("code") or "")


def _pause(antwort: httpx.Response) -> int:
    wert = antwort.headers.get("retry-after", "")
    return int(wert) if wert.isdigit() and 0 < int(wert) < 86_400 else PAUSE_OHNE_ANGABE


def _absage(antwort: httpx.Response, methode: str, pfad: str) -> NoReturn:
    """Jede Absage als Kennung. ⚠️ **401 heißt nie „du bist abgemeldet"**:
    Der Router gibt diese Kennungen als 409 weiter, sonst meldete die
    Oberfläche den Menschen aus nexmail ab.

    ⚠️ **Jede Kennung steht wörtlich an einem ``raise``**, sonst sieht der
    Wächter in ``test_meldungen.py`` sie nicht."""
    status = antwort.status_code
    code = _code(antwort)
    art = pfad.split("/")[0].split("?")[0]
    logger.info("nextime answered HTTP %s (%s) on %s %s.", status, code or "-", methode, art)
    if status == 401 and code == "api_off":
        raise NextimeFehler("nextime_api_aus")
    if status == 401:
        raise NextimeFehler("nextime_zugang_ungueltig")
    if status == 403 and code == "token_reads_only":
        raise NextimeFehler("nextime_nur_lesen")
    if status == 403 and code == "calendar_read_only":
        raise NextimeFehler("nextime_kalender_nur_lesen")
    if status == 403:
        raise NextimeFehler("nextime_nicht_erlaubt")
    if status == 404:
        raise NextimeFehler("nextime_nicht_gefunden")
    if status == 409 and code == "not_an_invitation":
        raise NextimeFehler("nextime_keine_einladung")
    if status == 409 and code == "answers_not_possible":
        raise NextimeFehler("nextime_antwort_unmoeglich")
    if status == 409 and code == "invitation_changed":
        raise NextimeFehler("nextime_einladung_geaendert")
    if status == 413:
        raise NextimeFehler("nextime_ical_zu_gross")
    if status == 422 and code == "attendee_unknown":
        raise NextimeFehler("nextime_teilnehmer_unbekannt")
    if status == 422 and code in ("invalid_ical", "ical_method_unsupported", "not_an_invitation"):
        raise NextimeFehler("nextime_einladung_unlesbar")
    if status == 422 and code == "invalid_range":
        raise NextimeFehler("nextime_zeitraum_zu_lang", tage=MAX_TAGE)
    if status == 422 and code == "occurrence_unknown":
        raise NextimeFehler("nextime_vorkommen_unbekannt")
    if status == 422:
        raise NextimeFehler("nextime_eingabe_abgelehnt")
    if status == 429:
        raise NextimeFehler("nextime_zu_viele_anfragen", sekunden=_pause(antwort))
    if 300 <= status < 400:
        raise NextimeFehler("nextime_weiterleitung", status=status)
    raise NextimeFehler("nextime_fehler", status=status)


def _ueber_verbindung(zugang: Zugang, methode: str, pfad: str, *, params, rumpf) -> httpx.Response:
    """Dieselbe Anfrage über die Klick-Verbindung (Modul verbinden, V18): Absagen und JSON wie mit einem Schlüssel."""
    from . import verbinden_store

    try:
        antwort = verbinden_store.anfragen("nextime", zugang.ueber, methode, f"/api/v1/{pfad}", params=params, rumpf=rumpf)
    except verbinden_store.Unerreichbar as fehler:
        raise NextimeFehler("nextime_nicht_erreichbar") from fehler
    if antwort.status_code >= 300:
        _absage(antwort, methode, pfad)
    return antwort


def _anfrage(
    zugang: Zugang,
    methode: str,
    pfad: str,
    *,
    params: dict | list | None = None,
    json_rumpf: dict | None = None,
    frist: float | None = None,
) -> httpx.Response:
    """Eine Anfrage an ``<adresse>/api/v1/<pfad>``, jeder Fehler als Kennung.

    ⚠️ **Die Adresse wird bei jedem Aufruf neu geprüft**: Der Betreiber kann
    das eigene Netz inzwischen gesperrt haben.
    """
    if zugang.ueber:
        return _ueber_verbindung(zugang, methode, pfad, params=params, rumpf=json_rumpf)
    if not zugang.token:
        raise NextimeFehler("nextime_zugang_fehlt")
    if TRANSPORT is None:
        _pruefen(zugang.url)
    else:
        adresse_bereinigen(zugang.url)
    try:
        with httpx.Client(timeout=frist or ZEITGRENZE, follow_redirects=False, transport=TRANSPORT) as klient:
            antwort = klient.request(
                methode,
                f"{zugang.url}/api/v1/{pfad}",
                params=params,
                json=json_rumpf,
                # ⚠️ Kein ``Origin``: nextime lehnt Anfragen aus Webseiten ab.
                headers={"Authorization": f"Bearer {zugang.token}", "User-Agent": "nexmail"},
            )
    except httpx.TimeoutException as fehler:
        logger.info("nextime did not answer in time: %s", type(fehler).__name__)
        raise NextimeFehler("nextime_zeitueberschreitung", sekunden=int(frist or ZEITGRENZE)) from fehler
    except httpx.HTTPError as fehler:
        logger.info("nextime was unreachable: %s", type(fehler).__name__)
        raise NextimeFehler("nextime_nicht_erreichbar") from fehler
    if antwort.status_code >= 300:
        _absage(antwort, methode, pfad)
    return antwort


def _json(antwort: httpx.Response) -> dict:
    try:
        daten = antwort.json()
    except ValueError as fehler:
        raise NextimeFehler("nextime_antwort_unlesbar") from fehler
    if not isinstance(daten, dict):
        raise NextimeFehler("nextime_antwort_unlesbar")
    return daten


def _liste(daten: dict, schluessel: str) -> list[dict]:
    werte = daten.get(schluessel)
    if not isinstance(werte, list):
        raise NextimeFehler("nextime_antwort_unlesbar")
    return [w for w in werte if isinstance(w, dict)]


def link(wert: object) -> str:
    """⚠️ **Nur http(s)**: Der Link steht später als ``href`` in der Oberfläche."""
    if isinstance(wert, str) and len(wert) <= 2000 and urlsplit(wert).scheme in ("http", "https"):
        return wert
    return ""


# --- Was nexmail braucht ------------------------------------------------------- #


def pruefen(zugang: Zugang) -> Ich:
    """``/me`` — und nur ein nextime, das alles kann, gilt als verbunden.

    ⚠️ **Ein Schlüssel, der nur liest, wird abgewiesen**: Ohne Schreiben kann
    nexmail weder eintragen noch antworten, und die Verbindung stünde da, bis
    der erste Klick scheitert. Ebenso ein Schlüssel für einzelne Kalender:
    Dann fehlten Kalender, und niemand sähe, warum.
    """
    try:
        daten = _json(_anfrage(zugang, "GET", "me"))
    except NextimeFehler as f:
        # Ein nextime ohne ``/api/v1`` antwortet mit 404: zu alt.
        if f.kennung == "nextime_nicht_gefunden":
            raise NextimeFehler("nextime_zu_alt") from f
        raise
    if daten.get("app") != "nextime":
        raise NextimeFehler("nextime_keine_antwort_von_nextime")
    merkmale = [str(m) for m in daten.get("features") or [] if isinstance(m, str)]
    if any(m not in merkmale for m in MERKMALE):
        raise NextimeFehler("nextime_zu_alt")
    stufe = str(daten.get("level") or "")
    if stufe != "write":
        raise NextimeFehler("nextime_nur_lesen")
    if daten.get("calendars") is not None:
        raise NextimeFehler("nextime_schluessel_nicht_fuer_alle")
    return Ich(
        name=str(daten.get("display_name") or daten.get("name") or "")[:200],
        stufe=stufe,
        version=str(daten.get("version") or "")[:40],
        zeitzone=str(daten.get("time_zone") or "")[:64],
        merkmale=merkmale,
    )


def kalender(zugang: Zugang, *, frist: float | None = None) -> list[dict]:
    """Die Kalender in der Reihenfolge der nextime-Seitenleiste."""
    return _liste(_json(_anfrage(zugang, "GET", "calendars", frist=frist)), "calendars")


def termine(
    zugang: Zugang, start: str, end: str, kalender_ids: list[int], *, frist: float | None = None
) -> list[dict]:
    """Alle Vorkommen im Fenster, Serien aufgerollt.

    ⚠️ **Die Kalender immer ausdrücklich nennen.** Ohne ``calendars`` liefert
    nextime die in nextime ausgeblendeten nicht, auch wenn sie in nexmail einen
    Haken haben.
    """
    if not kalender_ids:
        return []
    params = {"start": start, "end": end, "calendars": ",".join(str(i) for i in kalender_ids)}
    return _liste(_json(_anfrage(zugang, "GET", "events", params=params, frist=frist)), "events")


def termin(zugang: Zugang, event_id: int, vorkommen: str | None = None) -> dict:
    params = {"occurrence": vorkommen} if vorkommen else None
    return _json(_anfrage(zugang, "GET", f"events/{int(event_id)}", params=params))


def nach_uid(zugang: Zugang, uid: str, *, frist: float | None = None) -> list[dict]:
    """Jeder Termin mit dieser UID in den Kalendern des Schlüssels, einmal."""
    if not uid:
        return []
    return _liste(_json(_anfrage(zugang, "GET", "events", params={"uid": uid}, frist=frist)), "events")


def anlegen(zugang: Zugang, rumpf: dict) -> dict:
    return _json(_anfrage(zugang, "POST", "events", json_rumpf=rumpf))


def aendern(zugang: Zugang, event_id: int, rumpf: dict) -> dict:
    return _json(_anfrage(zugang, "PATCH", f"events/{int(event_id)}", json_rumpf=rumpf))


def loeschen(zugang: Zugang, event_id: int, umfang: str, vorkommen: str | None) -> None:
    params: dict[str, str] = {"scope": umfang}
    if vorkommen:
        params["occurrence"] = vorkommen
    _anfrage(zugang, "DELETE", f"events/{int(event_id)}", params=params)


def suchen(zugang: Zugang, wort: str) -> list[dict]:
    return _liste(_json(_anfrage(zugang, "GET", "search", params={"q": wort})), "events")


def stand(zugang: Zugang) -> str:
    """Die Versionsnummer von ``/state``: Zeichenkette vergleichen, nicht auswerten."""
    return str(_json(_anfrage(zugang, "GET", "state")).get("version") or "")


def antworten(zugang: Zugang, event_id: int, antwort: str, vorkommen: str | None = None) -> dict:
    """Eine Einladung beantworten, die schon in nextime steht.

    ``reply_by`` sagt, wer die Antwort an den Organisator schickt:
    ``source`` (iCloud, Google, CalDAV-Server selbst) oder ``client`` (nexmail
    per Mail). ⚠️ **Bei ``source`` schickt nexmail nichts**, sonst kommt die
    Antwort doppelt an (MAIL-1 EC-16).
    """
    rumpf: dict = {"answer": antwort}
    if vorkommen:
        rumpf["occurrence"] = vorkommen
    return _json(_anfrage(zugang, "POST", f"events/{int(event_id)}/answer", json_rumpf=rumpf))


def ical_eintragen(
    zugang: Zugang,
    ical: str,
    *,
    kalender_id: int | None,
    antwort: str | None,
    teilnehmer: str = "",
) -> dict:
    """Eine Einladung aus einer Mail eintragen (iMIP: REQUEST, PUBLISH, CANCEL).

    ⚠️ **nextime schickt dabei nie etwas** (``SCHEDULE-AGENT=CLIENT``,
    ``Schedule-Reply: F``); die Antwort an den Organisator schickt nexmail
    selbst, außer ``reply_by`` sagt ``source``.
    """
    if len(ical.encode("utf-8")) > MAX_ICAL:
        raise NextimeFehler("nextime_ical_zu_gross")
    rumpf: dict = {"ical": ical}
    if kalender_id is not None:
        rumpf["calendar_id"] = kalender_id
    if antwort:
        rumpf["answer"] = antwort
    if teilnehmer:
        rumpf["attendee"] = teilnehmer
    return _json(_anfrage(zugang, "POST", "events/ical", json_rumpf=rumpf))

