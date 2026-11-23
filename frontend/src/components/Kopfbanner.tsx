/* Das Banner ganz oben — wie in Nexview.
 *
 * Es läuft über die volle Breite: Die Marke gehört der ganzen Anwendung und
 * nicht einer Spalte darin.
 *
 * Wer angemeldet ist, zeigt seit dem 23.11.2026 die Profilzeile unten in der
 * Ordnerspalte (wie in nexnotes), nicht mehr ein Menü hier oben.
 */
import { useTranslation } from 'react-i18next'
import { Logo } from './Logo'

interface Props {
  /** Solange kein Postfach angebunden ist, sagt das Banner es. Danach
   *  verschwindet der Hinweis - ein Abzeichen, das immer da steht, wird nicht
   *  mehr gelesen. */
  ohnePostfach: boolean
}

export function Kopfbanner({ ohnePostfach }: Props) {
  const { t } = useTranslation()

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line-subtle bg-surface-1 px-3">
      <Logo withWordmark />

      <span className="flex-1" />

      {ohnePostfach && (
        <span className="hidden truncate rounded-pill bg-warning-soft px-2.5 py-1 text-[11px] font-medium text-warning sm:inline">
          {t('konto.kein_postfach')}
        </span>
      )}

      {/* ⚠️ **Rechts steht nichts mehr** (seit 23.11.2026). Bis dahin saß hier
          das Benutzermenü mit Bild, Einstellungen, „Was ist neu" und
          „Abmelden". Wie in nexnotes ist das jetzt die Profilzeile unten in
          der Ordnerspalte; „Was ist neu" steht unter „Über nexmail", der Stand
          des zweiten Faktors unter Sicherheit, „Abmelden" im Profil. Hell/
          Dunkel und Sprache waren schon am 22.11.2026 in die Einstellungen
          gezogen. */}
    </header>
  )
}
