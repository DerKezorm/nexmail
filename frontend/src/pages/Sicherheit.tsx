/* Sicherheit — seit konten 0.3.6 ganz aus dem Kontenmodul (`PAGES.security`): Passwort, Zweiter Faktor („An“/„Aus“),
 * Wiederherstellungscodes, Passkeys, „Angemeldete Geräte“ mit „Überall sonst abmelden“, „Mail bei neuer Anmeldung“;
 * Überschriften, Hinweise und Knöpfe sind die Wortlaute des Moduls, die Teile stehen untereinander. Danach nexmails
 * eigene Teile: Anmeldeanbieter verknüpfen, Google- und Microsoft-Konten (`pageOrder`).
 *
 * Aufgebaut wie nexnotes, nur aus dem gemeinsamen Bausatz (`vendor/nexui`, bauplaene/ui; 25.11.2026): jeder Teil des
 * Moduls ein `Box` in EINER Karte „Sicherheit“ (auch das Passwort), die Anmeldeanbieter ein `Box` mit einer `Row` je
 * Anbieter in derselben Karte, Google und Microsoft danach als eigene Karte. Jeder Knopf mit Art und Symbol aus
 * `BUTTONS` (konten 0.3.8) über `AccountButton`.
 *
 * ⚠️ **Angemeldete Geräte gehören sichtbar und einzeln kündbar.** Genau
 * dafür liegen die Sitzungen im Server und nicht im Token: „Überall sonst
 * abmelden" wirkt sofort. Eine Anwendung, die alle Postfächer hält, muss
 * zeigen können, wer sie gerade offen hat.
 *
 * ⚠️ **Die Zahl der übrigen Wiederherstellungscodes steht hier.** Sonst
 * erfährt man sie erst, wenn keiner mehr da ist — und dann ist es zu spät.
 */
import { Fragment, useCallback, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Fingerprint, Monitor, ShieldCheck } from 'lucide-react'
import { api } from '../api/client'
import type { Ich } from '../api/client'
import { AccountButton } from '../components/AccountButton'
import { useAccountQuestion } from '../components/AccountQuestion'
import { Oauthzugaenge } from '../components/Oauthzugaenge'
import { Anmeldeanbieter } from '../components/Anmeldeanbieter'
import { CodesZeigen, ZweiterFaktor } from '../components/ZweiterFaktor'
import { PASSWORD_MIN } from '../vendor/nexkonten/konten'
import { confirmOf } from '../lib/accountButton'
import { servermeldung } from '../lib/servermeldung'
import { alsJson, anlegeOptionen, geraetename, passkeyMoeglich } from '../lib/passkey'
import { PAGES, pageOrder, passwordChanged, SECOND_FACTOR_STATE, type PagePart } from '../vendor/nexkonten/konten'
import { Badge, Box, Card, CheckboxRow, ConfirmDialog, Dialog, Field, Notice, Row, Rows } from '../vendor/nexui'

/** nexmails eigene Teile der Sicherheit, nach denen des Moduls. */
export const SICHERHEIT_EIGENE = ['providers', 'googleMicrosoft'] as const
export const SICHERHEIT_TEILE = pageOrder('security', SICHERHEIT_EIGENE)

/** In der Karte „Sicherheit“ stehen die Teile des Moduls und die Anmeldeanbieter; Google und Microsoft danach. */
const eigeneKarte = (name: string) => name === 'googleMicrosoft'

function teil(name: string): PagePart {
  return PAGES.security.parts.find((p: PagePart) => p.part === name) as PagePart
}

interface Passkey {
  uid: string
  name: string
  created_at: string
  last_used_at: string | null
}

interface Passkeys {
  erlaubt: boolean
  grund: string
  passkeys: Passkey[]
}

interface Geraet {
  id: string
  geraet: string
  adresse: string
  angelegt: string
  zuletzt_gesehen: string
  aktuell: boolean
}

/** Unter so vielen Wiederherstellungscodes wird gewarnt. */
const WENIGE_CODES = 3

