/* Der Rahmen für alles vor der Anmeldung.
 *
 * Eine mittige Karte auf dem Seitengrund, darüber das Zeichen. Bewusst
 * schmal: Hier steht nie mehr als ein Formular, und ein Formular über die
 * ganze Bildschirmbreite liest sich schlecht.
 *
 * Der Modus- und der Sprachschalter sitzen oben rechts — sie gehören zu den
 * wenigen Dingen, die man **vor** der Anmeldung braucht: Wer die Oberfläche
 * nicht lesen kann, kommt sonst nicht einmal bis zum Kennwortfeld.
 */
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Moon, Sun } from 'lucide-react'
import { Logo } from './Logo'
import { SPRACHEN, spracheSetzen } from '../i18n'
import type { Sprachcode } from '../i18n'

interface Props {
  titel: string
  untertitel?: ReactNode
  /** Kleine Zeile über dem Titel, z. B. „Schritt 1 von 2". */
  marke?: string
  breit?: boolean
  children: ReactNode
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
}

export function Torbogen({
  titel,
  untertitel,
  marke,
  breit = false,
  children,
  modus,
  aufModus,
}: Props) {
  const { t, i18n } = useTranslation()

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-canvas">
      <div className="flex shrink-0 items-center justify-between p-4">
        <Logo withWordmark />
        <div className="flex items-center gap-1">
          <button
            type="button"
            title={modus === 'dark' ? t('nav.hell') : t('nav.dunkel')}
            aria-label={modus === 'dark' ? t('nav.hell') : t('nav.dunkel')}
            onClick={() => aufModus(modus === 'dark' ? 'light' : 'dark')}
            className="flex size-9 items-center justify-center rounded-md text-fg-3 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1 [&_svg]:size-[18px]"
          >
            {modus === 'dark' ? <Sun /> : <Moon />}
          </button>
          {SPRACHEN.map((s) => (
            <button
              key={s.code}
              type="button"
              title={s.name}
              onClick={() => void spracheSetzen(s.code as Sprachcode)}
              className={
                'rounded-sm px-1.5 py-1 text-[11px] font-semibold uppercase transition-colors duration-[var(--dur-fast)] ' +
                (i18n.language === s.code
                  ? 'text-accent-text'
                  : 'text-fg-4 hover:bg-surface-3 hover:text-fg-2')
              }
            >
              {s.code}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-1 items-start justify-center px-4 pt-6 pb-16 sm:items-center sm:pt-4">
        <main
          className={
            'w-full rounded-xl border border-line bg-surface-1 p-6 shadow-[var(--shadow-2)] sm:p-8 ' +
            (breit ? 'max-w-[620px]' : 'max-w-[420px]')
          }
        >
          {marke && (
            <p className="mb-2 text-[11px] font-semibold tracking-[0.06em] text-fg-4 uppercase">
              {marke}
            </p>
          )}
          {/* Ohne Untertitel traegt die Ueberschrift den Abstand selbst -
              sonst klebt die erste Feldbeschriftung darunter. */}
          <h1
            className={
              'font-display text-[24px] leading-snug font-medium text-fg-1 ' +
              (untertitel ? 'mb-2' : 'mb-6')
            }
          >
            {titel}
          </h1>
          {untertitel && <div className="mb-6 text-[13px] text-fg-3">{untertitel}</div>}
          {children}
        </main>
      </div>
    </div>
  )
}
