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
import { ChevronDown, LogOut, Settings, ShieldCheck, Sparkles } from 'lucide-react'
import { Logo } from './Logo'
import { Profilbild } from './Profilbild'
import type { Ich } from '../api/client'

interface Props {
  ich: Ich | null
  aufAbmelden: () => void
  /** Solange kein Postfach angebunden ist, sagt das Banner es. Danach
   *  verschwindet der Hinweis - ein Abzeichen, das immer da steht, wird nicht
   *  mehr gelesen. */
  ohnePostfach: boolean
  /** Zu den eigenen Einstellungen — sie gehören zum Profil, nicht zur App. */
  aufEinstellungen: () => void
  /** „Was ist neu“ zur laufenden Version noch einmal öffnen. Fehlt, wenn es
   *  dazu keinen Text gibt: Ein Menüpunkt, der ins Leere führt, ist schlimmer
   *  als keiner. */
  aufWasNeu?: () => void
}

export function Kopfbanner({
  ich,
  aufAbmelden,
  ohnePostfach,
  aufEinstellungen,
  aufWasNeu,
}: Props) {
  const { t } = useTranslation()
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

      {/* Hell/Dunkel und Sprache standen hier bis zum 22.11.2026. Seitdem
          stehen sie in den Einstellungen (Darstellung, Profil), wie in nexnotes;
          zweimal dieselbe Einstellung wäre eine Stelle zu viel. */}

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
            <Profilbild id={ich.id} name={ich.anzeigename} stand={ich.profilbild} groesse={28} />
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
                <ShieldCheck
                  className={`size-3.5 shrink-0 ${ich.zwei_faktor_aktiv ? 'text-success' : 'text-fg-4'}`}
                />
                <span>
                  {ich.zwei_faktor_aktiv
                    ? `${t('nav.faktor_an')} · ${t('nav.codes', { count: ich.offene_codes })}`
                    : t('nav.faktor_aus')}
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

              {/* ⚠️ **Hier, nicht nur auf der Über-Seite.** Die sieht nur
                  der Betreiber; den Banner nach dem Update sehen alle. */}
              {aufWasNeu && (
                <button
                  type="button"
                  onClick={() => {
                    setOffen(false)
                    aufWasNeu()
                  }}
                  className="flex w-full items-center gap-2.5 border-t border-line-subtle px-3 py-2 text-left text-[13px] text-fg-2 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1"
                >
                  <Sparkles className="size-4 shrink-0" />
                  {t('nav.wasneu')}
                </button>
              )}

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
