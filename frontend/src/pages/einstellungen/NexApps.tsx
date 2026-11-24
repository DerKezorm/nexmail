/* Die nex-Apps unter „Verbindungen": nextime und nextasks als Karten, wie in
 * nextime › Einstellungen › Verbindungen (MAIL-1 AC-2).
 *
 * ⚠️ **Nur die nex-Apps bekommen Karten**, um sie in den Vordergrund zu
 * stellen (Entscheidung 23.11.2026). Todoist, Webhook, iPhone und die
 * Programmschlüssel stehen darunter, wie sie waren.
 *
 * ⚠️ **nextime ist hier vollständig, nextasks nicht.** Die nextasks-Karte
 * zeigt den Stand und springt zum Abschnitt „Aufgaben" darunter, wo Verbinden
 * und Token erneuern schon wohnen; zwei Orte für dasselbe Formular liefen
 * auseinander.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Unlink } from 'lucide-react'
import { api, ApiFehler } from '../../api/client'
import {
  kalenderEntfernen,
  kalenderLaden,
  nextimeAuswahl,
  nextimeKalenderAlle,
  nextimeStandLaden,
  nextimeTrennen,
  nextimeVerbinden,
  type KalenderZeile,
  type NextimeStand,
} from '../../api/laden'
import { Button, Checkbox, Input } from '../../ds'
import { useNachfrage } from '../../components/Nachfrage'
import { kalenderPunkt } from '../../lib/farben'
import { servermeldung } from '../../lib/servermeldung'
import type { ZielStand } from '../../lib/aufgabenziele'
import { AUFGABENZIELE_GEAENDERT, TodoApps } from '../TodoApps'
import { Abschnitt, Knopfreihe, Lage } from './Verbindungsteile'
import nextimeLogo from '../../assets/nextime.svg'
import nextasksLogo from '../../assets/nextasks.svg'

/** Die Überschrift einer Gruppe, wie in nextimes Seitenleiste. */
function gruppenName(k: KalenderZeile, t: (s: string) => string): string {
  if (k.gruppe === 'own') return 'nextime'
  if (k.gruppe === 'shared') return t('kalender.gruppe_geteilt')
  if (k.gruppe === 'subscriptions') return t('kalender.gruppe_abos')
  return k.herkunft || 'nextime'
}

/** Woran „Kalender hinzufügen" sagt: zur nextime-Karte, aufgeklappt. */
export const ZU_NEXTIME = 'nexmail:zu-nextime'
const MARKE = 'nexmail.nextimeKarteAuf'

/** Die Marke aus „Kalender hinzufügen" setzen; ⚠️ im Browser-Speicher, weil die
 *  Karte dabei erst entsteht. Fehlt der Speicher, geht die Karte eben zu auf. */
export function nextimeMarkeSetzen(): void {
  try {
    sessionStorage.setItem(MARKE, '1')
  } catch {
    // ohne Speicher: dann eben zu
  }
}

function nextimeMarkeHolen(): boolean {
  try {
    const da = sessionStorage.getItem(MARKE) === '1'
    sessionStorage.removeItem(MARKE)
    return da
  } catch {
    return false
  }
}

