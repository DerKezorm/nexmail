/* Die Farbe, an der man ein Postfach erkennt.
 *
 * Sechs Toene, in fester Vergabereihenfolge: das erste Postfach bekommt den
 * ersten, das zweite den zweiten. Sie stammen aus der Datenreihe des
 * nexapps-Design-Systems und sind dort auf Kontrast und Farbfehlsichtigkeit
 * geprueft — hell wie dunkel.
 *
 * Deshalb waehlt nexmail sie zu und laesst niemanden selbst mischen: Zwei
 * selbstgewaehlte, kaum unterscheidbare Toene faellt erst auf, wenn man aus
 * dem falschen Postfach geantwortet hat.
 *
 * Die Klassennamen stehen ausgeschrieben da, weil Tailwind nur findet, was
 * woertlich im Quelltext steht - ein zusammengesetztes `bg-data-${n}` waere
 * im Bau spurlos verschwunden.
 */
import type { Postfachfarbe } from '../daten/typen'

export const PUNKT_KLASSE: Record<Postfachfarbe, string> = {
  1: 'bg-data-1',
  2: 'bg-data-2',
  3: 'bg-data-3',
  4: 'bg-data-4',
  5: 'bg-data-5',
  6: 'bg-data-6',
}

export const TEXT_KLASSE: Record<Postfachfarbe, string> = {
  1: 'text-data-1',
  2: 'text-data-2',
  3: 'text-data-3',
  4: 'text-data-4',
  5: 'text-data-5',
  6: 'text-data-6',
}

/** Welche Farbe ein neu angelegtes Postfach bekaeme. */
export function naechsteFarbe(vergeben: Postfachfarbe[]): Postfachfarbe {
  for (let n = 1; n <= 6; n++) {
    if (!vergeben.includes(n as Postfachfarbe)) return n as Postfachfarbe
  }
  // Ab dem siebten Postfach faengt die Reihe wieder von vorn an. Das ist
  // ehrlicher als ein siebter, ungepruefter Ton.
  return ((vergeben.length % 6) + 1) as Postfachfarbe
}
