"""Was der Betreiber in der Oberfläche pflegt.

In Stufe 0 ist das genau eine Sache: die **öffentliche Adresse**. Sie steht
hier, weil sie ohne OIDC schon nützlich ist (Links in Mails) — und weil sie
mit OIDC zur Voraussetzung wird:

⚠️ **Ohne öffentliche Adresse lässt sich später kein OIDC-Anbieter anlegen.**
Aus ihr entsteht die Rückkehr-Adresse, die beim Anbieter hinterlegt werden
muss. Die Prüfung sitzt dann beim Anlegen des Anbieters und nicht beim ersten
Anmeldeversuch — dort träfe sie den falschen Menschen.
Siehe FALLSTRICKE.md §4.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import einstellung_lesen, einstellung_schreiben
from ..deps import AngemeldeterBenutzer, Betreiber, DbSession
from ..services import systempost
from ..services.aufraeumen import ERLAUBTE_TAGE

router = APIRouter(prefix="/api/einstellungen", tags=["einstellungen"])

SCHLUESSEL_OEFFENTLICHE_ADRESSE = "oeffentliche_adresse"
SCHLUESSEL_ZEITZONE = "zeitzone"


class Einstellungen(BaseModel):
    oeffentliche_adresse: str = Field(default="", max_length=300)
    #: IANA-Name, z. B. ``Europe/Berlin``. Leer heißt: die Zone des Browsers.
    zeitzone: str = Field(default="", max_length=80)


@router.get("", response_model=Einstellungen)
def lesen(_: AngemeldeterBenutzer, db: DbSession) -> Einstellungen:
    return Einstellungen(
        oeffentliche_adresse=einstellung_lesen(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE),
        # ⚠️ Die Umgebung ist die Rückfallebene, nicht die Wahrheit: Wer sie
        # gesetzt hat, will sie als Vorgabe - überschreiben darf die
        # Oberfläche sie trotzdem.
        zeitzone=einstellung_lesen(db, SCHLUESSEL_ZEITZONE) or get_settings().zeitzone,
    )


@router.put("", response_model=Einstellungen)
def schreiben(eingabe: Einstellungen, _: AngemeldeterBenutzer, db: DbSession) -> Einstellungen:
    adresse = eingabe.oeffentliche_adresse.strip().rstrip("/")
    if adresse:
        teile = urlsplit(adresse)
        if teile.scheme not in ("http", "https") or not teile.netloc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Die öffentliche Adresse muss mit http:// oder https:// beginnen.",
            )
    zone = eingabe.zeitzone.strip()
    if zone:
        # ⚠️ **Prüfen, nicht glauben.** Eine erfundene Zone bringt die
        # Oberfläche zum Stolpern, und der Fehler taucht erst beim Anzeigen
        # eines Datums auf — weit weg von der Stelle, an der er entstand.
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as fehler:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"„{zone}“ ist keine bekannte Zeitzone. Beispiel: Europe/Berlin.",
            ) from fehler

    einstellung_schreiben(db, SCHLUESSEL_OEFFENTLICHE_ADRESSE, adresse)
    einstellung_schreiben(db, SCHLUESSEL_ZEITZONE, zone)
    return Einstellungen(oeffentliche_adresse=adresse, zeitzone=zone)


# --- Aufraeumen: Papierkorb und Junk selbst leeren ------------------------ #


class Aufraeumen(BaseModel):
    """Aufbewahrung in Tagen — 0 heisst: nie von selbst leeren.

    ⚠️ **Je Benutzer, nicht je Installation.** Die Werte liegen als Spalten am
    Benutzer; wer hier eine gemeinsame Einstellung baut, laesst den Betreiber
    ueber die Postfaecher aller anderen entscheiden.
    """

    papierkorb_tage: int = 0
    junk_tage: int = 0


@router.get("/aufraeumen", response_model=Aufraeumen)
def aufraeumen_lesen(ich: AngemeldeterBenutzer) -> Aufraeumen:
    return Aufraeumen(
        papierkorb_tage=ich.aufraeumen_papierkorb_tage,
        junk_tage=ich.aufraeumen_junk_tage,
    )


@router.put("/aufraeumen", response_model=Aufraeumen)
def aufraeumen_schreiben(
    eingabe: Aufraeumen, ich: AngemeldeterBenutzer, db: DbSession
) -> Aufraeumen:
    # ⚠️ Eine Positivliste, keine Bereichspruefung: Die Oberflaeche bietet
    # genau diese Stufen an, und ein von Hand geschicktes „1" hiesse sonst,
    # dass morgen frueh alles von gestern endgueltig weg ist.
    for wert in (eingabe.papierkorb_tage, eingabe.junk_tage):
        if wert not in ERLAUBTE_TAGE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Die Aufbewahrung muss aus, 7, 14, 30 oder 90 Tage sein.",
            )
    ich.aufraeumen_papierkorb_tage = eingabe.papierkorb_tage
    ich.aufraeumen_junk_tage = eingabe.junk_tage
    db.commit()
    return Aufraeumen(
        papierkorb_tage=ich.aufraeumen_papierkorb_tage,
        junk_tage=ich.aufraeumen_junk_tage,
    )


# --- Der Postausgang von nexmail selbst ---------------------------------- #


class PostausgangAntwort(BaseModel):
    server: str = ""
    port: int = 587
    sicherheit: str = "starttls"
    benutzer: str = ""
    absender: str = ""
    absendername: str = "nexmail"
    #: ⚠️ Das Passwort verlaesst den Server nie — auch nicht verschluesselt.
    #: Die Oberflaeche erfaehrt nur, **dass** eines hinterlegt ist.
    passwort_liegt_vor: bool = False


class PostausgangEingabe(BaseModel):
    server: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    sicherheit: str = Field(default="starttls", max_length=16)
    benutzer: str = Field(default="", max_length=320)
    absender: str = Field(default="", max_length=320)
    absendername: str = Field(default="nexmail", max_length=120)
    #: ⚠️ ``None`` heisst **unveraendert**, "" heisst ausdruecklich „keins".
    #: Dieselbe Regel wie bei den Postfaechern: Die Oberflaeche kann ein
    #: gespeichertes Passwort nicht anzeigen und schickt deshalb nichts, wenn
    #: niemand das Feld angefasst hat.
    passwort: str | None = Field(default=None, max_length=500)


class Probe(BaseModel):
    an: str = Field(min_length=3, max_length=320)


@router.get("/postausgang", response_model=PostausgangAntwort)
def postausgang_lesen(_: Betreiber, db: DbSession) -> PostausgangAntwort:
    angaben = systempost.lesen(db)
    return PostausgangAntwort(
        server=angaben.server,
        port=angaben.port,
        sicherheit=angaben.sicherheit,
        benutzer=angaben.benutzer,
        absender=angaben.absender,
        absendername=angaben.absendername,
        passwort_liegt_vor=bool(einstellung_lesen(db, systempost.S_PASSWORT)),
    )


@router.put("/postausgang", response_model=PostausgangAntwort)
def postausgang_schreiben(
    eingabe: PostausgangEingabe, betreiber: Betreiber, db: DbSession
) -> PostausgangAntwort:
    if eingabe.sicherheit not in ("ssl", "starttls", "keine"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verschlüsselung muss SSL/TLS, STARTTLS oder keine sein.",
        )
    if eingabe.server.strip() and "@" not in eingabe.absender:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ohne Absenderadresse nimmt kein Server die Mail an.",
        )

    systempost.schreiben(
        db,
        systempost.Postausgang(
            server=eingabe.server,
            port=eingabe.port,
            sicherheit=eingabe.sicherheit,
            benutzer=eingabe.benutzer,
            absender=eingabe.absender,
            absendername=eingabe.absendername,
        ),
        eingabe.passwort,
    )
    return postausgang_lesen(betreiber, db)


@router.post("/postausgang/probe", status_code=status.HTTP_204_NO_CONTENT)
def postausgang_proben(eingabe: Probe, _: Betreiber, db: DbSession) -> None:
    """Eine Probemail verschicken.

    ⚠️ **Der Knopf ist kein Beiwerk.** Ein Postausgang, der erst bei der ersten
    Einladung scheitert, laesst den Betreiber im Glauben, sie sei unterwegs —
    und den Eingeladenen warten. Hier scheitert er sofort und mit Grund.
    """
    try:
        systempost.senden(
            db,
            eingabe.an,
            "Probe von nexmail",
            "Diese Mail bestätigt, dass nexmail selbst Post verschicken kann.\n"
            "Damit funktionieren Einladungen.\n",
        )
    except systempost.PostFehler as fehler:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(fehler)) from fehler
