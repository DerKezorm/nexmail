/* Wie die Beschriftungen der Felder aussehen: in der App klein und in Großbuchstaben (das Design-System), in den
 * Einstellungen normal geschrieben wie in nexnotes (Entscheidung vom 25.11.2026: Einstellungsseiten sehen aus wie
 * nexnotes, die übrige App bleibt, wie sie ist).
 *
 * ⚠️ **Ein Kontext, kein Schalter je Feld.** Dieselben Bausteine (Input, Select, Nachfrage, Kalender- und
 * Buchfenster, zweiter Faktor) stehen in den Einstellungen und anderswo; `EinstellungenPage` stellt alles darunter auf
 * „normal“, auch Fenster, die von dort aufgehen.
 */
import { createContext, useContext } from 'react'

export type Beschriftungsart = 'gross' | 'normal'

export const Beschriftung = createContext<Beschriftungsart>('gross')

/** Die Beschriftung eines Feldes, wie das Design-System sie vorgibt. */
export const BESCHRIFTUNG_GROSS = 'text-[12px] font-semibold uppercase tracking-[0.06em] text-fg-3'

/** Die Beschriftung eines Feldes in den Einstellungen, wie in nexnotes (`Field`): normal geschrieben, hell, mittelfett. */
export const BESCHRIFTUNG_NORMAL = 'text-sm font-medium text-fg-1'

/** Die Überschrift einer Gruppe von Feldern in den Einstellungen (`legend`, wie nexnotes' `SubHead`). */
export const GRUPPENTITEL = 'text-sm font-semibold text-fg-1'

/** Die Klassen der Beschriftung an dieser Stelle der App. */
export function useBeschriftung(): string {
  return useContext(Beschriftung) === 'normal' ? BESCHRIFTUNG_NORMAL : BESCHRIFTUNG_GROSS
}
