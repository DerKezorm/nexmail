/* Darstellung — was jeder für sich einstellt.
 *
 * ⚠️ **Diese Einstellungen liegen im Browser, nicht im Server.** Sie gehören
 * zum Gerät: Am großen Bildschirm will man eine andere Dichte als am Telefon.
 * Das steht auch in der Oberfläche — eine Einstellung, die man am zweiten
 * Gerät nicht wiederfindet und die das nicht sagt, wirkt kaputt.
 *
 * ⚠️ **Die Zeitzone steht hier bewusst nicht.** Sie gilt für alle Benutzer und
 * liegt im Server; ihr Platz ist die Verwaltung. Zweimal dieselbe Einstellung
 * an zwei Orten heißt: Niemand weiß, welche gewinnt.
 *
 * Hell/Dunkel und Sprache stehen ebenfalls nicht hier, sondern oben rechts in
 * der Leiste: Man ändert sie beiläufig und will dafür keine Seite aufsuchen.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { Button, Select, Switch } from '../ds'
import { api, ApiFehler } from '../api/client'
import { useGemerkt } from '../lib/haken'
import { WISCH_LINKS_VORGABE, WISCH_RECHTS_VORGABE } from '../lib/wischen'
import type { WischAktion } from '../lib/wischen'

export type Dichte = 'kompakt' | 'normal'

/* Aufbewahrung in Tagen für Papierkorb und Junk. 0 heißt: nie von selbst
   leeren. ⚠️ Genau die Stufen, die der Server erlaubt (Positivliste in
   services/aufraeumen.py) — eine hier erfundene Stufe käme als 400 zurück. */
interface Aufraeumen {
  papierkorb_tage: number
  junk_tage: number
}

const AUFRAEUMEN_STUFEN = [0, 7, 14, 30, 90] as const

/* Die vier Moeglichkeiten je Wischrichtung. Die Reihenfolge ist die der
   Vorgaben: aus, dann die beiden Aufraeum-Wege, dann der Umschalter. */
const WISCH_AKTIONEN: WischAktion[] = ['aus', 'archivieren', 'loeschen', 'gelesen']

