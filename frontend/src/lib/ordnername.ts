/* Wie ein Ordner in der Oberfläche heißt.
 *
 * ⚠️ **Nur zwei Ordner bekommen einen übersetzten Namen**, alle anderen
 * tragen den, den der Betreiber auf seinem Server sieht. Wer dort „Spam"
 * angelegt hat, soll nicht „Junk" lesen.
 *
 * - Der Posteingang: Er heißt `INBOX`, weil der IMAP-Server ihn so nennt, und
 *   kein Mensch nennt ihn so. Outlook zeigt „Posteingang".
 * - Die Wiedervorlage: Den Ordner legt nexmail selbst an, mit einem festen
 *   Namen (services/wiedervorlage.ORDNER_NAME), damit jedes Gerät denselben
 *   sieht. Bis 0.22.2 stand er auch in der englischen Oberfläche deutsch da,
 *   neben dem Menüpunkt „Snooze". Umbenannt wird auf dem Server nichts: Die
 *   Ordner bestehender Postfächer bleiben, wie sie sind.
 */

/** Pfad des Wiedervorlage-Ordners, oberste Ebene, auf jedem Server gleich. */
export const WIEDERVORLAGE_PFAD = 'Wiedervorlage'

export function ordnerName(
  o: { rolle: string; name: string; pfad?: string },
  t: (schluessel: string) => string,
): string {
  if (o.rolle === 'posteingang') return t('ordner.posteingang')
  if (o.pfad === WIEDERVORLAGE_PFAD) return t('ordner.wiedervorlage')
  return o.name
}
