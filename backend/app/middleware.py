"""Middleware: Unterpfad abstreifen, Oberflaeche packen, Sicherheitskopfzeilen setzen."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.middleware.gzip import GZipMiddleware

logger = logging.getLogger("nexmail.anfrage")


class OberflaechePackenMiddleware:
    """Packt die gebaute Oberflaeche, aber **nicht** die Schnittstelle.

    ⚠️ **Der ganze Gewinn liegt in den statischen Dateien.** Gemessen am
    03.09.2026: Der Einstieg wiegt 1.134.849 Byte roh und 342.188 gepackt, also
    70 Prozent weniger. Bei einer Erstinstallation ohne Reverse Proxy ging das
    bisher ungepackt hinaus - der Server setzt selbst keine Packung, und die
    ``docker-compose.yml`` stellt keinen Proxy davor.

    ⚠️ **Die API bleibt bewusst ungepackt.** Gepackte Antworten sind die
    Voraussetzung fuer BREACH: Wer eine Eingabe steuert, die zusammen mit einem
    Geheimnis in derselben Antwort landet, kann das Geheimnis an der Laenge
    ablesen. Bei einem Mailclient steuert ein Fremder die Eingabe muehelos, er
    schickt einfach eine Mail mit dem Betreff seiner Wahl. Ein Geheimnis im
    Rumpf gibt es heute nicht (die Sitzung liegt in einem HttpOnly-Cookie),
    aber der Gewinn waere ohnehin klein: Eine Listenantwort sind gemessen
    36 kB. Also die Klasse gar nicht erst aufmachen.

    ⚠️ **Der Pfad ist hier schon ohne Unterpfad.** ``BasisPfadMiddleware``
    haengt weiter aussen und hat ihn abgestreift, bevor diese Middleware ihn
    sieht - sonst traefe ``/api`` unter einem Vorbau nie zu, und die
    Schnittstelle waere doch gepackt.
    """

    def __init__(self, app: Any, mindestgroesse: int = 1000) -> None:
        self._durchreichen = app
        self._packend = GZipMiddleware(app, minimum_size=mindestgroesse)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith("/api"):
            await self._durchreichen(scope, receive, send)
            return
        await self._packend(scope, receive, send)



class BasisPfadMiddleware:
    """Streift den Unterpfad (``NEXMAIL_URL_BASE``) vom Anfragepfad.

    Damit beantwortet nexmail jede Adresse **doppelt**: mit Vorbau
    (``/nexmail/api/health``) und ohne (``/api/health``). Beides ist noetig:

    * Ein **durchreichender** Proxy schickt die Anfrage mitsamt Vorbau weiter -
      der Normalfall.
    * Ein **abschneidender** Proxy entfernt ihn vorher. Und der
      Docker-Healthcheck ruft ohnehin direkt an der Wurzel an.

    Es wird nur der Pfad umgeschrieben, sonst nichts: Routing, Rechte und
    Protokoll sehen die Anfrage anschliessend so, als waere sie an der Wurzel
    angekommen. Ein Pfad, der den Vorbau nur scheinbar traegt
    (``/nexmailfoo``), bleibt unangetastet.

    Uebernommen aus ``nexview/backend/app/middleware.py``.
    """

    def __init__(self, app: Any, basis: str) -> None:
        self.app = app
        self.basis = basis.rstrip("/")
        self._praefix = self.basis + "/"
        self._basis_roh = self.basis.encode("latin-1")

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] in ("http", "websocket") and self.basis:
            pfad = scope.get("path", "")
            neu = None
            if pfad == self.basis:
                neu = "/"
            elif pfad.startswith(self._praefix):
                neu = pfad[len(self.basis) :]
            if neu is not None:
                scope["path"] = neu
                # ``raw_path`` ist die unentschluesselte Urfassung; wo sie
                # vorliegt, muss sie denselben Schnitt bekommen, sonst zeigen
                # zwei Felder desselben Scopes auf verschiedene Adressen.
                roh = scope.get("raw_path")
                if isinstance(roh, bytes) and roh.startswith(self._basis_roh):
                    scope["raw_path"] = roh[len(self._basis_roh) :] or b"/"
        await self.app(scope, receive, send)


class SicherheitskopfMiddleware:
    """Kopfzeilen, die an jede Antwort gehoeren.

    ⚠️ **Die Inhaltsregeln sind streng, und das ist bei einem Mail-Client
    keine Kuer.** Der Lesebereich zeigt fremdes HTML; alles, was dort trotz
    Bereinigung durchkaeme, soll wenigstens hier auflaufen. ``frame-src``
    bleibt offen fuer den eigenen abgeschotteten Rahmen (``srcdoc``), der
    zaehlt als ``'self'``.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.regeln = "; ".join(
            [
                "default-src 'self'",
                "base-uri 'self'",
                "object-src 'none'",
                # ⚠️ **'self', nicht 'none'.** Die Druckseite laeuft in einem
                # unsichtbaren Rahmen der App selbst - mit 'none' blockierte
                # der Browser genau diesen Rahmen, und gedruckt wurde eine
                # leere Seite (02.09.2026). Gegen Clickjacking zaehlt, dass
                # FREMDE Seiten nexmail nicht einbetten koennen - und das
                # verhindert 'self' genauso.
                "frame-ancestors 'self'",
                "form-action 'self'",
                # Vite baut die Stile in eine Datei; 'unsafe-inline' braucht es
                # nur fuer die wenigen gesetzten style-Attribute der Oberflaeche.
                "style-src 'self' 'unsafe-inline'",
                "script-src 'self'",
                # data: fuer die QR-Codes und Inline-Bilder aus Nachrichten.
                "img-src 'self' data: blob:",
                # ⚠️ **``data:`` gehoert dazu.** Der Schriftsatz kommt als npm-Paket
                # mit und bringt einzelne Schnitte als eingebettete ``data:``-URI
                # mit. Ohne diese Erlaubnis verwirft der Browser sie stumm, und die
                # Oberflaeche faellt bei einzelnen Schnitten auf Systemschriften
                # zurueck — sichtbar nur, wenn man genau hinsieht. Am 01.09.2026 vom
                # Pruefstand gefunden, nicht von Hand.
                #
                # Eine Schrift ist kein Code: ``data:`` ist hier ungefaehrlich,
                # anders als bei ``script-src``.
                "font-src 'self' data:",
                "connect-src 'self'",
            ]
        )

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def senden(nachricht: dict) -> None:
            if nachricht["type"] == "http.response.start":
                kopf = nachricht.setdefault("headers", [])
                kopf.append((b"content-security-policy", self.regeln.encode("latin-1")))
                kopf.append((b"x-content-type-options", b"nosniff"))
                kopf.append((b"referrer-policy", b"no-referrer"))
                kopf.append((b"cross-origin-opener-policy", b"same-origin"))
            await send(nachricht)

        await self.app(scope, receive, senden)


