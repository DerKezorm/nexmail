/* Dialog „Sitzung abgelaufen“ (konten 0.3.5): Endet die Sitzung, während eine Seite offen ist, meldet man sich hier
 * neu an, und die Seite darunter bleibt, samt allem, was darauf geschrieben ist. Die Teile je Schritt kommen aus dem
 * Kontenmodul (`sessionExpiredParts(next)`): erst Passwort und „oder“ mit den Anbietern, dann, was der Server als
 * Nächstes verlangt (Code, Passkey, Einrichten, Codes). nexmails Schritte (`schritt`) heißen dabei wie die des Moduls.
 *
 * ⚠️ **Ausgelöst von `api/client.ts`**: Eine Anfrage außerhalb von `/api/auth/` und `/api/setup/` bekommt 401, die
 * Sitzung ist also weg (abgelaufen, anderswo abgemeldet). Die Anmeldewege selbst melden 401 als Antwort.
 * ⚠️ **Ein Anbieter verlässt die Seite** (Weiterleitung); was auf ihr geschrieben war, geht dann verloren.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Fingerprint, KeyRound } from 'lucide-react'
import { api, type Ich, type Schritt } from '../api/client'
import { Button, Dialog, Input } from '../ds'
import { appPfad } from '../lib/basis'
import { alsJson, anmeldeOptionen, passkeyMoeglich } from '../lib/passkey'
import { servermeldung } from '../lib/servermeldung'
import { CODE_DIGITS, sessionExpiredParts } from '../vendor/nexkonten/konten'
import { CodesZeigen } from './ZweiterFaktor'

/** Das Ereignis, mit dem `api/client.ts` sagt: Die Sitzung ist weg. */
export const SITZUNG_WEG = 'nexmail:sitzung-weg'

/** nexmails Antwort auf einen Anmeldeschritt als Schritt des Moduls (`NEXT_STEPS`). */
export function naechster(antwort: Schritt): string {
  if (antwort.schritt === 'fertig') return antwort.weiter === 'show_codes' && antwort.codes?.length ? 'show_codes' : 'session'
  if (antwort.schritt === 'code') return 'second_factor'
  if (antwort.schritt === 'einrichten') return 'second_factor_setup'
  return antwort.schritt === 'passkey' ? 'passkey' : 'sign_in'
}