export function Darstellung() {
  const { t } = useTranslation()
  const [dichte, setDichte] = useGemerkt<Dichte>('nexmail.dichte', 'normal')
  const [anreisser, setAnreisser] = useGemerkt<boolean>('nexmail.anreisser', true)
  const [punkte, setPunkte] = useGemerkt<boolean>('nexmail.punkte', true)
  /* Wann eine offene Nachricht als gelesen gilt — in Sekunden.
     `0` heißt sofort, `-1` heißt: nur von Hand.
     ⚠️ **Outlooks Auswahl, nicht eine eigene.** „Wer Outlook bedienen kann,
     soll sich hier zu Hause fühlen" — und diese Einstellung ist genau die,
     die dort jeder kennt, der sie je gesucht hat. */
  const [gelesenNach, setGelesenNach] = useGemerkt<number>('nexmail.gelesen_nach', 2)
  /* „Senden rückholen" — wie viele Sekunden eine gesendete Nachricht noch
     zurückzuholen ist. Der Wert wird beim Senden als Aufschub mitgeschickt
     (`senden_ab = jetzt + Aufschub`); der Server hält sie so lange im Ausgang.
     ⚠️ **Vorgabe aus.** Wer nichts einstellt, merkt keinen Unterschied — jede
     Mail geht wie bisher sofort hinaus. */
  const [rueckholen, setRueckholen] = useGemerkt<number>('nexmail.rueckholen', 0)
  /* Wisch-Aktionen der schmalen Ansicht. ⚠️ Dieselben Schluessel liest `App`
     — wer hier umstellt, wischt ab dem naechsten Zug anders, ohne F5. */
  const [wischLinks, setWischLinks] = useGemerkt<WischAktion>(
    'nexmail.wisch_links',
    WISCH_LINKS_VORGABE,
  )
  const [wischRechts, setWischRechts] = useGemerkt<WischAktion>(
    'nexmail.wisch_rechts',
    WISCH_RECHTS_VORGABE,
  )

  /* ⚠️ Anders als der Rest der Seite liegt das Aufräumen im Server, je
     Benutzer — es löscht endgültig und darf nicht je Gerät verschieden sein.
     Drei Zustände statt zwei: noch nicht geladen · geladen · ging nicht.
     Ein Fehler darf nicht wie „aus" aussehen — wer „90 Tage" eingestellt hat
     und ein stilles „Nie" sieht, traut der Einstellung nie wieder. */
  const [aufraeumen, setAufraeumen] = useState<Aufraeumen | null>(null)
  const [aufraeumenFehler, setAufraeumenFehler] = useState('')

  const aufraeumenLaden = useCallback(() => {
    setAufraeumenFehler('')
    api
      .holen<Aufraeumen>('/api/einstellungen/aufraeumen')
      .then(setAufraeumen)
      .catch(() => setAufraeumenFehler(t('anmeldung.fehler_allgemein')))
  }, [t])

  useEffect(aufraeumenLaden, [aufraeumenLaden])

  const aufraeumenStellen = (feld: keyof Aufraeumen, wert: number) => {
    if (!aufraeumen) return
    const neu = { ...aufraeumen, [feld]: wert }
    setAufraeumen(neu)
    api.aendern<Aufraeumen>('/api/einstellungen/aufraeumen', neu).catch((f) => {
      // Der alte Stand gilt weiter — also wieder anzeigen, was der Server hat.
      setAufraeumenFehler(
        f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'),
      )
      api.holen<Aufraeumen>('/api/einstellungen/aufraeumen').then(setAufraeumen).catch(() => {})
    })
  }

  const stufenText = (n: number) =>
    n === 0 ? t('darstellung.aufraeumen_aus') : t('darstellung.aufraeumen_tage', { n })

  return (
    <div className="flex max-w-[560px] flex-col gap-5">
      <p className="mb-0 flex items-start gap-2 text-[12px] text-fg-4">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        {t('darstellung.nur_dieses_geraet')}
      </p>

      <Select
        label={t('darstellung.dichte')}
        hint={t('darstellung.dichte_hinweis')}
        value={dichte}
        onChange={(e) => setDichte(e.target.value as Dichte)}
      >
        <option value="normal">{t('darstellung.dichte_normal')}</option>
        <option value="kompakt">{t('darstellung.dichte_kompakt')}</option>
      </Select>

      <Select
        label={t('darstellung.gelesen')}
        hint={t('darstellung.gelesen_hinweis')}
        value={String(gelesenNach)}
        onChange={(e) => setGelesenNach(Number(e.target.value))}
      >
        <option value="0">{t('darstellung.gelesen_sofort')}</option>
        <option value="2">{t('darstellung.gelesen_sekunden', { n: 2 })}</option>
        <option value="5">{t('darstellung.gelesen_sekunden', { n: 5 })}</option>
        <option value="10">{t('darstellung.gelesen_sekunden', { n: 10 })}</option>
        <option value="-1">{t('darstellung.gelesen_hand')}</option>
      </Select>

      <Select
        label={t('darstellung.rueckholen')}
        hint={t('darstellung.rueckholen_hinweis')}
        value={String(rueckholen)}
        onChange={(e) => setRueckholen(Number(e.target.value))}
      >
        <option value="0">{t('darstellung.rueckholen_aus')}</option>
        <option value="5">{t('darstellung.rueckholen_sekunden', { n: 5 })}</option>
        <option value="10">{t('darstellung.rueckholen_sekunden', { n: 10 })}</option>
        <option value="30">{t('darstellung.rueckholen_sekunden', { n: 30 })}</option>
      </Select>

      <Select
        label={t('darstellung.wisch_links')}
        hint={t('darstellung.wisch_hinweis')}
        value={wischLinks}
        onChange={(e) => setWischLinks(e.target.value as WischAktion)}
      >
        {WISCH_AKTIONEN.map((a) => (
          <option key={a} value={a}>
            {t(`darstellung.wisch_${a}`)}
          </option>
        ))}
      </Select>

      <Select
        label={t('darstellung.wisch_rechts')}
        value={wischRechts}
        onChange={(e) => setWischRechts(e.target.value as WischAktion)}
      >
        {WISCH_AKTIONEN.map((a) => (
          <option key={a} value={a}>
            {t(`darstellung.wisch_${a}`)}
          </option>
        ))}
      </Select>

      <Switch
        checked={anreisser}
        label={t('darstellung.anreisser')}
        description={t('darstellung.anreisser_hinweis')}
        onCheckedChange={setAnreisser}
      />

      <Switch
        checked={punkte}
        label={t('darstellung.punkte')}
        description={t('darstellung.punkte_hinweis')}
        onCheckedChange={setPunkte}
      />

      <section className="mt-2 flex flex-col gap-4 border-t border-line-subtle pt-5">
        <div className="flex flex-col gap-1">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">
            {t('darstellung.aufraeumen_titel')}
          </h2>
          {/* Der eine Satz, der die Folge nennt: endgültig, auch auf dem Server. */}
          <p className="mb-0 text-[12px] text-fg-4">{t('darstellung.aufraeumen_hinweis')}</p>
        </div>

        {aufraeumenFehler && (
          <div className="flex items-center gap-3">
            <p className="mb-0 text-[13px] text-danger">{aufraeumenFehler}</p>
            <Button variant="ghost" size="sm" onClick={aufraeumenLaden}>
              {t('stoerung.nochmal')}
            </Button>
          </div>
        )}

        {aufraeumen && (
          <>
            <Select
              label={t('darstellung.aufraeumen_papierkorb')}
              value={String(aufraeumen.papierkorb_tage)}
              onChange={(e) => aufraeumenStellen('papierkorb_tage', Number(e.target.value))}
            >
              {AUFRAEUMEN_STUFEN.map((n) => (
                <option key={n} value={String(n)}>
                  {stufenText(n)}
                </option>
              ))}
            </Select>

            <Select
              label={t('darstellung.aufraeumen_junk')}
              value={String(aufraeumen.junk_tage)}
              onChange={(e) => aufraeumenStellen('junk_tage', Number(e.target.value))}
            >
              {AUFRAEUMEN_STUFEN.map((n) => (
                <option key={n} value={String(n)}>
                  {stufenText(n)}
                </option>
              ))}
            </Select>
          </>
        )}
      </section>
    </div>
  )
}
