/* Das Kontextmenue.
 *
 * Rechtsklick wie in Outlook. Drei Dinge, die man dabei leicht falsch macht
 * und die hier absichtlich anders sind:
 *
 * 1. **Es bleibt im Bild.** Ein Menue, das am unteren Rand aufklappt, waere
 *    zur Haelfte abgeschnitten - es kippt deshalb nach oben bzw. nach links.
 * 2. **Es schliesst bei allem.** Klick daneben, Escape, Scrollen, ein zweiter
 *    Rechtsklick woanders, Wechsel in ein anderes Fenster.
 * 3. **Es ist mit der Tastatur bedienbar.** Pfeile, Enter, Escape. Die
 *    Kontextmenue-Taste und Umschalt+F10 loesen es ohnehin aus, und wer so
 *    hineinkommt, kommt sonst nicht wieder heraus.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export interface MenueEintrag {
  id: string
  text: string
  symbol?: ReactNode
  /** Trennlinie ueber diesem Eintrag. */
  trennerDavor?: boolean
  /** Zerstoerend — wird rot dargestellt. */
  gefaehrlich?: boolean
  deaktiviert?: boolean
  /** Untermenue, z. B. die Ordnerliste bei "Verschieben". */
  unter?: MenueEintrag[]
  tun?: () => void
}

interface Props {
  x: number
  y: number
  eintraege: MenueEintrag[]
  aufSchliessen: () => void
}

const BREITE = 232

export function Kontextmenue({ x, y, eintraege, aufSchliessen }: Props) {
  const kasten = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })
  const [offenesUnter, setOffenesUnter] = useState<string | null>(null)

  /** Alle bedienbaren Eintraege der obersten Ebene, in Anzeigereihenfolge. */
  function bedienbare(): HTMLButtonElement[] {
    const el = kasten.current
    if (!el) return []
    return [...el.querySelectorAll<HTMLButtonElement>(':scope > div > [role="menuitem"]')].filter(
      (b) => !b.disabled,
    )
  }

  /** Pfeiltasten, Pos1 und Ende. Ohne sie kommt man mit der Tastatur zwar
   *  hinein (Kontextmenue-Taste, Umschalt+F10), aber nur muehsam voran. */
  function beiPfeil(e: React.KeyboardEvent) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
    e.preventDefault()
    const liste = bedienbare()
    if (liste.length === 0) return
    const jetzt = liste.indexOf(document.activeElement as HTMLButtonElement)
    const naechst =
      e.key === 'Home'
        ? 0
        : e.key === 'End'
          ? liste.length - 1
          : e.key === 'ArrowDown'
            ? (jetzt + 1 + liste.length) % liste.length
            : (jetzt - 1 + liste.length) % liste.length
    liste[naechst]?.focus()
  }

  // Erst messen, dann setzen - sonst blitzt das Menue einmal an der falschen
  // Stelle auf.
  useLayoutEffect(() => {
    const el = kasten.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    setPos({
      x: x + width > window.innerWidth - 8 ? Math.max(8, x - width) : x,
      y: y + height > window.innerHeight - 8 ? Math.max(8, y - height) : y,
    })
    // Der Fokus wandert ins Menue. Bliebe er auf der Nachrichtenzeile,
    // wuerden die Pfeiltasten die Liste bewegen statt das Menue.
    el.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
  }, [x, y])

  useEffect(() => {
    /* ⚠️ **Klicks im Menü sind keine Klicks daneben.**
     *
     * Hier stand ein bedingungsloses `aufSchliessen()`. Der Zuhörer hängt in
     * der **Erfassungsphase** am Dokument — er läuft also, bevor der Eintrag
     * seinen eigenen Klick sieht. Ergebnis: Jeder `pointerdown` schloss das
     * Menü, der Eintrag verschwand, und der Klick landete im Nichts. Kein
     * einziger Menüpunkt tat etwas, und keiner meldete einen Fehler.
     *
     * Das `stopPropagation` am Kasten half nicht: React hängt seine Zuhörer
     * an der Wurzel und in der Aufstiegsphase auf — da ist der Zuhörer hier
     * längst gelaufen.
     */
    function zu(e: Event) {
      if (kasten.current?.contains(e.target as Node)) return
      aufSchliessen()
    }
    function beiTaste(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        aufSchliessen()
      }
    }
    // "true" = in der Erfassungsphase: So schliesst das Menue auch dann,
    // wenn der Klick auf einem Element landet, das ihn selbst abfaengt.
    document.addEventListener('pointerdown', zu, true)
    document.addEventListener('keydown', beiTaste, true)
    window.addEventListener('blur', zu)
    window.addEventListener('resize', zu)
    document.addEventListener('scroll', zu, true)
    return () => {
      document.removeEventListener('pointerdown', zu, true)
      document.removeEventListener('keydown', beiTaste, true)
      window.removeEventListener('blur', zu)
      window.removeEventListener('resize', zu)
      document.removeEventListener('scroll', zu, true)
    }
  }, [aufSchliessen])

  return (
    <div
      ref={kasten}
      role="menu"
      style={{ left: pos.x, top: pos.y, width: BREITE }}
      // Der eigene pointerdown darf nicht bis zum Schliesser durchlaufen.
      onPointerDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={beiPfeil}
      className="fixed z-[60] rounded-lg border border-line bg-surface-1 py-1 shadow-[var(--shadow-3)]"
    >
      {eintraege.map((e) => (
        <Zeile
          key={e.id}
          eintrag={e}
          unterOffen={offenesUnter === e.id}
          aufUnter={(offen) => setOffenesUnter(offen ? e.id : null)}
          aufSchliessen={aufSchliessen}
        />
      ))}
    </div>
  )
}

