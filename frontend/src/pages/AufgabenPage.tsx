/* Aufgaben — Mails, die noch etwas von einem wollen.
 *
 * ⚠️ **Eine Aufgabe zeigt auf ihre Mail, sie kopiert sie nicht.** Ein Klick
 * öffnet die Mail; das Abhaken lässt sie, wo sie ist. nexmail wird kein
 * Aufgabenverwalter — es merkt sich nur, was noch offen ist.
 *
 * ⚠️ **Und sie überlebt ihre Mail.** Wer im Papierkorb aufräumt, soll nicht
 * lautlos seine Liste mitlöschen. Eine verwaiste Aufgabe steht weiter da, sagt
 * es und trägt trotzdem noch Betreff und Absender — sonst weiß niemand mehr,
 * worum es ging.
 *
 * ⚠️ **Eine Aufgabe in einer Todo-App gehört dieser App.** Sie steht hier
 * trotzdem, mit ihrer Liste und einem Link dorthin; Haken und Datum sind der
 * letzte Stand, den der Abgleich geholt hat. Abhaken geht über die App, das
 * Datum ändert man nur dort.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CalendarClock,
  CalendarDays,
  Check,
  CircleCheck,
  ExternalLink,
  GripVertical,
  Inbox,
  Layers,
  ListChecks,
  ListTodo,
  MailWarning,
  Trash2,
} from 'lucide-react'
import type { Ansichtsrahmen } from '../components/Ansichtsleiste'
import { api } from '../api/client'
import type { Konto } from '../daten/typen'
import { PUNKT_KLASSE } from '../lib/farben'
import { EmptyState, IconButton } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import { ARTNAME } from '../lib/aufgabenziele'

export interface AufgabenZeile {
  id: number
  nachricht_id: number | null
  konto_id: string
  betreff: string
  von_name: string
  von_adresse: string
  mail_datum: string | null
  erledigt: string | null
  faellig: string | null
  verwaist: boolean
  /** Leer heißt: nexmails eigene Aufgabe. Sonst die Todo-App, `todoist`. */
  fern_art: string
  fern_url: string
  fern_liste: string
  /** In der App gelöscht — die Zeile sagt es, statt zu verschwinden. */
  fern_geloescht: boolean
  /** Nach dem Trennen der Verbindung: nicht mehr abgeglichen. */
  fern_verbunden: boolean
}

/** Was die Liste zeigt (Seitenleiste, oben). */
type Filter = 'offen' | 'heute' | 'datum' | 'erledigt'

/** Wo eine Aufgabe liegt: leer heißt nexmails eigene Liste, sonst der Name
 *  der App samt Liste, wie ihn der Server schickt („Todoist › Arbeit“). */
export function ortVon(z: AufgabenZeile): string {
  if (!z.fern_art) return ''
  return z.fern_liste || ARTNAME[z.fern_art] || z.fern_art
}

/** Der heutige Tag als `JJJJ-MM-TT` in der Zeit des Browsers. Fristen tragen
 *  Mitternacht UTC, also zählt nur ihr Datumsteil. */
function heuteText(jetzt = new Date()): string {
  const m = String(jetzt.getMonth() + 1).padStart(2, '0')
  const d = String(jetzt.getDate()).padStart(2, '0')
  return `${jetzt.getFullYear()}-${m}-${d}`
}

export function passt(z: AufgabenZeile, filter: Filter, heute = heuteText()): boolean {
  if (filter === 'erledigt') return Boolean(z.erledigt)
  if (z.erledigt) return false
  if (filter === 'heute') return Boolean(z.faellig && z.faellig.slice(0, 10) <= heute)
  if (filter === 'datum') return Boolean(z.faellig)
  return true
}

interface Props {
  /** Werkzeugleiste und Seitenspalte, von `App` gebaut wie in der Mail. */
  rahmen: Ansichtsrahmen
  konten: Konto[]
  /** Die Mail zu einer Aufgabe öffnen. */
  aufMail: (nachrichtId: number) => void
  /** Nach jeder Änderung, damit die Zahl an der Leiste stimmt. */
  aufAenderung?: () => void
}

