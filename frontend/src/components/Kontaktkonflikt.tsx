/* Zwei Fassungen desselben Kontakts, nebeneinander.
 *
 * Das Gegenstück zu `Konfliktfenster.tsx` beim Kalender, aus demselben Grund:
 * Ein 412 vom Anbieter heißt „jemand hat die Karte am Telefon geändert, seit
 * du sie geöffnet hast". Die eigene Änderung wegzuwerfen wäre die schlechteste
 * der drei Antworten; sie blind darüberzuschreiben die zweitschlechteste.
 *
 * ⚠️ **Ansehen ist keine Entscheidung.** Die fremde Fassung kommt vom Server
 * als Attrappe (`GET …/konflikt`); weder die Zeile noch ihr ETag werden dabei
 * angefasst. Gespeichert ist nichts, solange die Frage offen ist.
 *
 * ⚠️ **Drei Ausgänge, nicht zwei.** Meine Fassung, die andere — und abbrechen.
 * Die eigene Eingabe steht ja noch im Formular dahinter.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'
import { api } from '../api/client'
import { Button, Dialog } from '../ds'
import { servermeldung } from '../lib/servermeldung'

/** Was der Mensch entschieden hat. */
export type Kontaktwahl = 'meine' | 'andere'

/** Die Felder, um die es geht — dieselben fünf, die das Formular kennt. */
export interface Kontaktfassung {
  name: string
  adresse: string
  firma: string
  telefon: string
  notiz: string
}

interface Konfliktbild {
  vorhanden: boolean
  fremd: Kontaktfassung | null
}

function Fassung({
  kopf,
  fassung,
  betont,
}: {
  kopf: string
  fassung: Kontaktfassung | null
  betont?: boolean
}) {
  const { t } = useTranslation()
  const zeilen: Array<[string, string]> = fassung
    ? [
        [t('kontakte.name'), fassung.name],
        [t('kontakte.adresse'), fassung.adresse],
        [t('kontakte.telefon'), fassung.telefon],
        [t('kontakte.firma'), fassung.firma],
        [t('kontakte.notiz'), fassung.notiz],
      ]
    : []
  return (
    <div
      className={`flex min-w-0 flex-1 flex-col gap-1 rounded-lg border p-3 ${
        betont ? 'border-accent bg-surface-3' : 'border-line bg-surface-2'
      }`}
    >
      <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-4 uppercase">{kopf}</span>
      {fassung ? (
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12px]">
          {zeilen.map(([marke, wert]) => (
            <div key={marke} className="contents">
              <dt className="text-fg-4">{marke}</dt>
              <dd className="m-0 truncate text-fg-1">{wert || '–'}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <span className="text-[12px] text-fg-3">…</span>
      )}
    </div>
  )
}

export function Kontaktkonflikt({
  kontaktId,
  meine,
  aufWahl,
  aufSchliessen,
}: {
  kontaktId: number
  /** Die eigene Fassung, so wie sie gespeichert werden sollte. */
  meine: Kontaktfassung
  aufWahl: (wahl: Kontaktwahl) => void
  aufSchliessen: () => void
}) {
  const { t } = useTranslation()
  const [fremd, setFremd] = useState<Kontaktfassung | null>(null)
  const [geloescht, setGeloescht] = useState(false)
  const [fehler, setFehler] = useState('')
  const [laedt, setLaedt] = useState(true)

  useEffect(() => {
    let gilt = true
    void (async () => {
      try {
        const bild = await api.holen<Konfliktbild>(`/api/kontakte/${kontaktId}/konflikt`)
        if (!gilt) return
        setGeloescht(!bild.vorhanden)
        setFremd(bild.fremd)
      } catch (f) {
        /* ⚠️ Ein Netzfehler beim Nachsehen ist nicht „dort ist nichts". Die
           Kennung `konflikt_nicht_abrufbar` sagt, dass die Änderung nicht
           verloren ist; die Knöpfe bleiben gesperrt. */
        if (gilt) setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      } finally {
        if (gilt) setLaedt(false)
      }
    })()
    return () => {
      gilt = false
    }
  }, [kontaktId, t])

  return (
    <Dialog
      open
      width={620}
      title={t('kontakte.konflikt_titel')}
      onClose={aufSchliessen}
      footer={
        <>
          <Button variant="ghost" onClick={aufSchliessen}>
            {t('aktion.abbrechen')}
          </Button>
          {/* ⚠️ Nur anbieten, was es gibt: Ist die Karte drüben gelöscht,
              gibt es keine fremde Fassung zu übernehmen. */}
          {!geloescht && (
            <Button variant="ghost" disabled={laedt || Boolean(fehler)} onClick={() => aufWahl('andere')}>
              {t('kontakte.konflikt_andere')}
            </Button>
          )}
          <Button variant="primary" disabled={laedt || Boolean(fehler)} onClick={() => aufWahl('meine')}>
            {t('kontakte.konflikt_meine')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p className="mb-0 text-[13px] text-warning-text">
            {geloescht ? t('kontakte.konflikt_geloescht') : t('kontakte.konflikt_hinweis')}
          </p>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        {!geloescht && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Fassung kopf={t('kontakte.konflikt_meine_kopf')} fassung={meine} betont />
            <Fassung kopf={t('kontakte.konflikt_andere_kopf')} fassung={fremd} />
          </div>
        )}
      </div>
    </Dialog>
  )
}
