"""Das Bild vor einer Zeile: Kontaktfoto, sonst das gepruefte Markenlogo (BIMI).

Gewuenscht in der Diskussion #4, entschieden am 27.09.2026: **so streng wie
Apple Mail.** Ein Logo gibt es nur, wenn alles davon stimmt:

1. Die Mail hat die Absenderpruefung bestanden (DMARC, gelesen aus
   ``Authentication-Results``, siehe ``services/absenderpruefung.py``).
2. Die Absenderdomain veroeffentlicht einen BIMI-Eintrag im DNS
   (``default._bimi.<domain>``) mit einem Markenzertifikat (``a=``).
3. Das Zertifikat ist ein gueltiges Verified Mark Certificate: fuer genau
   diese Domain ausgestellt, zum Markenzweck bestimmt, und die Kette reicht
   bis zu einer der Wurzeln, die die BIMI Group als Aussteller nennt.
4. Das Logo ist das **im Zertifikat** (Erweiterung „Logotype“, RFC 3709),
   ein SVG Tiny PS ohne Skript und ohne Verweis nach draussen.

⚠️ **Das Logo wird nicht mitgeschickt.** Die Firma hinterlegt es fuer ihre
Domain; nexmail fragt einmal je Domain das DNS und laedt das Zertifikat, auf
das der Eintrag zeigt. Der Browser greift nirgends hin.

⚠️ **Die ``l=``-Adresse im Eintrag wird nicht geholt.** Sie muesste dasselbe
Bild zeigen wie das Zertifikat; wer nur das Zertifikat nimmt, braucht ihr
nicht zu glauben.

⚠️ **Eine Domain buergt fuer alle ihre Absender.** Hat ``firma.example.com`` ein
Logo, bekommt es auch ``anna@firma.example.com``. So will es der Standard, und so
zeigt es Apple Mail.

⚠️ **Nicht geprueft wird der Widerruf** (OCSP, CRL). Ein widerrufenes
Zertifikat faellt erst nach Ablauf aus dem Zwischenspeicher (``FRISCH``).

Ausserdem gibt es Apples eigene Liste („Branded Mail“), in die Firmen ihr Logo
bei Apple eintragen. Die ist geschlossen; nexmail kommt nicht heran.
"""

from __future__ import annotations

import base64
import gzip
import logging
import re
import threading
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import Absenderlogo, Benutzer, Kontakt, utcnow
from . import bildvermittler, kontakte, vcard

logger = logging.getLogger("nexmail.absenderbild")

#: Ein Markenzertifikat samt Kette hat rund 9 KB.
MAX_ZERTIFIKAT = 64 * 1024
#: So verlangt es die BIMI-Spezifikation fuer das Logo.
MAX_SVG = 32 * 1024
ZEITGRENZE = 5.0
#: ⚠️ **Kurz, weil es keine Widerrufspruefung gibt.** Nach einer Woche wird
#: der Eintrag neu gelesen und das Zertifikat neu geprueft.
FRISCH = timedelta(days=7)
NICHTS_FRISCH = timedelta(days=3)

#: Zweck „Brand Indicator for Message Identification“ (RFC 9345 folgend).
ZWECK_BIMI = "1.3.6.1.5.5.7.3.31"
#: Die Erweiterung, in der das Logo steckt (RFC 3709).
LOGOTYPE = "1.3.6.1.5.5.7.1.12"

#: Die Wurzeln der Aussteller, die die BIMI Group nennt
#: (bimigroup.org/vmc-issuers, Stand 27.09.2026): DigiCert, GlobalSign,
#: SSL.com. Entrust steht nicht mehr darauf.
#:
#: ⚠️ **Zweimal festgehalten, als Datei und als Fingerabdruck.** Die Datei
#: ``vorlagen/bimi-wurzeln.pem`` liefert die Schluessel; die Fingerabdruecke
#: hier stellen sicher, dass niemand eine fuenfte Wurzel dazulegt, ohne diese
#: Zeilen anzufassen. DigiCerts Wurzel stimmt mit der in den Ketten von
#: Revolut, PayPal und Amazon ueberein, GlobalSigns kam ueber http und https
#: gleich an.
WURZEL_FINGERABDRUECKE = frozenset(
    {
        "50:43:86:c9:ee:89:32:fe:cc:95:fa:de:42:7f:69:c3:e2:53:4b:73:10:48:9e:30:0f:ee:44:8e:33:c4:6b:42",  # DigiCert Verified Mark Root CA
        "cd:12:2c:b8:77:c6:92:8b:90:17:b0:f0:b8:0d:bd:50:81:96:30:0b:bd:03:cd:73:56:c3:be:ef:52:4e:7e:0b",  # GlobalSign Verified Mark Root R42
        "1b:82:e7:f4:91:0b:51:e3:e8:02:a4:93:ac:dc:17:ff:58:ea:c8:b9:eb:7c:09:b5:2a:c6:cd:2e:fb:83:59:8c",  # SSL.com VMC ECC Root CA 2024
        "8f:9d:1b:76:98:88:67:82:a5:99:b4:85:10:65:1c:66:a1:aa:0c:5c:a3:19:20:97:bd:c6:85:34:15:4b:d3:0d",  # SSL.com VMC RSA Root CA 2024
    }
)


