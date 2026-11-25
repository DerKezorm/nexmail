/* Farbe und Symbol eines Postfachs wählen, wie in nextasks (24.11.2026).
 *
 * ⚠️ **Vorne steht jeweils die Vorgabe:** „Automatisch“ (die sechs geprüften
 * Postfachfarben, die nexmail selbst vergibt) und „Kein Symbol“ (dann bleibt
 * der Punkt). Wer nichts wählt, sieht nexmail wie bisher.
 */
import { createElement, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Search } from 'lucide-react'
import type { Postfachfarbe } from '../daten/typen'
import { PUNKT_KLASSE, TEXT_KLASSE } from '../lib/farben'
import { FARBTOENE, tonVon } from '../lib/farbtoene'
import { symboleSuchen } from '../lib/nextasksSymbole'
import { BESCHRIFTUNG_NORMAL } from '../ds/beschriftung'

/* Nur in den Einstellungen (Postfach-Fenster): normal geschrieben wie dort die Felder. */
const BESCHRIFTUNG = BESCHRIFTUNG_NORMAL

interface Props {
  /** Die automatisch vergebene Farbe (1..6), für „Automatisch“. */
  farbe: Postfachfarbe
  farbton: string
  symbol: string
  aufFarbton: (wert: string) => void
  aufSymbol: (wert: string) => void
}

export function Zeichenwahl({ farbe, farbton, symbol, aufFarbton, aufSymbol }: Props) {
  const { t } = useTranslation()
  const [suche, setSuche] = useState('')
  const eigen = farbton.startsWith('#')
  const ton = tonVon(farbton)
  const treffer = symboleSuchen(suche)

  const kachel = (an: boolean) =>
    'relative flex size-7 items-center justify-center rounded-full border-2 transition-colors ' +
    (an ? 'border-fg-1' : 'border-transparent hover:border-line-strong')

  return (
    <div className="flex flex-col gap-4">
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className={`mb-1 p-0 ${BESCHRIFTUNG}`}>{t('konto.farbe')}</legend>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            aria-pressed={!farbton}
            aria-label={t('konto.farbe_automatisch')}
            title={t('konto.farbe_automatisch')}
            onClick={() => aufFarbton('')}
            className={kachel(!farbton)}
          >
            <span className={`size-5 rounded-full ${PUNKT_KLASSE[farbe]}`} />
            <span className="absolute -right-0.5 -bottom-0.5 rounded-full bg-surface-1 px-0.5 text-[8px] font-bold text-fg-2">
              A
            </span>
          </button>
          {Object.entries(FARBTOENE).map(([name, hex]) => (
            <button
              key={name}
              type="button"
              aria-pressed={farbton === name}
              aria-label={t(`konto.farbname.${name}`)}
              title={t(`konto.farbname.${name}`)}
              onClick={() => aufFarbton(name)}
              className={kachel(farbton === name)}
            >
              <span className="flex size-5 items-center justify-center rounded-full" style={{ backgroundColor: hex }}>
                {farbton === name && <Check className="size-3 text-white" strokeWidth={3} />}
              </span>
            </button>
          ))}
          {/* Eigene Farbe über den Wähler des Systems, wie in nextasks. */}
          <label className={kachel(eigen) + ' cursor-pointer'} title={t('konto.farbe_eigene')}>
            <span
              className="size-5 rounded-full"
              style={{
                background: eigen
                  ? farbton
                  : 'conic-gradient(#d9534f, #d39b12, #4f9e3f, #22a08a, #3a84d0, #8a59c0, #d65a7c, #d9534f)',
              }}
            />
            <input
              type="color"
              aria-label={t('konto.farbe_eigene')}
              value={eigen ? farbton : '#3a84d0'}
              onChange={(e) => aufFarbton(e.target.value.toLowerCase())}
              className="absolute inset-0 cursor-pointer opacity-0"
            />
          </label>
        </div>
        {eigen && ton && ton !== farbton && (
          <p className="mb-0 text-[12px] text-fg-4">{t('konto.farbe_angepasst')}</p>
        )}
      </fieldset>

      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className={`mb-1 p-0 ${BESCHRIFTUNG}`}>{t('konto.symbol')}</legend>
        <label className="flex items-center gap-2 rounded-md border border-line bg-surface-1 px-2.5 py-1.5">
          <Search className="size-3.5 shrink-0 text-fg-4" aria-hidden />
          <input
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            placeholder={t('konto.symbol_suchen')}
            aria-label={t('konto.symbol_suchen')}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-fg-1 outline-none placeholder:text-fg-4"
          />
        </label>
        <div className="grid max-h-44 grid-cols-[repeat(auto-fill,minmax(2.25rem,1fr))] gap-1 overflow-y-auto pr-1">
          {!suche && (
            <button
              type="button"
              aria-pressed={!symbol}
              onClick={() => aufSymbol('')}
              className={
                'col-span-3 flex h-9 items-center justify-center gap-1.5 rounded-md border px-2 text-[12px] ' +
                (!symbol ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-fg-2 hover:bg-surface-3')
              }
            >
              <span className={`size-2.5 rounded-full ${ton ? '' : PUNKT_KLASSE[farbe]}`} style={ton ? { backgroundColor: ton } : undefined} />
              {t('konto.symbol_keins')}
            </button>
          )}
          {treffer.map((s) => (
            <button
              key={s.name}
              type="button"
              aria-pressed={symbol === s.name}
              aria-label={s.name}
              title={s.name}
              onClick={() => aufSymbol(s.name)}
              className={
                'flex h-9 items-center justify-center rounded-md border ' +
                (symbol === s.name ? 'border-accent bg-accent-soft' : 'border-transparent hover:bg-surface-3')
              }
            >
              {createElement(s.icon, {
                className: `size-4 ${ton ? '' : TEXT_KLASSE[farbe]}`,
                style: { color: ton ?? undefined },
                'aria-hidden': true,
              })}
            </button>
          ))}
          {treffer.length === 0 && (
            <p className="col-span-full mb-0 py-2 text-[12px] text-fg-4">{t('konto.symbol_nichts')}</p>
          )}
        </div>
      </fieldset>
    </div>
  )
}
