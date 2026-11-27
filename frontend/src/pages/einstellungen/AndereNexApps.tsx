/* Mein Konto › Verbindungen, die anderen nex-Apps (Modul verbinden): je Partner eine Karte mit dem Zeichen des Moduls,
 * „Mit … verbinden“ oder von Hand; nur Partner, die nexmail nutzt (V20, `in_use` auf dem Server: nextime, nextasks,
 * nexfolk, nexpaper). Kalender- und Listenwahl offen in der Karte, in jedem Zustand (V23).
 *
 * Seit verbinden 0.1.8 (B3, V42, V46) richtet nur der Betreiber die anderen Apps ein: die Karte hat kein Adressfeld
 * mehr, „Einrichten“ und „Von Hand verbinden“ für eine neue Verbindung sieht nur er (`operator`). Eine alte Verbindung
 * von Hand bleibt dem Konto änderbar; nexmails alte Wege dafür nehmen weiter an (E55). */
import { useTranslation } from 'react-i18next'

import { modulAnfrage } from '../../api/client'
import { zeitpunkt } from '../../lib/format'
import { ConnectionsArea } from '../../vendor/nexverbinden'
import { NexApps } from './NexApps'

export function AndereNexApps({ betreiber }: { betreiber: boolean }) {
  const { t, i18n } = useTranslation()
  return (
    <ConnectionsArea
      app="nexmail"
      request={modulAnfrage}
      operator={betreiber}
      manual={{ nextime: <NexApps nur="nextime" teil="hand" />, nextasks: <NexApps nur="nextasks" teil="hand" /> }}
      extra={(view) =>
        view.partner === 'nextime' || view.partner === 'nextasks' ? (
          <NexApps nur={view.partner} teil="wahl" />
        ) : view.partner === 'nexfolk' || view.partner === 'nexpaper' ? (
          <p className="m-0 text-sm text-fg-3">{t(`einstellungen.${view.partner}_nutzung`)}</p>
        ) : null
      }
      language={i18n.language}
      when={zeitpunkt}
    />
  )
}