class NichtVerifiziert(Exception):
    """Das Zertifikat traegt kein Logo, dem nexmail glaubt. Mit Grund, fuers Protokoll."""


def _wurzeln_laden() -> list[x509.Certificate]:
    datei = Path(__file__).resolve().parent.parent / "vorlagen" / "bimi-wurzeln.pem"
    wurzeln = x509.load_pem_x509_certificates(datei.read_bytes())
    gefunden = {w.fingerprint(hashes.SHA256()).hex(":") for w in wurzeln}
    if gefunden != WURZEL_FINGERABDRUECKE:
        raise RuntimeError("bimi-wurzeln.pem does not match the pinned fingerprints")
    return wurzeln


WURZELN = _wurzeln_laden()


# --- Der Eintrag im DNS ------------------------------------------------------ #


_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_ZWEITE_EBENE = frozenset({"co", "com", "org", "net", "gov", "ac", "edu", "ne", "or", "go"})


def domain_aus(adresse: str) -> str | None:
    """Die Domain einer Mailadresse, klein, oder ``None``."""
    _, at, host = adresse.strip().lower().rpartition("@")
    return host if at and _DOMAIN.match(host) else None


def stammdomain(domain: str) -> str:
    """Die Organisationsdomain: ``news.revolut.com`` -> ``revolut.com``.

    ⚠️ **Eine Naeherung, keine Public-Suffix-Liste**, wie sie DMARC eigentlich
    verlangt. Ein Fehlgriff kostet ein fehlendes Logo, keins zu viel: Das
    Zertifikat muss die Domain ohnehin selbst nennen.
    """
    teile = domain.split(".")
    tiefe = 3 if len(teile) >= 3 and len(teile[-1]) == 2 and teile[-2] in _ZWEITE_EBENE else 2
    return ".".join(teile[-tiefe:])


def eintrag_deuten(text: str) -> str | None:
    """Die Zertifikatsadresse (``a=``) aus einem BIMI-Eintrag, oder ``None``.

    ``None`` auch fuer einen Eintrag ohne ``a=``: Ohne Zertifikat zeigt Apple
    kein Logo, und nexmail auch nicht.
    """
    felder: dict[str, str] = {}
    for teil in text.split(";"):
        name, gleich, wert = teil.strip().partition("=")
        if gleich:
            felder[name.strip().lower()] = wert.strip()
    if felder.get("v") != "BIMI1":
        return None
    adresse = felder.get("a", "")
    return adresse if adresse.lower().startswith("https://") else None


def _txt(name: str) -> list[str]:
    import dns.exception
    import dns.resolver

    try:
        antwort = dns.resolver.resolve(name, "TXT", lifetime=ZEITGRENZE)
    except (dns.exception.DNSException, OSError):
        return []
    return [b"".join(r.strings).decode("utf-8", "replace") for r in antwort]


