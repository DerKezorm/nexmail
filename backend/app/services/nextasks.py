"""nextasks — die Schnittstelle, sonst nichts.

Was eine Verbindung ist, wem sie gehoert und wann abgeglichen wird, steht in
``aufgabenziele.py``. Hier steht nur, wie man mit nextasks spricht: ueber
dessen ``/api/v1`` mit einem API-Token (``ntk_…``), Beschreibung in nextasks
unter ``docs/api.md``.

⚠️ **Gleichwertig zu Todoist, aber selbst gehostet.** Anders als bei Todoist
tippt der Mensch hier die Adresse ein. Also gilt dieselbe Pruefung wie bei
einem Webhook und den Kalendern: nichts im eigenen Netz, solange der Betreiber
es nicht freigibt (``netzfreigabe.py``), der eigene Rechner nie, und keiner
Weiterleitung folgen.

⚠️ **Erst ``/me``, dann alles andere.** Ein Token, der nur lesen darf, oder ein
nextasks, dessen ``features`` ``tasks`` und ``external_ref`` nicht nennen,
wird beim Verbinden abgewiesen; sonst scheiterte erst das erste „Zu Aufgabe
machen", weit weg von der Ursache.

⚠️ **``external_ref`` macht das Anlegen wiederholbar.** nextasks antwortet auf
denselben Schluessel mit 200 und der vorhandenen Aufgabe, auch einer
erledigten oder einer im Papierkorb. Damit gilt „eine Mail, eine Aufgabe" auch
dort, selbst wenn nexmail seine Zeile verloren hat.

⚠️ **Kein Rumpf einer Antwort geht ins Protokoll**, nur Status und Kennung.
Darin koennen Aufgabentexte stehen.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import NoReturn
from urllib.parse import urlsplit

import httpx

from . import netzfreigabe
from .bildvermittler import Abgelehnt, adresse_pruefen
from ..meldung import Meldung
from .webhook import _eigener_rechner

logger = logging.getLogger("nexmail.nextasks")

#: ⚠️ **Kurz.** Hier wartet ein Mensch vor dem Fenster „Zu Aufgabe machen".
ZEITGRENZE = 20.0

MAX_ADRESSE = 500
MAX_TOKEN = 500
#: Was nextasks in ``notes`` annimmt.
MAX_NOTIZ = 20_000
#: Was nextasks in ``external_ref`` annimmt.
MAX_SCHLUESSEL = 200
#: Wie viele Kennungen ``?ids=`` traegt (nextasks' Hoechstwert).
IDS_JE_ABFRAGE = 200
#: ⚠️ Ein Deckel fuer die Seiten, wie bei Todoist: ein Cursor, der nie leer
#: wird, liesse die Schleife sonst ewig laufen.
MAX_SEITEN = 20

#: Ohne diese Merkmale in ``/me`` ist nextasks zu alt fuer nexmail.
MERKMALE = ("tasks", "external_ref")

#: Wenn nextasks bei 429 kein ``Retry-After`` nennt.
PAUSE_OHNE_ANGABE = 60

#: Trennt Liste und Abschnitt im Ziel (``<liste>/<abschnitt>``). nextasks'
#: Kennungen sind UUIDs, ein Schraegstrich kommt darin nicht vor.
ABSCHNITT = "/"

#: Fuer die Tests: ``httpx.MockTransport``. Im Betrieb immer ``None``.
TRANSPORT: httpx.BaseTransport | None = None


class NextasksFehler(Meldung, RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz."""


@dataclass
class Zugang:
    #: Die Adresse, unter der nextasks laeuft, ohne Schraegstrich am Ende.
    url: str
    token: str


@dataclass
class Ich:
    name: str
    stufe: str


@dataclass
class Liste:
    #: Die Liste, oder ``<liste>/<abschnitt>``.
    id: str
    #: Mit Bereich davor („Familie › Einkauf"), dazu der Abschnitt.
    name: str
    #: Der Bereich ist beim Konto ausgeblendet; solche stehen am Ende.
    ausgeblendet: bool = False


@dataclass
class FernStand:
    """Wie nextasks eine Aufgabe gerade sieht."""

    id: str
    erledigt: datetime | None = None
    faellig: date | None = None
    #: Der Link in nextasks' Oberflaeche, leer ohne oeffentliche Adresse dort.
    url: str = ""
    #: Im Papierkorb: wiederherstellbar, also weiter nachsehen.
    papierkorb: bool = False
    #: Endgueltig weg, oder fuer diesen Token nicht mehr sichtbar.
    weg: bool = False


# --- Zugang ------------------------------------------------------------------ #


def zugang_lesen(roh: str) -> Zugang:
    try:
        daten = json.loads(roh)
        return Zugang(url=str(daten["url"]), token=str(daten["token"]))
    except (ValueError, TypeError, KeyError) as fehler:
        raise NextasksFehler("nextasks_zugang_kaputt") from fehler


