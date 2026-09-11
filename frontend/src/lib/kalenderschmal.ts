/* Die schmale Kalenderansicht — die Rechnung, ohne Browser.
 *
 * Am Telefon zeigt nexmail den Monat als Raster mit Punkten und darunter die
 * Termine des angetippten Tages, oder eine fortlaufende Terminübersicht. Was
 * dafür gerechnet wird, steht hier, damit die schnelle Prüfebene es laden
 * kann — dieselbe Trennung wie bei `ziehen.ts` und `ueberlappung.ts`. Das
 * Zeichnen sitzt in `pages/KalenderPage.tsx` (`KalenderSchmal`).
 *
 * ⚠️ **Ein Tag ist keine 24 Stunden.** Alle Tagessprünge laufen über
 * `setDate` auf einer Ortszeit, nie über Millisekunden — siehe `ziehen.ts`.
 */
import { imTag } from './kalendertage'
import type { TagVorkommen } from './kalendertage'

export interface Vorkommen extends TagVorkommen {
  kalenderId: string
}

/** Die Tage des Monatsrasters: ab dem Montag der Woche, in der der Erste
 *  liegt, in ganzen Wochen bis zum Sonntag der Woche, in der der Letzte liegt.
 *  ⚠️ Das sind vier, fünf oder sechs Zeilen — nicht immer sechs. Eine feste
 *  sechste Zeile zeigte am Telefon eine Woche des übernächsten Monats und
 *  kostete die Höhe der Tagesliste darunter. */
export function monatsraster(anker: Date): Date[] {
  const erster = new Date(anker.getFullYear(), anker.getMonth(), 1)
  const start = new Date(erster)
  start.setDate(erster.getDate() - ((erster.getDay() + 6) % 7))
  const letzter = new Date(anker.getFullYear(), anker.getMonth() + 1, 0)
  const ende = new Date(letzter)
  ende.setDate(letzter.getDate() + (6 - ((letzter.getDay() + 6) % 7)))
  const tage: Date[] = []
  for (const d = new Date(start); d <= ende; d.setDate(d.getDate() + 1)) tage.push(new Date(d))
  return tage
}

/** Die Termine eines Tages: ganztägige zuerst, dann nach Beginn. Was über
 *  mehrere Tage geht, steht an jedem davon. */
export function tagesliste<T extends Vorkommen>(termine: readonly T[], tag: Date): T[] {
  return termine
    .filter((e) => imTag(e, tag))
    .sort((a, b) => {
      if (a.ganztaegig !== b.ganztaegig) return a.ganztaegig ? -1 : 1
      return a.beginn.localeCompare(b.beginn)
    })
}

/** Die Kalender, die an einem Tag etwas haben — für die Punkte unter der
 *  Zahl: je Kalender einer, in der Reihenfolge des ersten Vorkommens,
 *  höchstens `hoechstens`. Mehr Punkte passen nicht unter eine Zahl, und drei
 *  Kalender an einem Tag sagen schon „voll". */
export function farbpunkte<T extends Vorkommen>(termine: readonly T[], tag: Date, hoechstens = 3): string[] {
  const ids: string[] = []
  for (const e of tagesliste(termine, tag)) {
    if (ids.includes(e.kalenderId)) continue
    ids.push(e.kalenderId)
    if (ids.length === hoechstens) break
  }
  return ids
}

/** Die Terminübersicht: jeder Tag von `von` bis `bis` (ausschließend), an dem
 *  etwas liegt, mit seiner Liste. Tage ohne Termin fallen weg — eine Liste,
 *  die leere Tage aufzählt, ist ein Kalender ohne Raster. */
export function nachTagen<T extends Vorkommen>(
  termine: readonly T[],
  von: Date,
  bis: Date,
): Array<{ tag: Date; termine: T[] }> {
  const raus: Array<{ tag: Date; termine: T[] }> = []
  const d = new Date(von)
  d.setHours(0, 0, 0, 0)
  const ende = new Date(bis)
  ende.setHours(0, 0, 0, 0)
  for (; d < ende; d.setDate(d.getDate() + 1)) {
    const drin = tagesliste(termine, d)
    if (drin.length > 0) raus.push({ tag: new Date(d), termine: drin })
  }
  return raus
}
