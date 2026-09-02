/* Post hinein und hinaus — je Ordner.
 *
 * ⚠️ **Der Import ist ein Vorgang, kein Knopfdruck.** Zehntausend Mails über
 * IMAP anzuhängen dauert; das Fenster zeigt deshalb laufende Zahlen und darf
 * zugehen, ohne den Vorgang mitzunehmen. Beim Öffnen fragt es nach, ob schon
 * einer läuft — sonst verliert ein F5 die Anzeige zu einem Vorgang, der
 * weiterläuft.
 *
 * ⚠️ **Zwei Ausgänge, und sie tun Verschiedenes.** „Import abbrechen" hält
 * an, „Schließen" lässt laufen. Genau das ist die Ausnahme von „ein Fenster,
 * ein Ausgang" — und deshalb steht es an beiden Schaltflächen dran.
 *
 * ⚠️ **Der Download geht über `window.location`, nicht über `fetch`.** Eine
 * mbox kann Gigabyte haben; sie erst als Blob in den Speicher des Browsers zu
 * holen, wirft den Reiter um. So schreibt der Browser sie direkt auf die
 * Platte. Damit dabei nie eine Fehlerseite statt einer Datei kommt, fragt das
 * Fenster **vorher** ab, was der Ordner hergibt.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Upload } from 'lucide-react'
import { ApiFehler } from '../api/client'
import {
  exportVorschau,
  laufenderUmzug,
  postEinspielen,
  umzugAbbrechen,
  umzugStand,
} from '../api/laden'
import type { Exportvorschau, Umzugsstand } from '../api/laden'
import { Button, Dialog, Select } from '../ds'
import { appPfad } from '../lib/basis'
import type { Ordner } from '../daten/typen'

/** Wie oft der Stand nachgefragt wird, solange ein Import läuft. */
const TAKT_MS = 1000

interface Props {
  ordner: Ordner
  art: 'ein' | 'aus'
  onClose: () => void
  /** Nach einem Import: Liste und Ordnerzahlen neu holen. */
  onFertig?: () => void
}

export function Umzugsfenster({ ordner, art, onClose, onFertig }: Props) {
  return art === 'ein' ? (
    <Einspielen ordner={ordner} onClose={onClose} onFertig={onFertig} />
  ) : (
    <Herunterladen ordner={ordner} onClose={onClose} />
  )
}

/* --- Hinein ------------------------------------------------------------ */

function Einspielen({ ordner, onClose, onFertig }: Omit<Props, 'art'>) {
  const { t } = useTranslation()
  const [datei, setDatei] = useState<File | null>(null)
  const [stand, setStand] = useState<Umzugsstand | null>(null)
  const [fehler, setFehler] = useState('')
  const [beschaeftigt, setBeschaeftigt] = useState(false)
  const feld = useRef<HTMLInputElement>(null)
  /* ⚠️ Der Rückruf darf nicht bei jedem Takt neu greifen — sonst löst das
     Aufräumen des Effekts die Abfrage aus, die es gerade gestartet hat. */
  const fertigRef = useRef(onFertig)
  fertigRef.current = onFertig

  // Läuft schon einer? Dann zeigt das Fenster ihn, statt einen zweiten
  // anzubieten, den der Server ohnehin abweisen würde.
  useEffect(() => {
    void laufenderUmzug()
      .then((laufend) => laufend && setStand(laufend))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!stand?.laeuft) return
    let lebt = true
    const uhr = window.setInterval(() => {
      void umzugStand(stand.id)
        .then((neu) => {
          if (!lebt) return
          setStand(neu)
          if (!neu.laeuft) fertigRef.current?.()
        })
        .catch(() => undefined)
    }, TAKT_MS)
    return () => {
      lebt = false
      window.clearInterval(uhr)
    }
  }, [stand?.id, stand?.laeuft])

  async function starten() {
    if (!datei) return
    setBeschaeftigt(true)
    setFehler('')
    try {
      setStand(await postEinspielen(Number(ordner.id), datei))
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('stoerung.stamm'))
    } finally {
      setBeschaeftigt(false)
    }
  }

  const laeuft = Boolean(stand?.laeuft)
  const fertig = Boolean(stand && !stand.laeuft)

  return (
    <Dialog
      open
      width={520}
      title={t('umzug.ein_titel', { ordner: ordner.name })}
      description={stand ? undefined : t('umzug.ein_text')}
      onClose={onClose}
      footer={
        laeuft ? (
          <>
            <Button
              variant="danger"
              onClick={() => {
                if (stand) void umzugAbbrechen(stand.id).then(setStand).catch(() => undefined)
              }}
            >
              {t('aktion.abbrechen')}
            </Button>
            <Button variant="ghost" onClick={onClose}>
              {t('aktion.schliessen')}
            </Button>
          </>
        ) : fertig ? (
          <Button variant="primary" onClick={onClose}>
            {t('aktion.schliessen')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('aktion.abbrechen')}
            </Button>
            <Button
              variant="primary"
              disabled={!datei || beschaeftigt}
              loading={beschaeftigt}
              onClick={() => void starten()}
            >
              {t('umzug.ein_start')}
            </Button>
          </>
        )
      }
    >
      <div className="flex flex-col gap-3 text-sm">
        {!stand && (
          <>
            <input
              ref={feld}
              type="file"
              accept=".mbox,.mbx,application/mbox"
              className="sr-only"
              onChange={(e) => setDatei(e.target.files?.[0] ?? null)}
            />
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                iconLeft={<Upload className="size-4" />}
                onClick={() => feld.current?.click()}
              >
                {t('umzug.ein_datei_waehlen')}
              </Button>
              <span className="min-w-0 flex-1 truncate text-fg-3">
                {datei ? `${datei.name} · ${groesse(datei.size)}` : t('umzug.ein_datei')}
              </span>
            </div>
          </>
        )}

        {stand && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 font-medium text-fg-1">
              {laeuft ? (
                <span className="size-3 animate-spin rounded-full border-[1.5px] border-accent border-t-transparent" />
              ) : (
                <Check className="size-4 text-accent" />
              )}
              {laeuft ? t('umzug.ein_laeuft') : t('umzug.ein_fertig')}
            </div>
            <div className="text-fg-2">
              {t('umzug.ein_zahlen', {
                importiert: stand.importiert,
                uebersprungen: stand.uebersprungen,
              })}
            </div>
            <div className="text-[12px] text-fg-4">
              {t('umzug.ein_gelesen', { count: stand.gelesen })}
            </div>
            {laeuft && <p className="text-[12px] text-fg-4">{t('umzug.ein_dauer')}</p>}
            {stand.abgebrochen && <Hinweis text={t('umzug.ein_abgebrochen')} />}
            {stand.abgeschnitten && (
              <Hinweis text={t('umzug.ein_abgeschnitten', { count: stand.importiert })} />
            )}
            {stand.ohneKennung > 0 && (
              <Hinweis text={t('umzug.ein_ohne_kennung', { count: stand.ohneKennung })} />
            )}
            {stand.fehler && <Hinweis text={stand.fehler} />}
            {stand.fehlerGesamt > 0 && (
              <div className="flex flex-col gap-1">
                <Hinweis text={t('umzug.ein_fehler', { count: stand.fehlerGesamt })} />
                <ul className="ml-6 list-disc text-[12px] text-fg-3">
                  {stand.fehlerJeMail.map((zeile) => (
                    <li key={zeile} className="truncate">
                      {zeile}
                    </li>
                  ))}
                  {stand.fehlerGesamt > stand.fehlerJeMail.length && (
                    <li>
                      {t('umzug.ein_fehler_mehr', {
                        count: stand.fehlerGesamt - stand.fehlerJeMail.length,
                      })}
                    </li>
                  )}
                </ul>
              </div>
            )}
          </div>
        )}

        {fehler && <Hinweis text={fehler} />}
      </div>
    </Dialog>
  )
}

