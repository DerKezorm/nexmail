/* Sicherheit — seit konten 0.3.6 ganz aus dem Kontenmodul (`PAGES.security`): Passwort, Zweiter Faktor („An“/„Aus“),
 * Wiederherstellungscodes, Passkeys, „Angemeldete Geräte“ mit „Überall sonst abmelden“, „Mail bei neuer Anmeldung“;
 * Überschriften, Hinweise und Knöpfe sind die Wortlaute des Moduls, die Teile stehen untereinander. Danach nexmails
 * eigene Teile: Anmeldeanbieter verknüpfen, Google- und Microsoft-Konten (`pageOrder`).
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
import { Fingerprint, KeyRound, LogOut, Monitor, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Ich } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Oauthzugaenge } from '../components/Oauthzugaenge'
import { Anmeldeanbieter } from '../components/Anmeldeanbieter'
import { Badge, Button, Dialog, IconButton, Input, Switch } from '../ds'
import { CodesZeigen, ZweiterFaktor } from '../components/ZweiterFaktor'
import { servermeldung } from '../lib/servermeldung'
import { alsJson, anlegeOptionen, geraetename, passkeyMoeglich } from '../lib/passkey'
import { PAGES, pageOrder, SECOND_FACTOR_STATE, type PagePart } from '../vendor/nexkonten/konten'

/** nexmails eigene Teile der Sicherheit, nach denen des Moduls. */
export const SICHERHEIT_EIGENE = ['providers', 'googleMicrosoft'] as const
export const SICHERHEIT_TEILE = pageOrder('security', SICHERHEIT_EIGENE)

function teil(name: string): PagePart {
  return PAGES.security.parts.find((p: PagePart) => p.part === name) as PagePart
}

