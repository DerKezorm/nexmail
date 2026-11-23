/* Mail, Kalender, Aufgaben, Kontakte: die vier Ansichten als Knopfgruppe in
 * der Werkzeugleiste.
 *
 * ⚠️ **Bis zum 23.11.2026 war das eine eigene Leiste ganz links (`NavRail`).**
 * Sie nahm 64 px über die ganze Höhe für vier Symbole (gemeldet: „die
 * verbraucht nur unnötig Platz"). Seitdem stehen die Knöpfe in der
 * Werkzeugleiste jeder Ansicht an derselben Stelle, gleich hinter dem Knopf der
 * Seitenleiste. Die Einstellungen sind keine Ansicht mehr daneben, sondern die
 * Profilzeile unten in der Ordnerspalte, wie in nexnotes.
 *
 * ⚠️ **An „Aufgaben" hängt eine Zahl.** Eine Aufgabenliste, die man erst
 * sieht, wenn man hinklickt, wird vergessen. Die Zahl steht nur da, wenn
 * wirklich etwas offen ist.
 *
 * ⚠️ **Schmal ein einziger Knopf mit Menü.** Vier Symbole neben „Neue
 * Nachricht", Suche und Abgleich ließen der Suche auf 375 px keine 20 px.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarDays, ChevronDown, ListChecks, Mail, Users } from 'lucide-react'

export type Ansicht = 'mail' | 'kalender' | 'aufgaben' | 'kontakte' | 'einstellungen'

interface Props {
  ansicht: Ansicht
  aufAnsicht: (a: Ansicht) => void
  /** Wie viele Aufgaben offen sind. 0 blendet die Zahl aus. */
  offeneAufgaben?: number
  schmal?: boolean
}

export function Ansichtswahl({ ansicht, aufAnsicht, offeneAufgaben = 0, schmal = false }: Props) {
  const { t } = useTranslation()
  const [offen, setOffen] = useState(false)
  const kasten = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!offen) return
    function zu(e: PointerEvent) {
      if (!kasten.current?.contains(e.target as Node)) setOffen(false)
    }
    function taste(e: KeyboardEvent) {
      if (e.key === 'Escape') setOffen(false)
    }
    document.addEventListener('pointerdown', zu)
    document.addEventListener('keydown', taste)
    return () => {
      document.removeEventListener('pointerdown', zu)
      document.removeEventListener('keydown', taste)
    }
  }, [offen])

  const ziele: ReadonlyArray<{ id: Ansicht; Symbol: typeof Mail; text: string; zahl?: number }> = [
    { id: 'mail', Symbol: Mail, text: t('nav.mail') },
    { id: 'kalender', Symbol: CalendarDays, text: t('nav.kalender') },
    { id: 'aufgaben', Symbol: ListChecks, text: t('nav.aufgaben'), zahl: offeneAufgaben },
    { id: 'kontakte', Symbol: Users, text: t('nav.kontakte') },
  ]

  const zahl = (z?: number) =>
    z ? (
      <span
        aria-hidden
        className="absolute -top-0.5 -right-0.5 min-w-4 rounded-pill bg-accent px-1 text-center text-[10px] leading-4 font-semibold text-on-accent"
      >
        {z}
      </span>
    ) : null

  if (schmal) {
    const jetzt = ziele.find((z) => z.id === ansicht) ?? ziele[0]
    const offenGesamt = ziele.reduce((s, z) => s + (z.zahl ?? 0), 0)
    return (
      <div ref={kasten} className="relative shrink-0">
        <button
          type="button"
          aria-label={t('nav.ansicht', { name: jetzt.text })}
          title={t('nav.ansicht', { name: jetzt.text })}
          aria-expanded={offen}
          aria-haspopup="menu"
          onClick={() => setOffen(!offen)}
          className="relative flex h-[34px] items-center gap-0.5 rounded-md px-2 text-fg-2 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1 [&_svg]:size-[18px]"
        >
          <jetzt.Symbol aria-hidden />
          <ChevronDown aria-hidden className="!size-3.5 text-fg-4" />
          {zahl(offenGesamt)}
        </button>
        {offen && (
          <div
            role="menu"
            className="absolute top-full left-0 z-50 mt-1 w-[200px] rounded-lg border border-line bg-surface-1 py-1 shadow-[var(--shadow-3)]"
          >
            {ziele.map((z) => (
              <button
                key={z.id}
                type="button"
                role="menuitem"
                aria-current={z.id === ansicht ? 'page' : undefined}
                onClick={() => {
                  setOffen(false)
                  aufAnsicht(z.id)
                }}
                className={
                  'flex w-full items-center gap-2.5 px-3 py-2 text-left text-[14px] transition-colors duration-[var(--dur-fast)] ' +
                  (z.id === ansicht
                    ? 'bg-accent-soft font-medium text-accent-text'
                    : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')
                }
              >
                <z.Symbol aria-hidden className="size-4 shrink-0" />
                <span className="flex-1">{z.text}</span>
                {Boolean(z.zahl) && (
                  <span className="rounded-pill bg-accent px-1.5 text-[10px] leading-4 font-semibold text-on-accent">
                    {z.zahl}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <nav aria-label={t('nav.ansichten')} className="flex shrink-0 items-center gap-0.5">
      {ziele.map((z) => {
        const an = z.id === ansicht
        return (
          <button
            key={z.id}
            type="button"
            title={z.text}
            aria-label={z.text}
            aria-current={an ? 'page' : undefined}
            onClick={() => aufAnsicht(z.id)}
            className={
              'relative flex size-[34px] items-center justify-center rounded-md ' +
              'transition-colors duration-[var(--dur-fast)] [&_svg]:size-[18px] ' +
              (an ? 'bg-accent-soft text-accent-text' : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
            }
          >
            <z.Symbol aria-hidden />
            {zahl(z.zahl)}
          </button>
        )
      })}
    </nav>
  )
}
