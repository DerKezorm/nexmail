/* Die Seite hinter dem Link aus der Einladungsmail.
 *
 * ⚠️ **Die einzige Seite, die ohne Anmeldung etwas anlegt.** Wer hier landet,
 * hat noch kein Konto — der Schlüssel aus der Mail ist der ganze Nachweis.
 *
 * ⚠️ **Ein Passwort und sonst nichts.** Kein zweiter Faktor, kein
 * Postfach-Assistent, keine Tour. Das ist die erste Minute, die jemand mit
 * nexmail verbringt; alles, was hier steht, muss er beantworten können, ohne
 * etwas zu wissen. Den zweiten Faktor schaltet er später selbst ein.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { api } from '../api/client'
import { appPfad } from '../lib/basis'
import { Torbogen } from '../components/Torbogen'
import { Button, Input } from '../ds'
import { Meldung } from './EinrichtungPage'
import { servermeldung } from '../lib/servermeldung'
import {
  DISPLAY_NAME_MAX,
  EMAIL_MAX,
  PASSWORD_MIN,
  USERNAME_MAX,
  followUsername,
  suggestUsername,
  usernameProblem,
} from '../vendor/nexkonten/konten'

interface Vorschau {
  /** Vorschlag, oder der Name einer Einladung von vorher (sie behält ihn). */
  benutzername: string
  anzeigename: string
  /** Die Adresse der Einladung, vorbelegt. */
  kontaktadresse?: string
  min_passwort?: number
  /** Aus („Anmeldung mit Passwort“ in der Verwaltung): nur „Weiter mit …“. */
  passwort?: boolean
}

