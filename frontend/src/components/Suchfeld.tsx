/* Das eine Suchfeld, in jeder Ansicht gleich (Mail, Kalender, Kontakte).
 *
 * ⚠️ **Aussehen wie in nexnotes** (gemeldet am 23.11.2026, Vorbild nexnotes
 * `search/register.tsx`): 36 px hoch, 9 px Ecken, heller Rahmen auf dem Grund
 * der Leiste, Lupe links in 15 px, Platzhalter leise, rechts das Kürzel als
 * kleines Kästchen. Wer eine der Apps kennt, erkennt die Suche in der anderen.
 *
 * Strg+K (Mac: ⌘K) springt hinein, wie in den anderen Apps; Strg+F auch.
 *
 * Rechts daneben kann etwas stehen, das zur Suche gehört (in der Mail: wo
 * gesucht wird). Es steht im Feld, nicht daneben.
 */
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Search } from 'lucide-react'

/** Mac oder nicht: dort heißt die Taste ⌘. */
const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

/** Strg+K oder Strg+F (Mac: ⌘), ohne Umschalt und Alt. */
export function istSuchtaste(e: Pick<KeyboardEvent, 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey' | 'key'>): boolean {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return false
  const k = e.key.toLowerCase()
  return k === 'k' || k === 'f'
}

interface Props {
  wert: string
  aufWert: (w: string) => void
  platzhalter: string
  /** Name für Vorlesehilfen, wenn er vom Platzhalter abweicht. */
  label?: string
  /** Ob Strg+K (und Strg+F) ins Feld springen und das Kürzel im Feld steht.
   *  ⚠️ Nur ein Feld je Ansicht setzt das; es gibt nur eine Suche. */
  tasten?: boolean
  /** Das Kürzel im Feld ausblenden (schmal, dort gibt es keine Tastatur). */
  ohneKuerzel?: boolean
  /** Was rechts im Feld zur Suche gehört. */
  rechts?: ReactNode
  className?: string
}

export function Suchfeld({ wert, aufWert, platzhalter, label, tasten = false, ohneKuerzel = false, rechts, className = '' }: Props) {
  const { t } = useTranslation()
  const feld = useRef<HTMLInputElement>(null)

  /* ⚠️ **Strg+K springt in die Suche, wie in nexnotes, nextasks und nextime**
     (seit 23.11.2026; vorher öffnete Strg+K hier die Befehlspalette, die liegt
     jetzt auf Strg+Umschalt+P). Strg+F bleibt dazu: In einem Mail-Client
     durchsucht die Suche der App alles, die des Browsers nur, was gerade
     sichtbar ist. Über einem Fenster gehört die Tastatur dem Fenster. */
  useEffect(() => {
    if (!tasten) return
    function beiTaste(e: KeyboardEvent) {
      if (!istSuchtaste(e)) return
      if (document.querySelector('[aria-modal="true"]')) return
      e.preventDefault()
      feld.current?.focus()
      feld.current?.select()
    }
    document.addEventListener('keydown', beiTaste)
    return () => document.removeEventListener('keydown', beiTaste)
  }, [tasten])

  const kuerzel = tasten && !ohneKuerzel ? (MAC ? '⌘ K' : t('suche.kuerzel')) : ''

  return (
    <div
      className={
        'flex h-9 min-w-0 items-center gap-2 rounded-[9px] border border-line bg-surface-1 px-2.5 ' +
        'transition-[border-color,box-shadow] duration-[var(--dur-fast)] ' +
        'focus-within:border-accent focus-within:shadow-[var(--focus-ring)] ' +
        className
      }
    >
      <Search aria-hidden className="size-[15px] shrink-0 text-fg-4" strokeWidth={2} />
      <input
        ref={feld}
        type="search"
        value={wert}
        onChange={(e) => aufWert(e.target.value)}
        placeholder={platzhalter}
        aria-label={label ?? platzhalter}
        className="min-w-0 flex-1 bg-transparent text-[13.5px] text-fg-1 outline-none placeholder:text-fg-4 [&::-webkit-search-cancel-button]:hidden"
      />
      {kuerzel && (
        <kbd
          aria-hidden
          className="hidden shrink-0 rounded border border-line px-1.5 font-mono text-[11px] leading-[18px] text-fg-4 md:inline"
        >
          {kuerzel}
        </kbd>
      )}
      {rechts}
    </div>
  )
}
