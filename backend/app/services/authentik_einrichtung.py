"""Der authentik-Knopf: nexmail legt seinen eigenen Anbieter in authentik an.

Der Betreiber gibt die Adresse von authentik und ein Einmal-Token. nexmail
erledigt dann ueber die API v3, was man sonst in einem Dutzend Formulare
zusammenklickt: einen Signierschluessel, den Provider, die Anwendung und
zuletzt den eigenen Anmelde-Anbieter. Jeder Schritt meldet, ob er geklappt hat
und, wenn nicht, woran es lag. Der erste Fehlschlag haelt an; was davor
entstand, bleibt stehen, und ein zweiter Druck aktualisiert statt zu
verdoppeln.

⚠️ **Das Token wird nur fuer diese Aufrufe benutzt.** Es wird nie gespeichert
und nie protokolliert. Eine Meldung nennt den HTTP-Status, nie das Token und
nie den Rumpf der Antwort: Die Adresse tippt ein Betreiber ein, sie kann auf
jeden Dienst im Netz zeigen, und dessen Antwort hat im Browser nichts zu
suchen.

Der Blueprint ist der Weg fuer alle, die kein Token aus der Hand geben wollen:
eine YAML-Datei fuer authentiks Blueprint-Import, die dieselben Dinge anlegt,
mit dem mitgelieferten selbst unterschriebenen Zertifikat als Schluessel, weil
ein Blueprint keinen erzeugen kann.

Uebernommen aus nexbeat (09.10.2026), das es aus nexdeck hat. Geschrieben gegen
die authentik-API von 2024.x bis 2026.x.

⚠️ **Seit 2026.8 hat ein Provider ``grant_types``**, und der Anmelde-Endpunkt
lehnt jede Anfrage ab, deren Ablauf dort nicht steht. Ein ueber die API
angelegter Provider ohne das Feld hat eine leere Liste, also nennt der Knopf
den einen Ablauf, den nexmail benutzt. Aeltere Fassungen uebergehen das Feld.

⚠️ **Anders als in nexbeat ohne eigene Zuordnung fuer ``email_verified``.**
nexmail ordnet nie ueber eine Adresse zu, auch Einladungen nicht mehr (siehe
``oidc_konten``). authentiks eigene Zuordnung fuer ``email`` genuegt; eine,
die fuer jede Adresse buergt, waere hier eine Zusage ohne Nutzen.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..models import OidcAnbieter, neue_id
from . import oidc

logger = logging.getLogger("nexmail.authentik")

NAME = "nexmail"
SLUG = "nexmail"
#: Das Kuerzel des Anbieters in nexmail. Es steckt in der Rueckkehr-Adresse,
#: ist also fest: Dem Provider in authentik wird genau diese Adresse genannt.
KUERZEL = "authentik"
ANZEIGENAME = "authentik"
#: authentiks eigene Zuordnungen fuer openid, email und profile, gefunden am
#: verwalteten Namen.
VERWALTETE_ZUORDNUNGEN = (
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-email",
    "goauthentik.io/providers/oauth2/scope-profile",
)
#: nexmail benutzt den Authorization Code Flow und sonst nichts.
ABLAEUFE = ("authorization_code",)
BEVORZUGTER_ANMELDEFLUSS = "default-provider-authorization-implicit-consent"
BEVORZUGTER_ABMELDEFLUSS = "default-provider-invalidation-flow"
ZERTIFIKAT_TAGE = 3650
ZEITGRENZE = httpx.Timeout(15.0, connect=5.0)

SCHRITTE = ("erreicht", "schluessel", "zuordnungen", "provider", "anwendung", "eingetragen")

#: Tests setzen hier einen ``httpx.MockTransport``.
transport_fuer_tests: httpx.AsyncBaseTransport | None = None


class SchrittAbbruch(Exception):
    """Ein Schritt ist gescheitert, mit dem technischen Grund.

    ⚠️ **Der Grund ist englisch und wird nicht uebersetzt**, und das ist
    entschieden, nicht vergessen: Er nennt Pfade der authentik-API und
    HTTP-Status, eine Zeile wie im Protokoll, und gehoert dem Betreiber, der
    ihn bei authentik nachschlaegt. Uebersetzt wird der Name des Schritts
    (``SCHRITTE``), daneben steht dieser Satz. Dieselbe Abwaegung wie bei
    ``OidcFehler``; deshalb heisst die Klasse nicht ``…Fehler`` und faellt
    nicht unter ``test_meldungen``.
    """

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


@dataclass
class Schritt:
    kennung: str
    ok: bool
    text: str = ""


@dataclass
class Ergebnis:
    schritte: list[Schritt] = field(default_factory=list)
    client_id: str = ""
    issuer: str = ""

    @property
    def ok(self) -> bool:
        return len(self.schritte) == len(SCHRITTE) and all(s.ok for s in self.schritte)

    def als_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schritte": [{"kennung": s.kennung, "ok": s.ok, "text": s.text} for s in self.schritte],
            "client_id": self.client_id,
            "issuer": self.issuer,
        }


class _Api:
    """Die paar Aufrufe, die nexmail braucht; das Token steht im Kopf und sonst nirgends."""

    def __init__(self, basis: str, token: str) -> None:
        self.basis = basis.rstrip("/")
        extra: dict[str, Any] = (
            {"transport": transport_fuer_tests} if transport_fuer_tests is not None else {}
        )
        # Ein eigener Klient je Lauf: Das Token steht im Kopf und soll mit dem
        # Lauf verschwinden.
        self._klient = httpx.AsyncClient(
            timeout=ZEITGRENZE,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            **extra,
        )

    async def schliessen(self) -> None:
        await self._klient.aclose()

    async def rufen(
        self, methode: str, pfad: str, *, frage: dict[str, str] | None = None, rumpf: Any = None
    ) -> Any:
        adresse = f"{self.basis}/api/v3{pfad}"
        try:
            antwort = await self._klient.request(methode, adresse, params=frage, json=rumpf)
        except httpx.HTTPError as fehler:
            art = fehler.__class__.__name__
            raise SchrittAbbruch(
                f"{methode} {pfad}: authentik at {self.basis} not reachable ({art})"
            ) from fehler
        except Exception as fehler:  # noqa: BLE001
            # ``httpx.InvalidURL`` ist kein HTTPError; die Adresse kommt vom Betreiber.
            art = fehler.__class__.__name__
            raise SchrittAbbruch(
                f"{methode} {pfad}: the address {self.basis!r} cannot be used ({art})"
            ) from fehler
        if not antwort.is_success:
            art = antwort.headers.get("content-type", "").split(";")[0].strip() or "no content type"
            hinweis = " (the token may not do this)" if antwort.status_code in (401, 403) else ""
            raise SchrittAbbruch(f"{methode} {pfad} answered {antwort.status_code} ({art}){hinweis}")
        if not antwort.content:
            return None
        try:
            return antwort.json()
        except ValueError as fehler:
            raise SchrittAbbruch(
                f"{methode} {pfad} answered {antwort.status_code} without JSON"
            ) from fehler

    async def einer(self, pfad: str, frage: dict[str, str], feld: str, wert: str) -> dict | None:
        """Der eine Listeneintrag, dessen ``feld`` genau ``wert`` ist.

        ⚠️ **Der Filter der Adresse allein genuegt nicht.** Ein lockerer Filter
        oder ein uebergangener Parameter gaebe einen Fremden zurueck; der
        genaue Vergleich hier verhindert das.
        """
        daten = await self.rufen("GET", pfad, frage=frage)
        eintraege = daten.get("results", []) if isinstance(daten, dict) else []
        for eintrag in eintraege:
            if isinstance(eintrag, dict) and str(eintrag.get(feld) or "") == wert:
                return eintrag
        return None


def _pk(eintrag: dict[str, Any], was: str) -> Any:
    pk = eintrag.get("pk")
    if pk in (None, ""):
        raise SchrittAbbruch(f"{was} has no pk in authentik's answer")
    return pk


async def _erreicht(api: _Api) -> str:
    daten = await api.rufen("GET", "/admin/version/")
    fassung = str((daten or {}).get("version_current") or "") if isinstance(daten, dict) else ""
    return f"authentik {fassung}" if fassung else "authentik reached, version unknown"


async def _schluessel(api: _Api) -> tuple[Any, str]:
    vorhanden = await api.einer("/crypto/certificatekeypairs/", {"name": NAME}, "name", NAME)
    if vorhanden is not None:
        return _pk(vorhanden, "certificate"), f"using the existing certificate {NAME!r}"
    neu = await api.rufen(
        "POST",
        "/crypto/certificatekeypairs/generate/",
        rumpf={"common_name": NAME, "subject_alt_name": "", "validity_days": ZERTIFIKAT_TAGE, "alg": "rsa"},
    )
    if not isinstance(neu, dict):
        raise SchrittAbbruch("certificate generation answered without an object")
    return _pk(neu, "certificate"), f"generated the certificate {NAME!r} ({ZERTIFIKAT_TAGE} days)"


async def _zuordnungen(api: _Api) -> tuple[list[Any], str]:
    pfad = "/propertymappings/provider/scope/"
    kennungen = []
    for verwaltet in VERWALTETE_ZUORDNUNGEN:
        eintrag = await api.einer(pfad, {"managed": verwaltet}, "managed", verwaltet)
        if eintrag is None:
            raise SchrittAbbruch(f"authentik's default scope mapping {verwaltet!r} was not found")
        kennungen.append(_pk(eintrag, "scope mapping"))
    return kennungen, "using authentik's mappings for openid, email and profile"


async def _fluss(api: _Api, zweck: str, bevorzugt: str) -> Any:
    daten = await api.rufen("GET", "/flows/instances/", frage={"designation": zweck})
    eintraege = [e for e in (daten.get("results", []) if isinstance(daten, dict) else []) if isinstance(e, dict)]
    if not eintraege:
        raise SchrittAbbruch(f"no flow with designation {zweck!r} in authentik")
    for eintrag in eintraege:
        if eintrag.get("slug") == bevorzugt:
            return _pk(eintrag, "flow")
    return _pk(eintraege[0], "flow")


def _namen_der_instanz(rueckkehr: str) -> tuple[str, str]:
    """Name und Kuerzel dieser Installation, wenn ein anderes nexmail die schlichten schon hat."""
    rechner = urlsplit(rueckkehr).netloc.lower()
    anhang = re.sub(r"[^a-z0-9]+", "-", rechner).strip("-")[:40] or "instance"
    return f"{NAME} ({rechner})", f"{SLUG}-{anhang}"


async def _namen(api: _Api, rueckkehr: str) -> tuple[str, str]:
    """Die schlichten Namen, ausser ein Provider dieses Namens schickt woandershin zurueck.

    ⚠️ **Dann arbeitet hier ein zweites nexmail** (ein Teststand etwa), und
    die schlichten Namen zu nehmen braeche dem ersten die Anmeldung.
    """
    vorhanden = await api.einer("/providers/oauth2/", {"name": NAME}, "name", NAME)
    if vorhanden is None:
        return NAME, SLUG
    adressen = {
        str(e.get("url", "")) for e in vorhanden.get("redirect_uris") or [] if isinstance(e, dict)
    }
    if not adressen or rueckkehr in adressen:
        return NAME, SLUG
    return _namen_der_instanz(rueckkehr)


async def _provider(
    api: _Api, rueckkehr: str, schluessel: Any, zuordnungen: list[Any], name: str
) -> tuple[Any, str, str, str]:
    anmelden = await _fluss(api, "authorization", BEVORZUGTER_ANMELDEFLUSS)
    abmelden = await _fluss(api, "invalidation", BEVORZUGTER_ABMELDEFLUSS)
    rumpf = {
        "name": name,
        "authorization_flow": anmelden,
        "invalidation_flow": abmelden,
        "client_type": "confidential",
        "grant_types": list(ABLAEUFE),
        "redirect_uris": [{"matching_mode": "strict", "url": rueckkehr}],
        # ⚠️ **Ohne Signierschluessel unterschreibt authentik mit HS256** und
        # dem Client-Geheimnis, und nexmail nimmt das nie an.
        "signing_key": schluessel,
        "sub_mode": "user_uuid",
        "property_mappings": zuordnungen,
        "include_claims_in_id_token": True,
    }
    vorhanden = await api.einer("/providers/oauth2/", {"name": name}, "name", name)
    if vorhanden is None:
        antwort = await api.rufen("POST", "/providers/oauth2/", rumpf=rumpf)
        text = f"created the provider {name!r}"
    else:
        antwort = await api.rufen("PATCH", f"/providers/oauth2/{_pk(vorhanden, 'provider')}/", rumpf=rumpf)
        text = f"updated the existing provider {name!r}"
    if not isinstance(antwort, dict):
        raise SchrittAbbruch("the provider call answered without an object")
    client_id = str(antwort.get("client_id") or "")
    geheimnis = str(antwort.get("client_secret") or "")
    if not client_id or not geheimnis:
        raise SchrittAbbruch("authentik's provider answer carries no client_id or client_secret")
    return _pk(antwort, "provider"), client_id, geheimnis, text


async def _anwendung(api: _Api, provider_pk: Any, name: str, slug: str) -> str:
    rumpf = {"name": name, "slug": slug, "provider": provider_pk}
    vorhanden = await api.einer("/core/applications/", {"slug": slug}, "slug", slug)
    if vorhanden is None:
        await api.rufen("POST", "/core/applications/", rumpf=rumpf)
        return f"created the application {slug!r}"
    await api.rufen("PATCH", f"/core/applications/{slug}/", rumpf=rumpf)
    return f"updated the existing application {slug!r}"


def issuer_fuer(basis: str, slug: str = SLUG) -> str:
    return f"{basis.rstrip('/')}/application/o/{slug}/"


def _kontext(anbieter_id: str) -> str:
    # ⚠️ Derselbe Kontext wie in ``routers/oidc._kontext``, sonst liest der
    # Rueckweg das Geheimnis nicht.
    return f"oidc:{anbieter_id}:geheimnis"


async def _eintragen(db: Session, issuer: str, client_id: str, geheimnis: str) -> str:
    """nexmails eigenen Anbieter speichern, dann den Aussteller mit einer Selbstauskunft bestaetigen.

    Zuerst gespeichert: Die Werte hat authentik gerade ausgegeben, und eine
    gescheiterte Selbstauskunft heisst meist, dass nexmail authentik unter
    dieser Adresse nicht erreicht; das wird am Netz oder mit einer anderen
    Adresse behoben.

    ⚠️ **Ein neuer Anbieter legt keine Konten an.** Wer sich darueber
    anmeldet, kommt in das Konto, das er unter Sicherheit verknuepft hat, oder
    nimmt ueber die Einladungsseite eine Einladung an. Sonst nirgends hin.

    ⚠️ **Ein geaenderter Aussteller nimmt die alten Verknuepfungen nicht
    mit.** Sie haengen am Aussteller, und ein ``sub`` gilt nur bei dem, der es
    vergeben hat; die alten fuehren danach ins Leere, statt zufaellig in ein
    fremdes Konto.
    """
    issuer = issuer.rstrip("/")
    anbieter = db.execute(
        select(OidcAnbieter).where(OidcAnbieter.kuerzel == KUERZEL)
    ).scalar_one_or_none()
    if anbieter is None:
        anbieter = OidcAnbieter(
            id=neue_id(),
            kuerzel=KUERZEL,
            anzeigename=ANZEIGENAME,
            issuer=issuer,
            client_id=client_id,
            scopes="openid email profile",
            aktiv=True,
        )
        text = f"added the sign-in provider {KUERZEL!r}"
    else:
        anbieter.issuer = issuer
        anbieter.client_id = client_id
        anbieter.aktiv = True
        text = f"updated the sign-in provider {KUERZEL!r}"
    # ⚠️ Erst die Kennung, dann verschluesseln: Sie faehrt als Zusatzdaten mit.
    anbieter.client_secret = crypto.verschluesseln(geheimnis, _kontext(anbieter.id))
    db.add(anbieter)
    db.commit()
    try:
        await oidc.beschreibung_holen(issuer)
    except oidc.OidcFehler as fehler:
        raise SchrittAbbruch(f"{text}, but the discovery at {issuer} failed: {fehler.text}") from fehler
    return f"{text}; discovery at {issuer} confirmed"


async def einrichten(db: Session, basis: str, token: str, rueckkehr: str) -> Ergebnis:
    """Der ganze Lauf, Schritt fuer Schritt. Haelt beim ersten Fehlschlag an."""
    ergebnis = Ergebnis(issuer=issuer_fuer(basis))
    api = _Api(basis, token)
    schluessel: Any = None
    zuordnungen: list[Any] = []
    provider_pk: Any = None
    client_id = geheimnis = ""
    name, slug = NAME, SLUG
    try:
        for kennung in SCHRITTE:
            try:
                if kennung == "erreicht":
                    text = await _erreicht(api)
                elif kennung == "schluessel":
                    schluessel, text = await _schluessel(api)
                elif kennung == "zuordnungen":
                    zuordnungen, text = await _zuordnungen(api)
                elif kennung == "provider":
                    name, slug = await _namen(api, rueckkehr)
                    ergebnis.issuer = issuer_fuer(basis, slug)
                    provider_pk, client_id, geheimnis, text = await _provider(
                        api, rueckkehr, schluessel, zuordnungen, name
                    )
                    ergebnis.client_id = client_id
                elif kennung == "anwendung":
                    text = await _anwendung(api, provider_pk, name, slug)
                else:
                    text = await _eintragen(db, ergebnis.issuer, client_id, geheimnis)
            except SchrittAbbruch as fehler:
                ergebnis.schritte.append(Schritt(kennung, False, fehler.text))
                logger.warning("authentik setup stopped at step %s: %s", kennung, fehler.text)
                break
            ergebnis.schritte.append(Schritt(kennung, True, text))
            logger.info("authentik setup step %s done: %s", kennung, text)
    finally:
        await api.schliessen()
    return ergebnis


# --- Der Blueprint -------------------------------------------------------- #


def blueprint(rueckkehr: str) -> str:
    """Ein Blueprint (Schema 1), der dieselben Dinge anlegt wie der Knopf.

    ``!Find`` und ``!KeyOf`` sind authentiks YAML-Marken; die Datei entsteht
    als Text, damit sie als Marken herauskommen und nicht als Zeichenketten.
    Die Rueckkehr-Adresse steht als JSON-Zeichenkette da; das ist ein
    gueltiger YAML-Wert in doppelten Anfuehrungszeichen, was immer sie traegt.
    """
    adresse = json.dumps(rueckkehr)
    zuordnungen = "\n".join(
        f"        - !Find [authentik_providers_oauth2.scopemapping, [managed, {v}]]"
        for v in VERWALTETE_ZUORDNUNGEN
    )
    return f"""# nexmail: OpenID Connect provider and application for authentik.
