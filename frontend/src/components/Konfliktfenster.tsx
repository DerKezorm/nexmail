/* Zwei Fassungen desselben Termins, nebeneinander.
 *
 * ⚠️ **„Bitte erst abgleichen" ist keine Auskunft.** Es sagt nicht, was drüben
 * steht, und wer es befolgt, wirft seine eigene Änderung weg, ohne sie mit der
 * anderen verglichen zu haben. Bis zum 04.09.2026 war das der ganze Ausgang
 * eines Konflikts.
 *
 * ⚠️ **Drei Ausgänge, nicht zwei.** Meine Fassung, die andere — und abbrechen.
 * Wer sich nicht entscheiden kann, soll nichts verlieren; die eigene Änderung
 * steht ja noch im Formular dahinter.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'
import type { TerminZeile } from '../api/laden'
import { konfliktAnsehen } from '../api/laden'
import { Button, Dialog } from '../ds'
import { servermeldung } from '../lib/servermeldung'

/** Was der Mensch entschieden hat. */
export type Konfliktwahl = 'meine' | 'andere'

function Fassung({
  kopf,
  titel,
  wann,
  ort,
  betont,
}: {
  kopf: string
  titel: string
  wann: string
  ort: string
  betont?: boolean
}) {
  return (
    <div
      className={`flex min-w-0 flex-1 flex-col gap-1 rounded-lg border p-3 ${
        betont ? 'border-accent bg-surface-3' : 'border-line bg-surface-2'
      }`}
    >
      <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-4 uppercase">
        {kopf}
      </span>
      <span className="truncate text-[14px] font-medium text-fg-1">{titel}</span>
      <span className="text-[12px] text-fg-3">{wann}</span>
      {ort && <span className="truncate text-[12px] text-fg-3">{ort}</span>}
    </div>
  )
}

export function Konfliktfenster({
  termin,
  sprache,
  aufWahl,
  aufSchliessen,
}: {
  /** Die eigene Fassung, so wie sie gespeichert werden sollte. */
  termin: TerminZeile
  sprache: string
  aufWahl: (wahl: Konfliktwahl) => void
  aufSchliessen: () => void
}) {
  const { t } = useTranslation()
  const [fremd, setFremd] = useState<TerminZeile | null>(null)
  const [geloescht, setGeloescht] = useState(false)
  const [fehler, setFehler] = useState('')
  const [laedt, setLaedt] = useState(true)

  useEffect(() => {
    let gilt = true
    void (async () => {
      try {
        const raus = await konfliktAnsehen(termin.id)
        if (!gilt) return
        setGeloescht(!raus.vorhanden)
        setFremd(raus.fremd)
      } catch (f) {
        if (gilt) setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      } finally {
        if (gilt) setLaedt(false)
      }
    })()
    return () => {
      gilt = false
    }
  }, [termin.id, t])

  function wann(z: TerminZeile): string {
    const von = new Date(z.beginn)
    const bis = z.ende ? new Date(z.ende) : null
    if (z.ganztaegig) {
      return `${von.toLocaleDateString(sprache)} · ${t('kalender.ganztaegig')}`
    }
    const uhr: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }
    return `${von.toLocaleDateString(sprache)} · ${von.toLocaleTimeString(sprache, uhr)}${
      bis ? `–${bis.toLocaleTimeString(sprache, uhr)}` : ''
    }`
  }

  return (
    <Dialog
      open
      width={620}
      title={t('kalender.konflikt_titel')}
      onClose={aufSchliessen}
      footer={
        <>
          <Button variant="ghost" onClick={aufSchliessen}>
            {t('aktion.abbrechen')}
          </Button>
          {/* ⚠️ Nur anbieten, was es gibt: Ist der Termin drüben gelöscht,
              gibt es keine fremde Fassung zu übernehmen. */}
          {!geloescht && (
            <Button variant="ghost" disabled={laedt} onClick={() => aufWahl('andere')}>
              {t('kalender.konflikt_andere')}
            </Button>
          )}
          <Button variant="primary" disabled={laedt} onClick={() => aufWahl('meine')}>
            {t('kalender.konflikt_meine')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p className="mb-0 text-[13px] text-warning-text">
            {geloescht ? t('kalender.konflikt_geloescht') : t('kalender.konflikt_hinweis')}
          </p>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        {!geloescht && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Fassung
              kopf={t('kalender.konflikt_meine_kopf')}
              titel={termin.titel}
              wann={wann(termin)}
              ort={termin.ort}
              betont
            />
            <Fassung
              kopf={t('kalender.konflikt_andere_kopf')}
              titel={fremd ? fremd.titel : '…'}
              wann={fremd ? wann(fremd) : '…'}
              ort={fremd ? fremd.ort : ''}
            />
          </div>
        )}
      </div>
    </Dialog>
  )
}
