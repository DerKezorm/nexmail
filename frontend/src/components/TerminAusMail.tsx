/* „Termin daraus machen" — aus einer Mail ein Termin, in nextime oder einem
 * eigenen Kalender (MAIL-1 AC-17).
 *
 * ⚠️ **Der Kalender wird jedes Mal gewählt**, vorgewählt der, den man zuletzt
 * für dasselbe Postfach genommen hat (AC-5): Geschäftliche und private Post
 * gehören in verschiedene Kalender. Ohne Vorwahl gilt nextimes Standard.
 *
 * ⚠️ **Eine Kennung je Fenster** (`anfrage`): Ein Doppelklick auf „Anlegen"
 * schickt sie zweimal, und es entsteht doch nur ein Termin (EC-15). Ein
 * zweiter, bewusster Termin aus derselben Mail kommt aus einem neuen Fenster.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarClock, ExternalLink } from 'lucide-react'
import {
  ausMailLaden,
  kalenderLaden,
  neueAnfrage,
  terminAusMail,
  type AusMail,
  type KalenderZeile,
} from '../api/laden'
import { Button, Checkbox, Dialog, Input, Select } from '../ds'
import { servermeldung } from '../lib/servermeldung'

/** Woran der Lesebereich erkennt, dass aus einer Mail ein Termin wurde. */
export const TERMIN_AUS_MAIL = 'nexmail:termin-aus-mail'

export interface MailFuerTermin {
  id: string
  betreff: string
}

