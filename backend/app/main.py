"""nexmail — der Server.

⚠️ **Die Liste der öffentlichen Adressen unten ist eine Erlaubnisliste.** Alles
andere hängt an ``Depends(angemeldet)``. Ein Test läuft über die ganze
Routentabelle und schlägt fehl, sobald ein Pfad weder geschützt ist noch dort
steht — mit Begründung. Umgekehrt gedacht („ich sperre, was schaden kann")
wäre die erste vergessene Zeile ein Datenleck.
Siehe FALLSTRICKE.md §5.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .db import SessionLocal, init_db
from .deps import angemeldet
from .middleware import (
    BasisPfadMiddleware,
    OberflaechePackenMiddleware,
    SicherheitskopfMiddleware,
    VorgangMiddleware,
)
from .routers import (
    abwesenheit as abwesenheit_router,
    aufgaben as aufgaben_router,
    mailoauth as mailoauth_router,
    austausch as austausch_router,
    bilder as bilder_router,
    oidc as oidc_router,
    auth,
    benutzer as benutzer_router,
    einladung as einladung_router,
    einstellungen,
    erinnerungen as erinnerungen_router,
    kalender as kalender_router,
    health,
    kontakte,
    konten,
    nachrichten,
    protokoll as protokoll_router,
    regeln,
    schlagworte as schlagworte_router,
    setup,
    sicherung,
    sitzungen,
    suche,
    termine as termine_router,
    ueber as ueber_router,
    verfassen,
)
from .services import imap as imapdienst
from .services import sitzung as sitzungsdienst

# ⚠️ **Hier stand ``logging.basicConfig``, und es war eine Undichtigkeit.**
# Es haengt einen StreamHandler **ohne Filter** an den Wurzel-Logger, und der
# steht vor den Handlern aus ``protokoll.einrichten()``. Folge, am 03.09.2026
# gemessen: Jede Zeile ging zweimal auf die Standardfehlerausgabe, und die
# erste Kopie ging an der Zensur vorbei. In ``docker logs`` stand
# ``A001 LOGIN nutzer@example.org Sonnenblume42Xyz`` im Klartext, waehrend die
# Protokolldatei brav ``… ***`` zeigte. Dazu Ortszeit statt UTC und keine
# Vorgangsnummer, also zwei Zeitachsen in einer Ausgabe.
#
# Ersatzlos gestrichen: Zwischen dem Import dieses Moduls und
# ``protokoll.einrichten()`` (erste Zeile des Lebenslaufs) wird **nichts**
# protokolliert - nachgemessen, nicht vermutet -, und die Stufe setzt
# ``stufe_anwenden`` ohnehin selbst.
logger = logging.getLogger("nexmail")

einstellungen_ = get_settings()


#: ⚠️ **Jeder Eintrag braucht einen Grund.** Wer hier etwas hinzufügt, ohne
#: einen nennen zu können, hat wahrscheinlich vergessen, die Abhängigkeit zu
#: setzen.
OEFFENTLICHE_PFADE: dict[str, str] = {
    "/api/health": (
        "Der Docker-Healthcheck läuft ohne Anmeldung — er soll ja gerade dann "
        "antworten, wenn etwas nicht stimmt."
    ),
    "/api/mailoauth/{art}/zurueck": (
        "Der Rückweg von Google oder Microsoft ist eine Navigation von fremder "
        "Seite — ein Sitzungs-Cookie mit SameSite=strict fährt dabei nicht mit. "
        "Der Nachweis steckt stattdessen im Anlauf-Cookie (SameSite=lax) und "
        "im zufälligen Zustand, der zurückkommen muss; ohne beides passiert "
        "nichts. Dasselbe Muster wie beim OIDC-Rückweg."
    ),
    "/api/setup/status": (
        "Die Oberfläche muss wissen, ob sie den Einrichtungsassistenten oder "
        "die Anmeldung zeigt. Zu diesem Zeitpunkt gibt es noch kein Konto."
    ),
    "/api/setup/konto": (
        "Das erste Konto anlegen. Schließt sich selbst, sobald ein Benutzer "
        "existiert — siehe routers/setup.py."
    ),
    "/api/auth/anmelden": "Die Anmeldung selbst kann keine Anmeldung verlangen.",
    "/api/auth/code": (
        "Zweiter Schritt der Anmeldung. Hängt an der halben Sitzung, die "
        "Schritt eins gesetzt hat — geschützt, aber nicht über 'angemeldet'."
    ),
    "/api/auth/wiederherstellung": "Wie /api/auth/code, nur mit einem Wiederherstellungscode.",
    "/api/auth/einrichtung": (
        "Zeigt den QR-Code, solange der zweite Faktor unbestätigt ist. Hängt "
        "ebenfalls an der halben Sitzung."
    ),
    "/api/oidc/knoepfe": (
        "Welche Anbieter auf der Anmeldeseite stehen. Die sieht noch niemand "
        "angemeldet — herausgegeben wird nur, was ohnehin auf einem Knopf "
        "steht."
    ),
    "/api/oidc/{kuerzel}/start": (
        "Der Hinweg zum Anbieter. Wer sich anmelden will, ist noch nicht "
        "angemeldet. Mit Sitzung heisst derselbe Weg „verknuepfen“."
    ),
    "/api/oidc/{kuerzel}/zurueck": (
        "Der Rueckweg vom Anbieter — eine Browser-Weiterleitung per GET. "
        "Geschuetzt ist er ueber das signierte Anlauf-Cookie (state, nonce, "
        "PKCE), nicht ueber eine Anmeldung; die entsteht ja gerade erst."
    ),
    "/api/einladung/{schluessel}": (
        "Eine Einladung ansehen und annehmen. Wer sie annimmt, hat noch kein "
        "Konto — der Schlüssel aus der Mail ist der ganze Nachweis. Deshalb "
        "hängt an beiden Adressen die Anmeldebremse, und beide antworten "
        "gleich, egal ob der Schlüssel unbekannt, abgelaufen oder verbraucht "
        "ist."
    ),
    "/api/sicherung/einspielen-vor-einrichtung": (
        "Eine Sicherung auf einer frischen Installation einspielen. Zu diesem "
        "Zeitpunkt gibt es kein Konto, das sich anmelden könnte. Schließt sich "
        "selbst, sobald ein Benutzer existiert — wie /api/setup/konto."
    ),
    "/api/bilder/{marke}": (
        "Bilder aus fremden Mails, geholt vom Server. Der Abruf kommt aus dem "
        "abgeschotteten Lesebereich — der hat eine fremde Herkunft, und das "
        "Sitzungs-Cookie steht auf SameSite=Strict, faehrt also nicht mit "
        "(02.09.2026 im echten Browser gemessen). Der Ausweis ist die "
        "Unterschrift in der Adresse: Sie oeffnet genau ein Bild, gilt eine "
        "Stunde, und ausgestellt wird sie nur einem Angemeldeten fuer eine "
        "Mail, die ihm gehoert."
    ),
    "/api/sicherung/pruefen-vor-einrichtung": (
        "Der Blick ins Archiv, bevor es eingespielt wird — auf einer frischen "
        "Installation also ohne Konto, genau wie das Einspielen selbst. "
        "⚠️ Er gibt nur preis, was ohnehin nur mit dem Archivpasswort zu "
        "lesen ist: Ohne das Passwort antwortet der Weg mit 400. Schließt "
        "sich, sobald ein Benutzer existiert."
    ),
}


@asynccontextmanager
async def lebenslauf(_: FastAPI):
    # ⚠️ **Vor allem anderen.** Sonst fehlen genau die Meldungen der
    # Schemapflege in der Datei - und die sind bei einem misslungenen Update
    # das Erste, wonach man sucht.
    from .services import protokoll as protokolldienst

    protokolldienst.einrichten()

    init_db()

    if einstellungen_.zwei_faktor_aus:
        # ⚠️ Laut, bei jedem Start. Ein Notausgang, den man vergisst
        # zurückzustellen, ist kein Notausgang mehr.
        logger.warning(
            "NEXMAIL_2FA_AUS is set: the second factor is DISABLED for every "
            "sign-in. Unset it as soon as the authenticator app works again."
        )

    with SessionLocal() as db:
        # Die gemerkte Stufe gilt erst jetzt: Beim allerersten Start gibt es
        # die Datenbank noch nicht.
        protokolldienst.gespeicherte_stufe_anwenden(db)

        # ⚠️ **Straenge einmal neu bestimmen.** Der alte Schluessel nahm bei
        # einer Nachricht ohne ``References`` den Betreff-Hash — eine Antwort
        # darauf traegt aber ``References: <kennung-der-ersten>`` und bekam
        # damit einen anderen Schluessel als die Nachricht, auf die sie
        # antwortet. Der Strang zerfiel an genau der Stelle, an der er
        # entsteht. Ohne diesen Lauf zeigte die Konversationsansicht bei
        # bestehender Post lauter Einzelstuecke und saehe aus, als taete sie
        # nichts.
        #
        # Einmal, gemerkt an einem Schluessel — wie beim Fuellen des
        # Suchindex. Bei jedem Start waere es eine Wanderung ueber
        # Hunderttausende Zeilen.
        from .db import einstellung_lesen, einstellung_schreiben
        from .models import Benutzer
        from .services import straenge as straengedienst

        if einstellung_lesen(db, "straenge_aufgebaut") != "1":
            for person in db.query(Benutzer).all():
                straengedienst.neu_aufbauen(db, person.id)
            einstellung_schreiben(db, "straenge_aufgebaut", "1")

        # ⚠️ **``angekommen`` fuer den Bestand einmal auf „jetzt" setzen.**
        # Die Spalte kam nach den ersten Abgleichen dazu; Zeilen davor stehen
        # auf NULL. Das Papierkorb-Aufraeumen misst daran die Verweildauer —
        # NULL hiesse Rueckfall aufs Absendedatum, und eine gestern geloeschte
        # Januar-Mail waere beim naechsten Lauf endgueltig weg. „Jetzt" gibt
        # dem Bestand eine frische Frist: die sichere Richtung.
        #
        # ⚠️ **Einmal, gemerkt an einem Schluessel** — wie beim
        # Strang-Neuaufbau darueber. Ohne die Marke lief bei JEDEM Start ein
        # ``UPDATE ... WHERE angekommen IS NULL`` ueber die ganze Tabelle, und
        # zwar auch dann, wenn es keine einzige Zeile mehr trifft: Es gibt
        # keinen Index auf ``angekommen``, der Plan ist ``SCAN nachricht``.
        # Gemessen am 03.09.2026: 327 ms bei 250.000 Zeilen, bei jedem
        # Hochfahren, fuer null geaenderte Zeilen.
        #
        # ⚠️ **Wer die Spalte je erneut nachzieht, loescht die Marke.**
        # Neue Zeilen bekommen ihren Wert aus der Vorgabe (``default=utcnow``
        # in ``models.Nachricht``); NULL entsteht nur beim Nachziehen einer
        # Spalte per ``ALTER TABLE``, und das passiert genau einmal je Spalte.
        if einstellung_lesen(db, "ankunft_nachgetragen") != "1":
            from sqlalchemy import update as _update

            from .models import Nachricht, utcnow

            nachgetragen = db.execute(
                _update(Nachricht)
                .where(Nachricht.angekommen.is_(None))
                .values(angekommen=utcnow())
            ).rowcount
            einstellung_schreiben(db, "ankunft_nachgetragen", "1")
            db.commit()
            if nachgetragen:
                logger.info("Filled in the arrival date for %s message(s).", nachgetragen)

        weg = sitzungsdienst.aufraeumen(db)
        if weg:
            logger.info("Removed %s expired session(s).", weg)

        # ⚠️ **Der einzige Ort, an dem Ruecksetzpunkte weggeworfen werden.**
        # ``db._sichern`` legt beim Schemawechsel einen an, kann aber nicht
        # aufraeumen: Es laeuft, bevor die Datenbank lesbar ist, und kennt die
        # eingestellte Zahl nicht. Gaebe es dort einen zweiten Aufraeumer mit
        # einer festen Zahl, waere die Zahl in der Oberflaeche eine Behauptung,
        # die das naechste Update stillschweigend widerruft.
        from .services import sicherungsliste

        behalten = einstellung_lesen(db, sicherungsliste.SCHLUESSEL_BEHALTEN)
        sicherungsliste.aufraeumen(
            int(behalten) if behalten.isdigit() else sicherungsliste.BEHALTEN_VORGABE
        )

        # ⚠️ **Abgebrochene Versandvorgaenge wieder aufnehmen.** Ohne das
        # bliebe eine Mail, die beim Herunterfahren mitten im Senden war,
        # stumm liegen - und der Absender merkt es erst, wenn jemand nachfragt.
        from .services import senden as sendedienst

        sendedienst.aufraeumen(db)

        # ⚠️ **Und die Hochladungen eines abgebrochenen Imports.** Der
        # Import-Faden loescht seine Datei im ``finally``; ein Neustart
        # mittendrin laesst ihn nie dorthin kommen. Uebrig blieben bis zu vier
        # Gigabyte in ``data/einfuhr``, die niemand je wieder ansieht.
        from .services import austausch as austauschdienst

        austauschdienst.einfuhr_aufraeumen()

        # ⚠️ **Und die Anhaenge, auf die keine Zeile mehr zeigt.** Sie werden
        # beim Abgleich geschrieben und bis zum 03.09.2026 von niemandem
        # geloescht; in ``data-dev`` waren 91,5 Prozent des Verzeichnisses
        # verwaist. Nur hier, beim Start: Im Betrieb liegt zwischen dem
        # Schreiben der Datei und dem Festschreiben ihrer Zeile ein Moment, in
        # dem sie verwaist aussieht.
        from .services import abgleich as abgleichdienst

        abgleichdienst.blobs_aufraeumen(db)
        offen = sendedienst.warteschlange_abarbeiten(db)
        if offen["versucht"]:
            logger.info(
                "Outbox picked up: %s tried, %s sent, %s still waiting.",
                offen["versucht"], offen["gesendet"], offen["liegen"],
            )

    # ⚠️ **Nach allem anderen.** Der Takt macht IMAP-Verbindungen auf; laeuft
    # er los, bevor die Warteschlange durch ist, streiten sich beide um das
    # eine Schloss je Postfach.
    from .services import takt as taktdienst

    taktdienst.starten()
    # ⚠️ Eigener Faden, absichtlich unabhaengig vom Abgleich-Takt: Wer den mit
    # NEXMAIL_TAKT_SEKUNDEN=0 abschaltet, meint „nicht dauernd Post holen",
    # nicht „keine Sicherungen mehr".
    taktdienst.sicherungsplan_starten()
    # ⚠️ Ebenfalls eigener Faden, aus demselben Grund: Wer den Abgleich-Takt
    # abschaltet, meint nicht „geplante Mails gehen nie hinaus".
    taktdienst.versandplan_starten()
    # ⚠️ Und noch einer: Papierkorb und Junk nach der eingestellten
    # Aufbewahrung leeren — abgeschalteter Abgleich-Takt heisst nicht
    # „der Papierkorb waechst wieder ewig".
    taktdienst.aufraeumplan_starten()
    # ⚠️ Und die Wiedervorlage: Auch sie haengt an einem eigenen Faden —
    # abgeschalteter Abgleich-Takt heisst nicht „weggelegte Mails kommen
    # nie zurueck".
    taktdienst.wiedervorlage_starten()
    taktdienst.kalender_starten()

    logger.info("nexmail %s is ready.", __version__)
    try:
        yield
    finally:
        taktdienst.anhalten()


app = FastAPI(
    title="nexmail",
    version=__version__,
    lifespan=lebenslauf,
    # Die eingebauten Doku-Seiten holen ihr JavaScript von einem fremden CDN
    # und laufen damit gegen die eigenen Inhaltsregeln. In Nexview waren sie
    # deshalb in jeder Installation eine weiße Seite. Hier gar nicht erst an.
    docs_url=None,
    redoc_url=None,
)

@app.exception_handler(imapdienst.Verbindungsfehler)
async def _verbindungsfehler(request: Request, fehler: imapdienst.Verbindungsfehler):
    """Ein Postfach, das nicht antwortet, ist kein Programmabsturz.

    ⚠️ **An einer Stelle statt an dreizehn.** Jede Handlung, die den
    Mailserver anfasst — markieren, verschieben, öffnen, senden, Ordner
    anlegen — kann daran scheitern, dass der Server nicht erreichbar ist oder
    die Anmeldung abgewiesen wird. Wer das je Adresse abfängt, vergisst eine:
    Am 01.09.2026 gab „Markieren" einen nackten 500er zurück, weil das
    Postfach-Passwort nicht mehr stimmte. Die Oberfläche zeigte „Das hat nicht
    geklappt", und im Protokoll stand ein Stacktrace, den niemand deuten muss.

    502 statt 500: Der Fehler liegt hinter uns, nicht bei uns — und die
    Meldung sagt, was zu tun ist.
    """
    logger.warning("Mailbox unreachable during %s: %s", request.url.path, fehler.roh[:200])
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": fehler.text})


if einstellungen_.cors_origins:
    # Nur für den Entwicklungsbetrieb: Im Container liefert derselbe Server
    # die Oberfläche aus, dann ist nichts „cross origin".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=einstellungen_.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

NUR_ANGEMELDET = [Depends(angemeldet)]

app.include_router(health.router)
app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(sitzungen.router, dependencies=NUR_ANGEMELDET)
app.include_router(einstellungen.router, dependencies=NUR_ANGEMELDET)
app.include_router(abwesenheit_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(konten.router, dependencies=NUR_ANGEMELDET)
app.include_router(kontakte.router, dependencies=NUR_ANGEMELDET)
app.include_router(nachrichten.router, dependencies=NUR_ANGEMELDET)
app.include_router(regeln.router, dependencies=NUR_ANGEMELDET)
app.include_router(schlagworte_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(protokoll_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(verfassen.router, dependencies=NUR_ANGEMELDET)
app.include_router(suche.router, dependencies=NUR_ANGEMELDET)
app.include_router(benutzer_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(aufgaben_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(termine_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(austausch_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(erinnerungen_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(kalender_router.router, dependencies=NUR_ANGEMELDET)
# ⚠️ **Nicht als Ganzes geschuetzt.** Der Rueckweg vom Anbieter ist eine
# Navigation von fremder Seite; er traegt seinen eigenen Nachweis (Anlauf-
# Cookie plus signierter Zustand) und darf deshalb ohne Sitzung ankommen.
app.include_router(mailoauth_router.router)
app.include_router(ueber_router.router, dependencies=NUR_ANGEMELDET)
# ⚠️ **Ohne ``NUR_ANGEMELDET``.** Hinweg und Rueckweg gehoeren zur
# Anmeldung; die Verwaltungs-Adressen darin haengen einzeln am Betreiber.
app.include_router(oidc_router.router)
app.include_router(einladung_router.router)
# ⚠️ **Ohne NUR_ANGEMELDET am Router.** Dieser Router traegt beides: den Weg
# vor der Einrichtung (ohne Anmeldung, siehe Liste oben) und die beiden
# Wege danach (mit). Die Abhaengigkeit haengt deshalb am einzelnen Endpunkt.
app.include_router(sicherung.router)
# ⚠️ **Ohne ``NUR_ANGEMELDET``, und das ist keine Nachlaessigkeit.** Die
# Begruendung steht oben in OEFFENTLICHE_PFADE und ausfuehrlich in
# routers/bilder.py.
app.include_router(bilder_router.router)


# --- Die gebaute Oberfläche ausliefern ---------------------------------- #


def _statisches_verzeichnis() -> Path | None:
    if einstellungen_.static_dir:
        pfad = Path(einstellungen_.static_dir)
        return pfad if pfad.is_dir() else None
    mitgeliefert = Path(__file__).resolve().parent / "static"
    return mitgeliefert if mitgeliefert.is_dir() else None


def _datei_im_haus(wurzel: Path, pfad: str) -> Path | None:
    """Die angefragte Datei, aber nur wenn sie wirklich unter ``wurzel`` liegt.

    ⚠️ **Ohne diese Pruefung liefert der Auffangweg jede Datei des Containers
    aus.** ``wurzel / pfad`` folgt einem ``..`` klaglos: ``/app/static`` plus
    ``../../data/secret.key`` ist ``/data/secret.key``, und genau das kam am
    03.09.2026 mit HTTP 200 zurueck. Ohne Anmeldung, und samt dem Schluessel,
    der jedes gespeicherte Postfach-Passwort einwickelt; die Datenbank kam
    denselben Weg. Ein Browser raeumt ``..`` vor dem Senden weg, deshalb faellt
    es beim Bedienen nie auf - ``curl --path-as-is`` und jeder Suchlauf tun es
    nicht.

    ⚠️ **Verglichen wird nach ``resolve()``, nicht auf der Zeichenkette.** Das
    loest ``..``, ``.`` und Verknuepfungen auf einmal auf; wer stattdessen nach
    ``".."`` im Text sucht, hat die kodierten Formen und den umgekehrten
    Schraegstrich als Trenner unter Windows uebersehen.
    """
    try:
        datei = (wurzel / pfad).resolve()
    except (OSError, ValueError):
        # Ungueltige Zeichen im Pfad. Unter Windows wirft das statt zu scheitern.
        return None
    if not datei.is_relative_to(wurzel):
        return None
    return datei if datei.is_file() else None


def _index_mit_vorbau(datei: Path, basis: str | None = None) -> str | None:
    """``index.html`` mit vorangestelltem Unterpfad — oder ``None`` ohne.

    ⚠️ **Der Vorbau kommt beim Start hinein, nicht beim Bauen.** Vite traegt
    ihn beim Bauen in ``BASE_URL`` ein; ein Abbild waere damit fuer **einen**
    Pfad gebaut. Wer nexmail unter ``/mail`` betreibt statt unter
    ``/nexmail``, braeuchte ein eigenes — und ein fertiges Abbild aus einem
    Katalog haette gar keinen.

    Die gebaute Seite verweist mit **absoluten** Pfaden auf sich selbst
    (``/assets/…``). Unter einem Unterpfad fragt der Browser damit an der
    Wurzel der Domain — dort, wohin der Proxy gar nicht zeigt, und die Seite
    bleibt weiss. Deshalb bekommen ``href="/`` und ``src="/`` den Vorbau.

    Dazu faehrt die Basis als ``window.__NEXMAIL_BASIS__`` mit; daraus bezieht
    die Oberflaeche ihren Vorbau fuer API-Aufrufe **und** fuer alles, was sie
    aus der Adresse liest (der Einladungslink zum Beispiel).

    Einmal beim Start, nicht je Anfrage.
    """
    basis = einstellungen_.url_base if basis is None else basis
    if not basis:
        return None
    html = datei.read_text(encoding="utf-8")
    # ⚠️ Nur einfache Schraegstriche: ``href="//fremde.example"`` ist eine
    # Adresse auf einem anderen Host und darf keinen Vorbau bekommen.
    html = re.sub(r'\b(href|src)="/(?!/)', lambda t: f'{t.group(1)}="{basis}/', html)
    # ⚠️ **Ein ``<meta>``, kein ``<script>``.** Nexview spritzt an dieser
    # Stelle eine Inline-Zeile ein — dort geht das, weil dessen CSP ohnehin mit
    # Pruefsummen der Inline-Skripte arbeitet. nexmails CSP sagt schlicht
    # ``script-src 'self'``, und die eingespritzte Zeile wurde stumm
    # verworfen: Die Seite lud, blieb aber ohne Vorbau und damit ohne
    # Anmeldemaske. Am 01.09.2026 vom Pruefstand gefunden, nicht von Hand.
    #
    # Ein ``meta`` faellt unter keine Skript-Regel, braucht keine Pruefsumme
    # und kann nicht blockiert werden.
    marke = f'<meta name="nexmail-basis" content="{basis}">'
    if "<head>" in html:
        return html.replace("<head>", "<head>\n    " + marke, 1)
    return marke + html


def _css_mit_vorbau(ordner: Path, basis: str | None = None) -> dict[str, str]:
    """Die Stilvorlagen mit vorangestelltem Unterpfad — je Datei einmal.

    ⚠️ **Die ``index.html`` allein reicht nicht.** In der gebauten CSS stehen
    die Schriften als ``url(/assets/…)`` — ebenfalls absolut. Unter einem
    Unterpfad sucht der Browser sie an der Wurzel der Domain, bekommt vierzehn
    404er und faellt still auf Systemschriften zurueck. Die Seite sieht dabei
    fast richtig aus; genau deshalb faellt es von Hand nicht auf.

    Am 01.09.2026 vom Pruefstand mit echtem nginx gefunden.
    """
    basis = einstellungen_.url_base if basis is None else basis
    if not basis or not (ordner / "assets").is_dir():
        return {}
    heraus: dict[str, str] = {}
    for datei in (ordner / "assets").glob("*.css"):
        inhalt = datei.read_text(encoding="utf-8")
        neu = inhalt.replace("url(/assets/", f"url({basis}/assets/")
        if neu != inhalt:
            heraus[datei.name] = neu
    return heraus


_frontend = _statisches_verzeichnis()
if _frontend is not None:
    # ⚠️ Einmal aufgeloest. ``_datei_im_haus`` vergleicht dagegen, und ein
    # unaufgeloester Vergleichswert liesse jeden Vergleich ins Leere laufen.
    _wurzel = _frontend.resolve()
    _index = _index_mit_vorbau(_frontend / "index.html")
    _css = _css_mit_vorbau(_frontend)

    # ⚠️ **Vor dem Mount**, sonst greift er zuerst: Starlette nimmt die erste
    # passende Route, und ``app.mount`` haengt hinten an.
    if _css:

        @app.get("/assets/{name}", include_in_schema=False)
        def stilvorlage(name: str):
            if name in _css:
                return Response(_css[name], media_type="text/css")
            datei = _datei_im_haus(_wurzel, f"assets/{name}")
            if datei is not None:
                return FileResponse(datei)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.get("/{pfad:path}", include_in_schema=False)
    def oberflaeche(pfad: str):
        """Alles, was keine Schnittstelle ist, bekommt die Oberfläche.

        Eine einseitige Anwendung kennt ihre Adressen selbst; der Server darf
        bei ``/einstellungen`` nicht mit 404 antworten, sonst ist ein
        Neuladen mitten in der App ein Fehler.
        """
        datei = _datei_im_haus(_wurzel, pfad) if pfad else None
        if datei is not None:
            return FileResponse(datei)
        if _index is not None:
            return HTMLResponse(_index)
        return FileResponse(_frontend / "index.html")


# --- Ganz außen ---------------------------------------------------------- #

app.add_middleware(SicherheitskopfMiddleware)

# ⚠️ **Vor den Sicherheitskopfzeilen, damit sie jede Antwort sieht** — auch
# die, die eine Ausnahme auslöst. Ohne das fehlte ausgerechnet beim Absturz
# die Vorgangsnummer.
app.add_middleware(VorgangMiddleware)

# ⚠️ **Weiter außen als die Vorgangsnummer**, damit die fertige Antwort
# gepackt wird und nicht ein Zwischenstand. Und innerhalb des Unterpfads: Der
# Pfad muss hier schon ohne Vorbau ankommen, sonst greift die Ausnahme für
# ``/api`` unter einem Vorbau nicht.
app.add_middleware(OberflaechePackenMiddleware)

# ⚠️ **Nach den Inhaltsregeln, damit ganz außen.** Jede Anfrage wird zuerst vom
# Unterpfad befreit, bevor irgendetwas anderes sie sieht — so zählen Routing,
# Rechte und Protokoll weiter auf dieselben Wurzel-Adressen wie ohne Unterpfad.
# Ohne gesetzte Basis wird gar nichts eingehängt.
if einstellungen_.url_base:
    app.add_middleware(BasisPfadMiddleware, basis=einstellungen_.url_base)
    logger.info("Running under the sub path %s.", einstellungen_.url_base)
