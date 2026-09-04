/* Die zusätzlichen Absenderadressen eines Postfachs.
 *
 * ⚠️ **Eine Zeile je Adresse, kein Komma-Textfeld.** Zu jeder Adresse gehört
 * ein eigener Name; in einer Zeichenkette müsste man beides mit einem Zeichen
 * trennen, das in keinem von beidem vorkommen darf — und genau das tippt
 * irgendwann jemand.
 *
 * ⚠️ **Leer zeigt nur einen Knopf.** Die allermeisten Postfächer haben keine
 * Zweitadresse; eine leere Zeile mit zwei Feldern stünde bei jedem im Weg und
 * sähe aus, als müsse man sie ausfüllen.
 */
import { useTranslation } from 'react-i18next'
import { Plus, X } from 'lucide-react'
import { Input } from '../ds'

export interface Absenderalias {
  adresse: string
  name: string
}

interface Props {
  werte: Absenderalias[]
  aufAendern: (werte: Absenderalias[]) => void
  /** Die Hauptadresse — sie steht als erste Zeile da, unveränderlich. */
  hauptadresse: string
}

export function Absenderfeld({ werte, aufAendern, hauptadresse }: Props) {
  const { t } = useTranslation()

  function setzen(i: number, teil: Partial<Absenderalias>) {
    aufAendern(werte.map((w, k) => (k === i ? { ...w, ...teil } : w)))
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-fg-2">{t('konto.aliase')}</span>

      {/* ⚠️ **Die Hauptadresse steht mit da, obwohl sie kein Alias ist.**
          Ohne sie sähe die Liste aus, als gäbe es nur die Zweitadressen — und
          niemand wüsste, wogegen sie „zusätzlich" sind. */}
      <div className="flex items-center gap-2 rounded-md bg-surface-3 px-2 py-1.5">
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg-2">
          {hauptadresse || t('konto.aliase_haupt_leer')}
        </span>
        <span className="shrink-0 text-[11px] text-fg-4">{t('konto.aliase_haupt')}</span>
      </div>

      {werte.map((w, i) => (
        <div key={i} className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <Input
              type="email"
              placeholder={t('konto.aliase_adresse')}
              value={w.adresse}
              onChange={(e) => setzen(i, { adresse: e.target.value })}
            />
          </div>
          <div className="min-w-0 flex-1">
            <Input
              placeholder={t('konto.aliase_name')}
              value={w.name}
              onChange={(e) => setzen(i, { name: e.target.value })}
            />
          </div>
          <button
            type="button"
            aria-label={t('konto.aliase_entfernen', { adresse: w.adresse || '' })}
            onClick={() => aufAendern(werte.filter((_, k) => k !== i))}
            className="mt-1 shrink-0 rounded-sm p-1.5 text-fg-4 hover:bg-surface-3 hover:text-fg-1"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={() => aufAendern([...werte, { adresse: '', name: '' }])}
        className="flex items-center gap-1.5 self-start rounded-sm px-1 py-0.5 text-[12px] text-accent hover:underline"
      >
        <Plus className="size-3.5" aria-hidden />
        {t('konto.aliase_hinzufuegen')}
      </button>

      <span className="text-[11px] text-fg-4">{t('konto.aliase_hinweis')}</span>
    </div>
  )
}
