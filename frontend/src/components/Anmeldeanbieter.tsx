/* Mein Konto → Sicherheit → Anmeldeanbieter.
 *
 * Ein Kasten (`Box`) in der Karte „Sicherheit“, je aktivem Anbieter eine Zeile (`Row`) mit Zustand und „Verknüpfen“
 * (secondary) oder „Lösen“ (danger), wie in nexnotes; Art und Symbol aus `BUTTONS` (konten 0.3.8). Wortlaute nur aus dem Anmeldemodul
 * (`oidc.account.*`), Fehler über `oidcErrorKey`, nie die rohe Kennung.
 *
 * ⚠️ **Verknüpfen fragt das Passwort noch einmal**: ein POST mit Sitzung und Passwort, kein Link. Die
 * Antwort nennt die Adresse beim Anbieter; der Browser geht dorthin, und die Rückkehr landet wieder hier
 * (`lib/kontorueckweg.ts`).
 *
 * ⚠️ **Lösen geht nicht, wenn es der einzige Weg herein ist** (kein Passwort, letzte Verknüpfung): Der Knopf fehlt,
 * und der Satz `oidc.account.only` sagt warum. Der Server lehnt es ohnehin ab (`oidc_only_account`).
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { confirmOf } from '../lib/accountButton'
import { KONTO_RUECKWEG } from '../lib/kontorueckweg'
import { servermeldung } from '../lib/servermeldung'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'
import { Badge, Box, ConfirmDialog, Field, Notice, Row, Rows } from '../vendor/nexui'
import { AccountButton } from './AccountButton'

interface Zeile {
  slug: string
  label: string
  linked: boolean
  only: boolean
}

export function Anmeldeanbieter({ hatKennwort = true }: { hatKennwort?: boolean }) {
  const { t } = useTranslation()
  const [zeilen, setZeilen] = useState<Zeile[]>([])
  const [fehler, setFehler] = useState(() => {
    const schluessel = oidcErrorKey(KONTO_RUECKWEG.fehler)
    return schluessel ? t(schluessel) : ''
  })
  const [gelungen, setGelungen] = useState(KONTO_RUECKWEG.verknuepft)
  const [fragtKennwort, setFragtKennwort] = useState<Zeile | null>(null)
  const [kennwort, setKennwort] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<Zeile[]>('/api/oidc/me'))
    } catch {
      setZeilen([])
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  function deuten(f: unknown): string {
    const schluessel = f instanceof ApiFehler ? oidcErrorKey(f.detail) : null
    return schluessel ? t(schluessel) : servermeldung(f, t('anmeldung.fehler_allgemein'))
  }

  async function verknuepfen() {
    if (!fragtKennwort) return
    setLaeuft(true)
    setFehler('')
    try {
      const { url } = await api.senden<{ url: string }>(
        `/api/oidc/${encodeURIComponent(fragtKennwort.slug)}/link`,
        { password: kennwort },
      )
      window.location.assign(url)
    } catch (f) {
      setFehler(deuten(f))
      setLaeuft(false)
    }
  }

  async function loesen(zeile: Zeile) {
    setFehler('')
    setGelungen('')
    try {
      await api.loeschen(`/api/oidc/${encodeURIComponent(zeile.slug)}/link`)
      await laden()
    } catch (f) {
      setFehler(deuten(f))
    }
  }

  if (zeilen.length === 0 && !fehler) return null

  const verknuepftMit = zeilen.find((z) => z.slug === gelungen)

  return (
    <Box title={t('oidc.account.title')} hint={t('oidc.account.text')} testId="anmeldeanbieter-konto">
      {verknuepftMit && (
        <Notice tone="ok">
          {verknuepftMit.label} · {t('oidc.account.linked')}
        </Notice>
      )}
      {fehler && !fragtKennwort && <Notice tone="danger">{fehler}</Notice>}
      <Rows label={t('oidc.account.title')}>
        {zeilen.map((z) => (
          <Row
            key={z.slug}
            icon={KeyRound}
            name={z.label}
            badge={<Badge tone={z.linked ? 'on' : 'off'}>{z.linked ? t('oidc.account.linked') : t('oidc.account.notLinked')}</Badge>}
            note={z.linked && z.only ? t('oidc.account.only', { name: z.label }) : undefined}
            action={
              z.linked ? (
                !z.only && <AccountButton name="oidc.account.unlink" onClick={() => void loesen(z)} />
              ) : (
                hatKennwort && (
                  <AccountButton
                    name="oidc.account.link"
                    onClick={() => {
                      setKennwort('')
                      setFehler('')
                      setFragtKennwort(z)
                    }}
                  />
                )
              )
            }
          />
        ))}
      </Rows>

      {fragtKennwort && (
        <ConfirmDialog
          title={`${t('oidc.account.link')}: ${fragtKennwort.label}`}
          text={t('oidc.account.text')}
          confirm={confirmOf('oidc.account.link', t('oidc.account.link'))}
          cancel={t('aktion.abbrechen')}
          closeLabel={t('aktion.schliessen')}
          busy={laeuft}
          error={fehler || undefined}
          confirmDisabled={!kennwort}
          onCancel={() => !laeuft && setFragtKennwort(null)}
          onConfirm={() => void verknuepfen()}
        >
          <Field label={t('account.currentPassword')} type="password" autoComplete="current-password" value={kennwort} onChange={(e) => setKennwort(e.target.value)} />
        </ConfirmDialog>
      )}
    </Box>
  )
}
