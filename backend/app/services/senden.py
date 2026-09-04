"""Senden — und die Warteschlange, die einen Neustart übersteht.

Der Ablauf ist absichtlich in dieser Reihenfolge:

    1. Mail bauen und **auf die Platte legen**
    2. Zeile im Ausgang anlegen
    3. senden
    4. in „Gesendet" ablegen **und den Ordner abgleichen**
    5. Zeile auf „gesendet" setzen

⚠️ **Erst ablegen, dann senden.** Wer zuerst sendet und dann speichert,
verliert bei einem Absturz dazwischen keine Mail — sondern weiß nur nicht mehr,
dass sie draußen ist, und schickt sie beim nächsten Lauf ein zweites Mal.
Umgekehrt ist der schlimmste Fall eine Mail, die im Ausgang liegt und noch
einmal versucht wird.

⚠️ **``APPEND`` in „Gesendet" ist nicht optional.** Ohne ihn steht die
gesendete Mail nur in nexmail und in keinem anderen Client — auf dem Telefon
sieht es aus, als hätte man nie geantwortet.
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.utils import getaddresses
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Ausgang, Konto, neue_id, utcnow
from . import abgleich, imap as imapdienst, konten as kontendienst
from .verfassen import Entwurf, bauen
from ..meldung import Meldung

logger = logging.getLogger("nexmail.senden")

#: Wie oft ein Versand wiederholt wird, bevor er als gescheitert gilt. Danach
#: bleibt die Mail im Ausgang stehen und wartet auf eine Hand.
MAX_VERSUCHE = 5

#: Um wie viele Minuten ein **geplanter** Versand nach einem Fehlschlag
#: verschoben wird — je Versuch der nächste Wert. ⚠️ Ohne die Verschiebung
#: griffe der Versandplan (Minutentakt) denselben Eintrag jede Minute wieder
#: und verbrennte alle fünf Versuche in fünf Minuten; ein zehnminütiger
#: SMTP-Schluckauf zur Planzeit ließe die Mail dann dauerhaft liegen.
GEPLANT_VERZOEGERUNG_MINUTEN = (2, 5, 15, 30)


class SendeFehler(Meldung, RuntimeError):
    pass


class AbbruchKollision(RuntimeError):
    """Der Eintrag ist nicht mehr abzubrechen — der Versand hat ihn schon."""


def ausgangsordner() -> Path:
    ordner = get_settings().data_dir / "ausgang"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def _datei(kennung: str) -> Path:
    return ausgangsordner() / f"{kennung}.eml"


def einreihen(
    db: Session, konto: Konto, entwurf: Entwurf, senden_ab: datetime | None = None
) -> Ausgang:
    """Bauen, ablegen, in die Warteschlange stellen — noch nichts senden.

    ``senden_ab`` haelt den Eintrag bis zu diesem Zeitpunkt (UTC) zurueck.
    """
    roh, message_id = bauen(entwurf)

    kennung = neue_id()
    _datei(kennung).write_bytes(roh)

    alle_empfaenger = [
        *entwurf.an,
        *entwurf.kopie,
        *entwurf.blindkopie,
    ]
    zeile = Ausgang(
        id=kennung,
        benutzer_id=konto.benutzer_id,
        konto_id=konto.id,
        stand="wartet",
        an_json=json.dumps(alle_empfaenger, ensure_ascii=False),
        betreff=entwurf.betreff,
        message_id=message_id,
        senden_ab=senden_ab,
    )
    db.add(zeile)
    db.commit()
    logger.info("A message was queued for sending.")
    return zeile


def faellig_bedingung():
    """Nur was dran ist: ohne ``senden_ab``, oder mit einem in der Vergangenheit.

    ⚠️ **Diese Bedingung ist der ganze Aufschub.** Jede Abfrage, die Wartendes
    hinausschickt, muss sie tragen — ohne sie ginge eine fuer morgen geplante
    Mail beim naechsten Neustart sofort hinaus.
    """
    return or_(Ausgang.senden_ab.is_(None), Ausgang.senden_ab <= utcnow())


def _in_gesendet_ablegen(db: Session, konto: Konto, roh: bytes) -> bool:
    """Die gesendete Mail ins Postfach legen — **und gleich zurückholen**.

    Findet sich kein „Gesendet"-Ordner, wird nichts abgelegt und ``False``
    gemeldet — das ist kein Grund, den Versand als gescheitert zu behandeln.
    Die Mail ist draußen; sie fehlt nur in der Ablage.

    ⚠️ **Der Abgleich danach ist kein Beiwerk.** ``APPEND`` legt die Mail beim
    Anbieter ab, nicht in nexmails Datenbank. Ohne den Abgleich bleibt
    „Gesendet" leer, bis jemand von Hand aktualisiert — und wer gerade
    geantwortet hat, sieht seine Antwort nirgends und schickt sie ein zweites
    Mal. Genau das ist am 31.08.2026 passiert.

    Der Abgleich läuft **auf derselben Verbindung und unter demselben
    Schloss** wie der ``APPEND``. Das ist Vorgabe, nicht Bequemlichkeit: Apple
    erlaubt nur eine IMAP-Verbindung je Postfach.
    """
    gesendet = next((o for o in konto.ordner if o.rolle == "gesendet"), None)
    if gesendet is None:
        logger.info("No sent folder for this mailbox; the copy is skipped.")
        return False

    imap_pw, _ = kontendienst.passwoerter_lesen(konto)
    with abgleich.HALTER.schloss(konto.id):
        klient = imapdienst.fuer_konto(db, konto)
        try:
            klient.append(gesendet.pfad, roh, [rb"\Seen"], datetime.now(timezone.utc))
            abgleich.ordner_abgleichen(klient, db, konto, gesendet)
            db.commit()
        finally:
            try:
                klient.logout()
            except Exception:  # noqa: BLE001
                pass
    return True


def versenden(db: Session, zeile: Ausgang) -> None:
    """Einen Eintrag der Warteschlange tatsächlich hinausschicken."""
    datei = _datei(zeile.id)
    if not datei.is_file():
        zeile.stand = "gescheitert"
        zeile.letzter_fehler = "Die vorbereitete Nachricht liegt nicht mehr auf der Platte."
        db.commit()
        raise SendeFehler(zeile.letzter_fehler)

    konto = db.get(Konto, zeile.konto_id)
    if konto is None:
        zeile.stand = "gescheitert"
        zeile.letzter_fehler = "Das Postfach gibt es nicht mehr."
        db.commit()
        raise SendeFehler(zeile.letzter_fehler)

    roh = datei.read_bytes()
    empfaenger = json.loads(zeile.an_json or "[]")
    _, smtp_pw = kontendienst.passwoerter_lesen(konto)

    # ⚠️ **Die Zeile wird beansprucht, nicht einfach beschrieben.** Ein
    # bedingtes UPDATE, das nur greift, wenn niemand dazwischenkam: Der
    # Abbruch (``abbrechen``) läuft in einem anderen Faden mit eigener
    # Session — ohne diese Bedingung konnten „Rückgängig" in letzter Sekunde
    # und der Versandplan **beide** gewinnen, und die Mail ging trotz eines
    # gemeldeten Abbruchs hinaus. SQLite serialisiert Schreiber; von zwei
    # bedingten UPDATEs greift damit genau eines.
    beansprucht = db.execute(
        update(Ausgang)
        .where(Ausgang.id == zeile.id, Ausgang.stand.in_(["wartet", "unterwegs", "gescheitert"]))
        .values(stand="unterwegs", versuche=Ausgang.versuche + 1)
    )
    db.commit()
    if not beansprucht.rowcount:
        # Abgebrochen oder schon von anderer Hand versandt — nichts mehr tun.
        db.expire_all()
        raise SendeFehler("eintrag_zurueckgenommen")
    db.refresh(zeile)

    try:
        _smtp_senden(konto, smtp_pw, empfaenger, roh)
    except Exception as fehler:  # noqa: BLE001
        zeile.stand = "gescheitert" if zeile.versuche >= MAX_VERSUCHE else "wartet"
        zeile.letzter_fehler = str(fehler)[:500]
        # ⚠️ **Geplantes rueckt nach hinten statt sofort wieder dran zu sein.**
        # Der Versandplan sieht jede Minute nach; ohne Verschiebung waeren
        # alle fuenf Versuche nach fuenf Minuten verbraucht. Gewoehnliche
        # Sendungen (ohne ``senden_ab``) bleiben unangetastet — die wiederholt
        # ohnehin nur der Start oder ein Klick.
        if zeile.stand == "wartet" and zeile.senden_ab is not None:
            minuten = GEPLANT_VERZOEGERUNG_MINUTEN[
                min(zeile.versuche, len(GEPLANT_VERZOEGERUNG_MINUTEN)) - 1
            ]
            zeile.senden_ab = utcnow() + timedelta(minutes=minuten)
        db.commit()
        logger.warning("Sending failed (attempt %s): %s", zeile.versuche, fehler)
        raise SendeFehler(str(fehler)) from fehler

    # Ab hier ist die Mail draußen. Alles Weitere darf sie nicht mehr
    # zurückholen - deshalb wird der Stand **zuerst** gesetzt.
    zeile.stand = "gesendet"
    zeile.gesendet = utcnow()
    zeile.letzter_fehler = ""
    db.commit()

    try:
        _in_gesendet_ablegen(db, konto, roh)
    except Exception as fehler:  # noqa: BLE001
        # ⚠️ Kein Fehler nach außen: Die Mail ist versandt. Wer hier abbricht,
        # bringt den Benutzer dazu, sie ein zweites Mal zu schicken.
        logger.warning("The message was sent but could not be filed in Sent: %s", fehler)

    datei.unlink(missing_ok=True)


def _xoauth2_anmelden(verbindung, benutzer: str, token: str) -> None:
    """``AUTH XOAUTH2`` von Hand — ``smtplib`` kennt das Verfahren nicht.

    ⚠️ **Base64 ohne Zeilenumbrueche.** ``encodebytes`` haengt alle 76 Zeichen
    ein ``
