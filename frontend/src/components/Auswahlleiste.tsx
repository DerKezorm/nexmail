/* Die Leiste unter der Liste im Auswahlmodus der schmalen Ansicht.
 *
 * Fünf Knöpfe in Daumennähe: Löschen · Archivieren · Verschieben ·
 * Gelesen/Ungelesen · Mehr. Sie wirken auf die Mehrfachauswahl, über
 * dieselben Wege wie die Tasten Entf und E und das Kontextmenü am Rechner —
 * die Leiste ist nur eine weitere Hand am selben Hebel, kein eigener.
 *
 * ⚠️ **Ohne Auswahl sind die Knöpfe gesperrt, nicht weg.** Wer den Modus
 * gerade eingeschaltet hat, soll sehen, was gleich möglich ist; eine Leiste,
 * die erst mit dem ersten Haken erscheint, sieht aus, als fehle sie.
 *
 * ⚠️ **„Gelesen" oder „Ungelesen" entscheidet `lib/auswahl.gelesenZiel`**
 * an der ganzen Auswahl, nicht an der ersten Zeile. */
import { Archive, FolderInput, Mail, MailOpen, MoreHorizontal, Trash2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
  anzahl: number
  gelesenZiel: 'gelesen' | 'ungelesen'
  aufLoeschen: () => void
  aufArchivieren: () => void
  aufVerschieben: () => void
  aufGelesen: () => void
  aufMehr: () => void
}

export function Auswahlleiste(p: Props) {
  const { t } = useTranslation()
  const gesperrt = p.anzahl === 0

  const knopf = (symbol: ReactNode, text: string, tun: () => void, gefaehrlich = false) => (
    <button
      type="button"
      disabled={gesperrt}
      onClick={tun}
      className={
        'flex flex-col items-center gap-0.5 rounded-md px-1 pt-1.5 pb-1 text-[11px] ' +
        'transition-colors duration-[var(--dur-fast)] ' +
        'disabled:text-fg-4 [&>svg]:size-[22px] ' +
        (gefaehrlich
          ? 'text-danger-text enabled:active:bg-danger-soft'
          : 'text-fg-2 enabled:active:bg-surface-3')
      }
    >
      {symbol}
      <span>{text}</span>
    </button>
  )

  return (
    <nav
      aria-label={t('aktion.auswahl_leiste')}
      className="grid shrink-0 grid-cols-5 border-t border-line bg-surface-1 px-1 pt-1 pb-[calc(0.25rem+env(safe-area-inset-bottom))]"
    >
      {knopf(<Trash2 />, t('aktion.loeschen'), p.aufLoeschen, true)}
      {knopf(<Archive />, t('aktion.archivieren'), p.aufArchivieren)}
      {knopf(<FolderInput />, t('aktion.verschieben'), p.aufVerschieben)}
      {p.gelesenZiel === 'ungelesen'
        ? knopf(<Mail />, t('aktion.ungelesen_kurz'), p.aufGelesen)
        : knopf(<MailOpen />, t('aktion.gelesen_kurz'), p.aufGelesen)}
      {knopf(<MoreHorizontal />, t('aktion.mehr_kurz'), p.aufMehr)}
    </nav>
  )
}
