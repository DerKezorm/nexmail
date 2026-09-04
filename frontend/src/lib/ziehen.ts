/* Was beim Ziehen eines Termins herauskommt.
 *
 * ⚠️ **Ohne Browser, damit es prüfbar bleibt.** Dieselbe Trennung wie bei
 * `lesegrund.ts` und `pushlage.ts`: Die Maus gehört der Ansicht, die Rechnung
 * gehört hierher. Was hier falsch ist, verschiebt einen echten Termin — und
 * zwar auf dem Server, denn ein Zug geht sofort hinaus.
 */

/** Auf welches Vielfache gerastet wird.
 *
 * ⚠️ **Gerundet, nicht abgeschnitten.** Wer abschneidet, macht aus jedem Zug
 * nach unten einen zu kurzen: 14 Minuten würden zu 0, und der Termin bliebe
 * scheinbar stehen. Thunderbird und Google rastern ebenfalls auf 15.
 */
export const RASTER_MINUTEN = 15

/** Kürzer geht nicht.
 *
 * ⚠️ **Ein Termin von null Minuten ist kein Termin.** Er wäre im Raster
 * unsichtbar und damit nicht mehr anzufassen — man hätte ihn verloren, ohne
 * ihn gelöscht zu haben.
 */
export const MIN_MINUTEN = 15

export interface Zeitraum {
  /** ISO mit Zone, wie der Server es liefert und erwartet. */
  beginn: string
  ende: string
}

/** Wie viele Rasterschritte eine Mausbewegung bedeutet. */
export function minutenAusPixeln(dy: number, stundeHoehe: number): number {
  const roh = (dy / stundeHoehe) * 60
  return Math.round(roh / RASTER_MINUTEN) * RASTER_MINUTEN
}

/** Im Zeitraster verschoben — die Dauer bleibt.
 *
 * ⚠️ **Beide Enden mitschicken.** Der Server lässt ein nicht mitgeschicktes
 * Feld unverändert; wer nur den Beginn setzt, lässt das Ende stehen und macht
 * aus einer Stunde eine halbe. Steht so auch in CLAUDE.md.
 *
 * ⚠️ **Hier ist Millisekunden-Arithmetik richtig**, anders als beim
 * Tagessprung: „eine halbe Stunde später" ist eine Dauer, keine Uhrzeit.
 */
export function verschobenUmMinuten(z: Zeitraum, minuten: number): Zeitraum {
  const ms = minuten * 60_000
  return {
    beginn: new Date(new Date(z.beginn).getTime() + ms).toISOString(),
    ende: new Date(new Date(z.ende).getTime() + ms).toISOString(),
  }
}

/** Auf einen anderen Tag gezogen — die Uhrzeit bleibt, die Dauer auch.
 *
 * ⚠️ **Nicht über Millisekunden rechnen.** Ein Tag hat zweimal im Jahr 23 oder
 * 25 Stunden. Wer 86.400.000 ms addiert, zieht einen Termin von 9 Uhr über die
 * Zeitumstellung auf 8 Uhr — und niemand bringt das mit der Sommerzeit in
 * Verbindung. `setDate` auf einer Ortszeit hält die Wanduhr fest, und genau
 * das meint „auf den nächsten Tag ziehen".
 *
 * ⚠️ **Ganztägig geht NICHT durch die Ortszeit.** Der Wert ist ein
 * Kalendertag auf UTC-Mitternacht; über `new Date(...)` in der Ortszeit landet
 * westlich von Greenwich der Vortag. Dieselbe Falle wie in `fuerFeld`.
 */
export function verschobenUmTage(z: Zeitraum, tage: number, ganztaegig: boolean): Zeitraum {
  if (tage === 0) return { beginn: z.beginn, ende: z.ende }
  if (ganztaegig) return { beginn: tagVerschoben(z.beginn, tage), ende: tagVerschoben(z.ende, tage) }
  return {
    beginn: ortszeitVerschoben(z.beginn, tage),
    ende: ortszeitVerschoben(z.ende, tage),
  }
}

/** Die untere Kante gezogen — nur das Ende wandert.
 *
 * ⚠️ **Der Beginn bleibt, auch wenn man weit nach oben zieht.** Ein Ende vor
 * dem Beginn wäre ein Termin mit negativer Dauer; abgefangen wird das nicht
 * mit einer Meldung, sondern indem die Kante bei `MIN_MINUTEN` stehen bleibt.
 * Eine Fehlermeldung für eine Mausbewegung wäre Schikane.
 */
export function endeGezogen(z: Zeitraum, minuten: number): Zeitraum {
  const a = new Date(z.beginn).getTime()
  const b = new Date(z.ende).getTime() + minuten * 60_000
  const kuerzeste = a + MIN_MINUTEN * 60_000
  return { beginn: z.beginn, ende: new Date(Math.max(b, kuerzeste)).toISOString() }
}

/** Wie viele Tage zwischen zwei Kalendertagen liegen — in der Ortszeit.
 *
 * ⚠️ **Über Mitternacht normiert, nicht über die Differenz in Millisekunden.**
 * Sonst zählt die Zeitumstellung als „nicht ganz ein Tag", und ein Zug über
 * den letzten Oktobersonntag landet einen Tag daneben.
 */
export function tageDazwischen(von: Date, bis: Date): number {
  const a = new Date(von.getFullYear(), von.getMonth(), von.getDate())
  const b = new Date(bis.getFullYear(), bis.getMonth(), bis.getDate())
  return Math.round((b.getTime() - a.getTime()) / 86_400_000)
}

/** Ein Kalendertag (UTC-Mitternacht) um `tage` weiter. */
function tagVerschoben(iso: string, tage: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + tage)
  return `${d.toISOString().slice(0, 10)}T00:00:00Z`
}

/** Ein Zeitpunkt um `tage` weiter, mit derselben Uhrzeit auf der Wanduhr. */
function ortszeitVerschoben(iso: string, tage: number): string {
  const d = new Date(iso)
  d.setDate(d.getDate() + tage)
  return d.toISOString()
}
