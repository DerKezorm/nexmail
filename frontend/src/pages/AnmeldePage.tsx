/* Anmelden — zwei Schritte, wie im Server.
 *
 * Passwort → Code. Dazu zwei Nebenwege, die beide schon einmal jemandem den
 * Zugang gerettet haben:
 *
 *   • **Wiederherstellungscode**, wenn das Telefon weg ist.
 *   • **Einrichtung nachholen**, wenn die App nie eingerichtet wurde. Ohne
 *     diesen Weg wäre ein Konto tot, obwohl niemand etwas falsch gemacht hat.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { appPfad } from '../lib/basis'
import { Torbogen } from '../components/Torbogen'
import { AccountButton } from '../components/AccountButton'
import { Checkbox, Field, OrLine, TextLink } from '../vendor/nexui'
import { Meldung } from './EinrichtungPage'
import { CodesZeigen } from '../components/ZweiterFaktor'
import { ApiFehler, api } from '../api/client'
import { servermeldung } from '../lib/servermeldung'
import type { Einrichtung, Schritt } from '../api/client'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'
import { EMAIL_MAX } from '../vendor/nexkonten/konten'
import { alsJson, anmeldeOptionen, passkeyMoeglich } from '../lib/passkey'

type Lage = 'passwort' | 'code' | 'wiederherstellung' | 'einrichten' | 'passkey' | 'codes'

interface Props {
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufFertig: () => void
  aufVergessen: () => void
}

export function AnmeldePage({ modus, aufModus, aufFertig, aufVergessen }: Props) {
  const { t } = useTranslation()

  /* Nach einem Anbieter, dem der Eintrag den zweiten Faktor nicht glaubt, kommt
     der Browser mit `?schritt=code` zurück: Die halbe Sitzung steht, jetzt der
     Code, wie nach dem Passwort. */
  const [lage, setLage] = useState<Lage>(() =>
    // Nach einem Anbieter: `?schritt=code` (Faktor vorhanden) oder `?schritt=einrichten` (Betreiber verlangt ihn).
    (() => {
      const schritt = new URLSearchParams(window.location.search).get('schritt')
      return schritt === 'code' || schritt === 'einrichten' || schritt === 'passkey' ? schritt : 'passwort'
    })(),
  )
  const [benutzername, setBenutzername] = useState('')
  const [passwort, setPasswort] = useState('')
  // „Angemeldet bleiben“ (Kontenmodul Teil 2), ab Werk an: 30 Tage, gleitend. Aus: Schluss mit dem Browser,
  // spätestens nach 12 Stunden.
  const [bleiben, setBleiben] = useState(true)
  const [code, setCode] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [einrichtung, setEinrichtung] = useState<Einrichtung | null>(null)
  // Nach dem Einrichten beim Anmelden: die Wiederherstellungscodes, einmal.
  const [codes, setCodes] = useState<string[]>([])

  /* Anmelde-Anbieter.
     Leer heißt: Es gibt keine, und dann steht hier nichts. Ist die Anmeldung
     mit Passwort aus, stehen nur die Knöpfe da und klein der Weg für den
     Betreiber, der sich immer mit Passwort anmelden kann. */
  const [seite, setSeite] = useState<{ providers: Array<{ slug: string; label: string }>; password: boolean }>({
    providers: [],
    password: true,
  })
  const [betreiberWeg, setBetreiberWeg] = useState(false)
  // „Mit Passkey anmelden“ (Kontenmodul Teil 2): nur, wenn der Betreiber sie erlaubt, nexmail unter https läuft und
  // der Browser sie kann.
  const [passkeyAn, setPasskeyAn] = useState(false)
  useEffect(() => {
    if (!passkeyMoeglich()) return
    api
      .holen<{ an: boolean }>('/api/auth/passkey')
      .then((s) => setPasskeyAn(s.an))
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    api
      .holen<{ providers: Array<{ slug: string; label: string }>; password: boolean }>('/api/oidc/anmeldeseite')
      .then(setSeite)
      .catch(() => undefined)
  }, [])

  /* ⚠️ **Der Rückweg meldet sich über die Adresse** (`/anmelden?error=<code>`).
     Er ist eine Browser-Weiterleitung, keine API-Antwort; der Satz zur Kennung
     kommt aus den Wortlauten des Anmeldemoduls (`oidc.error.*`), nie die rohe
     Kennung. Danach wird die Adresse aufgeräumt — sonst steht der Fehler beim
     nächsten Neuladen wieder da. */
  const [oidcFehler, setOidcFehler] = useState('')
  useEffect(() => {
    const abfrage = new URLSearchParams(window.location.search)
    const schluessel = oidcErrorKey(abfrage.get('error'))
    if (schluessel) setOidcFehler(t(schluessel))
    else if (abfrage.get('error')) setOidcFehler(t('anmeldung.fehler_allgemein'))
    if (abfrage.has('error') || abfrage.has('schritt') || window.location.pathname !== appPfad('/')) {
      window.history.replaceState(null, '', appPfad('/'))
    }
  }, [t])

  useEffect(() => {
    if (lage !== 'einrichten') return
    api
      .holen<Einrichtung>('/api/auth/einrichtung')
      .then(setEinrichtung)
      .catch(() => setLage('passwort'))
  }, [lage])

  function deuten(f: unknown): string {
    /* ⚠️ **Die Bremse hat Vorrang vor dem Katalog.** Sie trägt eine Zahl aus
       einer Kopfzeile, nicht aus dem Rumpf — „warte 43 Sekunden" lässt sich
       nicht als Kennung ausdrücken. */
    if (f instanceof ApiFehler && f.status === 429) {
      return t('anmeldung.zu_viele', { s: f.wartenSekunden ?? 60 })
    }
    return servermeldung(f, t('anmeldung.fehler_allgemein'))
  }

  async function mitPasskey() {
    await schritt(async () => {
      const optionen = await api.senden<Record<string, unknown>>('/api/auth/passkey/start', {})
      const antwort = await navigator.credentials.get({ publicKey: anmeldeOptionen(optionen) })
      if (!antwort) throw new Error('passkey_invalid')
      return api.senden<Schritt>('/api/auth/passkey', {
        credential: alsJson(antwort as PublicKeyCredential),
        angemeldet_bleiben: bleiben,
      })
    })
  }

  async function schritt(aufruf: () => Promise<Schritt>) {
    setFehler('')
    setLaeuft(true)
    try {
      const antwort = await aufruf()
      if (antwort.schritt === 'fertig' && antwort.weiter === 'show_codes' && antwort.codes?.length) {
        setCodes(antwort.codes)
        setLage('codes')
      } else if (antwort.schritt === 'fertig') aufFertig()
      else if (antwort.schritt === 'einrichten') setLage('einrichten')
      else if (antwort.schritt === 'passkey') setLage('passkey')
      else setLage('code')
    } catch (f) {
      setFehler(deuten(f))
    } finally {
      setLaeuft(false)
    }
  }

  // --- Schritt 1: Passwort --------------------------------------------- //

  /* Das Formular steht da, solange die Anmeldung mit Passwort an ist, es keinen
     Anbieter gibt oder der Betreiber seinen Weg geöffnet hat. */
  const passwortformDa = seite.password || betreiberWeg || seite.providers.length === 0

  if (lage === 'passwort') {
    return (
      <Torbogen titel={t('anmeldung.titel')} modus={modus} aufModus={aufModus}>
        {oidcFehler && <Meldung text={oidcFehler} />}
        {passwortformDa && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void schritt(() =>
              api.senden<Schritt>('/api/auth/anmelden', {
                benutzername: benutzername.trim(),
                passwort,
                angemeldet_bleiben: bleiben,
              }),
            )
          }}
          className="flex flex-col gap-4"
        >
          {/* Kontenmodul: „Benutzername oder E-Mail“; der Feldname zum Server bleibt `benutzername`. */}
          <Field
            label={t('account.login')}
            value={benutzername}
            autoFocus
            autoComplete="username"
            maxLength={EMAIL_MAX}
            onChange={(e) => setBenutzername(e.target.value)}
          />
          <Field
            label={t('account.password')}
            type="password"
            value={passwort}
            autoComplete="current-password"
            onChange={(e) => setPasswort(e.target.value)}
          />
          <Checkbox label={t('account.stayIn')} checked={bleiben} onChange={setBleiben} />
          {fehler && <Meldung text={fehler} />}
          <AccountButton name="signIn" type="submit" wide busy={laeuft} disabled={!benutzername || !passwort}>
            {t('anmeldung.weiter')}
          </AccountButton>
          {/* ⚠️ **Hier und nirgends sonst.** Wer sein Passwort vergessen hat,
              kommt nicht bis in ein Menü. */}
          <div className="text-center">
            <TextLink onClick={aufVergessen}>{t('account.forgot')}</TextLink>
          </div>
        </form>
        )}
        {passwortformDa && seite.providers.length > 0 && (
          <OrLine>{t('oidc.login.or')}</OrLine>
        )}
        {/* ⚠️ **Ein gewöhnlicher Verweis, kein fetch.** Der Hinweg ist eine
            Browser-Weiterleitung zum Anbieter; ein Aufruf im Hintergrund
            landete an einer fremden Adresse und käme nie zurück. */}
        {seite.providers.length > 0 && (
          <div className="flex flex-col gap-2" data-testid="anmelde-knoepfe">
            {seite.providers.map((a) => (
              <AccountButton key={a.slug} name="oidc.login.button" wide href={appPfad(`/api/oidc/${encodeURIComponent(a.slug)}/start`)}>
                {t('oidc.login.button', { name: a.label })}
              </AccountButton>
            ))}
          </div>
        )}
        {passkeyAn && (
          <AccountButton name="account.passkeySignIn" wide onClick={() => void mitPasskey()} />
        )}
        {!passwortformDa && (
          <div className="text-center">
            <TextLink onClick={() => setBetreiberWeg(true)}>{t('oidc.login.operator')}</TextLink>
          </div>
        )}
      </Torbogen>
    )
  }

  // --- Nachträgliche Einrichtung des zweiten Faktors -------------------- //

  if (lage === 'codes') {
    return (
      <Torbogen titel={t('einrichtung.codes_titel')} breit modus={modus} aufModus={aufModus}>
        <CodesZeigen codes={codes} benutzername={benutzername} aufFertig={aufFertig} />
      </Torbogen>
    )
  }

  // Ein Passkey ist der zweite Schritt (der Betreiber verlangt einen zweiten Faktor, das Konto hat einen Passkey).
  if (lage === 'passkey') {
    return (
      <Torbogen titel={t('account.secondFactor')} untertitel={t('account.passkeysHint')} modus={modus} aufModus={aufModus}>
        <div className="flex flex-col gap-4">
          {fehler && <Meldung text={fehler} />}
          <AccountButton name="account.passkeySignIn" wide busy={laeuft} disabled={!passkeyMoeglich()} onClick={() => void mitPasskey()} />
        </div>
      </Torbogen>
    )
  }

  if (lage === 'einrichten') {
    return (
      <Torbogen
        titel={t('anmeldung.faktor_fehlt_titel')}
        untertitel={t('anmeldung.faktor_fehlt_text')}
        breit
        modus={modus}
        aufModus={aufModus}
      >
        <div className="flex flex-col gap-5">
          {einrichtung && (
            <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
              <div
                className="shrink-0 rounded-lg bg-white p-2"
                dangerouslySetInnerHTML={{ __html: einrichtung.qr_svg }}
              />
              <div className="min-w-0 flex-1">
                <p className="m-0 mb-1 text-xs text-[var(--nexui-text-muted)]">{t('einrichtung.geheimnis_abtippen')}</p>
                <code className="block break-all rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-[13px] text-fg-1 select-all">
                  {einrichtung.geheimnis}
                </code>
              </div>
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault()
              void schritt(() => api.senden<Schritt>('/api/auth/code', { code: code.trim() }))
            }}
            className="flex flex-col gap-4"
          >
            <Field
              label={t('einrichtung.code_eingabe')}
              value={code}
              mono
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="000000"
              autoFocus
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            />
            {fehler && <Meldung text={fehler} />}
            <AccountButton name="confirm" type="submit" wide busy={laeuft} disabled={code.length !== 6}>
              {t('einrichtung.fertigstellen')}
            </AccountButton>
          </form>
        </div>
      </Torbogen>
    )
  }

  // --- Schritt 2: Code oder Wiederherstellung --------------------------- //

  const mitCode = lage === 'code'

  return (
    <Torbogen
      titel={mitCode ? t('anmeldung.code_titel') : t('anmeldung.wiederherstellung_titel')}
      untertitel={mitCode ? t('anmeldung.code_text') : t('anmeldung.wiederherstellung_text')}
      modus={modus}
      aufModus={aufModus}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void schritt(() =>
            api.senden<Schritt>(
              mitCode ? '/api/auth/code' : '/api/auth/wiederherstellung',
              { code: code.trim() },
            ),
          )
        }}
        className="flex flex-col gap-4"
      >
        <Field
          label={mitCode ? t('anmeldung.code_eingabe') : t('anmeldung.wiederherstellung_titel')}
          value={code}
          mono
          autoFocus
          inputMode={mitCode ? 'numeric' : 'text'}
          autoComplete="one-time-code"
          maxLength={mitCode ? 6 : 11}
          placeholder={mitCode ? '000000' : t('anmeldung.wiederherstellung_eingabe')}
          onChange={(e) =>
            setCode(mitCode ? e.target.value.replace(/\D/g, '') : e.target.value.toUpperCase())
          }
        />

        {fehler && <Meldung text={fehler} />}

        <AccountButton name="codeSubmit" type="submit" wide busy={laeuft} disabled={mitCode ? code.length !== 6 : code.length < 10}>
          {t('anmeldung.anmelden')}
        </AccountButton>

        <div className="text-center">
          <TextLink
            onClick={() => {
              setCode('')
              setFehler('')
              setLage(mitCode ? 'wiederherstellung' : 'code')
            }}
          >
            {mitCode ? t('anmeldung.wiederherstellung_zeigen') : t('anmeldung.zurueck_zum_code')}
          </TextLink>
        </div>
      </form>
    </Torbogen>
  )
}
