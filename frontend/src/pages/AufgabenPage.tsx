/* Aufgaben — Mails, die noch etwas von einem wollen.
 *
 * ⚠️ **Eine Aufgabe zeigt auf ihre Mail, sie kopiert sie nicht.** Ein Klick
 * öffnet die Mail; das Abhaken lässt sie, wo sie ist. nexmail wird kein
 * Aufgabenverwalter — es merkt sich nur, was noch offen ist.
 *
 * ⚠️ **Und sie überlebt ihre Mail.** Wer im Papierkorb aufräumt, soll nicht
 * lautlos seine Liste mitlöschen. Eine verwaiste Aufgabe steht weiter da, sagt
 * es und trägt trotzdem noch Betreff und Absender — sonst weiß niemand mehr,
 * worum es ging.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, GripVertical, ListChecks, MailWarning, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Konto } from '../daten/typen'
import { PUNKT_KLASSE } from '../lib/farben'
import { EmptyState, IconButton } from '../ds'
import { servermeldung } from '../lib/servermeldung'

export interface AufgabenZeile {
  id: number
  nachricht_id: number | null
  konto_id: string
  betreff: string
  von_name: string
  von_adresse: string
  mail_datum: string | null
  erledigt: string | null
  faellig: string | null
  verwaist: boolean
}

interface Props {
  konten: Konto[]
  /** Die Mail zu einer Aufgabe öffnen. */
  aufMail: (nachrichtId: number) => void
  /** Nach jeder Änderung, damit die Zahl an der Leiste stimmt. */
  aufAenderung?: () => void
}

