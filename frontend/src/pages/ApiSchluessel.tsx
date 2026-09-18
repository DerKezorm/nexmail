/* API-Schlüssel — damit ein Dashboard lesend hineinsieht.
 *
 * ⚠️ **Riegel und eigene Schlüssel an EINEM Ort.** Dieselbe Lehre wie beim
 * KI-Dienst (siehe `KiSeite.tsx`): Liegt die Erlaubnis in der Verwaltung und
 * der Schlüssel in den Einstellungen, findet man die eine Hälfte und hält sie
 * für das Ganze. Der Betreiber sieht den Riegel deshalb hier, über seiner
 * eigenen Liste.
 *
 * ⚠️ **Der Schlüssel steht genau einmal da.** Danach kennt nexmail nur noch
 * seinen Fingerabdruck. Das Fenster lässt sich in diesem Schritt deshalb nicht
 * durch einen Klick daneben schließen: Weg wäre dann auch der Schlüssel.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy, KeyRound, Lock, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { KontoZeile } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Badge, Button, Checkbox, Dialog, IconButton, Input, Select, Switch } from '../ds'
import { BASIS } from '../lib/basis'
import { servermeldung } from '../lib/servermeldung'

type Stufe = 'anzahl' | 'betreff'

interface Eintrag {
  id: string
  name: string
  praefix: string
  stufe: Stufe
  konten: string[]
  angelegt: string
  zuletzt_benutzt: string | null
}

interface Stand {
  erlaubt: boolean
  schluessel: Eintrag[]
}

interface Entwurf {
  id: string | null
  name: string
  stufe: Stufe
  konten: string[]
}

export function ApiSchluessel({ istBetreiber }: { istBetreiber: boolean }) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [stand, setStand] = useState<Stand | null>(null)
  const [konten, setKonten] = useState<KontoZeile[]>([])
  const [ladefehler, setLadefehler] = useState('')
  const [fehler, setFehler] = useState('')
  const [entwurf, setEntwurf] = useState<Entwurf | null>(null)
  const [neu, setNeu] = useState<string | null>(null)
  const [laeuft, setLaeuft] = useState(false)

  const laden = useCallback(async () => {
    try {
      const [s, k] = await Promise.all([
        api.holen<Stand>('/api/apischluessel'),
        api.holen<KontoZeile[]>('/api/konten'),
      ])
      setStand(s)
      setKonten(k)
      setLadefehler('')
    } catch (f) {
      // ⚠️ Ein Fehler darf nicht wie Leere aussehen: Sonst stünde „noch kein
      // Schlüssel" da, obwohl drei Dashboards daran hängen.
      setLadefehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function riegel(an: boolean) {
    setFehler('')
    try {
      await api.aendern('/api/apischluessel/erlaubt', { erlaubt: an })
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function speichern() {
    if (!entwurf) return
    setFehler('')
    setLaeuft(true)
    try {
      const koerper = { name: entwurf.name, stufe: entwurf.stufe, konten: entwurf.konten }
      if (entwurf.id) {
        await api.aendern(`/api/apischluessel/${entwurf.id}`, koerper)
        setEntwurf(null)
      } else {
        const r = await api.senden<{ schluessel: string }>('/api/apischluessel', koerper)
        setNeu(r.schluessel)
      }
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function widerrufen(e: Eintrag) {
    const ja = await fragen({
      titel: t('apischluessel.widerrufen_titel', { name: e.name }),
      text: t('apischluessel.widerrufen_text'),
      knopf: t('apischluessel.widerrufen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    setFehler('')
    try {
      await api.loeschen(`/api/apischluessel/${e.id}`)
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  function schliessen() {
    setEntwurf(null)
    setNeu(null)
    setFehler('')
    /* ⚠️ Wer den neuen Schlüssel gleich im Dashboard eingetragen hat, will
       beim Schließen sehen, dass er benutzt wurde. Ohne das stand „noch nie
       benutzt" da, bis jemand die Seite neu lud. */
    void laden()
  }

  const namen = new Map(konten.map((k) => [k.id, k.anzeigename || k.adresse]))
  const erlaubt = stand?.erlaubt ?? false

  return (
    <div className="flex max-w-[720px] flex-col gap-5">
      <p className="mb-0 text-[13px] text-fg-2">{t('apischluessel.lede')}</p>

      {istBetreiber && stand && (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-[240px] flex-1 flex-col gap-1">
              <span className="flex items-center gap-2 text-[13px] font-semibold text-fg-1">
                <Lock className="size-4 text-fg-4" aria-hidden />
                {t('apischluessel.riegel')}
              </span>
              <p className="mb-0 text-[12px] text-fg-3">{t('apischluessel.riegel_hinweis')}</p>
            </div>
            {/* Breit steht der Schalter rechts in einer Zeile, schmal bricht
                er unter den Hinweis. Ohne shrink-0 drückte der Hinweis seine
                Beschriftung auf drei Zeilen, ohne flex-wrap am Telefon den
                Hinweis auf ein Wort je Zeile. */}
            <div className="shrink-0">
              <Switch
                label={t('apischluessel.riegel_erlauben')}
                checked={erlaubt}
                onCheckedChange={(an) => void riegel(an)}
              />
            </div>
          </div>
        </section>
      )}

      {stand && !erlaubt && (
        <p
          role="status"
          className="mb-0 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-[13px] text-fg-2"
        >
          {istBetreiber ? t('apischluessel.zu_betreiber') : t('apischluessel.zu_benutzer')}
        </p>
      )}

      {ladefehler && (
        <div className="flex items-center gap-3">
          <p role="alert" className="mb-0 flex-1 text-[13px] text-danger">
            {ladefehler}
          </p>
          <Button size="sm" onClick={() => void laden()}>
            {t('apischluessel.nochmal')}
          </Button>
        </div>
      )}

      {fehler && !entwurf && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}

      {stand && (
        <section className="flex flex-col gap-3">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('apischluessel.meine')}</h2>

          {stand.schluessel.length === 0 ? (
            <p className="mb-0 text-[13px] text-fg-3">{t('apischluessel.leer')}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {stand.schluessel.map((e) => (
                <li
                  key={e.id}
                  className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5"
                >
                  <KeyRound className="size-4 shrink-0 text-fg-4" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-[13px] text-fg-1">{e.name}</span>
                      <Badge tone={e.stufe === 'betreff' ? 'warning' : 'neutral'}>
                        {e.stufe === 'betreff'
                          ? t('apischluessel.stufe_kurz_betreff')
                          : t('apischluessel.stufe_kurz_anzahl')}
                      </Badge>
                    </span>
                    <span className="block truncate text-[12px] text-fg-3">
                      {e.konten.length
                        ? e.konten.map((k) => namen.get(k) ?? k).join(' · ')
                        : t('apischluessel.kein_postfach_mehr')}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-fg-4">
                      {e.praefix}… ·{' '}
                      {e.zuletzt_benutzt
                        ? t('apischluessel.zuletzt', {
                            wann: new Date(e.zuletzt_benutzt).toLocaleString(i18n.language),
                          })
                        : t('apischluessel.nie_benutzt')}
                    </span>
                  </div>
                  <IconButton
                    icon={<Pencil />}
                    label={t('apischluessel.bearbeiten', { name: e.name })}
                    size="sm"
                    onClick={() => {
                      setFehler('')
                      setEntwurf({ id: e.id, name: e.name, stufe: e.stufe, konten: e.konten })
                    }}
                  />
                  <IconButton
                    icon={<Trash2 />}
                    label={t('apischluessel.widerrufen_name', { name: e.name })}
                    size="sm"
                    onClick={() => void widerrufen(e)}
                  />
                </li>
              ))}
            </ul>
          )}

          {/* ⚠️ Ein gesperrter Knopf sagt, warum. Sonst sieht er kaputt aus. */}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              iconLeft={<Plus className="size-4" />}
              disabled={!erlaubt || konten.length === 0}
              onClick={() => {
                setFehler('')
                setNeu(null)
                setEntwurf({
                  id: null,
                  name: '',
                  stufe: 'anzahl',
                  konten: konten.length === 1 ? [konten[0].id] : [],
                })
              }}
            >
              {t('apischluessel.neu')}
            </Button>
            {erlaubt && konten.length === 0 && (
              <span className="text-[12px] text-fg-3">{t('apischluessel.erst_postfach')}</span>
            )}
          </div>

          <Adresse />
        </section>
      )}

      <Dialog
        open={entwurf !== null}
        width={520}
        title={
          neu
            ? t('apischluessel.neu_da_titel')
            : entwurf?.id
              ? t('apischluessel.bearbeiten_titel')
              : t('apischluessel.neu_titel')
        }
        abweisbar={!neu && !laeuft}
        onClose={schliessen}
        footer={
          neu ? undefined : (
            <Button variant="primary" disabled={laeuft} onClick={() => void speichern()}>
              {entwurf?.id ? t('apischluessel.speichern') : t('apischluessel.anlegen')}
            </Button>
          )
        }
      >
        {neu ? (
          <Klartext schluessel={neu} />
        ) : (
          entwurf && (
            <Formular
              entwurf={entwurf}
              konten={konten}
              aendern={setEntwurf}
              fehler={fehler}
            />
          )
        )}
      </Dialog>

      {nachfrage}
    </div>
  )
}