def dmarc_durchgesetzt(domain: str) -> bool:
    """Setzt die Domain DMARC durch (``p=quarantine`` oder ``reject``, ganz)?

    ⚠️ **BIMI verlangt es, und Apple prueft es.** Eine Domain mit ``p=none``
    laesst gefaelschte Mails durch; ihr Logo zu zeigen hiesse, der Faelschung
    zu helfen. Gesucht wird wie bei DMARC: erst ``_dmarc.<domain>``, dann die
    Organisationsdomain, und dort gilt fuer eine Unterdomain ``sp=``.
    """
    stamm = stammdomain(domain)
    for name, ist_unterdomain in dict.fromkeys(((domain, False), (stamm, domain != stamm))):
        for text in _txt(f"_dmarc.{name}"):
            felder: dict[str, str] = {}
            for teil in text.split(";"):
                schluessel, gleich, wert = teil.strip().partition("=")
                if gleich:
                    felder[schluessel.strip().lower()] = wert.strip().lower()
            if felder.get("v") != "dmarc1":
                continue
            regel = felder.get("sp", felder.get("p", "")) if ist_unterdomain else felder.get("p", "")
            return regel in ("quarantine", "reject") and felder.get("pct", "100") == "100"
    return False


def zertifikatsadresse(domain: str) -> str | None:
    """Erst die Domain selbst, dann ihre Organisationsdomain (so will es BIMI)."""
    for name in dict.fromkeys((domain, stammdomain(domain))):
        for text in _txt(f"default._bimi.{name}"):
            if text.strip().startswith("v=BIMI1"):
                # Der erste Eintrag, der sich BIMI nennt, gilt. Ein erklaerter
                # Verzicht (``a=`` leer) heisst: kein Logo, auch nicht vom Stamm.
                return eintrag_deuten(text)
    return None


# --- Das Zertifikat ----------------------------------------------------------- #


def _zwecke(zertifikat: x509.Certificate) -> set[str] | None:
    try:
        return {o.dotted_string for o in zertifikat.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value}
    except x509.ExtensionNotFound:
        return None


def _ausgestellt_von(kind: x509.Certificate, eltern: x509.Certificate) -> bool:
    try:
        kind.verify_directly_issued_by(eltern)
    except Exception:  # noqa: BLE001 - InvalidSignature, ValueError, TypeError: jede Absage heisst nein
        return False
    return True