export function SitzungAbgelaufen({ ich, aufFertig }: { ich: Ich | null; aufFertig: () => void }) {
  const { t } = useTranslation()
  const [offen, setOffen] = useState(false)
  const [next, setNext] = useState('sign_in')
  const [passwort, setPasswort] = useState('')
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[]>([])
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [anbieter, setAnbieter] = useState<Array<{ slug: string; label: string }>>([])

  useEffect(() => {
    function weg() {
      setOffen((schon) => {
        if (!schon) {
          setNext('sign_in')
          setPasswort('')
          setCode('')
          setFehler('')
        }
        return true
      })
    }
    window.addEventListener(SITZUNG_WEG, weg)
    return () => window.removeEventListener(SITZUNG_WEG, weg)
  }, [])

  useEffect(() => {
    if (!offen) return
    void api
      .holen<{ providers: Array<{ slug: string; label: string }> }>('/api/oidc/anmeldeseite')
      .then((s) => setAnbieter(s.providers), () => setAnbieter([]))
  }, [offen])

  if (!offen || !ich) return null
  const mitPasswort = ich.hat_kennwort !== false

  function fertig() {
    setOffen(false)
    aufFertig()
  }

  async function schritt(aufruf: () => Promise<Schritt>) {
    setFehler('')
    setLaeuft(true)
    try {
      const antwort = await aufruf()
      const weiter = naechster(antwort)
      if (weiter === 'session') return fertig()
      if (weiter === 'show_codes') setCodes(antwort.codes ?? [])
      setNext(weiter)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  function wiederAnmelden() {
    if (next === 'second_factor') {
      void schritt(() => api.senden<Schritt>('/api/auth/code', { code: code.trim() }))
    } else {
      void schritt(() =>
        api.senden<Schritt>('/api/auth/anmelden', { benutzername: ich?.benutzername ?? '', passwort }),
      )
    }
  }

  function mitPasskey() {
    void schritt(async () => {
      const optionen = await api.senden<Record<string, unknown>>('/api/auth/passkey/start', {})
      const antwort = await navigator.credentials.get({ publicKey: anmeldeOptionen(optionen) })
      if (!antwort) throw new Error('passkey_invalid')
      return api.senden<Schritt>('/api/auth/passkey', { credential: alsJson(antwort as PublicKeyCredential) })
    })
  }

  const teile: Record<string, () => React.ReactNode> = {
    sessionExpiredHint: () => <p className="mb-0 text-[13px] text-fg-2">{t('account.sessionExpiredHint')}</p>,
    password: () =>
      mitPasswort && (
        <Input
          label={t('account.password')}
          type="password"
          autoComplete="current-password"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
        />
      ),
    code: () => (
      <Input
        label={t('account.code')}
        value={code}
        mono
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={20}
        onChange={(e) => setCode(e.target.value)}
      />
    ),
    signInAgain: () =>
      (next !== 'sign_in' || mitPasswort) && (
        <div>
          <Button
            type="submit"
            variant="primary"
            loading={laeuft}
            disabled={next === 'second_factor' ? code.trim().length < CODE_DIGITS : !passwort}
          >
            {t('account.signInAgain')}
          </Button>
        </div>
      ),
    /* „oder“ und die Anbieter wie auf der Anmeldeseite: ein gewöhnlicher Verweis, die Weiterleitung verlässt die
       Seite. */
    or: () =>
      anbieter.length > 0 && (
        <div className="flex flex-col gap-2">
          {mitPasswort && (
            <div className="flex items-center gap-3 text-[12px] text-fg-4" aria-hidden>
              <span className="h-px flex-1 bg-line-subtle" />
              {t('oidc.login.or')}
              <span className="h-px flex-1 bg-line-subtle" />
            </div>
          )}
          {anbieter.map((a) => (
            <a
              key={a.slug}
              href={appPfad(`/api/oidc/${encodeURIComponent(a.slug)}/start`)}
              className="flex h-[var(--control-h-md)] items-center justify-center gap-2 rounded-md border border-line bg-surface-2 text-sm font-medium text-fg-1 no-underline transition-colors duration-[var(--dur-fast)] hover:border-accent"
            >
              <KeyRound aria-hidden className="size-4" />
              {t('oidc.login.button', { name: a.label })}
            </a>
          ))}
        </div>
      ),
    passkeySignIn: () => (
      <div>
        <Button
          type="button"
          variant="primary"
          loading={laeuft}
          disabled={!passkeyMoeglich()}
          iconLeft={<Fingerprint className="size-4" />}
          onClick={mitPasskey}
        >
          {t('account.passkeySignIn')}
        </Button>
      </div>
    ),
    factorRequired: () => <p className="mb-0 text-[13px] text-fg-2">{t('account.factorRequired')}</p>,
    /* Einrichten geht auf der Anmeldeseite weiter (die halbe Sitzung steht schon); einen Passkey legt nexmail erst
       nach der Anmeldung an, unter Sicherheit. */
    totpSetup: () => (
      <div>
        <Button type="button" variant="primary" onClick={() => window.location.assign(appPfad('/?schritt=einrichten'))}>
          {t('account.totpSetup')}
        </Button>
      </div>
    ),
    // Den Hinweis zu den Codes sagt `CodesZeigen` selbst, gleich darunter.
    recoveryCodesHint: () => null,
    recoveryCodes: () => <CodesZeigen codes={codes} benutzername={ich.benutzername} aufFertig={fertig} />,
  }

  return (
    <Dialog open title={t('account.sessionExpired')} onClose={() => undefined} abweisbar={false}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          wiederAnmelden()
        }}
      >
        {sessionExpiredParts(next).map((teil) => (
          <div key={teil} className="contents">
            {teile[teil]?.()}
          </div>
        ))}
        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}
      </form>
    </Dialog>
  )
}
