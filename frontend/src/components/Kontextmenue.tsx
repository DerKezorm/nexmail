/* Das Kontextmenue.
 *
 * Rechtsklick wie in Outlook. Drei Dinge, die man dabei leicht falsch macht
 * und die hier absichtlich anders sind:
 *
 * 1. **Es bleibt im Bild — samt seiner Untermenues.** Ein Menue, das am
 *    unteren Rand aufklappt, waere zur Haelfte abgeschnitten; es kippt
 *    deshalb nach oben bzw. nach links.
 *
 *    ⚠️ **Das galt bis zum 02.09.2026 nur fuer die oberste Ebene.** Die
 *    Untermenues von „Schlagwort" und „Wiedervorlage" standen fest auf
 *    `left-full` — und ein Rechtsklick am rechten Rand schob sie **neben den
 *    Bildschirm**. Gemeldet aus dem Betrieb: „das ist NEBEN meinem Monitor".
 *    Sichtbar wird das nur, wenn das Menue selbst schon gekippt ist, also
 *    genau dort, wo man es beim Bauen nicht ausprobiert.
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
  /** Gesetzt heisst: Dieser Eintrag ist ein Umschalter (menuitemcheckbox)
   *  und traegt bei `true` ein Haekchen — z. B. ein gesetztes Schlagwort.
   *  ⚠️ Nicht nur das Haekchen zeichnen: `aria-checked` muss mit, sonst ist
   *  der Zustand fuer Vorleseprogramme unsichtbar. */
  aktiv?: boolean
  tun?: () => void
}

interface Props {
  x: number
  y: number
  eintraege: MenueEintrag[]
  aufSchliessen: () => void
}

const BREITE = 232
/** Abstand zum Fensterrand, den Menü und Untermenü immer halten. */
const RAND = 8

/** Wo das Menü steht (links oben), damit es ganz im Bild ist: am rechten Rand nach links gekippt, am unteren nach oben,
 *  nie über den oberen oder linken Rand hinaus. Die Höhe ist höchstens die des Fensters weniger 2 × 8 px (`max-height`),
 *  ein längeres Menü scrollt in sich. */
export function hauptPosition(x: number, y: number, breite: number, hoehe: number, fensterB: number, fensterH: number) {
  const h = Math.min(hoehe, fensterH - 2 * RAND)
  return {
    x: x + breite > fensterB - RAND ? Math.max(RAND, x - breite) : x,
    y: y + h > fensterH - RAND ? Math.max(RAND, Math.min(y - h, fensterH - RAND - h)) : y,
  }
}

/** Wo ein Untermenü steht (Fensterkoordinaten, es ist `fixed`, damit das scrollende Hauptmenü es nicht abschneidet):
 *  rechts neben seiner Zeile, sonst links daneben, und wo auf keiner Seite Platz ist, an den Rand geklemmt, sodass es
 *  ganz sichtbar ist. Nach unten so weit hoch, dass sein Fuß im Bild bleibt, nie über den oberen Rand. */
export function unterPosition(
  anker: { left: number; right: number; top: number },
  breite: number,
  hoehe: number,
  fensterB: number,
  fensterH: number,
) {
  let left: number
  if (anker.right + breite <= fensterB - RAND) left = anker.right
  else if (anker.left - breite >= RAND) left = anker.left - breite
  else left = Math.max(RAND, Math.min(anker.right, fensterB - RAND - breite))
  const ueberstand = anker.top + hoehe - (fensterH - RAND)
  const top = ueberstand > 0 ? Math.max(RAND, anker.top - ueberstand) : anker.top
  return { left, top, links: left < anker.left }
}

