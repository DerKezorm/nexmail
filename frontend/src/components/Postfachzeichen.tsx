/* Woran man ein Postfach erkennt: sein Symbol in seiner Farbe, ohne Symbol der
 * Punkt wie bisher (seit 24.11.2026, gewünscht: „wenn man kein icon will … dann
 * bleibt der punkt“).
 *
 * ⚠️ **Die Farbe:** `farbton` (wie nextasks: Name oder `#rrggbb`), sonst eine
 * der sechs geprüften Postfachfarben (`farbe`, `lib/farben.ts`).
 *
 * ⚠️ **Fester Platz in Symbolbreite**, auch für den Punkt (gemeldet am
 * 24.11.2026): Sonst rückt eine Zeile mit Symbol alles dahinter ein, und in den
 * Favoriten stehen die Posteingänge nicht mehr untereinander.
 */
import { createElement } from 'react'
import type { Postfachfarbe } from '../daten/typen'
import { PUNKT_KLASSE, TEXT_KLASSE } from '../lib/farben'
import { tonVon } from '../lib/farbtoene'
import { symbolFuer } from '../lib/nextasksSymbole'

export interface Postfachmerkmale {
  farbe: Postfachfarbe | number
  farbton?: string
  symbol?: string
}

const PUNKT = { klein: 'size-2', mittel: 'size-2.5', gross: 'size-3' } as const
const SYMBOL = { klein: 'size-3', mittel: 'size-3.5', gross: 'size-4' } as const

export function Postfachzeichen({
  konto,
  groesse = 'klein',
  className = '',
}: {
  konto: Postfachmerkmale
  groesse?: keyof typeof PUNKT
  className?: string
}) {
  const ton = tonVon(konto.farbton)
  const farbe = (konto.farbe || 1) as Postfachfarbe
  return (
    <span aria-hidden className={`inline-flex ${SYMBOL[groesse]} shrink-0 items-center justify-center ${className}`}>
      {konto.symbol ? (
        createElement(symbolFuer(konto.symbol), {
          className: `${SYMBOL[groesse]} ${ton ? '' : TEXT_KLASSE[farbe]}`,
          style: ton ? { color: ton } : undefined,
          strokeWidth: 2.25,
        })
      ) : (
        <span
          className={`${PUNKT[groesse]} rounded-full ${ton ? '' : PUNKT_KLASSE[farbe]}`}
          style={ton ? { backgroundColor: ton } : undefined}
        />
      )}
    </span>
  )
}
