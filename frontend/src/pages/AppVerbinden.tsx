/* Die Seite /app-connect (Gerätemodul geraete 0.1.0, G8): eine App, die man nur mit der Adresse des Servers
 * eingerichtet hat, öffnet sie im Browser. Wer angemeldet ist, sieht, welches Konto sich verbindet, und stimmt zu; die
 * App bekommt über `nexmail://connected?code=…&state=…` einen Einmalcode (fünf Minuten, einmal). Ohne Anmeldung kommt
 * vorher die gewöhnliche Anmeldung (`Start.tsx`), danach dieselbe Adresse.
 */
import { useTranslation } from 'react-i18next'
import type { Ich } from '../api/client'
import { modulAnfrage } from '../api/client'
import { ohneBasis } from '../lib/basis'
import { AppConnectPage } from '../vendor/nexgeraete'

/** Ob die Adresse die Seite /app-connect ist (mit oder ohne Unterpfad). */
export function istAppVerbinden(pfad: string): boolean {
  return ohneBasis(pfad) === '/app-connect'
}

export function AppVerbinden({ ich }: { ich: Ich | null }) {
  const { i18n } = useTranslation()
  return (
    <AppConnectPage
      request={modulAnfrage}
      app="nexmail"
      scheme="nexmail"
      account={ich ? { name: ich.anzeigename || ich.benutzername, login: ich.benutzername } : null}
      language={i18n.language}
      search={window.location.search}
    />
  )
}
