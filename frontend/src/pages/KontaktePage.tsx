/* Das Adressbuch.
 *
 * Aufteilung wie im Mailteil: links die Liste, rechts der Eintrag. Wer sich in
 * nexmail zurechtfindet, findet sich auch hier zurecht — eine zweite
 * Anordnung für dieselbe Sache wäre eine zweite Sache zum Lernen.
 *
 * ⚠️ **Aufgeschnapptes ist gekennzeichnet.** nexmail sammelt Empfänger aus
 * „Gesendet" ein; ohne sichtbaren Unterschied weiß später niemand mehr, was er
 * selbst gepflegt hat und was von allein kam — und traut sich deshalb nicht,
 * aufzuräumen.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Plus, Trash2, Upload, UserRoundPlus, Users } from 'lucide-react'
import { api } from '../api/client'
import { Badge, Button, Checkbox, EmptyState, IconButton, Input } from '../ds'
import { useNachfrage } from '../components/Nachfrage'
import { appPfad } from '../lib/basis'
import { servermeldung } from '../lib/servermeldung'

export interface Kontakt {
  id: number
  name: string
  adresse: string
  firma: string
  telefon: string
  notiz: string
  quelle: string
  verwendet: number
}

/* Ein Verteiler — ein Eingabehelfer beim Adressieren, kein Mailbegriff.
 * In der Mail stehen nur die Einzeladressen der Mitglieder. */
export interface Gruppe {
  id: number
  name: string
  mitglieder: number
  mitglied_ids: number[]
  adressen: string[]
}

const LEER: Omit<Kontakt, 'id' | 'quelle' | 'verwendet'> = {
  name: '',
  adresse: '',
  firma: '',
  telefon: '',
  notiz: '',
}

