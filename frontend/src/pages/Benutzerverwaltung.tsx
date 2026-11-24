/* Wer nexmail benutzen darf — der Reiter „Benutzer" in der Verwaltung.
 *
 * ⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
 * einzeln. nexmail ist der Mail-Client eines Haushalts, keine Plattform.
 *
 * ⚠️ **Was fehlt, steht oben — bevor jemand tippt.** Ohne Postausgang und
 * ohne öffentliche Adresse geht keine Einladung hinaus. Das erst beim
 * Absenden zu melden, hieße: Formular ausgefüllt, Fehler kassiert, und der
 * Weg zur Abhilfe liegt in einem anderen Reiter.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  AtSign,
  Crown,
  KeyRound,
  Mail,
  Pencil,
  ShieldCheck,
  Sparkles,
  SparklesIcon,
  Trash2,
  Unlink,
  UserPen,
  UserPlus,
} from 'lucide-react'
import { api } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Badge, Button, Dialog, IconButton, Input, Select } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import { INVITE_DAYS, INVITE_DAYS_DEFAULT, RESET_DAYS, RESET_DAYS_DEFAULT } from '../vendor/nexkonten/konten'

interface BenutzerZeile {
  id: string
  benutzername: string
  anzeigename: string
  ist_betreiber: boolean
  zwei_faktor_aktiv: boolean
  angelegt: string
  postfaecher: number
  ki_erlaubt: boolean
  /** Die Kennung im Anmeldemodul, für „Verknüpfung lösen“. */
  nummer: number
  /** Die Anmeldeanbieter, mit denen das Konto verknüpft ist. */
  anbieter: Array<{ id: number; slug: string; label: string }>
  /** Kontenmodul: die Adresse, ob ein anderes Konto sie auch hat, ob es ein Passwort gibt. */
  kontaktadresse?: string
  adresse_doppelt?: boolean
  hat_kennwort?: boolean
}

interface EinladungsZeile {
  id: string
  benutzername: string
  anzeigename: string
  adresse: string
  laeuft_ab: string
  abgelaufen: boolean
  /** Der Link, einmal, wenn er nicht per Mail hinausging. */
  link?: string
}

interface Bestand {
  benutzer: BenutzerZeile[]
  einladungen: EinladungsZeile[]
  postausgang_da: boolean
  adresse_da: boolean
}

interface Umfang {
  postfaecher: number
  nachrichten: number
  kontakte: number
  regeln: number
  signaturen: number
}