function wirt(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function KarteKopf({
  logo,
  name,
  satz,
  lage,
  offen,
  aufKlick,
  steuert,
}: {
  logo: string
  name: string
  satz: string
  lage: React.ReactNode
  offen?: boolean
  aufKlick: () => void
  /** Die Kennung dessen, was der Knopf aufklappt; ohne: ein Sprung. */
  steuert?: string
}) {
  return (
    <button
      type="button"
      onClick={aufKlick}
      aria-expanded={steuert ? Boolean(offen) : undefined}
      aria-controls={steuert}
      className="flex w-full items-start gap-4 rounded-xl p-5 text-left transition-colors duration-[var(--dur-fast)] hover:bg-surface-2"
    >
      <img src={logo} alt="" aria-hidden className="size-10 shrink-0 rounded-[10px]" />
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-[16px] font-semibold text-fg-1">{name}</span>
        <span className="text-[13px] leading-relaxed text-fg-3">{satz}</span>
        {!offen && <span className="pt-1">{lage}</span>}
      </span>
      {offen ? (
        <ChevronDown aria-hidden className="mt-1 size-4 shrink-0 text-fg-4" />
      ) : (
        <ChevronRight aria-hidden className="mt-1 size-4 shrink-0 text-fg-4" />
      )}
    </button>
  )
}

export function NexApps() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [nextime, setNextime] = useState<NextimeStand | null>(null)
  const [nextasks, setNextasks] = useState<{ verbunden: boolean; fehler: string; adresse: string } | null>(
    null,
  )
  /* ⚠️ **Aufgeklappt, wenn man über „Kalender hinzufügen" kommt** (Befund 2
     vom 24.11.2026): Das Fenster legt dafür eine Marke ab. */
  const [offen, setOffen] = useState(() => nextimeMarkeHolen())
  const [nextasksOffen, setNextasksOffen] = useState(false)
  const [adresse, setAdresse] = useState('')
  const [schluessel, setSchluessel] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [hinweis, setHinweis] = useState('')
  /** „Schlüssel ändern" geöffnet: dann steht das Formular statt der Übersicht. */
  const [aendern, setAendern] = useState(false)
  /** AC-15: Was nexmail selbst schon verbindet und doppelt erscheinen kann. */
  const [doppelte, setDoppelte] = useState<KalenderZeile[]>([])
  /** Alle nextime-Kalender mit ihrer Auswahl (Entscheidung 23.11.2026). */
  const [auswahl, setAuswahl] = useState<KalenderZeile[] | null>(null)

  const laden = useCallback(async () => {
    try {
      const stand = await nextimeStandLaden()
      setNextime(stand)
      if (stand.verbunden) {
        const alle = await kalenderLaden().catch(() => [] as KalenderZeile[])
        setDoppelte(alle.filter((k) => k.art === 'caldav' || k.art === 'ics'))
        setAuswahl(await nextimeKalenderAlle().catch(() => null))
      } else {
        setDoppelte([])
        setAuswahl(null)
      }
    } catch (f) {
      setFehler(servermeldung(f))
    }
    try {
      const ziele = await api.holen<ZielStand>('/api/aufgabenziele')
      const v = ziele.verbindungen.find((x) => x.art === 'nextasks')
      let wo = ''
      if (v) {
        wo = await api
          .holen<{ url: string }>(`/api/aufgabenziele/${v.id}/nextasks`)
          .then((x) => x.url)
          .catch(() => '')
      }
      setNextasks({ verbunden: Boolean(v), fehler: v?.fehler ?? '', adresse: wo })
    } catch {
      setNextasks({ verbunden: false, fehler: '', adresse: '' })
    }
  }, [])

  useEffect(() => {
    void laden()
    const neu = () => void laden()
    window.addEventListener(AUFGABENZIELE_GEAENDERT, neu)
    return () => window.removeEventListener(AUFGABENZIELE_GEAENDERT, neu)
  }, [laden])

  // Schon offen und dann über „Kalender hinzufügen" gekommen: auch aufklappen.
  useEffect(() => {
    const auf = () => {
      nextimeMarkeHolen()
      setOffen(true)
    }
    window.addEventListener(ZU_NEXTIME, auf)
    return () => window.removeEventListener(ZU_NEXTIME, auf)
  }, [])

  async function verbinden() {
    setLaeuft(true)
    setFehler('')
    setHinweis('')
    try {
      const neu = await nextimeVerbinden(adresse, schluessel)
      setSchluessel('')
      setAendern(false)
      setHinweis(t('nextime.verbunden_mit', { count: neu.kalender }))
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function trennen() {
    const ja = await fragen({
      titel: t('nextime.trennen_frage'),
      text: t('nextime.trennen_text'),
      knopf: t('nextime.trennen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    try {
      await nextimeTrennen()
      setHinweis('')
      await laden()
    } catch (f) {
      setFehler(servermeldung(f))
    }
  }

  /** Einen Kalender nehmen oder weglassen. Sofort umschalten, bei Absage zurück. */
  async function waehlen(k: KalenderZeile, an: boolean) {
    setAuswahl((alt) => (alt ?? []).map((x) => (x.id === k.id ? { ...x, gewaehlt: an } : x)))
    try {
      await nextimeAuswahl(k.id, an)
    } catch (f) {
      setFehler(servermeldung(f))
      setAuswahl(await nextimeKalenderAlle().catch(() => null))
    }
  }

  async function kalenderTrennen(k: KalenderZeile) {
    const ja = await fragen({
      titel: t('kalender.entfernen_frage', { name: k.name }),
      text: t('kalender.entfernen_gegenstelle', { wo: k.herkunft }),
      knopf: t('kalender.trennen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    try {
      await kalenderEntfernen(k.id)
      await laden()
    } catch (f) {
      setFehler(servermeldung(f))
    }
  }

  const verbunden = Boolean(nextime?.verbunden)
  const formular = (erneuern: boolean) => (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        void verbinden()
      }}
    >
      {!erneuern && <p className="mb-0 text-[13px] text-fg-3">{t('nextime.hinweis')}</p>}
      <Input
        label={t('nextime.adresse')}
        value={adresse}
        placeholder="https://kalender.example.com"
        onChange={(e) => setAdresse(e.target.value)}
        hint={t('nextime.adresse_hinweis')}
      />
      <Input
        label={t('nextime.schluessel')}
        type="password"
        autoComplete="off"
        value={schluessel}
        placeholder="nt_api_…"
        onChange={(e) => setSchluessel(e.target.value)}
      />
      <Knopfreihe rechts>
        {erneuern && (
          <Button type="button" variant="secondary" onClick={() => setAendern(false)}>
            {t('aktion.abbrechen')}
          </Button>
        )}
        <Button
          type="submit"
          variant="primary"
          loading={laeuft}
          disabled={laeuft || !adresse.trim() || !schluessel.trim()}
        >
          {t('nextime.verbinden')}
        </Button>
      </Knopfreihe>
    </form>
  )

  /* Jede Gruppe nur einmal: nextime liefert die Kalender in seiner Reihenfolge,
     eine Gruppe kann darin zweimal vorkommen (etwa versteckte am Ende). Die
     Gruppen bleiben in der Reihenfolge ihres ersten Auftritts. */
  const geordnet = (() => {
    if (!auswahl) return null
    const rang = new Map<string, number>()
    auswahl.forEach((k) => {
      const g = gruppenName(k, t)
      if (!rang.has(g)) rang.set(g, rang.size)
    })
    return [...auswahl].sort((a, b) => rang.get(gruppenName(a, t))! - rang.get(gruppenName(b, t))!)
  })()

  /* Erfolg und Fehler stehen unter der Statuszeile, nicht unter den Knöpfen. */
  const meldungen = (
    <>
      {hinweis && <p className="mb-0 text-[13px] text-success">{hinweis}</p>}
      {fehler && <p role="alert" className="mb-0 text-[13px] text-danger">{fehler}</p>}
    </>
  )

  return (
    <>
      <div className="flex flex-col gap-4">
        {/* --- nextime ---------------------------------------------------- */}
        <div className="rounded-xl border border-line bg-surface-1" role="region" aria-label="nextime">
          <KarteKopf
            logo={nextimeLogo}
            name="nextime"
            satz={t('nextime.satz')}
            offen={offen}
            steuert="nextime-verbindung"
            aufKlick={() => {
              setOffen((o) => !o)
              if (nextime?.adresse) setAdresse(nextime.adresse)
            }}
            lage={
              nextime === null ? null : verbunden ? (
                nextime.letzterFehler ? (
                  <Lage art="warn" text={t('nextime.gestoert')} adresse={wirt(nextime.adresse)} />
                ) : (
                  <Lage art="ok" text={t('nextime.verbunden')} adresse={wirt(nextime.adresse)} />
                )
              ) : (
                <Lage art="aus" text={t('nextime.nicht_verbunden')} />
              )
            }
          />
          {offen && (
            <div id="nextime-verbindung" className="flex flex-col gap-4 border-t border-line-subtle p-5">
              {verbunden && nextime && !aendern ? (
                <>
                  <Lage
                    art={nextime.letzterFehler ? 'warn' : 'ok'}
                    text={nextime.letzterFehler ? t('nextime.gestoert') : t('nextime.verbunden')}
                    adresse={wirt(nextime.adresse)}
                    zusatz={t('nextime.zeigt')}
                  />
                  {meldungen}
                  {nextime.letzterFehler && (
                    <p role="alert" className="mb-0 text-[13px] text-warning">
                      {servermeldung(new ApiFehler(409, nextime.letzterFehler), t('nextime.gestoert'))}
                    </p>
                  )}
                  {/* Welche Kalender nexmail nimmt. ⚠️ **Nicht gewählte erscheinen
                      nirgends** in nexmail; die Haken in der Kalender-Seitenleiste
                      bleiben fürs schnelle Ein- und Ausblenden. */}
                  {geordnet && geordnet.length > 0 && (
                    <Abschnitt titel={t('nextime.auswahl_titel')} hinweis={t('nextime.auswahl_hinweis')}>
                      {geordnet.map((k, i) => {
                        const kopf = gruppenName(k, t)
                        const neu = i === 0 || gruppenName(geordnet[i - 1], t) !== kopf
                        return (
                          <div key={k.id} className="flex flex-col">
                            {neu && (
                              <span className={`text-[13px] font-medium text-fg-1 ${i ? 'pt-2' : ''}`}>{kopf}</span>
                            )}
                            <span className="flex items-center gap-2 py-0.5 pl-6 text-[13px]">
                              <span aria-hidden className={`size-2.5 shrink-0 rounded-sm ${kalenderPunkt(k)}`} />
                              <Checkbox
                                label={k.name}
                                checked={k.gewaehlt !== false}
                                onCheckedChange={(an) => void waehlen(k, an)}
                              />
                            </span>
                          </div>
                        )
                      })}
                    </Abschnitt>
                  )}
                  {doppelte.length > 0 && (
                    <Abschnitt titel={t('nextime.doppelt_titel')} hinweis={t('nextime.doppelt_hinweis')}>
                      <ul className="m-0 flex list-none flex-col gap-1 p-0">
                        {doppelte.map((k) => (
                          <li key={k.id} className="flex items-center gap-2 text-[13px]">
                            <span className="min-w-0 flex-1 truncate text-fg-1">
                              {k.name}
                              {k.herkunft && <span className="text-fg-4"> · {k.herkunft}</span>}
                            </span>
                            <Button
                              size="sm"
                              variant="ghost"
                              iconLeft={<Unlink className="size-3.5" />}
                              onClick={() => void kalenderTrennen(k)}
                            >
                              {t('kalender.trennen')}
                            </Button>
                          </li>
                        ))}
                      </ul>
                    </Abschnitt>
                  )}
                  <Knopfreihe>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setAdresse(nextime.adresse)
                        setSchluessel('')
                        setHinweis('')
                        setAendern(true)
                      }}
                    >
                      {t('nextime.schluessel_aendern')}
                    </Button>
                    <Button variant="secondary" onClick={() => void trennen()}>
                      {t('nextime.trennen')}
                    </Button>
                  </Knopfreihe>
                </>
              ) : (
                <>
                  {meldungen}
                  {formular(verbunden)}
                </>
              )}
            </div>
          )}
        </div>

        {/* --- nextasks --------------------------------------------------- */}
        <div className="rounded-xl border border-line bg-surface-1" role="region" aria-label="nextasks">
          <KarteKopf
            logo={nextasksLogo}
            name="nextasks"
            satz={t('nextime.nextasks_satz')}
            offen={nextasksOffen}
            steuert="nextasks-verbindung"
            aufKlick={() => setNextasksOffen((o) => !o)}
            lage={
              nextasks === null ? null : nextasks.verbunden ? (
                nextasks.fehler ? (
                  <Lage art="warn" text={t('nextime.gestoert')} adresse={wirt(nextasks.adresse)} />
                ) : (
                  <Lage art="ok" text={t('nextime.verbunden')} adresse={wirt(nextasks.adresse)} />
                )
              ) : (
                <Lage art="aus" text={t('nextime.nicht_verbunden')} />
              )
            }
          />
          {nextasksOffen && (
            <div id="nextasks-verbindung" className="border-t border-line-subtle p-5">
              <TodoApps teil="nextasks" />
            </div>
          )}
        </div>
      </div>
      {nachfrage}
    </>
  )
}
