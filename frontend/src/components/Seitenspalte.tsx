/* Die Spalte links in Kalender, Aufgaben und Kontakten — gebaut wie die
 * Ordnerspalte der Mail: einklappbar über den Knopf oben links, in der Breite
 * zu ziehen (der Griff merkt sie je Ansicht), und unten die Profilzeile.
 *
 * ⚠️ **Eine Spalte, drei Ansichten** (gemeldet am 23.11.2026): Kalender und
 * Kontakte hatten feste Breiten, keine Profilzeile und nichts zum Einklappen;
 * die Aufgaben hatten gar keine Spalte. Derselbe Griff an derselben Stelle,
 * sonst lernt man jede Ansicht neu.
 */
import type { ReactNode } from 'react'
import { Griff } from './Griff'

interface Props {
  offen: boolean
  breite: number
  aufBreite: (b: number) => void
  /** Name des Griffs für Vorlesehilfen. */
  griffLabel: string
  /** Die Profilzeile unten. */
  fuss?: ReactNode
  children: ReactNode
  min?: number
  max?: number
}

export function Seitenspalte({ offen, breite, aufBreite, griffLabel, fuss, children, min = 200, max = 420 }: Props) {
  if (!offen) return null
  return (
    <>
      <aside
        style={{ width: breite }}
        className="flex shrink-0 flex-col border-r border-line-subtle bg-surface-1"
        data-testid="seitenspalte"
      >
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {fuss}
      </aside>
      <Griff breite={breite} aufBreite={aufBreite} min={min} max={max} label={griffLabel} />
    </>
  )
}
