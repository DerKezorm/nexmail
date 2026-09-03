/* Die Wiederholung eines Termins — zusammensetzen statt auswählen.
 *
 * ⚠️ **Der Rechner konnte immer mehr als die Maske.** `wiederholung.py`
 * beherrscht die ganze `RRULE`; anlegen ließen sich vier feste Muster und kein
 * Ende. „Jeden zweiten Dienstag", „letzter Freitag im Monat", „zehnmal", „bis
 * zum 31.12." gab es damit nur, wenn sie aus einem anderen Programm kamen.
 *
 * ⚠️ **Eine fremde Regel wird NICHT zerlegt angeboten.** Steht in ihr etwas,
 * das diese Maske nicht abbildet (`BYMONTHDAY`, `BYSETPOS`, `FREQ=HOURLY`),
 * meldet der Server `wiederholungFremd`. Dann bleibt sie als Ganzes stehen —
 * sie hier in Bausteine zu zerlegen hieße, sie beim Speichern zu zerstören.
 *
 * ⚠️ **Zusammengesetzt wird hier, entschieden im Server.** Die beiden Regeln,
 * an denen man sich schneidet — `UNTIL` steht in UTC und muss den letzten Tag
 * einschließen, `COUNT` und `UNTIL` schließen sich aus —, zieht
 * `regel_normieren` gerade. Eine Regel, die nur diese Maske kennt, gälte für
 * keinen anderen Client.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Input, Select } from '../ds'

/** Die Wochentage in der Reihenfolge, die RFC 5545 vorgibt. */
const TAGE = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const

/** Der Wievielte bei „am dritten Dienstag". -1 ist der letzte. */
const ORDINALE = [1, 2, 3, 4, -1]

export interface Wiederholung {
  freq: string
  intervall: number
  tage: string[]
  monatsart: string
  ordinal: number
  endeArt: string
  anzahl: number
  bis: string
}

export const LEERE_WIEDERHOLUNG: Wiederholung = {
  freq: '',
  intervall: 1,
  tage: [],
  monatsart: 'tag',
  ordinal: 1,
  endeArt: 'nie',
  anzahl: 10,
  bis: '',
}

/** Aus den Bausteinen eine `RRULE`. Leer, wenn es keine Wiederholung gibt. */
export function alsRrule(w: Wiederholung): string {
  if (!w.freq) return ''
  const freq = { taeglich: 'DAILY', woechentlich: 'WEEKLY', monatlich: 'MONTHLY', jaehrlich: 'YEARLY' }[
    w.freq
  ]
  if (!freq) return ''
  const teile = [`FREQ=${freq}`]
  if (w.intervall > 1) teile.push(`INTERVAL=${w.intervall}`)
  if (w.freq === 'woechentlich' && w.tage.length) {
    // In der Reihenfolge des Formats, nicht in der des Anklickens.
    teile.push(`BYDAY=${TAGE.filter((t) => w.tage.includes(t)).join(',')}`)
  }
  if (w.freq === 'monatlich' && w.monatsart === 'wochentag') {
    teile.push(`BYDAY=${w.ordinal}${w.tage[0] ?? 'MO'}`)
  }
  // ⚠️ Nur eines von beiden — der Server wirft das zweite ohnehin weg, aber
  // eine Regel, die schon hier stimmt, ist eine Fehlerquelle weniger.
  if (w.endeArt === 'anzahl' && w.anzahl > 0) teile.push(`COUNT=${w.anzahl}`)
  else if (w.endeArt === 'datum' && w.bis) teile.push(`UNTIL=${w.bis.replaceAll('-', '')}`)
  return teile.join(';')
}

/** Der Wievielte dieses Wochentags im Monat — 1..4, oder -1 für den letzten. */
export function derWievielte(d: Date): number {
  const nr = Math.floor((d.getDate() - 1) / 7) + 1
  // Ist es der letzte seiner Art im Monat? Dann heißt er so, nicht „der 5."
  const naechster = new Date(d)
  naechster.setDate(d.getDate() + 7)
  if (naechster.getMonth() !== d.getMonth()) return -1
  return nr
}

/** Die fertigen Muster für einen Termin, der an diesem Tag beginnt.
 *
 * ⚠️ **Vier Felder für „jeden Montag" sind drei zu viel.** Wer eine
 * Wiederholung anlegt, will fast immer eines dieser Muster; die Bausteine
 * darunter sind für den Rest da. So macht es Thunderbird, und aus demselben
 * Grund: Der Normalfall soll ein Klick sein.
 */
