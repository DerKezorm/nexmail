"""Schlagworte fuer einzelne Mails — als IMAP-Keywords.

⚠️ **Das Schlagwort lebt auf dem Mailserver, nicht in nexmail.** Gesetzt wird
es als IMAP-Keyword per STORE; damit ueberlebt es nexmail und erscheint in
Thunderbird und am Telefon. Umgekehrt gilt dasselbe: Was ein anderer Client
vergibt, holt der Abgleich hier herein — und legt fuer ein unbekanntes Atom
selbst eine Definition an, statt es unsichtbar liegen zu lassen.

⚠️ **Erst der Server, dann die eigene Datenbank** — dieselbe Regel wie in
services/handeln.py, und aus demselben Grund: Eine Anwendung, die ein
Schlagwort nur lokal merkt, macht ihrem Besitzer etwas vor. Auf dem Telefon
fehlt es, und beim naechsten Abgleich verschwindet es auch hier wieder.

⚠️ **Keywords sind ohne Gross/klein zu vergleichen** (RFC 3501). „Arbeit" und
„ARBEIT" sind auf dem Server dasselbe Flag; wer hier exakt vergleicht, legt
beim Abgleich eine zweite Definition fuer dieselbe Wahrheit an.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Benutzer, Konto, Nachricht, Schlagwort
from . import imap as imapdienst, konten as kontendienst
from ..meldung import Meldung

logger = logging.getLogger("nexmail.schlagworte")


class SchlagwortFehler(Meldung, ValueError):
    """Traegt eine KENNUNG, keinen Satz — die Oberflaeche uebersetzt sie."""


#: Dieselben sechs gepruefte Toene wie bei den Postfaechern — keine eigene
#: Palette. Siehe frontend/src/lib/farben.ts und konten.FARBEN.
FARBEN = kontendienst.FARBEN

#: ⚠️ Thunderbirds fuenf eingebaute Marken. Sie kommen als ``$label1`` bis
#: ``$label5`` an — als Name waere das ein Raetsel. Die englischen
#: Thunderbird-Namen, weil Namen nur einmal beim Anlegen entstehen und nach
#: aussen Englisch gilt; der Betreiber kann umbenennen.
THUNDERBIRD_NAMEN = {
    "$label1": "Important",
    "$label2": "Work",
    "$label3": "Personal",
    "$label4": "To Do",
    "$label5": "Later",
}

#: ⚠️ **Technische Keywords sind keine Schlagworte.** ``$Forwarded`` und
#: ``$MDNSent`` (RFC 5788), die Junk-Trias und Apples ``$has_cal`` setzt
#: Software, nicht ein Mensch — kein Client zeigt sie als Marke. Wer sie
#: uebernimmt, hat nach dem ersten Abgleich eines Bestandspostfachs eine
#: Schlagwortliste voller Maschinenkram, und die echten gehen darin unter.
TECHNISCHE_KEYWORDS = frozenset(
    k.lower()
    for k in (
        "$forwarded",
        "$mdnsent",
        "$submitted",
        "$submitpending",
        "$junk",
        "$notjunk",
        "$phishing",
        "junk",
        "nonjunk",
        "notjunk",
        "$autojunk",
        "$has_cal",
        "$has_attachment",
        "redirected",
        "forwarded",
    )
)

_VERBOTEN = re.compile(r"[^A-Za-z0-9_-]+")

#: Was Umlaute in einem Atom werden. ``str.translate`` braucht Codepunkte.
_UMSCHRIFT = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
)


def atom_aus_name(name: str) -> str:
    """Aus einem Anzeigenamen ein IMAP-taugliches Atom machen.

    Nur ``A-Za-z0-9_-``: Umlaute umgeschrieben (ae, oe, ue, ss), Leerzeichen
    zu ``_``, alles andere weg. Kollisionen loest ``anlegen`` mit einer
    angehaengten Zahl — hier entsteht nur die Rohform.
    """
    wort = name.strip().translate(_UMSCHRIFT)
    wort = re.sub(r"\s+", "_", wort)
    wort = _VERBOTEN.sub("", wort)
    # Ein Name nur aus Sonderzeichen darf kein leeres Flag ergeben — ein
    # STORE mit leerem Atom waere ein Protokollfehler beim Anbieter.
    return wort[:80] or "Schlagwort"


def ist_schlagwort_flag(flag: bytes | str) -> bool:
    """Ob ein FLAGS-Eintrag ein Schlagwort ist.

    ⚠️ **Systemflags beginnen mit ``\\`` und sind NIE Schlagworte** —
    ``\\Seen`` als Marke in der Liste waere Unsinn. Technische Keywords
    (siehe oben) ebenfalls nicht.
    """
    wort = flag.decode(errors="replace") if isinstance(flag, bytes) else str(flag)
    if not wort or wort.startswith("\\"):
        return False
    return wort.lower() not in TECHNISCHE_KEYWORDS


def atome_aus_flags(flags) -> list[str]:
    """Alle Schlagwort-Atome aus einer FLAGS-Antwort, in Serverreihenfolge."""
    heraus: list[str] = []
    for flag in flags or ():
        if not ist_schlagwort_flag(flag):
            continue
        wort = flag.decode(errors="replace") if isinstance(flag, bytes) else str(flag)
        heraus.append(wort)
    return heraus


def atome_lesen(nachricht: Nachricht) -> list[str]:
    """Die JSON-Spalte zurueck in eine Liste — Altbestand (NULL) ist leer."""
    try:
        werte = json.loads(nachricht.schlagworte or "[]")
    except ValueError:
        return []
    return [w for w in werte if isinstance(w, str)]


def naechste_farbe(db: Session, benutzer_id: str) -> int:
    """Dieselbe Vergabelogik wie bei den Postfaechern: die erste freie der
    sechs Farben, ab der siebten von vorn."""
    vergeben = set(
        db.execute(
            select(Schlagwort.farbe).where(Schlagwort.benutzer_id == benutzer_id)
        ).scalars().all()
    )
    for farbe in FARBEN:
        if farbe not in vergeben:
            return farbe
    anzahl = db.query(Schlagwort).filter(Schlagwort.benutzer_id == benutzer_id).count()
    return FARBEN[anzahl % len(FARBEN)]


def meine(db: Session, benutzer_id: str) -> list[Schlagwort]:
    """⚠️ Der eine Einschraenker — jede Abfrage auf Schlagworte geht hier durch."""
    return list(
        db.execute(
            select(Schlagwort)
            .where(Schlagwort.benutzer_id == benutzer_id)
            .order_by(Schlagwort.angelegt, Schlagwort.id)
        ).scalars().all()
    )


def eines(db: Session, benutzer_id: str, schlagwort_id: int) -> Schlagwort:
    zeile = db.get(Schlagwort, schlagwort_id)
    # Fremder Besitz meldet dasselbe wie „gibt es nicht" — sonst verraet die
    # Antwort, welche Kennungen existieren.
    if zeile is None or zeile.benutzer_id != benutzer_id:
        raise SchlagwortFehler("schlagwort_unbekannt")
    return zeile


def per_atom(db: Session, benutzer_id: str, atom: str) -> Schlagwort | None:
    """Die Definition zu einem Atom — ohne Gross/klein, wie IMAP vergleicht."""
    gesucht = atom.lower()
    for zeile in meine(db, benutzer_id):
        if zeile.atom.lower() == gesucht:
            return zeile
    return None


def definitionen_sicherstellen(db: Session, benutzer_id: str, atome) -> int:
    """Fuer fremde Atome selbst Definitionen anlegen.

    ⚠️ **Das ist der Interop-Gewinn.** Ein Keyword, das Thunderbird gesetzt
    hat, soll hier als Schlagwort erscheinen statt unsichtbar an der Mail zu
    kleben. Name = Atom (bei ``$label1``..``$label5`` der Thunderbird-Name),
    Farbe = die naechste freie. Der Betreiber benennt um, wenn ihm der Name
    nicht gefaellt — das Atom bleibt, es steht ja auf dem Server.

    Gibt zurueck, wie viele Definitionen neu entstanden sind. ⚠️ Der Aufrufer
    committet — diese Funktion laeuft mitten in Abgleich-Transaktionen.
    """
    frisch = {a for a in atome if a}
    if not frisch:
        return 0
    bekannt = {
        wert.lower()
        for wert in db.execute(
            select(Schlagwort.atom).where(Schlagwort.benutzer_id == benutzer_id)
        ).scalars()
    }
    neu = 0
    for atom in sorted(frisch):
        if atom.lower() in bekannt:
            continue
        name = THUNDERBIRD_NAMEN.get(atom.lower(), atom)
        db.add(
            Schlagwort(
                benutzer_id=benutzer_id,
                name=name,
                atom=atom,
                farbe=naechste_farbe(db, benutzer_id),
            )
        )
        # Flush, damit die Farbvergabe die eben angelegte Zeile schon sieht —
        # sonst bekaemen drei fremde Atome in einem Lauf dreimal Farbe 1.
        db.flush()
        bekannt.add(atom.lower())
        neu += 1
        logger.info("Created a tag definition for the foreign keyword '%s'.", atom)
    return neu


def anlegen(db: Session, benutzer_id: str, name: str) -> Schlagwort:
    """Eine Definition aus einem Anzeigenamen — samt Kollisionsaufloesung.

    ⚠️ Zwei Namen, die sich nur in Gross/klein unterscheiden, sind zwei
    Marken, die gleich aussehen — dieselbe Regel wie bei den
    Postfach-Schlagworten. Deshalb 409 statt einer zweiten Zeile.
    """
    sauber = name.strip()
    if not sauber:
        raise SchlagwortFehler("schlagwort_name_leer")
    vorhandene = meine(db, benutzer_id)
    if any(z.name.lower() == sauber.lower() for z in vorhandene):
        raise SchlagwortFehler("schlagwort_name_vergeben")

    atom = atom_aus_name(sauber)
    vergeben = {z.atom.lower() for z in vorhandene}
    if atom.lower() in vergeben:
        # Kollision: Zahl anhaengen, bis es passt. „Büro" und „Buero" ergeben
        # dasselbe Atom — das zweite wird Buero2.
        n = 2
        while f"{atom}{n}".lower() in vergeben:
            n += 1
        atom = f"{atom}{n}"

    zeile = Schlagwort(
        benutzer_id=benutzer_id,
        name=sauber[:100],
        atom=atom,
        farbe=naechste_farbe(db, benutzer_id),
    )
    db.add(zeile)
    db.commit()
    return zeile


def umbenennen(db: Session, benutzer_id: str, schlagwort_id: int, name: str) -> Schlagwort:
    """⚠️ Nur der Anzeige-Name. Das Atom steht auf dem Server — es umzubenennen
    hiesse, jede markierte Mail auf jedem Server anzufassen."""
    sauber = name.strip()
    if not sauber:
        raise SchlagwortFehler("schlagwort_name_leer")
    zeile = eines(db, benutzer_id, schlagwort_id)
    if any(
        z.id != zeile.id and z.name.lower() == sauber.lower()
        for z in meine(db, benutzer_id)
    ):
        raise SchlagwortFehler("schlagwort_name_vergeben")
    zeile.name = sauber[:100]
    db.commit()
    return zeile


def farbe_setzen(db: Session, benutzer_id: str, schlagwort_id: int, farbe: int) -> Schlagwort:
    if farbe not in FARBEN:
        raise SchlagwortFehler("schlagwort_farbe_unbekannt")
    zeile = eines(db, benutzer_id, schlagwort_id)
    zeile.farbe = farbe
    db.commit()
    return zeile


# --- Auf dem Server ------------------------------------------------------- #


def _keywords_erlaubt(zustand: dict) -> bool:
    """Ob der Ordner eigene Keywords annimmt.

    ⚠️ **PERMANENTFLAGS ohne ``\\*`` heisst: keine eigenen Keywords.** Manche
    Server (und manche Ordner) erlauben nur die Systemflags — ein STORE mit
    einem Keyword wuerde dort abgewiesen oder still verworfen. Fehlt die
    Angabe ganz, gelten nach RFC 3501 alle Flags als dauerhaft — dann ja.
    """
    perma = zustand.get(b"PERMANENTFLAGS")
    if perma is None:
        return True
    for flag in perma:
        wort = flag.decode(errors="replace") if isinstance(flag, bytes) else str(flag)
        if wort == "\\*":
            return True
    return False


def _uidvaliditaet_pruefen(zustand, ordner) -> None:
    """Die gespeicherten UIDs gelten nur, solange UIDVALIDITY stimmt.

    ⚠️ Nach einem Wechsel zaehlt der Server neu — ein STORE auf die alten
    UIDs traefe dann **andere** Nachrichten, wuerde mit OK beantwortet, und
    lokal wuerde die gemeinte verbucht. Der Abgleich (abgleich.py) behandelt
    genau diesen Fall als Neuaufbau; bis der gelaufen ist, wird hier
    abgelehnt statt blind gespeichert.
    """
    gueltigkeit = int(zustand.get(b"UIDVALIDITY", 0) or 0)
    if ordner.uidvalidity and gueltigkeit and gueltigkeit != ordner.uidvalidity:
        raise SchlagwortFehler("schlagwort_ordner_veraltet")


def _als_verbindungsfehler(fehler: Exception) -> Exception:
    """Einen rohen IMAP-Fehler auf stehender Verbindung deutbar machen.

    ⚠️ Der 502-Auffangbehandler in main.py faengt nur
    ``imapdienst.Verbindungsfehler`` — der entsteht sonst ausschliesslich in
    ``verbinden()``. Ein STORE oder SELECT, das auf offener Verbindung
    scheitert, kaeme als nackter 500 heraus, obwohl der Fehler hinter uns
    liegt, nicht bei uns.
    """
    if isinstance(fehler, (SchlagwortFehler, imapdienst.Verbindungsfehler)):
        return fehler
    return imapdienst.Verbindungsfehler(
        imapdienst.Fehlerart.UNERWARTET,
        "Der Mailserver hat die Änderung nicht angenommen. Versuch es noch einmal.",
        f"{type(fehler).__name__}: {fehler}",
    )


def _je_konto_und_ordner(nachrichten: list[Nachricht]):
    """Die Auswahl nach Konto und Ordner buendeln — ein SELECT je Ordner, ein
    STORE je Ordner, statt einem Umlauf je Nachricht."""
    gruppen: dict[str, dict[int, list[Nachricht]]] = defaultdict(lambda: defaultdict(list))
    for nachricht in nachrichten:
        gruppen[nachricht.konto_id][nachricht.ordner_id].append(nachricht)
    return gruppen


def zuweisen(
    db: Session, benutzer: Benutzer, nachrichten: list[Nachricht], atom: str, setzen: bool
) -> int:
    """Ein Schlagwort an Mails setzen oder von ihnen nehmen.

    ⚠️ **Erst der Server, dann lokal** — je Ordner: Erst wenn der STORE
    angenommen ist, wird die JSON-Spalte der betroffenen Zeilen nachgezogen.
    Wirft der Server, bleibt hier alles, wie es war („Eine Handlung ist erst
    fertig, wenn nexmails Datenbank es weiss" — und die darf nichts wissen,
    was der Server nie erfahren hat).
    """
    definition = per_atom(db, benutzer.id, atom)
    if definition is None:
        raise SchlagwortFehler("schlagwort_unbekannt")

    from . import abgleich  # kreisfrei erst hier: abgleich importiert diesen Dienst

    beruehrt = 0
    for konto_id, je_ordner in _je_konto_und_ordner(nachrichten).items():
        konto = db.get(Konto, konto_id)
        imap_pw, _ = kontendienst.passwoerter_lesen(konto)
        with abgleich.HALTER.schloss(konto.id):
            klient = imapdienst.fuer_konto(db, konto)
            try:
                for _ordner_id, zeilen in je_ordner.items():
                    pfad = zeilen[0].ordner.pfad
                    zustand = klient.select_folder(pfad, readonly=False)
                    _uidvaliditaet_pruefen(zustand, zeilen[0].ordner)
                    if not _keywords_erlaubt(zustand):
                        # ⚠️ Eine KENNUNG, kein Satz — die Oberflaeche
                        # uebersetzt sie in beide Sprachen.
                        raise SchlagwortFehler("schlagworte_nicht_unterstuetzt")
                    uids = [z.uid for z in zeilen]
                    if setzen:
                        klient.add_flags(uids, [definition.atom.encode()])
                    else:
                        klient.remove_flags(uids, [definition.atom.encode()])
                    # Der Server hat angenommen — erst jetzt lokal nachziehen.
                    for zeile in zeilen:
                        _lokal_nachziehen(zeile, definition.atom, setzen)
                        beruehrt += 1
                    # ⚠️ Je ORDNER festschreiben, nicht je Konto: Dieser
                    # Ordner ist auf dem Server schon durch. Scheiterte der
                    # naechste, risse ein spaeterer Commit-Punkt das hier
                    # Angenommene lokal wieder zurueck — Server und
                    # Datenbank liefen auseinander.
                    db.commit()
            except Exception as fehler:
                raise _als_verbindungsfehler(fehler) from fehler
            finally:
                try:
                    klient.logout()
                except Exception:  # noqa: BLE001
                    pass
    logger.info(
        "Keyword '%s' %s on %s message(s).",
        definition.atom,
        "set" if setzen else "removed",
        beruehrt,
    )
    return beruehrt


def _lokal_nachziehen(nachricht: Nachricht, atom: str, setzen: bool) -> None:
    werte = atome_lesen(nachricht)
    ohne = [w for w in werte if w.lower() != atom.lower()]
    if setzen:
        ohne.append(atom)
    nachricht.schlagworte = json.dumps(ohne, ensure_ascii=False)


def betroffene_zaehlen(db: Session, benutzer_id: str, atom: str) -> int:
    """Wie viele bekannte Mails das Schlagwort tragen — fuer die Rueckfrage
    vor dem Loeschen."""
    return (
        db.query(Nachricht)
        .filter(Nachricht.benutzer_id == benutzer_id, traegt_atom(atom))
        .count()
    )


def alle_zaehlen(db: Session, benutzer_id: str) -> dict[str, int]:
    """Wie oft jedes Atom vorkommt — in EINEM Durchgang.

    ⚠️ **Vorher ein Vollscan je Schlagwort.** ``GET /api/schlagworte`` rief
    ``betroffene_zaehlen`` je Zeile auf, und der ``LIKE`` auf die JSON-Spalte
    kann keinen Index nutzen: gemessen 240 ms je Schlagwort bei 250.000
    Nachrichten. Bei sechs Schlagworten war das eineinhalb Sekunden — fuer eine
    Liste, die die Oberflaeche bei jedem Oeffnen der Seite holt.

    ⚠️ **Eingeschraenkt wird in SQLite, nicht in Python.** Die allermeisten
    Nachrichten tragen gar kein Schlagwort; ohne die Bedingung wanderten alle
    250.000 Spaltenwerte herueber, nur damit Python sie verwirft.

    ⚠️ **Klein verglichen** — IMAP-Keywords gelten ohne Gross/klein, und die
    Zaehlung muss dieselbe Regel haben wie ``traegt_atom``, sonst zeigt die
    Liste eine andere Zahl als die Rueckfrage beim Loeschen.
    """
    zaehler: Counter[str] = Counter()
    zeilen = db.execute(
        select(Nachricht.schlagworte)
        .where(
            Nachricht.benutzer_id == benutzer_id,
            Nachricht.schlagworte.isnot(None),
            Nachricht.schlagworte != "",
            Nachricht.schlagworte != "[]",
        )
        .execution_options(yield_per=2_000)
    )
    for (roh,) in zeilen:
        try:
            werte = json.loads(roh or "[]")
        except ValueError:
            continue
        for w in werte:
            if isinstance(w, str):
                zaehler[w.lower()] += 1
    return dict(zaehler)


def traegt_atom(atom: str):
    """Der LIKE-Ausdruck auf die JSON-Spalte.

    Atome bestehen aus ``A-Za-z0-9_-`` — trotzdem werden die LIKE-Sonderzeichen
    maskiert: Fremde Atome kommen vom Server, und ein ``_`` darin traefe sonst
    jedes Zeichen. ``ilike``, weil IMAP-Keywords ohne Gross/klein gelten.
    """
    sicher = atom.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return Nachricht.schlagworte.ilike(f'%"{sicher}"%', escape="\\")


def loeschen(db: Session, benutzer: Benutzer, schlagwort_id: int) -> int:
    """Eine Definition loeschen — samt Keyword auf allen bekannten Mails.

    ⚠️ **Erst die Server, dann die Datenbank.** Je Konto und Ordner gebuendelt
    ein ``remove_flags``; erst wenn alle Server durch sind, faellt die
    Definition. Scheitert ein Server, bleibt sie stehen — sonst staende das
    Keyword weiter auf den Mails, waere hier aber unsichtbar und kaeme beim
    naechsten Abgleich als „fremdes Atom" prompt wieder.

    nexmail kennt nur, was es je abgeglichen hat — Mails jenseits des
    Flags-Fensters oder in nie geoeffneten Ordnern behalten ihr Keyword auf
    dem Server. Das sagt die Oberflaeche in der Rueckfrage.
    """
    definition = eines(db, benutzer.id, schlagwort_id)
    from . import abgleich

    traeger = (
        db.query(Nachricht)
        .filter(Nachricht.benutzer_id == benutzer.id, traegt_atom(definition.atom))
        .all()
    )
    for konto_id, je_ordner in _je_konto_und_ordner(traeger).items():
        konto = db.get(Konto, konto_id)
        imap_pw, _ = kontendienst.passwoerter_lesen(konto)
        with abgleich.HALTER.schloss(konto.id):
            klient = imapdienst.fuer_konto(db, konto)
            try:
                for _ordner_id, zeilen in je_ordner.items():
                    zustand = klient.select_folder(zeilen[0].ordner.pfad, readonly=False)
                    # ⚠️ Nicht wegwerfen: Nach einem UIDVALIDITY-Wechsel
                    # traefe das remove_flags andere Nachrichten.
                    _uidvaliditaet_pruefen(zustand, zeilen[0].ordner)
                    klient.remove_flags(
                        [z.uid for z in zeilen], [definition.atom.encode()]
                    )
                    for zeile in zeilen:
                        _lokal_nachziehen(zeile, definition.atom, setzen=False)
                    # Je Ordner festschreiben — wie bei ``zuweisen``.
                    db.commit()
            except Exception as fehler:
                raise _als_verbindungsfehler(fehler) from fehler
            finally:
                try:
                    klient.logout()
                except Exception:  # noqa: BLE001
                    pass

    db.delete(definition)
    db.commit()
    logger.info(
        "Tag '%s' deleted; the keyword was removed from %s known message(s).",
        definition.atom,
        len(traeger),
    )
    return len(traeger)
