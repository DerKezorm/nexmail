/* Ein Feld für die Schlagworte eines Postfachs.
 *
 * ⚠️ **Kein Komma-getrenntes Textfeld.** Das sieht einfacher aus und ist es
 * für den Betreiber nicht: Er sieht nicht, was gerade zählt, tippt „privat ,
 * arbeit" und rätselt, ob das Leerzeichen mit im Wort steckt. Fertige
 * Schlagworte stehen deshalb als Pillen da — sichtbar abgeschlossen, einzeln
 * wegzuklicken.
 *
 * ⚠️ **Und was schon vergeben ist, steht darunter.** Ohne das entstehen
 * „Arbeit", „arbeit" und „Job" nebeneinander, und die Gruppierung zerfällt an
 * genau der Stelle, an der sie helfen sollte.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

interface Props {
  werte: string[]
  aufAendern: (werte: string[]) => void
  /** Schlagworte, die an anderen Postfächern schon hängen. */
  vorschlaege?: string[]
}

export function Schlagwortfeld({ werte, aufAendern, vorschlaege = [] }: Props) {
  const { t } = useTranslation()
  const [entwurf, setEntwurf] = useState('')

  function hinzufuegen(roh: string) {
    const wort = roh.replace(',', ' ').trim()
    setEntwurf('')
    if (!wort) return
    // Groß/klein trennt keine Gruppen — dieselbe Regel wie im Server.
    if (werte.some((w) => w.toLowerCase() === wort.toLowerCase())) return
    aufAendern([...werte, wort])
  }

  const offen = vorschlaege.filter(
    (v) => !werte.some((w) => w.toLowerCase() === v.toLowerCase()),
  )

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-fg-2">{t('konto.tags')}</span>

      <div className="fokusrahmen flex min-h-[var(--control-h-md)] flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface-3 px-2 py-1.5 transition-[border-color,box-shadow] duration-[var(--dur-fast)] focus-within:border-accent focus-within:shadow-[var(--focus-ring)]">
        {werte.map((w) => (
          <span
            key={w}
            className="flex items-center gap-1 rounded-pill bg-accent-soft py-0.5 pr-1 pl-2 text-[12px] text-accent-text"
          >
            {w}
            <button
              type="button"
              aria-label={t('konto.tags_entfernen', { wort: w })}
              onClick={() => aufAendern(werte.filter((x) => x !== w))}
              className="rounded-pill p-0.5 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3"
            >
              <X aria-hidden className="size-3" />
            </button>
          </span>
        ))}

        <input
          value={entwurf}
          aria-label={t('konto.tags')}
          placeholder={werte.length ? '' : t('konto.tags_platzhalter')}
          onChange={(e) => {
            // Ein getipptes Komma schließt das Wort ab — wie in jedem
            // Adressfeld. Wer es abtippt, meint genau das.
            if (e.target.value.includes(',')) hinzufuegen(e.target.value)
            else setEntwurf(e.target.value)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              // ⚠️ Sonst schickt Enter das ganze Formular ab, und aus einem
              // halb getippten Schlagwort wird ein gespeichertes Postfach.
              e.preventDefault()
              hinzufuegen(entwurf)
            }
            if (e.key === 'Backspace' && !entwurf && werte.length) {
              aufAendern(werte.slice(0, -1))
            }
          }}
          /* ⚠️ **Auch beim Verlassen übernehmen.** Wer tippt und dann auf
             „Speichern" klickt, hat sein Schlagwort sonst nie vergeben — und
             sieht erst hinterher, dass es fehlt. */
          onBlur={() => hinzufuegen(entwurf)}
          className="min-w-[8rem] flex-1 bg-transparent text-[13px] text-fg-1 outline-none placeholder:text-fg-4"
        />
      </div>

      <span className="text-[11px] text-fg-3">{t('konto.tags_hinweis')}</span>

      {offen.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <span className="text-[11px] text-fg-4">{t('konto.tags_bekannt')}</span>
          {offen.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => hinzufuegen(v)}
              className="rounded-pill border border-line px-2 py-0.5 text-[11px] text-fg-3 transition-colors duration-[var(--dur-fast)] hover:border-accent hover:text-fg-1"
            >
              {v}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
