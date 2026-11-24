/* Die Termin-Einladung im Lesebereich.
 *
 * ⚠️ **Zusagen und Übernehmen sind zwei Dinge.** Eine Zusage benachrichtigt
 * den Einladenden; in den Kalender kommt der Termin erst auf Klick. Wer zusagt, ohne den Termin wirklich zu wollen,
 * soll ihn nicht im Kalender wiederfinden. Die Karte sagt beides.
 *
 * ⚠️ **Was nicht sicher ist, wird benannt statt geraten.** Eine Wiederholung
 * steht als Hinweis da, nicht als ausgerechnete Reihe; eine unbekannte
 * Zeitzone steht mit ihrem Namen daneben, statt die Zeit stillschweigend als
 * Ortszeit auszugeben. Beides wäre sonst um Stunden falsch, ohne dass man es
 * der Anzeige ansieht.
 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  CalendarDays,
  CalendarPlus,
  Check,
  Clock,
  ExternalLink,
  MapPin,
  RefreshCw,
  Repeat,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { ApiFehler } from '../api/client'
import type { Einladung, KalenderZeile } from '../api/laden'
import {
  kalenderLaden,
  nextimeAktualisieren,
  nextimeEntfernen,
  terminAntworten,
  terminUebernehmen,
} from '../api/laden'
import { servermeldung } from '../lib/servermeldung'
import { Button } from '../ds'
import { useNachfrage } from './Nachfrage'
import { anzeigename } from '../lib/format'

interface Props {
  nachrichtId: string
  einladung: Einladung
  /** Nach einer Antwort — damit der Lesebereich den neuen Stand hält. */
  aufAntwort: (neu: Einladung) => void
}

/** Beginn und Ende als ein Satz. Bei einem ganzen Tag ohne Uhrzeit. */
function zeitraum(e: Einladung, sprache: string): string {
  if (!e.beginn) return ''
  if (e.ganztaegig) {
    const tag = new Date(`${e.beginn}T00:00:00`)
    return tag.toLocaleDateString(sprache, { dateStyle: 'full' })
  }
  const von = new Date(e.beginn)
  const lang = von.toLocaleString(sprache, { dateStyle: 'full', timeStyle: 'short' })
  if (!e.ende) return lang
  const bis = new Date(e.ende)
  // Am selben Tag reicht die Uhrzeit für das Ende.
  const gleicherTag = von.toDateString() === bis.toDateString()
  const ende = gleicherTag
    ? bis.toLocaleTimeString(sprache, { timeStyle: 'short' })
    : bis.toLocaleString(sprache, { dateStyle: 'full', timeStyle: 'short' })
  return `${lang} – ${ende}`
}