export function Sicherheit({
  ich,
  ichNeuLaden,
}: {
  ich: Ich | null
  ichNeuLaden?: () => void
}) {
  const { t, i18n } = useTranslation()
  const { ask, dialog } = useAccountQuestion()
  const [geraete, setGeraete] = useState<Geraet[] | null>(null)
  const [fehler, setFehler] = useState('')

  const [passkeys, setPasskeys] = useState<Passkeys | null>(null)
  /** Tag und Uhrzeit wie in nexnotes („25.11.2026, 11:50“). */
  const zeitpunkt = (wann: string) =>
    new Date(wann).toLocaleString(i18n.language, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

  const laden = useCallback(async () => {
    setGeraete(await api.holen<Geraet[]>(`/api/sitzungen?sprache=${encodeURIComponent(i18n.language)}`))
    setPasskeys(await api.holen<Passkeys>('/api/auth/passkeys').catch(() => null))
  }, [i18n.language])

  useEffect(() => {
    void laden().catch(() => setGeraete([]))
  }, [laden])

  /** Das eigene Passwort für einen Schritt, der es verlangt; ein Konto ohne Passwort bestätigt mit der frischen
   *  Anmeldung beim Anbieter (der Server prüft das), dann wird nicht gefragt. */
  async function passwortFragen(knopf: 'account.passkeyAdd' | 'account.passkeyRemove' | 'account.recoveryCodesNew'): Promise<string | null> {
    if (ich && ich.hat_kennwort === false) return ''
    const kennwort = await ask({
      title: t(knopf),
      text: t('account.confirmWithPassword'),
      field: { label: t('account.currentPassword'), type: 'password' },
      confirm: confirmOf(knopf, t(knopf)),
    })
    return typeof kennwort === 'string' && kennwort ? kennwort : null
  }

  async function passkeyHinzufuegen() {
    const kennwort = await passwortFragen('account.passkeyAdd')
    if (kennwort === null) return
    const name = await ask({
      title: t('account.passkeyAdd'),
      field: { label: t('account.passkeyName'), initial: geraetename() },
      confirm: confirmOf('account.passkeyAdd', t('account.passkeyAdd')),
    })
    if (name === null) return
    await mit(async () => {
      const optionen = await api.senden<Record<string, unknown>>('/api/auth/passkeys/start', { passwort: kennwort })
      const antwort = await navigator.credentials.create({ publicKey: anlegeOptionen(optionen) })
      if (!antwort) return null
      return api.senden('/api/auth/passkeys', {
        credential: alsJson(antwort as PublicKeyCredential),
        name: typeof name === 'string' ? name.trim() : '',
      })
    })
  }

  async function mit<T>(tun: () => Promise<T>) {
    setFehler('')
    try {
      const ergebnis = await tun()
      await laden()
      // ⚠️ **Auch den angemeldeten Benutzer.** Der zweite Faktor, die Zahl der
      // Wiederherstellungscodes, der Anzeigename — alles steckt in `ich`, und
      // das kommt von oben. Ohne diese Zeile sieht man seine eigene Änderung
      // erst nach F5.
      ichNeuLaden?.()
      return ergebnis
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return null
    }
  }

  const [einschalten, setEinschalten] = useState(false)
  const [ausschalten, setAusschalten] = useState(false)
  const [kennwort, setKennwort] = useState('')

  const offen = ich?.offene_codes ?? 0
  const [neueCodes, setNeueCodes] = useState<string[] | null>(null)

  /** „Neue Codes erzeugen“: mit dem Passwort, die alten gelten danach nicht mehr; die neuen einmal zeigen. */
  async function codesNeu() {
    const kennwort = await passwortFragen('account.recoveryCodesNew')
    if (kennwort === null) return
    const antwort = await mit(() => api.senden<{ codes: string[] }>('/api/auth/zwei-faktor/codes', { passwort: kennwort }))
    if (antwort) setNeueCodes(antwort.codes)
  }

  /* Passwort ändern. Die Schnittstelle gab es seit Stufe 0, einen Dialog
     dafür erst seit 0.23.0. ⚠️ Das bisherige Passwort wird verlangt, auch
     angemeldet: Sonst genügt eine geklaute Sitzung, um den Eigentümer
     auszusperren. Danach fliegen die anderen Geräte hinaus, das eigene
     bleibt; die Liste darunter zeigt es sofort. */
  const [wechsel, setWechsel] = useState(false)
  const [altes, setAltes] = useState('')
  const [neues, setNeues] = useState('')
  const [neuesNochmal, setNeuesNochmal] = useState('')
  const [wechselFehler, setWechselFehler] = useState('')
  const [wechselLaeuft, setWechselLaeuft] = useState(false)
  const [gewechselt, setGewechselt] = useState('')

  function wechselZu() {
    setWechsel(false)
    setAltes('')
    setNeues('')
    setNeuesNochmal('')
    setWechselFehler('')
  }

  const wechselGrund =
    neues.length > 0 && neues.length < PASSWORD_MIN
      ? t('einrichtung.grund_kennwort_lang', { fehlen: PASSWORD_MIN - neues.length })
      : neuesNochmal && neues !== neuesNochmal
        ? t('account.passwordMismatch')
        : ''

  async function kennwortWechseln() {
    setWechselFehler('')
    setWechselLaeuft(true)
    try {
      const ergebnis = await api.aendern<{ abgemeldet: number }>('/api/auth/passwort', {
        altes,
        neues,
      })
      wechselZu()
      setGewechselt(t('sicherheit.kennwort_geaendert', { count: ergebnis.abgemeldet }))
      await laden()
    } catch (f) {
      setWechselFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setWechselLaeuft(false)
    }
  }

  /* Die Teile der Seite, wie das Kontenmodul sie ordnet (`PAGES.security`): Überschrift, Hinweis und Knöpfe aus
     seinen Wortlauten. nexmails eigene (Anbieter verknüpfen, Google und Microsoft) folgen danach. */
  const zustand = (ich?.zweiter_faktor ?? (ich?.zwei_faktor_aktiv ? 'active' : 'none')) as keyof typeof SECOND_FACTOR_STATE
  const teile: Record<string, () => ReactNode> = {
    password: () => {
      if (ich?.hat_kennwort === false) return null
      const p = teil('password')
      // konten 0.3.10: „Zuletzt geändert am …“ (Tag ohne Uhrzeit), bei Konten von vorher „unbekannt“.
      const geaendert = passwordChanged(ich?.passwort_geaendert)
      const tag = geaendert.date
        ? new Date(geaendert.date).toLocaleDateString(i18n.language, { day: '2-digit', month: '2-digit', year: 'numeric' })
        : ''
      return (
        <Box
          title={t(p.title)}
          hint={p.hint ? t(p.hint) : undefined}
          testId="passwort"
          actions={
            <AccountButton
              name="account.passwordChange"
              onClick={() => {
                setGewechselt('')
                setWechsel(true)
              }}
            />
          }
        >
          <p className="m-0 text-sm text-[var(--nexui-text-muted)]" data-testid="passwort-geaendert">
            {t(geaendert.text, { day: tag })}
          </p>
          {gewechselt ? <Notice tone="ok">{gewechselt}</Notice> : null}
        </Box>
      )
    },
    secondFactor: () => {
      const p = teil('secondFactor')
      return (
        <Box
          title={t(p.title)}
          badge={
            <Badge tone={ich?.zwei_faktor_aktiv || zustand === 'passkey' ? 'on' : 'off'}>
              {t(SECOND_FACTOR_STATE[zustand] ?? 'account.stateOff')}
            </Badge>
          }
          hint={t(p.hint)}
          testId="zweiter-faktor"
          actions={
            ich?.zwei_faktor_aktiv ? (
              <AccountButton name="account.totpRemove" onClick={() => setAusschalten(true)} />
            ) : (
              <AccountButton name="account.totpSetup" onClick={() => setEinschalten(true)} />
            )
          }
        />
      )
    },
    recoveryCodes: () => {
      if (!ich?.zwei_faktor_aktiv && !ich?.offene_codes) return null
      const p = teil('recoveryCodes')
      return (
        <Box
          title={t(p.title)}
          badge={<Badge tone={offen < WENIGE_CODES ? 'warn' : 'off'}>{t('account.recoveryLeft', { count: offen })}</Badge>}
          hint={t(p.hint)}
          testId="codes"
          actions={<AccountButton name="account.recoveryCodesNew" onClick={() => void codesNeu()} />}
        />
      )
    },
    /* Nur, wenn der Betreiber sie erlaubt und nexmail unter https läuft; vorhandene stehen auch sonst da, damit man
       sie entfernen kann. */
    passkeys: () => {
      if (!passkeys || !(passkeys.erlaubt || passkeys.passkeys.length > 0)) return null
      const p = teil('passkeys')
      return (
        <Box
          title={t(p.title)}
          hint={t(p.hint)}
          testId="passkeys"
          actions={passkeys.erlaubt && passkeyMoeglich() && <AccountButton name="account.passkeyAdd" onClick={() => void passkeyHinzufuegen()} />}
        >
          {passkeys.passkeys.length > 0 && (
            <Rows label={t(p.title)}>
              {passkeys.passkeys.map((k) => (
                <Row
                  key={k.uid}
                  icon={Fingerprint}
                  name={k.name || t(p.title)}
                  detail={zeitpunkt(k.last_used_at ?? k.created_at)}
                  action={
                    <AccountButton
                      name="account.passkeyRemove"
                      onClick={() =>
                        void (async () => {
                          const kennwort = await passwortFragen('account.passkeyRemove')
                          if (kennwort === null) return
                          await mit(() => api.senden(`/api/auth/passkeys/${k.uid}/entfernen`, { passwort: kennwort }))
                        })()
                      }
                    />
                  }
                />
              ))}
            </Rows>
          )}
        </Box>
      )
    },
    sessions: () => {
      const p = teil('sessions')
      return (
        <Box
          title={t(p.title)}
          hint={t(p.hint)}
          testId="geraete"
          actions={
            <AccountButton
              name="account.signOutEverywhere"
              disabled={(geraete?.length ?? 0) <= 1}
              onClick={() =>
                void (async () => {
                  const ja = await ask({
                    title: t(p.buttons[0]),
                    // Browser und gekoppelte iPhones/iPads; Kalender-Programme, API-Schlüssel, Passkeys bleiben.
                    text: t(p.hint),
                    confirm: confirmOf('account.signOutEverywhere', t(p.buttons[0])),
                  })
                  if (ja !== true) return
                  await mit(() => api.senden('/api/sitzungen/alle-beenden', {}))
                })()
              }
            />
          }
        >
          {geraete === null ? (
            <div className="h-16" />
          ) : (
            <Rows label={t(p.title)}>
              {geraete.map((g) => (
                <Row
                  key={g.id}
                  icon={Monitor}
                  name={g.geraet || t('sicherheit.unbekanntes_geraet')}
                  badge={g.aktuell ? <Badge tone="on">{t('account.sessionThis')}</Badge> : undefined}
                  // Wie in nexnotes: beim eigenen Browser nichts, sonst Tag und Uhrzeit (ohne Sekunden), davor die Adresse.
                  detail={g.aktuell ? undefined : [g.adresse, zeitpunkt(g.zuletzt_gesehen)].filter(Boolean).join(' · ')}
                  action={
                    // Die eigene Sitzung beendet man über „Abmelden“, nicht hier.
                    !g.aktuell && <AccountButton name="account.sessionSignOut" onClick={() => void mit(() => api.loeschen(`/api/sitzungen/${g.id}`))} />
                  }
                />
              ))}
            </Rows>
          )}
        </Box>
      )
    },
    /* Kontenmodul Teil 2: eine Mail, wenn sich jemand aus einem Browser anmeldet, den nexmail für dieses Konto noch
       nicht kennt. Ab Werk an; geht nur an eine bestätigte Adresse. */
    newSignInMail: () => {
      const p = teil('newSignInMail')
      return (
        <CheckboxRow
          label={t(p.title)}
          hint={t(p.hint)}
          checked={ich?.mail_neue_anmeldung ?? true}
          onChange={(an) => void mit(() => api.aendern('/api/auth/ich/neue-anmeldung', { an }))}
        />
      )
    },
    /* --- nexmails eigene Teile ------------------------------------------ */
    /* Anmeldeanbieter: verknüpfen mit Passwort, lösen; ein Kasten in der Karte „Sicherheit“ wie in nexnotes. */
    providers: () => <Anmeldeanbieter hatKennwort={ich?.hat_kennwort !== false} />,
    /* ⚠️ **Google und Microsoft hier, nicht beim Postfach.** Eine Zustimmung gilt fuer Postfach UND Kalender; sie an
       einem der beiden aufzuhaengen hiesse, sie beim anderen zu verstecken. */
    googleMicrosoft: () => <Oauthzugaenge istBetreiber={Boolean(ich?.ist_betreiber)} />,
  }

  return (
    <div className="flex flex-col gap-5">
      {fehler && <Notice tone="danger">{fehler}</Notice>}
      {/* `layout: 'stacked'`: ein Teil unter dem anderen, auch auf breiten Bildschirmen. Die des Moduls und die
          Anmeldeanbieter in der Karte „Sicherheit“, Google und Microsoft danach als eigene Karte. */}
      <Card id="security" icon={ShieldCheck} title={t(PAGES.security.title)}>
        {SICHERHEIT_TEILE.filter((name) => name in teile && !eigeneKarte(name)).map((name) => (
          <Fragment key={name}>{teile[name]()}</Fragment>
        ))}
      </Card>
      {SICHERHEIT_TEILE.filter((name) => name in teile && eigeneKarte(name)).map((name) => (
        <Fragment key={name}>{teile[name]()}</Fragment>
      ))}

      {wechsel && (
        <ConfirmDialog
          title={t('account.passwordChange')}
          text={t('sicherheit.kennwort_folge')}
          confirm={confirmOf('resetSubmit', t('account.passwordChange'))}
          cancel={t('aktion.abbrechen')}
          closeLabel={t('aktion.schliessen')}
          busy={wechselLaeuft}
          error={wechselFehler || wechselGrund}
          confirmDisabled={!altes || neues.length < PASSWORD_MIN || neues !== neuesNochmal}
          onCancel={wechselZu}
          onConfirm={() => void kennwortWechseln()}
        >
          <Field label={t('account.currentPassword')} type="password" autoComplete="current-password" value={altes} onChange={(e) => setAltes(e.target.value)} />
          <Field
            label={t('account.newPassword')}
            type="password"
            autoComplete="new-password"
            hints={[t('account.passwordRules', { minimum: PASSWORD_MIN })]}
            value={neues}
            onChange={(e) => setNeues(e.target.value)}
          />
          <Field label={t('account.passwordRepeat')} type="password" autoComplete="new-password" value={neuesNochmal} onChange={(e) => setNeuesNochmal(e.target.value)} />
        </ConfirmDialog>
      )}

      {einschalten && (
        <Dialog title={t('account.totpSetup')} onClose={() => setEinschalten(false)} closeLabel={t('aktion.schliessen')}>
          <ZweiterFaktor
            benutzername={ich?.benutzername ?? ''}
            aufAbbrechen={() => setEinschalten(false)}
            aufFertig={() => {
              setEinschalten(false)
              void laden()
            }}
          />
        </Dialog>
      )}

      {ausschalten && (
        <ConfirmDialog
          title={t('account.totpRemove')}
          text={t('sicherheit.faktor_aus_warnung')}
          confirm={confirmOf('account.totpRemove', t('account.totpRemove'))}
          cancel={t('aktion.abbrechen')}
          closeLabel={t('aktion.schliessen')}
          error={fehler || undefined}
          confirmDisabled={!kennwort}
          onCancel={() => setAusschalten(false)}
          onConfirm={async () => {
            const ok = await mit(() => api.senden('/api/auth/zwei-faktor/aus', { passwort: kennwort }))
            if (ok !== null) {
              setAusschalten(false)
              setKennwort('')
            }
          }}
        >
          <Field label={t('account.currentPassword')} hints={[t('account.confirmWithPassword')]} type="password" autoComplete="current-password" value={kennwort} onChange={(e) => setKennwort(e.target.value)} />
        </ConfirmDialog>
      )}

      {neueCodes && (
        <Dialog title={t('account.recoveryCodes')} onClose={() => setNeueCodes(null)} closeLabel={t('aktion.schliessen')}>
          <CodesZeigen codes={neueCodes} benutzername={ich?.benutzername ?? ''} aufFertig={() => setNeueCodes(null)} />
        </Dialog>
      )}

      {dialog}
    </div>
  )
}
