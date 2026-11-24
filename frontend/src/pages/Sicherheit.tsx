/* Sicherheit — wer ist gerade angemeldet, und womit.
 *
 * ⚠️ **Angemeldete Geräte gehören sichtbar und einzeln kündbar.** Genau
 * dafür liegen die Sitzungen im Server und nicht im Token: „auf allen Geräten
 * abmelden" wirkt sofort. Eine Anwendung, die alle Postfächer hält, muss
 * zeigen können, wer sie gerade offen hat.
 *
 * ⚠️ **Die Zahl der übrigen Wiederherstellungscodes steht hier.** Sonst
 * erfährt man sie erst, wenn keiner mehr da ist — und dann ist es zu spät.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Fingerprint, KeyRound, LogOut, Monitor, ShieldAlert, ShieldCheck, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Ich } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Oauthzugaenge } from '../components/Oauthzugaenge'
import { Anmeldeanbieter } from '../components/Anmeldeanbieter'
import { Badge, Button, Dialog, IconButton, Input, Switch } from '../ds'
import { ZweiterFaktor } from '../components/ZweiterFaktor'
import { servermeldung } from '../lib/servermeldung'
import { alsJson, anlegeOptionen, geraetename, passkeyMoeglich } from '../lib/passkey'

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
    setGeraete(await api.holen<Geraet[]>('/api/sitzungen'))
    setPasskeys(await api.holen<Passkeys>('/api/auth/passkeys').catch(() => null))
  }, [])

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

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {/* Die Adresse für Kontosachen steht seit dem Umbau der Einstellungen
          (22.11.2026) im Profil, wie in nexnotes (`einstellungen/Profil.tsx`). */}
      {/* --- Passwort ---------------------------------------------------- */}
      {ich?.hat_kennwort !== false && (
        <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-4">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('sicherheit.kennwort')}</h2>
          <p className="mb-0 text-[13px] text-fg-2">{t('sicherheit.kennwort_hinweis')}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              iconLeft={<KeyRound className="size-4" />}
              onClick={() => {
                setGewechselt('')
                setWechsel(true)
              }}
            >
              {t('sicherheit.kennwort_aendern')}
            </Button>
            {gewechselt && (
              <span role="status" className="text-[13px] text-accent-text">
                {gewechselt}
              </span>
            )}
          </div>
        </section>
      )}

      {wechsel && (
        <Dialog open title={t('sicherheit.kennwort_aendern')} onClose={wechselZu}>
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
                {t('sicherheit.kennwort_aendern')}
              </Button>
              <Button type="button" variant="ghost" onClick={wechselZu}>
                {t('aktion.abbrechen')}
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      {/* --- Zweiter Faktor --------------------------------------------- */}
      <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-4">
        <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('sicherheit.zwei_faktor')}</h2>

        <div className="flex flex-wrap items-center gap-2 text-[13px] text-fg-2">
          {ich?.zwei_faktor_aktiv ? (
            <ShieldCheck className="size-4 shrink-0 text-success" />
          ) : (
            <ShieldAlert className="size-4 shrink-0 text-warning" />
          )}
          <span>
            {ich?.zwei_faktor_aktiv ? t('sicherheit.aktiv') : t('sicherheit.nicht_aktiv')}
          </span>
        </div>

        {ich?.zwei_faktor_aktiv && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={wenige ? 'warning' : 'neutral'}>
              {t('sicherheit.codes_uebrig', { count: ich?.offene_codes ?? 0 })}
            </Badge>
            {/* ⚠️ Kein leiser Hinweis: Wer keine Codes mehr hat und sein Handy
                verliert, kommt nur noch über den Nothammer in der compose-Datei
                hinein. */}
            {wenige && (
              <span className="text-[12px] text-warning">{t('sicherheit.codes_knapp')}</span>
            )}
          </div>
        )}

        {/* ⚠️ **Die Anwendung sagt, was der ausgeschaltete Faktor kostet.**
            Er ist seit dem 01.09.2026 eine Wahl — und eine Wahl ohne Folgen
            ausgesprochen ist keine. Der Satz steht hier und nicht in einer
            README, die niemand aufschlägt. */}
        {!ich?.zwei_faktor_aktiv && (
          <p className="mb-0 text-[12px] text-fg-3">{t('sicherheit.faktor_empfehlung')}</p>
        )}

        <div className="flex flex-wrap gap-2 pt-1">
          {ich?.zwei_faktor_aktiv ? (
            <Button size="sm" variant="ghost" onClick={() => setAusschalten(true)}>
              {t('sicherheit.faktor_ausschalten')}
            </Button>
          ) : (
            <Button size="sm" variant="primary" onClick={() => setEinschalten(true)}>
              {t('sicherheit.faktor_einschalten')}
            </Button>
          )}
        </div>
      </section>

      {einschalten && (
        <Dialog open title={t('sicherheit.faktor_einschalten')} onClose={() => setEinschalten(false)}>
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
        <Dialog open title={t('sicherheit.faktor_ausschalten')} onClose={() => setAusschalten(false)}>
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
                {t('sicherheit.faktor_ausschalten')}
              </Button>
              <Button variant="ghost" onClick={() => setAusschalten(false)}>
                {t('aktion.abbrechen')}
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {/* --- Passkeys (Kontenmodul Teil 2) ------------------------------- */}
      {/* Nur, wenn der Betreiber sie erlaubt und nexmail unter https läuft; vorhandene stehen auch sonst da, damit man
          sie entfernen kann. */}
      {passkeys && (passkeys.erlaubt || passkeys.passkeys.length > 0) && (
        <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 p-4">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('account.passkeys')}</h2>
          <p className="mb-0 text-[12px] text-fg-3">{t('account.passkeysHint')}</p>
          {passkeys.passkeys.length > 0 && (
            <ul className="flex flex-col gap-2">
              {passkeys.passkeys.map((p) => (
                <li key={p.uid} className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-3 py-2">
                  <Fingerprint className="size-4 shrink-0 text-fg-4" />
                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-fg-1">{p.name || t('account.passkeys')}</span>
                    <span className="block truncate font-mono text-[11px] text-fg-4">
                      {new Date(p.last_used_at ?? p.created_at).toLocaleString(i18n.language)}
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
                        await mit(() => api.senden(`/api/auth/passkeys/${p.uid}/entfernen`, { passwort: kennwort }))
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
                {t('account.passkeyAdd')}
              </Button>
            </div>
          )}
        </section>
      )}

      {/* --- Anmeldeanbieter: verknüpfen mit Passwort, lösen ------------- */}
      <Anmeldeanbieter />

      {/* --- Google und Microsoft ---------------------------------------- */}
      {/* ⚠️ **Hier, nicht beim Postfach.** Eine Zustimmung gilt fuer Postfach
          UND Kalender; sie an einem der beiden aufzuhaengen hiesse, sie beim
          anderen zu verstecken. */}
      <Oauthzugaenge istBetreiber={Boolean(ich?.ist_betreiber)} />

      {/* --- Angemeldete Geräte ------------------------------------------ */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <h2 className="mb-0 flex-1 text-[13px] font-semibold text-fg-1">
            {t('sicherheit.geraete')}
          </h2>
          {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
        </div>

        {geraete === null ? (
          <div className="h-16" />
        ) : (
          <ul className="flex flex-col gap-2">
            {geraete.map((g) => (
              <li
                key={g.id}
                className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5"
              >
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

        {/* Kontenmodul Teil 2: eine Mail, wenn sich jemand aus einem Browser anmeldet, den nexmail für dieses Konto
            noch nicht kennt. Ab Werk an; geht nur an eine bestätigte Adresse. */}
        <Switch
          label={t('account.newSignInMail')}
          description={t('account.newSignInMailHint')}
          checked={ich?.mail_neue_anmeldung ?? true}
          onCheckedChange={(an) => void mit(() => api.aendern('/api/auth/ich/neue-anmeldung', { an }))}
        />

        <div>
          <Button
            variant="danger"
            iconLeft={<LogOut className="size-4" />}
            disabled={(geraete?.length ?? 0) <= 1}
            onClick={() =>
              void (async () => {
                const ja = await fragen({
                  titel: t('sicherheit.alle_beenden'),
                  text: t('sicherheit.alle_beenden_sicher'),
                  knopf: t('sicherheit.alle_beenden'),
                  gefaehrlich: true,
                })
                if (ja !== true) return
                await mit(() => api.senden('/api/sitzungen/alle-beenden', {}))
              })()
            }
          >
            {t('sicherheit.alle_beenden')}
          </Button>
        </div>
      </section>

      {nachfrage}
    </div>
  )
}