export function AufgabenPage({ konten, aufMail, aufAenderung }: Props) {
  const { t } = useTranslation()
  const [zeilen, setZeilen] = useState<AufgabenZeile[] | null>(null)
  const [fehler, setFehler] = useState('')
  const [gezogen, setGezogen] = useState<number | null>(null)
  const [ueber, setUeber] = useState<number | null>(null)

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<AufgabenZeile[]>('/api/aufgaben'))
      setFehler('')
    } catch (f) {
      // ⚠️ Ein Fehler darf nicht wie eine leere Liste aussehen — dieselbe
      // Regel wie bei den Postfächern.
      setFehler(servermeldung(f, t('aufgaben.laden_ging_nicht')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function mit(tun: () => Promise<unknown>) {
    try {
      await tun()
      await laden()
      aufAenderung?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function ablegen(zielId: number) {
    if (zeilen === null || gezogen === null || gezogen === zielId) return
    const ohne = zeilen.filter((z) => z.id !== gezogen)
    const platz = ohne.findIndex((z) => z.id === zielId)
    const neu = [...ohne.slice(0, platz), zeilen.find((z) => z.id === gezogen)!, ...ohne.slice(platz)]
    // ⚠️ Erst hier zeichnen, dann schicken: Eine Reihenfolge, die nach dem
    // Loslassen erst zurückspringt und dann sitzt, fühlt sich kaputt an.
    setZeilen(neu)
    setGezogen(null)
    setUeber(null)
    await mit(() => api.aendern('/api/aufgaben/reihenfolge', { ids: neu.map((z) => z.id) }))
  }

  if (zeilen === null && !fehler) return <div className="h-24" />

  const offen = (zeilen ?? []).filter((z) => !z.erledigt)

  return (
    <div className="h-full overflow-y-auto bg-canvas">
      <div className="mx-auto flex max-w-[720px] flex-col gap-4 px-6 py-6">
        <div className="flex items-baseline gap-3">
          <h1 className="mb-0 font-display text-[20px] font-medium text-fg-1">
            {t('nav.aufgaben')}
          </h1>
          <span className="text-[12px] text-fg-4">
            {t('aufgaben.offen', { count: offen.length })}
          </span>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 rounded-md border border-danger bg-danger-soft px-3 py-2 text-[13px] text-fg-1">
            {fehler}
          </p>
        )}

        {zeilen !== null && zeilen.length === 0 && !fehler && (
          <EmptyState
            icon={<ListChecks />}
            title={t('aufgaben.leer_titel')}
            description={t('aufgaben.leer_text')}
          />
        )}

        <ul className="flex list-none flex-col gap-1.5 p-0">
          {(zeilen ?? []).map((z) => {
            const farbe = konten.find((k) => k.id === z.konto_id)?.farbe
            const faellig = z.faellig ? new Date(z.faellig) : null
            const ueberfaellig = Boolean(faellig && !z.erledigt && faellig < new Date())

            return (
              <li
                key={z.id}
                draggable={!z.erledigt}
                onDragStart={() => setGezogen(z.id)}
                onDragEnd={() => {
                  setGezogen(null)
                  setUeber(null)
                }}
                onDragOver={(e) => {
                  e.preventDefault()
                  setUeber(z.id)
                }}
                onDrop={() => void ablegen(z.id)}
                className={
                  'flex items-start gap-3 rounded-lg border bg-surface-1 px-3 py-2.5 ' +
                  'transition-colors duration-[var(--dur-fast)] ' +
                  (ueber === z.id ? 'border-accent ' : 'border-line ') +
                  (z.erledigt ? 'opacity-60 ' : '')
                }
              >
                {/* ⚠️ Der Griff ist sichtbar, nicht geraten. Eine Zeile, die
                    sich ziehen lässt und das nicht zeigt, zieht niemand. */}
                <span
                  aria-hidden
                  className={
                    'mt-1 shrink-0 ' + (z.erledigt ? 'text-transparent' : 'cursor-grab text-fg-4')
                  }
                >
                  <GripVertical className="size-4" />
                </span>

                <button
                  type="button"
                  role="checkbox"
                  aria-checked={Boolean(z.erledigt)}
                  aria-label={
                    z.erledigt ? t('aufgaben.wieder_offen') : t('aufgaben.abhaken')
                  }
                  onClick={() =>
                    void mit(() =>
                      api.flicken(`/api/aufgaben/${z.id}`, { erledigt: !z.erledigt }),
                    )
                  }
                  className={
                    'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border ' +
                    'transition-colors duration-[var(--dur-fast)] ' +
                    (z.erledigt
                      ? 'border-accent bg-accent text-on-accent'
                      : 'border-line-strong hover:border-accent')
                  }
                >
                  {z.erledigt && <Check className="size-3.5" />}
                </button>

                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    {farbe && (
                      <span
                        aria-hidden
                        className={`size-2 shrink-0 rounded-full ${PUNKT_KLASSE[farbe]}`}
                      />
                    )}
                    <button
                      type="button"
                      disabled={z.nachricht_id === null}
                      onClick={() => z.nachricht_id !== null && aufMail(z.nachricht_id)}
                      className={
                        'min-w-0 flex-1 truncate text-left text-[13px] ' +
                        (z.erledigt ? 'text-fg-3 line-through ' : 'text-fg-1 ') +
                        (z.nachricht_id === null ? 'cursor-default' : 'hover:text-accent-text')
                      }
                    >
                      {z.betreff || t('liste.kein_betreff')}
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 pl-4 text-[11px] text-fg-4">
                    <span className="truncate">{z.von_name || z.von_adresse}</span>

                    {/* ⚠️ Die verwaiste Aufgabe sagt es. Sonst klickt man ins
                        Leere und hält nexmail für kaputt. */}
                    {z.verwaist && (
                      <span className="flex items-center gap-1 text-warning">
                        <MailWarning className="size-3" />
                        {t('aufgaben.mail_weg')}
                      </span>
                    )}

                    {/* ⚠️ **Ohne Datum bleibt hier nur das Kalendersymbol.**
                        Ein leeres `<input type="date">` malt „tt.mm.jjjj" hin,
                        und das stünde bei den meisten Aufgaben — die haben
                        keine Frist. Die schmale Breite schneidet den
                        Platzhalter weg; der eingebaute Kalenderknopf bleibt
                        anklickbar. Ein zweites Symbol daneben wäre eins zu
                        viel: Der Browser bringt seines mit. */}
                    <label
                      className="flex items-center"
                      title={t('aufgaben.faellig')}
                    >
                      <span className="sr-only">{t('aufgaben.faellig')}</span>
                      <input
                        type="date"
                        aria-label={t('aufgaben.faellig')}
                        value={faellig ? faellig.toISOString().slice(0, 10) : ''}
                        onChange={(e) =>
                          void mit(() =>
                            api.flicken(`/api/aufgaben/${z.id}`, {
                              faellig: e.target.value ? `${e.target.value}T00:00:00Z` : null,
                              faellig_setzen: true,
                            }),
                          )
                        }
                        className={
                          'rounded-sm border border-transparent bg-transparent py-0.5 ' +
                          'text-[11px] hover:border-line ' +
                          (faellig ? 'w-[6.5rem] px-1 ' : 'w-[1.4rem] px-0 ') +
                          (ueberfaellig ? 'text-danger' : 'text-fg-4')
                        }
                      />
                    </label>

                    {/* ⚠️ **Das Eingangsdatum der Mail steht hier nicht.**
                        Zwei unbeschriftete Daten nebeneinander liest niemand
                        richtig — man hält das eine für das andere. Hier zählt
                        die Frist; wann die Mail kam, steht in der Mail, und
                        die ist einen Klick entfernt. */}
                  </div>
                </div>

                <IconButton
                  icon={<Trash2 />}
                  label={t('aufgaben.entfernen')}
                  onClick={() => void mit(() => api.loeschen(`/api/aufgaben/${z.id}`))}
                />
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
