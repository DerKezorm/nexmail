/* Die schmale Leiste ganz links.
 *
 * Wenige Ziele: Mail, Kalender, Aufgaben, Kontakte. Regeln und Signaturen wohnen in den
 * Einstellungen — sie sind Einrichtung, keine taegliche Ansicht, und ein
 * Symbol, das man zweimal im Jahr drueckt, verbraucht hier nur
 * Aufmerksamkeit.
 *
 * ⚠️ **An „Aufgaben" haengt eine Zahl.** Eine Aufgabenliste, die man erst
 * sieht, wenn man hinklickt, wird vergessen — und dann haette man sie sich
 * sparen koennen. Die Zahl steht nur da, wenn wirklich etwas offen ist.
 *
 * Unten die zwei Schalter, die keine Ansicht sind: Modus und Sprache.
 *
 * Die Marke steht hier NICHT mehr: Seit das Kopfbanner ueber allem laeuft,
 * saessen Zeichen und Wortmarke sonst zweimal innerhalb von sechzig Pixeln.
 */
import { useTranslation } from 'react-i18next'
import { CalendarDays, ListChecks, Mail, Settings, Users } from 'lucide-react'

export type Ansicht = 'mail' | 'kalender' | 'aufgaben' | 'kontakte' | 'einstellungen'

interface Props {
  ansicht: Ansicht
  /** Wie viele Aufgaben offen sind. 0 blendet die Zahl aus. */
  offeneAufgaben?: number
  aufAnsicht: (a: Ansicht) => void
}

export function NavRail({ ansicht, aufAnsicht, offeneAufgaben = 0 }: Props) {
  const { t } = useTranslation()

  const ziele: ReadonlyArray<{ id: Ansicht; symbol: React.ReactNode; text: string; zahl?: number }> = [
    { id: 'mail', symbol: <Mail />, text: t('nav.mail') },
    { id: 'kalender', symbol: <CalendarDays />, text: t('nav.kalender') },
    { id: 'aufgaben', symbol: <ListChecks />, text: t('nav.aufgaben'), zahl: offeneAufgaben },
    { id: 'kontakte', symbol: <Users />, text: t('nav.kontakte') },
  ]

  return (
    <nav className="flex w-[var(--rail-w)] shrink-0 flex-col items-center gap-1 border-r border-line-subtle bg-surface-1 py-3">
      <div className="flex flex-col gap-1">
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
                'relative flex size-10 items-center justify-center rounded-md ' +
                'transition-colors duration-[var(--dur-fast)] [&_svg]:size-5 ' +
                (an ? 'bg-accent-soft text-accent-text' : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
              }
            >
              {an && (
                <span
                  aria-hidden
                  className="absolute top-1/2 -left-3 h-5 w-0.5 -translate-y-1/2 rounded-pill bg-accent"
                />
              )}
              {z.symbol}
              {Boolean(z.zahl) && (
                <span
                  aria-hidden
                  className="absolute top-0.5 right-0.5 min-w-4 rounded-pill bg-accent px-1 text-center text-[10px] leading-4 font-semibold text-on-accent"
                >
                  {z.zahl}
                </span>
              )}
            </button>
          )
        })}
      </div>


      {/* ⚠️ **Unten in der Ecke, getrennt von den Ansichten, und für alle.**
          Bis 0.30 standen hier „Über" und das Zahnrad der Verwaltung, nur für
          den Betreiber, und KI hatte einen eigenen Punkt oben. Seit dem
          22.11.2026 liegt das alles in den Einstellungen, gegliedert wie in
          nexnotes (Mein Konto, Mail, Server, Über); das Zahnrad führt dorthin,
          wie „Name · Einstellungen" unten in der Seitenleiste von nexnotes. */}
      <div className="mt-auto flex flex-col gap-1">
        <button
          type="button"
          title={t('nav.einstellungen')}
          aria-label={t('nav.einstellungen')}
          aria-current={ansicht === 'einstellungen' ? 'page' : undefined}
          onClick={() => aufAnsicht('einstellungen')}
          className={
            'relative flex size-10 items-center justify-center rounded-md ' +
            'transition-colors duration-[var(--dur-fast)] [&_svg]:size-5 ' +
            (ansicht === 'einstellungen'
              ? 'bg-accent-soft text-accent-text'
              : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
          }
        >
          {ansicht === 'einstellungen' && (
            <span
              aria-hidden
              className="absolute top-1/2 -left-3 h-5 w-0.5 -translate-y-1/2 rounded-pill bg-accent"
            />
          )}
          <Settings />
        </button>
      </div>
    </nav>
  )
}
