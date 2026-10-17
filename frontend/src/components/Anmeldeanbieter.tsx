/* Mein Konto → Sicherheit → Anmeldeanbieter.
 *
 * Je aktivem Anbieter eine Zeile mit Zustand und „Verknüpfen“ oder „Lösen“. Wortlaute nur aus dem Anmeldemodul
 * (`oidc.account.*`), Fehler über `oidcErrorKey`, nie die rohe Kennung.
 *
 * ⚠️ **Verknüpfen fragt das Kennwort noch einmal**: ein POST mit Sitzung und Kennwort, kein Link. Die
 * Antwort nennt die Adresse beim Anbieter; der Browser geht dorthin, und die Rückkehr landet wieder hier
 * (`lib/kontorueckweg.ts`).
 *
 * ⚠️ **Lösen geht nicht, wenn es der einzige Weg herein ist** (kein Kennwort, letzte Verknüpfung): Der Knopf fehlt,
 * und der Satz `oidc.account.only` sagt warum. Der Server lehnt es ohnehin ab (`oidc_only_account`).
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { Badge, Button, Dialog, Input } from '../ds'
import { KONTO_RUECKWEG } from '../lib/kontorueckweg'
import { servermeldung } from '../lib/servermeldung'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'

interface Zeile {
  slug: string
  label: string
  linked: boolean
  only: boolean
}

export function Anmeldeanbieter() {
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
    <section className="flex flex-col gap-3" data-testid="anmeldeanbieter-konto">
      <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('oidc.account.title')}</h2>
      <p className="mb-0 text-[12px] text-fg-3">{t('oidc.account.text')}</p>

      {verknuepftMit && (
        <p role="status" className="mb-0 text-[13px] text-success">
          {verknuepftMit.label} · {t('oidc.account.linked')}
        </p>
      )}
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}

      <ul className="flex list-none flex-col gap-2 p-0">
        {zeilen.map((z) => (
          <li
            key={z.slug}
            className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-2.5"
          >
            <KeyRound aria-hidden className="size-4 shrink-0 text-fg-4" />
            <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">{z.label}</span>
            <Badge tone={z.linked ? 'accent' : 'neutral'}>
              {z.linked ? t('oidc.account.linked') : t('oidc.account.notLinked')}
            </Badge>
            {z.linked ? (
              z.only ? (
                <span className="basis-full text-[12px] text-fg-3">
                  {t('oidc.account.only', { name: z.label })}
                </span>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => void loesen(z)}>
                  {t('oidc.account.unlink')}
                </Button>
              )
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setKennwort('')
                  setFehler('')
                  setFragtKennwort(z)
                }}
              >
                {t('oidc.account.link')}
              </Button>
            )}
          </li>
        ))}
      </ul>

      {fragtKennwort && (
        <Dialog
          open
          title={`${t('oidc.account.link')}: ${fragtKennwort.label}`}
          onClose={() => !laeuft && setFragtKennwort(null)}
        >
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              void verknuepfen()
            }}
          >
            <p className="mb-0 text-[13px] text-fg-2">{t('oidc.account.text')}</p>
            <Input
              label={t('anmeldung.passwort')}
              type="password"
              autoComplete="current-password"
              autoFocus
              value={kennwort}
              onChange={(e) => setKennwort(e.target.value)}
            />
            {fehler && (
              <p role="alert" className="mb-0 text-[13px] text-danger">
                {fehler}
              </p>
            )}
            <div className="flex gap-2">
              <Button type="submit" variant="primary" loading={laeuft} disabled={!kennwort}>
                {t('oidc.account.link')}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setFragtKennwort(null)}>
                {t('aktion.abbrechen')}
              </Button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  )
}