export function AufgabenPage({ rahmen, konten, aufMail, aufAenderung }: Props) {
  const { t } = useTranslation()
  const [zeilen, setZeilen] = useState<AufgabenZeile[] | null>(null)
  const [fehler, setFehler] = useState('')
  const [gezogen, setGezogen] = useState<number | null>(null)
  const [ueber, setUeber] = useState<number | null>(null)
  const [filter, setFilter] = useState<Filter>('offen')
  /** `null` heißt: überall; leer heißt: nexmails eigene Liste. */
  const [ort, setOrt] = useState<string | null>(null)

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<AufgabenZeile[]>('/api/aufgaben'))
      setFehler('')
    } catch (f) {
      // ⚠️ Ein Fehler darf nicht wie eine leere Liste aussehen — dieselbe
      // Regel wie bei den Postfächern.
      setFehler(servermeldung(f, t('aufgaben.laden_ging_nicht')))
    }
  }, [t])

  useEffect(() => {
    void (async () => {
      await laden()
      /* ⚠️ **Erst zeigen, dann nachsehen.** Die Liste steht sofort mit dem
         letzten Stand da; was die Todo-Apps inzwischen sagen, kommt einen
         Augenblick später. Scheitert das, bleibt der letzte Stand stehen —
         der Grund steht an der Verbindung in den Einstellungen. */
      try {
        await api.senden('/api/aufgaben/abgleichen', {})
        await laden()
        aufAenderung?.()
      } catch {
        /* Der letzte Stand bleibt; siehe oben. */
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laden])

  async function mit(tun: () => Promise<unknown>) {
    try {
      await tun()
      await laden()
      aufAenderung?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function ablegen(zielId: number) {
    if (zeilen === null || gezogen === null || gezogen === zielId) return
    const ohne = zeilen.filter((z) => z.id !== gezogen)
    const platz = ohne.findIndex((z) => z.id === zielId)
    const neu = [...ohne.slice(0, platz), zeilen.find((z) => z.id === gezogen)!, ...ohne.slice(platz)]
    // ⚠️ Erst hier zeichnen, dann schicken: Eine Reihenfolge, die nach dem
    // Loslassen erst zurückspringt und dann sitzt, fühlt sich kaputt an.
    setZeilen(neu)
    setGezogen(null)
    setUeber(null)
    await mit(() => api.aendern('/api/aufgaben/reihenfolge', { ids: neu.map((z) => z.id) }))
  }

  const alle = zeilen ?? []
  const heute = heuteText()
  const amOrt = (z: AufgabenZeile, o: string | null) => o === null || ortVon(z) === o
  const sichtbar = alle.filter((z) => passt(z, filter, heute) && amOrt(z, ort))
  /* Die Orte in der Reihenfolge, in der sie zuerst vorkommen; nexmails eigene
     Liste immer vorn. Ohne verbundene App bleibt der Block weg. */
  const orte = [...new Set(alle.map(ortVon))].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : 0))
  const zahlAm = (o: string | null) => alle.filter((z) => passt(z, filter, heute) && amOrt(z, o)).length

  const FILTER: ReadonlyArray<{ id: Filter; symbol: React.ReactNode; text: string }> = [
    { id: 'offen', symbol: <ListTodo />, text: t('aufgaben.filter_offen') },
    { id: 'heute', symbol: <CalendarClock />, text: t('aufgaben.filter_heute') },
    { id: 'datum', symbol: <CalendarDays />, text: t('aufgaben.filter_datum') },
    { id: 'erledigt', symbol: <CircleCheck />, text: t('aufgaben.filter_erledigt') },
  ]

  const zeilenKlasse = (an: boolean) =>
    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] ' +
    'transition-colors duration-[var(--dur-fast)] [&_svg]:size-4 [&_svg]:shrink-0 ' +
    (an ? 'bg-accent-soft text-accent-text' : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')

  /* ⚠️ **Die Seitenleiste der Aufgaben** (gemeldet am 23.11.2026, wie die
     Seitenleiste von nextasks): oben, was gezeigt wird (je mit Zahl), darunter,
     wo die Aufgaben liegen. Ohne verbundene Todo-App gibt es nur einen Ort,
     dann fällt der zweite Block weg. Die Zahl am Ort folgt dem Filter. */
  const seitenleiste = (
    <nav aria-label={t('aufgaben.filter_titel')} className="flex flex-col gap-0.5 p-2">
      {FILTER.map((f) => {
        const zahl = alle.filter((z) => passt(z, f.id, heute) && amOrt(z, ort)).length
        return (
          <button
            key={f.id}
            type="button"
            aria-current={filter === f.id ? 'page' : undefined}
            onClick={() => {
              setFilter(f.id)
              rahmen.zeigen()
            }}
            className={zeilenKlasse(filter === f.id)}
          >
            {f.symbol}
            <span className="min-w-0 flex-1 truncate">{f.text}</span>
            {zahl > 0 && <span className="text-[11px] tabular-nums text-fg-4">{zahl}</span>}
          </button>
        )
      })}

      {orte.length > 1 && (
        <>
          <h2 className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wide text-fg-4 uppercase">
            {t('aufgaben.orte')}
          </h2>
          <button
            type="button"
            aria-current={ort === null ? 'page' : undefined}
            onClick={() => {
              setOrt(null)
              rahmen.zeigen()
            }}
            className={zeilenKlasse(ort === null)}
          >
            <Layers />
            <span className="min-w-0 flex-1 truncate">{t('aufgaben.ort_alle')}</span>
            <span className="text-[11px] tabular-nums text-fg-4">{zahlAm(null)}</span>
          </button>
          {orte.map((o) => (
            <button
              key={o || '__nexmail__'}
              type="button"
              aria-current={ort === o ? 'page' : undefined}
              onClick={() => {
                setOrt(o)
                rahmen.zeigen()
              }}
              className={zeilenKlasse(ort === o)}
            >
              {o ? <ExternalLink /> : <Inbox />}
              <span className="min-w-0 flex-1 truncate">{o || t('aufgaben.ort_nexmail')}</span>
              <span className="text-[11px] tabular-nums text-fg-4">{zahlAm(o)}</span>
            </button>
          ))}
        </>
      )}
    </nav>
  )

  const titel = FILTER.find((f) => f.id === filter)?.text ?? t('nav.aufgaben')

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-canvas">
      {rahmen.kopf({})}
    <div className="flex min-h-0 flex-1">
      {rahmen.spalte(seitenleiste)}
    {rahmen.ersatz ? (
      <div className="flex min-w-0 flex-1 flex-col">{rahmen.ersatz}</div>
    ) : (
    <div className="min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-[720px] flex-col gap-4 px-6 py-6">
        {/* Schmal gibt es keine Seitenspalte; die Filter stehen dann hier. */}
        {rahmen.schmal && (
          <div className="flex flex-wrap gap-1.5">
            {FILTER.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={
                  'rounded-pill border px-3 py-1 text-[12px] ' +
                  (filter === f.id ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-fg-3')
                }
              >
                {f.text}
              </button>
            ))}
          </div>
        )}
        <div className="flex items-baseline gap-3">
          <h1 className="mb-0 font-display text-[20px] font-medium text-fg-1">
            {titel}
          </h1>
          <span className="text-[12px] text-fg-4">
            {filter === 'erledigt'
              ? t('aufgaben.erledigt_zahl', { count: sichtbar.length })
              : t('aufgaben.offen', { count: sichtbar.length })}
          </span>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 rounded-md border border-danger bg-danger-soft px-3 py-2 text-[13px] text-fg-1">
            {fehler}
          </p>
        )}

        {zeilen !== null && sichtbar.length === 0 && !fehler && (
          <EmptyState
            icon={<ListChecks />}
            title={alle.length === 0 ? t('aufgaben.leer_titel') : t('aufgaben.filter_leer')}
            description={alle.length === 0 ? t('aufgaben.leer_text') : undefined}
          />
        )}

        <ul className="flex list-none flex-col gap-1.5 p-0">
          {sichtbar.map((z) => {
            const farbe = konten.find((k) => k.id === z.konto_id)?.farbe
            const faellig = z.faellig ? new Date(z.faellig) : null
            const ueberfaellig = Boolean(faellig && !z.erledigt && faellig < new Date())
            const inApp = Boolean(z.fern_art && z.fern_verbunden && !z.fern_geloescht)

            return (
              <li
                key={z.id}
                draggable={!z.erledigt}
                onDragStart={() => setGezogen(z.id)}
                onDragEnd={() => {
                  setGezogen(null)
                  setUeber(null)
                }}
                onDragOver={(e) => {
                  e.preventDefault()
                  setUeber(z.id)
                }}
                onDrop={() => void ablegen(z.id)}
                className={
                  'flex items-start gap-3 rounded-lg border bg-surface-1 px-3 py-2.5 ' +
                  'transition-colors duration-[var(--dur-fast)] ' +
                  (ueber === z.id ? 'border-accent ' : 'border-line ') +
                  (z.erledigt ? 'opacity-60 ' : '')
                }
              >
                {/* ⚠️ Der Griff ist sichtbar, nicht geraten. Eine Zeile, die
                    sich ziehen lässt und das nicht zeigt, zieht niemand. */}
                <span
                  aria-hidden
                  className={
                    'mt-1 shrink-0 ' + (z.erledigt ? 'text-transparent' : 'cursor-grab text-fg-4')
                  }
                >
                  <GripVertical className="size-4" />
                </span>

                <button
                  type="button"
                  role="checkbox"
                  aria-checked={Boolean(z.erledigt)}
                  aria-label={
                    z.erledigt ? t('aufgaben.wieder_offen') : t('aufgaben.abhaken')
                  }
                  onClick={() =>
                    void mit(() =>
                      api.flicken(`/api/aufgaben/${z.id}`, { erledigt: !z.erledigt }),
                    )
                  }
                  className={
                    'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border ' +
                    'transition-colors duration-[var(--dur-fast)] ' +
                    (z.erledigt
                      ? 'border-accent bg-accent text-on-accent'
                      : 'border-line-strong hover:border-accent')
                  }
                >
                  {z.erledigt && <Check className="size-3.5" />}
                </button>

                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    {farbe && (
                      <span
                        aria-hidden
                        className={`size-2 shrink-0 rounded-full ${PUNKT_KLASSE[farbe]}`}
                      />
                    )}
                    <button
                      type="button"
                      disabled={z.nachricht_id === null}
                      onClick={() => z.nachricht_id !== null && aufMail(z.nachricht_id)}
                      className={
                        'min-w-0 flex-1 truncate text-left text-[13px] ' +
                        (z.erledigt ? 'text-fg-3 line-through ' : 'text-fg-1 ') +
                        (z.nachricht_id === null ? 'cursor-default' : 'hover:text-accent-text')
                      }
                    >
                      {z.betreff || t('liste.kein_betreff')}
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 pl-4 text-[11px] text-fg-4">
                    <span className="truncate">{z.von_name || z.von_adresse}</span>

                    {/* ⚠️ Die verwaiste Aufgabe sagt es. Sonst klickt man ins
                        Leere und hält nexmail für kaputt. */}
                    {z.verwaist && (
                      <span className="flex items-center gap-1 text-warning">
                        <MailWarning className="size-3" />
                        {t('aufgaben.mail_weg')}
                      </span>
                    )}

                    {z.fern_art && (
                      <span className="flex items-center gap-1">
                        {z.fern_liste || ARTNAME[z.fern_art] || z.fern_art}
                        {/* Eine in der App gelöschte Aufgabe hat dort keine
                            Seite mehr; der Link führte ins Leere. */}
                        {z.fern_url && !z.fern_geloescht && (
                          <a
                            href={z.fern_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            aria-label={t('aufgaben.in_app_oeffnen')}
                            title={t('aufgaben.in_app_oeffnen')}
                            className="text-fg-4 hover:text-accent-text"
                          >
                            <ExternalLink className="size-3" aria-hidden />
                          </a>
                        )}
                      </span>
                    )}

                    {z.fern_geloescht && (
                      <span className="flex items-center gap-1 text-warning">
                        <MailWarning className="size-3" />
                        {t('aufgaben.in_app_geloescht')}
                      </span>
                    )}

                    {/* ⚠️ **Das Datum einer App-Aufgabe nur lesen.** Geändert
                        wird es in der App; hier wäre es beim nächsten
                        Abgleich still wieder überschrieben. */}
                    {inApp ? (
                      faellig && (
                        <span className={ueberfaellig ? 'text-danger' : ''}>
                          {faellig.toLocaleDateString(undefined, { timeZone: 'UTC' })}
                        </span>
                      )
                    ) : (
                    <>
                    {/* ⚠️ **Ohne Datum bleibt hier nur das Kalendersymbol.**
                        Ein leeres `<input type="date">` malt „tt.mm.jjjj" hin,
                        und das stünde bei den meisten Aufgaben — die haben
                        keine Frist. Die schmale Breite schneidet den
                        Platzhalter weg; der eingebaute Kalenderknopf bleibt
                        anklickbar. Ein zweites Symbol daneben wäre eins zu
                        viel: Der Browser bringt seines mit. */}
                    <label
                      className="flex items-center"
                      title={t('aufgaben.faellig')}
                    >
                      <span className="sr-only">{t('aufgaben.faellig')}</span>
                      <input
                        type="date"
                        aria-label={t('aufgaben.faellig')}
                        value={faellig ? faellig.toISOString().slice(0, 10) : ''}
                        onChange={(e) =>
                          void mit(() =>
                            api.flicken(`/api/aufgaben/${z.id}`, {
                              faellig: e.target.value ? `${e.target.value}T00:00:00Z` : null,
                              faellig_setzen: true,
                            }),
                          )
                        }
                        className={
                          'rounded-sm border border-transparent bg-transparent py-0.5 ' +
                          'text-[11px] hover:border-line ' +
                          (faellig ? 'w-[6.5rem] px-1 ' : 'w-[1.4rem] px-0 ') +
                          (ueberfaellig ? 'text-danger' : 'text-fg-4')
                        }
                      />
                    </label>
                    </>
                    )}

                    {/* ⚠️ **Das Eingangsdatum der Mail steht hier nicht.**
                        Zwei unbeschriftete Daten nebeneinander liest niemand
                        richtig — man hält das eine für das andere. Hier zählt
                        die Frist; wann die Mail kam, steht in der Mail, und
                        die ist einen Klick entfernt. */}
                  </div>
                </div>

                <IconButton
                  icon={<Trash2 />}
                  label={z.fern_art ? t('aufgaben.entfernen_nur_hier') : t('aufgaben.entfernen')}
                  onClick={() => void mit(() => api.loeschen(`/api/aufgaben/${z.id}`))}
                />
              </li>
            )
          })}
        </ul>
      </div>
    </div>
    )}
    </div>
    </div>
  )
}
