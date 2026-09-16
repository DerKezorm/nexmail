/* Die Leiste ueber den drei Inhaltsspalten.
 *
 * Links die eine Hauptaktion, in der Mitte die Suche. Der Bereichsumschalter
 * sitzt **in** der Suche, nicht daneben: Wo gesucht wird, ist Teil der Suche
 * und keine eigene Einstellung, die man vorher trifft und danach vergisst.
 */
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { AppWindow, Maximize2, PanelLeft, PanelRight, PenLine, RefreshCw, Search } from 'lucide-react'
import { Button, IconButton } from '../ds'
import { naechsterLesemodus } from '../lib/lesemodus'
import type { Lesemodus } from '../lib/lesemodus'

const LESEMODUS_SYMBOL: Record<Lesemodus, typeof PanelRight> = {
  rechts: PanelRight,
  ganz: Maximize2,
  fenster: AppWindow,
}

export type Suchbereich = 'ordner' | 'postfach' | 'alle'

interface Props {
  suche: string
  aufSuche: (s: string) => void
  bereich: Suchbereich
  aufBereich: (b: Suchbereich) => void
  aufNeu: () => void
  /** Nur schmal: oeffnet die Ordner-Schublade. */
  aufSchublade?: () => void
  ordnerOffen: boolean
  aufOrdnerOffen: (offen: boolean) => void
  schmal: boolean
  aufAbgleichen: () => void
  gleichtAb: boolean
  /** Wo eine Mail aufgeht. Nur breit; schmal fehlt der Knopf. */
  lesemodus: Lesemodus
  aufLesemodus: (m: Lesemodus) => void
}

export function Kopfleiste({
  suche,
  aufSuche,
  bereich,
  aufBereich,
  aufNeu,
  aufSchublade,
  ordnerOffen,
  aufOrdnerOffen,
  schmal,
  aufAbgleichen,
  gleichtAb,
  lesemodus,
  aufLesemodus,
}: Props) {
  const { t } = useTranslation()
  const feld = useRef<HTMLInputElement>(null)
  const LesemodusSymbol = LESEMODUS_SYMBOL[lesemodus]
  // Wörtlich, nicht zusammengesetzt: Nur so sieht der Schlüssel-Wächter sie.
  const lesemodusName: Record<Lesemodus, string> = {
    rechts: t('lesemodus.rechts'),
    ganz: t('lesemodus.ganz'),
    fenster: t('lesemodus.fenster'),
  }

  // Strg+F gehoert in einem Mail-Client der Suche der App, nicht der des
  // Browsers: Der Browser durchsucht nur, was gerade sichtbar ist - also
  // zwanzig von vierzigtausend Nachrichten.
  useEffect(() => {
    function beiTaste(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        feld.current?.focus()
        feld.current?.select()
      }
    }
    document.addEventListener('keydown', beiTaste)
    return () => document.removeEventListener('keydown', beiTaste)
  }, [])

  return (
    <header className="flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-line-subtle bg-surface-1 px-3">
      {schmal ? (
        <IconButton icon={<PanelLeft />} label={t('ordner.ausklappen')} onClick={aufSchublade} />
      ) : (
        <IconButton
          icon={<PanelLeft />}
          label={ordnerOffen ? t('ordner.einklappen') : t('ordner.ausklappen')}
          active={ordnerOffen}
          onClick={() => aufOrdnerOffen(!ordnerOffen)}
        />
      )}

      {/* ⚠️ **Schmal bleibt nur das Symbol — der Name muss trotzdem dran.**
          Sonst ist der wichtigste Knopf der Anwendung für eine Vorlesehilfe
          eine namenlose Schaltfläche, und wer mit der Maus zögert, bekommt
          nicht einmal einen Hinweis. Am 01.09.2026 von einem eigenen Wächter
          gefunden, nicht von einem Menschen. */}
      <Button
        variant="primary"
        iconLeft={<PenLine className="size-4" />}
        onClick={aufNeu}
        aria-label={t('aktion.neu')}
        title={schmal ? t('aktion.neu') : undefined}
      >
        {schmal ? '' : t('aktion.neu')}
      </Button>

      <div className="fokusrahmen flex h-[var(--control-h-md)] min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-surface-3 px-2.5 transition-[border-color,box-shadow] duration-[var(--dur-fast)] focus-within:border-accent focus-within:shadow-[var(--focus-ring)]">
        <Search className="size-4 shrink-0 text-fg-4" />
        <input
          ref={feld}
          value={suche}
          onChange={(e) => aufSuche(e.target.value)}
          placeholder={t('suche.platzhalter')}
          className="min-w-0 flex-1 bg-transparent text-sm text-fg-1 outline-none placeholder:text-fg-4"
        />
        {!schmal && (
          <select
            value={bereich}
            onChange={(e) => aufBereich(e.target.value as Suchbereich)}
            aria-label={t('suche.platzhalter')}
            className="shrink-0 cursor-pointer rounded-sm bg-transparent text-[12px] text-fg-3 outline-none hover:text-fg-1"
          >
            <option value="ordner" className="bg-surface-1 text-fg-1">
              {t('suche.bereich.ordner')}
            </option>
            <option value="postfach" className="bg-surface-1 text-fg-1">
              {t('suche.bereich.postfach')}
            </option>
            <option value="alle" className="bg-surface-1 text-fg-1">
              {t('suche.bereich.alle')}
            </option>
          </select>
        )}
      </div>

      {/* Ein Knopf, drei Modi, reihum. Symbol und Name sagen, was GERADE
          gilt, und der Name nennt dazu, was ein Klick daraus macht. Ohne den
          zweiten Teil wüsste man vor dem Klick nicht, wohin er führt. */}
      {!schmal && (
        <IconButton
          icon={<LesemodusSymbol />}
          label={t('lesemodus.knopf', {
            jetzt: lesemodusName[lesemodus],
            danach: lesemodusName[naechsterLesemodus(lesemodus)],
          })}
          onClick={() => aufLesemodus(naechsterLesemodus(lesemodus))}
        />
      )}

      <IconButton
        icon={<RefreshCw className={gleichtAb ? 'animate-spin' : undefined} />}
        label={t('aktion.aktualisieren')}
        disabled={gleichtAb}
        onClick={aufAbgleichen}
      />
    </header>
  )
}
