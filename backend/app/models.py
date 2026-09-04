"""Die Tabellen von nexmail.

⚠️ **Jede Tabelle mit persoenlichen Daten traegt ``benutzer_id``** - auch
solange es nur einen Benutzer gibt. Mehrbenutzer ist zugesagt, und
nachtraeglich waere es ein Umbau durch jede Abfrage. Siehe FALLSTRICKE.md §5.

⚠️ **Zwei Sorten Primaerschluessel, mit Grund.** Was ein Geheimnis traegt
(``benutzer``, spaeter ``konto``), bekommt eine Zeichenkette aus ``uuid4`` -
sie steht **vor** dem Einfuegen fest und kann deshalb als Zusatzdaten in die
Verschluesselung wandern (siehe crypto.py). Alles, wovon es spaeter
Hunderttausende gibt (``nachricht``, ``ordner``), bekommt eine Zahl: 32
Zeichen je Zeile waeren dort messbarer Ballast.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Zeitstempel, die auch nach dem Lesen eine Zeitzone haben.

    ⚠️ **SQLite speichert keine Zeitzone** - auch nicht bei
    ``DateTime(timezone=True)``. Beim Lesen kommt ein naiver Wert zurueck, und
    der erste Vergleich mit ``utcnow()`` scheitert mit "can't compare
    offset-naive and offset-aware datetimes". Genau daran ist der erste
    Testlauf hier gescheitert.

    Es an der Vergleichsstelle zu flicken waere falsch: Dann traefe es bei der
    naechsten Spalte wieder, und man haette zwei Sorten Zeitstempel im selben
    Programm. Der Typ nimmt alles in UTC entgegen und gibt alles in UTC
    zurueck - eine Stelle, ein Verhalten.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, wert, dialect):  # noqa: ARG002
        if wert is None:
            return None
        if wert.tzinfo is None:
            # Ein naiver Wert von aussen ist ein Fehler, aber kein Grund
            # abzustuerzen - er wird als UTC gelesen.
            return wert
        return wert.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, wert, dialect):  # noqa: ARG002
        if wert is None:
            return None
        return wert.replace(tzinfo=timezone.utc)


def neue_id() -> str:
    return uuid.uuid4().hex


class Benutzer(Base):
    """Ein Mensch, der sich anmeldet.

    ⚠️ **``passwort_hash`` darf leer sein.** Das ist keine Nachlaessigkeit,
    sondern die Vorbereitung auf OIDC: Passwort ist *ein* Anmeldeweg, nicht
    *der*. Waere das Feld verpflichtend, waere reines OIDC spaeter ein Umbau
    am Kern statt einer Ergaenzung. Siehe FALLSTRICKE.md §4.
    """

    __tablename__ = "benutzer"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    benutzername: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    anzeigename: Mapped[str] = mapped_column(String(120), default="")

    #: Argon2id. Leer heisst: Dieser Benutzer meldet sich anders an.
    passwort_hash: Mapped[str] = mapped_column(Text, default="")

    #: ⚠️ Der Haken, nicht die Rolle. Er sagt nicht, was dieser Benutzer darf,
    #: sondern was **andere** mit ihm nicht duerfen. Er entsteht beim Anlegen
    #: des ersten Kontos - wer nexmail aufsetzt, muss dafuer nichts wissen.
    ist_betreiber: Mapped[bool] = mapped_column(Boolean, default=False)

    #: Wohin ein Ruecksetz-Link geht, wenn dieser Mensch sein Kennwort
    #: vergessen hat. **Nicht** eines seiner Postfaecher: Am 04.09.2026 so
    #: entschieden — die Adresse fuer Kontosachen bleibt getrennt und wird
    #: ausdruecklich gesetzt.
    #:
    #: ⚠️ **Leer heisst: kein Weg zurueck.** Wer sie nie eintraegt, kommt nach
    #: einem vergessenen Kennwort nicht mehr hinein — und merkt das erst im
    #: Ernstfall. Deshalb traegt eine Einladung sie gleich mit ein, und die
    #: Sicherheitsseite sagt deutlich, wenn keine dasteht.
    kontaktadresse: Mapped[str] = mapped_column(String(320), default="")

    # --- Der KI-Dienst dieses Menschen ---------------------------------- #
    #
    # ⚠️ **Je Benutzer, nicht je Installation.** Wer umformulieren lassen will,
    # bringt seinen eigenen Zugang mit — dann zahlt jeder seinen eigenen
    # Schluessel, und der Betreiber muss niemandem etwas vorgeben. Dieselbe
    # Ueberlegung wie beim OAuth-Zugang, der auch am Benutzer haengt.
    #
    # ⚠️ **Ab Werk aus.** nexmail blockt Zaehlpixel, liefert Schriften mit und
    # holt Bilder ueber den eigenen Server; hier geht Text nach draussen. Das
    # ist eine Entscheidung, die ein Mensch trifft, kein Vorgabewert.
    ki_aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Die Basisadresse, OpenAI-foermig. Mit Schraegstrich am Ende, damit
    #: ``urljoin`` daraus ``…/models`` und ``…/chat/completions`` macht.
    ki_url: Mapped[str] = mapped_column(String(500), default="")
    ki_modell: Mapped[str] = mapped_column(String(200), default="")
    #: Verschluesselt, Kontext ``benutzer:<id>:ki``. Er oeffnet ein fremdes
    #: Konto mit einer Rechnung daran — also ein Passwort.
    ki_schluessel: Mapped[str] = mapped_column(Text, default="")

    #: TOTP-Geheimnis, verschluesselt (Kontext ``benutzer:<id>:totp``).
    totp_geheimnis: Mapped[str] = mapped_column(Text, default="")
    totp_bestaetigt: Mapped[bool] = mapped_column(Boolean, default=False)

    #: ⚠️ Der zuletzt angenommene Zeitschritt. Ohne ihn gilt ein abgefangener
    #: Code noch dreissig Sekunden lang ein zweites Mal.
    totp_letzter_schritt: Mapped[int] = mapped_column(Integer, default=0)

    #: Aufbewahrung in Tagen fuer Papierkorb und Junk — 0 heisst: nie von
    #: selbst leeren. ⚠️ **Die Vorgabe ist aus, mit Absicht:** Ein Mail-Client,
    #: der ungefragt endgueltig loescht, macht genau den Schrecken, den ein
    #: Datenverlust macht. Wer es einschaltet, hat die Folge gelesen.
    aufraeumen_papierkorb_tage: Mapped[int] = mapped_column(Integer, default=0)
    aufraeumen_junk_tage: Mapped[int] = mapped_column(Integer, default=0)
    #: Wann die letzte Aufraeumrunde fuer diesen Benutzer lief — dasselbe
    #: Muster wie ``sicherung_zuletzt`` beim Sicherungs-Zeitplan, nur je
    #: Benutzer als Spalte statt als Einstellungs-Schluessel.
    aufraeumen_zuletzt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    #: „Bilder immer anzeigen" — der globale Schalter unter Darstellung.
    #: ⚠️ **Im Server, obwohl Darstellung sonst im Browser wohnt.** Das hier
    #: ist keine Frage des Bildschirms, sondern eine Entscheidung ueber die
    #: eigene Post: Wer sie am Arbeitsrechner still anders vorfaende als zu
    #: Hause, wuesste nie, warum ein Absender einmal Bescheid weiss und einmal
    #: nicht. Vorgabe aus — wer sie einschaltet, hat den Satz daneben gelesen.
    bilder_immer_laden: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Web Push --------------------------------------------------------- #
    #
    # ⚠️ **Wobei gemeldet wird, gehoert dem Benutzer; ob ueberhaupt, dem
    # Geraet.** Die Erlaubnis erteilt jeder Browser fuer sich, und sie steht
    # deshalb in ``PushAnmeldung``. Was eine Meldung ausloest, ist dagegen eine
    # Entscheidung ueber die eigene Post — wer sie am Telefon anders vorfaende
    # als am Rechner, wuesste nie, warum es einmal klingelt und einmal nicht.
    # Dieselbe Trennung wie bei ``bilder_immer_laden`` daneben.
    push_termine: Mapped[bool] = mapped_column(Boolean, default=True)
    push_mail: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Aus heisst: nur der Posteingang. ⚠️ **Das ist die Vorgabe, mit Absicht.**
    #: Was eine Regel ins Archiv geraeumt hat, hat der Benutzer weggeordnet;
    #: eine Meldung darueber macht die Regel wertlos.
    push_mail_alle_ordner: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Eine Mail, die auf einem anderen Geraet schon gelesen wurde, kommt beim
    #: Abgleich trotzdem als „neu" herein.
    push_mail_nur_ungelesen: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Eine Meldung je Abgleichrunde statt einer je Nachricht.
    push_mail_buendeln: Mapped[bool] = mapped_column(Boolean, default=True)

    #: ⚠️ **Als Text, nicht als Uhrzeit.** „Ab 22 Uhr Ruhe" ist eine Aussage
    #: ueber die Ortszeit des Betreibers, nicht ueber einen Zeitstempel — genau
    #: dieselbe Ueberlegung wie beim Zeitraum der Abwesenheitsnotiz.
    push_ruhezeit: Mapped[bool] = mapped_column(Boolean, default=False)
    push_ruhezeit_von: Mapped[str] = mapped_column(String(5), default="22:00")
    push_ruhezeit_bis: Mapped[str] = mapped_column(String(5), default="07:00")

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    sitzungen: Mapped[list["Sitzung"]] = relationship(
        back_populates="benutzer", cascade="all, delete-orphan"
    )
    push_anmeldungen: Mapped[list["PushAnmeldung"]] = relationship(
        back_populates="benutzer", cascade="all, delete-orphan"
    )
    codes: Mapped[list["Wiederherstellungscode"]] = relationship(
        back_populates="benutzer", cascade="all, delete-orphan"
    )
    oidc: Mapped[list["OidcVerknuepfung"]] = relationship(
        back_populates="benutzer", cascade="all, delete-orphan"
    )


class Kennwortruecksetzung(Base):
    """Ein ausgesprochener Ruecksetz-Link, den noch niemand benutzt hat.

    ⚠️ **Der Schluessel liegt nur als Hash da.** Er steht in einer Mail und
    setzt ein Kennwort — das ist ein Passwort, kein Datensatz-Merkmal.
    Dieselbe Regel wie bei der Einladung und den Wiederherstellungscodes.

    ⚠️ **Kurze Gueltigkeit, kuerzer als bei einer Einladung.** Eine Einladung
    wartet auf einen Menschen, der vielleicht erst am Wochenende Zeit hat. Ein
    Ruecksetz-Link entsteht, weil jemand **gerade jetzt** vor der Tuer steht.
    """

    #: ⚠️ **Nicht „kennwortruecksetzung".** Der Passwortzensor im Protokoll
    #: schwaerzt alles hinter „kennwort" — der Tabellenname stand beim Start
    #: als ``kennwort*****`` in der Schema-Zeile, und ein Protokoll, das einen
    #: Tabellennamen verbirgt, kostet bei der Fehlersuche Zeit.
    __tablename__ = "ruecksetzung"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    schluessel_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    laeuft_ab: Mapped[datetime] = mapped_column(UtcDateTime)
    #: Wann er benutzt wurde. ``None`` heisst: noch offen.
    eingeloest: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)


class Wiederherstellungscode(Base):
    """Der Weg zurueck, wenn das Telefon weg ist.

    Nur als Hash gespeichert. SHA-256 genuegt hier und Argon2 waere falsch
    am Platz: Diese Codes sind 128 Bit Zufall, es gibt nichts zu raten - der
    einzige Zweck des Hashes ist, dass ein gestohlener Datenbestand sie nicht
    verraet.
    """

    __tablename__ = "wiederherstellungscode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    verbraucht: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    benutzer: Mapped[Benutzer] = relationship(back_populates="codes")


class Sitzung(Base):
    """Eine Anmeldung.

    ⚠️ **Der Zustand liegt im Server, nicht im Token.** Ein JWT gilt bis zum
    Ablauf, egal was passiert; hier kostet jede Anfrage eine Abfrage und
    bringt dafuer, was zaehlt: "auf allen Geraeten abmelden" wirkt sofort.

    ⚠️ **Im Cookie steht ein Zufallswert, in der Datenbank sein Hash.** Wer die
    Datei liest, bekommt keine gueltigen Sitzungen in die Hand.
    """

    __tablename__ = "sitzung"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    #: ⚠️ Falsch, solange nur das Passwort stimmt. Eine unbestaetigte Sitzung
    #: darf ausschliesslich den zweiten Schritt aufrufen - sonst waere der
    #: zweite Faktor eine Zierde.
    bestaetigt: Mapped[bool] = mapped_column(Boolean, default=False)

    geraet: Mapped[str] = mapped_column(String(200), default="")
    adresse: Mapped[str] = mapped_column(String(64), default="")

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    gueltig_bis: Mapped[datetime] = mapped_column(UtcDateTime)

    benutzer: Mapped[Benutzer] = relationship(back_populates="sitzungen")


class OidcVerknuepfung(Base):
    """Verbindung zwischen einem Benutzer und einer fremden Identitaet.

    ⚠️ **Verknuepft wird ueber ``issuer`` + ``subject``, nie ueber die
    E-Mail-Adresse.** Adressen wechseln den Besitzer, ``subject`` nicht. Wer
    ueber die Adresse verknuepft, baut eine Kontouebernahme ein.

    Steht ab Stufe 0 leer da. Gebaut wird OIDC spaeter - aber wenn die Tabelle
    erst dann entsteht, entsteht mit ihr eine Wanderung der Bestandsdaten.
    """

    __tablename__ = "oidc_verknuepfung"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_oidc_identitaet"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    issuer: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    adresse_bestaetigt: Mapped[bool] = mapped_column(Boolean, default=False)
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    benutzer: Mapped[Benutzer] = relationship(back_populates="oidc")


class Konto(Base):
    """Ein Postfach.

    ⚠️ **Der Primaerschluessel ist eine uuid4-Zeichenkette**, nicht eine Zahl.
    Er steht damit **vor** dem Einfuegen fest und kann als Zusatzdaten in die
    Verschluesselung der beiden Passwoerter wandern (``konto:<id>:imap_passwort``).
    Ohne das liesse sich ein verschluesseltes Passwort von einem Postfach auf
    ein anderes kopieren, und die Entschluesselung merkte nichts.

    ⚠️ **IMAP und SMTP haben getrennte Benutzernamen.** Bei den meisten
    Anbietern sind sie gleich - bei iCloud nicht: Apple will beim Posteingang
    nur den Namensteil und beim Postausgang die vollstaendige Adresse. Wer hier
    ein Feld spart, kann bei iCloud lesen aber nicht senden, und die
    Fehlermeldung ist in beiden Faellen dieselbe wie bei einem Tippfehler.
    """

    __tablename__ = "konto"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )

    #: ⚠️ **Zwei Namen, zwei Zwecke.** ``anzeigename`` steht in der
    #: Ordnerspalte und in den Listen - er darf „Privat" oder „Arbeit"
    #: heissen. ``absendername`` steht im ``From`` jeder Mail, die hinausgeht,
    #: und den liest der Empfaenger. Ein Feld fuer beides hiess: Wer sein
    #: Postfach in der Spalte „Arbeit" nennt, verschickte Post von „Arbeit".
    anzeigename: Mapped[str] = mapped_column(String(120))

    #: ⚠️ **Abgewiesene Zugangsdaten duerfen nicht stumm bleiben.** Der Takt
    #: versuchte es bis zum 02.09.2026 alle zwei Minuten neu, und niemand
    #: erfuhr davon - aufgefallen, als ein geaendertes iCloud-Passwort einfach
    #: keine neuen Mails mehr brachte. Hier steht 'anmeldung', sobald der
    #: Server die Anmeldung ablehnt, und wieder '', sobald sie gelingt. Die
    #: Oberflaeche macht daraus den roten Banner.
    stoerung: Mapped[str] = mapped_column(String(20), default="")
    #: Leer heisst: ``anzeigename`` nehmen. So bleibt es fuer alle, die vor
    #: dieser Trennung eingerichtet haben, wie es war.
    absendername: Mapped[str] = mapped_column(String(120), default="")
    adresse: Mapped[str] = mapped_column(String(320))

    # --- Abwesenheitsnotiz, je Postfach ---------------------------------- #
    #
    # ⚠️ **Je Postfach, nicht je Benutzer.** Die Antwort geht ueber dessen
    # Postausgang und mit dessen Adresse hinaus, und dienstlich schreibt man
    # kaum dasselbe wie privat. Am 02.09.2026 so entschieden.
    abwesenheit_aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ⚠️ **Datum als Zeichenkette (``JJJJ-MM-TT``), nicht als Zeitstempel.**
    #: „Bis einschliesslich den 14." ist eine Aussage ueber einen KALENDERTAG
    #: in der Zeitzone des Betreibers, kein Zeitpunkt. Als UTC-Zeitstempel
    #: gespeichert waere die Notiz je nach Zeitzone einen halben Tag zu frueh
    #: oder zu spaet aus — genau die Sorte Fehler, die erst im Urlaub auffaellt.
    abwesenheit_von: Mapped[str] = mapped_column(String(10), default="")
    #: Leer heisst: laeuft, bis jemand den Schalter umlegt.
    abwesenheit_bis: Mapped[str] = mapped_column(String(10), default="")
    abwesenheit_betreff: Mapped[str] = mapped_column(String(300), default="")
    #: Reiner Text, kein HTML. Eine Abwesenheitsnotiz ist kurz und sachlich,
    #: und formatierte Post an Fremde, die niemand gegenliest, ist eine
    #: Fehlerquelle ohne Gewinn.
    abwesenheit_text: Mapped[str] = mapped_column(Text, default="")

    imap_server: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    #: "ssl" oder "starttls"
    imap_sicherheit: Mapped[str] = mapped_column(String(16), default="ssl")
    imap_benutzer: Mapped[str] = mapped_column(String(320))
    imap_passwort: Mapped[str] = mapped_column(Text, default="")

    smtp_server: Mapped[str] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_sicherheit: Mapped[str] = mapped_column(String(16), default="starttls")
    smtp_benutzer: Mapped[str] = mapped_column(String(320))
    smtp_passwort: Mapped[str] = mapped_column(Text, default="")

    #: Leer heisst Passwort. ⚠️ **Der Anmeldeweg gehoert ans Postfach, nicht an
    #: den Anbieter:** Dasselbe Google-Konto laesst sich mit App-Passwort ODER
    #: mit OAuth anbinden, und wer umstellt, soll nicht alles neu eintragen.
    oauth_zugang_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("oauth_zugang.id", ondelete="SET NULL"), default=None
    )

    #: 1 bis 6 - der Punkt in der Liste. Wird zugeteilt, nicht gewaehlt.
    #: Freie Schlagworte, kommagetrennt — „privat,verein".
    #:
    #: ⚠️ **Bewusst eine Spalte statt einer eigenen Tabelle.** Gefiltert wird
    #: in der Oberfläche über eine Handvoll Postfächer; es gibt keine Abfrage,
    #: die nach einem Schlagwort sucht. Eine Nebentabelle brächte hier einen
    #: Verbund und eine Migration und nichts sonst. Wer je nach Schlagwort
    #: suchen will, hat den Punkt erreicht, an dem sich die Tabelle lohnt.
    tags: Mapped[str] = mapped_column(String(255), default="")
    #: Zusaetzliche Absenderadressen als JSON — ``[{"adresse": …, "name": …}]``.
    #:
    #: ⚠️ **Eine Spalte, keine Nebentabelle** — dieselbe Ueberlegung wie oben
    #: bei ``tags``: eine Handvoll je Postfach, und keine Abfrage sucht danach.
    #: Beim Antworten wird in Python ueber die paar Adressen gegangen.
    aliase: Mapped[str] = mapped_column(Text, default="[]")
    farbe: Mapped[int] = mapped_column(Integer, default=1)
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    zuletzt_geprueft: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    letzter_fehler: Mapped[str] = mapped_column(Text, default="")
    #: ⚠️ **Die Kennung, nicht nur der Satz.** ``letzter_fehler`` traegt den
    #: deutschen Satz des Servers - die Oberflaeche zeigte ihn woertlich, auf
    #: Englisch blieb er deutsch, und das Abzeichen schnitt ihn nach 40
    #: Zeichen ab („abgewie"). Am 02.09.2026 aufgefallen. Der Server benennt
    #: (``Fehlerart``), die Oberflaeche uebersetzt - wie bei OIDC.
    letzter_fehler_art: Mapped[str] = mapped_column(String(30), default="")

    #: Ob dieses Postfach schon einmal vollstaendig abgeglichen wurde.
    #:
    #: ⚠️ **Nur fuer die Benachrichtigungen, und dort unentbehrlich.** Beim
    #: ersten Abgleich ist **jede** Mail neu; ein frisch eingerichtetes
    #: Postfach mit 8.000 Nachrichten meldete sonst „8.000 neue Nachrichten"
    #: — oder, ohne Buendelung, achttausendmal. Die erste Runde setzt die
    #: Marke und meldet nichts.
    #:
    #: ⚠️ **Bestehende Postfaecher fangen ebenfalls bei ``False`` an**, denn
    #: ``_fehlende_spalten`` legt die Spalte mit der Vorgabe an. Sie
    #: verschlucken damit **eine** Runde nach dem Update. Das ist der billige
    #: Fehler von beiden: Andersherum bekaeme jeder beim ersten Start nach dem
    #: Update eine Meldung ueber seinen halben Posteingang.
    erstabgleich_durch: Mapped[bool] = mapped_column(Boolean, default=False)

    benutzer: Mapped[Benutzer] = relationship()
    ordner: Mapped[list["Ordner"]] = relationship(
        back_populates="konto", cascade="all, delete-orphan"
    )
    #: Nur zum Anzeigen: Die Kachel in den Einstellungen sagt damit, ob dieses
    #: Postfach ueber Google, ueber Microsoft oder ueber IMAP angebunden ist —
    #: und wie viele Kalender an derselben Zustimmung haengen.
    #: ``selectin``, damit die Kontenliste nicht je Postfach nachfragt.
    oauth_zugang: Mapped["OauthZugang | None"] = relationship(lazy="selectin")


class Ordner(Base):
    """Ein Ordner im Postfach.

    ⚠️ **``uidvalidity`` ist keine Zierde.** Aendert der Server sie, ist die
    gesamte lokale Zuordnung von Nummern zu Nachrichten wertlos und der Ordner
    muss neu geholt werden. Das ist der Fall, den fast jeder Eigenbau
    uebersieht - deshalb steht die Spalte hier, bevor die erste Nachricht
    geholt wird.

    Zahl als Primaerschluessel: Hiervon gibt es spaeter viele, und es steckt
    kein Geheimnis darin.
    """

    __tablename__ = "ordner"
    __table_args__ = (UniqueConstraint("konto_id", "pfad", name="uq_ordner_pfad"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    konto_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("konto.id", ondelete="CASCADE"), index=True
    )

    #: Der Pfad, wie der Server ihn nennt - "INBOX", "Sent Messages", "Haus/Rechnungen".
    pfad: Mapped[str] = mapped_column(String(512))
    #: Was in der Oberflaeche steht - der letzte Teil des Pfades.
    name: Mapped[str] = mapped_column(String(255))
    #: posteingang | gesendet | entwuerfe | archiv | junk | papierkorb | eigen
    rolle: Mapped[str] = mapped_column(String(16), default="eigen")

    abonniert: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Ob der Ordner Nachrichten aufnehmen kann. Manche Server haben reine
    #: Zwischenknoten ("\Noselect"), die nur Unterordner tragen.
    waehlbar: Mapped[bool] = mapped_column(Boolean, default=True)

    uidvalidity: Mapped[int] = mapped_column(Integer, default=0)
    hoechste_uid: Mapped[int] = mapped_column(Integer, default=0)
    anzahl: Mapped[int] = mapped_column(Integer, default=0)
    ungelesen: Mapped[int] = mapped_column(Integer, default=0)
    #: Ob die Wichtigkeit des Bestands einmal nachgezogen wurde. Die Spalte
    #: ``wichtigkeit`` kam nach den ersten Abgleichen dazu — alle Zeilen davor
    #: standen auf „normal", waehrend identische neue Mails ihr „!" bekamen.
    #: Der Abgleich holt die Kopfzeilen dafuer **einmal** fuer die juengsten
    #: Nachrichten nach (dasselbe Fenster wie die Flags) und setzt dann diesen
    #: Merker; aeltere heilt das Oeffnen der Mail.
    wichtigkeit_nachgezogen: Mapped[bool] = mapped_column(Boolean, default=False)

    konto: Mapped[Konto] = relationship(back_populates="ordner")


class Nachricht(Base):
    """Eine Nachricht.

    ⚠️ **Kopfdaten immer, Texte auf Abruf.** ``koerper_text`` und
    ``koerper_html`` sind leer, bis jemand die Nachricht oeffnet. Wer beim
    ersten Abgleich alles holt, wartet bei vierzigtausend Mails Stunden und
    hat danach Gigabyte auf der Platte - gemessen sind Kopfdaten rund fuenf
    Kilobyte je Nachricht, bereinigtes HTML von Newslettern gern das
    Zwanzigfache.

    ⚠️ **``uid`` gilt nur zusammen mit der ``uidvalidity`` des Ordners.**
    Aendert der Server sie, ist die Zuordnung wertlos - siehe Ordner.
    """

    __tablename__ = "nachricht"
    __table_args__ = (
        UniqueConstraint("ordner_id", "uid", name="uq_nachricht_uid"),
        Index("ix_nachricht_liste", "ordner_id", "datum"),
        # ⚠️ Teilindex fuer die Ungelesen-Zaehler. Gemessen: ohne ihn 12,8 ms
        # je Ordner, mit ihm 0,05 ms - bei 120 Ordnern der Unterschied
        # zwischen fluessig und sekundenlang blockiert.
        Index("ix_nachricht_ungelesen", "ordner_id", sqlite_where=text("gelesen = 0")),
        # ⚠️ **Der Ordnerbaum, und der Teilindex darueber traegt ihn
        # nicht.** ``routers/konten.py`` zaehlt je Postfach Gesamtzahl UND
        # Ungelesene in einer Gruppenabfrage, eingeschraenkt auf ``konto_id``.
        # Damit ist ``ix_nachricht_ungelesen`` aussen vor (er steht allein auf
        # ``ordner_id``), und SQLite laeuft ueber ``ix_nachricht_konto_id`` samt
        # einem TEMP B-TREE fuer die Gruppierung. Gemessen am 03.09.2026 bei
        # 250.000 Nachrichten: 373,6 ms fuer den ganzen Baum. Mit diesem
        # Deckindex 36,1 ms, Plan ``SEARCH ... USING COVERING INDEX``, und die
        # Datenbank waechst um 6,1 Prozent.
        #
        # ⚠️ **Die 5,6 ms in CLAUDE.md galten einer anderen Abfrage.**
        # Sie stammen von der reinen Ungelesen-Zaehlung ueber ``ordner_id``; die
        # Gesamtzahl kam am 02.09.2026 dazu und hat den Teilindex ausgeschlossen.
        # Der Baum wird nach jedem Handgriff geholt, nicht nur beim Start.
        Index("ix_nachricht_zaehlen", "konto_id", "ordner_id", "gelesen"),
        # ⚠️ **Die Ansicht, die jeder nach der Anmeldung zuerst sieht.**
        # „Alle Posteingaenge" schraenkt auf ``benutzer_id`` ein und sortiert
        # nach ``datum``; ``ix_nachricht_liste`` ist ``(ordner_id, datum)`` und
        # taugt nur fuer EINEN Ordner. Ohne diesen Index sortiert SQLite den
        # ganzen Bestand des Benutzers, um 60 Zeilen zu zeigen: gemessen
        # 1.145 ms bei 250.000 Nachrichten, mit ihm 0,7 ms. Er traegt auch den
        # Merkpunkt beim Weiterblaettern und den Filter „markiert" ueber alle
        # Postfaecher.
        Index("ix_nachricht_zeitachse", "benutzer_id", "datum"),
        # ⚠️ **Aufgaben und Wiedervorlage finden ihre Mail hierueber.**
        # Beide zeigen mit der ``message_id`` auf die Nachricht, weil eine
        # Zeilennummer den naechsten Abgleich nicht ueberlebt (siehe Aufgabe).
        # Auf ``nachricht`` hatte die Spalte keinen Index, also wurde je Eintrag
        # der halbe Bestand abgesucht: gemessen 180 ms je Aufgabe bei 250.000
        # Nachrichten, bei zwanzig Aufgaben 3,5 s. Der teuerste Fall ist die
        # verwaiste Aufgabe, weil dann alles abgesucht wird, ohne etwas zu
        # finden.
        Index("ix_nachricht_message_id", "benutzer_id", "message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    konto_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("konto.id", ondelete="CASCADE"), index=True
    )
    ordner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ordner.id", ondelete="CASCADE"), index=True
    )

    uid: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str] = mapped_column(String(500), default="")
    #: Woran zwei Nachrichten als zusammengehoerig erkannt werden. Wird
    #: mitgeschrieben, obwohl v1 flach anzeigt - spaeter waere es eine
    #: Wanderung ueber Hunderttausende Zeilen.
    thread_key: Mapped[str] = mapped_column(String(500), default="", index=True)
    #: ``References`` und ``In-Reply-To``, durch Leerzeichen getrennt.
    #: Gebraucht, um Straenge nachtraeglich neu aufbauen zu koennen — ohne die
    #: Kopfzeilen muesste dafuer jede Mail neu vom Server geholt werden.
    referenzen: Mapped[str] = mapped_column(Text, default="")
    #: Der Betreff ohne „Re:", „AW:", „Fwd:" — klein geschrieben. Der Rueckfall,
    #: wenn eine Mail keine Antwortkette mitbringt.
    betreff_kern: Mapped[str] = mapped_column(String(500), default="", index=True)

    von_name: Mapped[str] = mapped_column(String(320), default="")
    von_adresse: Mapped[str] = mapped_column(String(320), default="", index=True)
    an_json: Mapped[str] = mapped_column(Text, default="[]")
    kopie_json: Mapped[str] = mapped_column(Text, default="[]")

    betreff: Mapped[str] = mapped_column(Text, default="")
    datum: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: Wann diese Zeile in diesen Ordner gekommen ist — beim Abgleich gesetzt.
    #: ⚠️ **Das ist die Verweildauer-Uhr des Aufraeumens.** ``datum`` ist das
    #: Absendedatum aus der ``Date``-Kopfzeile; wer den Papierkorb daran
    #: bemisst, loescht eine heute weggeworfene Januar-Mail sofort und
    #: endgueltig. Verschieben legt beim naechsten Abgleich eine neue Zeile an
    #: (siehe ``handeln.verschieben``) — die Uhr startet damit von selbst neu.
    #: Zeilen von vor dieser Spalte fuellt der Start einmalig auf „jetzt"
    #: (``main.lebenslauf``), die Rueckholfrist beginnt fuer sie also neu —
    #: die sichere Richtung.
    angekommen: Mapped[datetime | None] = mapped_column(UtcDateTime, default=utcnow)
    groesse: Mapped[int] = mapped_column(Integer, default=0)

    gelesen: Mapped[bool] = mapped_column(Boolean, default=False)
    markiert: Mapped[bool] = mapped_column(Boolean, default=False)
    beantwortet: Mapped[bool] = mapped_column(Boolean, default=False)
    #: JSON-Liste der Schlagwort-Atome (IMAP-Keywords) dieser Nachricht.
    #: ⚠️ **Die Wahrheit liegt auf dem Server** — hier steht nur, was der
    #: Abgleich zuletzt gesehen hat. Gesetzt und entfernt wird deshalb immer
    #: erst per STORE beim Anbieter, dann hier (siehe services/schlagworte.py).
    schlagworte: Mapped[str] = mapped_column(Text, default="[]")
    hat_anhang: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Traegt die Mail einen ``text/calendar``-Teil? Aus ``BODYSTRUCTURE``
    #: abgelesen, ohne den Koerper zu holen.
    #:
    #: ⚠️ **Ohne diese Spalte muesste der Abgleich jede Mail herunterladen**,
    #: nur um nachzusehen, ob eine Antwort auf eine Einladung darin steckt.
    hat_kalender: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ``hoch`` | ``normal`` | ``niedrig`` — beim Abgleich aus den Kopfzeilen
    #: ``Importance`` und ``X-Priority`` gedeutet, weil Absender mal die eine,
    #: mal die andere schreiben. Gespeichert wird das Ergebnis, nicht die
    #: Kopfzeile: Die Liste soll nicht bei jeder Zeile deuten muessen.
    wichtigkeit: Mapped[str] = mapped_column(String(10), default="normal")

    anreisser: Mapped[str] = mapped_column(Text, default="")
    koerper_text: Mapped[str] = mapped_column(Text, default="")
    #: Bereits bereinigt und mit ausgeklinkten Bildern.
    koerper_html: Mapped[str] = mapped_column(Text, default="")
    #: Wie viele Bilder ausgeklinkt wurden - die Oberflaeche zeigt danach den
    #: Hinweis, und ohne diese Zahl muesste sie im HTML suchen.
    geblockte_bilder: Mapped[int] = mapped_column(Integer, default=0)
    koerper_geholt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    ordner: Mapped["Ordner"] = relationship()
    anhaenge: Mapped[list["Anhang"]] = relationship(
        back_populates="nachricht", cascade="all, delete-orphan"
    )


class Anhang(Base):
    """Ein Anhang.

    ⚠️ **Der Inhalt liegt auf der Platte, nicht in der Datenbank** - unter
    ``/data/blobs/<sha256>``. Nach Pruefsumme benannt: Dieselbe Datei in zehn
    Mails liegt einmal da. Und eine SQLite-Datei, die Anhaenge traegt, ist
    nicht mehr zu sichern.
    """

    __tablename__ = "anhang"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nachricht_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nachricht.id", ondelete="CASCADE"), index=True
    )

    teil_id: Mapped[str] = mapped_column(String(32), default="1")
    dateiname: Mapped[str] = mapped_column(String(400), default="")
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    groesse: Mapped[int] = mapped_column(Integer, default=0)
    #: Bei Inline-Bildern der Wert aus Content-ID.
    cid: Mapped[str] = mapped_column(String(300), default="")
    #: Leer, solange der Inhalt noch nicht auf der Platte liegt.
    blob_hash: Mapped[str] = mapped_column(String(64), default="", index=True)

    nachricht: Mapped[Nachricht] = relationship(back_populates="anhaenge")


class Ausgang(Base):
    """Eine Nachricht, die hinaus soll.

    ⚠️ **Die Warteschlange ueberlebt einen Neustart.** Ohne sie waere eine
    Mail, die beim Senden auf einen Netzwackler trifft, einfach weg - und der
    Absender merkt es erst, wenn jemand nachfragt. Die fertigen Bytes liegen
    unter ``/data/ausgang/<id>.eml``, nicht in der Datenbank: Ein Anhang von
    zehn Megabyte hat in einer SQLite-Datei nichts verloren.
    """

    __tablename__ = "ausgang"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    konto_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("konto.id", ondelete="CASCADE"), index=True
    )

    #: wartet | unterwegs | gesendet | gescheitert
    stand: Mapped[str] = mapped_column(String(16), default="wartet", index=True)

    an_json: Mapped[str] = mapped_column(Text, default="[]")
    betreff: Mapped[str] = mapped_column(Text, default="")
    message_id: Mapped[str] = mapped_column(String(500), default="")

    versuche: Mapped[int] = mapped_column(Integer, default=0)
    letzter_fehler: Mapped[str] = mapped_column(Text, default="")

    #: Fruehestens ab wann gesendet wird, in UTC. Leer heisst: sofort.
    #: ⚠️ Der Zeitpunkt haelt den Eintrag nur zurueck, er stoesst nichts an -
    #: hinausgeschoben wird er von den faelligen Laeufen der Warteschlange.
    senden_ab: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    gesendet: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    konto: Mapped["Konto"] = relationship()


class Einstellung(Base):
    """Was der Betreiber in der Oberflaeche pflegt.

    Schluessel-Wert statt Spalten: Eine neue Einstellung soll keine
    Schemaaenderung sein. Werte sind Text; wer eine Zahl will, wandelt sie
    beim Lesen um.
    """

    __tablename__ = "einstellung"

    schluessel: Mapped[str] = mapped_column(String(64), primary_key=True)
    wert: Mapped[str] = mapped_column(Text, default="")


class Geheimnis(Base):
    """Interne Schluessel - derzeit genau einer: der verpackte DEK.

    Bewusst eine eigene Tabelle und nicht ``einstellung``: Was hier steht,
    gehoert nicht dem Betreiber und darf nie in einer Einstellungsseite
    auftauchen.
    """

    __tablename__ = "geheimnis"

    schluessel: Mapped[str] = mapped_column(String(64), primary_key=True)
    wert: Mapped[str] = mapped_column(Text)


class Kontakt(Base):
    """Ein Eintrag im Adressbuch.

    ⚠️ **Die Adresse ist der Schluessel, nicht der Name.** Menschen heissen
    mehrfach gleich und aendern ihren Namen; die Adresse ist das, woran eine
    Mail haengt. Deshalb ist sie je Benutzer eindeutig - sonst sammelt das
    Einsammeln aus Gesendet denselben Menschen zehnmal ein.

    ``quelle`` unterscheidet, was von Hand gepflegt wurde und was nexmail
    selbst aufgeschnappt hat. Ohne diese Spalte kann man Aufgeschnapptes nie
    wieder in einem Zug loswerden - und ein Adressbuch, das man nicht
    aufraeumen kann, benutzt niemand.
    """

    __tablename__ = "kontakt"
    __table_args__ = (
        UniqueConstraint("benutzer_id", "adresse", name="uq_kontakt_adresse"),
        Index("ix_kontakt_name", "benutzer_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)

    name: Mapped[str] = mapped_column(String(320), default="")
    #: Immer kleingeschrieben abgelegt. Mail-Adressen sind im Domaenenteil
    #: ohnehin gleichbedeutend, und ein Adressbuch mit "Max@" und "max@"
    #: nebeneinander ist kaputt.
    adresse: Mapped[str] = mapped_column(String(320))
    firma: Mapped[str] = mapped_column(String(320), default="")
    telefon: Mapped[str] = mapped_column(String(120), default="")
    notiz: Mapped[str] = mapped_column(Text, default="")

    #: ``hand`` oder ``gesammelt``.
    quelle: Mapped[str] = mapped_column(String(16), default="hand")
    #: Wie oft an diese Adresse geschrieben wurde - die Reihenfolge der
    #: Vorschlaege beim Tippen haengt daran.
    verwendet: Mapped[int] = mapped_column(Integer, default=0)
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Kontaktgruppe(Base):
    """Ein Verteiler im Adressbuch - ein Eingabehelfer, kein Mailbegriff.

    Wer eine Gruppe beim Adressieren auswaehlt, bekommt ihre Mitglieder als
    einzelne Empfaenger eingesetzt. In der Mail selbst stehen nur die
    Einzeladressen; der Server, der Empfaenger und jedes andere Programm
    sehen von der Gruppe nichts.

    ⚠️ **Loeschen einer Gruppe loescht keine Kontakte** - nur die
    Zuordnungen. Die Gruppe besitzt ihre Mitglieder nicht, sie zeigt auf sie.
    """

    __tablename__ = "kontaktgruppe"
    #: Exakt-gleiche Namen faengt schon die Datenbank; gleich bis auf
    #: Gross/klein prueft der Dienst - dieselbe Regel wie bei den
    #: Postfach-Schlagworten: "Privat" und "privat" waeren zwei Eintraege,
    #: die gleich aussehen und Verschiedenes meinen.
    __table_args__ = (UniqueConstraint("benutzer_id", "name", name="uq_kontaktgruppe_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class KontaktgruppeMitglied(Base):
    """Die Zuordnung Kontakt zu Gruppe - ein Kontakt darf in mehreren stehen.

    ⚠️ **``benutzer_id`` steht hier bewusst noch einmal**, obwohl sie ueber
    die Gruppe herleitbar waere: ``benutzer.entfernen`` leert jede Tabelle
    mit dieser Spalte ueber die Modelle - eine Tabelle ohne sie bliebe beim
    Loeschen eines Benutzers liegen. Siehe den Kopf dieser Datei.
    """

    __tablename__ = "kontaktgruppe_mitglied"
    __table_args__ = (
        # Zweimal eintragen ist ein Verklicken, kein zweites Mitglied.
        UniqueConstraint("gruppe_id", "kontakt_id", name="uq_gruppe_mitglied"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    gruppe_id: Mapped[int] = mapped_column(Integer, index=True)
    kontakt_id: Mapped[int] = mapped_column(Integer, index=True)


class Regel(Base):
    """Eine Regel: Wenn etwas zutrifft, tu etwas.

    ⚠️ **Die Reihenfolge ist Teil der Bedeutung.** Regeln laufen von oben nach
    unten; eine Regel mit ``stopp`` beendet den Lauf. Ohne feste Reihenfolge
    haengt das Ergebnis davon ab, wie die Datenbank die Zeilen zurueckgibt -
    und das aendert sich, ohne dass jemand etwas anfasst.

    Bedingungen und Aktionen stehen als JSON. Das ist bewusst: Eine neue
    Bedingungsart soll keine Schemaaenderung sein, und die Zahl der Regeln
    liegt bei einer Handvoll je Benutzer, nicht bei Tausenden.
    """

    __tablename__ = "regel"
    __table_args__ = (Index("ix_regel_reihenfolge", "benutzer_id", "reihenfolge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    #: Leer heisst: gilt fuer alle Postfaecher dieses Benutzers.
    konto_id: Mapped[str] = mapped_column(String(32), default="")

    name: Mapped[str] = mapped_column(String(200), default="")
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)

    #: "und" oder "oder" - wie die Bedingungen zusammenhaengen.
    verknuepfung: Mapped[str] = mapped_column(String(8), default="und")
    #: [{"feld": "von", "vergleich": "enthaelt", "wert": "…"}, …]
    bedingungen_json: Mapped[str] = mapped_column(Text, default="[]")
    #: [{"art": "verschieben", "wert": "12"}, …]
    aktionen_json: Mapped[str] = mapped_column(Text, default="[]")

    #: ⚠️ Nach dieser Regel keine weiteren mehr. Ohne das laeuft eine
    #: Nachricht durch alle Regeln und wird von der letzten wieder
    #: weggeschoben - der haeufigste Grund fuer "meine Regeln tun nichts".
    stopp: Mapped[bool] = mapped_column(Boolean, default=False)

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Signatur(Base):
    """Ein Textbaustein unter der eigenen Post.

    ⚠️ **Je Postfach, nicht je Benutzer.** Wer geschaeftlich und privat aus
    derselben Anwendung schreibt, will nicht die Firmenanschrift unter der
    Mail an die Familie.
    """

    __tablename__ = "signatur"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    #: Leer heisst: fuer jedes Postfach ohne eigene Signatur.
    konto_id: Mapped[str] = mapped_column(String(32), default="", index=True)

    name: Mapped[str] = mapped_column(String(200), default="")
    #: Bereits bereinigt - dieselbe Bereinigung wie beim Senden.
    html: Mapped[str] = mapped_column(Text, default="")
    #: Wird bei einer neuen Nachricht von selbst eingesetzt.
    standard: Mapped[bool] = mapped_column(Boolean, default=False)

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Textvorlage(Base):
    """Ein wiederkehrender Antwortbaustein fuer das Verfassen-Fenster.

    ⚠️ **Der Name ist je Benutzer einmalig** — er ist das, was im
    Vorlagen-Menue steht. Zwei gleichnamige Eintraege saehen dort identisch
    aus, und welcher eingefuegt wird, entschiede der Zufall.

    ⚠️ **Der Inhalt ist bereits bereinigt** — dieselbe Bereinigung wie beim
    Senden, wie bei den Signaturen. Er landet wortwoertlich im Editor und
    geht von dort denselben Weg hinaus wie jede Mail.
    """

    __tablename__ = "textvorlage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)

    name: Mapped[str] = mapped_column(String(200), default="")
    inhalt_html: Mapped[str] = mapped_column(Text, default="")
    #: Die Reihenfolge im Vorlagen-Menue — zum Ziehen, wie bei den Aufgaben.
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Einladung(Base):
    """Eine ausgesprochene Einladung, die noch niemand angenommen hat.

    ⚠️ **Der Schluessel liegt nur als Hash da.** Er steht in einer Mail und
    oeffnet ein Konto — das ist ein Passwort, kein Datensatz-Merkmal. Wer die
    Datenbank liest, darf damit nichts anfangen koennen. Dieselbe Regel wie
    bei den Wiederherstellungscodes.

    ⚠️ **Der Benutzername wird hier schon festgelegt** und beim Einloesen noch
    einmal geprueft: Zwischen Einladung und Annahme koennen Wochen liegen, und
    in der Zeit kann jemand anderes ihn belegt haben.
    """

    __tablename__ = "einladung"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    schluessel_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    benutzername: Mapped[str] = mapped_column(String(64))
    anzeigename: Mapped[str] = mapped_column(String(120), default="")
    #: Wohin die Einladung ging. Nur zum Wiedererkennen in der Liste.
    adresse: Mapped[str] = mapped_column(String(320), default="")
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    laeuft_ab: Mapped[datetime] = mapped_column(UtcDateTime)
    #: Gesetzt heisst: angenommen. Die Zeile bleibt als Spur stehen.
    eingeloest: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)


class Aufgabe(Base):
    """Eine Mail, die noch etwas von einem will.

    ⚠️ **Die Aufgabe zeigt auf die Mail, sie kopiert sie nicht** — so am
    01.09.2026 entschieden. Trotzdem stehen hier Betreff und Absender: als
    **Abzug** fuer den Fall, dass die Mail verschwindet. Eine Aufgabe, die dann
    nur noch „(nicht mehr da)" heisst, ist wertlos; man weiss nicht einmal
    mehr, worum es ging.

    ⚠️ **Wiedergefunden wird ueber ``message_id``, nicht ueber ``nachricht_id``.**
    Wer eine Mail vom Telefon aus in einen anderen Ordner schiebt, bekommt beim
    naechsten Abgleich eine **neue** Zeile mit neuer Kennung und neuer UID —
    die alte ist weg. Ueber die Zeilennummer waere die Aufgabe damit verwaist,
    obwohl die Mail zwei Ordner weiter liegt. Die ``Message-ID`` vergibt der
    absendende Server, und sie bleibt.
    """

    __tablename__ = "aufgabe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    #: Das Postfach, aus dem die Mail stammt — fuer den farbigen Punkt.
    konto_id: Mapped[str] = mapped_column(String(32), default="")

    #: Die Zeile, wie sie beim Anlegen hiess. Kann veralten.
    nachricht_id: Mapped[int | None] = mapped_column(Integer, default=None)
    #: Der bestaendige Weg zurueck zur Mail.
    message_id: Mapped[str] = mapped_column(String(500), default="", index=True)

    #: Abzug fuer den Fall, dass die Mail nicht mehr da ist.
    betreff: Mapped[str] = mapped_column(Text, default="")
    von_name: Mapped[str] = mapped_column(String(320), default="")
    von_adresse: Mapped[str] = mapped_column(String(320), default="")
    mail_datum: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    #: Gesetzt heisst: abgehakt. Die Zeile bleibt stehen.
    erledigt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    #: Faelligkeit, ohne Uhrzeit gedacht. Leer heisst: kein Datum.
    faellig: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    #: Von Hand gezogen. Klein steht oben.
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    __table_args__ = (
        # ⚠️ Dieselbe Mail nicht zweimal in der Liste. Ohne das entstehen
        # Doppel, sobald jemand den Menuepunkt zweimal trifft — und abhaken
        # muss man dann beide.
        UniqueConstraint("benutzer_id", "message_id", name="uq_aufgabe_mail"),
    )


class Wiedervorlage(Base):
    """Eine weggelegte Mail, die zu einem Zeitpunkt wieder auffallen soll.

    Die Mail selbst liegt in einem **echten** IMAP-Ordner „Wiedervorlage" auf
    dem Mailserver — sie bleibt damit von jedem Client aus sichtbar, nichts
    verschwindet in einer Nur-nexmail-Logik. Diese Tabelle traegt nur den
    Merker: wann sie zurueckkommt und wohin.

    ⚠️ **Wiedergefunden wird ueber die ``Message-ID``, nie ueber die
    Zeilennummer** — dieselbe Begruendung wie bei den Aufgaben: Das Weglegen
    selbst ist ein Verschieben, die lokale Zeile stirbt dabei, und beim
    Aufwachen liegt die Mail unter einer neuen UID. Die ``Message-ID``
    vergibt der absendende Server, und sie bleibt.

    ⚠️ **Zweimal weggelegt ersetzt den Eintrag** (neues Aufwachen), erzeugt
    keinen zweiten — die Eindeutigkeit unten haelt dagegen.
    """

    __tablename__ = "wiedervorlage"
    __table_args__ = (
        UniqueConstraint("benutzer_id", "konto_id", "message_id", name="uq_wiedervorlage_mail"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    konto_id: Mapped[str] = mapped_column(String(32), index=True)

    #: Der bestaendige Weg zurueck zur Mail.
    message_id: Mapped[str] = mapped_column(String(500), index=True)
    #: Wann die Mail zurueckkommt — UTC, wie jeder Zeitstempel hier.
    aufwachen: Mapped[datetime] = mapped_column(UtcDateTime)
    #: Woher sie kam — dorthin geht sie beim Aufwachen zurueck.
    zurueck_pfad: Mapped[str] = mapped_column(String(512))
    #: Abzug des Betreffs — damit die Liste der wartenden Eintraege etwas
    #: sagt, auch wenn die Mail gerade in keiner lokalen Zeile steht.
    betreff_abzug: Mapped[str] = mapped_column(Text, default="")
    #: Wie oft das Aufwecken hintereinander gescheitert ist — steuert den
    #: wachsenden Abstand bis zum naechsten Versuch (services/wiedervorlage).
    fehlversuche: Mapped[int] = mapped_column(Integer, default=0)
    #: Vor diesem Zeitpunkt wird nicht erneut aufgeweckt. Leer heisst: sofort,
    #: sobald ``aufwachen`` erreicht ist.
    naechster_versuch: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, default=None)
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Schlagwort(Base):
    """Ein Schlagwort fuer einzelne Mails — als IMAP-Keyword gespeichert.

    ⚠️ **Das Atom lebt auf dem Mailserver, der Name nur hier.** ``atom`` ist
    das IMAP-Keyword (nur ``A-Za-z0-9_-``), das an jeder markierten Mail
    haengt und damit nexmail ueberlebt: Thunderbird und das Telefon sehen es
    auch. ``name`` ist die Anzeige und darf Umlaute tragen; Umbenennen
    aendert nur ihn — das Atom steht ja auf fremden Servern.

    ⚠️ **Eindeutig je Benutzer, ohne Ruecksicht auf Gross/klein.** IMAP
    vergleicht Keywords ohne Gross/klein (RFC 3501); „Arbeit" und „ARBEIT"
    sind auf dem Server dasselbe Flag. Zwei Definitionen dafuer waeren zwei
    Zeilen fuer eine Wahrheit. Die Datenbank sichert die exakte Form, der
    Dienst vergleicht klein (services/schlagworte.py) — dasselbe Muster wie
    bei den Postfach-Schlagworten und den Kontaktgruppen.

    ``farbe`` ist eine der sechs geprueften Postfachfarben (1..6) — keine
    eigene Palette, siehe frontend/src/lib/farben.ts.
    """

    __tablename__ = "schlagwort"
    __table_args__ = (UniqueConstraint("benutzer_id", "atom", name="uq_schlagwort_atom"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)

    #: Was in der Oberflaeche steht.
    name: Mapped[str] = mapped_column(String(100))
    #: Das IMAP-Keyword. Nur ``A-Za-z0-9_-``.
    atom: Mapped[str] = mapped_column(String(100))
    #: 1 bis 6 — dieselben Toene wie die Postfachfarben.
    farbe: Mapped[int] = mapped_column(Integer, default=1)
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class OidcAnbieter(Base):
    """Ein Anmelde-Anbieter nach OpenID Connect — vom Betreiber eingerichtet.

    Aus nexmails Sicht ist ein Anbieter drei Werte: Adresse, Client-ID,
    Geheimnis. Ob dahinter Keycloak, Authentik, Authelia oder Pocket ID steht,
    ist dem Code egal — das ist der Sinn der Norm, und deshalb gibt es hier
    **keine** Anbieter-Sonderfaelle.

    ⚠️ **Ab Werk ist diese Tabelle leer, und dann aendert sich nichts.** Keine
    Knoepfe auf der Anmeldeseite, keine offenen Adressen — eine Installation,
    deren Betreiber nie einen Anbieter einrichtet, weiss von OIDC nichts.
    """

    __tablename__ = "oidc_anbieter"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    #: Kurzform fuer die Adresse: ``/api/oidc/<kuerzel>/start``.
    kuerzel: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    #: Was auf dem Knopf steht.
    anzeigename: Mapped[str] = mapped_column(String(120))
    #: Die Adresse des Anbieters, aus der die Selbstauskunft geholt wird.
    issuer: Mapped[str] = mapped_column(String(300))
    client_id: Mapped[str] = mapped_column(String(300))
    #: Verschluesselt, Kontext ``oidc:<id>:geheimnis``.
    client_secret: Mapped[str] = mapped_column(Text, default="")
    #: Leerzeichengetrennt. ``openid`` haengt der Dienst selbst an.
    scopes: Mapped[str] = mapped_column(String(300), default="openid email profile")
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Bildfreigabe(Base):
    """„Von diesem Absender immer laden" — wie in Thunderbird.

    ⚠️ **Die volle Adresse, nicht die Domain.** Am 02.09.2026 so entschieden:
    Eine Domain-Freigabe waere bequemer (Newsletter wechseln oft zwischen
    ``news@``, ``info@`` und ``no-reply@``), aber ein Klick gaebe dann auch
    jeder kuenftigen Werbemail derselben Firma frei — und der Klick faellt in
    dem Moment, in dem man eine bestimmte Mail sehen will, nicht in dem, in
    dem man ueber eine Firma entscheidet.

    ⚠️ **Die Absenderadresse ist faelschbar, und das ist hier in Ordnung.**
    Wer sie faelscht, erreicht genau eins: dass seine Bilder geladen werden,
    also dass er erfaehrt, wann die Mail geoeffnet wurde. Dasselbe erreicht er
    mit einer Mail, auf deren Balken jemand klickt. Es ist kein Zugang zu
    irgendetwas.

    Eindeutig je Benutzer, ohne Ruecksicht auf Gross/klein — Mailadressen
    werden ueberall in nexmail klein verglichen.
    """

    __tablename__ = "bildfreigabe"
    __table_args__ = (
        UniqueConstraint("benutzer_id", "adresse", name="uq_bildfreigabe_adresse"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)

    #: Klein geschrieben abgelegt — verglichen wird nie mit Gross/klein.
    adresse: Mapped[str] = mapped_column(String(320))
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Abwesenheitsantwort(Base):
    """Wem die Abwesenheitsnotiz schon geschickt wurde.

    ⚠️ **Diese Tabelle IST der Schleifenschutz**, nicht sein Beiwerk. „Je
    Absender einmal" muss irgendwo stehen, und wenn es ohnehin dasteht, soll
    der Betreiber es auch sehen duerfen: Eine Schleife erkennt man an dieser
    Liste, bevor sie peinlich wird. Am 02.09.2026 so entschieden.

    ⚠️ **Beim Einschalten wird geleert.** „Einmal" gilt je Abwesenheit, nicht
    je Lebenszeit des Postfachs — sonst bekaeme beim naechsten Urlaub niemand
    mehr eine Notiz, der beim vorigen schon eine hatte.
    """

    __tablename__ = "abwesenheitsantwort"
    __table_args__ = (
        UniqueConstraint("konto_id", "adresse", name="uq_abwesenheit_adresse"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    konto_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("konto.id", ondelete="CASCADE"), index=True
    )
    #: Klein geschrieben abgelegt — verglichen wird nie mit Gross/klein.
    adresse: Mapped[str] = mapped_column(String(320))
    gesendet: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Terminantwort(Base):
    """Wie auf eine Termin-Einladung geantwortet wurde.

    ⚠️ **Das ist kein Kalender.** Hier steht nur, was nexmail dem Einladenden
    gesagt hat — damit die Einladung beim zweiten Oeffnen nicht aussieht wie
    beim ersten und man nicht zweimal antwortet. Der Termin selbst liegt
    nirgends; dafuer braucht es weiterhin ein Kalenderprogramm.

    Der Schluessel ist die ``UID`` aus der Einladung, nicht die Nachricht: Eine
    aktualisierte Einladung kommt als **neue** Mail mit derselben UID, und die
    fruehere Antwort gehoert weiter dazu.
    """

    __tablename__ = "terminantwort"
    __table_args__ = (UniqueConstraint("benutzer_id", "uid", name="uq_terminantwort_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    #: Die ``UID`` des Termins aus der ``.ics``.
    uid: Mapped[str] = mapped_column(String(500))
    #: ``zusage`` | ``vorbehalt`` | ``absage``
    antwort: Mapped[str] = mapped_column(String(16))
    gesendet: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)



class Kalender(Base):
    """Ein Kalender — entweder nexmails eigener oder eine Gegenstelle.

    ⚠️ **CalDAV-foermig von Anfang an.** ``art`` leer heisst: Er lebt nur hier.
    Sonst traegt er Adresse, Zugangsdaten und ``ctag``. So wird aus „diesem
    Kalender eine Adresse geben" spaeter eine Zeile und keine Umstellung —
    dasselbe Muster wie „fuer OIDC vorbereitet" in Stufe 0.

    ⚠️ **Der Primaerschluessel ist eine uuid4-Zeichenkette**, nicht eine Zahl —
    genau wie beim Postfach, und aus demselben Grund: Er steht vor dem
    Einfuegen fest und wandert als Zusatzdaten in die Verschluesselung des
    Passworts (``kalender:<id>:passwort``). Ohne das liesse sich ein
    verschluesseltes Passwort von einem Kalender auf einen anderen kopieren.

    ⚠️ **Ein CalDAV-Zugang ergibt MEHRERE Zeilen hier, nicht eine.** Eine
    Apple-ID liefert „Privat", „Arbeit", „Geburtstage" — jeder davon ist ein
    eigener Kalender mit eigener Adresse, eigener Farbe und eigenem Haken. Die
    Zugangsdaten stehen deshalb an jeder Zeile; sie zu teilen hiesse, eine
    zweite Tabelle einzufuehren, und ein geloeschter Kalender riesse dann die
    anderen mit.
    """

    __tablename__ = "kalender"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(120))
    #: 1 bis 6 — dieselbe gepruefte Palette wie beim Postfach-Punkt.
    farbe: Mapped[int] = mapped_column(Integer, default=1)
    #: Der Haken in der Spalte. ⚠️ Ein unsichtbarer Kalender wird trotzdem
    #: abgeglichen — sonst waere „kurz ausblenden" ein stiller Datenverlust.
    sichtbar: Mapped[bool] = mapped_column(Boolean, default=True)
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)

    #: "" (nur hier) | "caldav" | "ics"
    art: Mapped[str] = mapped_column(String(16), default="")
    #: Was in der Oberflaeche als Herkunft dasteht — „iCloud", „Nextcloud".
    herkunft: Mapped[str] = mapped_column(String(120), default="")
    #: Die Adresse der Sammlung (CalDAV) bzw. der Datei (ICS).
    url: Mapped[str] = mapped_column(Text, default="")
    benutzer_name: Mapped[str] = mapped_column(String(320), default="")
    passwort: Mapped[str] = mapped_column(Text, default="")
    #: Gesetzt heisst: angemeldet wird mit einem Zugriffstoken statt mit dem
    #: Passwort. Derselbe Zugang wie beim Postfach — eine Zustimmung reicht.
    oauth_zugang_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("oauth_zugang.id", ondelete="SET NULL"), default=None
    )

    #: ⚠️ **Das Sammel-ETag der Sammlung.** Aendert es sich nicht, hat sich in
    #: dem Kalender nichts getan — dann spart der Abgleich den ganzen Abruf.
    #: Bei einem Postfach macht das die ``UIDNEXT``; hier ist es der ``ctag``.
    ctag: Mapped[str] = mapped_column(String(255), default="")
    #: RFC 6578, wenn der Server es kann: nur das Geaenderte holen.
    sync_token: Mapped[str] = mapped_column(Text, default="")

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    zuletzt_geprueft: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    letzter_fehler: Mapped[str] = mapped_column(Text, default="")

    termine: Mapped[list["Termin"]] = relationship(
        back_populates="kalender", cascade="all, delete-orphan"
    )

    @property
    def nur_lesen(self) -> bool:
        """⚠️ **Gilt nur fuer ICS-Abos, und dort liegt es am Format:** Ein
        veroeffentlichter Link bietet keinen Weg zurueck. In CalDAV schreibt
        nexmail sehr wohl."""
        return self.art == "ics"


class Termin(Base):
    """Ein Termin. Eine Reihe steht **einmal** hier, nicht als viele Zeilen.

    ⚠️ **``roh`` ist kein Beiwerk, sondern die Rueckfahrkarte.** Darin steht
    das ``VEVENT``, wie es kam — samt allem, was nexmail nicht versteht:
    Teilnehmer, Erinnerungen, ``X-APPLE-…``. Wer beim Zurueckschreiben nur die
    Felder ausgibt, die er kennt, loescht dem Besitzer stillschweigend seine
    Alarme und die halbe Teilnehmerliste. Geschrieben wird deshalb **auf dem
    Original**, nicht daneben. Dieselbe Ueberlegung wie bei mboxrd: Das Format
    muss verlustfrei durch nexmail hindurchgehen.

    ⚠️ **``uid`` ist der Schluessel des Termins, ``href`` der seiner Datei.**
    Auf dem Server liegt jeder Termin als eigene ``.ics`` unter einer Adresse;
    die UID steht drin. Beides wird gebraucht: die UID, um denselben Termin
    wiederzuerkennen, die Adresse, um ihn zu ueberschreiben.

    ⚠️ **``etag`` ist der Konfliktschutz.** Beim Schreiben faehrt es als
    ``If-Match`` mit. Antwortet der Server 412, hat jemand denselben Termin
    woanders geaendert — dann wird gefragt, nicht ueberschrieben.
    """

    __tablename__ = "termin"
    __table_args__ = (
        UniqueConstraint("kalender_id", "uid", "recurrence_id", name="uq_termin_uid"),
        Index("ix_termin_fenster", "kalender_id", "beginn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kalender_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("kalender.id", ondelete="CASCADE"), index=True
    )
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)

    uid: Mapped[str] = mapped_column(String(500))
    #: Die Adresse der ``.ics`` auf dem Server. Leer bei einem eigenen Kalender.
    href: Mapped[str] = mapped_column(Text, default="")
    etag: Mapped[str] = mapped_column(String(255), default="")
    #: Das ganze ``VEVENT``, wie es kam. Siehe oben.
    roh: Mapped[str] = mapped_column(Text, default="")

    titel: Mapped[str] = mapped_column(Text, default="")
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    ort: Mapped[str] = mapped_column(Text, default="")

    beginn: Mapped[datetime] = mapped_column(UtcDateTime)
    ende: Mapped[datetime] = mapped_column(UtcDateTime)
    ganztaegig: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Die Zone, in der die Reihe gerechnet wird. ⚠️ **Nicht die des
    #: Betreibers**, sondern die des Termins: „jeden Montag um 9" heisst neun
    #: Uhr dort, wo der Termin hingehoert.
    zeitzone: Mapped[str] = mapped_column(String(64), default="UTC")

    rrule: Mapped[str] = mapped_column(Text, default="")
    #: Die abgesagten Einzeltermine einer Reihe, kommagetrennt als ISO.
    exdate: Mapped[str] = mapped_column(Text, default="")
    #: Gesetzt heisst: Diese Zeile ueberschreibt EIN Vorkommen der Reihe mit
    #: derselben ``uid`` — „der Montag naechste Woche faellt auf 10 Uhr".
    recurrence_id: Mapped[str] = mapped_column(String(64), default="")

    sequenz: Mapped[int] = mapped_column(Integer, default=0)

    #: Minuten vor dem Beginn, **-1 heisst keine**. Kommt aus dem ersten
    #: relativen ``VALARM`` des Termins und geht als solcher wieder hinaus.
    #:
    #: ⚠️ **Der Alarm gehoert zum Termin, nicht zur Anzeige.** Er faehrt ueber
    #: CalDAV mit; wer ihn hier einstellt, wird auch auf dem Telefon erinnert.
    #: Umgekehrt zeigt nexmail einen Alarm an, den jemand anders gesetzt hat.
    erinnerung: Mapped[int] = mapped_column(Integer, default=-1)

    #: Organisator und Teilnehmer als JSON — **nur zum Anzeigen**.
    #:
    #: ⚠️ **Sie stehen nicht in ``EIGENE``.** Beim Zurueckschreiben bleiben sie
    #: unangetastet in ``roh``; nexmail liest sie, aendert sie aber nicht. Wer
    #: sie aendern koennte, muesste auch einladen koennen — und dazu gehoert
    #: der ganze Rueckkanal (``METHOD:REPLY``, ``SEQUENCE``, ``CANCEL``).
    organisator: Mapped[str] = mapped_column(Text, default="")
    teilnehmer: Mapped[str] = mapped_column(Text, default="")
    #: Wann zuletzt eine Einladung zu diesem Termin hinausging.
    #:
    #: ⚠️ **Daran haengt die ``SEQUENCE``.** Die erste Einladung geht mit der
    #: Nummer hinaus, die der Termin hat; jede weitere zaehlt hoch. Ohne das
    #: Hochzaehlen halten Outlook und Google die zweite Einladung fuer eine
    #: Wiederholung der ersten und zeigen die Aenderung gar nicht an — mit
    #: Hochzaehlen bei JEDEM Versand waere dagegen schon die erste eine
    #: „Aktualisierung" eines Termins, den niemand kennt.
    eingeladen_am: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    #: Antworten, die zu diesem Termin kamen, aber von einer **nicht
    #: eingeladenen** Adresse. JSON-Liste aus ``adresse``, ``antwort``, ``am``.
    #:
    #: ⚠️ **Nur wer eingeladen wurde, kann antworten** — sonst traegt sich ein
    #: Fremder in eine Teilnehmerliste ein, indem er eine Antwort schickt.
    #: Aber lautlos verwerfen ist auch falsch: Am 04.09.2026 antwortete
    #: Outlook unter der eigenen Absenderidentitaet statt unter der
    #: eingeladenen Adresse, und von aussen sah es aus, als sei der Rueckkanal
    #: kaputt. Was hier steht, zeigt die Oberflaeche am Termin; entscheiden
    #: muss ein Mensch.
    fremde_antworten: Mapped[str] = mapped_column(Text, default="[]")
    #: ``CONFIRMED`` | ``TENTATIVE`` | ``CANCELLED``
    status: Mapped[str] = mapped_column(String(16), default="CONFIRMED")

    #: ⚠️ **Hier geaendert, dort noch nicht angekommen.** Solange das steht,
    #: darf der Abgleich die Zeile nicht mit der Serverfassung ueberbuegeln.
    schmutzig: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Aus einer Mail uebernommen. Die Karte im Lesebereich sagt es dann, und
    #: der Termin weiss, dass eine Aenderung hier den Einladenden nicht
    #: erreicht.
    aus_einladung: Mapped[bool] = mapped_column(Boolean, default=False)

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    geaendert: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    kalender: Mapped[Kalender] = relationship(back_populates="termine")


class OauthAnbieter(Base):
    """Die App-Anmeldung, die der Betreiber bei Google oder Microsoft anlegt.

    ⚠️ **nexmail kann kein Geheimnis mitliefern.** Das Repo ist oeffentlich;
    ein eingebauter Client-Schluessel stuende darin, und Google wie Microsoft
    ziehen ihn zurueck, sobald sie ihn finden. Jeder Betreiber legt deshalb
    seine eigene App an — dieselbe Wand wie bei „OAuth fuer Postfaecher" in
    SPAETER.md, nur ist sie jetzt durchschritten statt umgangen.

    ⚠️ **Ab Werk ist diese Tabelle leer, und dann aendert sich nichts.** Wer nie
    einen Anbieter eintraegt, sieht in der Postfach-Einrichtung keinen Knopf
    dafuer.
    """

    __tablename__ = "oauth_anbieter"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    #: ``google`` oder ``microsoft`` — mehr kennt nexmail nicht, und das ist
    #: Absicht: Die Endpunkte und Bereiche stehen im Code, nicht in der
    #: Datenbank. Wer sie eintippen liesse, baut eine Fehlerquelle ohne Gewinn.
    art: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(300))
    client_secret: Mapped[str] = mapped_column(Text, default="")
    #: Nur Microsoft: ``common`` (jeder), ``organizations``, oder eine
    #: Mandanten-Kennung. ⚠️ Wer hier den falschen Wert setzt, bekommt eine
    #: Fehlermeldung erst auf der Anmeldeseite von Microsoft.
    mandant: Mapped[str] = mapped_column(String(120), default="common")
    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Erinnerungszustellung(Base):
    """Dass diese Erinnerung schon herausgegangen ist.

    ⚠️ **Der Schluessel traegt den Kanal.** Heute gibt es genau einen („in der
    App"); die Zeile ist trotzdem je Kanal eindeutig, damit ein zweiter Kanal
    spaeter zustellen darf, obwohl der erste es schon getan hat. Ohne das
    muesste man beim ersten Web-Push umbauen — dieselbe Vorsorge wie „fuer OIDC
    vorbereitet" in Stufe 0.

    ⚠️ **Und je VORKOMMEN, nicht je Termin.** Eine woechentliche Besprechung
    erinnerte sonst genau einmal.
    """

    __tablename__ = "erinnerungszustellung"
    __table_args__ = (
        UniqueConstraint("termin_id", "vorkommen", "kanal", name="uq_erinnerung"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    termin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("termin.id", ondelete="CASCADE"), index=True
    )
    benutzer_id: Mapped[str] = mapped_column(String(32), index=True)
    #: Der Beginn genau dieses Vorkommens.
    vorkommen: Mapped[datetime] = mapped_column(UtcDateTime)
    #: 'app' — spaeter 'push', 'mail', 'webhook'.
    kanal: Mapped[str] = mapped_column(String(20), default="app")

    zugestellt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: Gesetzt heisst: nicht vor diesem Zeitpunkt wieder zeigen.
    schlummert_bis: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    #: Weggeklickt. ⚠️ Die Zeile bleibt stehen — geloescht kaeme die
    #: Erinnerung beim naechsten Abruf sofort wieder.
    erledigt: Mapped[bool] = mapped_column(Boolean, default=False)


class KiVorgang(Base):
    """Was bei einem Handgriff wirklich zum KI-Dienst hinausging.

    ⚠️ **Der Zweck ist Nachprüfbarkeit, nicht Buchhaltung.** nexmail sagt an
    mehreren Stellen zu, dass Zitat und Signatur **nicht** mitgehen und dass der
    Entwurf als Text und nicht als Anweisung geschickt wird. Solche Zusagen sind
    ohne Beleg nur Behauptungen. Hier steht der Rumpf wörtlich, wie er
    abgeschickt wurde — wer nachsehen will, muss niemandem glauben.

    ⚠️ **Und es ist die Abwehr gegen versteckten Text.** Weiß auf Weiß,
    Schriftgröße 1, ein HTML-Kommentar: Wer fremden Text in seinen Entwurf
    einfügt, nimmt so etwas mit, ohne es im Editor zu sehen. In dieser Liste
    ist es sichtbar.

    ⚠️ **Der Rumpf liegt verschlüsselt**, mit dem Datenschlüssel und dem
    Kontext ``benutzer:<id>:ki-vorgang`` — dieselbe Behandlung wie ein
    Postfach-Kennwort. Er enthält den Text einer Mail, und eine zweite,
    dauerhafte Kopie davon im Klartext wäre schlechter als gar keine Liste.
    Der Preis steht dabei: **durchsuchen lässt sich das nicht.** AES-GCM salzt
    jeden Vorgang, ein ``LIKE`` findet nichts. Entschieden am 04.09.2026;
    gelesen wird die Liste ohnehin am Stück und in der Reihenfolge der Zeit.

    ⚠️ **Der Schlüssel des Dienstes steht NIE darin.** Er ist eine Kopfzeile,
    kein Teil des Rumpfes — und was hier gespeichert wird, ist genau der Rumpf.
    """

    __tablename__ = "ki_vorgang"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    #: ⚠️ Zusammen mit ``benutzer_id``, denn beides wird immer zusammen
    #: gebraucht: die eigene Liste, neueste zuerst, und das Aufräumen nach Alter.
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    #: Welches Modell gefragt wurde — es steht in der Zeile, weil es sich
    #: ändern darf und die Liste sonst nicht mehr zu deuten wäre.
    modell: Mapped[str] = mapped_column(String(200), default="")
    auftrag: Mapped[str] = mapped_column(String(40), default="")
    #: Ton oder Zielsprache, je nach Auftrag.
    ziel: Mapped[str] = mapped_column(String(40), default="")
    #: Der vollstaendige Rumpf als JSON, verschluesselt.
    rumpf: Mapped[str] = mapped_column(Text, default="")
    #: ⚠️ **Nicht „token" im Spaltennamen.** Die Protokollzensur schwaerzt
    #: alles nach diesem Wort; eine Zeile „806 token*** in" hat am 04.09.2026
    #: schon einmal eine Messung unlesbar gemacht.
    rein: Mapped[int] = mapped_column(Integer, default=0)
    raus: Mapped[int] = mapped_column(Integer, default=0)
    #: Leer heisst: hat geklappt. Sonst die Kennung des Fehlers.
    #: ⚠️ **Auch ein Fehlschlag steht in der Liste.** Der Text ging trotzdem
    #: hinaus; eine Liste, die nur die gelungenen zeigt, beantwortet die Frage
    #: „was hat mein Rechner verschickt" falsch.
    fehler: Mapped[str] = mapped_column(String(60), default="")


class PushAnmeldung(Base):
    """Ein Browser, der Meldungen annimmt.

    ⚠️ **Je Geraet eine Zeile, nicht je Benutzer.** Die Erlaubnis erteilt der
    Browser, und er gibt dafuer eine Adresse beim Push-Dienst seines
    Herstellers heraus (Mozilla, Google, Apple). Wer sich an drei Geraeten
    anmeldet, steht dreimal hier — und wer die Browserdaten loescht, faellt
    beim naechsten Zustellversuch mit 404 oder 410 heraus.

    ⚠️ **Diese drei Felder liegen im Klartext, anders als jedes Passwort.**
    Das ist eine Entscheidung, keine Nachlaessigkeit:

    * Der Browser haendigt sie **jeder Seite dieser Herkunft** aus und baut sie
      auf Wunsch jederzeit neu. Sie sind kein Geheimnis, das nexmail huetet.
    * Ein Abonnement, das mit ``applicationServerKey`` entstanden ist, nimmt
      **nur** Meldungen an, die mit unserem VAPID-Schluessel unterschrieben
      sind. Ohne den privaten Teil ist die Zeile wertlos — und **der** liegt
      verschluesselt (``push.SCHLUESSEL``, Kontext ``push-vapid``).
    * Verschluesselt liessen sie sich nicht eindeutig halten: AES-GCM salzt
      jeden Vorgang, derselbe Endpunkt saehe zweimal verschieden aus, und der
      eindeutige Index waere wirkungslos.

    Wer das je aendert, aendert damit auch den Index.
    """

    __tablename__ = "push_anmeldung"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    #: Die Adresse beim Push-Dienst. Eindeutig: Derselbe Browser, der sich ein
    #: zweites Mal anmeldet, bekommt dieselbe zurueck und soll keine zweite
    #: Zeile erzeugen.
    endpunkt: Mapped[str] = mapped_column(Text, unique=True)
    #: Der oeffentliche Schluessel des Browsers (P-256, base64url).
    p256dh: Mapped[str] = mapped_column(String(200))
    #: Das gemeinsame Geheimnis fuer die Ableitung (base64url).
    auth: Mapped[str] = mapped_column(String(64))

    #: „Firefox, Windows" — aus dem User-Agent, nur zum Wiedererkennen in der
    #: Liste. ⚠️ Nicht zur Unterscheidung: Zwei gleiche Browser auf demselben
    #: Rechner heissen gleich, und getrennt werden sie am Endpunkt.
    geraet: Mapped[str] = mapped_column(String(120), default="")

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: Wann zuletzt wirklich etwas ankam. ⚠️ Das ist nicht „zuletzt benutzt":
    #: Ein Geraet, das monatelang nichts zu melden bekam, ist trotzdem gesund.
    zuletzt_erreicht: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    benutzer: Mapped["Benutzer"] = relationship(back_populates="push_anmeldungen")


class OauthZugang(Base):
    """Eine erteilte Erlaubnis — ein Google- oder Microsoft-Konto.

    ⚠️ **Eine Erlaubnis, mehrere Nutzungen.** Wer sein Google-Konto einmal
    freigibt, soll nicht fuer den Kalender ein zweites Mal durch dieselbe
    Zustimmung laufen. Postfach und Kalender zeigen deshalb beide hierher.

    ⚠️ **Das Auffrischungs-Token ist das eigentliche Geheimnis.** Es oeffnet
    das Postfach dauerhaft und liegt deshalb verschluesselt (Kontext
    ``oauth:<id>:refresh``). Das kurzlebige Zugriffstoken ebenso — es waere
    sonst der eine Klartext-Schluessel in einer Datenbank voller Chiffren.
    """

    __tablename__ = "oauth_zugang"
    __table_args__ = (
        UniqueConstraint("benutzer_id", "art", "adresse", name="uq_oauth_zugang"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    benutzer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    art: Mapped[str] = mapped_column(String(20))
    #: Die Adresse des freigegebenen Kontos — sie steht in der Oberflaeche.
    adresse: Mapped[str] = mapped_column(String(320), default="")

    refresh: Mapped[str] = mapped_column(Text, default="")
    zugriff: Mapped[str] = mapped_column(Text, default="")
    #: Wann das Zugriffstoken ablaeuft. ⚠️ **Mit Vorlauf erneuern**, nicht erst
    #: beim Ablauf: Zwischen Pruefung und IMAP-Anmeldung liegen Sekunden, und
    #: ein abgelaufenes Token sieht aus wie ein falsches Passwort.
    ablauf: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    #: Was zugestanden wurde — zum Nachsehen, wenn etwas fehlt.
    bereich: Mapped[str] = mapped_column(Text, default="")

    angelegt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    #: Gesetzt, wenn die Erlaubnis nicht mehr gilt (widerrufen, Passwort
    #: geaendert, sieben Tage im Testbetrieb). ⚠️ **Das muss man sehen**, sonst
    #: sieht ein toter Zugang aus wie ein kaputter Mailserver.
    letzter_fehler: Mapped[str] = mapped_column(Text, default="")

    #: Die Kalender, die ueber diese Zustimmung laufen. Nur zum Zaehlen —
    #: geloescht wird ueber die Dienste, damit die Reihenfolge stimmt.
    kalender: Mapped[list["Kalender"]] = relationship(lazy="selectin", viewonly=True)
