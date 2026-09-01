"""Ein OIDC-Anbieter als Attrappe — mit echten Unterschriften.

⚠️ **Echte Unterschriften, keine abgeschalteten Pruefungen.** Ein Test, der die
Signaturpruefung ausschaltet, prueft alles ausser dem, worauf es ankommt. Hier
wird ein RSA-Schluesselpaar erzeugt, der Ausweis wirklich unterschrieben und
der oeffentliche Schluessel als JWKS ausgeliefert — genau wie bei Keycloak.

Damit lassen sich auch die Faelle nachstellen, an denen es schiefgeht: falsche
Unterschrift, falscher Aussteller, falscher Empfaenger, fehlender ``nonce``,
Adresse nur in ``userinfo``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

#: ⚠️ **Die echte Klasse, einmal beim Import gemerkt.**
#:
#: Wer sie erst in ``einspannen`` liest, faengt beim **zweiten** Einspannen die
#: eigene erste Fassung ein — und die setzt ihren Transport zurueck. Ein Test
#: mit zwei Laeufen prueft dann zweimal denselben Anbieter, und der zweite
#: scheitert an einer „falschen Unterschrift", die gar keine ist.
_ECHTER_KLIENT = httpx.AsyncClient

ISSUER = "https://anbieter.example"
CLIENT_ID = "nexmail-test"


@dataclass
class Attrappe:
    """Ein Anbieter, dessen Verhalten sich einstellen laesst."""

    issuer: str = ISSUER
    client_id: str = CLIENT_ID
    #: Was im ID-Ausweis steht. ``None`` laesst das Feld weg.
    email: str | None = "anna@example.com"
    email_bestaetigt: bool | None = True
    #: Was ``userinfo`` liefert — der Fall Authelia/Zitadel.
    userinfo: dict[str, Any] | None = None
    #: ``userinfo`` antwortet mit einer fremden Kennung.
    userinfo_fremdes_sub: bool = False
    #: Der Endpunkt fehlt in der Selbstauskunft (ADFS).
    ohne_userinfo: bool = False
    #: Der Token-Endpunkt lehnt ab.
    tausch_scheitert: bool = False
    #: Der Token-Endpunkt liefert kein ``id_token`` (fehlender openid-Scope).
    ohne_ausweis: bool = False
    #: Die Selbstauskunft nennt einen anderen Aussteller.
    falscher_aussteller: str = ""
    #: Der Ausweis wird mit einem fremden Schluessel unterschrieben.
    falsche_unterschrift: bool = False
    #: Der Ausweis traegt einen anderen ``nonce``.
    falscher_nonce: str = ""
    #: Was der Anbieter statt JSON liefert (Proxy davor).
    html_statt_json: bool = False
    #: ⚠️ **Der Verwechslungs-Angriff.** Der Ausweis wird mit **HS256** und dem
    #: oeffentlichen Schluessel als Geheimnis unterschrieben. Stuende HS256 in
    #: der Verfahrensliste, wuerde er angenommen — und den oeffentlichen
    #: Schluessel kennt jeder, er steht im JWKS.
    alg_verwechslung: bool = False

    subject: str = "sub-anna-123"
    name: str = "Anna Beispiel"
    _nonce: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.schluessel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.fremder = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # --- Was der Anbieter ausliefert -------------------------------------- #

    def beschreibung(self) -> dict[str, Any]:
        daten = {
            "issuer": self.falscher_aussteller or self.issuer,
            "authorization_endpoint": f"{self.issuer}/auth",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
        }
        if not self.ohne_userinfo:
            daten["userinfo_endpoint"] = f"{self.issuer}/userinfo"
        return daten

    def jwks(self) -> dict[str, Any]:
        zahlen = self.schluessel.public_key().public_numbers()
        import base64

        def b64(n: int) -> str:
            roh = n.to_bytes((n.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(roh).decode().rstrip("=")

        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": "probe",
                    "n": b64(zahlen.n),
                    "e": b64(zahlen.e),
                }
            ]
        }

    def ausweis(self) -> str:
        inhalt: dict[str, Any] = {
            "iss": self.issuer,
            "sub": self.subject,
            "aud": self.client_id,
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "nonce": self.falscher_nonce or self._nonce,
            "name": self.name,
        }
        if self.email is not None:
            inhalt["email"] = self.email
        if self.email_bestaetigt is not None:
            inhalt["email_verified"] = self.email_bestaetigt
        if self.alg_verwechslung:
            # ⚠️ **Von Hand zusammengesetzt.** PyJWT weigert sich, mit einem
            # oeffentlichen Schluessel als HMAC-Geheimnis zu unterschreiben —
            # ein Angreifer hat diese Bremse nicht. Also genau so, wie er es
            # taete: Kopf, Rumpf, HMAC.
            import base64 as _b64
            import hashlib as _hash
            import hmac as _hmac

            def teil(daten: dict) -> str:
                roh = json.dumps(daten, separators=(",", ":")).encode()
                return _b64.urlsafe_b64encode(roh).decode().rstrip("=")

            kopf = teil({"alg": "HS256", "typ": "JWT", "kid": "probe"})
            rumpf = teil(inhalt)
            marke = _hmac.new(
                self.oeffentlich_pem(), f"{kopf}.{rumpf}".encode(), _hash.sha256
            ).digest()
            return f"{kopf}.{rumpf}.{_b64.urlsafe_b64encode(marke).decode().rstrip('=')}"
        schluessel = self.fremder if self.falsche_unterschrift else self.schluessel
        return jwt.encode(inhalt, schluessel, algorithm="RS256", headers={"kid": "probe"})

    def oeffentlich_pem(self) -> bytes:
        """Der oeffentliche Schluessel als PEM — was ein Angreifer haette."""
        from cryptography.hazmat.primitives import serialization

        return self.schluessel.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    # --- Der Transport ----------------------------------------------------- #

    def transport(self) -> httpx.MockTransport:
        def antworten(anfrage: httpx.Request) -> httpx.Response:
            pfad = anfrage.url.path
            if self.html_statt_json:
                return httpx.Response(200, text="<html>Proxy</html>", headers={"content-type": "text/html"})

            if pfad.endswith("/.well-known/openid-configuration"):
                return httpx.Response(200, json=self.beschreibung())
            if pfad.endswith("/jwks"):
                return httpx.Response(200, json=self.jwks())
            if pfad.endswith("/token"):
                if self.tausch_scheitert:
                    return httpx.Response(
                        400, json={"error": "invalid_client", "error_description": "Client-ID falsch"}
                    )
                if self.ohne_ausweis:
                    return httpx.Response(200, json={"access_token": "zugang", "token_type": "Bearer"})
                return httpx.Response(
                    200, json={"id_token": self.ausweis(), "access_token": "zugang", "token_type": "Bearer"}
                )
            if pfad.endswith("/userinfo"):
                daten = dict(self.userinfo or {})
                daten.setdefault("sub", "jemand-anderes" if self.userinfo_fremdes_sub else self.subject)
                return httpx.Response(200, json=daten)
            return httpx.Response(404, json={"error": "not_found"})

        return httpx.MockTransport(antworten)


def einspannen(monkeypatch, attrappe: Attrappe) -> None:
    """Die Attrappe an die Stelle des echten Netzes setzen.

    ⚠️ **Zwei Wege ins Netz, beide muessen umgeleitet werden.** ``httpx`` holt
    Selbstauskunft, Token und ``userinfo`` — aber ``PyJWKClient`` holt die
    Schluessel mit ``urllib``. Wer nur httpx umbiegt, laesst den Test gegen das
    echte Internet laufen und wundert sich ueber die Laufzeit.
    """
    from app.services import oidc

    def gebaut(*args, **kwargs):
        kwargs["transport"] = attrappe.transport()
        return _ECHTER_KLIENT(*args, **kwargs)

    monkeypatch.setattr(oidc.httpx, "AsyncClient", gebaut)

    class SchluesselKlient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_signing_key_from_jwt(self, token: str):
            class Schluessel:
                # ⚠️ **Als PEM, nicht als Objekt.** Genau so kaeme der
                # Schluessel im Betrieb an — und nur so laesst sich der
                # Verwechslungs-Angriff ueberhaupt nachstellen: Mit einem
                # Objekt wuerde PyJWT HS256 aus einem anderen Grund abweisen,
                # und der Test bestuende, ohne die Verfahrensliste zu pruefen.
                key = attrappe.oeffentlich_pem()

            return Schluessel()

    monkeypatch.setattr(oidc.jwt, "PyJWKClient", SchluesselKlient)
