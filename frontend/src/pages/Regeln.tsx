/* Regeln — wenn etwas zutrifft, tu etwas.
 *
 * ⚠️ **Die Reihenfolge ist Teil der Bedeutung.** Regeln laufen von oben nach
 * unten; deshalb steht die Nummer sichtbar davor und lässt sich verschieben.
 * Eine Liste, deren Reihenfolge wirkt, aber nicht zu sehen ist, erzeugt
 * Ergebnisse, die niemand erklären kann.
 *
 * ⚠️ **„Danach aufhören" wird erklärt, nicht nur angeboten.** Ohne diesen
 * Haken läuft eine Nachricht durch alle Regeln, und die letzte schiebt sie
 * dorthin zurück, wo die erste sie gerade weggeholt hat — der häufigste Grund
 * für „meine Regeln tun nichts".
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowUp, Plus, SlidersHorizontal, Trash2 } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Button, EmptyState, IconButton, Input, Select, Switch } from '../ds'

interface Bedingung {
  feld: string
  vergleich: string
  wert: string
}

interface Aktion {
  art: string
  wert: string
}

export interface RegelZeile {
  id: number
  name: string
  aktiv: boolean
  reihenfolge: number
  konto_id: string
  verknuepfung: string
  bedingungen: Bedingung[]
  aktionen: Aktion[]
  stopp: boolean
}

interface OrdnerZeile {
  id: number
  name: string
  pfad: string
}

interface KontoZeile {
  id: string
  adresse: string
  anzeigename: string
}

const FELDER = ['von', 'an', 'betreff', 'inhalt']
const VERGLEICHE = ['enthaelt', 'enthaelt_nicht', 'ist', 'beginnt', 'endet']
const ARTEN = ['verschieben', 'gelesen', 'markieren', 'loeschen']

function leereRegel(): RegelZeile {
  return {
    id: 0,
    name: '',
    aktiv: true,
    reihenfolge: 0,
    konto_id: '',
    verknuepfung: 'und',
    bedingungen: [{ feld: 'von', vergleich: 'enthaelt', wert: '' }],
    aktionen: [{ art: 'gelesen', wert: '' }],
    stopp: true,
  }
}

export function Regeln() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [liste, setListe] = useState<RegelZeile[] | null>(null)
  const [konten, setKonten] = useState<KontoZeile[]>([])
  const [ordner, setOrdner] = useState<Record<string, OrdnerZeile[]>>({})
  const [offen, setOffen] = useState<RegelZeile | null>(null)
  const [fehler, setFehler] = useState('')
  const [meldung, setMeldung] = useState('')

  const laden = useCallback(async () => {
    setListe(await api.holen<RegelZeile[]>('/api/regeln'))
  }, [])

  useEffect(() => {
    void laden().catch(() => setListe([]))
    void api
      .holen<KontoZeile[]>('/api/konten')
      .then(async (k) => {
        setKonten(k)
        const karte: Record<string, OrdnerZeile[]> = {}
        for (const konto of k) {
          karte[konto.id] = await api.holen<OrdnerZeile[]>(`/api/konten/${konto.id}/ordner`)
        }
        setOrdner(karte)
      })
      .catch(() => setKonten([]))
  }, [laden])

  async function mit<T>(tun: () => Promise<T>, erfolg = '') {
    setFehler('')
    setMeldung('')
    try {
      const ergebnis = await tun()
      await laden()
      if (erfolg) setMeldung(erfolg)
      return ergebnis
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
      return null
    }
  }

  async function speichern(regel: RegelZeile) {
    const nutzdaten = {
      name: regel.name,
      aktiv: regel.aktiv,
      konto_id: regel.konto_id,
      verknuepfung: regel.verknuepfung,
      bedingungen: regel.bedingungen,
      aktionen: regel.aktionen,
      stopp: regel.stopp,
      reihenfolge: regel.reihenfolge,
    }
    const ergebnis = await mit(() =>
      regel.id
        ? api.aendern<RegelZeile>(`/api/regeln/${regel.id}`, nutzdaten)
        : api.senden<RegelZeile>('/api/regeln', nutzdaten),
    )
    if (ergebnis) setOffen(null)
  }

  /** Zwei Regeln tauschen die Plätze. Beide werden gespeichert. */
  async function schieben(index: number, richtung: -1 | 1) {
    if (!liste) return
    const andere = index + richtung
    if (andere < 0 || andere >= liste.length) return
    const a = liste[index]
    const b = liste[andere]
    await mit(async () => {
      await api.aendern(`/api/regeln/${a.id}`, { ...a, reihenfolge: b.reihenfolge })
      await api.aendern(`/api/regeln/${b.id}`, { ...b, reihenfolge: a.reihenfolge })
    })
  }

  if (liste === null) return <div className="h-24" />

  if (offen) {
    return (
      <Formular
        regel={offen}
        konten={konten}
        ordner={ordner}
        fehler={fehler}
        aufAendern={setOffen}
        aufSpeichern={() => void speichern(offen)}
        aufAbbrechen={() => {
          setOffen(null)
          setFehler('')
        }}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button variant="primary" iconLeft={<Plus className="size-4" />} onClick={() => setOffen(leereRegel())}>
          {t('regeln.neu')}
        </Button>
        <span className="flex-1" />
        {meldung && <span className="text-[13px] text-accent-text">{meldung}</span>}
        {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
      </div>

      {liste.length === 0 ? (
        <EmptyState
          icon={<SlidersHorizontal />}
          title={t('regeln.leer')}
          description={t('regeln.leer_text')}
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {liste.map((r, i) => (
            <li
              key={r.id}
              className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5"
            >
              {/* Die Nummer steht sichtbar davor: Die Reihenfolge wirkt. */}
              <span className="w-5 shrink-0 text-right text-[12px] tabular-nums text-fg-4">
                {i + 1}
              </span>
              <button
                type="button"
                onClick={() => setOffen(r)}
                className="min-w-0 flex-1 text-left"
              >
                <span className="block truncate text-[13px] font-medium text-fg-1">{r.name}</span>
                <span className="block truncate text-[12px] text-fg-3">
                  {t(`regeln.zusammenfassung`, {
                    bedingungen: r.bedingungen.length,
                    aktionen: r.aktionen.length,
                  })}
                  {r.stopp ? ` · ${t('regeln.stopp_kurz')}` : ''}
                </span>
              </button>
              <Switch
                checked={r.aktiv}
                label={t('regeln.aktiv')}
                onCheckedChange={(an) =>
                  void mit(() => api.aendern(`/api/regeln/${r.id}`, { ...r, aktiv: an }))
                }
              />
              <IconButton
                icon={<ArrowUp />}
                label={t('regeln.hoch')}
                size="sm"
                disabled={i === 0}
                onClick={() => void schieben(i, -1)}
              />
              <IconButton
                icon={<ArrowDown />}
                label={t('regeln.runter')}
                size="sm"
                disabled={i === liste.length - 1}
                onClick={() => void schieben(i, 1)}
              />
              <IconButton
                icon={<Trash2 />}
                label={t('regeln.entfernen')}
                size="sm"
                onClick={() =>
                  void (async () => {
                    const ja = await fragen({
                      titel: t('regeln.entfernen'),
                      text: t('regeln.entfernen_sicher', { name: r.name }),
                      knopf: t('regeln.entfernen'),
                      gefaehrlich: true,
                    })
                    if (ja !== true) return
                    await mit(() => api.loeschen(`/api/regeln/${r.id}`))
                  })()
                }
              />
            </li>
          ))}
        </ul>
      )}
      {nachfrage}
    </div>
  )
}

function Formular({
  regel,
  konten,
  ordner,
  fehler,
  aufAendern,
  aufSpeichern,
  aufAbbrechen,
}: {
  regel: RegelZeile
  konten: KontoZeile[]
  ordner: Record<string, OrdnerZeile[]>
  fehler: string
  aufAendern: (r: RegelZeile) => void
  aufSpeichern: () => void
  aufAbbrechen: () => void
}) {
  const { t } = useTranslation()

  // Zielordner: nur die des gewählten Postfachs. Eine Regel, die quer über
  // Konten schiebt, gibt es nicht — der Server weist sie ohnehin ab.
  const ziele = regel.konto_id
    ? (ordner[regel.konto_id] ?? [])
    : Object.values(ordner).flat()

  const setzen = (teil: Partial<RegelZeile>) => aufAendern({ ...regel, ...teil })

  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <Input
        label={t('regeln.name')}
        placeholder={t('regeln.name_platzhalter')}
        value={regel.name}
        onChange={(e) => setzen({ name: e.target.value })}
      />

      <Select
        label={t('regeln.postfach')}
        hint={t('regeln.postfach_hinweis')}
        value={regel.konto_id}
        onChange={(e) => setzen({ konto_id: e.target.value })}
      >
        <option value="">{t('regeln.alle_postfaecher')}</option>
        {konten.map((k) => (
          <option key={k.id} value={k.id}>
            {k.adresse}
          </option>
        ))}
      </Select>

      {/* --- Bedingungen ------------------------------------------------- */}
      <fieldset className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
        <legend className="px-1 text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('regeln.wenn')}
        </legend>

        <Select
          label={t('regeln.verknuepfung')}
          value={regel.verknuepfung}
          onChange={(e) => setzen({ verknuepfung: e.target.value })}
        >
          <option value="und">{t('regeln.und')}</option>
          <option value="oder">{t('regeln.oder')}</option>
        </Select>

        {regel.bedingungen.map((b, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <div className="w-[140px]">
              <Select
                label={t('regeln.feld')}
                value={b.feld}
                onChange={(e) => {
                  const neu = [...regel.bedingungen]
                  neu[i] = { ...b, feld: e.target.value }
                  setzen({ bedingungen: neu })
                }}
              >
                {FELDER.map((f) => (
                  <option key={f} value={f}>
                    {t(`regeln.feld_${f}`)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="w-[180px]">
              <Select
                label={t('regeln.vergleich')}
                value={b.vergleich}
                onChange={(e) => {
                  const neu = [...regel.bedingungen]
                  neu[i] = { ...b, vergleich: e.target.value }
                  setzen({ bedingungen: neu })
                }}
              >
                {VERGLEICHE.map((v) => (
                  <option key={v} value={v}>
                    {t(`regeln.vergleich_${v}`)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="min-w-[200px] flex-1">
              <Input
                label={t('regeln.wert')}
                value={b.wert}
                onChange={(e) => {
                  const neu = [...regel.bedingungen]
                  neu[i] = { ...b, wert: e.target.value }
                  setzen({ bedingungen: neu })
                }}
              />
            </div>
            <IconButton
              icon={<Trash2 />}
              label={t('regeln.bedingung_weg')}
              size="sm"
              disabled={regel.bedingungen.length === 1}
              onClick={() => setzen({ bedingungen: regel.bedingungen.filter((_, j) => j !== i) })}
            />
          </div>
        ))}

        {/* ⚠️ Steht der Betreiber auf „Inhalt", muss er wissen, wie weit das
            reicht: Texte holt nexmail erst beim Öffnen. */}
        {regel.bedingungen.some((b) => b.feld === 'inhalt') && (
          <p className="text-[12px] text-warning">{t('regeln.inhalt_hinweis')}</p>
        )}

        <Button
          size="sm"
          iconLeft={<Plus className="size-4" />}
          onClick={() =>
            setzen({
              bedingungen: [...regel.bedingungen, { feld: 'von', vergleich: 'enthaelt', wert: '' }],
            })
          }
        >
          {t('regeln.bedingung_dazu')}
        </Button>
      </fieldset>

      {/* --- Aktionen ---------------------------------------------------- */}
      <fieldset className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
        <legend className="px-1 text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('regeln.dann')}
        </legend>

        {regel.aktionen.map((a, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <div className="w-[200px]">
              <Select
                label={t('regeln.aktion')}
                value={a.art}
                onChange={(e) => {
                  const neu = [...regel.aktionen]
                  neu[i] = { ...a, art: e.target.value, wert: '' }
                  setzen({ aktionen: neu })
                }}
              >
                {ARTEN.map((art) => (
                  <option key={art} value={art}>
                    {t(`regeln.aktion_${art}`)}
                  </option>
                ))}
              </Select>
            </div>
            {a.art === 'verschieben' && (
              <div className="min-w-[220px] flex-1">
                <Select
                  label={t('regeln.zielordner')}
                  value={a.wert}
                  onChange={(e) => {
                    const neu = [...regel.aktionen]
                    neu[i] = { ...a, wert: e.target.value }
                    setzen({ aktionen: neu })
                  }}
                >
                  <option value="">—</option>
                  {ziele.map((o) => (
                    <option key={o.id} value={String(o.id)}>
                      {o.pfad}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <IconButton
              icon={<Trash2 />}
              label={t('regeln.aktion_weg')}
              size="sm"
              disabled={regel.aktionen.length === 1}
              onClick={() => setzen({ aktionen: regel.aktionen.filter((_, j) => j !== i) })}
            />
          </div>
        ))}

        <Button
          size="sm"
          iconLeft={<Plus className="size-4" />}
          onClick={() => setzen({ aktionen: [...regel.aktionen, { art: 'gelesen', wert: '' }] })}
        >
          {t('regeln.aktion_dazu')}
        </Button>
      </fieldset>

      <Switch
        checked={regel.stopp}
        label={t('regeln.stopp')}
        description={t('regeln.stopp_hinweis')}
        onCheckedChange={(an) => setzen({ stopp: an })}
      />

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}

      <div className="flex items-center gap-2">
        <Button variant="primary" onClick={aufSpeichern}>
          {t('regeln.speichern')}
        </Button>
        <Button variant="ghost" onClick={aufAbbrechen}>
          {t('aktion.abbrechen')}
        </Button>
      </div>
    </div>
  )
}