class VorgangMiddleware:
    """Jede Anfrage bekommt eine Nummer — und die steht in jeder Log-Zeile.

    ⚠️ **Das ist der Unterschied zwischen „irgendwann heute" und „bei diesem
    Klick".** Wer einen Fehler meldet, kennt die Uhrzeit selten genau; die
    Vorgangsnummer stand aber in der Meldung, die er gesehen hat. Ein einziges
    Suchen danach beantwortet, was bei diesem einen Klick passiert ist.

    Die Nummer geht auch als ``x-nexmail-vorgang`` zurück, damit die
    Oberfläche sie bei einem Fehler anzeigen kann.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from .services import protokoll

        nummer = uuid.uuid4().hex[:8]
        marke = protokoll.vorgang_beginnen(nummer)
        beginn = time.monotonic()
        pfad = scope.get("path", "")
        methode = scope.get("method", "")
        stand = {"code": 0}

        async def mitschreiben(nachricht) -> None:
            if nachricht["type"] == "http.response.start":
                stand["code"] = nachricht["status"]
                kopf = list(nachricht.get("headers", []))
                kopf.append((b"x-nexmail-vorgang", nummer.encode("ascii")))
                nachricht = {**nachricht, "headers": kopf}
            await send(nachricht)

        try:
            await self.app(scope, receive, mitschreiben)
        except Exception:
            # ⚠️ Mit Vorgangsnummer, Pfad und Dauer - das sagt mehr als
            # uvicorns „Exception in ASGI application", der deshalb
            # unterdrückt wird (siehe protokoll.py).
            dauer = (time.monotonic() - beginn) * 1000
            logger.exception("Unhandled error on %s %s after %.0f ms.", methode, pfad, dauer)
            raise
        finally:
            dauer = (time.monotonic() - beginn) * 1000
            # ⚠️ **Nur der Pfad, nie die Abfrage.** In einer Suchanfrage steht,
            # wonach jemand in seiner Post sucht - das gehört nicht in eine
            # Datei, die weitergegeben wird.
            if stand["code"] >= 500:
                logger.warning("%s %s -> %s in %.0f ms.", methode, pfad, stand["code"], dauer)
            else:
                logger.debug("%s %s -> %s in %.0f ms.", methode, pfad, stand["code"], dauer)
            protokoll.vorgang_beenden(marke)
