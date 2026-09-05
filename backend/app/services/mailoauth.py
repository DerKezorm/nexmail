"""OAuth für Google und Microsoft — Postfach **und** Kalender.

Beide Anbieter lassen Basic Auth nicht mehr zu, und beide verlangen dafür
dasselbe: eine App, die der **Betreiber** bei ihnen anlegt, und eine
Zustimmung, die der Benutzer im Browser erteilt.

⚠️ **nexmail kann kein Geheimnis mitliefern.** Das Repo ist öffentlich; ein
eingebauter Client-Schlüssel stünde darin, und Google wie Microsoft ziehen ihn
zurück, sobald sie ihn finden. Es gibt dafür keinen Trick — jeder Betreiber
legt seine eigene App an.

⚠️ **Bei Google muss die App auf „In production" stehen, nicht auf „Testing".**
Im Testbetrieb verfallen Auffrischungs-Token nach **sieben Tagen**; nexmail
verlöre dann jede Woche den Zugang, und es sähe aus wie ein kaputter
Mailserver. Der Preis von „In production" ohne Prüfung ist ein Warnbildschirm
beim Zustimmen, den man wegklickt. Die Oberfläche sagt das, bevor jemand
anfängt.

⚠️ **Eine Zustimmung, mehrere Nutzungen.** Wer sein Google-Konto freigibt,
soll nicht für den Kalender ein zweites Mal durch dieselbe Maske. Deshalb
werden **alle** Bereiche auf einmal erfragt, und ``OauthZugang`` gehört dem
Benutzer, nicht dem Postfach.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..models import Benutzer, OauthAnbieter, OauthZugang, utcnow
from ..meldung import Meldung

logger = logging.getLogger("nexmail.mailoauth")

#: Wie lange vor dem Ablauf ein Zugriffstoken erneuert wird.
#: ⚠️ **Mit Vorlauf, nicht erst beim Ablauf.** Zwischen der Prüfung und der
#: IMAP-Anmeldung liegen Sekunden, und ein gerade abgelaufenes Token sieht
#: aus wie ein falsches Passwort.
VORLAUF = timedelta(minutes=5)

ZEITGRENZE = 30.0


class OauthFehler(Meldung, RuntimeError):
    """Traegt eine KENNUNG, keinen deutschen Satz."""


@dataclass(frozen=True)
class Anbieterart:
    kennung: str
    name: str
    autorisierung: str
    token: str
    #: Was erfragt wird. ⚠️ **Alles auf einmal** — sonst muss der Benutzer für
    #: den Kalender ein zweites Mal zustimmen.
    bereiche: tuple[str, ...]
    #: Zusätzliche Parameter beim Hinweg.
    extra: dict[str, str] = field(default_factory=dict)


#: ⚠️ **Die Endpunkte stehen im Code, nicht in der Datenbank.** Wer sie
#: eintippen liesse, baut eine Fehlerquelle ohne Gewinn: Es gibt genau zwei
#: Anbieter, und ihre Adressen aendern sich nicht nach Laune.
ARTEN: dict[str, Anbieterart] = {
    "google": Anbieterart(
        kennung="google",
        name="Google",
        autorisierung="https://accounts.google.com/o/oauth2/v2/auth",
        token="https://oauth2.googleapis.com/token",
        bereiche=(
            # Postfach lesen und senden über IMAP/SMTP.
            "https://mail.google.com/",
            # Kalender über CalDAV.
            "https://www.googleapis.com/auth/calendar",
            # Kontakte über CardDAV (Beta). ⚠️ **Eine Zustimmung von vor dem
            # 05.09.2026 hat diesen Bereich nicht**; das Buch-Fenster sagt es
            # und schickt zum Neu-Verbinden, statt Google 403 sagen zu lassen.
            "https://www.googleapis.com/auth/carddav",
            # Nur, um die Adresse des Kontos zu erfahren.
            "https://www.googleapis.com/auth/userinfo.email",
        ),
        extra={
            # ⚠️ **Beides ist Pflicht für ein Auffrischungs-Token.** Ohne
            # ``access_type=offline`` gibt Google gar keines; ohne
            # ``prompt=consent`` nur beim allerersten Mal — und wer einmal
            # zugestimmt hat und neu verbindet, stünde ohne da.
            "access_type": "offline",
            "prompt": "consent",
        },
    ),
    "microsoft": Anbieterart(
        kennung="microsoft",
        name="Microsoft",
        autorisierung="https://login.microsoftonline.com/{mandant}/oauth2/v2.0/authorize",
        token="https://login.microsoftonline.com/{mandant}/oauth2/v2.0/token",
        bereiche=(
            "https://outlook.office.com/IMAP.AccessAsUser.All",
            "https://outlook.office.com/SMTP.Send",
            "offline_access",
            "openid",
            "email",
        ),
    ),
}


def _kontext(zugang_id: str, feld: str) -> str:
    return f"oauth:{zugang_id}:{feld}"


def _geheimnis_kontext(anbieter_id: str) -> str:
    return f"oauth_anbieter:{anbieter_id}:secret"


# --- Der Anbieter des Betreibers ------------------------------------------ #


def anbieter(db: Session, art: str) -> OauthAnbieter | None:
    return db.scalar(select(OauthAnbieter).where(OauthAnbieter.art == art))


def anbieter_setzen(
    db: Session, art: str, client_id: str, client_secret: str, mandant: str = "common"
) -> OauthAnbieter:
    if art not in ARTEN:
        raise OauthFehler("oauth_art_unbekannt")
    if not client_id.strip():
        raise OauthFehler("oauth_client_id_fehlt")
    eintrag = anbieter(db, art)
    if eintrag is None:
        eintrag = OauthAnbieter(art=art, client_id=client_id.strip())
        db.add(eintrag)
        db.flush()
    eintrag.client_id = client_id.strip()
    eintrag.mandant = (mandant or "common").strip()
    # ⚠️ **Nicht mitgeschickt heisst unveraendert** — dieselbe Regel wie beim
    # Passwort. Sonst verliert das Geheimnis, wer nur den Mandanten aendert.
    if client_secret:
        eintrag.client_secret = crypto.verschluesseln(
            client_secret, _geheimnis_kontext(eintrag.id)
        )
    db.commit()
    logger.info("The %s OAuth app was configured.", art)
    return eintrag


def anbieter_entfernen(db: Session, art: str) -> None:
    eintrag = anbieter(db, art)
    if eintrag is not None:
        db.delete(eintrag)
        db.commit()


def _geheimnis(eintrag: OauthAnbieter) -> str:
    if not eintrag.client_secret:
        return ""
    return crypto.entschluesseln(eintrag.client_secret, _geheimnis_kontext(eintrag.id))


# --- Der Hinweg ----------------------------------------------------------- #


def _adresse(art: Anbieterart, vorlage: str, mandant: str) -> str:
    return vorlage.format(mandant=mandant or "common")


def hinweg(
    db: Session, art: str, rueckkehr: str, anlauf: str
) -> str:
    """Die Adresse, zu der der Browser geschickt wird.

    ``anlauf`` ist der signierte Zustand (``state``) — er kommt zurück und
    beweist, dass die Rückkehr zu diesem Anlauf gehört.
    """
    eintrag = anbieter(db, art)
    if eintrag is None:
        raise OauthFehler("oauth_anbieter_fehlt")
    beschreibung = ARTEN[art]

    frage = {
        "client_id": eintrag.client_id,
        "redirect_uri": rueckkehr,
        "response_type": "code",
        "scope": " ".join(beschreibung.bereiche),
        "state": anlauf,
        **beschreibung.extra,
    }
    from urllib.parse import urlencode

    ziel = _adresse(beschreibung, beschreibung.autorisierung, eintrag.mandant)
    return f"{ziel}?{urlencode(frage)}"


# --- Der Rückweg ---------------------------------------------------------- #


def _token_anfragen(db: Session, art: str, daten: dict[str, str]) -> dict:
    eintrag = anbieter(db, art)
    if eintrag is None:
        raise OauthFehler("oauth_anbieter_fehlt")
    beschreibung = ARTEN[art]
    ziel = _adresse(beschreibung, beschreibung.token, eintrag.mandant)
    rumpf = {
        "client_id": eintrag.client_id,
        "client_secret": _geheimnis(eintrag),
        **daten,
    }
    try:
        antwort = httpx.post(ziel, data=rumpf, timeout=ZEITGRENZE)
    except httpx.HTTPError as f:
        raise OauthFehler("oauth_nicht_erreichbar") from f
    if antwort.status_code != 200:
        # ⚠️ **Der Grund des Anbieters wird protokolliert, nicht gezeigt.** Er
        # steht auf Englisch und nennt manchmal die Client-ID; in der
        # Oberflaeche waere er Fachchinesisch mit Beipack.
        logger.info("Token request to %s failed: %s %s", art, antwort.status_code, antwort.text[:300])
        raise OauthFehler("oauth_abgewiesen")
    try:
        return antwort.json()
    except ValueError as f:
        raise OauthFehler("oauth_antwort_unlesbar") from f


def _adresse_aus_token(daten: dict) -> str:
    """Die Kontoadresse aus dem ``id_token`` — ohne Unterschriftsprüfung.

    ⚠️ **Das ist hier vertretbar, bei der Anmeldung waere es ein Loch.** Das
    Token kommt gerade eben ueber TLS direkt vom Token-Endpunkt des Anbieters,
    nicht ueber den Browser; und es entscheidet nichts ueber Rechte, sondern
    liefert nur die Beschriftung des Zugangs. In ``services/oidc.py``, wo aus
    einem Ausweis eine Anmeldung wird, wird sehr wohl geprueft.
    """
    roh = daten.get("id_token") or ""
    if not roh or roh.count(".") != 2:
        return ""
    import base64
    import json

    teil = roh.split(".")[1]
    teil += "=" * (-len(teil) % 4)
    try:
        inhalt = json.loads(base64.urlsafe_b64decode(teil))
    except Exception:  # noqa: BLE001
        return ""
    wert = inhalt.get("email") or inhalt.get("preferred_username") or ""
    return str(wert)[:320]


def einloesen(
    db: Session, person: Benutzer, art: str, code: str, rueckkehr: str
) -> OauthZugang:
    """Den Code gegen Token tauschen und die Erlaubnis ablegen."""
    daten = _token_anfragen(
        db, art,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": rueckkehr},
    )
    refresh = daten.get("refresh_token") or ""
    if not refresh:
        # ⚠️ **Ohne Auffrischungs-Token ist der Zugang eine Stunde alt.** Bei
        # Google heisst das: ``access_type``/``prompt`` fehlten oder der
        # Benutzer hatte schon zugestimmt. Das jetzt zu melden ist besser als
        # in einer Stunde.
        raise OauthFehler("oauth_kein_refresh")

    adresse = _adresse_aus_token(daten)
    zugang = db.scalar(
        select(OauthZugang).where(
            OauthZugang.benutzer_id == person.id,
            OauthZugang.art == art,
            OauthZugang.adresse == adresse,
        )
    )
    if zugang is None:
        zugang = OauthZugang(benutzer_id=person.id, art=art, adresse=adresse)
        db.add(zugang)
        db.flush()

    zugang.refresh = crypto.verschluesseln(refresh, _kontext(zugang.id, "refresh"))
    _zugriff_ablegen(zugang, daten)
    zugang.bereich = daten.get("scope", "")
    zugang.letzter_fehler = ""
    db.commit()
    logger.info("An OAuth grant for %s was stored.", art)
    return zugang


def _zugriff_ablegen(zugang: OauthZugang, daten: dict) -> None:
    zugriff = daten.get("access_token") or ""
    if zugriff:
        zugang.zugriff = crypto.verschluesseln(zugriff, _kontext(zugang.id, "zugriff"))
    try:
        sekunden = int(daten.get("expires_in", 3600))
    except (TypeError, ValueError):
        sekunden = 3600
    zugang.ablauf = datetime.now(timezone.utc) + timedelta(seconds=sekunden)


def zugriffstoken(db: Session, zugang: OauthZugang) -> str:
    """Ein gültiges Zugriffstoken — bei Bedarf frisch geholt.

    ⚠️ **Das ist die Stelle, an der ein widerrufener Zugang auffällt.** Google
    zieht Auffrischungs-Token zurück, wenn der Benutzer sein Passwort ändert,
    wenn er die Erlaubnis entzieht — und nach sieben Tagen, solange die App auf
    „Testing" steht. Dann kommt ``invalid_grant``, und das muss als
    „bitte neu zustimmen" ankommen, nicht als „Mailserver kaputt".
    """
    jetzt = datetime.now(timezone.utc)
    if zugang.zugriff and zugang.ablauf and zugang.ablauf - VORLAUF > jetzt:
        return crypto.entschluesseln(zugang.zugriff, _kontext(zugang.id, "zugriff"))

    if not zugang.refresh:
        raise OauthFehler("oauth_zustimmung_fehlt")
    refresh = crypto.entschluesseln(zugang.refresh, _kontext(zugang.id, "refresh"))
    try:
        daten = _token_anfragen(
            db, zugang.art, {"grant_type": "refresh_token", "refresh_token": refresh}
        )
    except OauthFehler as f:
        if str(f) == "oauth_abgewiesen":
            zugang.letzter_fehler = "oauth_zustimmung_abgelaufen"
            db.commit()
            raise OauthFehler("oauth_zustimmung_abgelaufen") from f
        raise

    _zugriff_ablegen(zugang, daten)
    # ⚠️ **Manche Anbieter schicken ein NEUES Auffrischungs-Token mit.**
    # Microsoft tut es bei jeder Erneuerung; wer es wegwirft, faehrt weiter mit
    # dem alten und steht irgendwann ohne da.
    if daten.get("refresh_token"):
        zugang.refresh = crypto.verschluesseln(
            daten["refresh_token"], _kontext(zugang.id, "refresh")
        )
    zugang.letzter_fehler = ""
    db.commit()
    return crypto.entschluesseln(zugang.zugriff, _kontext(zugang.id, "zugriff"))


def zugaenge(db: Session, person: Benutzer) -> list[OauthZugang]:
    return list(
        db.scalars(
            select(OauthZugang)
            .where(OauthZugang.benutzer_id == person.id)
            .order_by(OauthZugang.angelegt)
        )
    )


def was_daran_haengt(db: Session, zugang: OauthZugang) -> tuple[list, list]:
    """Welche Postfächer und Kalender diese Zustimmung benutzen.

    ⚠️ **Die Zahlen gehören in die Rückfrage, nicht in den Bericht danach.**
    „2 Postfächer und 3 Kalender werden entfernt" ist eine andere Entscheidung
    als „Zustimmung entfernen"; wer das erst hinterher erfährt, hat es nicht
    entschieden.
    """
    from ..models import Adressbuch, Kalender, Konto

    konten = list(
        db.scalars(select(Konto).where(Konto.oauth_zugang_id == zugang.id))
    )
    kalender = list(
        db.scalars(select(Kalender).where(Kalender.oauth_zugang_id == zugang.id))
    )
    # ⚠️ Die Adressbuecher haengen genauso daran; ohne Zustimmung meldete jedes
    # bei jedem Takt „Zustimmung fehlt". Sie gehen beim Trennen mit, samt
    # nexmails Kopie der Kontakte, und die Rueckfrage zaehlt sie.
    buecher = list(
        db.scalars(select(Adressbuch).where(Adressbuch.oauth_zugang_id == zugang.id))
    )
    return konten, kalender, buecher


def entfernen(db: Session, person: Benutzer, zugang_id: str) -> None:
    """⚠️ Beim Anbieter bleibt die Erlaubnis bestehen — dort widerruft man sie
    selbst. nexmail vergisst nur seine Token, und die Oberfläche sagt das.

    ⚠️ **Was daran hängt, geht mit.** Die Fremdschlüssel stehen auf
    ``SET NULL``; ohne dieses Aufräumen bliebe ein Postfach ohne jeden
    Anmeldeweg stehen und meldete bei jedem Takt „Anmeldung fehlgeschlagen" —
    dieselbe Meldung wie bei einem Tippfehler im Passwort, und niemand brächte
    sie mit dem Trennen in Verbindung. Ein Kalender ebenso.
    """
    zugang = db.get(OauthZugang, zugang_id)
    if zugang is None or zugang.benutzer_id != person.id:
        raise OauthFehler("oauth_zugang_unbekannt")
    konten, kalender, buecher = was_daran_haengt(db, zugang)
    # ⚠️ Vor dem Loeschen merken: Nach dem ``commit`` ist die Zeile weg, und
    # ein Zugriff auf ``zugang.art`` schluege dann fehl.
    art, wie_viele = zugang.art, (len(konten), len(kalender), len(buecher))
    for konto in konten:
        db.delete(konto)
    for eintrag in kalender:
        db.delete(eintrag)
    for buch in buecher:
        # Dieselbe Regel wie beim Trennen eines Buches: erst die Zuordnungen
        # zu Gruppen, sonst zaehlen die Gruppen Geloeschte weiter mit.
        _buch_wegraeumen(db, buch)
    db.delete(zugang)
    db.commit()
    logger.info(
        "An OAuth grant for %s was removed, along with %d mailbox(es), %d calendar(s) "
        "and %d address book(s).",
        art, *wie_viele,
    )


def _buch_wegraeumen(db: Session, buch) -> None:
    from ..models import Kontakt
    from . import kontakte as kontaktdienst

    kontaktdienst.mitgliedschaften_loesen(
        db, select(Kontakt.id).where(Kontakt.adressbuch_id == buch.id)
    )
    db.query(Kontakt).filter(Kontakt.adressbuch_id == buch.id).delete(synchronize_session=False)
    db.delete(buch)


def xoauth2(benutzer: str, token: str) -> str:
    """Die SASL-Zeichenkette für ``AUTH XOAUTH2``.

    ⚠️ **Das Format ist starr** (``user=…^Aauth=Bearer …^A^A``); ein Byte
    daneben, und der Server antwortet mit demselben „Anmeldung fehlgeschlagen"
    wie bei einem falschen Passwort.
    """
    return f"user={benutzer}\x01auth=Bearer {token}\x01\x01"
