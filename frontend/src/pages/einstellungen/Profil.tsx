/* Einstellungen → Profil, wie in nexnotes: Bild, Anzeigename, Benutzername, E-Mail, Sprache, darunter klein die
 * Rolle, und „Abmelden" (Kontenmodul, `SCREENS.profile`).
 *
 * ⚠️ **Die E-Mail ist die Adresse des Kontos** (`kontaktadresse`), nicht eines der Postfächer. Ändern nur mit dem
 * Passwort; mit Postausgang gilt die neue erst nach ihrem Link, bis dahin die alte.
 * ⚠️ **Ohne sie gibt es keinen Weg zurück** nach einem vergessenen Passwort, außer über den Betreiber. Deshalb steht
 * die Warnung direkt unter dem Feld, sobald sie leer ist.
 *
 * ⚠️ **Die Sprache hängt seit dem Kontenmodul am Konto** und reist mit auf jedes Gerät (wie nexnotes).
 */
import { LogOut, ShieldAlert, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Ich } from '../../api/client'
import { Profilbild } from '../../components/Profilbild'
import { useNachfrage } from '../../components/Nachfrage'
import { Button, Input, Select } from '../../ds'
import { SPRACHEN, spracheSetzen, type Sprachcode } from '../../i18n'
import { servermeldung } from '../../lib/servermeldung'
import { DISPLAY_NAME_MAX, EMAIL_MAX, USERNAME_MAX } from '../../vendor/nexkonten/konten'
import { Karte } from './Karte'

