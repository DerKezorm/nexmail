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

type Lage = 'passwort' | 'code' | 'wiederherstellung' | 'einrichten'

interface Props {
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufFertig: () => void
}

export function AnmeldePage({ modus, aufModus, aufFertig }: Props) {
  const { t, i18n } = useTranslation()

  const [lage, setLage] = useState<Lage>('passwort')
  const [benutzername, setBenutzername] = useState('')
  const [passwort, setPasswort] = useState('')
  const [code, setCode] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [einrichtung, setEinrichtung] = useState<Einrichtung | null>(null)

  /* Anmelde-Anbieter. Leer heißt: Es gibt keine, und dann steht hier nichts.
     ⚠️ **Ab Werk ändert sich nichts** — wer nie einen Anbieter einrichtet,
     merkt von OIDC nichts. */
  const [anbieter, setAnbieter] = useState<Array<{ kuerzel: string; anzeigename: string }>>([])
  useEffect(() => {
    api
      .holen<Array<{ kuerzel: string; anzeigename: string }>>('/api/oidc/knoepfe')
      .then(setAnbieter)
      .catch(() => undefined)
  }, [])

  /* ⚠️ **Der Rückweg meldet sich über die Adresse.** Er ist eine
     Browser-Weiterleitung, keine API-Antwort; der Grund steht als Kennung in
     der Adresse, und die Übersetzung dazu liegt hier. Danach wird sie aus dem
     Verlauf geräumt — sonst steht der Fehler beim nächsten Neuladen wieder da. */
  const [oidcFehler, setOidcFehler] = useState('')
  useEffect(() => {
    const kennung = new URLSearchParams(window.location.search).get('oidc_fehler')
    if (!kennung) return
    /* ⚠️ **Gefragt wird der Katalog, nicht eine Liste im Code.** Bis zum
       03.09.2026 standen hier drei Kennungen fest eingetragen; der Server
       nennt aber zwölf. Die übrigen neun fielen alle auf „Die Anmeldung über
       den Anbieter hat nicht geklappt" zurück — ein Satz, der den Betreiber
       nichts wissen lässt, obwohl der Server es genau wusste. Eine Liste im
       Code altert lautlos: Wer eine Kennung ergänzt, denkt an sie nicht. */
    const schluessel = `oidc.fehler_${kennung}`
    setOidcFehler(t(i18n.exists(schluessel) ? schluessel : 'oidc.fehler_allgemein'))
    window.history.replaceState(null, '', appPfad('/'))
  }, [t, i18n])

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

  if (lage === 'passwort') {
    return (
      <Torbogen titel={t('anmeldung.titel')} modus={modus} aufModus={aufModus}>
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
          {oidcFehler && <Meldung text={oidcFehler} />}
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
        </form>

        {/* ⚠️ **Ein gewöhnlicher Verweis, kein fetch.** Der Hinweg ist eine
            Browser-Weiterleitung zum Anbieter; ein Aufruf im Hintergrund
            landete an einer fremden Adresse und käme nie zurück. */}
        {anbieter.length > 0 && (
          <div className="mt-5 flex flex-col gap-2 border-t border-line-subtle pt-5">
            {anbieter.map((a) => (
              <a
                key={a.kuerzel}
                href={appPfad(`/api/oidc/${a.kuerzel}/start`)}
                className="flex h-[var(--control-h-lg)] items-center justify-center gap-2 rounded-md border border-line bg-surface-2 text-sm font-medium text-fg-1 no-underline transition-colors duration-[var(--dur-fast)] hover:border-accent"
              >
                <KeyRound aria-hidden className="size-4" />
                {t('oidc.anmelden_mit', { name: a.anzeigename })}
              </a>
            ))}
          </div>
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
