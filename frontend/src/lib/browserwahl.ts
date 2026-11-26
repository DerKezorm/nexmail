/* Hell oder dunkel, wie dieser Browser es vor konten 1.1.0 gespeichert hat (`nexmail.modus`), roh, oder leer.
 *
 * ⚠️ **Nur ein wirklich gespeicherter Wert** (E45): nie die Vorgabe der Seite („dunkel“) und nie, was der Browser
 * bevorzugt (`prefers-color-scheme`). Sonst bekäme ein Konto ohne eigene Wahl einen Wert, den niemand gewählt hat; der
 * Server nimmt dann `theme_default_before` (bei nexmail „dunkel“, wie es bisher aussah). */
export const BROWSERWAHL_SCHLUESSEL = 'nexmail.modus'

export function gespeicherteBrowserwahl(speicher: Pick<Storage, 'getItem'> | undefined = globalThis.localStorage): string {
  try {
    return speicher?.getItem(BROWSERWAHL_SCHLUESSEL) ?? ''
  } catch {
    return ''
  }
}
