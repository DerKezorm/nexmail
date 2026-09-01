/* Das Banner ganz oben — wie in Nexview.
 *
 * Es läuft über die volle Breite, also auch über die NavRail hinweg: Die
 * Marke gehört der ganzen Anwendung und nicht einer Spalte darin.
 *
 * Rechts steht, wer angemeldet ist. Das ist bei einem Mail-Client keine
 * Zierde: Wer mehrere Postfächer und später mehrere Benutzer hat, muss auf
 * einen Blick sehen, in wessen Konto er gerade schreibt.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, LogOut, Moon, Settings, ShieldCheck, Sun } from 'lucide-react'
import { Logo } from './Logo'
import type { Ich } from '../api/client'
import { SPRACHEN, spracheSetzen } from '../i18n'
import type { Sprachcode } from '../i18n'

interface Props {
  ich: Ich | null
  aufAbmelden: () => void
  /** Solange kein Postfach angebunden ist, sagt das Banner es. Danach
   *  verschwindet der Hinweis - ein Abzeichen, das immer da steht, wird nicht
   *  mehr gelesen. */
  ohnePostfach: boolean
  /** Zu den eigenen Einstellungen — sie gehören zum Profil, nicht zur App. */
  aufEinstellungen: () => void
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
}

export function Kopfbanner({
  ich,
  aufAbmelden,
  ohnePostfach,
  aufEinstellungen,
  modus,
  aufModus,
}: Props) {
  const { t, i18n } = useTranslation()
  const [offen, setOffen] = useState(false)
  const kasten = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!offen) return
    function zu(e: MouseEvent) {
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

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line-subtle bg-surface-1 px-3">
      <Logo withWordmark />

      <span className="flex-1" />

      {ohnePostfach && (
        <span className="hidden truncate rounded-pill bg-warning-soft px-2.5 py-1 text-[11px] font-medium text-warning sm:inline">
          {t('konto.kein_postfach')}
        </span>
      )}

      {/* ⚠️ **Hell/Dunkel und Sprache gehören nach oben rechts, nicht in die
          NavRail.** Dort standen sie unten links am Rand — an einer Stelle,
          an der man sie erst sucht, wenn man weiß, dass es sie gibt. Oben
          rechts ist die Ecke, in der jede Anwendung ihre Einstellungen hat,
          und Nexview macht es genauso. */}
      <div
        role="group"
        aria-label={t('nav.modus')}
        className="flex items-center gap-0.5 rounded-pill border border-line bg-surface-2 p-0.5"
      >
        {(['dark', 'light'] as const).map((m) => (
          <button
            key={m}
            type="button"
            title={m === 'dark' ? t('nav.dunkel') : t('nav.hell')}
            aria-label={m === 'dark' ? t('nav.dunkel') : t('nav.hell')}
            aria-pressed={modus === m}
            onClick={() => aufModus(m)}
            className={
              'flex size-7 items-center justify-center rounded-pill transition-colors ' +
              'duration-[var(--dur-fast)] [&_svg]:size-4 ' +
              (modus === m
                ? 'bg-accent text-on-accent'
                : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
            }
          >
            {m === 'dark' ? <Moon /> : <Sun />}
          </button>
        ))}
      </div>

      <div
        role="group"
        aria-label={t('nav.sprache')}
        className="flex items-center gap-0.5 rounded-pill border border-line bg-surface-2 p-0.5"
      >
        {SPRACHEN.map((sp) => (
          <button
            key={sp.code}
            type="button"
            title={sp.name}
            aria-pressed={i18n.language === sp.code}
            onClick={() => spracheSetzen(sp.code as Sprachcode)}
            className={
              'rounded-pill px-2.5 py-1 text-[11px] font-semibold uppercase transition-colors ' +
              'duration-[var(--dur-fast)] ' +
              (i18n.language === sp.code
                ? 'bg-accent text-on-accent'
                : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
            }
          >
            {sp.code}
          </button>
        ))}
      </div>

      {ich && (
        <div ref={kasten} className="relative">
          <button
            type="button"
            onClick={() => setOffen(!offen)}
            aria-expanded={offen}
            /* ⚠️ **Der Name steht hier, nicht nur daneben.** Schmal blendet die
               Beschriftung aus und die beiden Symbole sind `aria-hidden` — der
               Knopf hätte dann gar keinen Namen mehr. Eine Vorlesehilfe sagt
               „Schaltfläche", sonst nichts, und über die Tastatur findet ihn
               niemand. Am 01.09.2026 an einem roten Test aufgefallen. */
            aria-label={t('nav.benutzermenue', { name: ich.anzeigename })}
            className="flex items-center gap-2 rounded-md px-2 py-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3"
          >
            <span
              aria-hidden
              className="flex size-7 items-center justify-center rounded-pill bg-accent-soft text-[11px] font-semibold text-accent-text"
            >
              {ich.anzeigename.slice(0, 2).toUpperCase()}
            </span>
            <span className="hidden text-[13px] text-fg-2 sm:inline">{ich.anzeigename}</span>
            <ChevronDown
              aria-hidden
              className={
                'size-3.5 shrink-0 text-fg-4 transition-transform duration-[var(--dur-fast)] ' +
                (offen ? 'rotate-180' : '')
              }
            />
          </button>

          {offen && (
            <div className="absolute top-full right-0 z-50 mt-1 w-[248px] rounded-lg border border-line bg-surface-1 py-1 shadow-[var(--shadow-3)]">
              <div className="border-b border-line-subtle px-3 py-2">
                <p className="mb-0 truncate text-[13px] font-medium text-fg-1">
                  {ich.anzeigename}
                </p>
                <p className="mb-0 truncate font-mono text-[11px] text-fg-4">{ich.benutzername}</p>
              </div>

              {/* Wie viele Wiederherstellungscodes noch übrig sind. Sichtbar,
                  weil man es sonst erst erfährt, wenn keiner mehr da ist. */}
              <div className="flex items-center gap-2 px-3 py-2 text-[12px] text-fg-3">
                <ShieldCheck className="size-3.5 shrink-0 text-success" />
                <span>
                  {ich.zwei_faktor_aktiv ? '2FA aktiv' : '2FA fehlt'} · {ich.offene_codes}{' '}
                  {ich.offene_codes === 1 ? 'Code' : 'Codes'}
                </span>
              </div>

              {/* ⚠️ **Die eigenen Einstellungen gehören hierher.** Postfächer,
                  Regeln, Signaturen, zweiter Faktor — das ist alles Profil.
                  In der NavRail standen sie neben „Mail" und „Kontakte", also
                  neben Ansichten, und wirkten dadurch wie eine vierte. */}
              <button
                type="button"
                onClick={() => {
                  setOffen(false)
                  aufEinstellungen()
                }}
                className="flex w-full items-center gap-2.5 border-t border-line-subtle px-3 py-2 text-left text-[13px] text-fg-2 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1"
              >
                <Settings className="size-4 shrink-0" />
                {t('nav.einstellungen')}
              </button>

              <button
                type="button"
                onClick={aufAbmelden}
                className="flex w-full items-center gap-2.5 border-t border-line-subtle px-3 py-2 text-left text-[13px] text-fg-2 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1"
              >
                <LogOut className="size-4 shrink-0" />
                {t('anmeldung.abmelden')}
              </button>
            </div>
          )}
        </div>
      )}
    </header>
  )
}