export function Profil({
  ich,
  ichNeuLaden,
  aufAbmelden,
}: {
  ich: Ich | null
  ichNeuLaden?: () => void
  aufAbmelden: () => void
}) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [name, setName] = useState(ich?.anzeigename ?? '')
  const [umbenannt, setUmbenannt] = useState(false)
  const [adresse, setAdresse] = useState(ich?.kontaktadresse ?? '')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [erledigt, setErledigt] = useState('')

  /* ⚠️ Nachziehen, wenn `ich` später eintrifft — beim ersten Rendern ist es
     null, und ein Feld, das dann leer bleibt, sähe aus wie „nichts gesetzt". */
  useEffect(() => {
    setName(ich?.anzeigename ?? '')
    setAdresse(ich?.kontaktadresse ?? '')
  }, [ich?.anzeigename, ich?.kontaktadresse])

  if (!ich) return null
  const person = ich

  async function tun(aktion: () => Promise<unknown>, meldung: string) {
    setLaeuft(true)
    setFehler('')
    setErledigt('')
    try {
      await aktion()
      setErledigt(meldung)
      ichNeuLaden?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  const unveraendert =
    name.trim() === person.anzeigename && adresse.trim() === (person.kontaktadresse ?? '')
  const adresseNeu = adresse.trim().toLowerCase() !== (person.kontaktadresse ?? '').toLowerCase()

  /** Das eigene Passwort, wo das Konto eins hat (Kontenmodul: Adresse und Benutzername nur damit). Ohne Passwort
   *  (nur über einen Anbieter): nichts zu fragen, der Server verlangt dann eine frische Anmeldung beim Anbieter. */
  async function passwortFragen(): Promise<string | null> {
    if (person.hat_kennwort === false) return ''
    const antwort = await fragen({
      titel: t('account.confirmWithPassword'),
      eingabe: { beschriftung: t('account.password'), typ: 'password' },
      knopf: t('aktion.speichern'),
    })
    return typeof antwort === 'string' && antwort ? antwort : null
  }

  async function speichern() {
    const passwort = adresseNeu ? await passwortFragen() : ''
    if (passwort === null) return
    await tun(
      () =>
        api.aendern('/api/auth/ich/profil', {
          anzeigename: name.trim(),
          kontaktadresse: adresse.trim(),
          passwort,
        }),
      t('profil.gespeichert'),
    )
  }

  async function benutzernameAendern() {
    const neu = await fragen({
      titel: t('account.username'),
      text: t('account.usernameRules'),
      eingabe: { beschriftung: t('account.username'), vorgabe: person.benutzername },
      knopf: t('aktion.weiter'),
    })
    if (typeof neu !== 'string' || !neu || neu === person.benutzername) return
    const passwort = await passwortFragen()
    if (passwort === null) return
    await tun(
      () => api.aendern('/api/auth/ich/benutzername', { benutzername: neu, passwort }),
      t('account.usernameChanged', { username: neu.trim().toLowerCase() }),
    )
    setUmbenannt(true)
  }

  return (
    <div className="flex flex-col gap-5">
      <div aria-live="polite">
        {fehler && (
          <p role="alert" className="mb-0 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-[13px] text-danger">
            {fehler}
          </p>
        )}
        {erledigt && !fehler && (
          <p className="mb-0 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-[13px] text-success">
            {erledigt}
          </p>
        )}
      </div>

      <Karte id="profil" symbol={UserRound} titel={t('einstellungen.bereiche.profil.titel')}>
        <div className="flex flex-wrap items-center gap-3" data-testid="profil-bild">
          <Profilbild id={person.id} name={person.anzeigename} stand={person.profilbild} groesse={64} />
          <div className="flex flex-wrap gap-2">
            {/* Ein Label als Knopf: Das Dateifeld selbst ist unsichtbar, der
                Klick auf die Beschriftung öffnet die Auswahl. */}
            <label className="inline-flex h-[34px] cursor-pointer items-center rounded-md border border-line bg-surface-2 px-3 text-[13px] font-medium text-fg-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3">
              {person.profilbild ? t('profil.bild_aendern') : t('profil.bild_hinzufuegen')}
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                data-testid="profilbild-datei"
                disabled={laeuft}
                onChange={(e) => {
                  const datei = e.target.files?.[0]
                  e.target.value = ''
                  if (datei)
                    void tun(() => api.datei('/api/auth/ich/profilbild', datei), t('profil.bild_gespeichert'))
                }}
              />
            </label>
            {person.profilbild && (
              <Button
                variant="ghost"
                disabled={laeuft}
                onClick={() =>
                  void tun(() => api.loeschen('/api/auth/ich/profilbild'), t('profil.bild_entfernt'))
                }
              >
                {t('profil.bild_entfernen')}
              </Button>
            )}
          </div>
        </div>

        {/* Felder und Reihenfolge aus dem Kontenmodul (`SCREENS.profile`): Anzeigename, Benutzername, E-Mail,
            Sprache. Der Benutzername ändert sich für sich (mit Passwort), die beiden anderen mit „Speichern“. */}
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void speichern()
          }}
        >
          <Input
            label={t('account.displayName')}
            hint={t('account.displayNameHint')}
            value={name}
            maxLength={DISPLAY_NAME_MAX}
            autoComplete="name"
            placeholder={person.benutzername}
            onChange={(e) => setName(e.target.value)}
          />
          <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
            <Input
              label={t('account.username')}
              hint={umbenannt ? t('account.formerUsername') : t('account.usernameHint')}
              value={person.benutzername}
              maxLength={USERNAME_MAX}
              readOnly
            />
            <Button type="button" disabled={laeuft} onClick={() => void benutzernameAendern()}>
              {t('aktion.bearbeiten')}
            </Button>
          </div>
          <Input
            type="email"
            label={t('account.email')}
            placeholder="name@example.com"
            value={adresse}
            maxLength={EMAIL_MAX}
            autoComplete="email"
            onChange={(e) => setAdresse(e.target.value)}
          />
          {/* Eine neue Adresse, die auf ihren Link wartet: bis dahin gilt die bisherige. */}
          {person.kontaktadresse_wartet && (
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
              <span className="flex-1">{t('account.emailPending', { email: person.kontaktadresse_wartet })}</span>
              <Button
                type="button"
                variant="ghost"
                disabled={laeuft}
                onClick={() =>
                  void tun(
                    () => api.senden('/api/auth/ich/kontaktadresse/nochmal', {}),
                    t('account.emailConfirmSent', { email: person.kontaktadresse_wartet }),
                  )
                }
              >
                {t('account.emailResend')}
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={laeuft}
                onClick={() => void tun(() => api.loeschen('/api/auth/ich/kontaktadresse/wartend'), t('profil.gespeichert'))}
              >
                {t('account.emailWithdraw')}
              </Button>
            </div>
          )}
          <div>
            <Button type="submit" variant="primary" disabled={laeuft || unveraendert}>
              {t('aktion.speichern')}
            </Button>
          </div>
        </form>

        <p className="mb-0 text-[12px] text-fg-3">
          {t('profil.rolle', {
            rolle: person.ist_betreiber ? t('profil.rolle_betreiber') : t('profil.rolle_benutzer'),
          })}
          {' · '}
          {t('account.emailHint')}
        </p>

        {!person.kontaktadresse && (
          <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft p-3 text-[12px] text-warning-text">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" />
            <span>{t('sicherheit.kontaktadresse_fehlt')}</span>
          </div>
        )}

        <Select
          label={t('account.language')}
          value={i18n.language}
          onChange={(e) => {
            const code = e.target.value as Sprachcode
            void spracheSetzen(code)
            // Am Konto gemerkt, damit sie auf jedem Gerät gilt; scheitert das, bleibt sie in diesem Browser.
            void api.aendern('/api/auth/ich/sprache', { sprache: code }).then(() => ichNeuLaden?.(), () => undefined)
          }}
          options={SPRACHEN.map((s) => ({ value: s.code, label: s.name }))}
        />
      </Karte>

      <Karte id="abmelden" symbol={LogOut} titel={t('profil.abmelden_titel')} text={t('profil.abmelden_text')}>
        <div>
          <Button iconLeft={<LogOut className="size-4" />} onClick={aufAbmelden}>
            {t('anmeldung.abmelden')}
          </Button>
        </div>
      </Karte>
      {nachfrage}
    </div>
  )
}
