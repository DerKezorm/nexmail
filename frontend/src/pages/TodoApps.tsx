/* Todo-Apps — die eigenen Verbindungen, nicht die des Betreibers.
 *
 * ⚠️ **Mehrere Verbindungen, wie bei den Kalendern.** Zwei Todoist-Konten
 * oder später eine zweite App sind gewollt; deshalb eine Liste mit
 * „Verbinden" darunter, nicht ein einzelner Zugang wie beim KI-Dienst.
 *
 * ⚠️ **Der Token geht nie zurück an die Oberfläche.** Die Zeile zeigt nur, ob
 * die App ihn zuletzt angenommen hat; wer einen neuen will, trennt und
 * verbindet neu.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ExternalLink, ListChecks, Unplug } from 'lucide-react'
import { api } from '../api/client'
import { Button, Input, Select } from '../ds'
import { useNachfrage } from '../components/Nachfrage'
import { servermeldung } from '../lib/servermeldung'
import {
  gruppenname,
  type Verbindung,
  type ZielGruppe,
  type ZielStand,
} from '../lib/aufgabenziele'

/** Wo man den Token findet — nur der Verweis, kein nacherzählter Weg. */
const TODOIST_TOKEN = 'https://app.todoist.com/app/settings/integrations/developer'

export function TodoApps() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [stand, setStand] = useState<ZielStand | null>(null)
  const [gruppen, setGruppen] = useState<ZielGruppe[] | null>(null)
  const [zugang, setZugang] = useState('')
  const [name, setName] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    try {
      const s = await api.holen<ZielStand>('/api/aufgabenziele')
      setStand(s)
      setFehler('')
      // Die Listen nur, wenn es etwas zu wählen gibt: Sie kosten je
      // Verbindung eine Anfrage bei der App.
      setGruppen(
        s.verbindungen.length
          ? await api.holen<ZielGruppe[]>('/api/aufgabenziele/listen')
          : [],
      )
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function verbinden() {
    setLaeuft(true)
    setFehler('')
    try {
      await api.senden('/api/aufgabenziele', { art: 'todoist', zugang, name })
      setZugang('')
      setName('')
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function trennen(v: Verbindung) {
    const ja = await fragen({
      titel: t('todoapps.trennen'),
      text: t('todoapps.trennen_frage', { name: gruppenname(v) }),
      knopf: t('todoapps.trennen'),
      gefaehrlich: true,
    })
    if (!ja) return
    try {
      await api.loeschen(`/api/aufgabenziele/${v.id}`)
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function standardSetzen(ziel: string) {
    try {
      setStand(await api.aendern<ZielStand>('/api/aufgabenziele/standard', { ziel }))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  if (stand === null && !fehler) return <div className="h-24" />

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <p className="mb-0 text-[13px] text-fg-2">{t('todoapps.einleitung')}</p>

      {fehler && (
        <p role="alert" className="mb-0 rounded-md border border-danger bg-surface-1 px-3 py-2 text-[13px] text-fg-1">
          {fehler}
        </p>
      )}

      {stand && stand.verbindungen.length > 0 && (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('todoapps.verbunden')}</h2>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {stand.verbindungen.map((v) => (
              <li key={v.id} className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-[13px] font-semibold text-fg-1">{gruppenname(v)}</span>
                  {/* ⚠️ Ein abgelehnter Token muss hier stehen. Sonst sieht
                      eine App, die nichts mehr meldet, aus wie eine, in der
                      nichts passiert. */}
                  {v.fehler ? (
                    <span className="flex items-center gap-1 text-[12px] text-warning">
                      <AlertTriangle className="size-3.5" aria-hidden />
                      {/* Nur der abgelehnte Token hat einen eigenen Satz:
                          Er ist der eine Fall, in dem der Mensch etwas tun
                          muss. Alles andere versucht der Takt weiter. */}
                      {v.fehler === 'todoist_zugang_ungueltig'
                        ? t('todoapps.token_abgelehnt')
                        : t('todoapps.klemmt')}
                    </span>
                  ) : (
                    <span className="text-[12px] text-fg-3">{t('todoapps.in_ordnung')}</span>
                  )}
                </div>
                <Button
                  variant="ghost"
                  iconLeft={<Unplug className="size-4" />}
                  onClick={() => void trennen(v)}
                >
                  {t('todoapps.trennen')}
                </Button>
              </li>
            ))}
          </ul>

          <Select
            label={t('todoapps.standard')}
            hint={t('todoapps.standard_hinweis')}
            value={stand.standard}
            onChange={(e) => void standardSetzen(e.target.value)}
          >
            <option value="" className="bg-surface-1 text-fg-1">
              {t('todoapps.eigene_liste')}
            </option>
            {/* Die App in jeder Zeile, aus demselben Grund wie im Fenster
                „Zu Aufgabe machen": Geschlossen zeigt die Auswahl keine Gruppe. */}
            {(gruppen ?? []).flatMap((g) =>
              g.listen.map((l) => (
                <option key={l.ziel} value={l.ziel} className="bg-surface-1 text-fg-1">
                  {`${gruppenname(g)} › ${l.name}`}
                </option>
              )),
            )}
            {/* Eine Wahl, deren Liste gerade nicht kam, bleibt sichtbar
                gewählt, statt still auf die eigene Liste zu springen. */}
            {stand.standard &&
              !(gruppen ?? []).some((g) => g.listen.some((l) => l.ziel === stand.standard)) && (
                <option value={stand.standard}>{t('todoapps.liste_unerreichbar')}</option>
              )}
          </Select>
        </section>
      )}

      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
        <h2 className="mb-0 flex items-center gap-2 text-[13px] font-semibold text-fg-1">
          <ListChecks className="size-4 text-fg-3" aria-hidden />
          {t('todoapps.todoist_verbinden')}
        </h2>
        <p className="mb-0 text-[12px] text-fg-3">
          {t('todoapps.todoist_hinweis')}{' '}
          <a
            href={TODOIST_TOKEN}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-accent-text hover:underline"
          >
            {t('todoapps.todoist_wo')}
            <ExternalLink className="size-3" aria-hidden />
          </a>
        </p>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (zugang.trim()) void verbinden()
          }}
        >
          <Input
            label={t('todoapps.token')}
            type="password"
            autoComplete="off"
            mono
            value={zugang}
            onChange={(e) => setZugang(e.target.value)}
          />
          <Input
            label={t('todoapps.name')}
            hint={t('todoapps.name_hinweis')}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
          />
          <div>
            <Button type="submit" variant="primary" disabled={!zugang.trim() || laeuft}>
              {laeuft ? t('todoapps.prueft') : t('todoapps.verbinden')}
            </Button>
          </div>
        </form>
      </section>

      {nachfrage}
    </div>
  )
}
