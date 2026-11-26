/* Server › Log: die Karte „Log" des gemeinsamen Moduls log (`vendor/nexlog`, bauplaene/log 1.0.0), aus dem Bausatz.
 *
 * nexmail gibt ihr seinen Client, sein Wort für das, was es hält („Mails"), und seine Art, einen Zeitpunkt zu schreiben
 * (in der eingestellten Zone wie jedes Datum in nexmail; die Datei steht in UTC). Herunterladen ist seit dem Modul ein
 * Text statt eines ZIP (E21). Der alte Weg `/api/protokoll` bleibt am Server.
 */
import { useTranslation } from 'react-i18next'

import { modulAnfrage } from '../api/client'
import { appPfad } from '../lib/basis'
import { protokollzeit, uhrzeit } from '../lib/format'
import { LogCard } from '../vendor/nexlog/LogCard'
import type { LogLine, LogRequest } from '../vendor/nexlog/log'

const anfrage: LogRequest = <T,>(pfad: string, init: Parameters<LogRequest>[1] = {}) => modulAnfrage<T>(pfad, init)

const wann = (zeile: LogLine, sprache: string) => protokollzeit(zeile.time, sprache)

export function Protokoll() {
  const { t } = useTranslation()
  return (
    <LogCard
      request={anfrage}
      base="/api/logs"
      downloadHref={appPfad('/api/logs/download')}
      things={t('einstellungen.dinge')}
      thingsDative={t('einstellungen.dinge_dativ')}
      when={wann}
      clock={(iso, sprache) => uhrzeit(iso, sprache)}
    />
  )
}
