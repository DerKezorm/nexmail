/* Wo eine Mail am Schreibtisch aufgeht.
 *
 * `rechts` ist der Lesebereich neben der Liste, wie bisher. Die beiden
 * anderen blenden ihn aus: Die Liste bekommt die ganze Breite, ein Klick
 * markiert nur, erst ein Doppelklick öffnet — über die Liste (`ganz`, wie am
 * Telefon) oder als Fenster darüber (`fenster`).
 *
 * ⚠️ **Nur am Schreibtisch.** Schmal gibt es keinen Lesebereich neben der
 * Liste; dort gilt der Modus nicht, und der Knopf fehlt.
 *
 * Ohne Browser, damit die schnelle Prüfebene es laden kann.
 */

export type Lesemodus = 'rechts' | 'ganz' | 'fenster'

const REIHE: Lesemodus[] = ['rechts', 'ganz', 'fenster']

/** Der nächste Modus beim Klick auf den Knopf. */
export function naechsterLesemodus(jetzt: Lesemodus): Lesemodus {
  const stelle = REIHE.indexOf(jetzt)
  return REIHE[(stelle + 1) % REIHE.length]
}

/** Der gemerkte Wert kommt aus dem `localStorage` — alles Unbekannte ist
 *  der Lesebereich rechts, nicht ein Modus, den es nicht gibt. */
export function lesemodusAus(wert: unknown): Lesemodus {
  return REIHE.includes(wert as Lesemodus) ? (wert as Lesemodus) : 'rechts'
}
