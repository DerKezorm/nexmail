import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/index.css'
import './i18n'
import Start from './Start'
import { arbeiter, moeglich } from './lib/push'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Start />
  </StrictMode>,
)

/* Den Service Worker anmelden — nicht die Erlaubnis holen.
 *
 * ⚠️ **Das sind zwei verschiedene Dinge, und nur eines davon darf hier
 * stehen.** Registrieren fragt niemanden etwas; es ist die Voraussetzung
 * dafür, dass ein Gerät mit längst erteilter Erlaubnis weiter Meldungen
 * bekommt und dass ein erneuertes Abonnement (`pushsubscriptionchange`)
 * überhaupt jemanden erreicht. Die **Nachfrage** gehört dagegen hinter einen
 * Klick im Reiter Benachrichtigungen: Eine, die beim Laden aus dem Nichts
 * kommt, klickt man weg — und danach ist die Funktion für dieses Gerät
 * dauerhaft zu, denn der Browser fragt kein zweites Mal.
 *
 * ⚠️ **Und ein Fehlschlag darf nichts kosten.** Ohne HTTPS gibt es gar keinen
 * Service Worker; die Anwendung läuft trotzdem, nur eben ohne Meldungen.
 */
if (moeglich()) void arbeiter().catch(() => undefined)
