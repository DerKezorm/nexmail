"""nexmail — der Server.

⚠️ **Die Liste der öffentlichen Adressen unten ist eine Erlaubnisliste.** Alles
andere hängt an ``Depends(angemeldet)``. Ein Test läuft über die ganze
Routentabelle und schlägt fehl, sobald ein Pfad weder geschützt ist noch dort
steht — mit Begründung. Umgekehrt gedacht („ich sperre, was schaden kann")
wäre die erste vergessene Zeile ein Datenleck.
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
from . import meldung as meldungsmodul
from .db import SessionLocal, init_db
from .deps import DbSession, angemeldet, nur_betreiber, nur_geraet
from .middleware import (
    AppFristMiddleware,
    BasisPfadMiddleware,
    OberflaechePackenMiddleware,
    SchemaVomProxyMiddleware,
    SicherheitskopfMiddleware,
    VorgangMiddleware,
)
from .routers import (
    absenderbild as absenderbild_router,
    abwesenheit as abwesenheit_router,
    api_v1 as api_v1_router,
    app1 as app1_router,
    app_kopplung as app_kopplung_router,
    apischluessel as apischluessel_router,
    aufgaben as aufgaben_router,
    aufgabenziele as aufgabenziele_router,
    nextime as nextime_router,
    nextasksansicht as nextasksansicht_router,
    mailoauth as mailoauth_router,
    austausch as austausch_router,
    bilder as bilder_router,
    oidc as oidc_router,
    auth,
    passkeys as passkeys_router,
    benutzer as benutzer_router,
    einladung as einladung_router,
    einstellungen,
    erinnerungen as erinnerungen_router,
    adressbuecher as adressbuecher_router,
    kalender as kalender_router,
    health,
    ki as ki_router,
    kontakte,
    konten,
    nachrichten,
    protokoll as protokoll_router,
    push as push_router,
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
from .services.abgleich import WartenFehler
from .services import imap as imapdienst
from .vendor import nexoidc
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


def _oeffentliche_adresse() -> str:
    """Die oeffentliche Adresse fuer das Anmeldemodul: die gespeicherte (in der Form von 0.21, ohne Vorbau) samt
    Vorbau, wie man nexmail erreicht; sonst ""."""
    from .db import einstellung_lesen
    from .services.adresse import fuer_modul

    with SessionLocal() as db:
        return fuer_modul(einstellung_lesen(db, "oeffentliche_adresse"), get_settings().url_base)


def _oeffentliche_adresse_speichern(adresse: str) -> None:
    """Eine in der authentik-Karte bestaetigte Adresse (samt Vorbau, wie der Browser sie nennt), sofort
    festgeschrieben (eigene Transaktion), in der gespeicherten Form von 0.21: ohne Vorbau."""
    from .db import einstellung_schreiben
    from .services.adresse import ohne_vorbau

    with SessionLocal() as db:
        einstellung_schreiben(db, "oeffentliche_adresse", ohne_vorbau(adresse, get_settings().url_base))


#: Das gemeinsame Anmeldemodul, vor der ersten Anfrage. Die Seiten tragen den Vorbau: Sie sind Ziele einer
#: Weiterleitung, die der Browser selbst aufloest.
nexoidc.configure(
    nexoidc.AppConfig(
        app_name="nexmail",
        server_secret=lambda: einstellungen_.resolved_secret_key(),
        api_prefix="/api",
        public_url=_oeffentliche_adresse,
        save_public_url=_oeffentliche_adresse_speichern,
        login_page=f"{einstellungen_.url_base}/anmelden",
        account_page=f"{einstellungen_.url_base}/konto/sicherheit",
        home=f"{einstellungen_.url_base}/",
    )
)


#: ⚠️ **Jeder Eintrag braucht einen Grund.** Wer hier etwas hinzufügt, ohne
#: einen nennen zu können, hat wahrscheinlich vergessen, die Abhängigkeit zu
#: setzen.
OEFFENTLICHE_PFADE: dict[str, str] = {
    "/api/locales": (
        "Die Sprachen der Installation (eingebaute und die des Betreibers, Modul sprachen) für die Sprachauswahl, "
        "auch auf der Anmeldeseite; für alle gleich, nichts Persönliches."
    ),
    "/api/locales/{code}": (
        "Die Texte einer Sprache, lesen ohne Anmeldung aus demselben Grund. Hochladen (PUT) und Entfernen (DELETE) "
        "verlangen den Betreiber (``operator=nur_betreiber``)."
    ),
    "/api/locales/template": (
        "Die Vorlage für eine neue Sprache; bei nexmail macht sie die Seite, der Weg antwortet 404 not_found."
    ),
    "/api/app/1/pairing/{pairing_id}/key": (
        "Hier holt sich die iPhone-App ihren Schlüssel, also hat sie noch keinen. Das "
        "Geheimnis aus dem QR-Code steht in der Kopfzeile, davor die Anmeldebremse."
    ),
    "/api/app/1/pairing/code": (
        "Derselbe Weg mit dem kurzen Code zum Abtippen: Wer ihn benutzt, hat noch "
        "keinen Schlüssel. Die Bremse zählt je Adresse, der Code gilt zehn Minuten."
    ),
    "/api/about": (
        "Version, Lizenz, Quelltext und Veröffentlichungen (Modul updates): stehen ohnehin auf GitHub, nichts "
        "Persönliches. Der Stand der Update-Prüfung darunter (``/api/about/updates``) verlangt eine Anmeldung, "
        "Schalten und Nachsehen den Betreiber."
    ),
    "/api/mcp": (
        "KI-Werkzeuge (Modul mcp): ein Programm bringt einen MCP-Schlüssel oder das Token eines verbundenen Programms "
        "in Authorization: Bearer, nie eine Sitzung (eine Anfrage mit Origin wird abgewiesen). Die Prüfung macht das "
        "Modul vor allem anderen; ohne gültigen Schlüssel 401, MCP aus: 404."
    ),
    "/api/oauth/register": (
        "Ein KI-Programm meldet sich selbst an (RFC 7591), bevor es einen Zugang hat: nur öffentliche Programme mit "
        "sicheren Rücksprungadressen, gebremst je Absender und für den Server; aus, solange Programme aus sind."
    ),
    "/api/oauth/token": (
        "Das Programm tauscht den Code der Zustimmung (PKCE) oder sein Erneuerungstoken; es hat dabei noch keine "
        "Sitzung. Ein Code gilt einmal, ein verbrauchtes Token wieder gebracht beendet das Programm."
    ),
    "/api/oauth/revoke": (
        "Ein Programm beendet seinen Zugang selbst (RFC 7009); wer ein Token kennt, darf es beenden."
    ),
    "/api/connect/token": (
        "Eine andere nex-App tauscht den Code einer Zustimmung oder erneuert ihren Zugang (Modul verbinden); sie hat "
        "keine Sitzung hier. PKCE, ein Code einmal, ein verbrauchtes Token wieder gebracht beendet die Verbindung."
    ),
    "/api/connect/revoke": (
        "Eine andere nex-App beendet ihre Verbindung (RFC 7009, Modul verbinden); wer ein Token kennt, darf es beenden."
    ),
    "/api/connect/retire": (
        "Ein alter API-Schlüssel beendet sich selbst, nachdem eine App neu verbunden hat (Modul verbinden); nexmail "
        "gewährt keinem Partner etwas, der Weg antwortet nur."
    ),
    "/api/connect/hello": (
        "Eine verbundene nex-App prüft ihre Verbindung mit ihrem Token (Modul verbinden), ohne Sitzung."
    ),
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
    "/api/auth/passkey": (
        "Anmelden mit Passkey (Kontenmodul Teil 2): GET sagt der Anmeldeseite, ob der Knopf dasteht, POST nimmt die"
        " Antwort des Browsers; beides vor jeder Anmeldung."
    ),
    "/api/auth/passkey/start": (
        "Der Anlauf zum Anmelden mit Passkey: eine Challenge im Cookie, hoechstens 20 offene je Absender (Modul)."
    ),
    "/api/auth/code": (
        "Zweiter Schritt der Anmeldung. Hängt an der halben Sitzung, die "
        "Schritt eins gesetzt hat — geschützt, aber nicht über 'angemeldet'."
    ),
    "/api/auth/wiederherstellung": "Wie /api/auth/code, nur mit einem Wiederherstellungscode.",
    "/api/auth/kennwort-vergessen": (
        "Wer sein Passwort vergessen hat, kann sich nicht anmelden — das ist "
        "der ganze Anlass. Die Adresse antwortet deshalb IMMER gleich (202, "
        "derselbe Rumpf, dieselbe Zeit: gesucht wird nach der Antwort), egal "
        "ob es das Konto gibt oder dort eine Adresse steht: Ein sichtbarer "
        "Unterschied waere eine Namensliste. GET sagt nur, ob ein Link per "
        "Mail ueberhaupt hinaus kann (Postausgang). Die Anmeldebremse zaehlt "
        "am Konto mit, sonst schickt eine Maschine tausend Mails los."
    ),
    "/api/auth/kennwort-neu": (
        "Der Link aus der Mail (oder vom Betreiber, oder vom Notfallbefehl) IST "
        "der Nachweis; wer angemeldet waere, braeuchte ihn nicht. Der Schluessel "
        "hat 256 Bit und liegt nur als Hash da, gilt eine Stunde (selbst "
        "angefordert) bzw. 1, 7 oder 30 Tage (Betreiber) und genau einmal — und "
        "die Bremse haengt auch hier davor."
    ),
    "/api/auth/kennwort-neu/{schluessel}": (
        "Dieselbe Seite fragt vorher, fuer wen der Link gilt; verbraucht nichts. "
        "Wer ihn nicht hat, erfaehrt nichts (dieselbe Kennung fuer unbekannt und "
        "abgelaufen), die Bremse haengt davor."
    ),
    "/api/auth/adresse/{schluessel}": (
        "Der Link, der eine neue Adresse bestaetigt, kommt per Mail und muss "
        "auch auf einem Geraet gehen, auf dem niemand angemeldet ist. 256 Bit, "
        "nur als Hash gespeichert, 24 Stunden, einmal; die Bremse haengt davor."
    ),
    "/api/auth/einrichtung": (
        "Zeigt den QR-Code, solange der zweite Faktor unbestätigt ist. Hängt "
        "ebenfalls an der halben Sitzung."
    ),
    "/api/oidc/providers": (
        "Welche Anbieter auf der Anmelde- und der Einladungsseite stehen. Die "
        "sieht noch niemand angemeldet; herausgegeben wird nur, was ohnehin auf "
        "einem Knopf steht (Kurzname und Name)."
    ),
    "/api/oidc/anmeldeseite": (
        "Dasselbe fuer die Anmeldeseite, dazu ob das Passwortformular dasteht. "
        "Wer sich anmelden will, ist noch nicht angemeldet."
    ),
    "/api/oidc/{slug}/start": (
        "Der Hinweg zum Anbieter. Wer sich anmelden will, ist noch nicht "
        "angemeldet. Die Bremse steht davor; eine Einladung reist nur mit, wenn "
        "ihr Schluessel gilt."
    ),
    "/api/oidc/{slug}/callback": (
        "Der Rueckweg vom Anbieter, eine Browser-Weiterleitung per GET. "
        "Geschuetzt ueber das signierte Anlauf-Cookie (state einmalig, nonce, "
        "PKCE), nicht ueber eine Anmeldung; die entsteht ja gerade erst. Beim "
        "Verknuepfen nimmt er das Konto aus der Sitzung."
    ),
    "/api/oidc/callback": (
        "Derselbe Rueckweg fuer den Eintrag oidc (die Adresse, die ein "
        "Anbieter aus einer Ein-Anbieter-Fassung kennt)."
    ),
    "/api/oidc/{slug}/einladung": (
        "Eine Einladung ueber einen Anbieter annehmen. Wer eingeladen ist, hat "
        "noch kein Konto; der Schluessel aus der Mail ist der Nachweis, genau "
        "wie beim Annehmen mit Passwort, und dieselbe Bremse steht davor. POST, "
        "damit der Schluessel in keinem Protokoll steht."
    ),
    "/api/oidc/{slug}/zurueck": (
        "Derselbe Rueckweg unter der Adresse, die die Anbieter aus nexmail 0.21 "
        "kennen; sie bleibt gueltig, solange ein Eintrag sie traegt."
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

    # Speicher und Sicherung (Modul sicherung): vor der Datenbank konfigurieren und wegräumen, was ein beendeter Lauf
    # liegen ließ (bei restore = "now" ruft nexmail das selbst, ``apply_pending`` gibt es hier nicht).
    from .services import sicherung_haken
    from .vendor import nexsicherung

    sicherung_haken.konfigurieren()
    try:
        nexsicherung.archives.tidy_at_start()
    except Exception:  # noqa: BLE001 - Aufräumen darf den Start nicht aufhalten
        logger.exception("Tidying the backups folder at the start failed.")
    nexsicherung.space.warn_at_start()

    init_db()
    # Modul ki 0.1.0: was nie gespeichert war, einmal festschreiben (Weg „Jedes Konto selbst", wo Konten eigene Zugänge
    # haben; Rechner dieser Zugänge im eigenen Netz auf die Liste des Betreibers, K2, K4). Ein zweiter Start ändert nichts.
    from .services import ki_store
    from .vendor import nexki

    with SessionLocal() as db:
        try:
            nexki.settings.adopt(ki_store.store_fuer(db), ki_store.CONFIG)
        except Exception:  # noqa: BLE001 - die KI ist Nebensache, der Start geht vor
            logger.exception("Adopting the AI settings of before failed.")
    # Ohne Konto: der Einrichtungscode ins Protokoll, bei jedem Start (Kontenmodul).
    from .services import konten_store
    from .vendor import nexkonten

    with SessionLocal() as db:
        nexkonten.setup.announce_setup(konten_store.store_fuer(db))
    # Den TLS-Kontext des Anmeldemoduls einmal ausserhalb der Ereignisschleife lesen.
    await nexoidc.warm()

    # ⚠️ Der Nothammer, laut bei jedem Start: Ein Notausgang, den man vergisst zurückzustellen, ist keiner mehr.
    nexkonten.factor.announce_switched_off()

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

        # ⚠️ **Jeder Benutzer braucht sein lokales Adressbuch**, und jeder
        # Kontakt einen Ort darin. Ein Kontakt ohne Buch ist einer, den die
        # Buecherspalte gar nicht zeigen kann — unsichtbar, ohne geloescht zu
        # sein, und das sieht aus wie Datenverlust. Muss deshalb laufen, bevor
        # jemand die Kontaktseite oeffnet.
        #
        # ⚠️ **Einmal, gemerkt an einem Schluessel** — wie darueber. Sonst
        # liefe bei jedem Start ein UPDATE ueber die ganze Kontakttabelle.
        if einstellung_lesen(db, "buecher_nachgetragen") != "1":
            from .services import adressbuecher as buchdienst

            buchdienst.nachtragen(db)
            einstellung_schreiben(db, "buecher_nachgetragen", "1")
        # Die Karten verbundener Buecher einmal neu holen lassen: 0.10.0 las
        # Apples leeres ``FN`` als Namen. Einmal, gemerkt an einer Marke; ohne
        # sie holte jeder Start alle Buecher noch einmal ganz.
        if einstellung_lesen(db, "karten_neu_gelesen") != "1":
            from .services import adressbuecher as buchdienst

            buchdienst.neu_lesen_erzwingen(db)
            einstellung_schreiben(db, "karten_neu_gelesen", "1")
        # Die Felder des Felder-Schritts (Vor- und Nachname, Listen) fuer den
        # Bestand einmal aus der Karte oder aus den alten Spalten fuellen.
        # Einmal, gemerkt an einer Marke, wie darueber.
        if einstellung_lesen(db, "kontaktfelder_nachgetragen") != "1":
            from .services import kontakte as kontaktdienst

            kontaktdienst.felder_nachtragen(db)
            einstellung_schreiben(db, "kontaktfelder_nachgetragen", "1")

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

        # Technische Keywords, die vor der Erweiterung der Liste als Schlagwort
        # hereinkamen (Issue #16). Vor dem Takt: Danach schriebe der Abgleich
        # in dieselben Zeilen.
        from .services import schlagworte as schlagwortdienst

        schlagwortdienst.technische_aufraeumen(db)

        # Vorschauen aus Stylesheet-Text. Einmal, gemerkt an einem Schluessel:
        # Neue Mails sind in Ordnung, und der Lauf sieht jede verdaechtige Zeile an.
        if einstellung_lesen(db, "anrisse_geheilt") != "1":
            from .services import abgleich as abgleichdienst

            abgleichdienst.anrisse_heilen(db)
            einstellung_schreiben(db, "anrisse_geheilt", "1")

        # Stränge, die das Öffnen einer Mail zerrissen hat. Einmal, wie oben.
        if einstellung_lesen(db, "straenge_geheilt") != "1":
            straengedienst.betreff_schluessel_heilen(db)
            einstellung_schreiben(db, "straenge_geheilt", "1")

        weg = sitzungsdienst.aufraeumen(db)
        if weg:
            logger.info("Removed %s expired session(s).", weg)

        # ⚠️ **Der einzige Ort beim Start, an dem automatische Sicherungen weggeworfen werden.** ``db._sichern`` legt
        # beim Schemawechsel einen Rücksetzpunkt an, kann aber nicht aufräumen: Es läuft, bevor die Datenbank lesbar
        # ist, und kennt die eingestellte Zahl nicht. Seit dem Modul sicherung gehen nur automatische (geplant, vor
        # einer Änderung); von Hand gemachte und hochgeladene bleiben, bis jemand sie löscht.
        nexsicherung.archives.prune(nexsicherung.plan.load().keep)

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
    # ⚠️ Der engste Faden von allen (eine Minute): Eine Erinnerung
    # „fuenf Minuten vorher“ waere bei einem weiteren Takt im schlechtesten
    # Fall erst nach dem Termin draußen.
    taktdienst.push_starten()
    # ⚠️ Nach dem Takt und an ihm hängend: Wer ihn abschaltet, meint genau das,
    # was die Wache täte. Ohne eingeschaltetes Postfach hält sie keine Leitung.
    from .services import postfachwache

    postfachwache.starten()

    # Der Wächter des Protokolls (Modul log): beendet eine tiefe Stufe nach ihrer Zeit, jede Minute, auch wenn der
    # Abgleich-Takt aus ist; räumt einmal am Tag ältere Dateien weg.
    import asyncio

    from .vendor import nexlog

    protokoll_halt = asyncio.Event()
    protokoll_waechter = asyncio.create_task(nexlog.run_forever(protokoll_halt))

    logger.info("nexmail %s is ready.", __version__)
    try:
        yield
    finally:
        protokoll_halt.set()
        protokoll_waechter.cancel()
        postfachwache.anhalten()
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
    # ⚠️ **Und die Beschreibung dahinter auch nicht.** Ohne diese Zeile lag
    # /openapi.json ohne Anmeldung offen: jede Adresse samt Docstring und
    # genauer Fassung, ein Lageplan an jeder Installation. Gelesen hat ihn
    # nichts, auch die Oberfläche nicht. Gefunden am 11.10.2026.
    openapi_url=None,
)

# ⚠️ **Ersetzt FastAPIs eigenen Handler fuer HTTPException.** Ohne das faellt
# das Feld ``werte`` weg: Starlette rendert nur ``detail``, und die Zahlen und
# Namen in einer Meldung („Der Name ist laenger als **40** Zeichen") kaemen nie
# in der Oberflaeche an. Kopfzeilen reicht er weiter — daran haengt unter
# anderem ``Retry-After`` bei der Anmeldebremse.
app.add_exception_handler(HTTPException, meldungsmodul.als_antwort)


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


@app.exception_handler(WartenFehler)
async def _warten(request: Request, fehler: WartenFehler):
    """Gerade geht es nicht, gleich wieder.

    503 samt ``Retry-After``, damit die App weiß, dass die Handlung nicht
    gescheitert ist: Sie bleibt in ihrer Warteschlange und kommt noch einmal.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": fehler.kennung, "werte": fehler.werte},
        headers={"Retry-After": str(fehler.werte.get("sekunden", 30))},
    )


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
app.include_router(passkeys_router.router)
app.include_router(sitzungen.router, dependencies=NUR_ANGEMELDET)
app.include_router(einstellungen.router, dependencies=NUR_ANGEMELDET)
app.include_router(ki_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(abwesenheit_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(konten.router, dependencies=NUR_ANGEMELDET)
app.include_router(kontakte.router, dependencies=NUR_ANGEMELDET)
app.include_router(adressbuecher_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(nachrichten.router, dependencies=NUR_ANGEMELDET)
app.include_router(absenderbild_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(regeln.router, dependencies=NUR_ANGEMELDET)
app.include_router(schlagworte_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(protokoll_router.router, dependencies=NUR_ANGEMELDET)
# Die Wege des Moduls log (``/api/logs``); ``nur_betreiber`` hängt schon am Router selbst.
app.include_router(protokoll_router.modul_router, dependencies=NUR_ANGEMELDET)
app.include_router(verfassen.router, dependencies=NUR_ANGEMELDET)
app.include_router(suche.router, dependencies=NUR_ANGEMELDET)
app.include_router(benutzer_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(aufgaben_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(aufgabenziele_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(nextime_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(nextasksansicht_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(termine_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(austausch_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(erinnerungen_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(kalender_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(push_router.router, dependencies=NUR_ANGEMELDET)
app.include_router(apischluessel_router.router, dependencies=NUR_ANGEMELDET)
# ⚠️ **Ohne ``NUR_ANGEMELDET``, und das ist keine Nachlaessigkeit.** Diese
# Adressen sind fuer andere Anwendungen und nehmen nur einen API-Schluessel,
# keine Sitzung. Jede einzelne haengt an ``deps.api_zugriff``; der Waechter
# in ``test_waechter.py`` zaehlt das als Schutz.
app.include_router(api_v1_router.router)
# ⚠️ **``nur_geraet`` an der ganzen Fläche.** Die Handler tragen ihr gewöhnliches
# ``angemeldet``; welche Tür das öffnet, entscheidet ``deps._sitzung`` am Pfad.
app.include_router(app1_router.router, dependencies=[Depends(nur_geraet)])
# Ohne Wache: Wer hier ankommt, hat noch keinen Schlüssel (OEFFENTLICHE_PFADE).
app.include_router(app_kopplung_router.public_router)
app.include_router(app_kopplung_router.router, dependencies=NUR_ANGEMELDET)
# ⚠️ **Nicht als Ganzes geschuetzt.** Der Rueckweg vom Anbieter ist eine
# Navigation von fremder Seite; er traegt seinen eigenen Nachweis (Anlauf-
# Cookie plus signierter Zustand) und darf deshalb ohne Sitzung ankommen.
app.include_router(mailoauth_router.router)
app.include_router(ueber_router.router, dependencies=NUR_ANGEMELDET)
# Über nexmail, Karte „Aktualisierungen“ (Modul updates 0.1.1) unter ``/api/about``: ``GET /api/about`` für jeden (steht
# in OEFFENTLICHE_PFADE), der Stand nur angemeldet und nur für Betreiber sichtbar (U15), Schalten und Nachsehen nur der
# Betreiber. Die alten Wege ``/api/ueber`` oben sind eine dünne Hülle darüber (U16).
from .services import aktualisierung as _aktualisierung  # noqa: E402
from .vendor.nexupdates import api as nexupdates_api  # noqa: E402

_aktualisierung.konfigurieren()
app.include_router(
    nexupdates_api.router(
        account=angemeldet,
        operator=nur_betreiber,
        is_operator=lambda person: bool(person.ist_betreiber),
    )
)
# ⚠️ **Ohne ``NUR_ANGEMELDET``.** Hinweg und Rueckweg gehoeren zur
# Anmeldung; die Verwaltungs-Adressen darin haengen einzeln am Betreiber.
app.include_router(oidc_router.router)
app.include_router(einladung_router.router)
# ⚠️ **Ohne NUR_ANGEMELDET am Router.** Dieser Router traegt beides: den Weg
# vor der Einrichtung (ohne Anmeldung, siehe Liste oben) und die beiden
# Wege danach (mit). Die Abhaengigkeit haengt deshalb am einzelnen Endpunkt.
app.include_router(sicherung.router)
# Server › Anmeldung (Kontenmodul 1.1.0): Schalter und „Bereit fürs Internet?“, nur für Betreiber.
from .routers import anmeldung_server as anmeldung_server_router  # noqa: E402

app.include_router(anmeldung_server_router.router, dependencies=NUR_ANGEMELDET)


def _post_store(db: DbSession):
    """Der Store des Mailmoduls ueber die Sitzung der Anfrage (Server › Mail)."""
    from .services.post_store import PostStore

    return PostStore(db)


# Server › Mail (Mailmodul post 1.1.0): Ansicht, Speichern, Testmail; nur fuer Betreiber. Die alten Wege
# ``/api/einstellungen/postausgang`` bleiben.
from .vendor.nexpost import api as nexpost_api  # noqa: E402

app.include_router(nexpost_api.router(operator=nur_betreiber, store=_post_store), dependencies=NUR_ANGEMELDET)


def _schluessel_store(db: DbSession):
    """Der Store des Moduls schluessel ueber die Sitzung der Anfrage; derselbe dient dem Modul mcp (MCP-Schluessel und
    verbundene Programme stehen in derselben Liste)."""
    from .services.mcp_store import McpStore

    return McpStore(db)


def _adresse_fuer_programme(request: Request) -> str:
    """Die Adresse, unter der Programme nexmail erreichen: die eingestellte, sonst die dieser Anfrage."""
    from .db import SessionLocal
    from .services import kontenpost

    with SessionLocal() as db:
        return kontenpost.oeffentliche_adresse(db) or (str(request.base_url).rstrip("/") + einstellungen_.url_base)


# Mein Konto › Verbindungen „API-Schluessel", Server › Allgemein „Schnittstellen", Server › Konten „API-Schluessel aller
# Konten" (Modul schluessel 1.0.0) unter ``/api/connections``. Nur Browser-Sitzungen (``deps._sitzung`` laesst ausserhalb
# von ``/api/app/`` kein Geraetetoken herein). Die alten Wege ``/api/apischluessel`` bleiben.
from .services.schluessel_store import KONFIGURATION as _SCHLUESSEL  # noqa: E402
from .vendor.nexschluessel import api as nexschluessel_api  # noqa: E402

app.include_router(
    nexschluessel_api.router(
        config=_SCHLUESSEL,
        store=_schluessel_store,
        account=angemeldet,
        operator=nur_betreiber,
        address=_adresse_fuer_programme,
    ),
    dependencies=NUR_ANGEMELDET,
)
# KI-Werkzeuge (Modul mcp 1.1.0): ``POST /api/mcp`` für Programme mit Schlüssel, OAuth unter ``/api/oauth`` samt
# Metadaten unter ``/.well-known``, die Seiten des Kontos und des Betreibers unter ``/api/connections/mcp``. Die
# Zustimmung (``/api/oauth/authorize``) verlangt eine echte Anmeldung im Browser.
from .services import mcp_hinweis as _mcp_hinweis  # noqa: E402
from .services import mcp_store as _mcp_store  # noqa: E402
from .services.anmeldebremse import adresse_von as _adresse_von  # noqa: E402
from .services.mcp_werkzeuge import MCP as _MCP  # noqa: E402
from .vendor.nexmcp import api as nexmcp_api  # noqa: E402


def _mcp_store_fuer(db: DbSession):
    return _mcp_store.store_fuer(db)


app.include_router(
    nexmcp_api.router(
        config=_MCP,
        store=_mcp_store_fuer,
        account=angemeldet,
        operator=nur_betreiber,
        account_id=lambda person: person.id,
        account_name=lambda person: person.benutzername,
        address=_adresse_fuer_programme,
        # Ohne ``NEXMAIL_CLIENT_IP`` kennt nexmail den Absender nicht; dann zählt die Bremse falscher Schlüssel nach der
        # Adresse der Verbindung, wie in den anderen Apps (TODO mcp 1.1.0, siehe einst-fragen).
        sender=lambda request: _adresse_von(request) or (request.client.host if request.client else ""),
        # Über den Namen gerufen, damit die Vertragstests mithören können (``notified``).
        notify=lambda ereignis, anfrage: _mcp_hinweis.melden(ereignis, anfrage),
    )
)
# KI-Anbieter (Modul ki 0.1.0): Server › KI-Anbieter unter ``/api/server/ai`` (Betreiber), Mein Konto › KI unter
# ``/api/me/ai``. Die alten Wege ``/api/ki/…`` bleiben mit ihren Kennungen und rufen dieselben Funktionen.
from .services import ki_store as _ki_store  # noqa: E402
from .vendor.nexki import api as nexki_api  # noqa: E402


def _ki_store_fuer(db: DbSession):
    return _ki_store.store_fuer(db)


app.include_router(
    nexki_api.router(
        config=_ki_store.CONFIG,
        store=_ki_store_fuer,
        account=angemeldet,
        operator=nur_betreiber,
        account_id=lambda person: person.id,
    ),
    dependencies=NUR_ANGEMELDET,
)
# Andere nex-Apps verbinden (Modul verbinden 0.1.1): ``/.well-known/nex-app``, ``/api/connect/…``; die Seiten
# ``/connect/app`` und ``/connect/return`` macht die Oberfläche. Die alten Wege (``/api/aufgabenziele/…/nextasks``,
# ``/api/nextime``) bleiben.
from .services import verbinden_store as _verbinden  # noqa: E402
from .vendor.nexverbinden import api as nexverbinden_api  # noqa: E402


def _verbinden_store_fuer(db: DbSession):
    return _verbinden.store_fuer(db)


def _alter_schluessel(store, konto_id, partner: str):
    from .models import Benutzer
    from .services import aufgabenziele, nextimeverbindung

    person = store.db.get(Benutzer, str(konto_id))
    if person is None:
        return None
    if partner == "nextasks":
        return aufgabenziele.nextasks_alter_schluessel(store.db, person)
    if partner == "nextime":
        return nextimeverbindung.alter_schluessel(store.db, person)
    return None


app.include_router(
    nexverbinden_api.router(
        config=_verbinden.CONFIG,
        store=_verbinden_store_fuer,
        account=angemeldet,
        operator=nur_betreiber,
        address=_adresse_fuer_programme,
        on_connected=lambda store, konto_id, partner: _verbinden.ueber_klick(partner, store, konto_id),
        old_key=_alter_schluessel,
    )
)
# Die Wege des Moduls sicherung (``/api/server/storage``), nur für Betreiber.
app.include_router(sicherung.modul_router, dependencies=NUR_ANGEMELDET)
# ⚠️ **Ohne ``NUR_ANGEMELDET``, und das ist keine Nachlaessigkeit.** Die
# Begruendung steht oben in OEFFENTLICHE_PFADE und ausfuehrlich in
# routers/bilder.py.
app.include_router(bilder_router.router)

# Server › Allgemein › Sprachen (Modul sprachen 1.0.0, E51): die eigenen Sprachen des Betreibers in
# ``<data>/locales``. Lesen ohne Anmeldung (Anmeldeseite), Hochladen und Entfernen nur der Betreiber; Ablehnungen in der
# Form des Moduls (E52, die Karte des Moduls versteht sie). Die Vorlage macht die Seite (sie kennt die englischen Texte).
from .vendor import nexsprachen  # noqa: E402
from .vendor.nexsprachen import api as nexsprachen_api  # noqa: E402


def sprachen_einrichten() -> None:
    """Beim Start: das Modul kennt nexmails Ordner und Sprachen, dann räumt es weg, was ein abgebrochenes Hochladen
    liegen ließ (``tidy_at_start``, E52). Auch der Vertragsadapter startet so neu (``restart``)."""
    nexsprachen.configure(
        nexsprachen.AppConfig(
            app_name="nexmail",
            folder=lambda: get_settings().data_dir / "locales",
            built_in={"de": "Deutsch", "en": "English"},
        )
    )
    nexsprachen.tidy_at_start()


sprachen_einrichten()
app.include_router(nexsprachen_api.router(operator=nur_betreiber))


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


#: ⚠️ **Die ``index.html`` muss jedes Mal nachgefragt werden.**
#:
#: Sie ging bisher nur mit ``ETag`` und ``Last-Modified`` hinaus, ohne
#: ``Cache-Control``. Ein Browser rechnet sich die Haltbarkeit dann selbst aus
#: (ueblich: ein Zehntel des Alters seit ``Last-Modified``) und fragt bis dahin
#: gar nicht nach. Nach einem Update zeigt er also die alte ``index.html`` —
#: und die verweist auf ``assets/index-<hash>.js``, die es nicht mehr gibt.
#: Ergebnis: **eine weisse Seite**, bis jemand von Hand hart neu laedt.
#:
#: Am 04.09.2026 genau so passiert, beim Pruefen einer neuen Funktion an einem
#: frisch gebauten Stand: Der Browser lud eine Stunde alte Stuecke, die auf der
#: Platte gar nicht mehr lagen.
#:
#: ⚠️ ``no-cache`` heisst **nicht** „nicht speichern", sondern „vor dem
#: Benutzen nachfragen". Mit dem ``ETag`` ist das ein 304 und kostet nichts.
#:
#: ⚠️ **Die Stuecke unter ``/assets`` brauchen das nicht.** Ihr Name traegt die
#: Pruefsumme des Inhalts; eine geaenderte Datei heisst anders und wird schon
#: deshalb neu geholt.
_INDEX_KOPF = {"Cache-Control": "no-cache"}

#: Dateien aus ``frontend/public``: ohne Pruefsumme im Namen, und sie aendern
#: sich mit einem Update (Manifest, Service Worker, Symbole, Favicon). Sie
#: bekommen dasselbe ``no-cache``. ⚠️ Ohne das installierte Chrome nach einem
#: neuen Symbol die Web-App mit dem alten aus dem eigenen Speicher (gesehen bei
#: Nexview 1.11.2, auch nach Deinstallieren). ``test_oberflaeche_cache.py``
#: prueft, dass jede Datei aus ``public`` hier steht.
_STETS_NACHFRAGEN = frozenset(
    {
        "manifest.webmanifest",
        "sw.js",
        "favicon.svg",
        "symbol-192.png",
        "symbol-512.png",
        "symbol-maskierbar-512.png",
        "meldung-96.png",
    }
)

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
            if pfad in _STETS_NACHFRAGEN:
                return FileResponse(datei, headers=_INDEX_KOPF)
            return FileResponse(datei)
        if _index is not None:
            return HTMLResponse(_index, headers=_INDEX_KOPF)
        return FileResponse(_frontend / "index.html", headers=_INDEX_KOPF)


# --- Ganz außen ---------------------------------------------------------- #

app.add_middleware(SicherheitskopfMiddleware)

# ⚠️ **Vor den Sicherheitskopfzeilen, damit sie jede Antwort sieht** — auch
# die, die eine Ausnahme auslöst. Ohne das fehlte ausgerechnet beim Absturz
# die Vorgangsnummer.
app.add_middleware(AppFristMiddleware)
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

# ⚠️ **Ganz aussen**: Wie die Anfrage beim Browser ankam (``X-Forwarded-Proto``),
# gilt nur hinter einem Proxy, den ``NEXMAIL_CLIENT_IP`` nennt. Ab Werk nichts.
app.add_middleware(SchemaVomProxyMiddleware)