export function Benutzerverwaltung({ ichNeuLaden }: { ichNeuLaden?: () => void }) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [bestand, setBestand] = useState<Bestand | null>(null)
  const [fehler, setFehler] = useState('')
  const [einladen, setEinladen] = useState(false)
  /** Ein Link zum Weitergeben (Einladung oder neues Passwort), einmal gezeigt. */
  const [weitergeben, setWeitergeben] = useState<{ titel: string; link: string } | null>(null)

  const laden = useCallback(async () => {
    try {
      setBestand(await api.holen<Bestand>('/api/benutzer'))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  /** Den Betreiber-Haken weitergeben.
   *
   * ⚠️ **Danach ist man selbst keiner mehr.** Der Haken wandert, er wird nicht
   * vergeben; zwei Betreiber wären nicht schlimm, aber null sind das Ende. Die
   * Rückfrage sagt genau das, und sie verlangt das eigene Kennwort — eine
   * geklaute Sitzung soll dafür nicht reichen.
   */
  async function uebergeben(p: BenutzerZeile) {
    const wer = p.anzeigename || p.benutzername
    const kennwort = await fragen({
      titel: t('verwaltung.uebergeben_frage', { wer }),
      text: t('verwaltung.uebergeben_text', { wer }),
      eingabe: { beschriftung: t('anmeldung.passwort'), typ: 'password' },
      knopf: t('verwaltung.uebergeben_knopf'),
      gefaehrlich: true,
    })
    if (typeof kennwort !== 'string' || !kennwort) return
    try {
      await api.senden(`/api/benutzer/${p.id}/betreiber`, { passwort: kennwort })
      await laden()
      ichNeuLaden?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  /** Einem einzelnen Konto KI-Dienste erlauben oder verbieten.
   *
   * ⚠️ **Ohne Rückfrage, anders als beim Entfernen und beim Übergeben.** Es
   * ist mit demselben Klick umkehrbar und kostet niemandem seinen Zugang —
   * die Schlüssel bleiben stehen. Eine Rückfrage für jeden Haken macht die
   * Verwaltung unbenutzbar, und dann wird sie umgangen.
   */
  async function kiUmlegen(p: BenutzerZeile) {
    try {
      await api.aendern(`/api/benutzer/${p.id}/ki`, { erlaubt: !p.ki_erlaubt })
      await laden()
    } catch (e) {
      setFehler(servermeldung(e))
    }
  }

  /** Eine Verknüpfung eines Kontos lösen: mit dem eigenen
   *  Kennwort des Betreibers, und die Rückfrage nennt Konto und Anbieter. */
  async function verknuepfungLoesen(p: BenutzerZeile, a: { id: number; label: string }) {
    const wer = p.anzeigename || p.benutzername
    const kennwort = await fragen({
      titel: t('anmeldeweg.verknuepfung_loesen'),
      text: t('anmeldeweg.verknuepfung_loesen_text', { wer, name: a.label }),
      eingabe: { beschriftung: t('anmeldung.passwort'), typ: 'password' },
      knopf: t('anmeldeweg.verknuepfung_loesen'),
      gefaehrlich: true,
    })
    if (typeof kennwort !== 'string' || !kennwort) return
    try {
      await api.loeschen(`/api/oidc/admin/accounts/${p.nummer}/links/${a.id}`, { password: kennwort })
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  /** Das eigene Passwort des Betreibers vor jeder Änderung an einem fremden Konto (Kontenmodul). */
  async function eigenesPasswort(titel: string): Promise<string | null> {
    const kennwort = await fragen({
      titel,
      text: t('account.confirmWithPassword'),
      eingabe: { beschriftung: t('account.password'), typ: 'password' },
      knopf: t('aktion.weiter'),
    })
    return typeof kennwort === 'string' && kennwort ? kennwort : null
  }

  async function handeln(aufruf: () => Promise<unknown>) {
    setFehler('')
    try {
      await aufruf()
      await laden()
      ichNeuLaden?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function namenAendern(p: BenutzerZeile, feld: 'benutzername' | 'anzeigename') {
    const titel = t(feld === 'benutzername' ? 'account.username' : 'account.displayName')
    const neu = await fragen({
      titel,
      text: feld === 'benutzername' ? t('account.usernameRules') : t('account.displayNameHint'),
      eingabe: { beschriftung: titel, vorgabe: feld === 'benutzername' ? p.benutzername : p.anzeigename },
      knopf: t('aktion.weiter'),
    })
    if (typeof neu !== 'string' || !neu) return
    const kennwort = await eigenesPasswort(titel)
    if (kennwort === null) return
    await handeln(() => api.aendern(`/api/benutzer/${p.id}/${feld}`, { [feld]: neu, passwort: kennwort }))
  }

  async function adresseEntfernen(p: BenutzerZeile) {
    const kennwort = await eigenesPasswort(t('account.emailRemove'))
    if (kennwort === null) return
    await handeln(() => api.senden(`/api/benutzer/${p.id}/kontaktadresse-entfernen`, { passwort: kennwort }))
  }

  /** „Link für ein neues Passwort“: wie lange er gilt, dann das eigene Passwort. Mit Postausgang und Adresse geht er
   *  per Mail hin, sonst steht er einmal zum Weitergeben da. Der Betreiber setzt nie selbst ein Passwort. */
  async function passwortLink(p: BenutzerZeile) {
    const dauer = await fragen({
      titel: t('account.resetLink'),
      text: p.anzeigename || p.benutzername,
      auswahl: {
        beschriftung: t('account.validFor'),
        werte: RESET_DAYS.map((tage) => ({ wert: String(tage), text: t('account.days', { count: tage }) })),
        vorgabe: String(RESET_DAYS_DEFAULT),
      },
      knopf: t('aktion.weiter'),
    })
    if (!dauer || typeof dauer !== 'object') return
    const kennwort = await eigenesPasswort(t('account.resetLink'))
    if (kennwort === null) return
    setFehler('')
    try {
      const antwort = await api.senden<{ link: string; an: string }>(`/api/benutzer/${p.id}/passwort-link`, {
        passwort: kennwort,
        tage: Number(dauer.wert),
      })
      if (antwort.link) setWeitergeben({ titel: t('account.resetLink'), link: antwort.link })
      else await fragen({ titel: t('account.resetLink'), text: t('account.resetLinkSent', { email: antwort.an }), knopf: t('aktion.fertig') })
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function entfernen(person: BenutzerZeile) {
    setFehler('')
    let umfang: Umfang | null = null
    try {
      umfang = await api.holen<Umfang>(`/api/benutzer/${person.id}/umfang`)
    } catch {
      umfang = null
    }

    /* ⚠️ **Zahlen statt „alle Daten".** „Wirklich entfernen?" beantwortet man
       mit Ja, ohne nachzudenken. „3 Postfächer und 12.418 Nachrichten" liest
       man. Und der Satz sagt ausdrücklich, dass auf dem Mailserver nichts
       passiert — sonst traut sich niemand. */
    const ja = await fragen({
      titel: t('verwaltung.benutzer_entfernen'),
      text: umfang
        ? t('verwaltung.benutzer_entfernen_text', {
            name: person.anzeigename || person.benutzername,
            postfaecher: umfang.postfaecher,
            nachrichten: umfang.nachrichten.toLocaleString(i18n.language),
          })
        : t('verwaltung.benutzer_entfernen_kurz', {
            name: person.anzeigename || person.benutzername,
          }),
      knopf: t('verwaltung.benutzer_entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return

    try {
      await api.loeschen(`/api/benutzer/${person.id}`)
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function zuruecknehmen(e: EinladungsZeile) {
    const ja = await fragen({
      titel: t('verwaltung.einladung_zuruecknehmen'),
      text: t('verwaltung.einladung_zuruecknehmen_text', { name: e.anzeigename || e.adresse || e.benutzername }),
      knopf: t('verwaltung.einladung_zuruecknehmen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await api.loeschen(`/api/benutzer/einladungen/${e.id}`)
    await laden()
  }

  if (bestand === null) return <div className="h-24" />

  /* Seit dem Kontenmodul geht eine Einladung auch ohne Postausgang: Der Link steht dann zum Weitergeben da. Ohne
     öffentliche Adresse gäbe es keinen Link. */
  const bereit = bestand.adresse_da

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {!(bestand.postausgang_da && bestand.adresse_da) && (
        <div className="flex gap-3 rounded-lg border border-warning/40 bg-warning-soft p-4">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="min-w-0">
            {!bestand.adresse_da && (
              <p className="mb-1 text-[13px] font-medium text-fg-1">{t('verwaltung.einladen_geht_nicht')}</p>
            )}
            <p className="mb-0 text-[13px] text-fg-2">
              {!bestand.adresse_da ? t('verwaltung.keine_adresse') : t('verwaltung.kein_postausgang')}
            </p>
          </div>
        </div>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <h2 className="mb-0 flex-1 text-[13px] font-semibold text-fg-1">
            {t('verwaltung.benutzer')}
          </h2>
          {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
        </div>

        <ul className="flex list-none flex-col gap-2 p-0">
          {bestand.benutzer.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <p className="mb-0 truncate text-sm font-medium text-fg-1">
                    {p.anzeigename || p.benutzername}
                  </p>
                  {p.ist_betreiber && <Badge tone="accent">{t('verwaltung.betreiber')}</Badge>}
                  {p.zwei_faktor_aktiv && (
                    <ShieldCheck
                      className="size-3.5 shrink-0 text-success"
                      aria-label={t('sicherheit.aktiv')}
                    />
                  )}
                </div>
                <p className="mb-0 truncate text-[12px] text-fg-4">
                  <span className="font-mono">{p.benutzername}</span>
                  {p.kontaktadresse ? ` · ${p.kontaktadresse}` : ''}
                </p>
                {p.adresse_doppelt && (
                  <div className="mt-1">
                    <Badge tone="warning">{t('account.emailDuplicate')}</Badge>
                  </div>
                )}
                {/* Die Anbieter, mit denen das Konto verknüpft ist, als kleine Marken; das Kreuz daneben löst. */}
                {p.anbieter.length > 0 && (
                  <div className="mt-1 flex flex-wrap items-center gap-1.5" data-testid="konto-anbieter">
                    {p.anbieter.map((a) => (
                      <span key={a.id} className="inline-flex items-center gap-0.5">
                        <Badge tone="neutral">{a.label}</Badge>
                        <IconButton
                          icon={<Unlink />}
                          size="sm"
                          label={t('anmeldeweg.verknuepfung_loesen_mit', { wer: p.anzeigename || p.benutzername, name: a.label })}
                          onClick={() => void verknuepfungLoesen(p, a)}
                        />
                      </span>
                    ))}
                  </div>
                )}
                <p className="mb-0 truncate text-[11px] text-fg-4">
                  {t('verwaltung.postfaecher_zahl', { count: p.postfaecher })}
                </p>
              </div>

              {/* ⚠️ Der Betreiber hat keinen Papierkorb: Danach könnte niemand
                  mehr die Verwaltung öffnen, und aus der Anwendung heraus führt
                  kein Weg zurück. */}
              {/* ⚠️ **Der teuerste Knopf der Verwaltung.** Wer ihn drückt,
                  gibt die Verwaltung ab und kann sie sich nicht zurückholen.
                  Deshalb steht das eigene Kennwort davor — und deshalb ist er
                  ein stiller Knopf, kein bunter. */}
              {/* ⚠️ **Die Ausnahmeliste, nicht die Einladungsliste.** Ab Werk
                  darf jedes Konto; wer einzelne aussperren will, tut es hier.
                  Der Riegel der Installation steht darüber und ist ab Werk zu —
                  solange der nicht offen ist, ändert dieser Haken nichts, und
                  die Zeile darunter sagt das auch. */}
              <IconButton
                icon={<Pencil />}
                label={`${t('account.username')}: ${p.anzeigename || p.benutzername}`}
                onClick={() => void namenAendern(p, 'benutzername')}
              />
              <IconButton
                icon={<UserPen />}
                label={`${t('account.displayName')}: ${p.anzeigename || p.benutzername}`}
                onClick={() => void namenAendern(p, 'anzeigename')}
              />
              {p.kontaktadresse && (
                <IconButton
                  icon={<AtSign />}
                  label={`${t('account.emailRemove')}: ${p.anzeigename || p.benutzername}`}
                  onClick={() => void adresseEntfernen(p)}
                />
              )}
              {!p.ist_betreiber && (
                <IconButton
                  icon={<KeyRound />}
                  label={`${t('account.resetLink')}: ${p.anzeigename || p.benutzername}`}
                  onClick={() => void passwortLink(p)}
                />
              )}
              <IconButton
                icon={p.ki_erlaubt ? <Sparkles /> : <SparklesIcon className="opacity-40" />}
                label={t(p.ki_erlaubt ? 'verwaltung.ki_konto_aus' : 'verwaltung.ki_konto_an', {
                  wer: p.anzeigename || p.benutzername,
                })}
                onClick={() => void kiUmlegen(p)}
              />

              {!p.ist_betreiber && (
                <IconButton
                  icon={<Crown />}
                  label={t('verwaltung.betreiber_uebergeben', {
                    wer: p.anzeigename || p.benutzername,
                  })}
                  onClick={() => void uebergeben(p)}
                />
              )}
              {!p.ist_betreiber && (
                <IconButton
                  icon={<Trash2 />}
                  label={t('verwaltung.benutzer_entfernen')}
                  onClick={() => void entfernen(p)}
                />
              )}
            </li>
          ))}
        </ul>
      </section>

      {bestand.einladungen.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">
            {t('verwaltung.offene_einladungen')}
          </h2>
          <ul className="flex list-none flex-col gap-2 p-0">
            {bestand.einladungen.map((e) => (
              <li
                key={e.id}
                className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
              >
                <Mail aria-hidden className="size-4 shrink-0 text-fg-4" />
                <div className="min-w-0 flex-1">
                  {/* Neue Einladungen tragen keinen Benutzernamen; Einladungen von vorher zeigen ihren. */}
                  <p className="mb-0 truncate text-sm text-fg-1">
                    {e.anzeigename || e.benutzername || e.adresse || t('verwaltung.einladung_ohne_namen')}
                  </p>
                  <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{e.adresse}</p>
                </div>
                {/* ⚠️ Abgelaufene bleiben sichtbar — sonst verschwindet eine
                    Einladung lautlos und der Betreiber wartet auf jemanden,
                    der nie einen gültigen Link hatte. */}
                <Badge tone={e.abgelaufen ? 'warning' : 'neutral'}>
                  {e.abgelaufen
                    ? t('verwaltung.abgelaufen')
                    : t('verwaltung.gilt_bis', {
                        wann: new Date(e.laeuft_ab).toLocaleDateString(i18n.language),
                      })}
                </Badge>
                <IconButton
                  icon={<Trash2 />}
                  label={t('verwaltung.einladung_zuruecknehmen')}
                  onClick={() => void zuruecknehmen(e)}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div>
        <Button
          variant="primary"
          iconLeft={<UserPlus className="size-4" />}
          disabled={!bereit}
          onClick={() => setEinladen(true)}
        >
          {t('verwaltung.einladen')}
        </Button>
      </div>

      {einladen && (
        <Einladungsfenster
          aufSchliessen={() => setEinladen(false)}
          aufFertig={(link) => {
            setEinladen(false)
            if (link) setWeitergeben({ titel: t('verwaltung.einladen'), link })
            void laden()
          }}
        />
      )}

      {weitergeben && (
        <Dialog open title={weitergeben.titel} onClose={() => setWeitergeben(null)}>
          <div className="flex flex-col gap-4">
            <Input label={t('account.resetLinkShown')} value={weitergeben.link} readOnly onFocus={(e) => e.target.select()} />
            <div className="flex gap-2">
              <Button variant="primary" onClick={() => void navigator.clipboard?.writeText(weitergeben.link)}>
                {t('aktion.kopieren')}
              </Button>
              <Button variant="ghost" onClick={() => setWeitergeben(null)}>
                {t('aktion.fertig')}
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {nachfrage}
    </div>
  )
}

function Einladungsfenster({
  aufSchliessen,
  aufFertig,
}: {
  aufSchliessen: () => void
  aufFertig: (link: string) => void
}) {
  const { t } = useTranslation()
  const [adresse, setAdresse] = useState('')
  const [anzeigename, setAnzeigename] = useState('')
  const [tage, setTage] = useState(String(INVITE_DAYS_DEFAULT))
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  async function abschicken() {
    setFehler('')
    setLaeuft(true)
    try {
      const zeile = await api.senden<EinladungsZeile>('/api/benutzer/einladungen', {
        adresse: adresse.trim(),
        anzeigename: anzeigename.trim(),
        tage: Number(tage),
      })
      aufFertig(zeile.link ?? '')
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  /* Kontenmodul (`SCREENS.operatorInvite`): E-Mail und Anzeigename, beide freiwillig, dazu wie lange der Link gilt.
     Einen Benutzernamen legt der Betreiber nicht mehr fest; den wählt der Eingeladene selbst. */
  return (
    <Dialog open title={t('verwaltung.einladen')} onClose={aufSchliessen}>
      <div className="flex flex-col gap-4">
        <Input
          type="email"
          label={t('account.email')}
          hint={t('verwaltung.einladung_adresse_hinweis')}
          placeholder="name@example.com"
          value={adresse}
          onChange={(e) => setAdresse(e.target.value)}
        />
        <Input
          label={t('account.displayName')}
          value={anzeigename}
          onChange={(e) => setAnzeigename(e.target.value)}
        />
        <Select label={t('account.validFor')} value={tage} onChange={(e) => setTage(e.target.value)}>
          {INVITE_DAYS.map((d) => (
            <option key={d} value={String(d)}>
              {t('account.days', { count: d })}
            </option>
          ))}
        </Select>

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        <div className="flex gap-2">
          <Button
            variant="primary"
            loading={laeuft}
            disabled={Boolean(adresse.trim()) && !adresse.includes('@')}
            onClick={() => void abschicken()}
          >
            {t('verwaltung.einladung_abschicken')}
          </Button>
          <Button variant="ghost" onClick={aufSchliessen}>
            {t('aktion.abbrechen')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