export function Kontextmenue({ x, y, eintraege, aufSchliessen }: Props) {
  const kasten = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })
  const [offenesUnter, setOffenesUnter] = useState<string | null>(null)

  /** Alle bedienbaren Eintraege der obersten Ebene, in Anzeigereihenfolge. */
  function bedienbare(): HTMLButtonElement[] {
    const el = kasten.current
    if (!el) return []
    // Auch die Umschalter (menuitemcheckbox) gehoeren zur Pfeilnavigation.
    return [
      ...el.querySelectorAll<HTMLButtonElement>(
        ':scope > div > [role="menuitem"], :scope > div > [role="menuitemcheckbox"]',
      ),
    ].filter((b) => !b.disabled)
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
    setPos(hauptPosition(x, y, width, height, window.innerWidth, window.innerHeight))
    // Der Fokus wandert ins Menue. Bliebe er auf der Nachrichtenzeile,
    // wuerden die Pfeiltasten die Liste bewegen statt das Menue.
    el.querySelector<HTMLButtonElement>(
      '[role="menuitem"]:not(:disabled), [role="menuitemcheckbox"]:not(:disabled)',
    )?.focus()
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
    /* ⚠️ **Scrollen erst ab dem nächsten Bild.** Ein Scroll-Ereignis wird
     * nicht beim Scrollen zugestellt, sondern im nächsten Bild. Der
     * Rechtsklick rendert Auswahl und Menü aber in einem Block von gut 100 ms;
     * ein Scrollen von kurz davor kam damit erst an, als das Menü schon hing,
     * und schloss es im selben Augenblick. Wartende Scroll-Ereignisse gehen
     * im Bildzyklus vor den `requestAnimationFrame`-Rückrufen hinaus, also
     * hört der Wächter erst von dort an zu.
     *
     * Gefunden am 19.09.2026, weil „Ein Untermenü bleibt im Bild, auch am
     * unteren Rand" in jedem dritten Lauf rot war: Playwright scrollt die
     * Zeile vor dem Klick ins Bild, und genau dieses Scrollen kam zu spät. */
    const bild = requestAnimationFrame(() => document.addEventListener('scroll', zu, true))
    return () => {
      cancelAnimationFrame(bild)
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
      /* ⚠️ **Nie höher als das Fenster** (gemessen 27.11.2026: 25 Einträge bei 800×600 liefen 118 px unten hinaus).
         Ein längeres Menü scrollt in sich; ein offenes Untermenü schließt dabei, weil es `fixed` an seiner Zeile hängt. */
      style={{ left: pos.x, top: pos.y, width: BREITE, maxHeight: 'calc(100dvh - 16px)' }}
      onScroll={() => setOffenesUnter(null)}
      // Der eigene pointerdown darf nicht bis zum Schliesser durchlaufen.
      onPointerDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={beiPfeil}
      className="fixed z-[60] overflow-y-auto overscroll-contain rounded-lg border border-line bg-surface-1 py-1 shadow-[var(--shadow-3)]"
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

/** Das Haekchen eines gesetzten Umschalters. Nur Zierde — den Zustand traegt
 *  `aria-checked` am Knopf. */
function Haken() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="!size-3.5 shrink-0 text-accent-text"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m5 13 4 4L19 7" />
    </svg>
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
  const reihe = useRef<HTMLDivElement>(null)
  const unterkasten = useRef<HTMLDivElement>(null)
  /** Auf welcher Seite das Untermenue aufgeht, und wie weit es hochruecken
   *  muss. ⚠️ Gemessen wird in `useLayoutEffect` — das laeuft **vor** dem
   *  Zeichnen, das Untermenue blitzt also nicht erst an der falschen Stelle
   *  auf. */
  const [lage, setLage] = useState<{ links: boolean; left: number; top: number }>({ links: false, left: 0, top: 0 })

  useLayoutEffect(() => {
    if (!unterOffen) return
    const anker = reihe.current?.getBoundingClientRect()
    const eigen = unterkasten.current?.getBoundingClientRect()
    if (!anker) return
    // Rechts kein Platz? Dann links neben das Menue — nicht neben den Monitor; links auch nicht: an den Rand geklemmt.
    // Nach unten so weit hoch, dass der Fuss noch im Bild ist.
    setLage(unterPosition(anker, BREITE, eigen?.height ?? 0, window.innerWidth, window.innerHeight))
  }, [unterOffen])

  return (
    <>
      {eintrag.trennerDavor && <div aria-hidden className="my-1 h-px bg-line-subtle" />}
      <div
        ref={reihe}
        className="relative"
        onMouseEnter={() => aufUnter(hatUnter)}
        onMouseLeave={() => aufUnter(false)}
      >
        <button
          type="button"
          role={eintrag.aktiv === undefined ? 'menuitem' : 'menuitemcheckbox'}
          aria-checked={eintrag.aktiv === undefined ? undefined : eintrag.aktiv}
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
          {eintrag.aktiv && <Haken />}
          {hatUnter && (
            <span className="shrink-0 text-fg-4">{unterOffen && lage.links ? '‹' : '›'}</span>
          )}
        </button>

        {hatUnter && unterOffen && (
          <div
            ref={unterkasten}
            role="menu"
            style={{ width: BREITE, left: lage.left, top: lage.top }}
            data-seite={lage.links ? 'links' : 'rechts'}
            className={
              'fixed z-[61] max-h-[320px] overflow-y-auto rounded-lg border border-line ' +
              'bg-surface-1 py-1 shadow-[var(--shadow-3)]'
            }
          >
            {/* ⚠️ Dieselben Eigenschaften wie auf der obersten Ebene:
                `deaktiviert` und `trennerDavor` gelten auch hier. Ein
                Untermenue, das sie stumm verschluckt, laesst einen bewusst
                gesperrten Eintrag („Heute Abend" nach 18 Uhr) klickbar. */}
            {eintrag.unter!.map((u) => (
              <div key={u.id}>
                {u.trennerDavor && <div aria-hidden className="my-1 h-px bg-line-subtle" />}
                <button
                  type="button"
                  role={u.aktiv === undefined ? 'menuitem' : 'menuitemcheckbox'}
                  aria-checked={u.aktiv === undefined ? undefined : u.aktiv}
                  disabled={u.deaktiviert}
                  onClick={() => {
                    u.tun?.()
                    aufSchliessen()
                  }}
                  className={
                    'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] ' +
                    'transition-colors duration-[var(--dur-fast)] [&>svg]:size-4 [&>svg]:shrink-0 ' +
                    'disabled:cursor-not-allowed disabled:opacity-40 ' +
                    (u.gefaehrlich
                      ? 'text-danger hover:bg-danger-soft'
                      : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')
                  }
                >
                  {u.symbol}
                  <span className="min-w-0 flex-1 truncate">{u.text}</span>
                  {u.aktiv && <Haken />}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
