"""Postfächer anlegen, prüfen, pflegen.

⚠️ **Die Passwörter gehen durch ``crypto`` und nirgendwo sonst.** Sie werden
in nexmails eigener Oberfläche eingetippt, landen verschlüsselt in der
Datenbank und verlassen den Server nie. Keine Konfigurationsdatei, keine
Umgebungsvariable — so am 31.08.2026 ausdrücklich festgelegt, und der Grund
ist gut: Ein Zugang in einer compose-Datei steht im Klartext in
``docker inspect`` und irgendwann in einem Repo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..models import Benutzer, Konto, Ordner, neue_id, utcnow
from . import anbieter as anbieterdienst
from . import imap as imapdienst

logger = logging.getLogger("nexmail.konten")

#: Sechs geprüfte Töne aus dem Design-System, in Vergabereihenfolge. Sie
#: werden **zugeteilt, nicht gewählt**: Zwei selbstgewählte, kaum
#: unterscheidbare Farben fallen erst auf, wenn man aus dem falschen Postfach
#: geantwortet hat.
FARBEN = (1, 2, 3, 4, 5, 6)


class KontoFehler(ValueError):
    pass


def _kontext(konto_id: str, feld: str) -> str:
    return f"konto:{konto_id}:{feld}"


def naechste_farbe(db: Session, benutzer: Benutzer) -> int:
    vergeben = set(
        db.execute(select(Konto.farbe).where(Konto.benutzer_id == benutzer.id)).scalars().all()
    )
    for farbe in FARBEN:
        if farbe not in vergeben:
            return farbe
    # Ab dem siebten faengt die Reihe wieder von vorn an - ehrlicher als ein
    # siebter, ungeprüfter Ton.
    return FARBEN[len(vergeben) % len(FARBEN)]


def meine(db: Session, benutzer: Benutzer) -> list[Konto]:
    """⚠️ Der eine Einschränker. Jede Abfrage auf Postfächer geht hier durch."""
    return list(
        db.execute(
            select(Konto)
            .where(Konto.benutzer_id == benutzer.id)
            .order_by(Konto.reihenfolge, Konto.angelegt)
        )
        .scalars()
        .all()
    )


def eines(db: Session, benutzer: Benutzer, konto_id: str) -> Konto:
    konto = db.get(Konto, konto_id)
    # ⚠️ Erst holen, dann den Besitzer prüfen - und bei fremdem Besitz
    # dasselbe melden wie bei „gibt es nicht". Sonst verrät die Antwort,
    # welche Kennungen existieren.
    if konto is None or konto.benutzer_id != benutzer.id:
        raise KontoFehler("Dieses Postfach gibt es nicht.")
    return konto


# --- Anlegen und Ändern -------------------------------------------------- #


@dataclass
class Zugangsdaten:
    anzeigename: str
    adresse: str
    imap_server: str
    imap_port: int
    imap_sicherheit: str
    imap_benutzer: str
    imap_passwort: str
    smtp_server: str
    smtp_port: int
    smtp_sicherheit: str
    smtp_benutzer: str
    smtp_passwort: str
    #: ⚠️ Ans Ende, weil ein Feld mit Vorgabe keinem ohne vorausgehen darf.
    #: Leer heißt: ``anzeigename`` nehmen.
    absendername: str = ""
    #: Freie Schlagworte. ``None`` heißt beim Ändern „unverändert lassen".
    tags: list[str] | None = None
    #: Statt der beiden Passwoerter: eine erteilte Zustimmung.
    #: ⚠️ **Google und Microsoft lassen nichts anderes mehr zu** — Basic Auth
    #: ueber IMAP und SMTP wird dort abgewiesen.
    oauth_zugang_id: str = ""


#: Mehr als das braucht niemand, und es hält die Pillenreihe lesbar.
TAGS_HOECHSTENS = 8
TAG_LAENGE = 24


def tags_normieren(roh: list[str] | None) -> str:
    """Aus einer Liste die gespeicherte Form machen.

    ⚠️ **Groß/klein trennt keine Gruppen.** Wer einmal „Privat" und einmal
    „privat" tippt, meint dasselbe und bekäme sonst zwei Pillen nebeneinander,
    die gleich aussehen. Verglichen wird deshalb klein geschrieben; behalten
    wird die **erste** Schreibweise, denn die hat er sich ausgesucht.
    """
    if roh is None:
        return ""
    gesehen: set[str] = set()
    heraus: list[str] = []
    for eintrag in roh:
        # Ein Komma im Schlagwort würde die Spalte zerreißen.
        wort = eintrag.replace(",", " ").strip()[:TAG_LAENGE].strip()
        if not wort or wort.lower() in gesehen:
            continue
        gesehen.add(wort.lower())
        heraus.append(wort)
        if len(heraus) >= TAGS_HOECHSTENS:
            break
    return ",".join(heraus)


def tags_lesen(konto: Konto) -> list[str]:
    """Die gespeicherte Form zurück in eine Liste."""
    return [t for t in (konto.tags or "").split(",") if t]


def _pruefen_regeln(daten: Zugangsdaten, passwort_noetig: bool = True) -> None:
    # ⚠️ Mit Zustimmung gibt es kein Passwort — und es darf auch keines geben.
    if daten.oauth_zugang_id:
        passwort_noetig = False
    if passwort_noetig and not (daten.imap_passwort and daten.smtp_passwort):
        # ⚠️ Beim Ändern ist ein leeres Feld erlaubt und heißt „unverändert" —
        # beim Anlegen wäre es ein Postfach ohne Zugang.
        raise KontoFehler("Ohne Passwort kann sich nexmail nicht anmelden.")
    if "@" not in daten.adresse:
        raise KontoFehler("Das sieht nicht nach einer E-Mail-Adresse aus.")
    if not daten.imap_server or not daten.smtp_server:
        raise KontoFehler("Ohne Serveradressen geht es nicht.")
    for sicherheit in (daten.imap_sicherheit, daten.smtp_sicherheit):
        if sicherheit not in ("ssl", "starttls"):
            raise KontoFehler("Verschlüsselung muss SSL/TLS oder STARTTLS sein.")
    for port in (daten.imap_port, daten.smtp_port):
        if not 1 <= port <= 65535:
            raise KontoFehler("Der Port liegt außerhalb des Möglichen.")


def anlegen(db: Session, benutzer: Benutzer, daten: Zugangsdaten) -> Konto:
    _pruefen_regeln(daten)

    if db.execute(
        select(Konto).where(
            Konto.benutzer_id == benutzer.id,
            func.lower(Konto.adresse) == daten.adresse.strip().lower(),
        )
    ).scalar_one_or_none():
        raise KontoFehler("Dieses Postfach ist schon eingerichtet.")

    hoechste = db.execute(
        select(func.max(Konto.reihenfolge)).where(Konto.benutzer_id == benutzer.id)
    ).scalar()

    konto = Konto(
        # ⚠️ **Die Kennung wird hier gesetzt, nicht dem Vorgabewert überlassen.**
        # SQLAlchemy vergibt ``default=neue_id`` erst beim Einfügen - bis
        # dahin ist ``konto.id`` schlicht ``None``. Verschlüsselt man vorher,
        # lautet der Kontext ``konto:None:imap_passwort``, nach dem Einfügen
        # aber ``konto:<uuid>:…``, und das Passwort ist nicht mehr lesbar.
        # Genau so ist es beim ersten Lauf passiert.
        id=neue_id(),
        benutzer_id=benutzer.id,
        anzeigename=daten.anzeigename.strip() or daten.adresse.split("@")[0],
        absendername=daten.absendername.strip(),
        adresse=daten.adresse.strip(),
        imap_server=daten.imap_server.strip(),
        imap_port=daten.imap_port,
        imap_sicherheit=daten.imap_sicherheit,
        imap_benutzer=daten.imap_benutzer.strip(),
        oauth_zugang_id=daten.oauth_zugang_id or None,
        smtp_server=daten.smtp_server.strip(),
        smtp_port=daten.smtp_port,
        smtp_sicherheit=daten.smtp_sicherheit,
        smtp_benutzer=daten.smtp_benutzer.strip(),
        tags=tags_normieren(daten.tags),
        farbe=naechste_farbe(db, benutzer),
        reihenfolge=(hoechste or 0) + 1,
    )
    # ⚠️ Erst die Kennung, dann verschlüsseln: Sie fährt als Zusatzdaten mit,
    # und ohne sie ließe sich der Wert an eine andere Stelle kopieren.
    konto.imap_passwort = crypto.verschluesseln(
        daten.imap_passwort, _kontext(konto.id, "imap_passwort")
    )
    konto.smtp_passwort = crypto.verschluesseln(
        daten.smtp_passwort, _kontext(konto.id, "smtp_passwort")
    )

    db.add(konto)
    db.commit()
    logger.info("A mailbox was added.")
    return konto


def aendern(db: Session, benutzer: Benutzer, konto_id: str, daten: Zugangsdaten) -> Konto:
    """Ein bestehendes Postfach ändern.

    ⚠️ **Ein leeres Passwortfeld heißt „unverändert", nicht „leer".** Die
    Oberfläche zeigt ein gespeichertes Passwort nie an — sie kann es gar
    nicht. Würde ein leeres Feld übernommen, verlöre jeder, der nur den
    Anzeigenamen ändert, seinen Zugang. Genau daran scheitern reihenweise
    Anwendungen mit Zugangsdaten-Formularen.

    ⚠️ **Die Adresse darf nicht mit einem anderen Postfach kollidieren** —
    sonst stünde dasselbe Konto zweimal da, und der Abgleich liefe zweimal.
    """
    konto = eines(db, benutzer, konto_id)
    _pruefen_regeln(daten, passwort_noetig=False)

    neue_adresse = daten.adresse.strip()
    doppelt = db.execute(
        select(Konto).where(
            Konto.benutzer_id == benutzer.id,
            func.lower(Konto.adresse) == neue_adresse.lower(),
            Konto.id != konto.id,
        )
    ).scalar_one_or_none()
    if doppelt is not None:
        raise KontoFehler("Ein anderes Postfach hat diese Adresse schon.")

    konto.anzeigename = daten.anzeigename.strip() or neue_adresse.split("@")[0]
    konto.absendername = daten.absendername.strip()
    konto.adresse = neue_adresse
    konto.imap_server = daten.imap_server.strip()
    konto.imap_port = daten.imap_port
    konto.imap_sicherheit = daten.imap_sicherheit
    konto.imap_benutzer = daten.imap_benutzer.strip()
    konto.smtp_server = daten.smtp_server.strip()
    konto.smtp_port = daten.smtp_port
    konto.smtp_sicherheit = daten.smtp_sicherheit
    konto.smtp_benutzer = daten.smtp_benutzer.strip()
    # ⚠️ ``None`` heißt „nicht mitgeschickt" — wie beim Passwort. Eine leere
    # Liste heißt dagegen ausdrücklich „alle Schlagworte weg".
    if daten.tags is not None:
        konto.tags = tags_normieren(daten.tags)

    if daten.imap_passwort:
        konto.imap_passwort = crypto.verschluesseln(
            daten.imap_passwort, _kontext(konto.id, "imap_passwort")
        )
    if daten.smtp_passwort:
        konto.smtp_passwort = crypto.verschluesseln(
            daten.smtp_passwort, _kontext(konto.id, "smtp_passwort")
        )

    db.commit()
    logger.info("A mailbox was changed.")
    return konto


def absendername(konto: Konto) -> str:
    """Was im ``From`` einer ausgehenden Mail steht.

    ⚠️ **Nicht der Name aus der Ordnerspalte.** Wer sein Postfach dort
    „Arbeit" nennt, verschickte sonst Post von einem Absender namens
    „Arbeit". Leer heißt: den Anzeigenamen nehmen — so bleibt es für alle,
    die vor dieser Trennung eingerichtet haben, wie es war.
    """
    return (konto.absendername or "").strip() or konto.anzeigename


def passwoerter_lesen(konto: Konto) -> tuple[str, str]:
    return (
        crypto.entschluesseln(konto.imap_passwort, _kontext(konto.id, "imap_passwort")),
        crypto.entschluesseln(konto.smtp_passwort, _kontext(konto.id, "smtp_passwort")),
    )


def entfernen(
    db: Session, benutzer: Benutzer, konto_id: str, *, kalender_mit: bool = False
) -> None:
    """⚠️ **Die Kalender haengen an der Zustimmung, nicht am Postfach.**

    Sie hier immer mitzunehmen waere falsch — dieselbe Zustimmung kann ein
    zweites Postfach tragen, und ein Kalender mit eigenen Terminen ist nichts,
    was nebenbei verschwindet. Sie immer stehen zu lassen ist aber auch falsch:
    Wer beides in einem Zug angelegt hat, haelt den Kalender danach fuer ein
    Waisenkind — genau so am 03.09.2026 gemeldet. Also entscheidet es der
    Mensch beim Entfernen, und die Vorgabe ist **stehen lassen**.
    """
    konto = eines(db, benutzer, konto_id)
    wie_viele = 0
    if kalender_mit and konto.oauth_zugang_id:
        from ..models import Kalender

        for kalender in db.scalars(
            select(Kalender).where(Kalender.oauth_zugang_id == konto.oauth_zugang_id)
        ):
            db.delete(kalender)
            wie_viele += 1
    db.delete(konto)
    db.commit()
    logger.info("A mailbox was removed, along with %d calendar(s).", wie_viele)


# --- Verbindung prüfen --------------------------------------------------- #


@dataclass
class Teilbefund:
    ok: bool
    art: str = ""
    text: str = ""


@dataclass
class Befund:
    imap: Teilbefund
    smtp: Teilbefund
    ordner: list[imapdienst.Ordnerangabe]
    faehigkeiten: list[str]

    @property
    def ok(self) -> bool:
        return self.imap.ok and self.smtp.ok


def pruefen(daten: Zugangsdaten, app_passwort_wo: str = "", token: str = "") -> Befund:
    """Beide Wege prüfen — **und beide melden**, nicht nur den ersten Fehler.

    ⚠️ Wer beim ersten Fehler abbricht, schickt den Betreiber durch zwei
    Runden: erst IMAP reparieren, dann erfahren, dass SMTP auch nicht ging.
    Bei iCloud ist genau das der Normalfall, weil dort die Benutzernamen
    verschieden sind.
    """
    ordner: list[imapdienst.Ordnerangabe] = []
    koennen: list[str] = []

    try:
        # ⚠️ Hier gibt es noch kein Postfach — der Verbindungstest laeuft
        # vor dem Anlegen, mit den Daten aus dem Formular.
        klient = imapdienst.verbinden(
            daten.imap_server, daten.imap_port, daten.imap_sicherheit,
            daten.imap_benutzer, daten.imap_passwort, app_passwort_wo, token=token,
        )
        try:
            koennen = imapdienst.faehigkeiten(klient)
            ordner = imapdienst.ordner_lesen(klient)
            imap_befund = Teilbefund(ok=True)
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass
    except imapdienst.Verbindungsfehler as fehler:
        imap_befund = Teilbefund(ok=False, art=fehler.art, text=fehler.text)

    try:
        imapdienst.smtp_pruefen(
            daten.smtp_server,
            daten.smtp_port,
            daten.smtp_sicherheit,
            daten.smtp_benutzer,
            daten.smtp_passwort,
            app_passwort_wo,
            token=token,
        )
        smtp_befund = Teilbefund(ok=True)
    except imapdienst.Verbindungsfehler as fehler:
        smtp_befund = Teilbefund(ok=False, art=fehler.art, text=fehler.text)

    return Befund(imap=imap_befund, smtp=smtp_befund, ordner=ordner, faehigkeiten=koennen)


def ordner_uebernehmen(db: Session, konto: Konto, angaben: list[imapdienst.Ordnerangabe]) -> None:
    """Die gelesene Ordnerliste in die Datenbank spiegeln.

    Vorhandene Zeilen werden aktualisiert, verschwundene entfernt. ``uidvalidity``
    und die Zähler bleiben unangetastet - die holt erst der Abgleich.
    """
    vorhanden = {o.pfad: o for o in konto.ordner}
    gesehen = set()

    for angabe in angaben:
        gesehen.add(angabe.pfad)
        zeile = vorhanden.get(angabe.pfad)
        if zeile is None:
            zeile = Ordner(konto_id=konto.id, pfad=angabe.pfad)
            db.add(zeile)
        zeile.name = angabe.name
        zeile.rolle = angabe.rolle
        zeile.waehlbar = angabe.waehlbar
        zeile.abonniert = "abonniert" in angabe.kennzeichen

    for pfad, zeile in vorhanden.items():
        if pfad not in gesehen:
            db.delete(zeile)

    konto.zuletzt_geprueft = utcnow()
    konto.letzter_fehler = ""
    konto.letzter_fehler_art = ""
    db.commit()


def vorschlag_fuer(adresse: str) -> anbieterdienst.Vorschlag | None:
    return anbieterdienst.vorschlagen(adresse)