#
# Apply it under Customization, Blueprints (create a blueprint from this file) or drop it into the
# blueprints/custom/ directory of the authentik worker. Afterwards add a provider in nexmail under
# Administration, OIDC: short name {KUERZEL}, address <authentik address>/application/o/{SLUG}/, and client ID
# and client secret from the provider "{NAME}" (Applications, Providers).
#
# The signing key is authentik's default self-signed certificate: a blueprint cannot generate one. Pick a
# different certificate at the provider afterwards if you prefer. Without any signing key authentik signs
# with HS256, and nexmail never accepts that.
#
# Written against the authentik blueprint schema v1 (2024.x to 2026.x). grant_types exists since authentik 2026.8,
# where a provider without it refuses every sign-in; older versions ignore the line.
version: 1
metadata:
  name: {NAME}
  labels:
    blueprints.goauthentik.io/description: OpenID Connect provider and application for nexmail
entries:
  - model: authentik_providers_oauth2.oauth2provider
    state: present
    id: nexmail-provider
    identifiers:
      name: {NAME}
    attrs:
      authorization_flow: !Find [authentik_flows.flow, [slug, {BEVORZUGTER_ANMELDEFLUSS}]]
      invalidation_flow: !Find [authentik_flows.flow, [slug, {BEVORZUGTER_ABMELDEFLUSS}]]
      client_type: confidential
      grant_types:
        - {ABLAEUFE[0]}
      redirect_uris:
        - matching_mode: strict
          url: {adresse}
      signing_key: !Find [authentik_crypto.certificatekeypair, [name, authentik Self-signed Certificate]]
      sub_mode: user_uuid
      include_claims_in_id_token: true
      property_mappings:
{zuordnungen}
  - model: authentik_core.application
    state: present
    identifiers:
      slug: {SLUG}
    attrs:
      name: {NAME}
      provider: !KeyOf nexmail-provider
"""
