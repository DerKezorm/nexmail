/* Die zwei Seiten des Moduls mcp 1.1.0 außerhalb der Einstellungen, für ein angemeldetes Konto:
 *
 * - `/oauth/authorize`: „Programm verbinden“ (Zustimmung eines KI-Programms über OAuth), mit Stufe, Postfächern und
 *   dem Extra „Mailtext lesen“ (ab Werk aus); danach geht es zur Adresse des Programms zurück.
 * - `/mcp/requests/<nr>`: eine Rückfrage mit allen Angaben, Erlauben oder Ablehnen. Hierher führt die Mitteilung im
 *   Browser („Ein Programm wartet auf dein Ja“) und „Ansehen“ in „Wartende Rückfragen“.
 *
 * Beide nur aus den Bausteinen des Moduls; der Rahmen ist der der Seiten vor der Anmeldung, ohne deren Formular.
 */
import { useTranslation } from 'react-i18next'

import { modulAnfrage } from '../api/client'
import { mcpWorte } from '../lib/mcpWorte'
import { appPfad, ohneBasis } from '../lib/basis'
import { zeitpunkt } from '../lib/format'
import { ConsentPage, RequestPage } from '../vendor/nexmcp'
import { Button } from '../vendor/nexui'

/** Welche Seite des Moduls die Adresse meint, sonst `null`. */
export function mcpSeiteVon(pfad: string): { art: 'zustimmung' } | { art: 'rueckfrage'; nummer: string } | null {
  const ohne = ohneBasis(pfad) ?? ''
  if (ohne === '/oauth/authorize') return { art: 'zustimmung' }
  const treffer = /^\/mcp\/requests\/([^/]+)$/.exec(ohne)
  return treffer ? { art: 'rueckfrage', nummer: decodeURIComponent(treffer[1]) } : null
}

export function McpSeite({ seite }: { seite: NonNullable<ReturnType<typeof mcpSeiteVon>> }) {
  const { t, i18n } = useTranslation()
  const worte = mcpWorte(t)
  return (
    <div className="flex min-h-full items-start justify-center overflow-auto bg-canvas px-4 py-10" data-testid="mcp-seite">
      <div className="flex w-full max-w-[620px] flex-col gap-4">
        {seite.art === 'zustimmung' ? (
          <ConsentPage request={modulAnfrage} areaWord={t('mcp.postfaecher')} words={worte} language={i18n.language} />
        ) : (
          <>
            <RequestPage
              request={modulAnfrage}
              id={seite.nummer}
              words={worte}
              language={i18n.language}
              when={(iso, sprache) => zeitpunkt(iso, sprache)}
            />
            <div>
              <Button kind="secondary" icon="ArrowLeft" href={appPfad('/settings/connections')}>
                {t('nav.einstellungen')}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
