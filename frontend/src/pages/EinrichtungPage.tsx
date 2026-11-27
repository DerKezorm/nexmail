/* Die erste Einrichtung: ein Schritt, das Konto des Betreibers.
 *
 * Bis 01.09.2026 kam danach ein zweiter Schritt mit QR-Code und
 * Wiederherstellungscodes. Der zweite Faktor ist seitdem freiwillig und wird
 * unter Einstellungen → Sicherheit eingeschaltet; „Schritt 1 von 2" stand
 * trotzdem noch bis 0.22.2 über dem Formular.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Torbogen } from '../components/Torbogen'
import { AccountButton } from '../components/AccountButton'
import { Field, Notice } from '../vendor/nexui'
import { api } from '../api/client'
import type { KontoAntwort } from '../api/client'
import { servermeldung } from '../lib/servermeldung'
import {
  DISPLAY_NAME_MAX,
  EMAIL_MAX,
  PASSWORD_MIN,
  SETUP_PAGE,
  USERNAME_MAX,
  followUsername,
  setupNotes,
  usernameProblem,
} from '../vendor/nexkonten/konten'
import { UpdateSetupRow } from '../vendor/nexupdates/UpdateSetupRow'

interface Props {
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  aufFertig: () => void
}

export function EinrichtungPage({ modus, aufModus, aufFertig }: Props) {
  const { t, i18n } = useTranslation()

  const [code, setCode] = useState('')
  const [anzeigename, setAnzeigename] = useState('')
  /* Der Benutzername folgt dem Anzeigenamen (Vorschlag des Moduls), bis man ihn selbst anfasst. */
  const [name, setName] = useState({ touched: false, username: '' })
  const benutzername = followUsername(name, anzeigename)
  const [adresse, setAdresse] = useState('')
  const [passwort, setPasswort] = useState('')
  const [wiederholung, setWiederholung] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  /* „Nach neuen Versionen sehen" (Modul updates, U1): einmal gefragt, vorbelegt an; später unter Über nexmail. */
  const [updates, setUpdates] = useState(true)

  async function kontoAnlegen(e: React.FormEvent) {
    e.preventDefault()
    setFehler('')
    if (passwort !== wiederholung) {
      setFehler(t('account.passwordMismatch'))
      return
    }
    setLaeuft(true)
    try {
      await api.senden<KontoAntwort>('/api/setup/konto', {
        einrichtungscode: code.trim(),
        anzeigename: anzeigename.trim(),
        benutzername: benutzername.trim(),
        kontaktadresse: adresse.trim(),
        passwort,
        // Still aus dem Browser, kein Feld (Kontenmodul); geändert wird sie im Profil.
        sprache: i18n.language,
        update_check: updates,
      })
      /* ⚠️ **Hier ist der Assistent zu Ende** (01.09.2026). Den zweiten Faktor schaltet jeder selbst ein, unter
         Einstellungen → Sicherheit. */
      aufFertig()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  // Der eine Satz, der den gesperrten Knopf erklärt, in der Reihenfolge der Felder: Er zeigt immer auf das nächste
  // fehlende und springt nicht hin und her.
  const grund = !code.trim()
    ? t('einrichtung.grund_code')
    : !anzeigename.trim()
      ? t('account.error.display_name_empty')
      : usernameProblem(benutzername)
        ? t('account.usernameRules')
        : passwort.length < PASSWORD_MIN
          ? t('einrichtung.grund_kennwort_lang', { fehlen: PASSWORD_MIN - passwort.length })
          : passwort !== wiederholung
            ? t('account.passwordMismatch')
            : ''

  return (
    <Torbogen
      titel={t(SETUP_PAGE.title)}
      untertitel={t(SETUP_PAGE.subtitle)}
      modus={modus}
      aufModus={aufModus}
    >
      {/* konten 0.3.6: Unter dem Passwort kein Satz über den zweiten Faktor; nur wo der Betreiber ihn verlangt, sagt
          es `setupNotes` (beim ersten Konto ist der Schalter noch aus). */}
      {setupNotes().map((note) => (
        <p key={note} className="m-0 text-sm">
          {t(note)}
        </p>
      ))}
      {/* Felder und Reihenfolge aus dem Kontenmodul (`SCREENS.setup`), gleich in jeder nex-App. */}
      <form onSubmit={kontoAnlegen} className="flex flex-col gap-4">
        <Field
          label={t('account.setupCode')}
          hints={[t('account.setupCodeHint')]}
          value={code}
          autoFocus
          autoComplete="off"
          onChange={(e) => setCode(e.target.value)}
        />
        <Field
          label={t('account.displayName')}
          hints={[t('account.displayNameHint')]}
          value={anzeigename}
          autoComplete="name"
          maxLength={DISPLAY_NAME_MAX}
          onChange={(e) => setAnzeigename(e.target.value)}
        />
        <Field
          label={t('account.username')}
          hints={[t('account.usernameHint')]}
          error={benutzername && usernameProblem(benutzername) ? t('account.usernameRules') : undefined}
          value={benutzername}
          autoComplete="username"
          maxLength={USERNAME_MAX}
          onChange={(e) => setName({ touched: true, username: e.target.value })}
        />
        <Field
          type="email"
          label={t('account.email')}
          hints={[t('account.emailHint')]}
          value={adresse}
          autoComplete="email"
          maxLength={EMAIL_MAX}
          onChange={(e) => setAdresse(e.target.value)}
        />
        {/* ⚠️ **Der Grund gehört an das Feld, nicht unter das Formular.** Ein Hinweis, den man erst zuordnen muss,
            ist keiner. */}
        <Field
          label={t('account.newPassword')}
          hints={[t('account.passwordRules')]}
          error={
            passwort && passwort.length < PASSWORD_MIN
              ? t('einrichtung.grund_kennwort', { fehlen: PASSWORD_MIN - passwort.length })
              : undefined
          }
          type="password"
          value={passwort}
          autoComplete="new-password"
          onChange={(e) => setPasswort(e.target.value)}
        />
        <Field
          label={t('account.passwordRepeat')}
          type="password"
          value={wiederholung}
          autoComplete="new-password"
          error={wiederholung && passwort !== wiederholung ? t('account.passwordMismatch') : undefined}
          onChange={(e) => setWiederholung(e.target.value)}
        />

        <UpdateSetupRow app="nexmail" checked={updates} onChange={setUpdates} language={i18n.language} bell={false} devices />

        {fehler && <Meldung text={fehler} />}

        {/* ⚠️ **Ein gesperrter Knopf muss sagen, warum.** */}
        {grund && <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{grund}</p>}

        <AccountButton name="setupSubmit" type="submit" wide busy={laeuft} disabled={Boolean(grund)}>
          {t('einrichtung.weiter')}
        </AccountButton>
      </form>
    </Torbogen>
  )
}

export function Meldung({ text }: { text: string }) {
  return <Notice tone="danger">{text}</Notice>
}
