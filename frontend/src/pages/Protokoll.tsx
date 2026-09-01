/* Das Protokoll ansehen und die Stufe umstellen.
 *
 * ⚠️ **Der Sinn ist die Ferndiagnose.** Wer einen Fehler meldet, soll das
 * Protokoll herunterladen und mitschicken können, ohne in einen Container zu
 * steigen. Deshalb: lesbar in der Oberfläche, filterbar, und als ZIP mit den
 * alten Ständen zum Weitergeben.
 *
 * ⚠️ **Die tiefen Stufen laufen ab, und das steht dabei.** Sonst schaltet
 * jemand „alles" ein, vergisst es, und der Ringpuffer überschreibt genau die
 * Zeilen, die er behalten wollte.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, RefreshCw, Trash2 } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Badge, Button, Input, Select } from '../ds'
import { protokollzeit } from '../lib/format'
import { appPfad } from '../lib/basis'

interface Zeile {
  zeit: string
  stufe: string
  modul: string
  meldung: string
  vorgang: string | null
  benutzer: string | null
}

interface Stand {
  stufe: string
  bis: string | null
  durch_umgebung: boolean
  stufen: string[]
  minuten: number[]
}

const FARBE: Record<string, 'neutral' | 'warning' | 'danger'> = {
  DEBUG: 'neutral',
  INFO: 'neutral',
  WARNING: 'warning',
  ERROR: 'danger',
  CRITICAL: 'danger',
}

export function Protokoll() {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()

  const [stand, setStand] = useState<Stand | null>(null)
  const [zeilen, setZeilen] = useState<Zeile[]>([])
  const [stufe, setStufe] = useState('')
  const [suche, setSuche] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  const laden = useCallback(async () => {
    const frage = new URLSearchParams({ grenze: '300' })
    if (stufe) frage.set('stufe', stufe)
    if (suche.trim()) frage.set('suche', suche.trim())
    setZeilen(await api.holen<Zeile[]>(`/api/protokoll?${frage}`))
  }, [stufe, suche])

  useEffect(() => {
    void api
      .holen<Stand>('/api/protokoll/stand')
      .then(setStand)
      .catch((f) =>
        setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein')),
      )
  }, [t])

  useEffect(() => {
    // Kurz warten, sonst eine Abfrage je Tastendruck.
    const uhr = window.setTimeout(() => void laden().catch(() => setZeilen([])), 250)
    return () => window.clearTimeout(uhr)
  }, [laden])

  async function stufeSetzen(neu: string, minuten: number) {
    setLaeuft(true)
    setFehler('')
    try {
      setStand(await api.aendern<Stand>('/api/protokoll/stufe', { stufe: neu, minuten }))
      await laden()
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setLaeuft(false)
    }
  }

  const tief = stand ? ['ausfuehrlich', 'alles'].includes(stand.stufe) : false

  return (
    <div className="flex flex-col gap-4">
      {/* --- Stufe -------------------------------------------------------- */}
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-[200px]">
            <Select
              label={t('protokoll.stufe')}
              value={stand?.stufe ?? 'normal'}
              disabled={!stand || stand.durch_umgebung || laeuft}
              onChange={(e) => void stufeSetzen(e.target.value, 30)}
            >
              {(stand?.stufen ?? []).map((s) => (
                <option key={s} value={s}>
                  {t(`protokoll.stufe_${s}`)}
                </option>
              ))}
            </Select>
          </div>

          {tief && !stand?.durch_umgebung && (
            <div className="w-[200px]">
              <Select
                label={t('protokoll.dauer')}
                defaultValue="30"
                onChange={(e) => void stufeSetzen(stand!.stufe, Number(e.target.value))}
              >
                {(stand?.minuten ?? []).map((m) => (
                  <option key={m} value={m}>
                    {m === 0 ? t('protokoll.bis_neustart') : t('protokoll.minuten', { count: m })}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>

        {/* ⚠️ Muss dastehen: Sonst klickt man an einer Auswahl herum, die
            nichts tut, und sucht den Fehler bei sich. */}
        {stand?.durch_umgebung && (
          <p className="mb-0 text-[12px] text-warning">{t('protokoll.durch_umgebung')}</p>
        )}
        {stand?.bis && (
          <p className="mb-0 text-[12px] text-fg-3">
            {t('protokoll.faellt_zurueck', {
              zeit: new Date(stand.bis).toLocaleString(i18n.language),
            })}
          </p>
        )}
        <p className="mb-0 text-[12px] text-fg-4">{t('protokoll.was_nicht_drinsteht')}</p>
      </section>

      {/* --- Werkzeuge ---------------------------------------------------- */}
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[220px] flex-1">
          <Input
            label={t('protokoll.suchen')}
            placeholder={t('protokoll.suchen_platzhalter')}
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
          />
        </div>
        <div className="w-[160px]">
          <Select label={t('protokoll.ab_stufe')} value={stufe} onChange={(e) => setStufe(e.target.value)}>
            <option value="">{t('protokoll.alle')}</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </Select>
        </div>
        <Button iconLeft={<RefreshCw className="size-4" />} onClick={() => void laden()}>
          {t('aktion.aktualisieren')}
        </Button>
        <Button
          iconLeft={<Download className="size-4" />}
          onClick={() => {
            window.location.href = appPfad('/api/protokoll/download')
          }}
        >
          {t('protokoll.herunterladen')}
        </Button>
        <Button
          variant="danger"
          iconLeft={<Trash2 className="size-4" />}
          onClick={() =>
            void (async () => {
              const ja = await fragen({
                titel: t('protokoll.leeren'),
                text: t('protokoll.leeren_sicher'),
                knopf: t('protokoll.leeren'),
                gefaehrlich: true,
              })
              if (ja !== true) return
              await api.loeschen('/api/protokoll')
              await laden()
            })()
          }
        >
          {t('protokoll.leeren')}
        </Button>
      </div>

      {fehler && <p className="mb-0 text-[13px] text-danger">{fehler}</p>}

      {/* --- Zeilen ------------------------------------------------------- */}
      <div className="max-h-[520px] overflow-auto rounded-lg border border-line bg-surface-1">
        {zeilen.length === 0 ? (
          <p className="px-3 py-6 text-center text-[13px] text-fg-4">{t('protokoll.leer')}</p>
        ) : (
          <ul className="divide-y divide-line-subtle">
            {zeilen.map((z, i) => (
              <li key={i} className="flex items-start gap-2 px-3 py-1.5">
                <span className="shrink-0 font-mono text-[11px] text-fg-4">
                  {protokollzeit(z.zeit, i18n.language)}
                </span>
                <Badge tone={FARBE[z.stufe] ?? 'neutral'}>{z.stufe}</Badge>
                <span className="min-w-0 flex-1 text-[12px] break-words text-fg-2">
                  {z.meldung}
                </span>
                {z.vorgang && (
                  <span
                    title={t('protokoll.vorgang')}
                    className="shrink-0 font-mono text-[11px] text-fg-4"
                  >
                    {z.vorgang}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {nachfrage}
    </div>
  )
}
