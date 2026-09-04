/* Alles zur KI an einem Ort.
 *
 * ⚠️ **Ein eigener Punkt in der Leiste, und das widerspricht dem Kopf von
 * `NavRail.tsx`** („ein Symbol, das man zweimal im Jahr drückt, verbraucht hier
 * nur Aufmerksamkeit"). Der Widerspruch ist bewusst und hat einen Anlass: Am
 * 04.09.2026 lag der Betreiber-Riegel unten im Reiter *Server*, unter dem
 * ganzen Postausgang. Er wurde gesucht und nicht gefunden — dann gibt es ihn
 * praktisch nicht. Ein Riegel, der entscheidet, ob Mailtext das Haus verlassen
 * darf, muss dort stehen, wo man ihn vermutet.
 *
 * ⚠️ **Und deshalb liegt hier ALLES dazu, nicht nur der Riegel.** Sonst wäre
 * die KI auf zwei Orte verteilt — Erlaubnis in der Verwaltung, eigener Zugang
 * in den Einstellungen —, und das ist schlechter als ein schlecht gelegener
 * Ort: Man findet die eine Hälfte und hält sie für das Ganze.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Lock } from 'lucide-react'
import { api } from '../api/client'
import { Switch } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import { KiDienst } from './KiDienst'

/** Ob in dieser Installation überhaupt ein KI-Dienst benutzt werden darf.
 *
 * ⚠️ **Ab Werk zu.** Ohne diesen Riegel entscheidet jeder Benutzer für sich,
 * ob Text aus seinen Mails an einen fremden Dienst geht — und der Betreiber,
 * der dafür verantwortlich ist, kann es weder sehen noch verbieten. Für einen
 * Haushalt wäre das richtig, für jede Organisation das Gegenteil.
 *
 * ⚠️ **Zusperren löscht keinen Zugang.** Die Schlüssel der Benutzer bleiben
 * stehen; benutzt werden sie nur nicht. Sonst kostete ein versehentliches
 * Zumachen alle Zugänge.
 */
function KiRiegel({ aufGeaendert }: { aufGeaendert: () => void }) {
  const { t } = useTranslation()
  const [erlaubt, setErlaubt] = useState<boolean | null>(null)
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    void api
      .holen<{ erlaubt: boolean }>('/api/ki/erlaubt')
      .then((r) => setErlaubt(r.erlaubt))
      .catch(() => undefined)
  }, [])

  async function umlegen(an: boolean) {
    setFehler('')
    try {
      const r = await api.aendern<{ erlaubt: boolean }>('/api/ki/erlaubt', { erlaubt: an })
      setErlaubt(r.erlaubt)
      /* ⚠️ Der Teil darunter hängt daran: Aufsperren muss den eigenen Zugang
         sofort zeigen, Zusperren ihn sofort verstecken. Sonst sieht der
         Betreiber seinen eigenen Riegel erst nach F5 wirken — dieselbe
         Prüffrage wie „Was ich ändere, muss ich auch sehen". */
      aufGeaendert()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="flex items-center gap-2 text-[13px] font-semibold text-fg-1">
            <Lock className="size-4 text-fg-4" aria-hidden />
            {t('verwaltung.ki')}
          </span>
          <p className="mb-0 text-[12px] text-fg-3">{t('verwaltung.ki_hinweis')}</p>
        </div>
        <Switch
          label={t('verwaltung.ki_erlauben')}
          checked={erlaubt ?? false}
          disabled={erlaubt === null}
          onCheckedChange={(an) => void umlegen(an)}
        />
      </div>
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
    </section>
  )
}

export function KiSeite({ istBetreiber }: { istBetreiber: boolean }) {
  const { t } = useTranslation()
  /* Ein Zähler statt eines Zustands: Er zwingt den unteren Teil zum Neubau,
     ohne dass diese Seite wissen müsste, was der dort lädt. */
  const [runde, setRunde] = useState(0)

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <h1 className="mb-1 text-[20px] font-semibold text-fg-1">{t('nav.ki')}</h1>
      <p className="mb-5 max-w-[720px] text-[13px] text-fg-2">{t('ki.seite_lede')}</p>

      <div className="flex max-w-[720px] flex-col gap-6">
        {istBetreiber && <KiRiegel aufGeaendert={() => setRunde((r) => r + 1)} />}
        <KiDienst key={runde} />
      </div>
    </div>
  )
}
