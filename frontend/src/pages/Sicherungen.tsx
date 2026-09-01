/* Sicherung und Wiederherstellung.
 *
 * ⚠️ **Zwei Dinge auf einer Seite, und sie zu verwechseln tut im Ernstfall
 * weh.** Die Tabelle zeigt **Rücksetzpunkte**: vollständige Kopien neben der
 * Datenbank, für ein missglücktes Update. Stirbt das Volume, sind sie mit weg.
 * Der Knopf „Herunterladen" erzeugt daraus die **Sicherung**: verschlüsselt,
 * ohne Nachrichten, für den Fall, dass dieser Rechner nicht mehr da ist.
 *
 * Beide Sätze stehen in der Oberfläche, nicht nur hier — sonst hält jemand
 * eine Liste auf derselben Platte für eine Sicherung.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, HardDriveDownload, Plus, Trash2, Upload } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import { Badge, Button, Dialog, EmptyState, IconButton, Input, Select } from '../ds'
import { useNachfrage } from '../components/Nachfrage'

interface Ruecksetzpunkt {
  name: string
  groesse: number
  erstellt: string
  art: string
  kommentar: string
  version: string
}

interface Zeitplan {
  takt: string
  behalten: number
}

interface Uebersicht {
  eintraege: Ruecksetzpunkt[]
  zeitplan: Zeitplan
  zuletzt: string
}

interface Anbieter {
  kuerzel: string
  anzeigename: string
  issuer: string
  rueckkehr_adresse: string
}

interface Befund {
  version: string
  erstellt: string
  schluessel_dabei: boolean
  nachrichten_entfernt: number
  adresse_im_archiv: string
  adresse_jetzt: string
  adresse_weicht_ab: boolean
  oidc_anbieter: Anbieter[]
}

const TAKTE = ['aus', 'taeglich', 'woechentlich', 'monatlich']

/** ⚠️ Kurz genug zum Merken wäre zu kurz zum Schützen. */
const MINDESTLAENGE = 8

