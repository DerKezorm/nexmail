/* Unten in der Ordnerspalte: wer angemeldet ist, und der Weg in die
 * Einstellungen — wie unten in der Seitenleiste von nexnotes („Name ·
 * Einstellungen" mit Zahnrad).
 *
 * ⚠️ **Bis zum 23.11.2026 standen hier „Postfach hinzufügen" und oben rechts
 * ein Benutzermenü.** Ein Postfach legt man in den Einstellungen an (die
 * (+)-Kachel unter Postfächer); der Stand des zweiten Faktors steht unter
 * Sicherheit, „Abmelden" im Profil, „Was ist neu" unter „Über nexmail".
 * Derselbe Griff an derselben Stelle wie in nexnotes und nextasks: Wer eine
 * der Apps kennt, findet sich in den anderen zurecht.
 *
 * Solange die Einstellungen offen sind, ist die Zeile farbig hinterlegt — wie
 * der gewählte Ordner darüber.
 */
import { useTranslation } from 'react-i18next'
import { Settings } from 'lucide-react'
import { Profilbild } from './Profilbild'
import type { Ich } from '../api/client'

interface Props {
  ich: Ich | null
  /** Die Einstellungen sind gerade offen. */
  aktiv: boolean
  aufEinstellungen: () => void
}

export function Profilzeile({ ich, aktiv, aufEinstellungen }: Props) {
  const { t } = useTranslation()
  const name = ich?.anzeigename || ich?.benutzername || ''
  const text = name ? `${name} · ${t('nav.einstellungen')}` : t('nav.einstellungen')
  return (
    <div className="shrink-0 border-t border-line-subtle p-2" data-testid="profilzeile">
      <button
        type="button"
        onClick={aufEinstellungen}
        aria-current={aktiv ? 'page' : undefined}
        aria-label={text}
        title={text}
        className={
          'flex w-full items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-left text-[14px] ' +
          'transition-colors duration-[var(--dur-fast)] ' +
          (aktiv
            ? 'bg-accent-soft text-accent-text'
            : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')
        }
      >
        {ich && <Profilbild id={ich.id} name={name} stand={ich.profilbild} groesse={28} />}
        {/* ⚠️ **Nur der Name** (gemeldet am 23.11.2026, wie nexnotes seit
            demselben Tag): Das Zahnrad sagt „Einstellungen"; das Wort steht
            nur noch für Vorlesehilfen und im Hinweis. */}
        <span className="min-w-0 flex-1 truncate">{name}</span>
        <Settings aria-hidden className="size-4 shrink-0" strokeWidth={1.8} />
      </button>
    </div>
  )
}
