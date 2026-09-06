/* Wie ein Kontakt in einer Liste beschriftet wird.
 *
 * ⚠️ **Seit dem 05.09.2026 darf die Adresse fehlen.** Mit CardDAV ist nexmail
 * der zweite Client einer Kontaktliste, und die hat Menschen ohne Postfach:
 * die Werkstatt, die Oma. Die Liste zeigte bis dahin `name || adresse` und
 * darunter die Adresse; ein Kontakt ohne beides wäre eine leere Zeile gewesen.
 *
 * Genommen wird, was da ist: erst der Name, sonst die Firma, sonst die
 * Adresse, sonst die Nummer. Darunter steht das Nächste, das nicht schon oben
 * steht. Ohne Browser, damit die schnelle Prüfebene es laden kann.
 *
 * ⚠️ **Die Firma steht vor Adresse und Nummer.** Ein Firmen-Kontakt von Apple
 * trägt seinen Namen in `ORG` und sonst keinen; die erste Fassung betitelte
 * ihn mit der Nummer und schrieb „Polizei Beispielstadt" klein darunter. Am
 * 05.09.2026 an einem echten iCloud-Buch aufgefallen. */
export interface Beschriftbar {
  name: string
  adresse: string
  telefon: string
  firma: string
}

export function beschriftung(k: Beschriftbar): { titel: string; unter: string } {
  const titel = k.name || k.firma || k.adresse || k.telefon
  const unter = [k.adresse, k.telefon, k.firma].find((w) => w && w !== titel) ?? ''
  return { titel, unter }
}

/** Wie eine Nummer oder Adresse aus der Karte beschriftet wird.
 *
 * ⚠️ **Drei Quellen, eine Reihenfolge.** Apple beschriftet über Gruppen mit
 * eigenen Wörtern („Mobile", „HomeFAX", „Other"), die übersetzt werden; eine
 * eigene Beschriftung des Menschen („Mutter") steht wörtlich da; ohne beides
 * entscheiden die Typen der Zeile (`cell,voice,pref`). Ohne Browser, damit
 * die schnelle Prüfebene es laden kann. */
export type NummerArt = 'cell' | 'home' | 'work' | 'fax' | 'main' | 'pager' | ''

const APPLE_WOERTER: Record<string, NummerArt> = {
  mobile: 'cell',
  iphone: 'cell',
  home: 'home',
  work: 'work',
  main: 'main',
  homefax: 'fax',
  workfax: 'fax',
  otherfax: 'fax',
  pager: 'pager',
  other: '',
}

export function nummerArt(typen: string): NummerArt {
  const t = typen.split(',').map((x) => x.trim().toLowerCase())
  if (t.some((x) => x === 'cell' || x === 'iphone' || x === 'mobile')) return 'cell'
  if (t.includes('fax')) return 'fax'
  if (t.includes('pager')) return 'pager'
  if (t.includes('main')) return 'main'
  if (t.includes('work')) return 'work'
  if (t.includes('home')) return 'home'
  return ''
}

export function beschriftungFuer(
  eintrag: { typen: string; beschriftung: string },
  uebersetzt: (art: Exclude<NummerArt, ''>) => string,
): string {
  const wort = eintrag.beschriftung.trim()
  const schluessel = wort.toLowerCase()
  if (schluessel in APPLE_WOERTER) {
    const art = APPLE_WOERTER[schluessel]
    return art ? uebersetzt(art) : ''
  }
  if (wort) return wort
  const art = nummerArt(eintrag.typen)
  return art ? uebersetzt(art) : ''
}

/** Welche Kontakte die Liste zeigt, nach den Haken an den Büchern.
 *
 * ⚠️ **Ein Kontakt, dessen Buch die Liste nicht kennt, bleibt sichtbar.**
 * Versteckt wird nur, was ausdrücklich abgehakt ist; alles andere wäre ein
 * Eintrag, der unsichtbar ist, ohne gelöscht zu sein, und das sieht aus wie
 * Datenverlust. */
export function sichtbareKontakte<K extends { adressbuch_id?: string | null }>(
  liste: K[],
  buecher: Array<{ id: string; sichtbar: boolean }>,
): K[] {
  const versteckt = new Set(buecher.filter((b) => !b.sichtbar).map((b) => b.id))
  return liste.filter((k) => !k.adressbuch_id || !versteckt.has(k.adressbuch_id))
}
