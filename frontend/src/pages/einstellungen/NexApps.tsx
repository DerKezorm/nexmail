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
import { Unlink } from 'lucide-react'
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
import { Badge, Box, Button, Buttons, Checkbox, Collapsible, Field, Notice, Row, Rows } from '../../vendor/nexui'
import { useNachfrage } from '../../components/Nachfrage'
import { kalenderPunkt } from '../../lib/farben'
import { servermeldung } from '../../lib/servermeldung'
import type { ZielStand } from '../../lib/aufgabenziele'
import { AUFGABENZIELE_GEAENDERT, TodoApps } from '../TodoApps'
import nextimeLogo from '../../assets/nextime.svg'
import nextasksLogo from '../../assets/nextasks.svg'

/** Die Überschrift einer Gruppe, wie in nextimes Seitenleiste. */
function gruppenName(k: KalenderZeile, t: (s: string) => string): string {
  if (k.gruppe === 'own') return 'nextime'
  if (k.gruppe === 'shared') return t('kalender.gruppe_geteilt')
  if (k.gruppe === 'subscriptions') return t('kalender.gruppe_abos')
  return k.herkunft || 'nextime'
}


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

/** Woran „Kalender hinzufügen" sagt: zur nextime-Karte, aufgeklappt. */
export const ZU_NEXTIME = 'nexmail:zu-nextime'
const MARKE = 'nexmail.nextimeKarteAuf'


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
      {!erneuern && <p className="m-0 text-sm">{t('nextime.hinweis')}</p>}
      <Field
        label={t('nextime.adresse')}
        value={adresse}
        placeholder="https://kalender.example.com"
        onChange={(e) => setAdresse(e.target.value)}
        hints={[t('nextime.adresse_hinweis')]}
      />
      <Field
        label={t('nextime.schluessel')}
        type="password"
        autoComplete="off"
        value={schluessel}
        placeholder="nt_api_…"
        onChange={(e) => setSchluessel(e.target.value)}
      />
      <Buttons end>
        {erneuern && (
          <Button kind="secondary" icon="X" onClick={() => setAendern(false)}>
            {t('aktion.abbrechen')}
          </Button>
        )}
        <Button
          type="submit"
          kind="primary"
          icon="Plug"
          busy={laeuft}
          disabled={laeuft || !adresse.trim() || !schluessel.trim()}
        >
          {t('nextime.verbinden')}
        </Button>
      </Buttons>
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
      {hinweis && <Notice tone="ok">{hinweis}</Notice>}
      {fehler && <Notice tone="danger">{fehler}</Notice>}
    </>
  )

  /** Zugeklappt: „verbunden · host“ (Bauplan, Verbindungen 3). */
  const status = (an: boolean | null, gestoert: boolean, wo: string) =>
    an === null ? null : an ? (
      <Badge tone={gestoert ? 'warn' : 'on'}>
        {gestoert ? t('nextime.gestoert') : t('nextime.verbunden')}
        {wo ? ` · ${wo}` : ''}
      </Badge>
    ) : (
      <Badge tone="off">{t('nextime.nicht_verbunden')}</Badge>
    )

  return (
    <>
      {/* --- nextime ---------------------------------------------------- */}
      <Collapsible
        variant="card"
        id="nextime"
        logo={nextimeLogo}
        title="nextime"
        subtitle={t('nextime.satz')}
        open={offen}
        onOpenChange={(auf) => {
          setOffen(auf)
          if (auf && nextime?.adresse) setAdresse(nextime.adresse)
        }}
        status={status(nextime === null ? null : verbunden, Boolean(nextime?.letzterFehler), wirt(nextime?.adresse ?? ''))}
      >
        {verbunden && nextime && !aendern ? (
          <>
            <p className="m-0 text-sm">{t('nextime.zeigt')}</p>
            {meldungen}
            {nextime.letzterFehler && (
              <Notice tone="warn">{servermeldung(new ApiFehler(409, nextime.letzterFehler), t('nextime.gestoert'))}</Notice>
            )}
            {/* Welche Kalender nexmail nimmt. ⚠️ **Nicht gewählte erscheinen nirgends** in nexmail; die Haken in der
                Kalender-Seitenleiste bleiben fürs schnelle Ein- und Ausblenden. */}
            {geordnet && geordnet.length > 0 && (
              <Box title={t('nextime.auswahl_titel')} hint={t('nextime.auswahl_hinweis')}>
                {geordnet.map((k, i) => {
                  const kopf = gruppenName(k, t)
                  const neu = i === 0 || gruppenName(geordnet[i - 1], t) !== kopf
                  return (
                    <div key={k.id} className="flex flex-col">
                      {neu && <span className={`text-sm font-medium ${i ? 'pt-2' : ''}`}>{kopf}</span>}
                      <span className="flex items-center gap-2 py-0.5 pl-6 text-sm">
                        <span aria-hidden className={`size-2.5 shrink-0 rounded-sm ${kalenderPunkt(k)}`} />
                        <Checkbox label={k.name} checked={k.gewaehlt !== false} onChange={(an) => void waehlen(k, an)} />
                      </span>
                    </div>
                  )
                })}
              </Box>
            )}
            {doppelte.length > 0 && (
              <Box title={t('nextime.doppelt_titel')} hint={t('nextime.doppelt_hinweis')}>
                <Rows label={t('nextime.doppelt_titel')}>
                  {doppelte.map((k) => (
                    <Row
                      key={k.id}
                      name={k.name}
                      detail={k.herkunft || undefined}
                      action={
                        <Button size="sm" kind="danger" icon={Unlink} onClick={() => void kalenderTrennen(k)}>
                          {t('kalender.trennen')}
                        </Button>
                      }
                    />
                  ))}
                </Rows>
              </Box>
            )}
            <Buttons>
              <Button
                kind="secondary"
                icon="KeyRound"
                onClick={() => {
                  setAdresse(nextime.adresse)
                  setSchluessel('')
                  setHinweis('')
                  setAendern(true)
                }}
              >
                {t('nextime.schluessel_aendern')}
              </Button>
              <Button kind="danger" icon={Unlink} onClick={() => void trennen()}>
                {t('nextime.trennen')}
              </Button>
            </Buttons>
          </>
        ) : (
          <>
            {meldungen}
            {formular(verbunden)}
          </>
        )}
      </Collapsible>

      {/* --- nextasks --------------------------------------------------- */}
      <Collapsible
        variant="card"
        id="nextasks"
        logo={nextasksLogo}
        title="nextasks"
        subtitle={t('nextime.nextasks_satz')}
        open={nextasksOffen}
        onOpenChange={setNextasksOffen}
        status={status(nextasks === null ? null : nextasks.verbunden, Boolean(nextasks?.fehler), wirt(nextasks?.adresse ?? ''))}
      >
        <TodoApps teil="nextasks" />
      </Collapsible>
      {nachfrage}
    </>
  )
}