function Formular({
  entwurf,
  konten,
  aendern,
  fehler,
}: {
  entwurf: Entwurf
  konten: KontoZeile[]
  aendern: (e: Entwurf) => void
  fehler: string
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-4">
      <Input
        label={t('apischluessel.name')}
        hint={t('apischluessel.name_hinweis')}
        placeholder={t('apischluessel.name_beispiel')}
        maxLength={80}
        value={entwurf.name}
        onChange={(e) => aendern({ ...entwurf, name: e.target.value })}
      />
      <Select
        label={t('apischluessel.stufe')}
        value={entwurf.stufe}
        onChange={(e) => aendern({ ...entwurf, stufe: e.target.value as Stufe })}
        options={[
          { value: 'anzahl', label: t('apischluessel.stufe_anzahl') },
          { value: 'betreff', label: t('apischluessel.stufe_betreff') },
        ]}
        hint={
          entwurf.stufe === 'betreff'
            ? t('apischluessel.stufe_betreff_hinweis')
            : t('apischluessel.stufe_anzahl_hinweis')
        }
      />
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium text-fg-2">
          {t('apischluessel.postfaecher')}
        </legend>
        {konten.map((k) => (
          <Checkbox
            key={k.id}
            label={k.anzeigename || k.adresse}
            description={k.anzeigename && k.anzeigename !== k.adresse ? k.adresse : undefined}
            checked={entwurf.konten.includes(k.id)}
            onCheckedChange={(an) =>
              aendern({
                ...entwurf,
                konten: an
                  ? [...entwurf.konten, k.id]
                  : entwurf.konten.filter((x) => x !== k.id),
              })
            }
          />
        ))}
        <p className="mb-0 text-[12px] text-fg-3">{t('apischluessel.postfaecher_hinweis')}</p>
      </fieldset>
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
    </div>
  )
}

