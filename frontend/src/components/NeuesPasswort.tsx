/* Nach einem neuen Passwort über einen Link: „Diese Geräte haben noch Zugriff“ mit „Alle trennen“ (Kontenmodul).
 *
 * ⚠️ **Ein neues Passwort beendet nur Browser-Anmeldungen.** Die iPhone-App und API-Schlüssel bleiben (Entwurf,
 * Entscheidung „Neues Passwort“): Wer sein Passwort vergessen hat, soll nicht jedes Gerät neu koppeln müssen. Wer es
 * zurücksetzt, weil jemand anders hineinkam, trennt hier alles mit einem Klick. Gezeigt wird das einmal, bei der
 * nächsten Anmeldung; danach weiß der Server, dass es gesehen ist.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { Button, Dialog } from '../ds'
import { servermeldung } from '../lib/servermeldung'

interface Zugaenge {
  herkunft: string
  zugaenge: Array<{ id: string; art: string; name: string; zuletzt: string | null }>
}

export function NeuesPasswort({ aufErledigt }: { aufErledigt: () => void }) {
  const { t } = useTranslation()
  const [stand, setStand] = useState<Zugaenge | null>(null)
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  useEffect(() => {
    api
      .holen<Zugaenge>('/api/auth/zugaenge')
      .then((z) => {
        // Nichts zu trennen und niemand anders war beteiligt: nichts zu zeigen.
        if (z.zugaenge.length === 0 && z.herkunft === 'self') {
          void api.senden('/api/auth/zugaenge/gesehen', {}).then(aufErledigt, () => undefined)
          return
        }
        setStand(z)
      })
      .catch(() => undefined)
  }, [aufErledigt])

  if (!stand) return null

  async function schliessen(trennen: boolean) {
    setLaeuft(true)
    try {
      await api.senden(trennen ? '/api/auth/zugaenge/trennen' : '/api/auth/zugaenge/gesehen', {})
      aufErledigt()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      setLaeuft(false)
    }
  }

  return (
    <Dialog
      open
      title={t('profil.neues_passwort_titel')}
      onClose={() => void schliessen(false)}
      footer={
        <>
          <Button variant="ghost" disabled={laeuft} onClick={() => void schliessen(false)}>
            {t('aktion.fertig')}
          </Button>
          {stand.zugaenge.length > 0 && (
            <Button variant="danger" loading={laeuft} onClick={() => void schliessen(true)}>
              {t('account.disconnectAll')}
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[13px] text-fg-2">
        {stand.herkunft !== 'self' && <p className="mb-0">{t('account.resetByOperator')}</p>}
        {stand.zugaenge.length > 0 && (
          <>
            <p className="mb-0">{t('account.remainingAccess')}</p>
            <ul className="mb-0 flex list-none flex-col gap-1 p-0">
              {stand.zugaenge.map((z) => (
                <li key={z.id} className="rounded-md border border-line bg-surface-2 px-3 py-2 text-fg-1">
                  {z.name || t(z.art === 'api_key' ? 'profil.zugang_schluessel' : 'profil.zugang_geraet')}
                  <span className="ml-2 text-[12px] text-fg-4">
                    {t(z.art === 'api_key' ? 'profil.zugang_schluessel' : 'profil.zugang_geraet')}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
        {fehler && (
          <p role="alert" className="mb-0 text-danger">
            {fehler}
          </p>
        )}
      </div>
    </Dialog>
  )
}
