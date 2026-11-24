/* Der Link, der eine neue Adresse bestätigt (Kontenmodul). Er kommt per Mail und muss auch auf einem Gerät gehen, auf
 * dem niemand angemeldet ist; deshalb steht die Seite vor der Anmeldung, wie die für ein neues Passwort.
 *
 * ⚠️ **Erst ansehen, dann bestätigen.** Manche Mailprogramme öffnen Links vorab, um sie zu prüfen; ein Link, der beim
 * bloßen Öffnen schon bestätigt, wäre dann verbraucht, bevor der Mensch ihn sieht.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MailCheck } from 'lucide-react'
import { api } from '../api/client'
import { Button } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import { Torbogen } from '../components/Torbogen'
import { Meldung } from './EinrichtungPage'

export function AdressePage({
  schluessel,
  modus,
  aufModus,
  aufFertig,
}: {
  schluessel: string
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufFertig: () => void
}) {
  const { t } = useTranslation()
  const [adresse, setAdresse] = useState('')
  const [fehler, setFehler] = useState('')
  const [fertig, setFertig] = useState(false)
  const [laeuft, setLaeuft] = useState(false)

  useEffect(() => {
    api
      .holen<{ adresse: string }>(`/api/auth/adresse/${encodeURIComponent(schluessel)}`)
      .then((a) => setAdresse(a.adresse))
      .catch((f) => setFehler(servermeldung(f, t('account.error.email_link_invalid'))))
  }, [schluessel, t])

  async function bestaetigen() {
    setLaeuft(true)
    try {
      await api.senden(`/api/auth/adresse/${encodeURIComponent(schluessel)}`, {})
      setFertig(true)
    } catch (f) {
      setFehler(servermeldung(f, t('account.error.email_link_invalid')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Torbogen modus={modus} aufModus={aufModus} titel={t('adresse.titel')} untertitel={adresse || undefined}>
      <div className="flex flex-col gap-4">
        {fehler && <Meldung text={fehler} />}
        {fertig && (
          <div className="flex items-start gap-3 rounded-lg border border-line bg-surface-3 p-3">
            <MailCheck className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
            <p className="mb-0 text-[13px] text-fg-2">{t('account.emailConfirmed')}</p>
          </div>
        )}
        {!fehler && !fertig && adresse && (
          <Button variant="primary" size="lg" fullWidth loading={laeuft} onClick={() => void bestaetigen()}>
            {t('adresse.bestaetigen')}
          </Button>
        )}
        {(fehler || fertig) && (
          <Button variant={fertig ? 'primary' : 'ghost'} onClick={aufFertig}>
            {t('adresse.weiter')}
          </Button>
        )}
      </div>
    </Torbogen>
  )
}