def zugang_schreiben(zugang: Zugang) -> str:
    return json.dumps({"url": zugang.url, "token": zugang.token})


def adresse_bereinigen(url: str) -> str:
    """Die Form pruefen, ohne aufzuloesen. Fuer das Speichern.

    ⚠️ **Mit Pfad erlaubt** (nextasks hinter einem Unterpfad), ohne Abfrage
    und Anker: Daran haengt nexmail ``/api/v1/…`` an.
    """
    url = url.strip().rstrip("/")
    teile = urlsplit(url)
    if (
        len(url) > MAX_ADRESSE
        or teile.scheme not in ("http", "https")
        or not teile.hostname
        or teile.query
        or teile.fragment
    ):
        raise NextasksFehler("nextasks_adresse_ungueltig")
    if teile.username or teile.password:
        # ⚠️ Zugangsdaten in der Adresse stuenden spaeter im Klartext da.
        raise NextasksFehler("nextasks_adresse_ungueltig")
    # ⚠️ Eigener Satz fuer localhost, wie beim Webhook: Im Container ist das
    # nexmail selbst, nicht der Rechner, auf dem nextasks laeuft.
    if _eigener_rechner(teile.hostname.lower()):
        raise NextasksFehler("nextasks_adresse_localhost")
    return url


def _pruefen(url: str) -> None:
    """⚠️ Dieselbe Pruefung wie beim Webhook (``webhook._pruefen``)."""
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
        raise NextasksFehler("nextasks_adresse_im_eigenen_netz") from grund
    if str(grund) == "bild_adresse_unerlaubt":
        raise NextasksFehler("nextasks_adresse_ungueltig") from grund
    raise NextasksFehler("nextasks_nicht_erreichbar") from grund


def schluessel_fuer(message_id: str) -> str:
    """``nexmail:<Message-ID>``, der eigene Schluessel in nextasks.

    ⚠️ **Hoechstens 200 Zeichen.** Eine laengere Message-ID wird gehasht,
    immer gleich: Derselbe Schluessel muss bei jeder Wiederholung derselbe
    sein, sonst entstuende doch ein Doppel.
    """
    schluessel = f"nexmail:{message_id}"
    if len(schluessel) <= MAX_SCHLUESSEL:
        return schluessel
    return "nexmail:sha256:" + hashlib.sha256(message_id.encode("utf-8")).hexdigest()


# --- Anfragen ------------------------------------------------------------------ #


def _code(antwort: httpx.Response) -> tuple[str, list]:
    """``detail.code`` und ``detail.fields`` aus einer Fehlerantwort."""
    try:
        daten = antwort.json()
    except ValueError:
        return "", []
    detail = daten.get("detail") if isinstance(daten, dict) else None
    if not isinstance(detail, dict):
        return "", []
    felder = detail.get("fields")
    return str(detail.get("code") or ""), felder if isinstance(felder, list) else []


def _pause(antwort: httpx.Response) -> int:
    wert = antwort.headers.get("retry-after", "")
    return int(wert) if wert.isdigit() and 0 < int(wert) < 86_400 else PAUSE_OHNE_ANGABE


def _absage(antwort: httpx.Response, methode: str, pfad: str) -> NoReturn:
    """Jede Absage als Kennung. ⚠️ **401 heisst nie „du bist abgemeldet"**:
    Der Router gibt diese Kennungen als 409 weiter.

    ⚠️ **Jede Kennung steht woertlich an einem ``raise``**, sonst sieht der
    Waechter in ``test_meldungen.py`` sie nicht."""
    status = antwort.status_code
    code, felder = _code(antwort)
    art = pfad.split("/")[0].split("?")[0]
    logger.info("nextasks answered HTTP %s (%s) on %s %s.", status, code or "-", methode, art)
    if status == 401 and code == "api_off":
        raise NextasksFehler("nextasks_api_aus")
    if status == 401:
        raise NextasksFehler("nextasks_zugang_ungueltig")
    if status == 403 and code == "token_reads_only":
        raise NextasksFehler("nextasks_nur_lesen")
    if status == 403 and code == "not_allowed":
        raise NextasksFehler("nextasks_nicht_erlaubt")
    if status == 404:
        raise NextasksFehler("nextasks_nicht_gefunden")
    if status == 409:
        raise NextasksFehler("nextasks_konflikt")
    if status == 422 and "list_id" in felder:
        raise NextasksFehler("nextasks_liste_unbekannt")
    if status == 429:
        raise NextasksFehler("nextasks_zu_viele_anfragen", sekunden=_pause(antwort))
    if 300 <= status < 400:
        raise NextasksFehler("nextasks_weiterleitung", status=status)
    raise NextasksFehler("nextasks_fehler", status=status)


