/* Einstellungen → Kalender und Adressbücher.
 *
 * ⚠️ **Ein zweiter Eingang, kein zweiter Weg** (gemeldet am 23.11.2026):
 * Anlegen geht hier und über „+" an der Überschrift in Kalender und Kontakten;
 * beide öffnen dasselbe Fenster (`Kalenderfenster`, `Buchfenster`), und
 * Umbenennen und Entfernen fragen hier dasselbe wie im Menü des Kalenders.
 * Dieselbe Regel wie bei den Postfächern: zwei Eingänge, ein Ablauf.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, BookUser, CalendarDays, Link2, PenLine, Plus, Trash2, Unlink } from 'lucide-react'
import { api } from '../../api/client'
import { kalenderAendern, kalenderEntfernen, kalenderLaden } from '../../api/laden'
import type { KalenderZeile } from '../../api/laden'
import { Button, IconButton } from '../../ds'
import { Kalenderfenster } from '../../components/Kalenderfenster'
import { Buchfenster } from '../../components/Buchfenster'
import { useNachfrage } from '../../components/Nachfrage'
import { PUNKT_KLASSE } from '../../lib/farben'
import { servermeldung } from '../../lib/servermeldung'
import type { Postfachfarbe } from '../../daten/typen'
import type { Buch } from '../KontaktePage'
import { Karte } from './Karte'

export function KalenderUndBuecher() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [kalender, setKalender] = useState<KalenderZeile[] | null>(null)
  const [buecher, setBuecher] = useState<Buch[] | null>(null)
  const [fehler, setFehler] = useState('')
  const [kalenderNeu, setKalenderNeu] = useState(false)
  const [buchNeu, setBuchNeu] = useState(false)

  const laden = useCallback(async () => {
    try {
      const [k, b] = await Promise.all([kalenderLaden(), api.holen<Buch[]>('/api/adressbuecher')])
      setKalender(k)
      setBuecher(b)
      setFehler('')
    } catch (f) {
      setFehler(servermeldung(f))
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  async function mit(tun: () => Promise<unknown>) {
    try {
      await tun()
      await laden()
    } catch (f) {
      setFehler(servermeldung(f))
    }
  }

  async function umbenennen(k: KalenderZeile) {
    const name = await fragen({
      titel: t('kalender.umbenennen'),
      text: t('kalender.umbenennen_frage'),
      eingabe: { beschriftung: t('kalender.name'), vorgabe: k.name },
      knopf: t('aktion.speichern'),
    })
    if (typeof name !== 'string' || !name.trim()) return
    await mit(() => kalenderAendern(k.id, { name: name.trim() }))
  }

  async function kalenderWeg(k: KalenderZeile) {
    /* ⚠️ Bei einer Gegenstelle sagt die Rückfrage, dass dort nichts gelöscht
       wird; ohne den Satz klingt „entfernen" nach „weg". Die Zahl der Termine
       kennt diese Seite nicht, deshalb ohne sie. */
    const ja = await fragen({
      titel: t('kalender.entfernen_frage', { name: k.name }),
      text: k.art ? t('kalender.entfernen_gegenstelle', { wo: k.herkunft }) : t('einstellungen.kalender_weg_text'),
      knopf: k.art ? t('kalender.trennen') : t('kalender.entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(() => kalenderEntfernen(k.id))
  }

  async function buchWeg(b: Buch) {
    const ja = await fragen({
      titel: t('kontakte.buch_trennen_frage', { name: b.name }),
      text: t('kontakte.buch_trennen_text', { count: b.kontakte, wo: b.herkunft }),
      knopf: t('kontakte.buch_trennen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(() => api.loeschen(`/api/adressbuecher/${b.id}`))
  }

  const zeile = 'flex items-center gap-2.5 rounded-lg border border-line px-3 py-2'

  return (
    <>
      {fehler && (
        <p role="alert" className="mb-0 rounded-md border border-danger bg-danger-soft px-3 py-2 text-[13px] text-fg-1">
          {fehler}
        </p>
      )}

      <Karte id="kalender" symbol={CalendarDays} titel={t('einstellungen.kalender_titel')} text={t('einstellungen.kalender_text')}>
        {(kalender ?? []).map((k) => (
          <div key={k.id} className={zeile}>
            <span aria-hidden className={`size-2.5 shrink-0 rounded-sm ${PUNKT_KLASSE[k.farbe]}`} />
            <div className="min-w-0 flex-1">
              <p className="mb-0 truncate text-[14px] text-fg-1">{k.name}</p>
              <p className="mb-0 truncate text-[12px] text-fg-4">
                {k.art ? `${k.herkunft}${k.nurLesen ? ` · ${t('kalender.nur_lesen')}` : ''}` : t('einstellungen.nur_hier')}
              </p>
            </div>
            {k.letzterFehler ? (
              <AlertTriangle aria-label={t('kalender.fehler_allgemein')} className="size-4 shrink-0 text-warning" />
            ) : (
              k.art && <Link2 aria-hidden className="size-4 shrink-0 text-fg-4" />
            )}
            <IconButton icon={<PenLine />} label={t('kalender.umbenennen')} size="sm" onClick={() => void umbenennen(k)} />
            <IconButton
              icon={k.art ? <Unlink /> : <Trash2 />}
              label={k.art ? t('kalender.trennen') : t('kalender.entfernen')}
              size="sm"
              onClick={() => void kalenderWeg(k)}
            />
          </div>
        ))}
        <div>
          <Button iconLeft={<Plus className="size-4" />} onClick={() => setKalenderNeu(true)}>
            {t('kalender.hinzufuegen_kurz')}
          </Button>
        </div>
      </Karte>

      <Karte id="adressbuecher" symbol={BookUser} titel={t('einstellungen.buecher_titel')} text={t('einstellungen.buecher_text')}>
        {(buecher ?? []).map((b) => (
          <div key={b.id} className={zeile}>
            <span aria-hidden className={`size-2.5 shrink-0 rounded-sm ${PUNKT_KLASSE[b.farbe as Postfachfarbe]}`} />
            <div className="min-w-0 flex-1">
              <p className="mb-0 truncate text-[14px] text-fg-1">{b.name}</p>
              <p className="mb-0 truncate text-[12px] text-fg-4">
                {(b.art ? b.herkunft : t('einstellungen.nur_hier')) + ` · ${t('einstellungen.kontakte_zahl', { count: b.kontakte })}`}
              </p>
            </div>
            {b.letzter_fehler ? (
              <AlertTriangle aria-label={t('kalender.fehler_allgemein')} className="size-4 shrink-0 text-warning" />
            ) : (
              b.art && <Link2 aria-hidden className="size-4 shrink-0 text-fg-4" />
            )}
            {b.art && (
              <IconButton icon={<Unlink />} label={t('kontakte.buch_trennen')} size="sm" onClick={() => void buchWeg(b)} />
            )}
          </div>
        ))}
        <div>
          <Button iconLeft={<Plus className="size-4" />} onClick={() => setBuchNeu(true)}>
            {t('kontakte.buch_verbinden')}
          </Button>
        </div>
      </Karte>

      {kalenderNeu && (
        <Kalenderfenster vorhanden={kalender ?? []} onClose={() => setKalenderNeu(false)} onFertig={() => void laden()} />
      )}
      {buchNeu && <Buchfenster onClose={() => setBuchNeu(false)} onFertig={() => void laden()} />}
      {nachfrage}
    </>
  )
}
