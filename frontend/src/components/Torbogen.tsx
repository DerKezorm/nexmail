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
import { AuthCard } from '../vendor/nexui'
import { Logo } from './Logo'
import { Beschriftung } from '../ds/beschriftung'
import { EINGEBAUT, eigeneSprachen, spracheSetzen } from '../i18n'
import { useLanguageOptions } from '../vendor/nexsprachen/languages'

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
  // Eingebaute und die Sprachen des Betreibers (Modul sprachen).
  const sprachen = useLanguageOptions(eigeneSprachen, EINGEBAUT)

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
          {sprachen.map((s) => (
            <button
              key={s.code}
              type="button"
              title={s.name}
              onClick={() => void spracheSetzen(s.code)}
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

      {/* Die Karte aus dem gemeinsamen Bausatz (`AuthCard`), Lage und Maße wie in nexnotes. */}
      <div className="flex flex-1 items-start justify-center px-4 pt-[6vh] pb-10">
        <AuthCard
          wide={breit}
          title={titel}
          subtitle={
            marke || untertitel ? (
              <>
                {marke && <span className="block text-xs font-semibold tracking-[0.06em] uppercase">{marke}</span>}
                {untertitel}
              </>
            ) : undefined
          }
        >
          {/* Anmelden, Einrichten, Einladung, Passwort: Beschriftungen normal geschrieben wie in nexnotes. */}
          <Beschriftung.Provider value="normal">{children}</Beschriftung.Provider>
        </AuthCard>
      </div>
    </div>
  )
}
