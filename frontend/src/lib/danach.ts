/* Was nach Löschen, Archivieren oder Verschieben aufgeht.
 *
 * Outlooks Einstellung „Nach dem Verschieben oder Löschen eines Elements",
 * dazu „die neueste". Gewünscht in Issue #6, ab Werk `nichts` wie bisher.
 *
 * ⚠️ **Entschieden wird an der NEUEN Liste, nicht an der alten.** Nach einer
 * Handlung lädt die Liste neu; was weg ist, ist weg, und bei einer
 * Mehrfachauswahl ist womöglich auch der alte Nachbar dabei. Gesucht wird
 * deshalb die letzte Zeile, die in der alten Liste VOR der offenen stand und
 * noch da ist. „Vorige" ist sie selbst, „nächste" die Zeile danach. Neue Post
 * oben verschiebt damit nichts.
 *
 * ⚠️ **Am Ende der Liste geht nichts auf**, auch nicht die andere Richtung.
 * Wer von oben nach unten abarbeitet, soll am Ende eine leere Fläche sehen,
 * nicht die Mail, die er gerade hinter sich gelassen hat.
 *
 * ⚠️ **Steht die offene Mail noch da, bleibt sie offen.** Dann hat die
 * Handlung sie nicht getroffen (Mehrfachauswahl ohne sie) oder sie ist
 * gescheitert; springen hieße, eine Mail zu überspringen, die niemand
 * angefasst hat.
 *
 * Ohne Browser, damit die schnelle Prüfebene es laden kann.
 */

export type Danach = 'nichts' | 'naechste' | 'vorige' | 'neueste'

export const DANACH_REIHE: Danach[] = ['nichts', 'naechste', 'vorige', 'neueste']

/** Der gemerkte Wert kommt aus dem `localStorage`; alles Unbekannte ist
 *  `nichts`, also das Verhalten von vor der Einstellung. */
export function danachAus(wert: unknown): Danach {
  return DANACH_REIHE.includes(wert as Danach) ? (wert as Danach) : 'nichts'
}

/** Welche Mail nach der Handlung gewählt ist, oder `null` für keine.
 *
 *  `alt` und `neu` sind die Kennungen der Liste vor und nach der Handlung,
 *  in der Reihenfolge, in der sie dastehen. `offen` ist die Mail, die vorher
 *  gewählt war. */
export function danachWaehlen(
  einstellung: Danach,
  alt: string[],
  neu: string[],
  offen: string | null,
): string | null {
  if (einstellung === 'nichts' || offen === null) return null
  if (neu.includes(offen)) return offen
  if (einstellung === 'neueste') return neu[0] ?? null

  const stelle = alt.indexOf(offen)
  if (stelle < 0) return null
  const davor = new Set(alt.slice(0, stelle))
  let letzte = -1
  neu.forEach((id, i) => {
    if (davor.has(id)) letzte = i
  })

  if (einstellung === 'vorige') return letzte >= 0 ? neu[letzte] : null
  return neu[letzte + 1] ?? null
}
