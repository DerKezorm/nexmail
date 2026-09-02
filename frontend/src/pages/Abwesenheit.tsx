/* Abwesenheitsnotiz — je Postfach.
 *
 * ⚠️ **Der Warnbalken oben steht immer da, nicht erst beim Einschalten.**
 * nexmail antwortet nur, solange es läuft; wer den Rechner ausmacht, soll es
 * vorher wissen und nicht dann, wenn niemand eine Antwort bekommen hat. Der
 * Anbieter kann es meist selbst und unabhängig davon.
 *
 * ⚠️ **Reiner Text, kein Editor.** Eine Abwesenheitsnotiz ist kurz und
 * sachlich, und formatierte Post an Fremde, die niemand gegenliest, ist eine
 * Fehlerquelle ohne Gewinn. Signaturen haben den vollen Editor, das hier
 * bewusst nicht.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import { Button, Input, Switch } from '../ds'
import { PUNKT_KLASSE } from '../lib/farben'
import type { Postfachfarbe } from '../daten/typen'

interface Stand {
  konto_id: string
  adresse: string
  farbe: number
  aktiv: boolean
  von: string
  bis: string
  betreff: string
  text: string
  laeuft: boolean
}

interface Antwortzeile {
  konto_id: string
  adresse: string
  gesendet: string
}

/** Die Kennungen des Servers — übersetzt, nicht roh gezeigt. */
const GRUENDE: Record<string, string> = {
  abwesenheit_ohne_text: 'abwesenheit.fehler_ohne_text',
  abwesenheit_zeitraum_verdreht: 'abwesenheit.fehler_zeitraum',
  abwesenheit_datum_ungueltig: 'abwesenheit.fehler_datum',
}