interface ZeileProps {
  eintrag: MenueEintrag
  unterOffen: boolean
  aufUnter: (offen: boolean) => void
  aufSchliessen: () => void
}

function Zeile({ eintrag, unterOffen, aufUnter, aufSchliessen }: ZeileProps) {
  const hatUnter = Boolean(eintrag.unter?.length)

  return (
    <>
      {eintrag.trennerDavor && <div aria-hidden className="my-1 h-px bg-line-subtle" />}
      <div className="relative" onMouseEnter={() => aufUnter(hatUnter)} onMouseLeave={() => aufUnter(false)}>
        <button
          type="button"
          role="menuitem"
          disabled={eintrag.deaktiviert}
          aria-haspopup={hatUnter || undefined}
          aria-expanded={hatUnter ? unterOffen : undefined}
          onClick={() => {
            if (hatUnter) {
              aufUnter(!unterOffen)
              return
            }
            eintrag.tun?.()
            aufSchliessen()
          }}
          className={
            'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] ' +
            'transition-colors duration-[var(--dur-fast)] [&>svg]:size-4 [&>svg]:shrink-0 ' +
            'disabled:cursor-not-allowed disabled:opacity-40 ' +
            (eintrag.gefaehrlich
              ? 'text-danger hover:bg-danger-soft'
              : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')
          }
        >
          {eintrag.symbol}
          <span className="min-w-0 flex-1 truncate">{eintrag.text}</span>
          {hatUnter && <span className="shrink-0 text-fg-4">›</span>}
        </button>

        {hatUnter && unterOffen && (
          <div
            role="menu"
            style={{ width: BREITE }}
            className="absolute top-0 left-full z-[61] max-h-[320px] overflow-y-auto rounded-lg border border-line bg-surface-1 py-1 shadow-[var(--shadow-3)]"
          >
            {eintrag.unter!.map((u) => (
              <button
                key={u.id}
                type="button"
                role="menuitem"
                onClick={() => {
                  u.tun?.()
                  aufSchliessen()
                }}
                className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] text-fg-2 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1 [&>svg]:size-4 [&>svg]:shrink-0"
              >
                {u.symbol}
                <span className="min-w-0 flex-1 truncate">{u.text}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
