/* Die Termin-Einladung im Lesebereich.
 *
 * ⚠️ **nexmail hat keinen Kalender, und die Karte sagt es.** Eine Zusage
 * benachrichtigt den Einladenden, sie legt den Termin nirgends ab. Wer das
 * verwechselt, wartet auf eine Erinnerung, die nie kommt.
 *
 * ⚠️ **Was nicht sicher ist, wird benannt statt geraten.** Eine Wiederholung
 * steht als Hinweis da, nicht als ausgerechnete Reihe; eine unbekannte
 * Zeitzone steht mit ihrem Namen daneben, statt die Zeit stillschweigend als
 * Ortszeit auszugeben. Beides wäre sonst um Stunden falsch, ohne dass man es
 * der Anzeige ansieht.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarDays, Check, Clock, MapPin, Repeat, Users, X } from 'lucide-react'
import type { Einladung } from '../api/laden'
import { terminAntworten } from '../api/laden'
import { Button } from '../ds'
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

  const antworten = async (antwort: 'zusage' | 'vorbehalt' | 'absage') => {
    setFehler('')
    setLaeuft(antwort)
    try {
      aufAntwort(await terminAntworten(nachrichtId, antwort))
    } catch {
      setFehler(t('termin.fehler'))
    } finally {
      setLaeuft('')
    }
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
          eine Zusage für einen Eintrag im Kalender. */}
      <p className="mb-0 pl-7 text-[11px] text-fg-4">{t('termin.kein_kalender')}</p>

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
    </section>
  )
}
