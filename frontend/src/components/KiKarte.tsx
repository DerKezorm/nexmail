/* Die Karte über der Mail: Zusammenfassung, Übersetzung, Frage.
 *
 * ⚠️ **Als Text, nie als HTML.** Die Mail, aus der das entstand, kann dem Modell
 * einen Link untergeschoben haben. React setzt hier Zeichen, kein Markup, und
 * das Etikett sagt, wessen Worte das sind.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Sparkles, X } from 'lucide-react'
import { IconButton, Input } from '../ds'

export type KiArt = 'zusammenfassen' | 'uebersetzen' | 'frage'

/** ⚠️ **Muss zu `kidienst.MAX_FRAGE` im Server passen.** Mehr schneidet er ab. */
const MAX_FRAGE = 500

interface Props {
  art: KiArt
  laeuft: boolean
  ergebnis: { text: string; gekuerzt: boolean } | null
  fehler: string
  aufFrage: (frage: string) => void
  aufSchliessen: () => void
}

export function KiKarte({ art, laeuft, ergebnis, fehler, aufFrage, aufSchliessen }: Props) {
  const { t } = useTranslation()
  const [frage, setFrage] = useState('')

  // Wörtlich, nicht zusammengesetzt: Nur so sieht der Schlüssel-Wächter sie.
  const titel = {
    zusammenfassen: t('ki.zusammenfassung_titel'),
    uebersetzen: t('ki.uebersetzung_titel'),
    frage: t('ki.frage_titel'),
  }[art]
  const laeuftText = {
    zusammenfassen: t('ki.zusammenfassung_laeuft'),
    uebersetzen: t('ki.uebersetzung_laeuft'),
    frage: t('ki.frage_laeuft'),
  }[art]
  const gekuerztText =
    art === 'uebersetzen' ? t('ki.uebersetzung_gekuerzt') : t('ki.zusammenfassung_gekuerzt')

  return (
    <section
      aria-label={titel}
      className="mx-6 mt-4 flex flex-col gap-2 rounded-lg border border-line bg-surface-2 px-4 py-3"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 shrink-0 text-fg-4" aria-hidden />
        <span className="flex-1 text-[12px] font-semibold text-fg-2">{titel}</span>
        {!laeuft && <IconButton icon={<X />} label={t('aktion.schliessen')} onClick={aufSchliessen} />}
      </div>

      {art === 'frage' && (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            aufFrage(frage)
          }}
        >
          <div className="min-w-0 flex-1">
            <Input
              autoFocus
              aria-label={t('ki.frage_titel')}
              placeholder={t('ki.frage_platzhalter')}
              maxLength={MAX_FRAGE}
              value={frage}
              onChange={(e) => setFrage(e.target.value)}
            />
          </div>
          <IconButton
            type="submit"
            icon={<Send />}
            label={t('ki.frage_stellen')}
            disabled={laeuft || !frage.trim()}
          />
        </form>
      )}

      {laeuft && (
        <p role="status" className="mb-0 text-[13px] text-fg-3">
          {laeuftText}
        </p>
      )}
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      {ergebnis && (
        <>
          <p className="mb-0 text-[13px] whitespace-pre-wrap text-fg-1">{ergebnis.text}</p>
          {ergebnis.gekuerzt && <p className="mb-0 text-[12px] text-warning">{gekuerztText}</p>}
          <p className="mb-0 text-[11px] text-fg-4">{t('ki.zusammenfassung_hinweis')}</p>
        </>
      )}
    </section>
  )
}