def _anfrage(
    zugang: Zugang,
    methode: str,
    pfad: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> httpx.Response:
    """Eine Anfrage an ``<adresse>/api/v1/<pfad>``, jeder Fehler als Kennung.

    ⚠️ **Die Adresse wird bei jedem Aufruf neu geprueft**, wie beim Webhook:
    Der Betreiber kann das eigene Netz inzwischen gesperrt haben.
    """
    if not zugang.token:
        raise NextasksFehler("nextasks_zugang_fehlt")
    # Mit eigenem Transport (nur in Tests) gibt es kein Netz, also auch nichts
    # aufzuloesen.
    if TRANSPORT is None:
        _pruefen(zugang.url)
    else:
        adresse_bereinigen(zugang.url)
    try:
        with httpx.Client(timeout=ZEITGRENZE, follow_redirects=False, transport=TRANSPORT) as klient:
            antwort = klient.request(
                methode,
                f"{zugang.url}/api/v1/{pfad}",
                params=params,
                json=json,
                # ⚠️ Kein ``Origin``: nextasks lehnt Anfragen aus Webseiten ab.
                headers={"Authorization": f"Bearer {zugang.token}", "User-Agent": "nexmail"},
            )
    except httpx.TimeoutException as fehler:
        logger.info("nextasks did not answer in time: %s", type(fehler).__name__)
        raise NextasksFehler("nextasks_zeitueberschreitung", sekunden=int(ZEITGRENZE)) from fehler
    except httpx.HTTPError as fehler:
        logger.info("nextasks was unreachable: %s", type(fehler).__name__)
        raise NextasksFehler("nextasks_nicht_erreichbar") from fehler
    if antwort.status_code >= 300:
        _absage(antwort, methode, pfad)
    return antwort


def _json(antwort: httpx.Response) -> dict:
    try:
        daten = antwort.json()
    except ValueError as fehler:
        raise NextasksFehler("nextasks_antwort_unlesbar") from fehler
    if not isinstance(daten, dict):
        raise NextasksFehler("nextasks_antwort_unlesbar")
    return daten


def _datum(wert: object) -> date | None:
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


def _link(wert: object) -> str:
    # ⚠️ Nur http(s): Der Link steht spaeter als ``href`` in der Oberflaeche.
    if isinstance(wert, str) and len(wert) <= 2000 and urlsplit(wert).scheme in ("http", "https"):
        return wert
    return ""


def _stand(daten: dict) -> FernStand:
    kennung = daten.get("id")
    if not isinstance(kennung, str) or not kennung:
        raise NextasksFehler("nextasks_antwort_unlesbar")
    if daten.get("gone") is True:
        return FernStand(id=kennung, weg=True)
    erledigt = None
    if daten.get("completed") is True:
        # Abgehakt, aber ohne Zeitpunkt: dann eben jetzt. Offen ist sie nicht.
        erledigt = _zeitpunkt(daten.get("completed_at")) or datetime.now(timezone.utc)
    return FernStand(
        id=kennung,
        erledigt=erledigt,
        faellig=_datum(daten.get("due_date")),
        url=_link(daten.get("link")),
        papierkorb=daten.get("trashed") is True,
    )


# --- Was nexmail braucht ------------------------------------------------------- #


def pruefen(zugang: Zugang) -> Ich:
    """``GET /me``: Gilt der Token, darf er schreiben, kann nextasks genug?

    ⚠️ **Ein 404 hier heisst: kein ``/api/v1``**, also ein nextasks von vor
    der Schnittstelle, oder unter der Adresse laeuft gar keins.
    """
    try:
        daten = _json(_anfrage(zugang, "GET", "me"))
    except NextasksFehler as fehler:
        if fehler.kennung == "nextasks_nicht_gefunden":
            raise NextasksFehler("nextasks_zu_alt") from fehler
        raise
    merkmale = daten.get("features")
    if not isinstance(merkmale, list) or not all(m in merkmale for m in MERKMALE):
        raise NextasksFehler("nextasks_zu_alt")
    if daten.get("level") != "write":
        raise NextasksFehler("nextasks_nur_lesen")
    return Ich(name=str(daten.get("display_name") or daten.get("name") or ""), stufe="write")


def listen(zugang: Zugang) -> list[Liste]:
    """Die Listen, in die der Token schreiben darf, samt Abschnitten.

    ⚠️ **In nextasks' Reihenfolge, Ausgeblendetes ans Ende.** nextasks liefert
    Listen ausgeblendeter Bereiche schon am Ende; sortiert wird trotzdem
    stabil, damit es nicht an der Gegenseite haengt.

    ⚠️ **Keine Liste ist „die Vorgabe".** Die erste Liste in ``/lists`` ist
    nicht zwingend die, in die nextasks ohne ``list_id`` schreibt.
    """
    daten = _json(_anfrage(zugang, "GET", "lists"))
    zeilen = daten.get("lists")
    if not isinstance(zeilen, list):
        raise NextasksFehler("nextasks_antwort_unlesbar")
    heraus: list[Liste] = []
    for z in zeilen:
        if not isinstance(z, dict) or not isinstance(z.get("id"), str) or not z["id"]:
            continue
        if z.get("writable") is False:
            continue
        name = " › ".join(str(t) for t in (z.get("space_name"), z.get("name")) if t)
        ausgeblendet = z.get("hidden") is True
        heraus.append(Liste(id=z["id"], name=name, ausgeblendet=ausgeblendet))
        for s in z.get("sections") or []:
            if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]:
                heraus.append(
                    Liste(
                        id=f"{z['id']}{ABSCHNITT}{s['id']}",
                        name=f"{name} › {s.get('name') or ''}",
                        ausgeblendet=ausgeblendet,
                    )
                )
    return sorted(heraus, key=lambda l: l.ausgeblendet)


