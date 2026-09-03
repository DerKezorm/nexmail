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
import { AlertTriangle, Check, ChevronDown, ChevronRight, Copy, KeyRound } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { Button, Input } from '../ds'

interface Zeile {
  art: string
  name: string
  eingerichtet: boolean
  client_id: string
  mandant: string
  rueckkehr: string
}

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
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="mb-1 text-[15px] font-medium text-fg-1">{t('oauth.titel')}</h2>
        <p className="text-[13px] leading-relaxed text-fg-3">{t('oauth.untertitel')}</p>
      </div>

      {/* ⚠️ Der Satz, der eine Woche später Ärger spart. */}
      <p className="flex items-start gap-2 rounded-md bg-warning-soft px-3 py-2 text-[12px] leading-relaxed text-warning">
        <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" />
        <span>{t('oauth.produktion_warnung')}</span>
      </p>

      {fehler && <p className="text-[12px] text-danger">{fehler}</p>}

      {(zeilen ?? []).map((z) => (
        <Anbieter key={z.art} zeile={z} aufAenderung={() => void laden()} />
      ))}
    </div>
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
  /* ⚠️ **Zugeklappt, nicht weggelassen.** Sieben Schritte offen auf der Seite
     erschlagen jeden, der nur die Client-ID nachtragen will — aber wer zum
     ersten Mal in der Cloud Console steht, kommt ohne sie nicht durch. */
  const [anleitungOffen, setAnleitungOffen] = useState(false)

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
    <section className="flex flex-col gap-3 rounded-lg border border-line p-4">
      <div className="flex items-center gap-2">
        <KeyRound aria-hidden className="size-4 shrink-0 text-fg-3" />
        <h3 className="flex-1 text-[14px] font-medium text-fg-1">{zeile.name}</h3>
        {zeile.eingerichtet && (
          <span className="flex items-center gap-1.5 text-[12px] text-accent-text">
            <Check aria-hidden className="size-3.5" />
            {t('oauth.eingerichtet')}
          </span>
        )}
      </div>

      <p className="text-[12px] leading-relaxed text-fg-4">
        {t(`oauth.anleitung_${zeile.art}`)}
      </p>

      {zeile.art === 'google' && (
        <div className="rounded-md border border-line-subtle">
          <button
            type="button"
            aria-expanded={anleitungOffen}
            onClick={() => setAnleitungOffen((a) => !a)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] font-medium text-fg-2 transition-colors duration-[var(--dur-fast)] hover:text-fg-1"
          >
            {anleitungOffen ? (
              <ChevronDown aria-hidden className="size-4 shrink-0 text-fg-4" />
            ) : (
              <ChevronRight aria-hidden className="size-4 shrink-0 text-fg-4" />
            )}
            <span className="flex-1">
              {anleitungOffen ? t('oauth.anleitung_verbergen') : t('oauth.anleitung_zeigen')}
            </span>
            {!anleitungOffen && (
              <span className="text-[11px] font-normal text-fg-4">
                {t('oauth.anleitung_dauer')}
              </span>
            )}
          </button>

          {anleitungOffen && (
            <ol className="m-0 flex list-none flex-col gap-3 border-t border-line-subtle px-3 py-3">
              {['g1', 'g2', 'g3', 'g4', 'g5', 'g6', 'g7'].map((nr, i) => (
                <li key={nr} className="flex gap-3">
                  <span
                    aria-hidden
                    className="flex size-5 shrink-0 items-center justify-center rounded-pill bg-surface-3 text-[11px] font-semibold text-fg-2"
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[12px] font-medium text-fg-1">
                      {t(`oauth.${nr}_titel`)}
                    </span>
                    <span className="block text-[12px] leading-relaxed text-fg-3">
                      {t(`oauth.${nr}_text`)}
                    </span>
                  </span>
                </li>
              ))}
              {/* ⚠️ **Der Satz, der einen Denkfehler ausräumt.** „Google findet
                  meinen localhost nicht" klingt zwingend und ist falsch: Google
                  ruft die Adresse nie auf, es schickt nur den Browser dorthin. */}
              <li className="flex gap-3 border-t border-line-subtle pt-3">
                <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-4" />
                <span className="text-[12px] leading-relaxed text-fg-3">
                  {t('oauth.localhost_hinweis')}
                </span>
              </li>
            </ol>
          )}
        </div>
      )}

      {/* ⚠️ **Wörtlich zum Kopieren.** Ein Zeichen daneben, und Google
          antwortet mit `redirect_uri_mismatch` — eine Meldung, die niemand
          mit dieser Zeile in Verbindung bringt. */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-medium text-fg-3">{t('oauth.rueckkehr')}</span>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-md bg-surface-2 px-2.5 py-1.5 font-mono text-[12px] text-fg-2">
            {zeile.rueckkehr || t('oauth.rueckkehr_fehlt')}
          </code>
          <Button
            size="sm"
            variant="secondary"
            iconLeft={<Copy className="size-3.5" />}
            disabled={!zeile.rueckkehr}
            onClick={() => void navigator.clipboard?.writeText(zeile.rueckkehr)}
          >
            {t('aktion.kopieren')}
          </Button>
        </div>
        {!zeile.rueckkehr && (
          <span className="text-[11px] text-warning">{t('oauth.adresse_fehlt')}</span>
        )}
      </div>

      <Input
        label={t('oauth.client_id')}
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
      />
      <Input
        label={t('oauth.client_secret')}
        type="password"
        value={secret}
        placeholder={zeile.eingerichtet ? t('oauth.secret_unveraendert') : ''}
        onChange={(e) => setSecret(e.target.value)}
        hint={zeile.eingerichtet ? t('oauth.secret_unveraendert') : undefined}
      />
      {zeile.art === 'microsoft' && (
        <Input
          label={t('oauth.mandant')}
          value={mandant}
          onChange={(e) => setMandant(e.target.value)}
          hint={t('oauth.mandant_hinweis')}
        />
      )}

      {fehler && <p className="text-[12px] text-danger">{fehler}</p>}

      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={!clientId.trim() || laeuft}
          loading={laeuft}
          onClick={() => void speichern()}
        >
          {t('aktion.speichern')}
        </Button>
        {gemerkt && <span className="text-[12px] text-fg-4">{t('oauth.gespeichert')}</span>}
        {zeile.eingerichtet && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              void api.loeschen(`/api/mailoauth/anbieter/${zeile.art}`).then(aufAenderung)
            }
          >
            {t('oauth.entfernen')}
          </Button>
        )}
      </div>
    </section>
  )
}
