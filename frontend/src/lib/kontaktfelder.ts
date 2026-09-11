/* Die Regeln der Kontaktmaske, ohne Browser.
 *
 * Seit dem Felder-Schritt (11.09.2026) trägt ein Kontakt Vor- und Nachname,
 * Spitzname, Abteilung, Position, Geburtstag, Webseite und drei Listen:
 * Nummern, Adressen, Anschriften. Jeder Eintrag hat eine Art (Mobil, Privat,
 * Arbeit …), wahlweise eine eigene Beschriftung, und genau einer je Liste
 * trägt den Stern.
 *
 * ⚠️ **Der Stern ist nexmails Sache, nicht die der Karte.** Er sagt, welche
 * Nummer die Liste zeigt und welche Adresse beim Adressieren genommen wird.
 * Auf die Karte geht er nicht (Apples `pref` trägt die zuerst eingetragene
 * Nummer, meist das Festnetz); beim Lesen fällt er auf das Handy, sonst auf
 * `pref`, sonst auf den ersten Eintrag.
 *
 * ⚠️ **Genau ein Stern, nie keiner.** Fällt die Zeile mit dem Stern weg,
 * wandert er auf die erste; die erste Zeile einer leeren Liste bekommt ihn.
 * Sonst hätte der Kontakt keine Nummer, die die Liste zeigen könnte.
 *
 * ⚠️ **Die Auswahl „Eigene …" ist eine Beschriftung, keine Art.** Apple hält
 * es genauso: `item2.X-ABLabel:Zweitbüro` statt eines Typs. Deshalb ist die
 * Art dann leer, und der Text steht in `beschriftung`. */

export interface Nummer {
  nummer: string
  art: string
  beschriftung: string
  bevorzugt: boolean
}

export interface Adresse {
  adresse: string
  art: string
  beschriftung: string
  bevorzugt: boolean
}

export interface Anschrift {
  strasse: string
  plz: string
  ort: string
  region: string
  land: string
  postfach: string
  zusatz: string
  art: string
  beschriftung: string
  bevorzugt: boolean
}

export interface Weiteres {
  art: string
  beschriftung: string
  text: string
}

export interface Kontaktfelder {
  vorname: string
  nachname: string
  spitzname: string
  firma: string
  abteilung: string
  titel: string
  geburtstag: string
  webseite: string
  notiz: string
  nummern: Nummer[]
  adressen: Adresse[]
  anschriften: Anschrift[]
}

export const NUMMER_ARTEN = ['cell', 'home', 'work', 'main', 'fax', 'pager', 'other'] as const
export const ADRESSE_ARTEN = ['home', 'work', 'other'] as const
export const ANSCHRIFT_ARTEN = ['home', 'work', 'other'] as const
/** Der Wert der Auswahl, hinter dem das Textfeld für die eigene Beschriftung erscheint. */
export const EIGEN = 'eigen'

type MitStern = { bevorzugt: boolean }
type MitArt = { art: string; beschriftung: string }

export function leereFelder(): Kontaktfelder {
  return {
    vorname: '',
    nachname: '',
    spitzname: '',
    firma: '',
    abteilung: '',
    titel: '',
    geburtstag: '',
    webseite: '',
    notiz: '',
    nummern: [],
    adressen: [],
    anschriften: [],
  }
}

/** Die Felder aus einer Zeile der Schnittstelle, als eigene Kopie: Das
 *  Formular ändert sie, die Liste links soll davon nichts merken. */
export function felderAusKontakt(k: Partial<Kontaktfelder>): Kontaktfelder {
  const leer = leereFelder()
  return {
    ...leer,
    ...Object.fromEntries(
      (Object.keys(leer) as Array<keyof Kontaktfelder>)
        .filter((f) => typeof k[f] === 'string')
        .map((f) => [f, k[f]]),
    ),
    nummern: (k.nummern ?? []).map((n) => ({ ...n })),
    adressen: (k.adressen ?? []).map((a) => ({ ...a })),
    anschriften: (k.anschriften ?? []).map((a) => ({ ...a })),
  }
}

