/* Ein Blatt von unten: die Einträge eines Menüs, mit dem Daumen bedienbar.
 *
 * Am Rechner steht dasselbe im Kontextmenü neben dem Mauszeiger. Am Telefon
 * gibt es keinen Zeiger, und ein Menü an der Berührung wäre halb unter dem
 * Finger; ein Blatt vom unteren Rand ist der Ort, an dem jedes
 * Telefon-Programm es zeigt. Die Einträge sind **dieselben `MenueEintrag`**
 * wie im Kontextmenü — eine Quelle, zwei Formen, sonst laufen sie
 * auseinander (dieselbe Regel wie beim Untermenü „Wiedervorlage").
 *
 * ⚠️ **Ein Untermenü ist eine zweite Seite, kein Aufklappen.** „Verschieben"
 * trägt die Ordnerliste, darunter je Postfach noch eine; aufgeklappt würde
 * das Blatt länger als der Bildschirm. Zurück geht mit dem Pfeil oben.
 *
 * ⚠️ **Ein Fenster hat genau einen sichtbaren Ausgang**: „Abbrechen" unten.
 * Der Klick daneben und Escape schließen es zusätzlich, das ist dasselbe
 * Verhalten wie beim Kontextmenü. */
import { ArrowLeft, Check, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MenueEintrag } from './Kontextmenue'

interface Props {
  titel: string
  eintraege: MenueEintrag[]
  aufSchliessen: () => void
  /** Läuft nach einer ausgeführten Handlung — nicht nach Abbrechen. */
  nachHandlung?: () => void
}

export function Aktionsblatt({ titel, eintraege, aufSchliessen, nachHandlung }: Props) {
  const { t } = useTranslation()
  /* Der Pfad ins Untermenü: leer heißt oberste Ebene. */
  const [pfad, setPfad] = useState<MenueEintrag[]>([])
  const oben = pfad[pfad.length - 1]
  const aktuell = oben ? (oben.unter ?? []) : eintraege
  const ueberschrift = oben ? oben.text : titel

  useEffect(() => {
    const beiTaste = (e: KeyboardEvent) => {
      if (e.key === 'Escape') aufSchliessen()
    }
    document.addEventListener('keydown', beiTaste)
    return () => document.removeEventListener('keydown', beiTaste)
  }, [aufSchliessen])

  return (
    <div className="fixed inset-0 z-[72]">
      <div className="absolute inset-0 bg-[var(--surface-overlay)]" onClick={aufSchliessen} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ueberschrift}
        className="absolute inset-x-0 bottom-0 flex max-h-[80%] flex-col rounded-t-2xl border-t border-line bg-surface-1 pb-[env(safe-area-inset-bottom)] shadow-[var(--shadow-3)]"
      >
        <div aria-hidden className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-pill bg-line" />
        <div className="flex shrink-0 items-center gap-1 px-2 py-2">
          {oben && (
            <button
              type="button"
              aria-label={t('aktion.zurueck')}
              onClick={() => setPfad((p) => p.slice(0, -1))}
              className="flex size-8 items-center justify-center rounded-md text-fg-2 hover:bg-surface-3"
            >
              <ArrowLeft className="size-5" />
            </button>
          )}
          <h2 className="min-w-0 truncate px-2 text-[12px] font-semibold tracking-[0.04em] text-fg-3 uppercase">
            {ueberschrift}
          </h2>
        </div>

        <ul role="menu" className="min-h-0 flex-1 overflow-y-auto">
          {aktuell.map((e) => (
            <li key={e.id} role="none">
              {e.trennerDavor && <hr className="my-1 border-line-subtle" />}
              <button
                type="button"
                role={e.aktiv !== undefined ? 'menuitemcheckbox' : 'menuitem'}
                aria-checked={e.aktiv !== undefined ? e.aktiv : undefined}
                disabled={e.deaktiviert}
                onClick={() => {
                  if (e.unter) {
                    setPfad((p) => [...p, e])
                    return
                  }
                  e.tun?.()
                  aufSchliessen()
                  nachHandlung?.()
                }}
                className={
                  'flex w-full items-center gap-3 px-4 py-3 text-left text-[15px] ' +
                  'transition-colors duration-[var(--dur-fast)] enabled:active:bg-surface-3 ' +
                  'disabled:text-fg-4 ' +
                  (e.gefaehrlich ? 'text-danger-text' : 'text-fg-1')
                }
              >
                <span className="shrink-0 text-fg-3 [&>svg]:size-5">{e.symbol}</span>
                <span className="min-w-0 flex-1 truncate">{e.text}</span>
                {e.aktiv && <Check aria-hidden className="size-4 shrink-0 text-accent-text" />}
                {e.unter && <ChevronRight aria-hidden className="size-4 shrink-0 text-fg-4" />}
              </button>
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={aufSchliessen}
          className="mx-4 mt-2 mb-3 shrink-0 rounded-lg bg-surface-3 py-2.5 text-[14px] font-medium text-fg-1 hover:bg-surface-2"
        >
          {t('aktion.abbrechen')}
        </button>
      </div>
    </div>
  )
}