export function Einladungskarte({ nachrichtId, einladung, aufAntwort }: Props) {
  const { t, i18n } = useTranslation()
  const [laeuft, setLaeuft] = useState('')
  const [fehler, setFehler] = useState('')

  /* ⚠️ **In WELCHEN Kalender, entscheidet der Mensch.** Der Server nahm sonst
     den ersten beschreibbaren — bei vier Kalendern ist das geraten, und man
     sucht den Termin danach in einem, in dem er nicht steht. Am 03.09.2026
     gemeldet: „ist im Kalender gelandet, aber hat mich nicht gefragt, in
     welchen".

     ⚠️ **Gefragt wird im Fenster, nicht auf der Karte.** Eine Auswahlliste
     neben dem Knopf steht auch dann da, wenn niemand sie braucht — die Karte
     sitzt in jeder Einladung mitten im Lesebereich. Und gefragt wird nur, wenn
     es etwas zu wählen gibt: Bei einem Kalender ist eine Liste mit einem
     Eintrag Zierde. */
  const { fragen, fenster: nachfrage } = useNachfrage()

  const uebernehmen = async () => {
    setFehler('')
    let ziel = ''
    const offene = (await kalenderLaden().catch(() => [] as KalenderZeile[])).filter(
      (k) => !k.nurLesen,
    )
    if (offene.length > 1) {
      const antwort = await fragen({
        titel: t('termin.in_kalender'),
        auswahl: {
          beschriftung: t('termin.welcher_kalender'),
          werte: offene.map((k) => ({ wert: k.id, text: k.name })),
        },
        knopf: t('termin.uebernehmen_knopf'),
      })
      if (typeof antwort !== 'object' || antwort === null || !('ja' in antwort)) return
      ziel = antwort.wert
    } else if (offene.length === 1) {
      ziel = offene[0].id
    }

    setLaeuft('uebernehmen')
    try {
      aufAntwort(await terminUebernehmen(nachrichtId, ziel))
    } catch (f) {
      // ⚠️ „Du hast noch keinen Kalender" ist etwas anderes als „ging nicht" —
      // und nur das Erste kann man beheben.
      const kennung = f instanceof ApiFehler ? f.detail : ''
      setFehler(
        kennung === 'kalender_fehlt' ? t('termin.kein_ziel') : t('termin.uebernehmen_fehler'),
      )
    } finally {
      setLaeuft('')
    }
  }

  /* Mit nextime (MAIL-1): der Stand dort. `null` ohne Verbindung — dann bleibt
     die Karte, wie sie war. */
  const lage = einladung.nextime
  const mitNextime = Boolean(lage && !lage.fehler)

  /** Wohin eine Zusage den Termin legt (MAIL-1 AC-5, AC-10).
   *
   * ⚠️ **Gefragt wird jedes Mal**, vorgewählt der Kalender, den man zuletzt
   * für dieses Postfach genommen hat: Geschäftliche und private Post gehören in
   * verschiedene Kalender. `null` heißt: abgebrochen. */
  const kalenderWaehlen = async (): Promise<string | null> => {
    const offene = (await kalenderLaden().catch(() => [] as KalenderZeile[])).filter(
      (k) => !k.nurLesen,
    )
    if (offene.length === 0) return ''
    const vorgabe =
      offene.find((k) => k.id === lage?.vorwahl)?.id ??
      offene.find((k) => k.standard)?.id ??
      offene[0].id
    if (offene.length === 1) return vorgabe
    const antwort = await fragen({
      titel: einladung.titel || t('termin.ohne_titel'),
      auswahl: {
        beschriftung: t('termin.welcher_kalender'),
        werte: offene.map((k) => ({
          wert: k.id,
          text: k.art === 'nextime' && k.herkunft ? `${k.name} · ${k.herkunft}` : k.name,
        })),
        vorgabe,
      },
      knopf: t('termin.zusagen_knopf'),
    })
    if (typeof antwort !== 'object' || antwort === null || !('ja' in antwort)) return null
    return antwort.wert
  }

  /* ⚠️ **Gesperrt, bevor gefragt wird** (Prüfbericht, Befund 4): Zwischen
     Klick und Antwort liegen das Laden der Kalender und die Frage; ein zweiter
     Klick in dieser Zeit schickte sonst eine zweite Zusage. Ein `ref`, weil der
     Zustand erst beim nächsten Zeichnen gilt. */
  const unterwegs = useRef(false)
  const antworten = async (antwort: 'zusage' | 'vorbehalt' | 'absage') => {
    if (unterwegs.current) return
    unterwegs.current = true
    setFehler('')
    setLaeuft(antwort)
    try {
      /* ⚠️ **Mit nextime ein Schritt** (AC-10): Zusagen fragt nach dem Kalender
         und trägt ein. Steht die Einladung schon in nextime, antwortet nextime
         (AC-9), und gefragt wird nichts. Absagen trägt nie etwas ein. */
      let ziel = ''
      if (mitNextime && lage && lage.terminId === null && antwort !== 'absage') {
        const gewaehlt = await kalenderWaehlen()
        if (gewaehlt === null) return
        ziel = gewaehlt
      }
      aufAntwort(await terminAntworten(nachrichtId, antwort, ziel))
    } catch (f) {
      setFehler(lage ? servermeldung(f, t('termin.fehler')) : t('termin.fehler'))
    } finally {
      unterwegs.current = false
      setLaeuft('')
    }
  }

  const mitNextimeTun = async (was: 'entfernen' | 'aktualisieren') => {
    setFehler('')
    setLaeuft(was)
    try {
      aufAntwort(
        await (was === 'entfernen' ? nextimeEntfernen(nachrichtId) : nextimeAktualisieren(nachrichtId)),
      )
    } catch (f) {
      setFehler(servermeldung(f, t('termin.fehler')))
    } finally {
      setLaeuft('')
    }
  }

  const zeitSatz = (u: { beginn: string; ende: string; ganztaegig: boolean }) => {
    if (u.ganztaegig) return t('termin.ganztags')
    const opt = { timeStyle: 'short' } as const
    return `${new Date(u.beginn).toLocaleTimeString(i18n.language, opt)}–${new Date(u.ende).toLocaleTimeString(i18n.language, opt)}`
  }

  const knoepfe: Array<{ id: 'zusage' | 'vorbehalt' | 'absage'; symbol: React.ReactNode }> = [
    { id: 'zusage', symbol: <Check className="size-4" /> },
    { id: 'vorbehalt', symbol: <Clock className="size-4" /> },
    { id: 'absage', symbol: <X className="size-4" /> },
  ]

  return (
    <section className="mx-6 mt-4 flex flex-col gap-3 rounded-lg border border-line bg-surface-2 px-4 py-3">
      <div className="flex items-start gap-3">
        <CalendarDays aria-hidden className="mt-0.5 size-4 shrink-0 text-accent-text" />
        <div className="min-w-0 flex-1">
          <p className="mb-0 text-[14px] font-medium text-fg-1">
            {einladung.titel || t('termin.ohne_titel')}
          </p>
          {einladung.beginn && (
            <p className="mb-0 text-[13px] text-fg-2">{zeitraum(einladung, i18n.language)}</p>
          )}
          {/* ⚠️ Die Zeit steht so da, wie sie kam — die Zone wird benannt. */}
          {einladung.fremdeZeitzone && (
            <p className="mb-0 text-[12px] text-warning-text">
              {t('termin.fremde_zeitzone', { zone: einladung.fremdeZeitzone })}
            </p>
          )}
        </div>
        {einladung.abgesagt && (
          <span className="shrink-0 rounded-pill bg-danger-soft px-2.5 py-0.5 text-[11px] font-medium text-danger">
            {t('termin.abgesagt')}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1 pl-7 text-[12px] text-fg-3">
        {einladung.ort && (
          <span className="flex items-center gap-1.5">
            <MapPin aria-hidden className="size-3.5 shrink-0" />
            {einladung.ort}
          </span>
        )}
        {einladung.wiederholtSich && (
          <span className="flex items-center gap-1.5">
            <Repeat aria-hidden className="size-3.5 shrink-0" />
            {t('termin.wiederholt_sich')}
          </span>
        )}
        {einladung.organisator.adresse && (
          <span className="flex items-center gap-1.5">
            <Users aria-hidden className="size-3.5 shrink-0" />
            {t('termin.von', {
              wer: anzeigename({
                name: einladung.organisator.name,
                adresse: einladung.organisator.adresse,
              }),
            })}
            {einladung.teilnehmer.length > 0 &&
              ` · ${t('termin.teilnehmer', { count: einladung.teilnehmer.length })}`}
          </span>
        )}
      </div>

      {/* ⚠️ **Der Satz, der die Erwartung geradezieht.** Ohne ihn hält man
          eine Zusage für einen Eintrag im Kalender. Mit nextime stimmt er
          nicht mehr: Dann steht da, wo der Termin liegt oder hinkommt. */}
      {!lage && <p className="mb-0 pl-7 text-[11px] text-fg-4">{t('termin.kein_kalender')}</p>}
      {lage?.fehler && (
        <p className="mb-0 flex items-start gap-1.5 pl-7 text-[12px] text-warning">
          <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {t('termin.nextime_fehlt', {
            grund: servermeldung(
              new ApiFehler(409, lage.fehler),
              t('kalender.nextime_nicht_erreichbar'),
            ),
          })}
        </p>
      )}
      {mitNextime && lage && (
        <div className="flex flex-col gap-1 pl-7 text-[12px] text-fg-3">
          {lage.terminId !== null ? (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>
                {t('termin.in_nextime', { kalender: lage.kalenderName || 'nextime' })}
              </span>
              {lage.link && (
                <a
                  href={lage.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-accent-text hover:underline"
                >
                  <ExternalLink aria-hidden className="size-3" />
                  {t('kalender.in_nextime_oeffnen')}
                </a>
              )}
            </span>
          ) : (
            !einladung.abgesagt && <span className="text-fg-4">{t('termin.zusagen_traegt_ein')}</span>
          )}
          {/* AC-12: Was zur selben Zeit schon im Kalender steht. */}
          {lage.ueberschneidungen.length > 0 && (
            <span className="text-warning">
              {t('termin.gleichzeitig', {
                was: lage.ueberschneidungen
                  .map(
                    (u) =>
                      `${u.titel || t('kalender.belegt')}${u.kalender ? ` (${u.kalender})` : ''} ${zeitSatz(u)}`,
                  )
                  .join(' · '),
              })}
            </span>
          )}
          {/* AC-11: Eine Aktualisierung zeigt, was anders ist, und wird erst auf
              Klick übernommen. */}
          {lage.ausMail && lage.abweichungen.length > 0 && !einladung.abgesagt && (
            <span className="flex flex-wrap items-center gap-2">
              <span>
                {t('termin.geaendert', {
                  was: lage.abweichungen.map((a) => t(`termin.abweichung_${a}`)).join(', '),
                })}
              </span>
              <Button
                size="sm"
                variant="secondary"
                iconLeft={<RefreshCw className="size-3.5" />}
                loading={laeuft === 'aktualisieren'}
                onClick={() => void mitNextimeTun('aktualisieren')}
              >
                {t('termin.in_nextime_uebernehmen')}
              </Button>
            </span>
          )}
          {/* AC-18: Eine abgesagte Kopie aus einer Mail geht erst auf Klick. */}
          {einladung.abgesagt && lage.ausMail && lage.terminId !== null && (
            <span>
              <Button
                size="sm"
                variant="secondary"
                iconLeft={<Trash2 className="size-3.5" />}
                loading={laeuft === 'entfernen'}
                onClick={() => void mitNextimeTun('entfernen')}
              >
                {t('termin.aus_nextime_entfernen')}
              </Button>
            </span>
          )}
        </div>
      )}

      {fehler && <p className="mb-0 pl-7 text-[12px] text-danger">{fehler}</p>}

      {!einladung.abgesagt && (
        <div className="flex flex-wrap items-center gap-2 pl-7">
          {knoepfe.map((k) => (
            <Button
              key={k.id}
              size="sm"
              variant={einladung.antwort === k.id ? 'primary' : 'secondary'}
              iconLeft={k.symbol}
              loading={laeuft === k.id}
              onClick={() => void antworten(k.id)}
            >
              {t(`termin.${k.id}`)}
            </Button>
          ))}
          {/* ⚠️ **Übernehmen ist ein eigener Knopf, keine Folge des
              Zusagens.** Steht der Termin schon im Kalender, sagt die Karte
              das — sonst legt man ihn zweimal an. */}
          {mitNextime ? null : einladung.imKalender ? (
            <span className="flex items-center gap-1.5 text-[12px] text-fg-4">
              <Check aria-hidden className="size-3.5 shrink-0 text-accent" />
              {t('termin.im_kalender')}
            </span>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              iconLeft={<CalendarPlus className="size-4" />}
              loading={laeuft === 'uebernehmen'}
              onClick={() => void uebernehmen()}
            >
              {t('termin.in_kalender')}
            </Button>
          )}

          {/* ⚠️ **Was geantwortet wurde, steht da.** Sonst sieht die Karte
              beim zweiten Öffnen aus wie beim ersten, und man antwortet
              zweimal. */}
          {einladung.antwort && einladung.antwortAm && (
            <span className="text-[12px] text-fg-4">
              {t('termin.geantwortet', {
                was: t(`termin.${einladung.antwort}_erledigt`),
                wann: new Date(einladung.antwortAm).toLocaleString(i18n.language, {
                  dateStyle: 'short',
                  timeStyle: 'short',
                }),
              })}
            </span>
          )}
        </div>
      )}

      {nachfrage}
    </section>
  )
}