export function Abwesenheit() {
  const { t, i18n } = useTranslation()
  const [liste, setListe] = useState<Stand[] | null>(null)
  const [antworten, setAntworten] = useState<Antwortzeile[]>([])
  const [fehler, setFehler] = useState('')
  /* Was gerade im Formular steht, je Postfach. Erst beim Speichern geht es
     zum Server — sonst schickt jeder Tastendruck eine Anfrage. */
  const [entwurf, setEntwurf] = useState<Record<string, Stand>>({})

  const laden = useCallback(async () => {
    const stand = await api.holen<Stand[]>('/api/abwesenheit')
    setListe(stand)
    setEntwurf(Object.fromEntries(stand.map((s) => [s.konto_id, s])))
    setAntworten(await api.holen<Antwortzeile[]>('/api/abwesenheit/antworten'))
  }, [])

  useEffect(() => {
    void laden().catch(() => {
      setListe([])
      setFehler(t('stoerung.stamm'))
    })
  }, [laden, t])

  const speichern = async (s: Stand) => {
    setFehler('')
    try {
      await api.aendern(`/api/abwesenheit/${s.konto_id}`, {
        aktiv: s.aktiv,
        von: s.von,
        bis: s.bis,
        betreff: s.betreff,
        text: s.text,
      })
      await laden()
    } catch (f) {
      const kennung = f instanceof ApiFehler ? f.detail : ''
      setFehler(GRUENDE[kennung] ? t(GRUENDE[kennung]) : t('anmeldung.fehler_allgemein'))
      // ⚠️ Der Stand des Servers gilt weiter — also wieder anzeigen, was dort
      // steht. Sonst sieht man eine Einstellung, die es nicht gibt.
      await laden().catch(() => {})
    }
  }

  if (liste === null) return <div className="h-24" />

  return (
    <div className="flex max-w-[720px] flex-col gap-5">
      {/* Der Satz, der die Grenze nennt. Er steht hier, nicht in einer README. */}
      <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-3">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
        <p className="mb-0 text-[12px] leading-relaxed text-fg-2">{t('abwesenheit.nur_wenn_es_laeuft')}</p>
      </div>

      {fehler && <p className="mb-0 text-[13px] text-danger">{fehler}</p>}

      {liste.length === 0 && (
        <p className="mb-0 text-[13px] text-fg-4">{t('abwesenheit.kein_postfach')}</p>
      )}

      {liste.map((s) => {
        const e = entwurf[s.konto_id] ?? s
        const geaendert =
          e.aktiv !== s.aktiv ||
          e.von !== s.von ||
          e.bis !== s.bis ||
          e.betreff !== s.betreff ||
          e.text !== s.text
        const setzen = (teil: Partial<Stand>) =>
          setEntwurf((alle) => ({ ...alle, [s.konto_id]: { ...e, ...teil } }))

        return (
          <section
            key={s.konto_id}
            className={
              'flex flex-col gap-4 rounded-lg border p-4 ' +
              (e.aktiv ? 'border-line bg-surface-1' : 'border-line-subtle bg-surface-1/60')
            }
          >
            <div className="flex flex-wrap items-center gap-3">
              <span
                aria-hidden
                className={`size-2 shrink-0 rounded-full ${PUNKT_KLASSE[(s.farbe || 1) as Postfachfarbe]}`}
              />
              <span className="font-mono text-[13px] font-medium text-fg-1">{s.adresse}</span>
              <span className="flex-1" />
              {/* ⚠️ **„Läuft" ist nicht dasselbe wie „an".** Der Zeitraum kann
                  noch nicht begonnen haben oder schon vorbei sein — und dann
                  ist der Schalter an, ohne dass etwas passiert. */}
              {s.aktiv && (
                <span
                  className={
                    'rounded-pill px-2.5 py-0.5 text-[11px] font-medium ' +
                    (s.laeuft ? 'bg-accent text-on-accent' : 'border border-line text-fg-3')
                  }
                >
                  {s.laeuft
                    ? s.bis
                      ? t('abwesenheit.laeuft_bis', { datum: s.bis })
                      : t('abwesenheit.laeuft')
                    : t('abwesenheit.ruht')}
                </span>
              )}
              <Switch
                checked={e.aktiv}
                label={t('abwesenheit.einschalten')}
                onCheckedChange={(an) => setzen({ aktiv: an })}
              />
            </div>

            {e.aktiv && (
              <>
                <div className="flex flex-wrap gap-4">
                  <div className="min-w-[150px] flex-1">
                    <Input
                      type="date"
                      label={t('abwesenheit.von')}
                      value={e.von}
                      onChange={(ev) => setzen({ von: ev.target.value })}
                    />
                  </div>
                  <div className="min-w-[150px] flex-1">
                    <Input
                      type="date"
                      label={t('abwesenheit.bis')}
                      hint={e.bis ? undefined : t('abwesenheit.bis_offen')}
                      value={e.bis}
                      onChange={(ev) => setzen({ bis: ev.target.value })}
                    />
                  </div>
                </div>

                <Input
                  label={t('abwesenheit.betreff')}
                  placeholder={t('abwesenheit.betreff_platzhalter')}
                  value={e.betreff}
                  onChange={(ev) => setzen({ betreff: ev.target.value })}
                />

                <label className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
                    {t('abwesenheit.text')}
                  </span>
                  <textarea
                    rows={5}
                    value={e.text}
                    onChange={(ev) => setzen({ text: ev.target.value })}
                    className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none"
                  />
                </label>

                <p className="mb-0 text-[12px] text-fg-4">{t('abwesenheit.schleifenschutz')}</p>
              </>
            )}

            {/* ⚠️ **Kein gesperrter Knopf, sondern keiner.** Ein grauer
                „Speichern" in jedem ausgeschalteten Block steht nur herum und
                sagt nichts — er erscheint, sobald es etwas zu speichern gibt. */}
            {geaendert && (
              <div className="flex items-center gap-3">
                <Button variant="primary" size="sm" onClick={() => void speichern(e)}>
                  {t('aktion.speichern')}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setzen(s)}>
                  {t('aktion.abbrechen')}
                </Button>
              </div>
            )}
          </section>
        )
      })}

      <section className="mt-2 flex flex-col gap-3 border-t border-line-subtle pt-5">
        <div className="flex flex-col gap-1">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">
            {t('abwesenheit.antworten_titel')}
          </h2>
          <p className="mb-0 text-[12px] text-fg-4">{t('abwesenheit.antworten_hinweis')}</p>
        </div>

        {antworten.length === 0 ? (
          <p className="mb-0 text-[12px] text-fg-4">{t('abwesenheit.antworten_leer')}</p>
        ) : (
          <ul className="flex list-none flex-col gap-1 p-0">
            {antworten.map((a) => (
              <li
                key={`${a.konto_id}-${a.adresse}`}
                className="flex items-center gap-3 rounded-md border border-line-subtle bg-surface-1 px-3 py-1.5"
              >
                <Check aria-hidden className="size-3.5 shrink-0 text-success" />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-2">
                  {a.adresse}
                </span>
                <span className="shrink-0 text-[11px] text-fg-4">
                  {new Date(a.gesendet).toLocaleString(i18n.language, {
                    dateStyle: 'short',
                    timeStyle: 'short',
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