export function vorschlaege(beginn: Date): Wiederholung[] {
  const tag = TAGE[(beginn.getDay() + 6) % 7]
  const wievielte = derWievielte(beginn)
  return [
    { ...LEERE_WIEDERHOLUNG, freq: 'taeglich' },
    { ...LEERE_WIEDERHOLUNG, freq: 'woechentlich', tage: [tag] },
    { ...LEERE_WIEDERHOLUNG, freq: 'woechentlich', intervall: 2, tage: [tag] },
    // ⚠️ Werktags ist ``FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR`` — nicht ``DAILY``.
    { ...LEERE_WIEDERHOLUNG, freq: 'woechentlich', tage: ['MO', 'TU', 'WE', 'TH', 'FR'] },
    { ...LEERE_WIEDERHOLUNG, freq: 'monatlich' },
    { ...LEERE_WIEDERHOLUNG, freq: 'monatlich', monatsart: 'wochentag', ordinal: wievielte, tage: [tag] },
    { ...LEERE_WIEDERHOLUNG, freq: 'jaehrlich' },
  ]
}

/** Ein Muster als Satz — „Monatlich am dritten Mittwoch".
 *
 * ⚠️ **Die Wochentags- und Monatsnamen kommen vom Browser.** In unsere
 * Dateien gehörten sie nicht: `Intl` kennt sie in jeder Sprache, und in der
 * dritten Sprache fehlten sie sonst wieder.
 */
export function musterSatz(
  w: Wiederholung,
  beginn: Date,
  t: (k: string, o?: Record<string, unknown>) => string,
  sprache: string,
): string {
  const wochentag = (tag: string) => {
    const nr = TAGE.indexOf(tag as (typeof TAGE)[number])
    return new Date(2026, 0, 5 + nr).toLocaleDateString(sprache, { weekday: 'long' })
  }

  if (w.freq === 'taeglich') return t('kalender.wdh_w_taeglich')
  if (w.freq === 'jaehrlich') {
    return t('kalender.wdh_satz_jaehrlich', {
      tag: beginn.toLocaleDateString(sprache, { day: 'numeric', month: 'long' }),
    })
  }
  if (w.freq === 'monatlich') {
    if (w.monatsart === 'wochentag') {
      return t('kalender.wdh_satz_monatlich_wochentag', {
        wievielte:
          w.ordinal === -1 ? t('kalender.wdh_letzten') : t('kalender.wdh_nten', { n: w.ordinal }),
        tag: wochentag(w.tage[0] ?? 'MO'),
      })
    }
    return t('kalender.wdh_satz_monatlich_tag', { tag: beginn.getDate() })
  }
  // Wöchentlich — mit einem Tag, mit mehreren, oder alle zwei Wochen.
  if (w.tage.length === 5 && ['MO', 'TU', 'WE', 'TH', 'FR'].every((x) => w.tage.includes(x))) {
    return t('kalender.wdh_satz_werktags')
  }
  const namen = TAGE.filter((x) => w.tage.includes(x)).map(wochentag).join(', ')
  if (w.intervall > 1) return t('kalender.wdh_satz_zweiwoechig', { tag: namen })
  return t('kalender.wdh_satz_woechentlich', { tag: namen })
}

interface Props {
  wert: Wiederholung
  aufAendern: (neu: Wiederholung) => void
  gesperrt?: boolean
  /** Der Beginn des Termins — die Muster leiten sich daraus ab. */
  beginn?: Date
}

