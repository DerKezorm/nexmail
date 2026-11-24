/* Farben wie in nextasks: elf benannte Töne und eigene als `#rrggbb`
 * (Postfächer seit 24.11.2026, gewünscht: „Farbwahl wie nextasks“; Aufgabenlisten
 * aus nextasks seit MAIL-2).
 *
 * ⚠️ **Eigene Farben werden lesbar gemacht**, wie in nextasks
 * (`lib/color.ts` dort): Reicht der Kontrast zu nexmails Gründen (hell und
 * dunkel) nicht für 3 : 1, wird der Ton Richtung Weiß bzw. Schwarz gezogen.
 * Ein fast schwarzes Postfach verschwände sonst im dunklen Modus.
 *
 * ⚠️ **Leer heißt: die sechs geprüften Postfachfarben** (`lib/farben.ts`), die
 * nexmail selbst vergibt. Sie bleiben die Vorgabe.
 */

/** Die Namen in nextasks' Reihenfolge, mit nextasks' Tönen. */
export const FARBTOENE: Record<string, string> = {
  red: '#d9534f',
  orange: '#dd7a2e',
  yellow: '#d39b12',
  green: '#4f9e3f',
  teal: '#22a08a',
  blue: '#3a84d0',
  indigo: '#5b68cc',
  purple: '#8a59c0',
  pink: '#d65a7c',
  brown: '#9a7550',
  gray: '#7a8890',
}

/** nexmails Gründe, hell und dunkel (Leinwand und Flächen). */
const GRUENDE = ['#ffffff', '#f4f6f5', '#e9eceb', '#0e1211', '#151a18', '#1c2220']

function kanaele(hex: string): [number, number, number] {
  return [1, 3, 5].map((an) => parseInt(hex.slice(an, an + 2), 16)) as [number, number, number]
}

function alsHex(werte: number[]): string {
  return '#' + werte.map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')).join('')
}

function helligkeit(hex: string): number {
  const [r, g, b] = kanaele(hex).map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function kontrast(a: string, b: string): number {
  const [hell, dunkel] = [helligkeit(a), helligkeit(b)].sort((x, y) => y - x)
  return (hell + 0.05) / (dunkel + 0.05)
}

function mischen(a: string, b: string, anteil: number): string {
  const x = kanaele(a)
  const y = kanaele(b)
  return alsHex(x.map((v, i) => v + (y[i] - v) * anteil))
}

/** Ein eigener Ton, der auf allen Gründen mit 3 : 1 steht (wie nextasks). */
export function lesbar(hex: string): string {
  const liest = (wert: string) => GRUENDE.every((g) => kontrast(wert, g) >= 3)
  if (liest(hex)) return hex
  const dunkel = helligkeit(hex) < 0.2
  const hin = dunkel ? '#ffffff' : '#000000'
  const seite = GRUENDE.filter((g) => (helligkeit(g) < 0.5) === dunkel)
  const genug = (wert: string) => seite.every((g) => kontrast(wert, g) >= 3)
  let unten = 0
  let oben = 1
  for (let schritt = 0; schritt < 24; schritt++) {
    const mitte = (unten + oben) / 2
    if (genug(mischen(hex, hin, mitte))) oben = mitte
    else unten = mitte
  }
  return mischen(hex, hin, oben)
}

/** Der Ton zu einem Namen oder `#rrggbb`; `null` für leer oder Unbekanntes. */
export function tonVon(farbton: string | null | undefined): string | null {
  if (!farbton) return null
  if (/^#[0-9a-f]{6}$/.test(farbton)) return lesbar(farbton)
  return FARBTOENE[farbton] ?? null
}
