/* Der Rückweg vom Anmeldeanbieter nach dem Verknüpfen: `/konto/sicherheit?linked=<kurzname>` oder `?error=<code>`.
 *
 * Das Anmeldemodul schickt den Browser nach dem Verknüpfen auf die Kontoseite (Bauplan „Anmeldung mit OIDC und
 * authentik“, Teil 02); in nexmail ist das Einstellungen → Sicherheit. Die Anwendung öffnet dort, und der Reiter
 * zeigt, wie es ausging.
 *
 * ⚠️ **Einmal beim Laden gelesen** (wie `oauthrueckweg.ts`): Die Ansicht der App und der Reiter fragen beide, und die
 * Adresse wird sofort bereinigt, sonst käme die Meldung bei jedem Neuladen wieder.
 */
import { appPfad, ohneBasis } from './basis'

export const KONTOSEITE = '/konto/sicherheit'

function lesen(): { da: boolean; verknuepft: string; fehler: string } {
  if (typeof window === 'undefined') return { da: false, verknuepft: '', fehler: '' }
  const pfad = ohneBasis(window.location.pathname)
  if (pfad !== KONTOSEITE) return { da: false, verknuepft: '', fehler: '' }
  const frage = new URLSearchParams(window.location.search)
  const ergebnis = { da: true, verknuepft: frage.get('linked') ?? '', fehler: frage.get('error') ?? '' }
  window.history.replaceState({}, '', appPfad('/'))
  return ergebnis
}

export const KONTO_RUECKWEG = lesen()