export function KontaktePage() {
  const { t } = useTranslation()

  const [liste, setListe] = useState<Kontakt[]>([])
  const [suche, setSuche] = useState('')
  const [gewaehlt, setGewaehlt] = useState<number | null>(null)
  const [entwurf, setEntwurf] = useState<typeof LEER | null>(null)
  const [gruppen, setGruppen] = useState<Gruppe[]>([])
  const [gruppeGewaehlt, setGruppeGewaehlt] = useState<number | null>(null)
  const [gruppeNeu, setGruppeNeu] = useState(false)
  const [fehler, setFehler] = useState('')
  const [meldung, setMeldung] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const dateifeld = useRef<HTMLInputElement>(null)
  const { fragen, fenster: nachfrage } = useNachfrage()

  const laden = useCallback(async (s: string) => {
    const roh = await api.holen<Kontakt[]>(`/api/kontakte?suche=${encodeURIComponent(s)}`)
    setListe(roh)
    return roh
  }, [])

  const gruppenLaden = useCallback(async () => {
    setGruppen(await api.holen<Gruppe[]>('/api/kontakte/gruppen'))
  }, [])

  useEffect(() => {
    // Kurz warten, sonst eine Abfrage je Tastendruck.
    const uhr = window.setTimeout(() => void laden(suche).catch(() => setListe([])), 200)
    return () => window.clearTimeout(uhr)
  }, [suche, laden])

  useEffect(() => {
    void gruppenLaden().catch(() => setGruppen([]))
  }, [gruppenLaden])

  const offen = liste.find((k) => k.id === gewaehlt) ?? null
  const gruppeOffen = gruppen.find((g) => g.id === gruppeGewaehlt) ?? null

  async function mit<T>(tun: () => Promise<T>, erfolg = ''): Promise<T | null> {
    setFehler('')
    setMeldung('')
    setLaeuft(true)
    try {
      const ergebnis = await tun()
      await laden(suche)
      // Die Gruppen haengen an den Kontakten (Mitgliederzahl!) — nach jeder
      // Handlung frisch holen, sonst zaehlt die Liste Geloeschte weiter mit.
      await gruppenLaden()
      if (erfolg) setMeldung(erfolg)
      return ergebnis
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return null
    } finally {
      setLaeuft(false)
    }
  }

  async function gruppeSpeichern(name: string, kontaktIds: number[]) {
    if (gruppeNeu) {
      const neu = await mit(async () => {
        const g = await api.senden<Gruppe>('/api/kontakte/gruppen', { name })
        if (kontaktIds.length > 0) {
          await api.aendern<Gruppe>(`/api/kontakte/gruppen/${g.id}/mitglieder`, {
            kontakt_ids: kontaktIds,
          })
        }
        return g
      })
      if (neu) {
        setGruppeNeu(false)
        setGruppeGewaehlt(neu.id)
      }
      return
    }
    if (!gruppeOffen) return
    await mit(async () => {
      if (name !== gruppeOffen.name) {
        await api.flicken<Gruppe>(`/api/kontakte/gruppen/${gruppeOffen.id}`, { name })
      }
      await api.aendern<Gruppe>(`/api/kontakte/gruppen/${gruppeOffen.id}/mitglieder`, {
        kontakt_ids: kontaktIds,
      })
    })
  }

  async function gruppeEntfernen(g: Gruppe) {
    // ⚠️ Die Rueckfrage nennt die Mitgliederzahl und sagt dazu, dass die
    // Kontakte bleiben — sonst liest jemand „entfernen" und fuerchtet um
    // sein Adressbuch.
    const ja = await fragen({
      titel: t('kontakte.gruppe_entfernen'),
      text:
        g.mitglieder === 0
          ? t('kontakte.gruppe_entfernen_text_leer', { name: g.name })
          : t('kontakte.gruppe_entfernen_text', { name: g.name, count: g.mitglieder }),
      knopf: t('kontakte.gruppe_entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(async () => {
      await api.loeschen(`/api/kontakte/gruppen/${g.id}`)
      setGruppeGewaehlt(null)
    })
  }

  async function speichern(felder: typeof LEER) {
    if (entwurf && gewaehlt === null) {
      const neu = await mit(() => api.senden<Kontakt>('/api/kontakte', felder))
      if (neu) {
        setEntwurf(null)
        setGewaehlt(neu.id)
      }
      return
    }
    if (offen) {
      await mit(() => api.flicken<Kontakt>(`/api/kontakte/${offen.id}`, felder))
      setEntwurf(null)
    }
  }

  async function vcardEinlesen(datei: File) {
    const formular = new FormData()
    formular.append('datei', datei)
    const stand = await mit(() =>
      api.formular<{ neu: number; ergaenzt: number }>('/api/kontakte/vcard', formular),
    )
    if (stand) setMeldung(t('kontakte.eingelesen', stand))
  }

  return (
    <div className="flex min-h-0 flex-1 bg-canvas">
      {/* --- Liste --------------------------------------------------- */}
      <div className="flex w-[320px] shrink-0 flex-col border-r border-line">
        <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line-subtle px-2">
          <IconButton
            icon={<Plus />}
            label={t('kontakte.neu')}
            size="sm"
            onClick={() => {
              setGewaehlt(null)
              setGruppeGewaehlt(null)
              setGruppeNeu(false)
              setEntwurf({ ...LEER })
            }}
          />
          <IconButton
            icon={<UserRoundPlus />}
            label={t('kontakte.einsammeln')}
            size="sm"
            onClick={() =>
              void mit(
                () => api.senden<{ neu: number }>('/api/kontakte/einsammeln', {}),
                t('kontakte.eingesammelt'),
              )
            }
          />
          <span aria-hidden className="mx-1 h-5 w-px bg-line" />
          <IconButton
            icon={<Upload />}
            label={t('kontakte.einlesen')}
            size="sm"
            onClick={() => dateifeld.current?.click()}
          />
          <IconButton
            icon={<Download />}
            label={t('kontakte.ausfuehren')}
            size="sm"
            onClick={() => {
              window.location.href = appPfad('/api/kontakte/vcard')
            }}
          />
          <span className="flex-1" />
          <span className="pr-1 text-[11px] text-fg-4">{liste.length}</span>
        </div>

        <input
          ref={dateifeld}
          type="file"
          accept=".vcf,text/vcard"
          className="sr-only"
          onChange={(e) => {
            const datei = e.target.files?.[0]
            if (datei) void vcardEinlesen(datei)
            e.target.value = ''
          }}
        />

        <div className="shrink-0 border-b border-line-subtle p-2">
          <Input
            placeholder={t('kontakte.suchen')}
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
          />
        </div>

        {/* --- Gruppen: Verteiler als Eingabehelfer beim Adressieren --- */}
        <div className="shrink-0 border-b border-line-subtle">
          <div className="flex h-9 items-center gap-1 pr-1 pl-3">
            <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
              {t('kontakte.gruppen')}
            </span>
            <span className="flex-1" />
            <IconButton
              icon={<Plus />}
              label={t('kontakte.gruppe_neu')}
              size="sm"
              onClick={() => {
                setGewaehlt(null)
                setEntwurf(null)
                setGruppeGewaehlt(null)
                setGruppeNeu(true)
                setFehler('')
                setMeldung('')
              }}
            />
          </div>
          {gruppen.length === 0 ? (
            <p className="px-3 pb-2 text-[12px] text-fg-4">{t('kontakte.gruppe_leer')}</p>
          ) : (
            <div className="max-h-44 overflow-y-auto pb-1">
              {gruppen.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => {
                    setGewaehlt(null)
                    setEntwurf(null)
                    setGruppeNeu(false)
                    setGruppeGewaehlt(g.id)
                    setFehler('')
                    setMeldung('')
                  }}
                  className={
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left ' +
                    'transition-colors duration-[var(--dur-fast)] ' +
                    (g.id === gruppeGewaehlt && !gruppeNeu ? 'bg-accent-soft' : 'hover:bg-surface-2')
                  }
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">{g.name}</span>
                  <Badge tone="neutral">{t('kontakte.gruppe_zahl', { count: g.mitglieder })}</Badge>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {liste.length === 0 ? (
            <p className="px-3 py-6 text-center text-[13px] text-fg-4">{t('kontakte.leer')}</p>
          ) : (
            liste.map((k) => (
              <button
                key={k.id}
                type="button"
                onClick={() => {
                  setGewaehlt(k.id)
                  setEntwurf(null)
                  setGruppeGewaehlt(null)
                  setGruppeNeu(false)
                  setFehler('')
                  setMeldung('')
                }}
                className={
                  'flex w-full flex-col items-start gap-0.5 border-b border-line-subtle px-3 py-2 text-left ' +
                  'transition-colors duration-[var(--dur-fast)] ' +
                  (k.id === gewaehlt ? 'bg-accent-soft' : 'hover:bg-surface-2')
                }
              >
                <span className="flex w-full items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg-1">
                    {k.name || k.adresse}
                  </span>
                  {/* ⚠️ Aufgeschnapptes muss man sehen — sonst traut sich
                      niemand, das Adressbuch aufzuräumen. */}
                  {k.quelle === 'gesammelt' && (
                    <Badge tone="neutral">{t('kontakte.gesammelt')}</Badge>
                  )}
                </span>
                <span className="w-full truncate text-[12px] text-fg-3">{k.adresse}</span>
              </button>
            ))
          )}
        </div>

        <div className="shrink-0 border-t border-line-subtle p-2">
          <Button
            size="sm"
            variant="ghost"
            fullWidth
            iconLeft={<Trash2 className="size-4" />}
            disabled={laeuft || !liste.some((k) => k.quelle === 'gesammelt')}
            onClick={() =>
              void mit(
                () => api.loeschen<{ entfernt: number }>('/api/kontakte/gesammelte'),
                t('kontakte.aufgeraeumt'),
              )
            }
          >
            {t('kontakte.gesammelte_weg')}
          </Button>
        </div>
      </div>

      {/* --- Eintrag ------------------------------------------------- */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {gruppeNeu || gruppeOffen ? (
          <GruppenFormular
            key={gruppeNeu ? 'gruppe-neu' : gruppeOffen!.id}
            gruppe={gruppeNeu ? null : gruppeOffen}
            laeuft={laeuft}
            fehler={fehler}
            meldung={meldung}
            aufSpeichern={gruppeSpeichern}
            aufEntfernen={gruppeOffen ? () => void gruppeEntfernen(gruppeOffen) : undefined}
          />
        ) : entwurf || offen ? (
          <Formular
            key={gewaehlt ?? 'neu'}
            werte={entwurf ?? {
              name: offen!.name,
              adresse: offen!.adresse,
              firma: offen!.firma,
              telefon: offen!.telefon,
              notiz: offen!.notiz,
            }}
            neu={gewaehlt === null}
            laeuft={laeuft}
            fehler={fehler}
            meldung={meldung}
            aufSpeichern={speichern}
            aufEntfernen={
              offen
                ? () =>
                    void mit(async () => {
                      await api.loeschen(`/api/kontakte/${offen.id}`)
                      setGewaehlt(null)
                    })
                : undefined
            }
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              icon={<Users />}
              title={t('kontakte.keine_auswahl')}
              description={t('kontakte.keine_auswahl_text')}
            />
          </div>
        )}
      </div>

      {nachfrage}
    </div>
  )
}

/* Das Formular fuer eine Gruppe: Name plus Mehrfachauswahl aus dem Adressbuch.
 *
 * ⚠️ **Die Auswahl zeigt das ganze Adressbuch, nicht die gefilterte Liste
 * links.** Wer links nach „anna" gesucht hat, soll rechts trotzdem Bernd
 * ankreuzen koennen — deshalb holt das Formular seine Kontakte selbst und
 * bringt einen eigenen Filter mit. */
function GruppenFormular({
  gruppe,
  laeuft,
  fehler,
  meldung,
  aufSpeichern,
  aufEntfernen,
}: {
  gruppe: Gruppe | null
  laeuft: boolean
  fehler: string
  meldung: string
  aufSpeichern: (name: string, kontaktIds: number[]) => Promise<void>
  aufEntfernen?: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(gruppe?.name ?? '')
  const [gewaehlt, setGewaehlt] = useState<Set<number>>(new Set(gruppe?.mitglied_ids ?? []))
  const [alle, setAlle] = useState<Kontakt[] | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api
      .holen<Kontakt[]>('/api/kontakte')
      .then(setAlle)
      .catch(() => setAlle([]))
  }, [])

  const kern = filter.trim().toLowerCase()
  const sichtbar = (alle ?? []).filter(
    (k) =>
      !kern ||
      k.name.toLowerCase().includes(kern) ||
      k.adresse.toLowerCase().includes(kern),
  )

  return (
    <form
      className="flex max-w-[560px] flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        void aufSpeichern(name.trim(), [...gewaehlt])
      }}
    >
      <Input
        label={t('kontakte.gruppe_name')}
        value={name}
        autoFocus={gruppe === null}
        onChange={(e) => setName(e.target.value)}
      />

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('kontakte.gruppe_mitglieder')}
        </span>
        {alle !== null && alle.length === 0 ? (
          <p className="text-[13px] text-fg-4">{t('kontakte.gruppe_keine_kontakte')}</p>
        ) : (
          <div className="flex flex-col overflow-hidden rounded-md border border-line">
            <div className="border-b border-line-subtle p-2">
              <Input
                size="sm"
                placeholder={t('kontakte.gruppe_mitglieder_filtern')}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <div className="max-h-72 overflow-y-auto p-2">
              <div className="flex flex-col gap-1.5">
                {sichtbar.map((k) => (
                  <Checkbox
                    key={k.id}
                    label={k.name || k.adresse}
                    description={k.name ? k.adresse : undefined}
                    checked={gewaehlt.has(k.id)}
                    onCheckedChange={(an) =>
                      setGewaehlt((alt) => {
                        const neu = new Set(alt)
                        if (an) neu.add(k.id)
                        else neu.delete(k.id)
                        return neu
                      })
                    }
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}
      {meldung && <p className="text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" loading={laeuft} disabled={!name.trim()}>
          {gruppe === null ? t('kontakte.anlegen') : t('kontakte.speichern')}
        </Button>
        {aufEntfernen && (
          <Button variant="danger" iconLeft={<Trash2 className="size-4" />} onClick={aufEntfernen}>
            {t('kontakte.gruppe_entfernen')}
          </Button>
        )}
      </div>
    </form>
  )
}

function Formular({
  werte,
  neu,
  laeuft,
  fehler,
  meldung,
  aufSpeichern,
  aufEntfernen,
}: {
  werte: typeof LEER
  neu: boolean
  laeuft: boolean
  fehler: string
  meldung: string
  aufSpeichern: (f: typeof LEER) => void
  aufEntfernen?: () => void
}) {
  const { t } = useTranslation()
  const [felder, setFelder] = useState(werte)

  useEffect(() => setFelder(werte), [werte])

  const setzen = (teil: Partial<typeof LEER>) => setFelder((alt) => ({ ...alt, ...teil }))

  return (
    <form
      className="flex max-w-[560px] flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        aufSpeichern(felder)
      }}
    >
      <Input
        label={t('kontakte.adresse')}
        mono
        autoComplete="email"
        value={felder.adresse}
        onChange={(e) => setzen({ adresse: e.target.value })}
      />
      <Input
        label={t('kontakte.name')}
        value={felder.name}
        onChange={(e) => setzen({ name: e.target.value })}
      />
      <Input
        label={t('kontakte.firma')}
        value={felder.firma}
        onChange={(e) => setzen({ firma: e.target.value })}
      />
      <Input
        label={t('kontakte.telefon')}
        value={felder.telefon}
        onChange={(e) => setzen({ telefon: e.target.value })}
      />
      <label className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('kontakte.notiz')}
        </span>
        <textarea
          rows={4}
          value={felder.notiz}
          onChange={(e) => setzen({ notiz: e.target.value })}
          className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none"
        />
      </label>

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}
      {meldung && <p className="text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" loading={laeuft}>
          {neu ? t('kontakte.anlegen') : t('kontakte.speichern')}
        </Button>
        {aufEntfernen && (
          <Button variant="danger" iconLeft={<Trash2 className="size-4" />} onClick={aufEntfernen}>
            {t('kontakte.entfernen')}
          </Button>
        )}
      </div>
    </form>
  )
}