/** Ein Teil der Seite: Überschrift (daneben ein Zustand), Hinweis, Inhalt. */
function Abschnitt({
  titel,
  zusatz,
  hinweis,
  children,
}: {
  titel: string
  zusatz?: ReactNode
  hinweis?: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{titel}</h2>
        {zusatz}
      </div>
      {hinweis && <p className="mb-0 text-[12px] text-fg-3">{hinweis}</p>}
      {children}
    </section>
  )
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

export function Sicherheit({
  ich,
  ichNeuLaden,
}: {
  ich: Ich | null
  ichNeuLaden?: () => void
}) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [geraete, setGeraete] = useState<Geraet[] | null>(null)
  const [fehler, setFehler] = useState('')

  const [passkeys, setPasskeys] = useState<Passkeys | null>(null)

  const laden = useCallback(async () => {
    setGeraete(await api.holen<Geraet[]>(`/api/sitzungen?sprache=${encodeURIComponent(i18n.language)}`))
    setPasskeys(await api.holen<Passkeys>('/api/auth/passkeys').catch(() => null))
  }, [i18n.language])

  useEffect(() => {
    void laden().catch(() => setGeraete([]))
  }, [laden])

  /** Das eigene Passwort für einen Schritt, der es verlangt; ein Konto ohne Passwort bestätigt mit der frischen
   *  Anmeldung beim Anbieter (der Server prüft das), dann wird nicht gefragt. */
  async function passwortFragen(titel: string): Promise<string | null> {
    if (ich && ich.hat_kennwort === false) return ''
    const kennwort = await fragen({
      titel,
      text: t('account.confirmWithPassword'),
      eingabe: { beschriftung: t('account.password'), typ: 'password' },
      knopf: t('aktion.weiter'),
    })
    return typeof kennwort === 'string' && kennwort ? kennwort : null
  }

  async function passkeyHinzufuegen() {
    const kennwort = await passwortFragen(t('account.passkeyAdd'))
    if (kennwort === null) return
    const name = await fragen({
      titel: t('account.passkeyAdd'),
      eingabe: { beschriftung: t('account.passkeyName'), vorgabe: geraetename() },
      knopf: t('account.passkeyAdd'),
    })
    if (name === null || name === false) return
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

  const wenige = (ich?.offene_codes ?? 0) <= 3
  const [neueCodes, setNeueCodes] = useState<string[] | null>(null)

  /** „Neue Codes erzeugen“: mit dem Passwort, die alten gelten danach nicht mehr; die neuen einmal zeigen. */
  async function codesNeu() {
    const kennwort = await passwortFragen(t('account.recoveryCodesNew'))
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
    neues.length > 0 && neues.length < 10
      ? t('einrichtung.grund_kennwort_lang', { fehlen: 10 - neues.length })
      : neuesNochmal && neues !== neuesNochmal
        ? t('einrichtung.passwort_ungleich')
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
      return (
        <Abschnitt titel={t(p.title)} hinweis={p.hint && t(p.hint)}>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              iconLeft={<KeyRound className="size-4" />}
              onClick={() => {
                setGewechselt('')
                setWechsel(true)
              }}
            >
              {t(p.buttons[0])}
            </Button>
            {gewechselt && (
              <span role="status" className="text-[13px] text-accent-text">
                {gewechselt}
              </span>
            )}
          </div>
        </Abschnitt>
      )
    },
    secondFactor: () => {
      const p = teil('secondFactor')
      return (
        <Abschnitt
          titel={t(p.title)}
          zusatz={
            <Badge tone={ich?.zwei_faktor_aktiv || zustand === 'passkey' ? 'success' : 'neutral'}>
              {t(SECOND_FACTOR_STATE[zustand] ?? 'account.stateOff')}
            </Badge>
          }
          hinweis={t(p.hint)}
        >
          <div className="flex flex-wrap gap-2">
            {ich?.zwei_faktor_aktiv ? (
              <Button size="sm" variant="ghost" onClick={() => setAusschalten(true)}>
                {t(p.buttons[1])}
              </Button>
            ) : (
              <Button size="sm" variant="primary" onClick={() => setEinschalten(true)}>
                {t(p.buttons[0])}
              </Button>
            )}
          </div>
        </Abschnitt>
      )
    },
    recoveryCodes: () => {
      if (!ich?.zwei_faktor_aktiv && !ich?.offene_codes) return null
      const p = teil('recoveryCodes')
      return (
        <Abschnitt
          titel={t(p.title)}
          zusatz={
            <Badge tone={wenige ? 'warning' : 'neutral'}>
              {t('account.recoveryLeft', { count: ich?.offene_codes ?? 0 })}
            </Badge>
          }
          hinweis={t(p.hint)}
        >
          <div>
            <Button size="sm" variant="secondary" onClick={() => void codesNeu()}>
              {t(p.buttons[0])}
            </Button>
          </div>
        </Abschnitt>
      )
    },
    /* Nur, wenn der Betreiber sie erlaubt und nexmail unter https läuft; vorhandene stehen auch sonst da, damit man
       sie entfernen kann. */
    passkeys: () => {
      if (!passkeys || !(passkeys.erlaubt || passkeys.passkeys.length > 0)) return null
      const p = teil('passkeys')
      return (
        <Abschnitt titel={t(p.title)} hinweis={t(p.hint)}>
          {passkeys.passkeys.length > 0 && (
            <ul className="flex flex-col gap-2">
              {passkeys.passkeys.map((k) => (
                <li key={k.uid} className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-3 py-2">
                  <Fingerprint className="size-4 shrink-0 text-fg-4" />
                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-fg-1">{k.name || t(p.title)}</span>
                    <span className="block truncate font-mono text-[11px] text-fg-4">
                      {new Date(k.last_used_at ?? k.created_at).toLocaleString(i18n.language)}
                    </span>
                  </div>
                  <IconButton
                    icon={<Trash2 />}
                    label={t('account.passkeyRemove')}
                    size="sm"
                    onClick={() =>
                      void (async () => {
                        const kennwort = await passwortFragen(t('account.passkeyRemove'))
                        if (kennwort === null) return
                        await mit(() => api.senden(`/api/auth/passkeys/${k.uid}/entfernen`, { passwort: kennwort }))
                      })()
                    }
                  />
                </li>
              ))}
            </ul>
          )}
          {passkeys.erlaubt && passkeyMoeglich() && (
            <div className="pt-1">
              <Button size="sm" variant="secondary" iconLeft={<Fingerprint className="size-4" />} onClick={() => void passkeyHinzufuegen()}>
                {t(p.buttons[0])}
              </Button>
            </div>
          )}
        </Abschnitt>
      )
    },
    sessions: () => {
      const p = teil('sessions')
      return (
        <Abschnitt titel={t(p.title)} hinweis={t(p.hint)}>
          {geraete === null ? (
            <div className="h-16" />
          ) : (
            <ul className="flex flex-col gap-2">
              {geraete.map((g) => (
                <li key={g.id} className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-3 py-2.5">
                  <Monitor className="size-4 shrink-0 text-fg-4" />
                  <div className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-[13px] text-fg-1">
                        {g.geraet || t('sicherheit.unbekanntes_geraet')}
                      </span>
                      {g.aktuell && <Badge tone="success">{t('sicherheit.dieses_geraet')}</Badge>}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-fg-4">
                      {g.adresse} · {new Date(g.zuletzt_gesehen).toLocaleString(i18n.language)}
                    </span>
                  </div>
                  <IconButton
                    icon={<LogOut />}
                    label={t('sicherheit.beenden')}
                    size="sm"
                    // Die eigene Sitzung beendet man über „Abmelden", nicht hier
                    // — sonst sieht es aus wie ein Fehler.
                    disabled={g.aktuell}
                    onClick={() => void mit(() => api.loeschen(`/api/sitzungen/${g.id}`))}
                  />
                </li>
              ))}
            </ul>
          )}
          <div>
            <Button
              variant="danger"
              iconLeft={<LogOut className="size-4" />}
              disabled={(geraete?.length ?? 0) <= 1}
              onClick={() =>
                void (async () => {
                  const ja = await fragen({
                    titel: t(p.buttons[0]),
                    // Browser und gekoppelte iPhones/iPads; Kalender-Programme, API-Schlüssel, Passkeys bleiben.
                    text: t(p.hint),
                    knopf: t(p.buttons[0]),
                    gefaehrlich: true,
                  })
                  if (ja !== true) return
                  await mit(() => api.senden('/api/sitzungen/alle-beenden', {}))
                })()
              }
            >
              {t(p.buttons[0])}
            </Button>
          </div>
        </Abschnitt>
      )
    },
    /* Kontenmodul Teil 2: eine Mail, wenn sich jemand aus einem Browser anmeldet, den nexmail für dieses Konto noch
       nicht kennt. Ab Werk an; geht nur an eine bestätigte Adresse. */
    newSignInMail: () => {
      const p = teil('newSignInMail')
      return (
        <Switch
          label={t(p.title)}
          description={t(p.hint)}
          checked={ich?.mail_neue_anmeldung ?? true}
          onCheckedChange={(an) => void mit(() => api.aendern('/api/auth/ich/neue-anmeldung', { an }))}
        />
      )
    },
    /* --- nexmails eigene Teile ------------------------------------------ */
    /* Anmeldeanbieter: verknüpfen mit Passwort, lösen. */
    providers: () => <Anmeldeanbieter />,
    /* ⚠️ **Google und Microsoft hier, nicht beim Postfach.** Eine Zustimmung gilt fuer Postfach UND Kalender; sie an
       einem der beiden aufzuhaengen hiesse, sie beim anderen zu verstecken. */
    googleMicrosoft: () => <Oauthzugaenge istBetreiber={Boolean(ich?.ist_betreiber)} />,
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      {/* `layout: 'stacked'`: ein Teil unter dem anderen, auch auf breiten Bildschirmen. */}
      {SICHERHEIT_TEILE.filter((name) => name in teile).map((name) => (
        <Fragment key={name}>{teile[name]()}</Fragment>
      ))}

      {wechsel && (
        <Dialog open title={t('account.passwordChange')} onClose={wechselZu}>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              void kennwortWechseln()
            }}
          >
            <Input
              label={t('sicherheit.kennwort_bisher')}
              type="password"
              autoComplete="current-password"
              value={altes}
              onChange={(e) => setAltes(e.target.value)}
            />
            <Input
              label={t('sicherheit.kennwort_neu')}
              type="password"
              autoComplete="new-password"
              hint={t('einrichtung.passwort_hinweis')}
              value={neues}
              onChange={(e) => setNeues(e.target.value)}
            />
            <Input
              label={t('einrichtung.passwort_wiederholen')}
              type="password"
              autoComplete="new-password"
              value={neuesNochmal}
              onChange={(e) => setNeuesNochmal(e.target.value)}
            />
            <p className="mb-0 text-[12px] text-fg-3">{t('sicherheit.kennwort_folge')}</p>
            {(wechselFehler || wechselGrund) && (
              <p role="alert" className="mb-0 text-[13px] text-danger">
                {wechselFehler || wechselGrund}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                type="submit"
                variant="primary"
                disabled={
                  wechselLaeuft || !altes || neues.length < 10 || neues !== neuesNochmal
                }
              >
                {t('account.passwordChange')}
              </Button>
              <Button type="button" variant="ghost" onClick={wechselZu}>
                {t('aktion.abbrechen')}
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      {einschalten && (
        <Dialog open title={t('account.totpSetup')} onClose={() => setEinschalten(false)}>
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
        <Dialog open title={t('account.totpRemove')} onClose={() => setAusschalten(false)}>
          <div className="flex flex-col gap-4">
            <p className="mb-0 text-[13px] text-fg-2">{t('sicherheit.faktor_aus_warnung')}</p>
            <Input
              label={t('sicherheit.faktor_aus_frage')}
              type="password"
              autoComplete="current-password"
              value={kennwort}
              onChange={(e) => setKennwort(e.target.value)}
            />
            {fehler && <p className="mb-0 text-[13px] text-danger">{fehler}</p>}
            <div className="flex gap-2">
              <Button
                variant="danger"
                disabled={!kennwort}
                onClick={async () => {
                  const ok = await mit(() =>
                    api.senden('/api/auth/zwei-faktor/aus', { passwort: kennwort }),
                  )
                  if (ok !== null) {
                    setAusschalten(false)
                    setKennwort('')
                  }
                }}
              >
                {t('account.totpRemove')}
              </Button>
              <Button variant="ghost" onClick={() => setAusschalten(false)}>
                {t('aktion.abbrechen')}
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {neueCodes && (
        <Dialog open title={t('account.recoveryCodes')} onClose={() => setNeueCodes(null)}>
          <CodesZeigen codes={neueCodes} benutzername={ich?.benutzername ?? ''} aufFertig={() => setNeueCodes(null)} />
        </Dialog>
      )}

      {nachfrage}
    </div>
  )
}
