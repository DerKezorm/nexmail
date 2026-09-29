/* Der Fehlersatz einer Zeile in der Liste „Was hinausging".
 *
 * ⚠️ **Die Werte kommen mit der Zeile, und nicht jede Zeile hat sie.** Bis
 * 29.09.2026 speicherte der Server nur die Kennung; die Liste zeigte dann
 * wörtlich „Der Dienst hat mit {{code}} geantwortet." Ältere Zeilen bleiben
 * bis zu vierzehn Tage stehen. Fehlt ein Wert, den der Satz braucht, steht
 * ein Satz ohne Einzelheiten da, nie ein Platzhalter.
 *
 * Ohne Browser, damit die schnelle Prüfebene es laden kann.
 */
import type { i18n as I18n } from 'i18next'

const PLATZHALTER = /\{\{\s*([\w.]+)\s*\}\}/g

export function vorgangFehler(i18n: I18n, fehler: string, werte: Record<string, unknown> = {}): string {
  const schluessel = `serverfehler.${fehler}`
  if (!i18n.exists(schluessel)) return i18n.t('ki.fehlgeschlagen')
  const vorlage = i18n.t(schluessel, { skipInterpolation: true })
  const fehlt = [...vorlage.matchAll(PLATZHALTER)].some(([, name]) => werte[name] === undefined)
  return fehlt ? i18n.t('ki.fehlgeschlagen') : i18n.t(schluessel, werte)
}
