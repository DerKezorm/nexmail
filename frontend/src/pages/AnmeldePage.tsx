/* Anmelden — zwei Schritte, wie im Server.
 *
 * Kennwort → Code. Dazu zwei Nebenwege, die beide schon einmal jemandem den
 * Zugang gerettet haben:
 *
 *   • **Wiederherstellungscode**, wenn das Telefon weg ist.
 *   • **Einrichtung nachholen**, wenn die App nie eingerichtet wurde. Ohne
 *     diesen Weg wäre ein Konto tot, obwohl niemand etwas falsch gemacht hat.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { appPfad } from '../lib/basis'
import { Torbogen } from '../components/Torbogen'
import { Button, Input } from '../ds'
import { Meldung } from './EinrichtungPage'
import { ApiFehler, api } from '../api/client'
import { servermeldung } from '../lib/servermeldung'
import type { Einrichtung, Schritt } from '../api/client'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'

type Lage = 'passwort' | 'code' | 'wiederherstellung' | 'einrichten'

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
     Code, wie nach dem Kennwort. */
  const [lage, setLage] = useState<Lage>(() =>
    new URLSearchParams(window.location.search).get('schritt') === 'code' ? 'code' : 'passwort',
  )
  const [benutzername, setBenutzername] = useState('')
  const [passwort, setPasswort] = useState('')
  const [code, setCode] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [einrichtung, setEinrichtung] = useState<Einrichtung | null>(null)

  /* Anmelde-Anbieter.
     Leer heißt: Es gibt keine, und dann steht hier nichts. Ist die Anmeldung
     mit Passwort aus, stehen nur die Knöpfe da und klein der Weg für den
     Betreiber, der sich immer mit Passwort anmelden kann. */
  const [seite, setSeite] = useState<{ providers: Array<{ slug: string; label: string }>; password: boolean }>({
    providers: [],
    password: true,
  })
  const [betreiberWeg, setBetreiberWeg] = useState(false)
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

  async function schritt(aufruf: () => Promise<Schritt>) {
    setFehler('')
    setLaeuft(true)
    try {
      const antwort = await aufruf()
      if (antwort.schritt === 'fertig') aufFertig()
      else if (antwort.schritt === 'einrichten') setLage('einrichten')
      else setLage('code')
    } catch (f) {
      setFehler(deuten(f))
    } finally {
      setLaeuft(false)
    }
  }

  // --- Schritt 1: Kennwort --------------------------------------------- //

  /* Das Formular steht da, solange die Anmeldung mit Passwort an ist, es keinen
     Anbieter gibt oder der Betreiber seinen Weg geöffnet hat. */
  const passwortformDa = seite.password || betreiberWeg || seite.providers.length === 0

  if (lage === 'passwort') {
    return (
      <Torbogen titel={t('anmeldung.titel')} modus={modus} aufModus={aufModus}>
        {oidcFehler && (
          <div className="mb-4">
            <Meldung text={oidcFehler} />
          </div>
        )}
        {passwortformDa && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void schritt(() =>
              api.senden<Schritt>('/api/auth/anmelden', {
                benutzername: benutzername.trim(),
                passwort,
              }),
            )
          }}
          className="flex flex-col gap-4"
        >
          <Input
            label={t('anmeldung.benutzername')}
            value={benutzername}
            autoFocus
            autoComplete="username"
            onChange={(e) => setBenutzername(e.target.value)}
          />
          <Input
            label={t('anmeldung.passwort')}
            type="password"
            value={passwort}
            autoComplete="current-password"
            onChange={(e) => setPasswort(e.target.value)}
          />
          {fehler && <Meldung text={fehler} />}
          <Button
            type="submit"
            variant="primary"
            size="lg"
            fullWidth
            loading={laeuft}
            disabled={!benutzername || !passwort}
          >
            {t('anmeldung.weiter')}
          </Button>
          {/* ⚠️ **Hier und nirgends sonst.** Wer sein Kennwort vergessen hat,
              kommt nicht bis in ein Menü. */}
          <button
            type="button"
            onClick={aufVergessen}
            className="mx-auto text-[13px] text-fg-3 underline underline-offset-2 hover:text-fg-1"
          >
            {t('kennwort.vergessen_link')}
          </button>
        </form>
        )}
        {passwortformDa && seite.providers.length > 0 && (
          <div className="my-5 flex items-center gap-3 text-[12px] text-fg-4" aria-hidden>
            <span className="h-px flex-1 bg-line-subtle" />
            {t('oidc.login.or')}
            <span className="h-px flex-1 bg-line-subtle" />
          </div>
        )}
        {/* ⚠️ **Ein gewöhnlicher Verweis, kein fetch.** Der Hinweg ist eine
            Browser-Weiterleitung zum Anbieter; ein Aufruf im Hintergrund
            landete an einer fremden Adresse und käme nie zurück. */}
        {seite.providers.length > 0 && (
          <div className="flex flex-col gap-2" data-testid="anmelde-knoepfe">
            {seite.providers.map((a) => (
              <a
                key={a.slug}
                href={appPfad(`/api/oidc/${encodeURIComponent(a.slug)}/start`)}
                className="flex h-[var(--control-h-lg)] items-center justify-center gap-2 rounded-md border border-line bg-surface-2 text-sm font-medium text-fg-1 no-underline transition-colors duration-[var(--dur-fast)] hover:border-accent"
              >
                <KeyRound aria-hidden className="size-4" />
                {t('oidc.login.button', { name: a.label })}
              </a>
            ))}
          </div>
        )}
        {!passwortformDa && (
          <button
            type="button"
            onClick={() => setBetreiberWeg(true)}
            className="mx-auto mt-5 block text-[12px] text-fg-4 underline underline-offset-2 hover:text-fg-1"
          >
            {t('oidc.login.operator')}
          </button>
        )}
      </Torbogen>
    )
  }

  // --- Nachträgliche Einrichtung des zweiten Faktors -------------------- //

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
                <p className="mb-1 text-[12px] font-semibold tracking-[0.06em] text-fg-4 uppercase">
                  {t('einrichtung.geheimnis_abtippen')}
                </p>
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
            <Input
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
            <Button
              type="submit"
              variant="primary"
              size="lg"
              fullWidth
              loading={laeuft}
              disabled={code.length !== 6}
            >
              {t('einrichtung.fertigstellen')}
            </Button>
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
        <Input
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

        <Button
          type="submit"
          variant="primary"
          size="lg"
          fullWidth
          loading={laeuft}
          disabled={mitCode ? code.length !== 6 : code.length < 10}
        >
          {t('anmeldung.anmelden')}
        </Button>

        <button
          type="button"
          onClick={() => {
            setCode('')
            setFehler('')
            setLage(mitCode ? 'wiederherstellung' : 'code')
          }}
          className="rounded-sm py-1 text-[13px] text-fg-3 transition-colors duration-[var(--dur-fast)] hover:text-accent-text"
        >
          {mitCode ? t('anmeldung.wiederherstellung_zeigen') : t('anmeldung.zurueck_zum_code')}
        </button>
      </form>
    </Torbogen>
  )
}
