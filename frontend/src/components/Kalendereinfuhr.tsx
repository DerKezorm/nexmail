/* Eine `.ics` in einen Kalender einspielen.
 *
 * ⚠️ **Der Bericht ist der halbe Sinn.** „Fertig" sagt nicht, ob etwas ankam.
 * Wer dieselbe Datei zweimal einliest, muss sehen, dass diesmal nichts
 * angelegt und alles übersprungen wurde — sonst hält er den Import für kaputt
 * oder legt ihn ein drittes Mal an.
 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarCheck, Upload } from 'lucide-react'
import { api } from '../api/client'
import { Button, Dialog } from '../ds'
import { servermeldung } from '../lib/servermeldung'

interface Bericht {
  angelegt: number
  uebersprungen: number
  unbrauchbar: number
  abgeschnitten: boolean
  fehler: string[]
}

export function Kalendereinfuhr({
  kalenderId,
  kalenderName,
  aufFertig,
  aufSchliessen,
}: {
  kalenderId: string
  kalenderName: string
  /** Läuft, wenn wirklich etwas angelegt wurde — dann muss die Ansicht neu. */
  aufFertig: () => void
  aufSchliessen: () => void
}) {
  const { t } = useTranslation()
  const feld = useRef<HTMLInputElement>(null)
  const [datei, setDatei] = useState<File | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [bericht, setBericht] = useState<Bericht | null>(null)

  async function einspielen() {
    if (!datei) return
    setFehler('')
    setLaeuft(true)
    try {
      const daten = new FormData()
      daten.append('datei', datei)
      const raus = await api.formular<Bericht>(`/api/kalender/${kalenderId}/ics`, daten)
      setBericht(raus)
      if (raus.angelegt > 0) aufFertig()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Dialog
      open
      width={520}
      title={t('kalender.ics_einspielen_titel', { name: kalenderName })}
      onClose={aufSchliessen}
      /* ⚠️ Solange etwas läuft, nicht wegklickbar — dieselbe Regel wie beim
         Anlegen eines Postfachs. */
      abweisbar={!laeuft}
      footer={
        bericht ? (
          <Button variant="primary" onClick={aufSchliessen}>
            {t('aktion.schliessen')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={aufSchliessen} disabled={laeuft}>
              {t('aktion.abbrechen')}
            </Button>
            <Button
              variant="primary"
              disabled={!datei || laeuft}
              loading={laeuft}
              onClick={() => void einspielen()}
            >
              {/* ⚠️ Ohne „…": Der Menüpunkt öffnet ein Fenster, dieser Knopf
                  führt die Handlung aus. Dieselben drei Punkte an beiden
                  Stellen sagen zweimal Verschiedenes. */}
              {t('kalender.ics_jetzt_einspielen')}
            </Button>
          </>
        )
      }
    >
      {bericht ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-start gap-3 rounded-lg border border-line bg-surface-3 p-3">
            <CalendarCheck className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
            <div className="flex min-w-0 flex-col gap-1 text-[13px] text-fg-2">
              <span className="font-medium text-fg-1">
                {t('kalender.ics_angelegt', { count: bericht.angelegt })}
              </span>
              {/* ⚠️ **Übersprungene gehören dazu.** Ohne die Zahl sieht ein
                  zweiter Lauf derselben Datei wie ein Fehlschlag aus. */}
              {bericht.uebersprungen > 0 && (
                <span>{t('kalender.ics_uebersprungen', { count: bericht.uebersprungen })}</span>
              )}
              {bericht.unbrauchbar > 0 && (
                <span>{t('kalender.ics_unbrauchbar', { count: bericht.unbrauchbar })}</span>
              )}
            </div>
          </div>
          {bericht.abgeschnitten && (
            <p className="mb-0 text-[12px] text-warning-text">{t('kalender.ics_abgeschnitten')}</p>
          )}
          {bericht.fehler.length > 0 && (
            <ul className="flex max-h-40 list-none flex-col gap-1 overflow-y-auto p-0">
              {bericht.fehler.map((f) => (
                <li key={f} className="truncate text-[12px] text-danger">
                  {f}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="mb-0 text-[13px] text-fg-2">{t('kalender.ics_einspielen_hinweis')}</p>
          <input
            ref={feld}
            type="file"
            accept=".ics,text/calendar"
            className="hidden"
            onChange={(e) => setDatei(e.target.files?.[0] ?? null)}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" onClick={() => feld.current?.click()} disabled={laeuft}>
              <Upload className="size-4" aria-hidden />
              {t('kalender.ics_datei_waehlen')}
            </Button>
            <span className="min-w-0 truncate text-[13px] text-fg-3">
              {datei ? datei.name : t('kalender.ics_keine_datei')}
            </span>
          </div>
          {fehler && (
            <p role="alert" className="mb-0 text-[13px] text-danger">
              {fehler}
            </p>
          )}
        </div>
      )}
    </Dialog>
  )
}