export function EinladungPage({
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
  const [vorschau, setVorschau] = useState<Vorschau | null>(null)
  const [hinfaellig, setHinfaellig] = useState('')
  const [anzeigename, setAnzeigename] = useState('')
  const [name, setName] = useState({ touched: false, username: '' })
  const benutzername = followUsername(name, anzeigename)
  const [adresse, setAdresse] = useState('')
  const [passwort, setPasswort] = useState('')
  const [wiederholung, setWiederholung] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  /* Die Anbieter, über die man die Einladung auch annehmen kann.
     ⚠️ **Der Schlüssel fährt mit**, per POST, nicht in der Adresse. Bis zum
     09.10.2026 fand nexmail die Einladung über die bestätigte Adresse beim
     Anbieter; Entra schickt keine Bestätigung, und in authentik kann jeder
     seine Adresse selbst ändern. */
  const [anbieter, setAnbieter] = useState<Array<{ slug: string; label: string }>>([])
  const [unterwegs, setUnterwegs] = useState('')
  const [anbieterFehler, setAnbieterFehler] = useState('')

  async function mitAnbieter(kuerzel: string) {
    setAnbieterFehler('')
    setUnterwegs(kuerzel)
    try {
      const { ziel } = await api.senden<{ ziel: string }>(
        `/api/oidc/${encodeURIComponent(kuerzel)}/einladung`,
        { schluessel },
      )
      // Das Ziel ist der Anbieter oder, bei einem Fehler davor, die eigene
      // Anmeldeseite mit `?error=`. Beides ist eine ganze Navigation.
      window.location.assign(ziel)
    } catch (f) {
      setAnbieterFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      setUnterwegs('')
    }
  }
  useEffect(() => {
    api
      .holen<Array<{ slug: string; label: string }>>('/api/oidc/providers')
      .then(setAnbieter)
      .catch(() => undefined)
  }, [])

  const holen = useCallback(async () => {
    try {
      const v = await api.holen<Vorschau>(`/api/einladung/${encodeURIComponent(schluessel)}`)
      setVorschau(v)
      setAnzeigename(v.anzeigename)
      setAdresse(v.kontaktadresse ?? '')
      /* Ein Name, den der Server anders vorschlägt als der Anzeigename ergäbe (der einer Einladung von vorher, oder
         ein nummerierter), bleibt stehen; sonst folgt er dem Anzeigenamen. */
      setName({ touched: v.benutzername !== suggestUsername(v.anzeigename), username: v.benutzername })
    } catch (f) {
      setHinfaellig(
        servermeldung(f, t('einladung.ungueltig_fallback')),
      )
    }
  }, [schluessel, t])

  useEffect(() => {
    void holen()
  }, [holen])

  async function annehmen(e: React.FormEvent) {
    e.preventDefault()
    setFehler('')
    if (passwort !== wiederholung) {
      setFehler(t('account.passwordMismatch'))
      return
    }
    setLaeuft(true)
    try {
      await api.senden(`/api/einladung/${encodeURIComponent(schluessel)}`, {
        anzeigename: anzeigename.trim(),
        benutzername: benutzername.trim(),
        kontaktadresse: adresse.trim(),
        passwort,
      })
      // ⚠️ Die Adresse aufräumen, bevor die App startet: Sonst steht der
      // Schlüssel weiter im Verlauf des Browsers und im Verlaufsspeicher.
      // ⚠️ Mit Vorbau — sonst springt der Browser aus der Anwendung heraus
      // auf die Wurzel der Domain.
      window.history.replaceState(null, '', appPfad('/'))
      aufFertig()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  if (hinfaellig) {
    return (
      <Torbogen
        marke="nexmail"
        titel={t('einladung.ungueltig_titel')}
        untertitel={hinfaellig}
        modus={modus}
        aufModus={aufModus}
      >
        <Button
          fullWidth
          onClick={() => {
            window.history.replaceState(null, '', appPfad('/'))
            aufFertig()
          }}
        >
          {t('einladung.zur_anmeldung')}
        </Button>
      </Torbogen>
    )
  }

  if (!vorschau) {
    return <div className="h-full bg-canvas" />
  }

  /* ⚠️ Dieselben Sätze wie in der Ersteinrichtung — und dieselben Schlüssel.
     Beim ersten Anlauf standen hier drei erfundene Namen, und die Oberfläche
     zeigte roh „einrichtung.grund_passwort". */
  const mindestens = vorschau.min_passwort ?? PASSWORD_MIN
  const grund = !anzeigename.trim()
    ? t('account.error.display_name_empty')
    : usernameProblem(benutzername)
      ? t('account.usernameRules')
      : passwort.length < mindestens
        ? t('einrichtung.grund_kennwort_lang', { fehlen: mindestens - passwort.length })
        : passwort !== wiederholung
          ? t('account.passwordMismatch')
          : ''

  return (
    <Torbogen
      marke="nexmail"
      titel={vorschau.anzeigename ? t('einladung.titel', { name: vorschau.anzeigename }) : t('einladung.titel_ohne_name')}
      untertitel={t('einladung.untertitel')}
      modus={modus}
      aufModus={aufModus}
    >
      {vorschau.passwort !== false && (
      /* Felder und Reihenfolge aus dem Kontenmodul (`SCREENS.invite`): wie die Einrichtung, ohne Code. */
      <form onSubmit={annehmen} className="flex flex-col gap-4">
        <Input
          label={t('account.displayName')}
          hint={t('account.displayNameHint')}
          value={anzeigename}
          autoComplete="name"
          maxLength={DISPLAY_NAME_MAX}
          onChange={(e) => setAnzeigename(e.target.value)}
        />
        <Input
          label={t('account.username')}
          hint={t('account.usernameHint')}
          error={benutzername && usernameProblem(benutzername) ? t('account.usernameRules') : undefined}
          value={benutzername}
          autoComplete="username"
          maxLength={USERNAME_MAX}
          onChange={(e) => setName({ touched: true, username: e.target.value })}
        />
        <Input
          type="email"
          label={t('account.email')}
          hint={t('account.emailHint')}
          value={adresse}
          autoComplete="email"
          maxLength={EMAIL_MAX}
          onChange={(e) => setAdresse(e.target.value)}
        />
        <Input
          label={t('account.newPassword')}
          hint={t('account.passwordRules', { minimum: mindestens })}
          type="password"
          autoComplete="new-password"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
        />
        <Input
          label={t('account.passwordRepeat')}
          type="password"
          autoComplete="new-password"
          value={wiederholung}
          error={wiederholung && passwort !== wiederholung ? t('account.passwordMismatch') : undefined}
          onChange={(e) => setWiederholung(e.target.value)}
        />

        {fehler && <Meldung text={fehler} />}
        {/* ⚠️ Der Grund steht am Feld und nicht am gesperrten Knopf — sonst
            sucht man ihn dort, wo nichts passiert. */}
        {grund && <p className="-mt-1 text-[13px] text-fg-3">{grund}</p>}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          fullWidth
          loading={laeuft}
          disabled={Boolean(grund)}
        >
          {t('einladung.loslegen')}
        </Button>
      </form>
      )}

      {/* ⚠️ **Beide Wege nebeneinander, nicht statt einander.** Der Betreiber am
          01.09.2026: „nicht jeder hat ein authentik konto" — eben. Wer keins
          hat, vergibt ein Passwort wie bisher; wer eins hat, spart es sich und
          bekommt ein Konto **ohne** Passwort. Ein ungenutztes Passwort ist das,
          welches schwach ist. */}
      {anbieter.length > 0 && (
        <div className="mt-5 flex flex-col gap-2">
          {vorschau.passwort !== false && (
            <div className="mb-3 flex items-center gap-3 text-[12px] text-fg-4" aria-hidden>
              <span className="h-px flex-1 bg-line-subtle" />
              {t('account.or')}
              <span className="h-px flex-1 bg-line-subtle" />
            </div>
          )}
          {anbieter.map((a) => (
            <button
              key={a.slug}
              type="button"
              disabled={Boolean(unterwegs)}
              onClick={() => void mitAnbieter(a.slug)}
              className="flex h-[var(--control-h-lg)] items-center justify-center gap-2 rounded-md border border-line bg-surface-2 text-sm font-medium text-fg-1 transition-colors duration-[var(--dur-fast)] hover:border-accent disabled:opacity-60"
            >
              <KeyRound aria-hidden className="size-4" />
              {t('oidc.invite.button', { name: a.label })}
            </button>
          ))}
          {anbieterFehler && (
            <p role="alert" className="mb-0 text-center text-[13px] text-danger">
              {anbieterFehler}
            </p>
          )}
        </div>
      )}
    </Torbogen>
  )
}