/** Der Klartext, einmal. Mit Kopierknopf, der auch ohne HTTPS geht.
 *
 * ⚠️ **`navigator.clipboard` gibt es nur in einem sicheren Kontext.** Ein
 * nexmail unter `http://nas:8080` im eigenen Netz ist keiner; dort fehlt die
 * Schnittstelle ganz. Dann wird das Feld markiert und über `execCommand`
 * kopiert, und notfalls steht der Schlüssel markiert zum Abschreiben da.
 */
function Klartext({ schluessel }: { schluessel: string }) {
  const { t } = useTranslation()
  const huelle = useRef<HTMLDivElement>(null)
  const [kopiert, setKopiert] = useState(false)

  function markieren() {
    huelle.current?.querySelector('input')?.select()
  }

  async function kopieren() {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(schluessel)
      } else {
        markieren()
        document.execCommand('copy')
      }
      setKopiert(true)
      window.setTimeout(() => setKopiert(false), 2000)
    } catch {
      markieren()
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="mb-0 text-[13px] text-fg-2">{t('apischluessel.einmal')}</p>
      <div className="flex items-end gap-2">
        <div ref={huelle} className="min-w-0 flex-1">
          <Input
            aria-label={t('apischluessel.schluessel')}
            readOnly
            mono
            value={schluessel}
            onFocus={(e) => e.currentTarget.select()}
          />
        </div>
        <Button
          iconLeft={kopiert ? <Check className="size-4" /> : <Copy className="size-4" />}
          onClick={() => void kopieren()}
        >
          {kopiert ? t('apischluessel.kopiert') : t('apischluessel.kopieren')}
        </Button>
      </div>
      <Adresse />
    </div>
  )
}

/** Welche Adresse ins Dashboard gehört. Samt Unterpfad, falls es einen gibt. */
function Adresse() {
  const { t } = useTranslation()
  const adresse = `${window.location.origin}${BASIS}`
  return (
    <p className="mb-0 text-[12px] text-fg-3">
      {t('apischluessel.adresse')}{' '}
      <span className="font-mono text-fg-2">{adresse}</span>
    </p>
  )
}
