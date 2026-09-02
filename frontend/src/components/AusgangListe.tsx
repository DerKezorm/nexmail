/* Der Postausgang — was noch nicht draußen ist, und warum.
 *
 * Hier liegen zwei Sorten Einträge nebeneinander: geplante Nachrichten, die
 * auf ihren Zeitpunkt warten, und liegen gebliebene, deren Versand scheiterte.
 * Beide lassen sich abbrechen — der Inhalt geht dann als Entwurf zurück ins
 * Postfach, nichts geht verloren.
 *
 * ⚠️ **Der Satz des Servers wird durchgereicht** (`letzter_fehler`). „Ließ
 * sich nicht senden" sieht aus wie ein kaputter Postausgang, obwohl nur die
 * Adresse falsch war.
 */
import { useTranslation } from 'react-i18next'
import { Clock, Send } from 'lucide-react'
import { Button, EmptyState } from '../ds'
import { planzeit } from '../lib/format'
import type { Ausgangseintrag } from '../daten/typen'

interface Props {
  eintraege: Ausgangseintrag[]
  /** Den Eintrag zurücknehmen — die Rückfrage stellt `App`. */
  aufAbbrechen: (eintrag: Ausgangseintrag) => void
}

export function AusgangListe({ eintraege, aufAbbrechen }: Props) {
  const { t, i18n } = useTranslation()

  return (
    <div className="flex h-full min-h-0 flex-col border-r border-line-subtle bg-surface-1">
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-line-subtle px-3">
        <h2 className="truncate font-display text-[15px] font-medium text-fg-1">
          {t('ordner.postausgang')}
        </h2>
        <span className="shrink-0 text-[11px] tabular-nums text-fg-4">{eintraege.length}</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {eintraege.length === 0 ? (
          <EmptyState
            compact
            icon={<Send />}
            title={t('ausgang.leer_titel')}
            description={t('ausgang.leer_text')}
          />
        ) : (
          <ul className="m-0 list-none p-0">
            {eintraege.map((e) => (
              <li key={e.id} className="border-b border-line-subtle px-3 py-2.5">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="m-0 truncate text-[13px] font-medium text-fg-1">
                      {e.betreff || t('liste.kein_betreff')}
                    </p>
                    {/* „Geplant für …" nur, solange der Plan noch gilt. Ein
                        gescheiterter Eintrag trägt zwar seinen Zeitpunkt,
                        aber die Aussage ist dann eine andere. */}
                    <p className="m-0 mt-0.5 flex items-center gap-1.5 text-[12px] text-fg-3">
                      {e.senden_ab && e.stand === 'wartet' ? (
                        <>
                          <Clock aria-hidden className="size-3.5 shrink-0" />
                          {t('ausgang.geplant_fuer', { zeit: planzeit(e.senden_ab, i18n.language) })}
                        </>
                      ) : (
                        t(`ausgang.stand_${e.stand}`)
                      )}
                    </p>
                    {e.letzter_fehler && (
                      <p className="m-0 mt-0.5 text-[12px] text-danger">{e.letzter_fehler}</p>
                    )}
                  </div>
                  {/* Was gerade gesendet wird, lässt sich nicht mehr
                      zurückholen — der Knopf verschwindet, statt zu lügen. */}
                  {e.stand !== 'unterwegs' && (
                    <Button size="sm" onClick={() => aufAbbrechen(e)}>
                      {t('ausgang.abbrechen')}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