export function Wiederholungsfeld({ wert, aufAendern, gesperrt = false, beginn }: Props) {
  const { t, i18n } = useTranslation()
  /* ⚠️ **„Eigen" ist ein Zustand der Maske, kein Wert der Regel.** Wer die
     Bausteine aufgeklappt hat, soll sie nicht verlieren, bloß weil seine
     Einstellung zufällig einem der Muster gleicht. */
  const [eigen, setEigen] = useState(false)

  function setzen(teil: Partial<Wiederholung>) {
    aufAendern({ ...wert, ...teil })
  }

  /** Wochentagsnamen kommen vom Browser — nicht aus unseren Dateien. */
  const kurz = (tag: string) => {
    const nr = TAGE.indexOf(tag as (typeof TAGE)[number])
    // 2026-01-05 war ein Montag.
    return new Date(2026, 0, 5 + nr).toLocaleDateString(i18n.language, { weekday: 'short' })
  }

  const tag = beginn ?? new Date()
  const muster = vorschlaege(tag)
  const jetzige = alsRrule(wert)
  const treffer = muster.findIndex((m) => alsRrule(m) === jetzige)
  // Was in der Liste steht: ein Muster, „Keine" — oder „Eigene …".
  const auswahl = eigen || (jetzige && treffer < 0) ? 'eigen' : jetzige ? String(treffer) : ''

  return (
    <div className="flex flex-col gap-3">
      <Select
        label={t('kalender.wiederholung')}
        value={auswahl}
        disabled={gesperrt}
        onChange={(e) => {
          const gewaehlt = e.target.value
          if (gewaehlt === 'eigen') {
            setEigen(true)
            // Mit dem an, was gerade gilt — oder wöchentlich als Anfang.
            if (!wert.freq) setzen({ freq: 'woechentlich', tage: [TAGE[(tag.getDay() + 6) % 7]] })
            return
          }
          setEigen(false)
          aufAendern(gewaehlt === '' ? LEERE_WIEDERHOLUNG : muster[Number(gewaehlt)])
        }}
      >
        <option value="">{t('kalender.wdh_keine')}</option>
        {muster.map((m, i) => (
          <option key={i} value={i}>
            {musterSatz(m, tag, t, i18n.language)}
          </option>
        ))}
        <option value="eigen">{t('kalender.wdh_eigen')}</option>
      </Select>

      {auswahl === 'eigen' && wert.freq && (
        <Select
          label={t('kalender.wdh_haeufigkeit')}
          value={wert.freq}
          disabled={gesperrt}
          onChange={(e) => setzen({ freq: e.target.value })}
        >
          <option value="taeglich">{t('kalender.wdh_w_taeglich')}</option>
          <option value="woechentlich">{t('kalender.wdh_w_woechentlich')}</option>
          <option value="monatlich">{t('kalender.wdh_w_monatlich')}</option>
          <option value="jaehrlich">{t('kalender.wdh_w_jaehrlich')}</option>
        </Select>
      )}

      {auswahl === 'eigen' && wert.freq && (
        <>
          <Input
            label={t(`kalender.wdh_alle_${wert.freq}`)}
            type="number"
            min={1}
            max={999}
            value={String(wert.intervall)}
            disabled={gesperrt}
            onChange={(e) => setzen({ intervall: Math.max(1, Number(e.target.value) || 1) })}
          />

          {wert.freq === 'woechentlich' && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] font-medium text-fg-3">{t('kalender.wdh_an_tagen')}</span>
              <div className="flex flex-wrap gap-1.5">
                {TAGE.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    disabled={gesperrt}
                    aria-pressed={wert.tage.includes(tag)}
                    onClick={() =>
                      setzen({
                        tage: wert.tage.includes(tag)
                          ? wert.tage.filter((x) => x !== tag)
                          : [...wert.tage, tag],
                      })
                    }
                    className={
                      'min-w-11 rounded-md border px-2 py-1 text-[12px] transition-colors duration-[var(--dur-fast)] disabled:opacity-60 ' +
                      (wert.tage.includes(tag)
                        ? 'border-accent bg-accent-soft text-accent-text'
                        : 'border-line text-fg-3 hover:text-fg-1')
                    }
                  >
                    {kurz(tag)}
                  </button>
                ))}
              </div>
              {/* ⚠️ Kein Tag heißt nicht „nie", sondern „am Wochentag des
                  Beginns" — das sagt die Maske, statt es geschehen zu lassen. */}
              {wert.tage.length === 0 && (
                <span className="text-[11px] text-fg-4">{t('kalender.wdh_kein_tag')}</span>
              )}
            </div>
          )}

          {wert.freq === 'monatlich' && (
            <div className="flex flex-col gap-1.5">
              <Select
                label={t('kalender.wdh_monatsart')}
                value={wert.monatsart}
                disabled={gesperrt}
                onChange={(e) => setzen({ monatsart: e.target.value })}
              >
                <option value="tag">
                  {t('kalender.wdh_am_tag', { tag: beginn ? beginn.getDate() : 1 })}
                </option>
                <option value="wochentag">{t('kalender.wdh_am_wochentag')}</option>
              </Select>

              {wert.monatsart === 'wochentag' && (
                <div className="flex gap-2">
                  <Select
                    label={t('kalender.wdh_der_wievielte')}
                    value={String(wert.ordinal)}
                    disabled={gesperrt}
                    onChange={(e) => setzen({ ordinal: Number(e.target.value) })}
                  >
                    {ORDINALE.map((n) => (
                      <option key={n} value={n}>
                        {n === -1 ? t('kalender.wdh_letzter') : t('kalender.wdh_nter', { n })}
                      </option>
                    ))}
                  </Select>
                  <Select
                    label={t('kalender.wdh_wochentag')}
                    value={wert.tage[0] ?? 'MO'}
                    disabled={gesperrt}
                    onChange={(e) => setzen({ tage: [e.target.value] })}
                  >
                    {TAGE.map((tag) => (
                      <option key={tag} value={tag}>
                        {kurz(tag)}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Select
              label={t('kalender.wdh_ende')}
              value={wert.endeArt}
              disabled={gesperrt}
              onChange={(e) => setzen({ endeArt: e.target.value })}
            >
              <option value="nie">{t('kalender.wdh_ende_nie')}</option>
              <option value="anzahl">{t('kalender.wdh_ende_anzahl')}</option>
              <option value="datum">{t('kalender.wdh_ende_datum')}</option>
            </Select>

            {wert.endeArt === 'anzahl' && (
              <Input
                label={t('kalender.wdh_wie_oft')}
                type="number"
                min={1}
                max={999}
                value={String(wert.anzahl)}
                disabled={gesperrt}
                onChange={(e) => setzen({ anzahl: Math.max(1, Number(e.target.value) || 1) })}
              />
            )}
            {wert.endeArt === 'datum' && (
              <Input
                label={t('kalender.wdh_bis')}
                type="date"
                value={wert.bis}
                disabled={gesperrt}
                onChange={(e) => setzen({ bis: e.target.value })}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}