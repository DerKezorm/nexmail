/* Fällige Erinnerungen — das Sammelfenster.
 *
 * ⚠️ **Eine Erinnerung, die von selbst verschwindet, hat man verpasst.** Ein
 * Toast unten wäre billiger; er ist nach vier Sekunden weg, und wer gerade in
 * einer Mail liest, sieht ihn nie. Deshalb ein Fenster, das stehen bleibt, bis
 * jemand handelt — so macht es Thunderbird, und aus demselben Grund.
 *
 * ⚠️ **Schlummern ist nicht Wegklicken.** Wer „Erledigt" drückt, sagt: Ich
 * weiß Bescheid. Wer schlummert, sagt: gleich noch einmal. Beides in einen
 * Knopf zu legen hieße, eine der beiden Absichten zu verlieren.
 *
 * ⚠️ **Der Kanal heißt „in der App", und er ZEIGT.** Der Server behält eine
 * fällige Erinnerung, bis sie erledigt oder geschlummert ist — wer die Seite
 * neu lädt, findet sie wieder. Ein Push würde stattdessen genau einmal feuern;
 * dafür trägt der Server schon die Unterscheidung.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BellRing, MapPin } from 'lucide-react'
import { Button, Dialog } from '../ds'
import { PUNKT_KLASSE } from '../lib/farben'
import type { FaelligeErinnerung } from '../api/laden'
import { erinnerungErledigt, erinnerungSchlummern, erinnerungenLaden } from '../api/laden'

/** Wie oft nachgefragt wird. ⚠️ Nicht kürzer: Eine Erinnerung ist auf die
 *  Minute genau, nicht auf die Sekunde — und jeder Abruf ist eine Abfrage über
 *  alle Termine im Fenster. */
const TAKT = 30_000

/** Die Schlummerzeiten. Dieselben wie im Server (`SCHLUMMER`). */
const SCHLUMMER = [5, 15, 60]

export function Erinnerungsfenster() {
  const { t, i18n } = useTranslation()
  const [faellig, setFaellig] = useState<FaelligeErinnerung[]>([])
  const [laeuft, setLaeuft] = useState(0)

  const holen = useCallback(async () => {
    try {
      setFaellig(await erinnerungenLaden())
    } catch {
      /* ⚠️ **Ein misslungener Abruf leert die Liste nicht.** Sonst
         verschwände eine offene Erinnerung, weil der Server kurz nicht
         antwortet — und man hielte sie für erledigt. */
    }
  }, [])

  useEffect(() => {
    void holen()
    const uhr = window.setInterval(() => void holen(), TAKT)
    return () => window.clearInterval(uhr)
  }, [holen])

  async function handeln(id: number, was: () => Promise<void>) {
    setLaeuft(id)
    try {
      await was()
      // Sofort aus der Liste nehmen, nicht auf den nächsten Takt warten:
      // Ein Knopf, dessen Wirkung erst in dreißig Sekunden kommt, wirkt kaputt.
      setFaellig((alt) => alt.filter((e) => e.id !== id))
    } finally {
      setLaeuft(0)
    }
  }

  if (faellig.length === 0) return null

  return (
    <Dialog
      open
      width={480}
      title={t('erinnerung.titel', { count: faellig.length })}
      /* ⚠️ **Wegklicken heisst schlummern, nicht wegwerfen.**
         Ein Fenster, aus dem es keinen Weg gibt, sperrt die ganze Anwendung —
         bei drei offenen Erinnerungen kommt man an nichts mehr heran. Ein
         Klick daneben ist aber auch keine Antwort auf „gleich hast du einen
         Termin". Also der dritte Weg: Escape und der Klick daneben schieben
         alles um fünf Minuten. Man kommt weiter, und verloren ist nichts. */
      onClose={() =>
        void (async () => {
          for (const e of faellig) await erinnerungSchlummern(e.id, 5)
          setFaellig([])
        })()
      }
      footer={
        <Button
          variant="primary"
          onClick={() =>
            void (async () => {
              for (const e of faellig) await erinnerungErledigt(e.id)
              setFaellig([])
            })()
          }
        >
          {t('erinnerung.alle_erledigt')}
        </Button>
      }
    >
      <ul className="flex list-none flex-col gap-3 p-0">
        {faellig.map((e) => (
          <li key={e.id} className="flex flex-col gap-2 rounded-lg border border-line p-3">
            <div className="flex items-start gap-2">
              <BellRing aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
              <div className="min-w-0 flex-1">
                <p className="mb-0 truncate text-[14px] font-medium text-fg-1">{e.titel}</p>
                <p className="mb-0 text-[12px] text-fg-3">{wann(e, i18n.language, t)}</p>
                {e.ort && (
                  <p className="mb-0 mt-0.5 flex items-center gap-1 truncate text-[12px] text-fg-4">
                    <MapPin aria-hidden className="size-3.5 shrink-0" />
                    {e.ort}
                  </p>
                )}
              </div>
              <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-fg-4">
                <span aria-hidden className={`size-2 rounded-full ${PUNKT_KLASSE[e.farbe]}`} />
                {e.kalender}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-fg-4">{t('erinnerung.schlummern')}</span>
              {SCHLUMMER.map((min) => (
                <Button
                  key={min}
                  size="sm"
                  variant="ghost"
                  disabled={laeuft === e.id}
                  onClick={() => void handeln(e.id, () => erinnerungSchlummern(e.id, min))}
                >
                  {min < 60 ? t('erinnerung.min', { count: min }) : t('erinnerung.std', { count: 1 })}
                </Button>
              ))}
              <span className="flex-1" />
              <Button
                size="sm"
                variant="secondary"
                disabled={laeuft === e.id}
                onClick={() => void handeln(e.id, () => erinnerungErledigt(e.id))}
              >
                {t('erinnerung.erledigt')}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Dialog>
  )
}

/** „In 15 Minuten" — oder die Uhrzeit, wenn der Termin schon läuft. */
function wann(
  e: FaelligeErinnerung,
  sprache: string,
  t: (k: string, o?: Record<string, unknown>) => string,
): string {
  const beginn = new Date(e.beginn)
  if (e.ganztaegig) {
    return beginn.toLocaleDateString(sprache, { dateStyle: 'full' })
  }
  const minuten = Math.round((beginn.getTime() - Date.now()) / 60_000)
  const uhr = beginn.toLocaleTimeString(sprache, { timeStyle: 'short' })
  if (minuten < 0) return t('erinnerung.laeuft_seit', { uhr })
  if (minuten === 0) return t('erinnerung.jetzt', { uhr })
  if (minuten < 60) return t('erinnerung.in_min', { count: minuten, uhr })
  return t('erinnerung.um', { uhr })
}