`` an; ein Zugriffstoken ist laenger als das, und der Server sieht
    dann eine abgeschnittene Zeile und meldet „Anmeldung fehlgeschlagen".
    """
    import base64

    from .mailoauth import xoauth2

    roh = base64.b64encode(xoauth2(benutzer, token).encode("utf-8")).decode("ascii")
    code, antwort = verbindung.docmd("AUTH", f"XOAUTH2 {roh}")
    if code not in (235, 503):
        # ⚠️ Der Server erwartet nach einer Absage noch eine leere Zeile,
        # sonst haengt die Verbindung.
        verbindung.docmd("")
        raise smtplib.SMTPAuthenticationError(code, antwort)


def _smtp_senden(
    konto: Konto, passwort: str, empfaenger: list[str], roh: bytes, token: str = ""
) -> None:
    """⚠️ **Mit ``token`` wird XOAUTH2 gesprochen.** Microsoft weist Basic Auth
    beim Senden seit Fruehjahr 2026 ab, Google laengst; ein ``login()`` mit
    Zugriffstoken bekaeme dieselbe Absage wie ein falsches Passwort."""
    import ssl

    if konto.smtp_sicherheit == "ssl":
        verbindung = smtplib.SMTP_SSL(konto.smtp_server, konto.smtp_port, timeout=30)
    else:
        verbindung = smtplib.SMTP(konto.smtp_server, konto.smtp_port, timeout=30)
        verbindung.starttls(context=ssl.create_default_context())
    try:
        if token:
            _xoauth2_anmelden(verbindung, konto.smtp_benutzer, token)
        else:
            verbindung.login(konto.smtp_benutzer, passwort)
        # ⚠️ Die Empfängerliste kommt hier her, nicht aus den Kopfzeilen -
        # sonst bekäme eine Blindkopie nie etwas.
        verbindung.sendmail(konto.adresse, empfaenger, roh)
    finally:
        try:
            verbindung.quit()
        except Exception:  # noqa: BLE001
            pass


def warteschlange_abarbeiten(db: Session) -> dict[str, int]:
    """Alles Wartende noch einmal versuchen. Beim Start und nach Bedarf.

    ⚠️ Auch „unterwegs" wird wieder aufgenommen: Dieser Stand bedeutet, dass
    der Prozess mitten im Versand abgebrochen ist. Die Mail könnte draußen
    sein - deshalb zählt der Versuch mit, und nach MAX_VERSUCHE bleibt sie
    liegen, statt endlos wiederholt zu werden.
    """
    # ⚠️ „abgebrochen" ist ein Zwischenstand von ``abbrechen`` und lebt nur
    # Sekunden. Steht er beim Start noch da, ist der Prozess mitten im Abbruch
    # gestorben — ob der Entwurf schon abgelegt wurde, weiss niemand. Deshalb
    # zurueck auf „gescheitert": Der Eintrag bleibt sichtbar liegen und wartet
    # auf eine Hand, statt entweder stumm zu verschwinden oder doch noch
    # hinauszugehen.
    haengen = db.execute(
        update(Ausgang)
        .where(Ausgang.stand == "abgebrochen")
        .values(stand="gescheitert", letzter_fehler="Der Abbruch wurde unterbrochen.")
    )
    db.commit()
    if haengen.rowcount:
        logger.warning("Recovered %s entry(ies) from an interrupted cancellation.", haengen.rowcount)

    offen = (
        db.execute(
            select(Ausgang).where(
                Ausgang.stand.in_(["wartet", "unterwegs"]),
                # ⚠️ Geplantes bleibt liegen, bis es dran ist - sonst hebelte
                # jeder Neustart „morgen 08:00" aus.
                faellig_bedingung(),
            )
        )
        .scalars()
        .all()
    )
    ergebnis = {"versucht": 0, "gesendet": 0, "liegen": 0}
    for zeile in offen:
        ergebnis["versucht"] += 1
        try:
            versenden(db, zeile)
            ergebnis["gesendet"] += 1
        except SendeFehler:
            # Der erwartete Fall: Der Mailserver nimmt sie gerade nicht.
            ergebnis["liegen"] += 1
        except Exception:  # noqa: BLE001
            # ⚠️ **Alles andere darf die Schleife nicht abbrechen.** Bis
            # zum 03.09.2026 stand hier nur ``except SendeFehler``. Ein
            # anderer Fehler bei der k-ten Mail liess die uebrigen liegen —
            # und beim Start noch mehr: ``warteschlange_abarbeiten`` laeuft im
            # Lebenslauf ohne eigenes ``try``, eine Ausnahme dort haette also
            # nexmail gar nicht erst hochkommen lassen. Genau dieselbe Falle
            # wie beim Abgleich am 03.09.2026, nur einen Dienst weiter.
            #
            # Zurueckgerollt wird zuerst: Sonst laeuft die naechste Zeile in
            # dieselbe gesperrte Sitzung.
            db.rollback()
            ergebnis["liegen"] += 1
            logger.exception("Sending queue entry %s hit an unexpected error.", zeile.id)
    return ergebnis


def faellige_geplante(db: Session) -> int:
    """Geplante Eintraege hinausschicken, deren Zeit gekommen ist.

    Laeuft im Takt des Versandplans (``takt.versandplan_starten``). Bewusst
    **nur** Eintraege mit ``senden_ab``: Ein gewoehnlicher Versand, der
    liegen blieb, wird wie bisher beim Start und auf Klick wiederholt - ihn
    hier alle paar Sekunden erneut zu versuchen wuerde seine fuenf Versuche
    in Minuten verbrennen.
    """
    faellige = (
        db.execute(
            select(Ausgang).where(
                Ausgang.stand == "wartet",
                Ausgang.senden_ab.is_not(None),
                Ausgang.senden_ab <= utcnow(),
            )
        )
        .scalars()
        .all()
    )
    raus = 0
    for zeile in faellige:
        try:
            versenden(db, zeile)
            raus += 1
        except SendeFehler:
            # Steht schon in der Zeile - und der Eintrag bleibt sichtbar
            # liegen, samt dem Satz des Servers.
            pass
    if raus:
        logger.info("Sent %s scheduled message(s).", raus)
    return raus


def _mit_blindkopie(roh: bytes, empfaenger: list[str]) -> bytes:
    """Blindkopien in den kuenftigen Entwurf zurueckschreiben.

    ⚠️ **Die fertige Mail traegt absichtlich keine ``Bcc``-Kopfzeile** — sonst
    waere „blind" nie blind gewesen. Beim Abbrechen kehrt sich das um: Ein
    Entwurf soll seine Blindkopie kennen, sonst verloere der Abbruch
    stillschweigend Empfaenger. Wer in der Empfaengerliste steht, aber in
    keiner Kopfzeile, war Blindkopie.
    """
    nachricht = message_from_bytes(roh)
    sichtbar = {
        adresse.lower()
        for _, adresse in getaddresses(
            nachricht.get_all("To", []) + nachricht.get_all("Cc", [])
        )
        if adresse
    }
    blind = [a for a in empfaenger if a.lower() not in sichtbar]
    if not blind:
        return roh
    # Vor die uebrigen Kopfzeilen gestellt statt neu zusammengebaut: Ein
    # erneutes Serialisieren koennte an Kodierungen nur verlieren.
    return b"Bcc: " + ", ".join(blind).encode("ascii", "ignore") + b"\r\n" + roh


def abbrechen(db: Session, zeile: Ausgang) -> int:
    """Einen wartenden Eintrag zuruecknehmen — der Inhalt wird Entwurf.

    Gibt die UID des abgelegten Entwurfs zurueck (0, wenn nichts mehr
    aufzubewahren war). ⚠️ Ohne sie hinge der wieder geoeffnete Inhalt an
    keiner Entwurfs-UID — jedes „Rueckgaengig" hinterliesse dauerhaft eine
    Sicherheits-Fassung im Entwurfsordner, die niemand mehr wegraeumt.

    ⚠️ **Zuerst wird die Zeile beansprucht** — dasselbe bedingte UPDATE wie in
    ``versenden``, nur in die andere Richtung. Der Versandfaden laeuft mit
    eigener Session: Wer nur den in der Request-Session gelesenen Stand
    prueft, kann „wartet" sehen, waehrend der Faden die Zeile schon auf
    „unterwegs" hebt — dann gingen Versand und Abbruch **beide** durch, die
    Mail waere draussen und der Aufrufer bekaeme trotzdem ein „zurueckgeholt".
    Greift das UPDATE nicht, fliegt ``AbbruchKollision``.

    ⚠️ **Erst der Entwurf, dann das Entfernen.** Umgekehrt kostet ein Absturz
    dazwischen die Nachricht. So ist der schlimmste Fall ein Entwurf, dessen
    Ausgangseintrag noch dasteht — aergerlich, aber nichts ist weg.

    Scheitert das Ablegen (etwa: kein Entwurfsordner), bekommt der Eintrag
    seinen alten Stand zurueck und der Fehler geht nach oben.
    """
    from . import entwuerfe as entwurfsdienst

    vorher = zeile.stand
    beansprucht = db.execute(
        update(Ausgang)
        .where(Ausgang.id == zeile.id, Ausgang.stand.in_(["wartet", "gescheitert"]))
        .values(stand="abgebrochen")
    )
    db.commit()
    if not beansprucht.rowcount:
        db.expire_all()
        raise AbbruchKollision(
            "Die Nachricht ist schon unterwegs und lässt sich nicht mehr zurückholen."
        )

    konto = db.get(Konto, zeile.konto_id)
    datei = _datei(zeile.id)
    entwurf_uid = 0
    if konto is not None and datei.is_file():
        roh = _mit_blindkopie(datei.read_bytes(), json.loads(zeile.an_json or "[]"))
        try:
            entwurf_uid = entwurfsdienst.roh_ablegen(db, konto, roh)
        except Exception:
            # Der Eintrag bleibt liegen, mit seinem alten Stand — ihn im
            # Beanspruchungs-Stand zu lassen hiesse, dass ihn weder der
            # Versandplan noch ein zweiter Abbruchversuch je wieder anfasst.
            db.execute(
                update(Ausgang).where(Ausgang.id == zeile.id).values(stand=vorher)
            )
            db.commit()
            raise
    else:
        # Ohne Datei oder Postfach gibt es nichts mehr aufzubewahren - dann
        # ist Entfernen alles, was der Abbruch noch tun kann.
        logger.warning("A queued message was cancelled without content to preserve.")

    db.delete(zeile)
    db.commit()
    datei.unlink(missing_ok=True)
    logger.info("A queued message was cancelled; its content was stored as a draft.")
    return entwurf_uid


def aufraeumen(db: Session) -> int:
    """Verwaiste Dateien im Ausgang wegwerfen.

    Eine ``.eml`` ohne Zeile in der Datenbank gehört zu nichts mehr - etwa
    nach einer Wiederherstellung aus einer älteren Sicherung.
    """
    bekannt = {
        f"{kennung}.eml"
        for kennung in db.execute(select(Ausgang.id)).scalars().all()
    }
    weg = 0
    for datei in ausgangsordner().glob("*.eml"):
        if datei.name not in bekannt:
            datei.unlink(missing_ok=True)
            weg += 1
    if weg:
        logger.info("Removed %s orphaned message file(s) from the outbox.", weg)
    return weg