def anlegen(
    zugang: Zugang,
    *,
    titel: str,
    notizen: str,
    link: str,
    liste: str,
    faellig: date | None,
    schluessel: str,
) -> tuple[FernStand, bool]:
    """Eine Aufgabe anlegen. Gibt ihren Stand zurueck und ob sie neu ist.

    ⚠️ **200 heisst „gab es schon"**, auch erledigt oder im Papierkorb; der
    Stand sagt dann, wie sie gerade ist.
    """
    rumpf: dict = {"title": titel[:500]}
    if notizen:
        rumpf["notes"] = notizen[:MAX_NOTIZ]
    if link:
        rumpf["url"] = link
    liste_id, _, abschnitt_id = liste.partition(ABSCHNITT)
    if liste_id:
        rumpf["list_id"] = liste_id
    if abschnitt_id:
        rumpf["section_id"] = abschnitt_id
    if faellig is not None:
        rumpf["due_date"] = faellig.isoformat()
    if schluessel:
        rumpf["external_ref"] = schluessel
    try:
        antwort = _anfrage(zugang, "POST", "tasks", json=rumpf)
    except NextasksFehler as fehler:
        # ⚠️ **Gemessen am 07.11.2026:** Fuer eine Liste, die der Token nicht
        # sieht, antwortet nextasks mit ``404 not_found``, nicht mit dem
        # ``422`` samt ``fields: ["list_id"]`` aus seiner ``api.md``. Beim
        # Anlegen kann nur die Liste (oder ihr Abschnitt) fehlen.
        if fehler.kennung == "nextasks_nicht_gefunden":
            raise NextasksFehler("nextasks_liste_unbekannt") from fehler
        raise
    return _stand(_json(antwort)), antwort.status_code == 201


def staende(zugang: Zugang, ids: list[str]) -> dict[str, FernStand]:
    """Wie nextasks diese Aufgaben sieht, in jedem Zustand.

    ⚠️ **Eine Frage je 200 Kennungen**, nicht eine je Aufgabe: ``?ids=``
    liefert offene, erledigte und Papierkorb, und was fort ist, als
    ``gone``. Was in der Antwort fehlt, bleibt unbekannt und unveraendert.
    """
    heraus: dict[str, FernStand] = {}
    for start in range(0, len(ids), IDS_JE_ABFRAGE):
        teil = ids[start : start + IDS_JE_ABFRAGE]
        cursor = ""
        for _ in range(MAX_SEITEN):
            params = {
                "ids": ",".join(teil),
                "state": "all",
                "include_trashed": "true",
                "limit": str(IDS_JE_ABFRAGE),
            }
            if cursor:
                params["cursor"] = cursor
            daten = _json(_anfrage(zugang, "GET", "tasks", params=params))
            zeilen = daten.get("tasks")
            if not isinstance(zeilen, list):
                raise NextasksFehler("nextasks_antwort_unlesbar")
            for z in zeilen:
                if isinstance(z, dict):
                    stand = _stand(z)
                    heraus[stand.id] = stand
            cursor = daten.get("next_cursor") or ""
            if not cursor:
                break
    return heraus


def haken(zugang: Zugang, fern_id: str, erledigt: bool) -> FernStand:
    """Abhaken oder wieder oeffnen, und wie die Aufgabe danach ist.

    ⚠️ **Eine wiederholte Aufgabe bleibt nach dem Abhaken offen**, mit neuem
    Datum (``next``, ``completed_copy``). Der Stand zeigt das; wer ihn liest,
    setzt hier keinen Haken.
    """
    antwort = _anfrage(zugang, "PATCH", f"tasks/{fern_id}", json={"completed": erledigt})
    return _stand(_json(antwort))
