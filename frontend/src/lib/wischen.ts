/* Wisch-Aktionen der schmalen Ansicht.
 *
 * Was ein Wisch nach links oder rechts tut, stellt jeder unter
 * Einstellungen -> Darstellung selbst ein. Die Vorgabe folgt den Tasten:
 * links = Loeschen (wie Entf), rechts = Archivieren (wie E).
 *
 * ⚠️ **Nur fuer den Finger, nie fuer die Maus.** Mit der Maus zieht man
 * Zeilen in den Ordnerbaum (HTML-Drag); dieselbe Geste zusaetzlich als
 * Wisch zu deuten hiesse, dass ein angefangenes Verschieben eine Mail
 * loescht. Die Zeile prueft deshalb `pointerType === 'touch'`.
 */

export type WischAktion = 'aus' | 'archivieren' | 'loeschen' | 'gelesen'

export const WISCH_LINKS_VORGABE: WischAktion = 'loeschen'
export const WISCH_RECHTS_VORGABE: WischAktion = 'archivieren'

/** Ab hier wird beim Loslassen ausgefuehrt, darunter schnappt die Zeile
 *  zurueck. 80 px — und auf sehr schmalen Zeilen hoechstens 40 % der Breite,
 *  sonst laege die Schwelle hinter der Mitte und wirkte wie kaputt. */
export function wischSchwelle(zeilenBreite: number): number {
  return Math.min(80, zeilenBreite * 0.4)
}
