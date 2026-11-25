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
 *
 * Seit 25.11.2026 nur aus dem gemeinsamen Bausatz (`vendor/nexui`, bauplaene/ui) wie in nexnotes: Bild als Kasten,
 * Knöpfe mit Art und Symbol aus `BUTTONS` (konten 0.3.8) über `AccountButton`.
 */
import { LogOut, UserRound } from 'lucide-react'
import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Ich } from '../../api/client'
import { AccountButton } from '../../components/AccountButton'
import { useAccountQuestion } from '../../components/AccountQuestion'
import { Profilbild } from '../../components/Profilbild'
import { SPRACHEN, spracheSetzen, type Sprachcode } from '../../i18n'
import { confirmOf } from '../../lib/accountButton'
import { servermeldung } from '../../lib/servermeldung'
import {
  DISPLAY_NAME_MAX,
  EMAIL_MAX,
  PAGES,
  pageOrder,
  screenFields,
  USERNAME_MAX,
  type PagePart,
} from '../../vendor/nexkonten/konten'
import { Box, Card, Field, Notice, SelectField } from '../../vendor/nexui'

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
  const { ask, dialog } = useAccountQuestion()
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
  async function passwortFragen(knopf: 'account.save' | 'account.providerEmailTake'): Promise<string | null> {
    if (person.hat_kennwort === false) return ''
    const antwort = await ask({
      title: t('account.confirmWithPassword'),
      field: { label: t('account.currentPassword'), type: 'password' },
      confirm: confirmOf(knopf, t(knopf)),
    })
    return typeof antwort === 'string' && antwort ? antwort : null
  }

  /** „Speichern“ unter den drei Feldern: erst der Benutzername, dann Anzeigename und Adresse in einem Zug (der Server
   *  prüft den Namen vor der Adresse). Das Passwort einmal für beides, nur wenn eins davon geändert ist. */
  async function speichern() {
    const bestaetigen = PAGES.profile.confirmOnSave.some((feld) => (feld === 'username' ? benutzernameNeu : adresseNeu))
    const passwort = bestaetigen ? await passwortFragen('account.save') : ''
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
    const passwort = await passwortFragen('account.providerEmailTake')
    if (passwort === null) return
    await tun(() => api.senden('/api/auth/ich/angebotene-adresse', { passwort }), t('profil.gespeichert'))
  }

  /** Die Hinweise unter einem Feld, je eine Zeile, per aria-describedby (konten 0.3.7, `screenFields`). */
  const hinweise = (feld: 'displayName' | 'username' | 'email') =>
    (screenFields('profile').find((eintrag) => eintrag.field === feld)?.hints ?? []).map((schluessel) => t(schluessel))

  const teile: Record<string, () => ReactNode> = {
    picture: () => {
      const p = teil('picture')
      return (
        <Box
          title={t(p.title)}
          hint={t(p.hint)}
          testId="profil-bild"
          actions={
            <>
              <AccountButton
                name="account.pictureUpload"
                accept="image/*"
                testId="profilbild"
                disabled={laeuft}
                onFile={(datei) => void tun(() => api.datei('/api/auth/ich/profilbild', datei), t('profil.bild_gespeichert'))}
              />
              {person.profilbild && (
                <AccountButton
                  name="account.pictureRemove"
                  disabled={laeuft}
                  onClick={() => void tun(() => api.loeschen('/api/auth/ich/profilbild'), t('profil.bild_entfernt'))}
                />
              )}
            </>
          }
        >
          <Profilbild id={person.id} name={person.anzeigename} stand={person.profilbild} groesse={56} />
        </Box>
      )
    },
    displayName: () => (
      <Field
        label={t(teil('displayName').title)}
        hints={hinweise('displayName')}
        value={name}
        maxLength={DISPLAY_NAME_MAX}
        autoComplete="name"
        placeholder={person.benutzername}
        onChange={(e) => setName(e.target.value)}
      />
    ),
    username: () => (
      <Field
        label={t(teil('username').title)}
        // Beide Hinweise unter dem Feld (konten 0.3.7): wofür er ist und seine Regeln.
        hints={umbenannt ? [...hinweise('username'), t('account.formerUsername')] : hinweise('username')}
        value={benutzername}
        maxLength={USERNAME_MAX}
        autoComplete="username"
        onChange={(e) => setBenutzername(e.target.value)}
      />
    ),
    email: () => (
      <>
        <Field
          type="email"
          label={t(teil('email').title)}
          hints={hinweise('email')}
          placeholder="name@example.com"
          value={adresse}
          maxLength={EMAIL_MAX}
          autoComplete="email"
          onChange={(e) => setAdresse(e.target.value)}
        />
        {/* Eine neue Adresse, die auf ihren Link wartet: bis dahin gilt die bisherige. */}
        {person.kontaktadresse_wartet && (
          <Box
            title={t('account.emailPending', { email: person.kontaktadresse_wartet })}
            testId="adresse-wartet"
            actions={
              <>
                <AccountButton
                  name="account.emailResend"
                  disabled={laeuft}
                  onClick={() =>
                    void tun(
                      () => api.senden('/api/auth/ich/kontaktadresse/nochmal', {}),
                      t('account.emailConfirmSent', { email: person.kontaktadresse_wartet }),
                    )
                  }
                />
                <AccountButton
                  name="account.emailWithdraw"
                  disabled={laeuft}
                  onClick={() => void tun(() => api.loeschen('/api/auth/ich/kontaktadresse/wartend'), t('profil.gespeichert'))}
                />
              </>
            }
          />
        )}
        {!person.kontaktadresse && <Notice tone="warn">{t('sicherheit.kontaktadresse_fehlt')}</Notice>}
      </>
    ),
    /* konten 0.3.3: Einem Konto mit Passwort bietet ein Anbieter seine Adresse nur an; seit 0.3.4 mit seinem Namen,
       „Nein, danke“ gilt für diese Adresse dauerhaft. */
    providerEmailOffer: () => {
      if (!person.angebotene_adresse || person.hat_kennwort === false) return null
      const p = teil('providerEmailOffer')
      return (
        <Box
          title={t(p.title, {
            // Ohne Namen (ältere Angebote, Verknüpfung getrennt) steht die Domain der Adresse für den Anbieter.
            provider: person.angebotene_adresse_von || person.angebotene_adresse.split('@')[1],
          })}
          hint={person.angebotene_adresse}
          testId="adresse-angebot"
          actions={
            <>
              <AccountButton name="account.providerEmailTake" disabled={laeuft} onClick={() => void angeboteneNehmen()} />
              <AccountButton
                name="account.providerEmailDismiss"
                disabled={laeuft}
                onClick={() => void tun(() => api.loeschen('/api/auth/ich/angebotene-adresse'), t('profil.gespeichert'))}
              />
            </>
          }
        />
      )
    },
    language: () => (
      <SelectField
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
      <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]">
        {t(teil('role').title)}: {person.ist_betreiber ? t('profil.rolle_betreiber') : t('profil.rolle_benutzer')}
      </p>
    ),
  }

  const sichtbar = PROFIL_TEILE.filter((name) => name in teile)
  const gesichert = (name: string) => (PAGES.profile.saveFields as readonly string[]).includes(name)

  return (
    <div className="flex flex-col gap-5">
      <div aria-live="polite" className="flex flex-col gap-2 empty:hidden">
        {fehler && <Notice tone="danger">{fehler}</Notice>}
        {erledigt && !fehler && <Notice tone="ok">{erledigt}</Notice>}
      </div>

      <Card id="profil" icon={UserRound} title={t(PAGES.profile.title)}>
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
                <AccountButton name="account.save" type="submit" disabled={laeuft || !benutzername.trim() || !(nameNeu || benutzernameNeu || adresseNeu)}>
                  {t(PAGES.profile.saveButton)}
                </AccountButton>
              </div>
            </form>
          ) : null,
        )}
      </Card>

      <Card id="abmelden" icon={LogOut} title={t('profil.abmelden_titel')} subtitle={t('profil.abmelden_text')}>
        <div>
          <AccountButton name="signOut" onClick={aufAbmelden}>
            {t('anmeldung.abmelden')}
          </AccountButton>
        </div>
      </Card>
      {dialog}
    </div>
  )
}