/** Ortszeit fürs Feld `datetime-local`. */
function feld(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Morgen zur nächsten vollen Stunde von jetzt — eine Mail plant selten für gleich. */
function vorschlag(): Date {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setMinutes(0, 0, 0)
  d.setHours(Math.min(Math.max(d.getHours() + 1, 8), 18))
  return d
}

export function TerminAusMail({ mail, aufZu }: { mail: MailFuerTermin | null; aufZu: () => void }) {
  const { t } = useTranslation()
  const [kalender, setKalender] = useState<KalenderZeile[] | null>(null)
  const [kalenderId, setKalenderId] = useState('')
  const [titel, setTitel] = useState('')
  const [ganztaegig, setGanztaegig] = useState(false)
  const [beginn, setBeginn] = useState('')
  const [ende, setEnde] = useState('')
  const [ort, setOrt] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const anfrage = useRef('')

  useEffect(() => {
    if (!mail) return
    anfrage.current = neueAnfrage()
    const start = vorschlag()
    // EC-21: Ohne Betreff steht „(kein Betreff)" da, sonst bliebe Speichern gesperrt.
    setTitel(mail.betreff.trim() || t('liste.kein_betreff'))
    setGanztaegig(false)
    setBeginn(feld(start))
    setEnde(feld(new Date(start.getTime() + 60 * 60 * 1000)))
    setOrt('')
    setFehler('')
    setKalender(null)
    void Promise.all([
      kalenderLaden(),
      ausMailLaden(mail.id).catch(() => ({ vorwahl: '', termine: [] }) as AusMail),
    ])
      .then(([alle, aus]) => {
        const offene = alle.filter((k) => !k.nurLesen)
        setKalender(offene)
        setKalenderId(
          offene.find((k) => k.id === aus.vorwahl)?.id ??
            offene.find((k) => k.standard)?.id ??
            offene[0]?.id ??
            '',
        )
      })
      .catch((f) => setFehler(servermeldung(f)))
  }, [mail, t])

  async function anlegen() {
    if (!mail || !kalenderId) return
    setLaeuft(true)
    setFehler('')
    try {
      /* ⚠️ **Ganztägig ist ein Kalendertag**, keine Mitternacht in Ortszeit;
         das Ende ist der Tag danach (wie überall in nexmail). */
      const tag = (wert: string, mehr = 0) => {
        const d = new Date(`${wert.slice(0, 10)}T00:00:00Z`)
        d.setUTCDate(d.getUTCDate() + mehr)
        return d.toISOString()
      }
      await terminAusMail(mail.id, {
        kalenderId,
        titel: titel.trim(),
        beginn: ganztaegig ? tag(beginn) : new Date(beginn).toISOString(),
        ende: ganztaegig ? tag(ende || beginn, 1) : ende ? new Date(ende).toISOString() : undefined,
        ganztaegig,
        ort: ort.trim(),
        anfrage: anfrage.current,
      })
      window.dispatchEvent(new CustomEvent(TERMIN_AUS_MAIL, { detail: mail.id }))
      aufZu()
    } catch (f) {
      setFehler(servermeldung(f, t('termin.aus_mail_fehler')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Dialog
      open={mail !== null}
      width={460}
      title={t('termin.aus_mail')}
      onClose={aufZu}
      footer={
        <>
          <Button variant="ghost" onClick={aufZu}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant="primary"
            loading={laeuft}
            disabled={laeuft || !kalenderId || !titel.trim() || !beginn}
            onClick={() => void anlegen()}
          >
            {t('termin.aus_mail_anlegen')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-sm">
        <Input label={t('kalender.titel')} value={titel} onChange={(e) => setTitel(e.target.value)} />
        <Checkbox label={t('kalender.ganztaegig')} checked={ganztaegig} onCheckedChange={setGanztaegig} />
        <div className="flex gap-3">
          <Input
            label={t('kalender.beginn')}
            type={ganztaegig ? 'date' : 'datetime-local'}
            value={ganztaegig ? beginn.slice(0, 10) : beginn}
            onChange={(e) => setBeginn(e.target.value)}
          />
          <Input
            label={t('kalender.ende')}
            type={ganztaegig ? 'date' : 'datetime-local'}
            value={ganztaegig ? ende.slice(0, 10) : ende}
            onChange={(e) => setEnde(e.target.value)}
          />
        </div>
        <Input label={t('kalender.ort')} value={ort} onChange={(e) => setOrt(e.target.value)} />
        {kalender !== null && kalender.length === 0 ? (
          <p className="mb-0 text-[12px] text-warning">{t('termin.kein_ziel')}</p>
        ) : (
          <Select
            label={t('kalender.kalender_feld')}
            value={kalenderId}
            disabled={kalender === null}
            onChange={(e) => setKalenderId(e.target.value)}
          >
            {(kalender ?? []).map((k) => (
              <option key={k.id} value={k.id}>
                {k.art === 'nextime' && k.herkunft ? `${k.name} · ${k.herkunft}` : k.name}
              </option>
            ))}
          </Select>
        )}
        <p className="mb-0 text-[11px] text-fg-4">{t('termin.aus_mail_hinweis')}</p>
        {fehler && <p className="mb-0 text-[12px] text-danger">{fehler}</p>}
      </div>
    </Dialog>
  )
}

/** Die Zeile im Lesebereich: welche Termine aus dieser Mail entstanden sind. */
export function TermineAusMail({ nachrichtId }: { nachrichtId: string }) {
  const { t, i18n } = useTranslation()
  const [termine, setTermine] = useState<AusMail['termine']>([])

  useEffect(() => {
    let gilt = true
    const laden = () =>
      void ausMailLaden(nachrichtId)
        .then((a) => {
          if (gilt) setTermine(a.termine)
        })
        .catch(() => {
          // Beiwerk: Die Mail steht auch ohne diese Zeile da.
        })
    setTermine([])
    laden()
    const neu = (e: Event) => {
      if ((e as CustomEvent).detail === nachrichtId) laden()
    }
    window.addEventListener(TERMIN_AUS_MAIL, neu)
    return () => {
      gilt = false
      window.removeEventListener(TERMIN_AUS_MAIL, neu)
    }
  }, [nachrichtId])

  if (termine.length === 0) return null
  return (
    <div className="mx-6 mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-fg-3">
      <CalendarClock aria-hidden className="size-3.5 shrink-0 text-accent-text" />
      <span>{t('termin.aus_mail_entstanden')}</span>
      {termine.map((z) => (
        <span key={z.id} className="flex items-center gap-1.5">
          <span className="text-fg-1">{z.titel}</span>
          <span className="text-fg-4">
            {new Date(z.beginn).toLocaleString(i18n.language, {
              dateStyle: 'short',
              ...(z.ganztaegig ? { timeZone: 'UTC' } : { timeStyle: 'short' }),
            })}
          </span>
          {z.link && (
            <a
              href={z.link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-accent-text hover:underline"
            >
              <ExternalLink aria-hidden className="size-3" />
              {t('kalender.in_nextime_oeffnen')}
            </a>
          )}
        </span>
      ))}
    </div>
  )
}
