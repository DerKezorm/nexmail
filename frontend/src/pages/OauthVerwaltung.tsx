/* Die App-Anmeldung bei Google und Microsoft — nur für den Betreiber.
 *
 * ⚠️ **nexmail kann kein Geheimnis mitliefern.** Das Repo ist öffentlich; ein
 * eingebauter Client-Schlüssel stünde darin, und Google wie Microsoft ziehen
 * ihn zurück, sobald sie ihn finden. Es gibt dafür keinen Trick — jeder
 * Betreiber legt seine eigene App an. Die Seite sagt das, statt es zu
 * verschweigen und den Betreiber raten zu lassen, warum nichts geht.
 *
 * ⚠️ **Der Warnsatz zu „In production" steht ganz oben.** Bei Google verfallen
 * Auffrischungs-Token im Testbetrieb nach sieben Tagen; wer das nicht weiß,
 * richtet alles ein, freut sich eine Woche und sucht dann den Fehler im
 * Mailserver.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Building2 } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { Badge, Box, Button, Buttons, Card, Collapsible, CopyRow, Field, Notice } from '../vendor/nexui'

interface Zeile {
  art: string
  name: string
  eingerichtet: boolean
  client_id: string
  mandant: string
  rueckkehr: string
}

/** Server › Mail, zweite Karte „Google und Microsoft" (app-eigen, Bausatz ui 1.1.0): je Anbieter ein Kasten. */
export function OauthVerwaltung() {
  const { t } = useTranslation()
  const [zeilen, setZeilen] = useState<Zeile[] | null>(null)
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<Zeile[]>('/api/mailoauth/anbieter'))
    } catch {
      setZeilen([])
      setFehler(t('oauth.laden_fehler'))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  return (
    <Card id="mail-oauth" icon={Building2} title={t('oauth.titel')} subtitle={t('oauth.untertitel')}>
      {/* ⚠️ Der Satz, der eine Woche später Ärger spart. */}
      <Notice tone="warn">{t('oauth.produktion_warnung')}</Notice>
      {fehler && <Notice tone="danger">{fehler}</Notice>}
      {(zeilen ?? []).map((z) => (
        <Anbieter key={z.art} zeile={z} aufAenderung={() => void laden()} />
      ))}
    </Card>
  )
}

function Anbieter({ zeile, aufAenderung }: { zeile: Zeile; aufAenderung: () => void }) {
  const { t, i18n } = useTranslation()
  const [clientId, setClientId] = useState(zeile.client_id)
  const [secret, setSecret] = useState('')
  const [mandant, setMandant] = useState(zeile.mandant)
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [gemerkt, setGemerkt] = useState(false)

  async function speichern() {
    setLaeuft(true)
    setFehler('')
    try {
      await api.aendern(`/api/mailoauth/anbieter/${zeile.art}`, {
        client_id: clientId.trim(),
        client_secret: secret,
        mandant: mandant.trim() || 'common',
      })
      setSecret('')
      setGemerkt(true)
      aufAenderung()
    } catch (f) {
      const kennung = f instanceof ApiFehler ? f.detail : ''
      const schluessel = `oauth.fehler_${kennung}`
      setFehler(i18n.exists(schluessel) ? t(schluessel) : t('oauth.fehler_allgemein'))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Box
      title={zeile.name}
      badge={<Badge tone={zeile.eingerichtet ? 'on' : 'off'}>{zeile.eingerichtet ? t('oauth.eingerichtet') : t('oauth.nicht_eingerichtet')}</Badge>}
      hint={t(`oauth.anleitung_${zeile.art}`)}
      actions={
        <Buttons>
          <Button kind="primary" icon="Check" disabled={!clientId.trim()} busy={laeuft} onClick={() => void speichern()}>
            {t('aktion.speichern')}
          </Button>
          {zeile.eingerichtet && (
            <Button
              kind="danger"
              icon="Trash2"
              onClick={() => void api.loeschen(`/api/mailoauth/anbieter/${zeile.art}`).then(aufAenderung)}
            >
              {t('oauth.entfernen')}
            </Button>
          )}
        </Buttons>
      }
    >
      {zeile.art === 'google' && (
        /* ⚠️ **Zugeklappt, nicht weggelassen.** Sieben Schritte offen erschlagen jeden, der nur die Client-ID
           nachtragen will; wer zum ersten Mal in der Cloud Console steht, kommt ohne sie nicht durch. */
        <Collapsible title={t('oauth.anleitung_zeigen')} status={t('oauth.anleitung_dauer')} id="oauth-google-anleitung">
          <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {['g1', 'g2', 'g3', 'g4', 'g5', 'g6', 'g7'].map((nr, i) => (
              <li key={nr} className="flex gap-3">
                <span aria-hidden className="w-5 shrink-0 text-sm font-semibold">
                  {i + 1}.
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{t(`oauth.${nr}_titel`)}</span>
                  <span className="block text-sm">{t(`oauth.${nr}_text`)}</span>
                </span>
              </li>
            ))}
            {/* ⚠️ „Google findet meinen localhost nicht" klingt zwingend und ist falsch: Google ruft die Adresse nie
                auf, es schickt nur den Browser dorthin. */}
            <li>
              <Notice tone="warn">{t('oauth.localhost_hinweis')}</Notice>
            </li>
          </ol>
        </Collapsible>
      )}

      {/* ⚠️ **Wörtlich zum Kopieren.** Ein Zeichen daneben, und Google antwortet mit `redirect_uri_mismatch`. */}
      {zeile.rueckkehr ? (
        <CopyRow label={t('oauth.rueckkehr')} value={zeile.rueckkehr} />
      ) : (
        <Notice tone="warn" title={t('oauth.rueckkehr_fehlt')}>
          {t('oauth.adresse_fehlt')}
        </Notice>
      )}

      <Field label={t('oauth.client_id')} value={clientId} onChange={(e) => setClientId(e.target.value)} />
      <Field
        label={t('oauth.client_secret')}
        type="password"
        value={secret}
        placeholder={zeile.eingerichtet ? t('oauth.secret_unveraendert') : ''}
        onChange={(e) => setSecret(e.target.value)}
        hints={zeile.eingerichtet ? [t('oauth.secret_unveraendert')] : []}
      />
      {zeile.art === 'microsoft' && (
        <Field
          label={t('oauth.mandant')}
          value={mandant}
          onChange={(e) => setMandant(e.target.value)}
          hints={[t('oauth.mandant_hinweis')]}
        />
      )}

      {fehler && <Notice tone="danger">{fehler}</Notice>}
      {gemerkt && <Notice tone="ok">{t('oauth.gespeichert')}</Notice>}
    </Box>
  )
}
