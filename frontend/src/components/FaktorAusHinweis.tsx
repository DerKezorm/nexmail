/* Der Nothammer ist unten (konten 0.3.3, `NOTICES`: `account.secondFactorOff`): Niemand wird nach einem zweiten
 * Faktor gefragt. Deutlich, damit ihn niemand vergisst zurückzustellen. Gleiche Optik wie der Hinweis im
 * Konfliktfenster. */
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/** nexmail kennt zwei Namen für dieselbe Variable: den alten und den des Moduls. */
const VARIABLEN = 'NEXMAIL_ZWEI_FAKTOR_AUS / NEXMAIL_SECOND_FACTOR_OFF'

export function FaktorAusHinweis() {
  const { t } = useTranslation()
  return (
    <div
      role="alert"
      data-testid="zweiter-faktor-aus"
      className="flex max-w-[720px] items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft p-3"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <div className="flex flex-col gap-1">
        <p className="mb-0 text-[13px] font-semibold text-warning-text">{t('account.secondFactorOff')}</p>
        <p className="mb-0 text-[13px] text-warning-text">
          {t('account.secondFactorOffHint', { secondFactorOffEnv: VARIABLEN })}
        </p>
      </div>
    </div>
  )
}