/* --- Hinaus ------------------------------------------------------------ */

function Herunterladen({ ordner, onClose }: Omit<Props, 'art' | 'onFertig'>) {
  const { t } = useTranslation()
  const [vorschau, setVorschau] = useState<Exportvorschau | null>(null)
  const [form, setForm] = useState<'mbox' | 'zip'>('mbox')
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    void exportVorschau(Number(ordner.id))
      .then(setVorschau)
      .catch((f) =>
        setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('stoerung.stamm')),
      )
  }, [ordner.id, t])

  const zipZuGross = Boolean(vorschau && vorschau.bekannt > vorschau.zipGrenze)
  const leer = Boolean(vorschau && vorschau.bekannt === 0)

  return (
    <Dialog
      open
      width={480}
      title={t('umzug.aus_titel', { ordner: ordner.name })}
      description={t('umzug.aus_text')}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant="primary"
            disabled={!vorschau || leer}
            onClick={() => {
              // ⚠️ Kein fetch/Blob: Eine Gigabyte-mbox im Speicher des
              // Browsers wirft den Reiter um. So schreibt er sie direkt weg.
              window.location.href = appPfad(
                `/api/austausch/export/${ordner.id}?form=${form}`,
              )
              onClose()
            }}
          >
            {t('umzug.aus_start')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-sm">
        {vorschau && (
          <>
            <div className="text-fg-2">
              {t('umzug.aus_bekannt', { count: vorschau.bekannt })}
            </div>
            {vorschau.gesamt > vorschau.bekannt && (
              <Hinweis
                text={t('umzug.aus_luecke', {
                  bekannt: vorschau.bekannt,
                  gesamt: vorschau.gesamt,
                })}
              />
            )}
            {leer && <Hinweis text={t('umzug.aus_leer')} />}
            <Select
              label={t('umzug.aus_form')}
              value={form}
              onChange={(e) => setForm(e.target.value as 'mbox' | 'zip')}
              hint={
                zipZuGross ? t('umzug.aus_zip_zu_gross', { grenze: vorschau.zipGrenze }) : undefined
              }
            >
              <option value="mbox">{t('umzug.aus_mbox')}</option>
              <option value="zip" disabled={zipZuGross}>
                {t('umzug.aus_zip')}
              </option>
            </Select>
          </>
        )}
        {fehler && <Hinweis text={fehler} />}
      </div>
    </Dialog>
  )
}

/* --- Kleinkram --------------------------------------------------------- */

function Hinweis({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-2 text-[12px] text-fg-3">
      <AlertTriangle className="mt-px size-4 shrink-0 text-warning" aria-hidden />
      <span>{text}</span>
    </p>
  )
}

function groesse(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}
