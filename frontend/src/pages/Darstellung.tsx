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
import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { Select, Switch } from '../ds'
import { useGemerkt } from '../lib/haken'

export type Dichte = 'kompakt' | 'normal'

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
    </div>
  )
}
