"""Der KI-Dienst eines Benutzers — OpenAI-förmig, wer auch immer dahintersteht.

⚠️ **Eine Schnittstelle, nicht vier.** `POST /v1/chat/completions` und
`GET /v1/models` sind der De-facto-Standard: Claude, Gemini, OpenAI, Ollama,
LM Studio, llama.cpp, vLLM, OpenRouter und was noch kommt sprechen alle
dieselbe Form. nexmail kennt deshalb **keinen einzigen Anbieter** — es kennt
drei Werte: Adresse, Schlüssel, Modell. Wer eine Liste von Anbietern in den
Server schreibt, sperrt jeden aus, der morgen dazukommt.

⚠️ **Je Benutzer.** Der Zugang hängt am Menschen, nicht an der Installation —
wie ein Postfach, wie eine OAuth-Zustimmung. Jeder zahlt seinen eigenen
Schlüssel, und der Betreiber muss nichts vorgeben.

⚠️ **Ab Werk aus.** nexmail blockt Zählpixel, liefert Schriften mit und holt
Bilder über den eigenen Server. Hier geht Text nach draußen; das ist eine
Entscheidung, die ein Mensch trifft.

⚠️ **Ein Abo ist kein API-Zugang.** Claude Pro/Max und ChatGPT Plus geben
keinen Schlüssel her — bei Anthropic verstößt es seit April 2026 sogar gegen
die Nutzungsbedingungen, ein Abo-OAuth-Token in einem fremden Programm zu
verwenden. Der Satz steht in der Oberfläche, nicht in einer README.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from .. import crypto
from ..meldung import Meldung
from ..models import Benutzer

logger = logging.getLogger("nexmail.ki")

#: ⚠️ **Kurz.** Wer auf eine Modellliste zehn Sekunden wartet, hält den Zugang
#: für kaputt — und er ist es meistens auch, wenn sie so lange braucht.
ZEITGRENZE = 20.0

#: Wie viele Modellnamen hereingelassen werden. Ollama listet, was gezogen
#: wurde; ein Vermittler wie OpenRouter listet Hunderte.
MAX_MODELLE = 500


class KiFehler(Meldung):
    """Etwas, das dem Menschen davor gezeigt wird."""


def _kontext(person: Benutzer) -> str:
    return f"benutzer:{person.id}:ki"


def schluessel_lesen(person: Benutzer) -> str:
    return crypto.entschluesseln(person.ki_schluessel, _kontext(person))


def schluessel_schreiben(person: Benutzer, klartext: str) -> None:
    person.ki_schluessel = (
        crypto.verschluesseln(klartext, _kontext(person)) if klartext else ""
    )


def adresse_pruefen(url: str) -> str:
    """Die Basisadresse säubern und auf ihre Form prüfen.

    ⚠️ **Mit Schrägstrich am Ende.** ``urljoin("…/v1", "models")`` wirft das
    ``v1`` weg und fragt ``…/models`` — bei jedem Anbieter die falsche Adresse,
    und die Meldung dazu lautet „nicht gefunden".

    ⚠️ **Nur ``http`` und ``https``.** Ein ``file:`` oder ``ftp:`` hätte hier
    nichts zu suchen; dieselbe Prüfung wie beim Bildvermittler und beim
    ICS-Abo. Das eigene Netz bleibt hier allerdings **erlaubt** — genau dort
    steht Ollama, und das ist der Weg, den nexmail empfiehlt.
    """
    url = (url or "").strip()
    if not url:
        raise KiFehler("ki_adresse_fehlt")
    teile = urlparse(url)
    if teile.scheme not in ("http", "https") or not teile.netloc:
        raise KiFehler("ki_adresse_ungueltig")
    return url if url.endswith("/") else url + "/"


def _kopfzeilen(schluessel: str) -> dict[str, str]:
    """⚠️ **Beide Formen.** Die OpenAI-Norm will ``Authorization: Bearer``;
    Anthropic nimmt daneben ``x-api-key`` samt ``anthropic-version``, und
    manche Aufstellungen antworten nur darauf. Beides zu schicken kostet
    nichts und erspart eine Anbieter-Fallunterscheidung im Code.
    """
    kopf = {"content-type": "application/json"}
    if schluessel:
        kopf["authorization"] = f"Bearer {schluessel}"
        kopf["x-api-key"] = schluessel
        kopf["anthropic-version"] = "2023-06-01"
    return kopf


def _antwort_deuten(antwort: httpx.Response) -> None:
    """Aus einem Statuscode eine Kennung machen, die etwas sagt.

    ⚠️ **„Es hat nicht geklappt" schickt den Menschen an die falsche Stelle.**
    401 heißt Schlüssel, 404 heißt Adresse, 429 heißt warten — drei
    verschiedene Handgriffe.
    """
    if antwort.status_code == 200:
        return
    if antwort.status_code in (401, 403):
        raise KiFehler("ki_schluessel_abgewiesen")
    if antwort.status_code == 404:
        raise KiFehler("ki_adresse_nicht_gefunden")
    if antwort.status_code == 429:
        raise KiFehler("ki_zu_viele_anfragen")
    logger.info("The AI service answered %s.", antwort.status_code)
    raise KiFehler("ki_dienst_antwortet_nicht", code=antwort.status_code)


def modelle_holen(
    url: str, schluessel: str, transport: object | None = None
) -> list[dict[str, str]]:
    """Die Modelle, die dieser Zugang hergibt.

    ⚠️ **Das ist zugleich der Verbindungstest.** Kommt die Liste, stimmen
    Adresse und Schlüssel — ein zweiter Knopf daneben prüfte dasselbe noch
    einmal. Dieselbe Überlegung wie bei der Probemail des Postausgangs, nur
    billiger zu haben.

    ⚠️ **Nicht jeder Dienst listet.** Manche Vermittler können ``/models``
    nicht; dann bleibt das Feld von Hand zu füllen. Eine Sackgasse darf das
    nicht sein — deshalb eine eigene Kennung statt „ging nicht".
    """
    url = adresse_pruefen(url)
    ziel = urljoin(url, "models")
    try:
        with httpx.Client(
            timeout=ZEITGRENZE, follow_redirects=True, transport=transport
        ) as klient:
            antwort = klient.get(ziel, headers=_kopfzeilen(schluessel))
    except httpx.HTTPError as fehler:
        logger.info("The AI service was unreachable: %s", type(fehler).__name__)
        raise KiFehler("ki_nicht_erreichbar") from fehler

    if antwort.status_code in (404, 405, 501):
        raise KiFehler("ki_kennt_keine_liste")
    _antwort_deuten(antwort)

    try:
        daten = antwort.json()
    except ValueError as fehler:
        raise KiFehler("ki_antwort_unlesbar") from fehler

    # ⚠️ **Die Form ist bei allen dieselbe**, der Inhalt nicht: OpenAI und
    # Ollama liefern nur ``id``, Anthropic zusaetzlich ``display_name``. Wo es
    # einen lesbaren Namen gibt, wird er gezeigt — sonst die Kennung.
    roh = daten.get("data") if isinstance(daten, dict) else None
    if not isinstance(roh, list):
        raise KiFehler("ki_antwort_unlesbar")

    raus: list[dict[str, str]] = []
    for eintrag in roh[:MAX_MODELLE]:
        if not isinstance(eintrag, dict):
            continue
        kennung = str(eintrag.get("id") or "").strip()
        if not kennung:
            continue
        raus.append(
            {"id": kennung, "name": str(eintrag.get("display_name") or "").strip()}
        )
    if not raus:
        raise KiFehler("ki_keine_modelle")
    logger.info("An AI service listed %s model(s).", len(raus))
    return raus


def einstellung_lesen(person: Benutzer) -> dict:
    """Was die Oberfläche zeigen darf.

    ⚠️ **Der Schlüssel geht nie zurück**, auch nicht dem Eigentümer. Er steht
    nur in der einen Anfrage, die ihn setzt — dieselbe Regel wie beim
    Postfach-Passwort. Gezeigt wird, **dass** einer da ist.
    """
    return {
        "aktiv": person.ki_aktiv,
        "url": person.ki_url,
        "modell": person.ki_modell,
        "schluessel_da": bool(person.ki_schluessel),
    }


def einstellung_schreiben(
    db: Session,
    person: Benutzer,
    *,
    aktiv: bool | None = None,
    url: str | None = None,
    modell: str | None = None,
    schluessel: str | None = None,
) -> dict:
    """Ändern, was mitgeschickt wurde.

    ⚠️ **Nicht mitgeschickt heisst unverändert** — dieselbe Regel wie beim
    Passwort, bei den Schlagworten und bei den Aliassen. Ohne sie verlöre
    jeder seinen Schlüssel, der nur das Modell wechselt. Eine leere
    Zeichenkette heisst dagegen ausdrücklich „weg".
    """
    if url is not None:
        person.ki_url = adresse_pruefen(url) if url.strip() else ""
    if modell is not None:
        person.ki_modell = modell.strip()[:200]
    if schluessel is not None:
        schluessel_schreiben(person, schluessel.strip())
    if aktiv is not None:
        # ⚠️ **Einschalten geht nur mit vollständigem Zugang.** Ein Schalter,
        # der „an" steht und beim ersten Umformulieren scheitert, ist
        # schlimmer als einer, der sich nicht umlegen lässt.
        if aktiv and not (person.ki_url and person.ki_modell):
            raise KiFehler("ki_zugang_unvollstaendig")
        person.ki_aktiv = aktiv

    db.commit()
    logger.info("A user changed their AI service settings (active=%s).", person.ki_aktiv)
    return einstellung_lesen(person)
