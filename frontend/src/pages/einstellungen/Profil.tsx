/* Einstellungen → Profil, seit konten 0.3.6 ganz aus dem Kontenmodul (`PAGES.profile`): Bild, Anzeigename,
 * Benutzername, E-Mail, angebotene Adresse, Sprache, klein die Rolle; Überschriften, Hinweise und Knöpfe sind die
 * Wortlaute des Moduls, die Felder stehen untereinander. Danach nexmails eigener Teil „Abmelden“ (`pageOrder`).
 *
 * ⚠️ **Die E-Mail ist die Adresse des Kontos** (`kontaktadresse`), nicht eines der Postfächer. Ändern nur mit dem
 * Passwort; mit Postausgang gilt die neue erst nach ihrem Link, bis dahin die alte.
 * ⚠️ **Ohne sie gibt es keinen Weg zurück** nach einem vergessenen Passwort, außer über den Betreiber. Deshalb steht
 * die Warnung direkt unter dem Feld, sobald sie leer ist.
 * ⚠️ **Der Benutzername wird direkt im Feld geändert** (kein „Bearbeiten“).
 * ⚠️ **Ein Knopf „Speichern“ für Anzeigename, Benutzername und E-Mail** (konten 0.3.7, `PAGES.profile.saveButton`), nie
 * beim Verlassen eines Felds. Ist Benutzername oder E-Mail geändert (`confirmOnSave`), fragt er vorher einmal das
 * Passwort.
 *
 * ⚠️ **Die Sprache hängt seit dem Kontenmodul am Konto** und reist mit auf jedes Gerät (wie nexnotes).
 */
import { LogOut, ShieldAlert, UserRound } from 'lucide-react'
import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Ich } from '../../api/client'
import { Profilbild } from '../../components/Profilbild'
import { useNachfrage } from '../../components/Nachfrage'
import { Button, Input, Select } from '../../ds'
import { SPRACHEN, spracheSetzen, type Sprachcode } from '../../i18n'
import { servermeldung } from '../../lib/servermeldung'
import {
  DISPLAY_NAME_MAX,
  EMAIL_MAX,
  PAGES,
  pageOrder,
  USERNAME_MAX,
  type PagePart,
} from '../../vendor/nexkonten/konten'
import { Karte } from './Karte'

/** nexmails eigene Teile des Profils, nach denen des Moduls. */
export const PROFIL_EIGENE = ['signOut'] as const
export const PROFIL_TEILE = pageOrder('profile', PROFIL_EIGENE)