def _ist_aussteller(zertifikat: x509.Certificate) -> bool:
    try:
        return bool(zertifikat.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
    except x509.ExtensionNotFound:
        return False


def _der_texte(daten: bytes) -> list[str]:
    """Alle IA5-Zeichenketten in einem DER-Block, in beliebiger Tiefe.

    ⚠️ **Von Hand, weil ``cryptography`` die Logotype-Erweiterung nicht
    zerlegt.** Gesucht wird nur, was dort als Adresse stehen kann; alles
    andere wird uebersprungen, und ein kaputter Block endet die Suche statt
    sie zu verwirren.
    """
    texte: list[str] = []
    stapel = [daten]
    while stapel:
        rest = stapel.pop()
        i = 0
        while i + 2 <= len(rest):
            kennung, laenge = rest[i], rest[i + 1]
            i += 2
            if laenge & 0x80:
                anzahl = laenge & 0x7F
                if anzahl == 0 or anzahl > 4 or i + anzahl > len(rest):
                    break
                laenge = int.from_bytes(rest[i : i + anzahl], "big")
                i += anzahl
            if i + laenge > len(rest):
                break
            inhalt = rest[i : i + laenge]
            i += laenge
            if kennung & 0x20:
                stapel.append(inhalt)
            elif kennung == 0x16:
                texte.append(inhalt.decode("ascii", "replace"))
    return texte


def logo_aus_zertifikat(zertifikat: x509.Certificate) -> bytes:
    try:
        roh = next(e for e in zertifikat.extensions if e.oid.dotted_string == LOGOTYPE).value.value
    except StopIteration:
        raise NichtVerifiziert("no logotype extension") from None
    for text in _der_texte(roh):
        kopf, komma, daten = text.partition(",")
        if not komma or not kopf.lower().startswith("data:image/svg+xml") or ";base64" not in kopf.lower():
            continue
        try:
            svg = base64.b64decode(daten, validate=True)
            if svg[:2] == b"\x1f\x8b":
                svg = gzip.decompress(svg)
        except (ValueError, OSError, EOFError):
            raise NichtVerifiziert("logotype data unreadable") from None
        return svg
    raise NichtVerifiziert("no SVG in the logotype extension")


def zertifikat_pruefen(pem: bytes, domain: str, jetzt=None) -> bytes:
    """Das Logo aus einem gueltigen Markenzertifikat fuer ``domain``, oder ``NichtVerifiziert``."""
    jetzt = jetzt or utcnow()
    try:
        kette = x509.load_pem_x509_certificates(pem)
    except ValueError:
        raise NichtVerifiziert("not a PEM certificate chain") from None
    blatt, zwischen = kette[0], kette[1:]

    if ZWECK_BIMI not in (_zwecke(blatt) or set()):
        raise NichtVerifiziert("not issued for BIMI")
    try:
        namen = {
            n.lower()
            for n in blatt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        }
    except x509.ExtensionNotFound:
        namen = set()
    if domain.lower() not in namen and stammdomain(domain) not in namen:
        raise NichtVerifiziert("certificate does not name the domain")

    # ⚠️ **Die Kette von unten nach oben, jede Stufe mit Unterschrift.** Was
    # die Datei sonst noch enthaelt (auch eine mitgelieferte Wurzel), zaehlt
    # nur als Zwischenglied; geglaubt wird am Ende allein den festen Wurzeln.
    aktuell = blatt
    for _ in range(5):
        if not (aktuell.not_valid_before_utc <= jetzt <= aktuell.not_valid_after_utc):
            raise NichtVerifiziert("certificate outside its validity")
        wurzel = next((w for w in WURZELN if _ausgestellt_von(aktuell, w)), None)
        if wurzel is not None:
            if not (wurzel.not_valid_before_utc <= jetzt <= wurzel.not_valid_after_utc):
                raise NichtVerifiziert("root outside its validity")
            svg = logo_aus_zertifikat(blatt)
            svg_pruefen(svg)
            return svg
        eltern = next(
            (
                z
                for z in zwischen
                # Ein selbst unterschriebenes Zertifikat ist eine Wurzel, kein
                # Zwischenglied, und Wurzeln kommen nur aus der festen Liste.
                if z.subject == aktuell.issuer
                and z.subject != z.issuer
                and _ist_aussteller(z)
                and _ausgestellt_von(aktuell, z)
            ),
            None,
        )
        if eltern is None:
            raise NichtVerifiziert("chain does not reach a BIMI root")
        # Ein Zwischenglied, das Zwecke nennt, muss BIMI darunter haben.
        zwecke = _zwecke(eltern)
        if zwecke is not None and ZWECK_BIMI not in zwecke:
            raise NichtVerifiziert("intermediate not for BIMI")
        aktuell = eltern
    raise NichtVerifiziert("chain too long")


# --- Das SVG ------------------------------------------------------------------ #


_VERBOTEN = frozenset({"script", "foreignobject", "iframe", "image", "use", "animation", "handler", "listener", "a"})


def svg_pruefen(svg: bytes) -> None:
    """⚠️ **Streng nach SVG Tiny PS, dem Profil, das BIMI vorschreibt.**

    Das Profil kennt weder Skripte noch Verweise nach draussen noch
    eingebettete Bilder. Was eines davon traegt, ist kein gueltiges Logo, und
    nexmail liefert es nicht aus: Es laege unter nexmails eigener Adresse.
    """
    if len(svg) > MAX_SVG:
        raise NichtVerifiziert("SVG too large")
    if b"<!doctype" in svg.lower() or b"<!entity" in svg.lower():
        raise NichtVerifiziert("SVG with DTD")
    try:
        wurzel = ET.fromstring(svg)
    except ET.ParseError:
        raise NichtVerifiziert("SVG unreadable") from None
    if wurzel.tag.rpartition("}")[2] != "svg" or wurzel.get("baseProfile", "").lower() != "tiny-ps":
        raise NichtVerifiziert("not SVG Tiny PS")
    for element in wurzel.iter():
        if element.tag.rpartition("}")[2].lower() in _VERBOTEN:
            raise NichtVerifiziert("SVG element not allowed")
        for name, wert in element.attrib.items():
            kurz = name.rpartition("}")[2].lower()
            if kurz.startswith("on"):
                raise NichtVerifiziert("SVG event handler")
            if kurz == "href" and not wert.startswith("#"):
                raise NichtVerifiziert("SVG reference outside the document")
            if "url(" in wert.replace(" ", "").lower() and "url(#" not in wert.replace(" ", "").lower():
                raise NichtVerifiziert("SVG reference outside the document")


# --- Holen und merken ----------------------------------------------------------- #


def _suchen(domain: str) -> bytes | None:
    if not dmarc_durchgesetzt(domain):
        return None
    adresse = zertifikatsadresse(domain)
    if adresse is None:
        return None
    try:
        pem = bildvermittler.datei_holen(adresse, MAX_ZERTIFIKAT, ZEITGRENZE)
        return zertifikat_pruefen(pem, domain)
    except bildvermittler.Abgelehnt as fehler:
        logger.info("BIMI certificate for %s not reachable (%s).", domain, fehler.kennung)
    except NichtVerifiziert as fehler:
        logger.info("BIMI certificate for %s rejected: %s.", domain, fehler)
    return None


_SCHLOESSER: dict[str, threading.Lock] = {}
_SCHLOSS_DER_SCHLOESSER = threading.Lock()


def _schloss(domain: str) -> threading.Lock:
    """⚠️ **Eine Domain wird nur einmal gleichzeitig geholt.** Eine Liste mit
    zehn Mails derselben Firma fragt zehnmal auf einmal an."""
    with _SCHLOSS_DER_SCHLOESSER:
        return _SCHLOESSER.setdefault(domain, threading.Lock())


def _frisch(eintrag: Absenderlogo | None, jetzt) -> bool:
    if eintrag is None:
        return False
    return jetzt - eintrag.geholt_am < (FRISCH if eintrag.inhalt else NICHTS_FRISCH)


def logo(db: Session, domain: str, jetzt=None) -> bytes | None:
    """Das gepruefte Logo einer Domain, aus dem Zwischenspeicher oder frisch."""
    jetzt = jetzt or utcnow()
    eintrag = db.get(Absenderlogo, domain)
    if not _frisch(eintrag, jetzt):
        with _schloss(domain):
            eintrag = db.get(Absenderlogo, domain, populate_existing=True)
            if not _frisch(eintrag, jetzt):
                gefunden = _suchen(domain)
                if eintrag is None:
                    eintrag = Absenderlogo(domain=domain)
                    db.add(eintrag)
                eintrag.inhalt = gefunden
                eintrag.typ = "image/svg+xml" if gefunden else ""
                eintrag.geholt_am = jetzt
                db.commit()
                logger.info("Brand logo for %s: %s.", domain, "verified" if gefunden else "none")
    return eintrag.inhalt if eintrag is not None and eintrag.inhalt else None


# --- Was vor der Zeile steht ------------------------------------------------------ #


def kontaktfoto(db: Session, person: Benutzer, adresse: str) -> tuple[bytes, str] | None:
    """Das Foto des Kontakts mit dieser Adresse, als Haupt- oder Zweitadresse."""
    adresse = adresse.strip().lower()
    muster = "%" + adresse.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    for kontakt in (
        db.query(Kontakt)
        .filter(
            Kontakt.benutzer_id == person.id,
            or_(func.lower(Kontakt.adresse) == adresse, func.lower(Kontakt.adressen).like(muster, escape="\\")),
        )
        .all()
    ):
        # ⚠️ Der LIKE ist nur die Vorauswahl: ``a@example.com`` steckt auch in
        # ``xa@example.com``. Entschieden wird am genauen Wert.
        eigene = {kontakt.adresse.lower()} | {
            str(a.get("adresse", "")).lower() for a in kontakte._json_liste(kontakt.adressen)
        }
        if adresse not in eigene:
            continue
        if kontakt.roh and vcard.hat_foto(kontakt.roh):
            foto = vcard.foto_lesen(kontakt.roh)
            if foto:
                return foto
    return None


def rasterart(inhalt: bytes) -> str | None:
    """Der Typ eines Fotos nach seinen ersten Bytes, nicht nach der Karte."""
    if inhalt.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if inhalt.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if inhalt.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if inhalt[:4] == b"RIFF" and inhalt[8:12] == b"WEBP":
        return "image/webp"
    return None


def bild(db: Session, person: Benutzer, adresse: str, mit_logo: bool) -> tuple[bytes, str] | None:
    """Was vor der Zeile steht: Kontaktfoto, sonst Markenlogo, sonst nichts.

    ``mit_logo`` setzt die Oberflaeche nur an Mails, deren Absenderpruefung
    bestanden ist (``absenderpruefung.geprueft``, im Listenabruf mitgeliefert).
    """
    foto = kontaktfoto(db, person, adresse)
    if foto:
        art = rasterart(foto[0])
        return (foto[0], art) if art else None
    if not (mit_logo and person.absenderlogos_laden):
        return None
    domain = domain_aus(adresse)
    if domain is None:
        return None
    svg = logo(db, domain)
    return (svg, "image/svg+xml") if svg else None
