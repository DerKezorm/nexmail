/* Die Formatierleiste.
 *
 * Zuschnitt nach der Entscheidung "wer Outlook bedienen kann, soll sich hier
 * zu Hause fuehlen": Schriftart, Groesse, fett/kursiv/unterstrichen,
 * Textfarbe, Hervorheben, Aufzaehlung, Nummerierung, Einzug, Ausrichtung,
 * Link, Zitat, Bild, Formatierung entfernen.
 *
 * **Tabellen fehlen mit Absicht** - sie stehen in SPAETER.md. In Mail-HTML
 * gehen sie nur mit veralteten Attributen zuverlaessig durch alle Clients,
 * und privat braucht sie kaum jemand.
 *
 * In Stufe A ist die Leiste sichtbar, aber ohne Wirkung: Die Knoepfe
 * bekommen ihre Funktion in Stufe 4 von Tiptap. Sie steht trotzdem schon
 * hier, weil sie die Hoehe und das Gewicht des Fensters bestimmt - und
 * genau das soll beurteilt werden koennen.
 */
import { useTranslation } from 'react-i18next'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  Highlighter,
  Image,
  IndentDecrease,
  IndentIncrease,
  Italic,
  Link2,
  List,
  ListOrdered,
  Quote,
  RemoveFormatting,
  Underline,
} from 'lucide-react'
import type { ReactNode } from 'react'

const SCHRIFTARTEN = ['Arial', 'Calibri', 'Georgia', 'Helvetica', 'Times New Roman', 'Verdana']
const GROESSEN = ['9', '10', '11', '12', '14', '18', '24', '36']

export function Formatierleiste() {
  const { t } = useTranslation()

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-y border-line-subtle bg-surface-2 px-2 py-1">
      <Auswahl aria-label={t('format.schriftart')} werte={SCHRIFTARTEN} breite="w-[112px]" />
      <Auswahl aria-label={t('format.groesse')} werte={GROESSEN} vorgabe="11" breite="w-[56px]" />

      <Trenner />
      <Knopf symbol={<Bold />} text={t('format.fett')} />
      <Knopf symbol={<Italic />} text={t('format.kursiv')} />
      <Knopf symbol={<Underline />} text={t('format.unterstrichen')} />
      <Knopf symbol={<Baseline />} text={t('format.textfarbe')} />
      <Knopf symbol={<Highlighter />} text={t('format.markieren')} />

      <Trenner />
      <Knopf symbol={<List />} text={t('format.aufzaehlung')} />
      <Knopf symbol={<ListOrdered />} text={t('format.nummerierung')} />
      <Knopf symbol={<IndentDecrease />} text={t('format.einzug_raus')} />
      <Knopf symbol={<IndentIncrease />} text={t('format.einzug_rein')} />

      <Trenner />
      <Knopf symbol={<AlignLeft />} text={t('format.links')} />
      <Knopf symbol={<AlignCenter />} text={t('format.mitte')} />
      <Knopf symbol={<AlignRight />} text={t('format.rechts')} />

      <Trenner />
      <Knopf symbol={<Link2 />} text={t('format.link')} />
      <Knopf symbol={<Quote />} text={t('format.zitat')} />
      <Knopf symbol={<Image />} text={t('format.bild')} />
      <Knopf symbol={<RemoveFormatting />} text={t('format.entfernen')} />
    </div>
  )
}

function Trenner() {
  return <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-line" />
}

function Knopf({ symbol, text }: { symbol: ReactNode; text: string }) {
  return (
    <button
      type="button"
      title={text}
      aria-label={text}
      className="flex size-7 shrink-0 items-center justify-center rounded-sm text-fg-3 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1 [&_svg]:size-4"
    >
      {symbol}
    </button>
  )
}

function Auswahl({
  werte,
  vorgabe,
  breite,
  ...rest
}: {
  werte: string[]
  vorgabe?: string
  breite: string
} & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      defaultValue={vorgabe ?? werte[0]}
      className={`h-7 shrink-0 cursor-pointer rounded-sm border border-line bg-surface-1 px-1.5 text-[12px] text-fg-2 outline-none hover:border-line-strong ${breite}`}
      {...rest}
    >
      {werte.map((w) => (
        <option key={w} value={w} className="bg-surface-1 text-fg-1">
          {w}
        </option>
      ))}
    </select>
  )
}