function teil(name: string): PagePart {
  return PAGES.profile.parts.find((p: PagePart) => p.part === name) as PagePart
}

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
  const [benutzername, setBenutzername] = useState(ich?.benutzername ?? '')
  const [umbenannt, setUmbenannt] = useState(false)
  const [adresse, setAdresse] = useState(ich?.kontaktadresse ?? '')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [erledigt, setErledigt] = useState('')

  /* ⚠️ Nachziehen, wenn `ich` später eintrifft — beim ersten Rendern ist es
     null, und ein Feld, das dann leer bleibt, sähe aus wie „nichts gesetzt". */
  useEffect(() => {
    setName(ich?.anzeigename ?? '')
    setBenutzername(ich?.benutzername ?? '')
    setAdresse(ich?.kontaktadresse ?? '')
  }, [ich?.anzeigename, ich?.benutzername, ich?.kontaktadresse])

  if (!ich) return null
  const person = ich

  async function tun(aktion: () => Promise<unknown>, meldung: string): Promise<boolean> {
    setLaeuft(true)
    setFehler('')
    setErledigt('')
    try {
      await aktion()
      setErledigt(meldung)
      ichNeuLaden?.()
      return true
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return false
    } finally {
      setLaeuft(false)
    }
  }

  const nameNeu = name.trim() !== person.anzeigename
  const adresseNeu = adresse.trim().toLowerCase() !== (person.kontaktadresse ?? '').toLowerCase()
  const benutzernameNeu = benutzername.trim().toLowerCase() !== person.benutzername

  /** Das eigene Passwort, wo das Konto eins hat (Kontenmodul: Adresse und Benutzername nur damit). Ohne Passwort
   *  (nur über einen Anbieter): nichts zu fragen, der Server verlangt dann eine frische Anmeldung beim Anbieter. */
  async function passwortFragen(): Promise<string | null> {
    if (person.hat_kennwort === false) return ''
    const antwort = await fragen({
      titel: t('account.confirmWithPassword'),
      eingabe: { beschriftung: t('account.password'), typ: 'password' },
      knopf: t('account.save'),
    })
    return typeof antwort === 'string' && antwort ? antwort : null
  }

  /** „Speichern“ unter den drei Feldern: erst der Benutzername, dann Anzeigename und Adresse in einem Zug (der Server
   *  prüft den Namen vor der Adresse). Das Passwort einmal für beides, nur wenn eins davon geändert ist. */
  async function speichern() {
    const bestaetigen = PAGES.profile.confirmOnSave.some((feld) => (feld === 'username' ? benutzernameNeu : adresseNeu))
    const passwort = bestaetigen ? await passwortFragen() : ''
    if (passwort === null) return
    const neu = benutzername.trim().toLowerCase()
    const ok = await tun(
      async () => {
        if (benutzernameNeu) await api.aendern('/api/auth/ich/benutzername', { benutzername: neu, passwort })
        if (nameNeu || adresseNeu)
          await api.aendern('/api/auth/ich/profil', {
            anzeigename: name.trim(),
            ...(adresseNeu ? { kontaktadresse: adresse.trim(), passwort } : {}),
          })
      },
      benutzernameNeu ? t('account.usernameChanged', { username: neu }) : t('profil.gespeichert'),
    )
    if (ok && benutzernameNeu) setUmbenannt(true)
  }

  /** „Übernehmen“: wie eine Adressänderung, mit Passwort; mit Postausgang wartet sie danach auf ihren Link. */
  async function angeboteneNehmen() {
    const passwort = await passwortFragen()
    if (passwort === null) return
    await tun(() => api.senden('/api/auth/ich/angebotene-adresse', { passwort }), t('profil.gespeichert'))
  }

  const teile: Record<string, () => ReactNode> = {
    picture: () => {
      const p = teil('picture')
      return (
        <div className="flex flex-col gap-2" data-testid="profil-bild">
          {/* Wie nexnotes: Überschrift und Hinweis oben, darunter Bild und Knöpfe. */}
          <div>
            <h3 className="mb-0 text-sm font-medium text-fg-1">{t(p.title)}</h3>
            <p className="mt-0.5 mb-0 text-[12px] text-fg-3">{t(p.hint)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Profilbild id={person.id} name={person.anzeigename} stand={person.profilbild} groesse={64} />
            <div className="flex flex-wrap gap-2">
              {/* Ein Label als Knopf: Das Dateifeld selbst ist unsichtbar, der
                  Klick auf die Beschriftung öffnet die Auswahl. */}
              <label className="inline-flex h-[34px] cursor-pointer items-center rounded-md border border-line bg-surface-2 px-3 text-[13px] font-medium text-fg-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3">
                {t(p.buttons[0])}
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
                  onClick={() => void tun(() => api.loeschen('/api/auth/ich/profilbild'), t('profil.bild_entfernt'))}
                >
                  {t(p.buttons[1])}
                </Button>
              )}
            </div>
          </div>
        </div>
      )
    },
    displayName: () => (
      <Input
        label={t(teil('displayName').title)}
        hint={t(teil('displayName').hint)}
        value={name}
        maxLength={DISPLAY_NAME_MAX}
        autoComplete="name"
        placeholder={person.benutzername}
        onChange={(e) => setName(e.target.value)}
      />
    ),
    username: () => {
      const p = teil('username')
      return (
        <Input
          label={t(p.title)}
          // Beide Hinweise unter dem Feld (konten 0.3.7): wofür er ist und seine Regeln.
          hint={
            <>
              <span className="block">{umbenannt ? t('account.formerUsername') : t(p.hint)}</span>
              {p.rules && <span className="block">{t(p.rules)}</span>}
            </>
          }
          value={benutzername}
          maxLength={USERNAME_MAX}
          autoComplete="username"
          onChange={(e) => setBenutzername(e.target.value)}
        />
      )
    },
    email: () => {
      const p = teil('email')
      return (
        <div className="flex flex-col gap-2">
          <Input
            type="email"
            label={t(p.title)}
            hint={t(p.hint)}
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
          {!person.kontaktadresse && (
            <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft p-3 text-[12px] text-warning-text">
              <ShieldAlert className="mt-0.5 size-4 shrink-0" />
              <span>{t('sicherheit.kontaktadresse_fehlt')}</span>
            </div>
          )}
        </div>
      )
    },
    /* konten 0.3.3: Einem Konto mit Passwort bietet ein Anbieter seine Adresse nur an; seit 0.3.4 mit seinem Namen,
       „Nein, danke“ gilt für diese Adresse dauerhaft. */
    providerEmailOffer: () => {
      if (!person.angebotene_adresse || person.hat_kennwort === false) return null
      const p = teil('providerEmailOffer')
      return (
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
          <span className="flex-1">
            {t(p.title, {
              // Ohne Namen (ältere Angebote, Verknüpfung getrennt) steht die Domain der Adresse für den Anbieter.
              provider: person.angebotene_adresse_von || person.angebotene_adresse.split('@')[1],
            })}{' '}
            <span className="text-fg-2">{person.angebotene_adresse}</span>
          </span>
          <Button type="button" variant="ghost" disabled={laeuft} onClick={() => void angeboteneNehmen()}>
            {t(p.buttons[0])}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={laeuft}
            onClick={() => void tun(() => api.loeschen('/api/auth/ich/angebotene-adresse'), t('profil.gespeichert'))}
          >
            {t(p.buttons[1])}
          </Button>
        </div>
      )
    },
    language: () => (
      <Select
        label={t(teil('language').title)}
        value={i18n.language}
        onChange={(e) => {
          const code = e.target.value as Sprachcode
          void spracheSetzen(code)
          // Am Konto gemerkt, damit sie auf jedem Gerät gilt; scheitert das, bleibt sie in diesem Browser.
          void api.aendern('/api/auth/ich/sprache', { sprache: code }).then(() => ichNeuLaden?.(), () => undefined)
        }}
        options={SPRACHEN.map((s) => ({ value: s.code, label: s.name }))}
      />
    ),
    role: () => (
      <p className="mb-0 text-[12px] text-fg-3">
        {t(teil('role').title)}: {person.ist_betreiber ? t('profil.rolle_betreiber') : t('profil.rolle_benutzer')}
      </p>
    ),
  }

  const sichtbar = PROFIL_TEILE.filter((name) => name in teile)
  const gesichert = (name: string) => (PAGES.profile.saveFields as readonly string[]).includes(name)

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

      <Karte id="profil" symbol={UserRound} titel={t(PAGES.profile.title)}>
        {/* `layout: 'stacked'`: ein Teil unter dem anderen, auch auf breiten Bildschirmen. Die drei Felder, die
            „Speichern“ zusammen sichert (`saveFields`), stehen in einem Formular, der Knopf darunter. */}
        {sichtbar.map((name) =>
          !gesichert(name) ? (
            <Fragment key={name}>{teile[name]()}</Fragment>
          ) : name === sichtbar.find(gesichert) ? (
            <form
              key="speichern"
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault()
                void speichern()
              }}
            >
              {sichtbar.filter(gesichert).map((feld) => (
                <Fragment key={feld}>{teile[feld]()}</Fragment>
              ))}
              <div>
                <Button type="submit" variant="primary" disabled={laeuft || !benutzername.trim() || !(nameNeu || benutzernameNeu || adresseNeu)}>
                  {t(PAGES.profile.saveButton)}
                </Button>
              </div>
            </form>
          ) : null,
        )}
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
