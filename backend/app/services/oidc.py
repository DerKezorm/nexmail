"""OpenID Connect: Selbstauskunft, Weiterleitung, Tausch, Pruefung.

Hier steht **nur die Norm** — kein Konto, keine Datenbanklogik. Was mit einer
geprueften Identitaet geschieht, entscheidet ``oidc_konten``.

Der Ablauf (Authorization Code Flow mit PKCE):

1. **Hinweg:** nexmail erzeugt drei Zufallswerte (``state``, ``nonce``,
   PKCE-``verifier``), legt sie in ein kurzlebiges signiertes Cookie und leitet
   zum Anbieter weiter.
2. **Rueckweg:** Der Anbieter schickt den Browser mit einem Einmal-Code
   zurueck. nexmail prueft ``state`` gegen das Cookie, tauscht den Code samt
   ``verifier`` gegen die Ausweise und prueft den ID-Ausweis: Unterschrift
   gegen die veroeffentlichten Schluessel, Aussteller, Empfaenger, Ablauf,
   ``nonce``.

Warum alle drei Werte, obwohl sie sich aehneln: ``state`` verhindert, dass
jemand einem Browser eine **fremde** Antwort unterschiebt. ``nonce``
verhindert, dass ein **abgefangener Ausweis** ein zweites Mal eingeloest wird —
er steht *im* Ausweis, nicht in der Adresse. Der PKCE-``verifier`` verhindert,
dass ein **abgefangener Code** etwas nuetzt.

⚠️ **Uebernommen aus ``nexview/backend/app/services/oidc.py``**, samt der
Fallstricke, die dort teuer gelernt wurden. Jeder davon steht unten an seiner
Stelle. Wer hier etwas vereinfacht, sollte erst den zugehoerigen Absatz lesen.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from ..config import get_settings

logger = logging.getLogger("nexmail.oidc")

#: Unterschrifts-Verfahren, die nexmail annimmt.
#:
#: ⚠️ **HS256 fehlt mit Absicht.** Ein symmetrisch unterschriebener Ausweis
#: wuerde mit dem Client-Geheimnis geprueft — und wer den ``alg``-Kopf umbiegt,
#: koennte sich mit einem selbstgebauten Ausweis anmelden. Das ist der
#: bekannteste JWT-Angriff.
#:
#: ⚠️ **Was hier fehlt, sperrt aus.** Ein Anbieter unterschreibt mit dem
#: Verfahren, das sein Betreiber eingestellt hat; steht es nicht in dieser
#: Liste, scheitert **jede** Anmeldung bei ihm. In nexview fehlten ES512 und
#: EdDSA, obwohl ES256 und ES384 dastanden — Pocket ID laesst beides
#: einstellen.
VERFAHREN = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA"]

#: Zeitgrenze fuer alles, ohne das keine Anmeldung zustande kaeme.
#: Selbstgehostete Anbieter auf kleiner Hardware brauchen ein paar Sekunden.
ZEITGRENZE = 10

#: ⚠️ **Kuerzer als der Rest.** Die Nachfrage bei ``userinfo`` haengt an
#: **jeder** Anmeldung, und ihr Ausbleiben ist verkraftbar — der Rueckfall ist
#: „keine zusaetzliche Auskunft". Der Token-Tausch ist das Gegenteil. Haengen
#: beide an derselben Grenze, verlangsamt ein traeger Endpunkt jede Anmeldung
#: im Haus um zehn Sekunden, fuer eine Auskunft, die vielleicht nie kommt.
NACHFRAGE_ZEITGRENZE = 5

#: ⚠️ **Entra ID mit ``common`` oder ``organizations``.** Dann nennt die
#: Selbstauskunft ``https://login.microsoftonline.com/{tenantid}/v2.0``, mit
#: genau diesem Platzhalter. Der echte Aussteller steht erst im Ausweis, mit
#: der Kennung aus ``tid``. Der Platzhalter selbst gilt **nie** als Aussteller.
#: Gefunden am 09.10.2026 in nexbeat; bis dahin lehnte nexmail Entra mit
#: ``common`` schon bei der Selbstauskunft ab.
MANDANT_PLATZHALTER = "{tenantid}"
_MANDANT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
#: Was bei Entra statt einer Mandanten-Kennung in der eingetragenen Adresse stehen darf.
_SAMMELMANDANTEN = ("common", "organizations", "consumers")

COOKIE_NAME = "nexmail_oidc"
#: Wie lange ein angefangener Lauf gilt. Laenger waere sinnlos: Wer zehn
#: Minuten beim Anbieter steht, faengt ohnehin neu an.
ANLAUF_MINUTEN = 10


class OidcFehler(Exception):
    """Der Anmeldelauf scheitert — mit Kennung zum Anzeigen.

    ``code`` geht als ``oidc_fehler``-Parameter an die Anmeldeseite zurueck,
    die daraus einen Satz in der eingestellten Sprache macht. Der Server
    benennt, er uebersetzt nicht — wie ueberall in nexmail.
    """

    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


@dataclass
class Identitaet:
    """Was am Ende eines Laufs feststeht."""

    #: ⚠️ **Der Aussteller aus dem geprueften Ausweis**, nicht aus der
    #: Selbstauskunft. Bei Entra mit ``common`` steht dort nur der Platzhalter,
    #: und eine Verknuepfung darauf galte fuer jeden Mandanten.
    issuer: str
    subject: str
    adresse: str = ""
    adresse_bestaetigt: bool = False
    anzeigename: str = ""


# --- Der Anlauf: Cookie mit state, nonce und PKCE ------------------------- #


def cookie_pfad() -> str:
    return f"{get_settings().url_base}/api/oidc"


def _schluessel() -> bytes:
    """Zum Signieren des Anlauf-Cookies — aus dem Datenschluessel abgeleitet."""
    from .. import crypto

    return hashlib.sha256(b"oidc-anlauf" + crypto._dek()).digest()


def zustand_schreiben(daten: dict[str, Any]) -> str:
    """Den Anlauf in eine signierte Zeichenkette packen.

    ⚠️ **Signiert, nicht verschluesselt.** Der Inhalt ist nicht geheim — er
    darf nur nicht **veraendert** werden. Wer ``state`` faelschen koennte,
    haette den Schutz ausgehebelt, fuer den es ihn gibt.
    """
    roh = json.dumps({**daten, "ab": int(time.time())}, separators=(",", ":")).encode()
    koerper = base64.urlsafe_b64encode(roh).decode().rstrip("=")
    marke = hmac.new(_schluessel(), koerper.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{koerper}.{marke}"


def zustand_lesen(wert: str | None) -> dict[str, Any] | None:
    """Zurueck — oder ``None``, wenn etwas nicht stimmt."""
    if not wert or "." not in wert:
        return None
    koerper, _, marke = wert.rpartition(".")
    erwartet = hmac.new(_schluessel(), koerper.encode(), hashlib.sha256).hexdigest()[:32]
    # ⚠️ Zeitunabhaengiger Vergleich: Ein einfaches ``==`` verraet ueber die
    # Laufzeit, wie viele Zeichen stimmen.
    if not hmac.compare_digest(marke, erwartet):
        return None
    try:
        fehlt = "=" * (-len(koerper) % 4)
        daten = json.loads(base64.urlsafe_b64decode(koerper + fehlt))
    except (ValueError, TypeError):
        return None
    if not isinstance(daten, dict):
        return None
    if int(time.time()) - int(daten.get("ab", 0)) > ANLAUF_MINUTEN * 60:
        return None
    return daten


def anlauf_erzeugen(
    kuerzel: str, absicht: str, benutzer_id: str = "", *, einladung_id: str = ""
) -> dict[str, str]:
    """Die drei Zufallswerte plus PKCE-Praegewert.

    ⚠️ **Beim Verknuepfen gehoert die Benutzerkennung hier hinein**, nicht in
    die Sitzung. Das Sitzungs-Cookie steht auf ``SameSite=strict`` und faehrt
    bei der Rueckkehr vom Anbieter **nicht** mit — der Rueckweg ist eine
    Navigation von fremder Seite. Wer sie beim Rueckweg aus der Sitzung holt,
    bekommt ``None``, und das Verknuepfen scheitert jedes Mal mit
    „the session is gone; nothing was linked".

    Genau so war es bis zum 01.09.2026: Der Knopf im Profil sah aus, als taete
    er etwas, und tat nie etwas. Aufgefallen erst, als der Pruefstand ihn zum
    ersten Mal an einem echten Keycloak durchspielte.

    ⚠️ **Das ist sicher, weil dieser Zustand signiert ist.** Er entsteht im
    Hinweg, wo die Sitzung noch da war, und laesst sich unterwegs nicht
    umschreiben. Das Anlauf-Cookie ist ``SameSite=lax`` — deshalb kommt es
    zurueck, waehrend das Sitzungs-Cookie draussen bleibt.

    ⚠️ **Beim Annehmen einer Einladung faehrt deren Kennung mit**, aus
    demselben Grund signiert: Wer sie unterwegs gegen eine andere tauschen
    koennte, loeste eine Einladung ein, deren Schluessel er nie hatte.
    """
    verifier = secrets.token_urlsafe(64)
    praege = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return {
        "kuerzel": kuerzel,
        "absicht": absicht,
        "benutzer_id": benutzer_id,
        "einladung_id": einladung_id,
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": verifier,
        "praege": praege,
    }


# --- Reden mit dem Anbieter ----------------------------------------------- #


def _inhaltstyp(antwort: httpx.Response) -> str:
    return (antwort.headers.get("content-type") or "").split(";")[0].strip()


def _json_deuten(antwort: httpx.Response, zweck: str, adresse: str) -> dict[str, Any]:
    """Den Rumpf als JSON deuten — oder mit dem echten Grund scheitern.

    ⚠️ **Der haeufigste Fall ist nicht kaputtes JSON, sondern gar keines.** Ein
    Reverse Proxy vor dem Anbieter, ein Pfad-Vertipper, eine Anmeldeseite
    davor: Zurueck kommt HTML, oft mit Status 200. Deshalb nennt das Protokoll
    den **Inhaltstyp** — ``text/html`` sagt in einem Wort, dass man beim Proxy
    nachsehen muss und nicht bei der Client-ID.

    ⚠️ Der Rumpf selbst steht **nicht** im Protokoll. Bei der Token-Antwort
    stuenden dort Ausweise, und ein Protokoll wandert in Fehlerberichte.
    """
    try:
        daten = antwort.json()
    except ValueError:
        logger.warning(
            "OIDC: the %s at %r is not JSON (content-type %s, %d bytes)",
            zweck, adresse, _inhaltstyp(antwort) or "none", len(antwort.content),
        )
        raise OidcFehler(
            "oidc_kein_json",
            f"The provider returned no JSON for {zweck} "
            f"({_inhaltstyp(antwort) or 'no content type'}); usually a proxy or "
            "an error page sits in front of it.",
        ) from None
    if not isinstance(daten, dict):
        raise OidcFehler("oidc_kein_json", f"The provider returned no object for {zweck}.")
    return daten


def _oauth_fehler(antwort: httpx.Response) -> str:
    """Warum der Anbieter abgelehnt hat — in einer Zeile fuers Protokoll.

    ⚠️ **Das ist die wertvollste Diagnose im ganzen Ablauf.** OAuth 2 schreibt
    ``error`` vor und empfiehlt ``error_description``; darin steht
    ``invalid_client`` oder ``invalid_grant`` statt „irgendwas mit 400", und
    der Text nennt oft genau das falsche Feld. Wer beides wegwirft, laesst den
    Betreiber raten.
    """
    try:
        daten = antwort.json()
    except ValueError:
        return (
            f"kein JSON ({_inhaltstyp(antwort) or 'ohne Typ'}, {len(antwort.content)} Bytes) — "
            "das ist meist ein Proxy oder eine Fehlerseite vor dem Anbieter"
        )
    if not isinstance(daten, dict):
        return "ein JSON-Rumpf, der kein Objekt ist"
    kennung = str(daten.get("error") or "").strip()
    erklaerung = str(daten.get("error_description") or "").strip()
    if not kennung and not erklaerung:
        return f"ein JSON-Rumpf ohne ``error`` (enthaelt: {', '.join(sorted(daten)) or 'nichts'})"
    if not erklaerung:
        return (
            f"error={kennung} — invalid_client zeigt auf Client-ID oder Geheimnis, "
            "invalid_grant auf den Code oder eine Rueckkehr-Adresse, die der "
            "Anbieter nicht kennt"
        )
    # ⚠️ ``!r``, nicht roh: Manche Anbieter legen einen Stacktrace in die
    # Beschreibung, und der zerrisse die Protokollzeile in mehrere.
    return f"error={kennung or 'none'} error_description={erklaerung[:300]!r}"


async def beschreibung_holen(issuer: str) -> dict[str, Any]:
    """Die Selbstauskunft des Anbieters.

    ⚠️ **Das ``issuer`` im Dokument muss der angefragten Adresse entsprechen.**
    Sonst koennte ein Anbieter Ausweise im Namen eines anderen ausstellen.
    """
    adresse = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=ZEITGRENZE, follow_redirects=True) as klient:
            antwort = await klient.get(adresse)
            antwort.raise_for_status()
    except Exception as fehler:  # noqa: BLE001
        # ⚠️ Absichtlich jede Ausnahme: ``httpx.InvalidURL`` erbt direkt von
        # ``Exception``, nicht von ``httpx.HTTPError`` — eine verhunzte Adresse
        # ginge an einem engeren Faenger vorbei.
        logger.warning("OIDC: provider description at %r could not be read: %r", adresse, fehler)
        raise OidcFehler(
            "oidc_kein_anbieter",
            f"The discovery document at {adresse} is unreachable.",
        ) from fehler

    daten = _json_deuten(antwort, "der Selbstauskunft", adresse)
    gemeldet = str(daten.get("issuer") or "")
    if not aussteller_passt_zur_vorlage(issuer, gemeldet):
        raise OidcFehler(
            "oidc_falscher_aussteller",
            f"The provider calls itself {gemeldet!r}, but {issuer!r} is configured. "
            "The two have to match.",
        )
    return daten


def aussteller_passt_zur_vorlage(eingetragen: str, gemeldet: str) -> bool:
    """Ob die Selbstauskunft zur eingetragenen Adresse gehoert.

    Gleich (ohne abschliessenden Schraegstrich), oder: Die Selbstauskunft
    traegt den Entra-Platzhalter ``{tenantid}``, und an seiner Stelle steht in
    der eingetragenen Adresse ``common``, ``organizations``, ``consumers`` oder
    eine Mandanten-Kennung. Alles andere muss Zeichen fuer Zeichen stimmen.
    """
    eingetragen, gemeldet = eingetragen.rstrip("/"), gemeldet.rstrip("/")
    if not gemeldet:
        return False
    if eingetragen == gemeldet:
        return True
    if gemeldet.count(MANDANT_PLATZHALTER) != 1:
        return False
    vorne, _, hinten = gemeldet.partition(MANDANT_PLATZHALTER)
    if not (eingetragen.startswith(vorne) and eingetragen.endswith(hinten)):
        return False
    mitte = eingetragen[len(vorne) : len(eingetragen) - len(hinten)]
    return mitte in _SAMMELMANDANTEN or bool(_MANDANT.fullmatch(mitte))


def zugelassene_aussteller(beschreibung: dict[str, Any], ausweis: dict[str, Any]) -> set[str]:
    """Wer diesen Ausweis ausgestellt haben darf.

    Der Aussteller der Selbstauskunft, Zeichen fuer Zeichen. Traegt er den
    Entra-Platzhalter, wird die Kennung aus ``tid`` desselben, schon
    unterschriebenen Ausweises eingesetzt. Welche Mandanten hineinduerfen,
    regelt dort die App-Registrierung (ein Mandant oder mehrere); nexmail
    laesst ohnehin nur herein, wer verknuepft oder eingeladen ist.
    """
    gemeldet = str(beschreibung.get("issuer") or "")
    if MANDANT_PLATZHALTER not in gemeldet:
        return {gemeldet} if gemeldet else set()
    mandant = str(ausweis.get("tid") or "")
    if not _MANDANT.fullmatch(mandant):
        return set()
    return {gemeldet.replace(MANDANT_PLATZHALTER, mandant)}


def gehoert_zum_anbieter(anbieter_issuer: str, verknuepft_issuer: str) -> bool:
    """Ob eine Verknuepfung zu einem eingetragenen Anbieter gehoert.

    Fuer die Anzeige im Profil. Gleich ohne Schraegstrich, oder Entra: Der
    Anbieter steht mit ``common`` (oder ``organizations``, ``consumers``) da,
    die Verknuepfung traegt den echten Mandanten an derselben Stelle.
    """
    a, v = anbieter_issuer.rstrip("/"), verknuepft_issuer.rstrip("/")
    if a == v:
        return True
    teile_a, teile_v = a.split("/"), v.split("/")
    if len(teile_a) != len(teile_v):
        return False
    anders = [i for i, (x, y) in enumerate(zip(teile_a, teile_v)) if x != y]
    return (
        len(anders) == 1
        and teile_a[anders[0]] in _SAMMELMANDANTEN
        and bool(_MANDANT.fullmatch(teile_v[anders[0]]))
    )


async def code_tauschen(
    beschreibung: dict[str, Any],
    *,
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    rueckkehr: str,
) -> tuple[str, str | None]:
    """Den Einmal-Code gegen die Ausweise tauschen."""
    adresse = str(beschreibung.get("token_endpoint") or "")
    if not adresse:
        raise OidcFehler("oidc_kein_token_endpunkt", "The provider names no token endpoint.")

    daten = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": rueckkehr,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:
        daten["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(timeout=ZEITGRENZE) as klient:
            antwort = await klient.post(
                adresse,
                data=daten,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
    except Exception as fehler:  # noqa: BLE001
        logger.warning("OIDC: token endpoint at %r not reachable: %r", adresse, fehler)
        raise OidcFehler("oidc_tausch", f"The token endpoint {adresse} is unreachable.") from fehler

    if antwort.status_code >= 400:
        logger.warning("OIDC: token exchange refused: %s", _oauth_fehler(antwort))
        raise OidcFehler(
            "oidc_tausch",
            "The provider refused the exchange; the reason is in the log above. "
            "Usually the client id, the secret or the redirect URI.",
        )

    rumpf = _json_deuten(antwort, "der Token-Antwort", adresse)
    id_token = rumpf.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        # ⚠️ **Steht dort nur ``access_token``, war es kein OIDC-Lauf.** Meist
        # fehlt der Bereich ``openid`` — der Anbieter hat dann brav OAuth 2
        # gemacht und keinen Ausweis ausgestellt.
        raise OidcFehler(
            "oidc_kein_ausweis",
            "The provider returned no ID token. Usually the 'openid' scope is "
            "missing.",
        )
    zugang = rumpf.get("access_token")
    return id_token, zugang if isinstance(zugang, str) and zugang else None


def _symmetrisch_benennen(id_token: str, fehler: Exception) -> None:
    """Einen mit dem Client-Geheimnis unterschriebenen Ausweis beim Namen nennen.

    ⚠️ **authentik ohne gewaehlten Signierschluessel** unterschreibt mit HS256
    und veroeffentlicht eine leere Schluesselliste (nexdeck, Issue #11). Ohne
    diesen Satz hiesse das nur „Schluessel nicht lesbar", und man sucht am
    Netz statt am Provider. Angenommen wird der Ausweis trotzdem nie: Das
    entscheidet ``VERFAHREN``, hier wird nur die Meldung genauer.
    """
    try:
        verfahren = str(jwt.get_unverified_header(id_token).get("alg") or "")
    except Exception:  # noqa: BLE001
        return
    if verfahren.upper().startswith("HS"):
        raise OidcFehler(
            "oidc_ausweis_hs256",
            f"The ID token is signed with {verfahren}, that is with the client secret. "
            "Choose a signing key at the provider; in authentik that is 'Signing Key'.",
        ) from fehler


async def ausweis_pruefen(
    beschreibung: dict[str, Any], id_token: str, *, client_id: str, nonce: str
) -> dict[str, Any]:
    """Unterschrift, Aussteller, Empfaenger, Ablauf und ``nonce``."""
    jwks = str(beschreibung.get("jwks_uri") or "")
    if not jwks:
        raise OidcFehler("oidc_keine_schluessel", "The provider names no JWKS URI.")

    try:
        klient = jwt.PyJWKClient(jwks, timeout=ZEITGRENZE)
        # ⚠️ **In einem eigenen Faden.** PyJWKClient holt mit urllib, also
        # blockierend; im Hauptfaden stuende der ganze Server still, solange
        # der Anbieter braucht.
        schluessel = await asyncio.to_thread(klient.get_signing_key_from_jwt, id_token)
        # ⚠️ **Den Aussteller prueft nexmail unten selbst**, wegen Entra. Das
        # ``options``-Woerterbuch entsteht bei jedem Aufruf neu: PyJWT
        # veraendert es an Ort und Stelle (GHSA-gvp8-978c-rx2q), und ein
        # geteiltes naehme Pruefungen von einem Aufruf in den naechsten mit.
        daten = jwt.decode(
            id_token,
            schluessel.key,
            algorithms=VERFAHREN,
            audience=client_id,
            options={"require": ["exp", "iat", "sub", "iss"], "verify_iss": False},
        )
    except jwt.InvalidTokenError as fehler:
        logger.warning("OIDC: the id_token could not be verified: %r", fehler)
        _symmetrisch_benennen(id_token, fehler)
        raise OidcFehler(
            "oidc_ausweis", "The provider's ID token could not be verified."
        ) from fehler
    except Exception as fehler:  # noqa: BLE001
        logger.warning("OIDC: keys at %r could not be read: %r", jwks, fehler)
        _symmetrisch_benennen(id_token, fehler)
        raise OidcFehler("oidc_keine_schluessel", "The provider's keys could not be read.") from fehler

    # ⚠️ **Beim Aussteller die beiden Werte nennen.** „Invalid issuer" allein
    # laesst einen raten, und die haeufigste Ursache ist eine Kleinigkeit:
    # authentik schreibt je nach Einstellung entweder die Adresse der Anwendung
    # oder die des Servers in den Ausweis, und wer zwei Anwendungen hat, traegt
    # leicht die Kennung der einen mit der Adresse der anderen ein. Am
    # 01.09.2026 genau dort haengengeblieben.
    gefunden = str(daten.get("iss") or "")
    if gefunden not in zugelassene_aussteller(beschreibung, daten):
        erwartet = str(beschreibung.get("issuer") or "")
        logger.warning(
            "OIDC: issuer mismatch - the token says %r, the discovery document says %r",
            gefunden,
            erwartet,
        )
        raise OidcFehler(
            "oidc_ausweis",
            f"The ID token names {gefunden!r} as issuer, the discovery document "
            f"{erwartet!r}. The two have to match; with authentik the "
            "provider setting 'Issuer mode' decides this.",
        )

    # ⚠️ **Mehrere Empfaenger verlangen ``azp``** (OIDC Core 3.1.3.7) — und die
    # Pruefung gilt, **sobald** ``azp`` dasteht, nicht erst bei mehreren.
    azp = daten.get("azp")
    if azp is not None and azp != client_id:
        raise OidcFehler("oidc_ausweis", "The ID token was issued for a different application.")

    if daten.get("nonce") != nonce:
        # ⚠️ Ohne diese Pruefung liesse sich ein abgefangener Ausweis ein
        # zweites Mal einloesen.
        raise OidcFehler("oidc_ausweis", "The ID token does not belong to this sign-in attempt.")
    return daten


async def nachfragen(
    beschreibung: dict[str, Any], zugang: str, subject: str
) -> dict[str, Any]:
    """``userinfo`` — was der Anbieter sonst noch ueber diese Person sagt.

    ⚠️ **Ohne das ist nexmail bei mehreren Anbietern blind.** Nach OIDC Core
    ist im ID-Ausweis allein ``sub`` zugesichert. **Authelia** legt ``email``
    gar nicht hinein; **Zitadel** liefert sie nur bei einem anderen Ablauf. Bei
    beiden kaeme nie eine Adresse an.

    ⚠️ **Das ``sub`` entscheidet.** Antwortet ``userinfo`` mit einer anderen
    Kennung als der Ausweis, wird die Antwort **verworfen** — die Norm verlangt
    das (Core 5.3.2), und ohne die Pruefung liesse sich einer beglaubigten
    Anmeldung die Adresse einer fremden anhaengen.

    ⚠️ **Ein Fehlschlag darf nichts kaputtmachen.** Wer heute ohne diesen
    Aufruf hereinkommt, muss es auch morgen — der Rueckfall ist „keine
    zusaetzliche Auskunft", nicht ein gescheiterter Lauf.
    """
    adresse = beschreibung.get("userinfo_endpoint")
    if not isinstance(adresse, str) or not adresse:
        # ⚠️ Nicht stumm zurueckkehren: Sonst sieht der Betreiber nur die
        # Abweisung mit „keine Adresse" und sucht bei den Scopes — waehrend die
        # Selbstauskunft den Endpunkt gar nicht nennt. ADFS kennt ihn nicht.
        logger.info("OIDC: the provider names no userinfo endpoint - not asking")
        return {}

    try:
        async with httpx.AsyncClient(timeout=NACHFRAGE_ZEITGRENZE) as klient:
            antwort = await klient.get(adresse, headers={"Authorization": f"Bearer {zugang}"})
            antwort.raise_for_status()
            daten = antwort.json()
    except Exception as fehler:  # noqa: BLE001 - Absicht, siehe oben
        # ⚠️ **Absichtlich jede Ausnahme, nicht eine Liste von Namen.** In
        # nexview stand hier ``httpx.HTTPError``, und genau daran ging
        # ``httpx.InvalidURL`` vorbei — eine verhunzte Adresse in der
        # Selbstauskunft haette eine Anmeldung umgerissen, die ohne diese
        # Nachfrage funktioniert haette. ``%r`` nennt den Typ mit; ohne das
        # bezahlt man den groben Faenger, ohne den Gegenwert zu bekommen.
        logger.warning("OIDC: userinfo at %r could not be read: %r", adresse, fehler)
        return {}

    if not isinstance(daten, dict) or daten.get("sub") != subject:
        logger.warning("OIDC: userinfo answered for a different subject - discarded")
        return {}
    return daten


def identitaet_bauen(ausweis: dict[str, Any], auskunft: dict[str, Any], issuer: str) -> Identitaet:
    """Ausweis und Nachfrage zu einer Identitaet zusammenlegen.

    ⚠️ **Der Ausweis behaelt das letzte Wort.** Er ist unterschrieben und
    geprueft; die Nachfrage fuellt nur, was er nicht sagt.

    ⚠️ **Die Bestaetigung muss zu DIESER Adresse gehoeren.** Ein ``email``
    aus der Nachfrage mit einem ``email_verified`` aus dem Ausweis waere ein
    Freibrief: Wer sich bei einem Anbieter eine fremde Adresse eintraegt,
    uebernaehme darueber ein fremdes nexmail-Konto.
    """
    adresse = str(ausweis.get("email") or "")
    bestaetigt = bool(ausweis.get("email_verified")) if adresse else False
    if not adresse:
        adresse = str(auskunft.get("email") or "")
        bestaetigt = bool(auskunft.get("email_verified")) if adresse else False

    name = str(ausweis.get("name") or auskunft.get("name") or "")
    return Identitaet(
        issuer=issuer,
        subject=str(ausweis.get("sub") or ""),
        adresse=adresse.strip().lower(),
        adresse_bestaetigt=bestaetigt,
        anzeigename=name.strip(),
    )


def weiterleitung_bauen(
    beschreibung: dict[str, Any], *, client_id: str, scopes: str, rueckkehr: str, anlauf: dict
) -> str:
    ziel = str(beschreibung.get("authorization_endpoint") or "")
    if not ziel:
        raise OidcFehler("oidc_kein_anmeldeendpunkt", "The provider names no authorization endpoint.")
    bereiche = " ".join(dict.fromkeys(["openid", *scopes.split()]))
    frage = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": rueckkehr,
            "scope": bereiche,
            "state": anlauf["state"],
            "nonce": anlauf["nonce"],
            "code_challenge": anlauf["praege"],
            "code_challenge_method": "S256",
        }
    )
    return f"{ziel}{'&' if '?' in ziel else '?'}{frage}"
