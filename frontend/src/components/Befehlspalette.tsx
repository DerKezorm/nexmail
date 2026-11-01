/* Strg+K: jeder Handgriff und jeder Ordner, ohne die Hand von der Tastatur.
 *
 * ⚠️ **Das Eingabefeld behält den Fokus**, die Pfeile bewegen nur die Markierung
 * (`aria-activedescendant`). Wanderte der Fokus in die Liste, ginge das nächste
 * Zeichen ins Leere, und die Tastenbefehle der Liste schlügen zu: `E` archiviert.
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Search } from 'lucide-react'
import { befehleFiltern } from '../lib/befehle'
import type { Befehl } from '../lib/befehle'

interface Props {
  befehle: Befehl[]
  /** Gruppen, die erst beim Suchen erscheinen. */
  nurGesucht: Set<string>
  /** Überschrift je Gruppe. */
  gruppen: Record<string, string>
  aufSchliessen: () => void
}

const zeilenKennung = (i: number) => `befehl-${i}`

export function Befehlspalette({ befehle, nurGesucht, gruppen, aufSchliessen }: Props) {
  const { t } = useTranslation()
  const [suche, setSuche] = useState('')
  const [stelle, setStelle] = useState(0)

  const treffer = useMemo(
    () => befehleFiltern(befehle, suche, nurGesucht),
    [befehle, suche, nurGesucht],
  )

  useEffect(() => setStelle(0), [suche])

  useEffect(() => {
    document.getElementById(zeilenKennung(stelle))?.scrollIntoView({ block: 'nearest' })
  }, [stelle])

  /* ⚠️ **Erst schließen, dann handeln.** Der Befehl kann ein Fenster öffnen, und
     das will den Fokus für sich. */
  function ausfuehren(b: Befehl | undefined) {
    if (!b) return
    aufSchliessen()
    b.tun()
  }

  function beiTaste(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      aufSchliessen()
    } else if (e.key === 'ArrowDown' && treffer.length > 0) {
      e.preventDefault()
      setStelle((s) => (s + 1) % treffer.length)
    } else if (e.key === 'ArrowUp' && treffer.length > 0) {
      e.preventDefault()
      setStelle((s) => (s - 1 + treffer.length) % treffer.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      ausfuehren(treffer[stelle])
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-[var(--surface-overlay)] p-4 pt-[12vh] backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) aufSchliessen()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('befehle.titel')}
        className="flex max-h-[60vh] w-full max-w-[560px] flex-col overflow-hidden rounded-xl border border-line bg-surface-1 shadow-[var(--shadow-3)]"
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-line-subtle px-3 py-2.5">
          <Search className="size-4 shrink-0 text-fg-4" aria-hidden />
          <input
            autoFocus
            role="combobox"
            aria-expanded
            aria-controls="befehle-liste"
            aria-activedescendant={treffer.length > 0 ? zeilenKennung(stelle) : undefined}
            aria-label={t('befehle.suche')}
            placeholder={t('befehle.suche')}
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            onKeyDown={beiTaste}
            className="min-w-0 flex-1 bg-transparent text-sm text-fg-1 outline-none placeholder:text-fg-4"
          />
        </div>

        <ul
          id="befehle-liste"
          role="listbox"
          aria-label={t('befehle.titel')}
          className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-1"
        >
          {treffer.map((b, i) => (
            <li key={b.id} role="presentation">
              {b.gruppe !== treffer[i - 1]?.gruppe && !suche.trim() && (
                <p
                  aria-hidden
                  className="mb-0 px-2.5 pt-2 pb-1 text-[11px] font-semibold tracking-[0.06em] text-fg-4 uppercase"
                >
                  {gruppen[b.gruppe]}
                </p>
              )}
              <button
                id={zeilenKennung(i)}
                type="button"
                role="option"
                aria-selected={i === stelle}
                tabIndex={-1}
                onMouseMove={() => setStelle(i)}
                onClick={() => ausfuehren(b)}
                className={
                  'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] [&_svg]:size-4 [&_svg]:shrink-0 ' +
                  (i === stelle ? 'bg-surface-3 ' : '') +
                  (b.gefaehrlich ? 'text-danger' : 'text-fg-1')
                }
              >
                {b.symbol}
                <span className="min-w-0 truncate">{b.text}</span>
                {suche.trim() && (
                  <span className="ml-auto shrink-0 pl-3 text-[11px] text-fg-4">
                    {gruppen[b.gruppe]}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>

        {treffer.length === 0 && (
          <p role="status" className="mb-0 px-4 py-3 text-[13px] text-fg-3">
            {t('befehle.nichts')}
          </p>
        )}
      </div>
    </div>
  )
}
