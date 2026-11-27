/** Ein Stück des Pfads entschlüsselt, `null` bei kaputter Prozentkodierung.
 *
 * ⚠️ **`decodeURIComponent` wirft bei `%` ohne zwei Hexziffern**, und der Browser lässt so ein `%` im Pfad stehen.
 * Wer beim Laden der App aus dem Pfad liest (`/settings/%`, ein abgeschnittener Einladungslink), brachte damit das
 * ganze Bündel zum Absturz: weiße Seite, auch die Anmeldung nicht erreichbar (Befundsuche 28.11.2026).
 *
 * Eine eigene Datei ohne Seiteneffekte (anders als `basis.ts`, das beim Laden `document` liest), damit auch die
 * Tests in der Node-Umgebung sie laden können. */
export function pfadteil(roh: string): string | null {
  try {
    return decodeURIComponent(roh)
  } catch {
    return null
  }
}
