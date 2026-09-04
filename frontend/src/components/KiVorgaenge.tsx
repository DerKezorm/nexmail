/* Was wirklich hinausging — wörtlich, nicht zusammengefasst.
 *
 * ⚠️ **Der Zweck ist Nachprüfbarkeit.** nexmail sagt zu, dass Zitat und
 * Signatur nicht mitgehen und dass der Entwurf als Text und nicht als Anweisung
 * geschickt wird. Eine Zusage ohne Beleg ist eine Behauptung; hier steht der
 * Rumpf, wie er abgeschickt wurde.
 *
 * ⚠️ **Und es ist die Abwehr gegen versteckten Text.** Weiß auf Weiß,
 * Schriftgröße 1, ein HTML-Kommentar: Wer fremden Text in seinen Entwurf
 * einfügt, nimmt so etwas mit, ohne es im Editor zu sehen. Hier ist es
 * sichtbar — deshalb wird der Rumpf als **Text** gezeigt und nicht gerendert.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { Button } from '../ds'
import { useNachfrage } from './Nachfrage'
import { servermeldung } from '../lib/servermeldung'

interface Nachricht {
  role: string
  content: string
}

interface Rumpf {
  model?: string
  max_tokens?: number
  messages?: Nachricht[]
}

interface Vorgang {
  id: number
  zeitpunkt: string
  modell: string
  auftrag: string
  ziel: string
  rein: number
  raus: number
  fehler: string
  rumpf: Rumpf | null
}

export function KiVorgaenge({ tage }: { tage: number }) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [zeilen, setZeilen] = useState<Vorgang[] | null>(null)
  const [offen, setOffen] = useState<number | null>(null)
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<Vorgang[]>('/api/ki/vorgaenge'))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function leeren() {
    const ja = await fragen({
      titel: t('ki.liste_leeren'),
      text: t('ki.liste_leeren_frage'),
      knopf: t('ki.liste_leeren'),
      gefaehrlich: true,
    })
    if (!ja) return
    try {
      await api.loeschen('/api/ki/vorgaenge')
      setZeilen([])
      setOffen(null)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  /* Nichts zu zeigen und nichts zu erklären — dann steht der Abschnitt nicht
     da. Ein leerer Kasten mit „noch keine Einträge" ist eine Zeile, die man
     einmal liest und danach nie wieder. */
  if (zeilen !== null && zeilen.length === 0 && !fehler) return null

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('ki.vorgaenge')}</h2>
          <p className="mb-0 text-[12px] text-fg-3">{t('ki.vorgaenge_hinweis', { tage })}</p>
        </div>
        {zeilen && zeilen.length > 0 && (
          <Button variant="ghost" iconLeft={<Trash2 className="size-4" />} onClick={() => void leeren()}>
            {t('ki.liste_leeren')}
          </Button>
        )}
      </div>

      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}

      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {(zeilen ?? []).map((v) => {
          const auf = offen === v.id
          return (
            <li key={v.id} className="rounded-md border border-line bg-surface-1">
              <button
                type="button"
                aria-expanded={auf}
                onClick={() => setOffen(auf ? null : v.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left"
              >
                {auf ? (
                  <ChevronDown className="size-4 shrink-0 text-fg-4" aria-hidden />
                ) : (
                  <ChevronRight className="size-4 shrink-0 text-fg-4" aria-hidden />
                )}
                <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">
                  {t(`ki.${v.auftrag}`, { defaultValue: v.auftrag })}
                  {v.ziel && ` · ${t(`ki.ton_${v.ziel}`, { defaultValue: v.ziel })}`}
                </span>
                <span className="shrink-0 text-[12px] text-fg-4 tabular-nums">
                  {new Date(v.zeitpunkt).toLocaleString(i18n.language)}
                </span>
                {v.fehler ? (
                  <span className="shrink-0 text-[12px] text-danger">
                    {t(`serverfehler.${v.fehler}`, { defaultValue: v.fehler })}
                  </span>
                ) : (
                  <span className="shrink-0 text-[12px] text-fg-4 tabular-nums">
                    {t('ki.verbrauch', { rein: v.rein, raus: v.raus })}
                  </span>
                )}
              </button>

              {auf && (
                <div className="flex flex-col gap-2 border-t border-line-subtle px-3 py-3">
                  <p className="mb-0 text-[12px] text-fg-4">
                    {t('ki.modell')}: {v.modell}
                  </p>
                  {v.rumpf === null ? (
                    <p className="mb-0 text-[12px] text-fg-4">{t('ki.rumpf_unlesbar')}</p>
                  ) : (
                    (v.rumpf.messages ?? []).map((n, i) => (
                      <div key={i} className="flex flex-col gap-1">
                        <span className="text-[11px] font-semibold uppercase tracking-wide text-fg-4">
                          {n.role === 'system' ? t('ki.anweisung') : t('ki.dein_text')}
                        </span>
                        {/* ⚠️ Als Text, nicht gerendert — sonst wäre versteckter
                            Text hier genauso unsichtbar wie im Editor. */}
                        <pre className="m-0 max-h-[260px] overflow-auto rounded-md border border-line bg-surface-2 p-2.5 text-[12px] leading-relaxed break-words whitespace-pre-wrap text-fg-2">
                          {n.content}
                        </pre>
                      </div>
                    ))
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {nachfrage}
    </section>
  )
}