function groesse(bytes: number): string {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export function Sicherungen() {
  const { t, i18n } = useTranslation()
  const { fragen, fenster } = useNachfrage()

  const [stand, setStand] = useState<Uebersicht | null>(null)
  // ⚠️ Drei Zustände, nicht zwei: „noch nicht geladen" ist nicht „nichts da".
  // Sonst behauptet die Seite bei einem Serverfehler, es gebe keine
  // Sicherungen — und genau so sieht ein Datenverlust aus.
  const [ladefehler, setLadefehler] = useState('')
  const [fehler, setFehler] = useState('')

  const [anlegenOffen, setAnlegenOffen] = useState(false)
  const [kommentar, setKommentar] = useState('')
  const [holen, setHolen] = useState<Ruecksetzpunkt | null>(null)
  const [passwort, setPasswort] = useState('')
  const [passwortWdh, setPasswortWdh] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  const [einspielenOffen, setEinspielenOffen] = useState(false)

  const laden = useCallback(() => {
    api
      .holen<Uebersicht>('/api/sicherung/liste')
      .then((daten) => {
        setStand(daten)
        setLadefehler('')
      })
      .catch((e: unknown) =>
        setLadefehler(e instanceof ApiFehler ? e.detail : t('sicherungen.ladefehler')),
      )
  }, [t])

  useEffect(laden, [laden])

  const passwortStimmt = passwort.length >= MINDESTLAENGE && passwort === passwortWdh

  async function anlegen() {
    setLaeuft(true)
    try {
      await api.senden('/api/sicherung/liste', { kommentar: kommentar.trim() })
      setAnlegenOffen(false)
      setKommentar('')
      setFehler('')
      laden()
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    } finally {
      setLaeuft(false)
    }
  }

  async function herunterladen() {
    if (!holen) return
    setLaeuft(true)
    try {
      await api.herunterladen(
        `/api/sicherung/liste/${encodeURIComponent(holen.name)}/archiv`,
        { passwort },
        holen.name.replace(/\.db$/, '.zip'),
      )
      setHolen(null)
      setPasswort('')
      setPasswortWdh('')
      setFehler('')
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    } finally {
      setLaeuft(false)
    }
  }

  async function entfernen(eintrag: Ruecksetzpunkt) {
    const ja = await fragen({
      titel: t('sicherungen.entfernen_titel'),
      text: t('sicherungen.entfernen_text', {
        wann: new Date(eintrag.erstellt).toLocaleString(i18n.language),
      }),
      knopf: t('einstellungen.entfernen'),
      gefaehrlich: true,
    })
    if (!ja) return
    try {
      await api.loeschen(`/api/sicherung/liste/${encodeURIComponent(eintrag.name)}`)
      laden()
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    }
  }

  async function zeitplanSetzen(werte: Partial<Zeitplan>) {
    if (!stand) return
    const neu = { ...stand.zeitplan, ...werte }
    setStand({ ...stand, zeitplan: neu })
    try {
      await api.aendern('/api/sicherung/zeitplan', neu)
      laden()
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {fenster}

      {fehler && <Warnung text={fehler} />}
      {ladefehler && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[13px] text-fg-1">
          <span className="flex-1">{ladefehler}</span>
          <Button variant="ghost" onClick={laden}>
            {t('sicherungen.nochmal')}
          </Button>
        </div>
      )}

      {/* --- Was das hier ist ------------------------------------------- */}
      <section className="rounded-xl border border-line bg-surface-1 p-4">
        <h2 className="text-[15px] font-medium text-fg-1">{t('sicherungen.titel')}</h2>
        <p className="mt-1 text-[13px] leading-relaxed text-fg-3">
          {t('sicherungen.einleitung')}
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-fg-3">
          ⚠️ {t('sicherungen.warnung_volume')}
        </p>
      </section>

      {/* --- Zeitplan --------------------------------------------------- */}
      {stand && (
        <section className="rounded-xl border border-line bg-surface-1 p-4">
          <h3 className="text-[14px] font-medium text-fg-1">{t('sicherungen.zeitplan')}</h3>
          <div className="mt-3 flex flex-wrap items-end gap-5">
            <Select
              label={t('sicherungen.takt')}
              value={stand.zeitplan.takt}
              onChange={(e) => void zeitplanSetzen({ takt: e.target.value })}
              options={TAKTE.map((takt) => ({
                value: takt,
                label: t(`sicherungen.takt_${takt}`),
              }))}
            />
            <Input
              label={t('sicherungen.behalten')}
              type="number"
              min={1}
              max={50}
              className="w-24"
              defaultValue={stand.zeitplan.behalten}
              key={stand.zeitplan.behalten}
              onBlur={(e) => {
                const zahl = Number(e.target.value)
                if (zahl >= 1 && zahl <= 50 && zahl !== stand.zeitplan.behalten) {
                  void zeitplanSetzen({ behalten: zahl })
                }
              }}
            />
            <p className="max-w-sm flex-1 text-[12px] leading-relaxed text-fg-3">
              {t('sicherungen.behalten_hinweis')}
            </p>
          </div>
        </section>
      )}

      {/* --- Die Liste --------------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[14px] font-medium text-fg-1">{t('sicherungen.liste')}</h3>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setFehler('')
                setEinspielenOffen(true)
              }}
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              {t('sicherungen.einspielen')}
            </Button>
            <Button
              onClick={() => {
                setFehler('')
                setAnlegenOffen(true)
              }}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {t('sicherungen.jetzt_anlegen')}
            </Button>
          </div>
        </div>

        {stand && stand.eintraege.length === 0 && !ladefehler && (
          <EmptyState
            icon={<HardDriveDownload />}
            title={t('sicherungen.leer')}
            description={t('sicherungen.leer_text')}
          />
        )}

        {stand && stand.eintraege.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[44rem] text-left text-[13px]">
              <thead className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-wide text-fg-3">
                <tr>
                  <th className="px-4 py-2.5 font-medium">{t('sicherungen.spalte_wann')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('sicherungen.spalte_art')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('sicherungen.spalte_notiz')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('sicherungen.spalte_fassung')}</th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    {t('sicherungen.spalte_groesse')}
                  </th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {stand.eintraege.map((eintrag) => (
                  <tr key={eintrag.name} className="border-b border-line/60 last:border-0">
                    <td className="whitespace-nowrap px-4 py-2.5 text-fg-1">
                      {new Date(eintrag.erstellt).toLocaleString(i18n.language)}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={eintrag.art === 'manuell' ? 'accent' : 'neutral'}>
                        {t(`sicherungen.art_${eintrag.art}`, {
                          defaultValue: eintrag.art,
                        })}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-fg-3">{eintrag.kommentar || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-fg-3">
                      {eintrag.version || '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right text-fg-3">
                      {groesse(eintrag.groesse)}
                    </td>
                    <td className="px-4 py-2.5">
                      {/* ⚠️ Beide Knöpfe tragen aria-label **und** title. Ein
                          Symbol ohne Namen ist für Vorleseprogramme stumm und
                          für alle anderen ein Ratespiel. */}
                      <div className="flex items-center justify-end gap-1">
                        <IconButton
                          icon={<Download className="h-4 w-4" />}
                          label={t('sicherungen.herunterladen')}
                          onClick={() => {
                            setFehler('')
                            setPasswort('')
                            setPasswortWdh('')
                            setHolen(eintrag)
                          }}
                        />
                        <IconButton
                          icon={<Trash2 className="h-4 w-4" />}
                          label={t('einstellungen.entfernen')}
                          onClick={() => void entfernen(eintrag)}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* --- Anlegen ----------------------------------------------------- */}
      <Dialog
        open={anlegenOffen}
        title={t('sicherungen.jetzt_anlegen')}
        description={t('sicherungen.anlegen_text')}
        onClose={() => setAnlegenOffen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAnlegenOffen(false)}>
              {t('aktion.abbrechen')}
            </Button>
            <Button onClick={() => void anlegen()} disabled={laeuft}>
              {t('sicherungen.anlegen')}
            </Button>
          </>
        }
      >
        <Input
          label={t('sicherungen.notiz')}
          value={kommentar}
          maxLength={200}
          placeholder={t('sicherungen.notiz_beispiel')}
          onChange={(e) => setKommentar(e.target.value)}
        />
      </Dialog>

      {/* --- Herunterladen ------------------------------------------------ */}
      <Dialog
        open={holen !== null}
        title={t('sicherungen.herunterladen')}
        description={t('sicherungen.herunterladen_text')}
        onClose={() => setHolen(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setHolen(null)}>
              {t('aktion.abbrechen')}
            </Button>
            <Button onClick={() => void herunterladen()} disabled={!passwortStimmt || laeuft}>
              {t('sicherungen.herunterladen')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-[12px] leading-relaxed text-fg-3">
            ⚠️ {t('sicherungen.passwort_warnung')}
          </p>
          <Input
            label={t('sicherungen.passwort')}
            type="password"
            autoComplete="new-password"
            value={passwort}
            onChange={(e) => setPasswort(e.target.value)}
          />
          <Input
            label={t('sicherungen.passwort_wdh')}
            type="password"
            autoComplete="new-password"
            value={passwortWdh}
            onChange={(e) => setPasswortWdh(e.target.value)}
            hint={
              passwort && passwort.length < MINDESTLAENGE
                ? t('sicherungen.passwort_kurz', { n: MINDESTLAENGE })
                : passwortWdh && passwort !== passwortWdh
                  ? t('sicherungen.passwort_ungleich')
                  : undefined
            }
          />
        </div>
      </Dialog>

      {einspielenOffen && (
        <Einspielen aufSchliessen={() => setEinspielenOffen(false)} />
      )}
    </div>
  )
}

function Warnung({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[13px] text-fg-1">
      {text}
    </div>
  )
}

/* --- Einspielen ---------------------------------------------------------- *
 *
 * ⚠️ **Zwei Schritte, und der erste fasst nichts an.** Der Grund ist die
 * öffentliche Adresse: Aus ihr baut nexmail die Einladungslinks und die
 * OIDC-Rückkehr. Kommt das Archiv von einer anderen Installation, zeigt sie
 * auf den alten Ort — Einladungen gehen ins Leere, und die Anmeldung über den
 * Anbieter scheitert mit einer Meldung, die nach einem kaputten Anbieter
 * aussieht.
 *
 * Auf **derselben** Maschine ist die Adresse aus dem Archiv die richtige, und
 * dann wird auch nichts gefragt. Ein Hinweis, der immer erscheint, wird nach
 * dem zweiten Mal weggeklickt.
 */
function Einspielen({ aufSchliessen }: { aufSchliessen: () => void }) {
  const { t } = useTranslation()
  const dateifeld = useRef<HTMLInputElement>(null)

  const [datei, setDatei] = useState<File | null>(null)
  const [passwort, setPasswort] = useState('')
  const [befund, setBefund] = useState<Befund | null>(null)
  const [adresseUebernehmen, setAdresseUebernehmen] = useState(true)
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fertig, setFertig] = useState(false)

  async function pruefen() {
    if (!datei) return
    setLaeuft(true)
    setFehler('')
    try {
      const formular = new FormData()
      formular.append('datei', datei)
      formular.append('passwort', passwort)
      setBefund(await api.formular<Befund>('/api/sicherung/pruefen', formular))
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    } finally {
      setLaeuft(false)
    }
  }

  async function einspielen() {
    if (!datei || !befund) return
    setLaeuft(true)
    setFehler('')
    try {
      const formular = new FormData()
      formular.append('datei', datei)
      formular.append('passwort', passwort)
      if (befund.adresse_weicht_ab && adresseUebernehmen) {
        formular.append('adresse', befund.adresse_jetzt)
      }
      await api.formular('/api/sicherung/einspielen', formular)
      setFertig(true)
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
      setLaeuft(false)
    }
  }

  // ⚠️ **Nach dem Einspielen ist die eigene Sitzung tot.** Sie stand in der
  // Datenbank, die es nicht mehr gibt. Ein „weiter" wäre gelogen — hier
  // führt nur ein Weg, und der geht zur Anmeldung.
  if (fertig) {
    return (
      <Dialog
        open
        title={t('sicherungen.fertig_titel')}
        description={t('sicherungen.fertig_text')}
        onClose={() => window.location.reload()}
        footer={
          <Button onClick={() => window.location.reload()}>
            {t('sicherungen.zur_anmeldung')}
          </Button>
        }
      />
    )
  }

  return (
    <Dialog
      open
      width={620}
      title={t('sicherungen.einspielen')}
      description={befund ? undefined : t('sicherungen.einspielen_text')}
      onClose={() => {
        if (!laeuft) aufSchliessen()
      }}
      footer={
        befund ? (
          <>
            <Button variant="ghost" onClick={aufSchliessen} disabled={laeuft}>
              {t('aktion.abbrechen')}
            </Button>
            <Button variant="danger" onClick={() => void einspielen()} disabled={laeuft}>
              {t('sicherungen.jetzt_einspielen')}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={aufSchliessen}>
              {t('aktion.abbrechen')}
            </Button>
            <Button onClick={() => void pruefen()} disabled={!datei || !passwort || laeuft}>
              {t('sicherungen.pruefen')}
            </Button>
          </>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {fehler && <Warnung text={fehler} />}

        {!befund && (
          <>
            <div>
              <span className="mb-1.5 block text-[13px] font-medium text-fg-1">
                {t('sicherungen.datei')}
              </span>
              <input
                ref={dateifeld}
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => setDatei(e.target.files?.[0] ?? null)}
                className="block w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px] text-fg-1 file:mr-3 file:rounded-md file:border-0 file:bg-surface-3 file:px-3 file:py-1.5 file:text-[13px] file:text-fg-1"
              />
            </div>
            <Input
              label={t('sicherungen.passwort')}
              type="password"
              autoComplete="off"
              value={passwort}
              onChange={(e) => setPasswort(e.target.value)}
            />
          </>
        )}

        {befund && (
          <>
            <dl className="rounded-xl border border-line bg-surface-2 px-4 py-3 text-[13px]">
              <Zeile label={t('sicherungen.aus_fassung')}>{befund.version || '—'}</Zeile>
              <Zeile label={t('sicherungen.erstellt_am')}>
                {befund.erstellt ? new Date(befund.erstellt).toLocaleString() : '—'}
              </Zeile>
              <Zeile label={t('sicherungen.schluessel')}>
                {befund.schluessel_dabei
                  ? t('sicherungen.schluessel_dabei')
                  : t('sicherungen.schluessel_fehlt')}
              </Zeile>
            </dl>

            <p className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[12px] leading-relaxed text-fg-1">
              ⚠️ {t('sicherungen.folgen')}
            </p>

            {befund.adresse_weicht_ab && (
              <div className="flex flex-col gap-2 rounded-xl border border-warn/50 bg-warn/10 px-4 py-3">
                <p className="text-[13px] font-medium text-fg-1">
                  {t('sicherungen.adresse_anders')}
                </p>
                <p className="text-[12px] leading-relaxed text-fg-2">
                  {t('sicherungen.adresse_erklaerung')}
                </p>
                <label className="mt-1 flex items-start gap-2 text-[13px] text-fg-1">
                  <input
                    type="radio"
                    className="mt-1"
                    checked={adresseUebernehmen}
                    onChange={() => setAdresseUebernehmen(true)}
                  />
                  <span>
                    <strong className="font-medium">{befund.adresse_jetzt}</strong>
                    <span className="block text-[12px] text-fg-3">
                      {t('sicherungen.adresse_neu_folge')}
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-2 text-[13px] text-fg-1">
                  <input
                    type="radio"
                    className="mt-1"
                    checked={!adresseUebernehmen}
                    onChange={() => setAdresseUebernehmen(false)}
                  />
                  <span>
                    <strong className="font-medium">{befund.adresse_im_archiv}</strong>
                    <span className="block text-[12px] text-fg-3">
                      {t('sicherungen.adresse_alt_folge')}
                    </span>
                  </span>
                </label>
              </div>
            )}

            {befund.oidc_anbieter.length > 0 && (
              <div className="rounded-xl border border-line bg-surface-2 px-4 py-3">
                <p className="text-[13px] font-medium text-fg-1">
                  {t('sicherungen.oidc_titel')}
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-fg-3">
                  {t('sicherungen.oidc_text')}
                </p>
                <ul className="mt-2 flex flex-col gap-2">
                  {befund.oidc_anbieter.map((anbieter) => (
                    <li key={anbieter.kuerzel} className="text-[12px]">
                      <span className="text-fg-1">{anbieter.anzeigename || anbieter.kuerzel}</span>
                      <code className="mt-0.5 block break-all rounded bg-surface-3 px-2 py-1 font-mono text-[11px] text-fg-2">
                        {anbieter.rueckkehr_adresse}
                      </code>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </Dialog>
  )
}

function Zeile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line/60 py-2 last:border-b-0">
      <dt className="text-fg-3">{label}</dt>
      <dd className="font-medium text-fg-1">{children}</dd>
    </div>
  )
}