export function neueNummer(vorhandene: Nummer[]): Nummer {
  // Die erste Nummer ist meist das Handy, jede weitere eher Festnetz.
  return { nummer: '', art: vorhandene.length === 0 ? 'cell' : 'home', beschriftung: '', bevorzugt: false }
}

export function neueAdresse(): Adresse {
  return { adresse: '', art: 'home', beschriftung: '', bevorzugt: false }
}

export function neueAnschrift(): Anschrift {
  return {
    strasse: '',
    plz: '',
    ort: '',
    region: '',
    land: '',
    postfach: '',
    zusatz: '',
    art: 'home',
    beschriftung: '',
    bevorzugt: false,
  }
}

/** Was die Auswahl zeigt: die Art, oder „Eigene …" bei einer Beschriftung.
 *  Eine Zeile ohne Art und ohne Beschriftung (`TEL;type=VOICE`) ist
 *  „Sonstige". */
export function auswahlWert(e: MitArt): string {
  if (e.beschriftung || e.art === EIGEN) return EIGEN
  return e.art || 'other'
}

/** Die Auswahl setzt die Art. „Eigene …" merkt sich als Art `eigen`, bis ein
 *  Text dasteht — sonst fiele die Auswahl auf „Sonstige" zurück, bevor jemand
 *  tippen kann. Der Server kennt `eigen` nicht und macht daraus die leere Art;
 *  gezählt wird dort nur die Beschriftung. */
export function artSetzen<T extends MitArt>(e: T, wert: string): T {
  if (wert === EIGEN) return { ...e, art: EIGEN }
  return { ...e, art: wert, beschriftung: '' }
}

export function sternSetzen<T extends MitStern>(liste: T[], index: number): T[] {
  return liste.map((e, i) => ({ ...e, bevorzugt: i === index }))
}

export function zeileHinzufuegen<T extends MitStern>(liste: T[], neu: T): T[] {
  return [...liste, { ...neu, bevorzugt: liste.length === 0 }]
}

export function zeileEntfernen<T extends MitStern>(liste: T[], index: number): T[] {
  const rest = liste.filter((_, i) => i !== index)
  if (rest.length > 0 && !rest.some((e) => e.bevorzugt)) {
    rest[0] = { ...rest[0], bevorzugt: true }
  }
  return rest
}

/** Ob überhaupt etwas eingegeben ist — der Server verlangt wenigstens Name,
 *  Adresse, Nummer oder Firma. */
export function etwasDrin(f: Kontaktfelder): boolean {
  return Boolean(
    f.vorname.trim() ||
      f.nachname.trim() ||
      f.firma.trim() ||
      f.nummern.some((n) => n.nummer.trim()) ||
      f.adressen.some((a) => a.adresse.trim()),
  )
}

/** Was die Liste links als Untertitel bekommt: die Nummer mit Stern, sonst
 *  die erste. Nur für Anzeigen, die keine Zeile der Schnittstelle haben. */
export function mitStern<T extends MitStern>(liste: T[]): T | undefined {
  return liste.find((e) => e.bevorzugt) ?? liste[0]
}

/** Die Beschriftung einer Zeile: die eigene, sonst die übersetzte Art. Apples
 *  Wörter („Anniversary", „Mother") werden übersetzt, wenn der Katalog sie
 *  kennt, sonst stehen sie, wie sie kamen. */
export function beschriftungText(
  e: { art: string; beschriftung: string },
  t: (schluessel: string) => string,
  kennt: (schluessel: string) => boolean,
): string {
  if (e.beschriftung) {
    const schluessel = `kontakte.apple_${e.beschriftung.toLowerCase()}`
    return kennt(schluessel) ? t(schluessel) : e.beschriftung
  }
  if (!e.art) return ''
  const schluessel = `kontakte.art_${e.art}`
  return kennt(schluessel) ? t(schluessel) : e.art
}
