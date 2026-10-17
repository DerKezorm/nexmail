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

/** Pfad des Wiedervorlage-Ordners auf einem Server ohne Namensraum-Präfix.
 *  ⚠️ Bei Dovecot mit `INBOX.` heißt er `INBOX.Wiedervorlage`; welcher es
 *  ist, sagt der Server (`wiedervorlage` an der Ordnerzeile). */
export const WIEDERVORLAGE_PFAD = 'Wiedervorlage'

export function istWiedervorlage(o: { pfad?: string; wiedervorlage?: boolean }): boolean {
  return o.wiedervorlage ?? o.pfad === WIEDERVORLAGE_PFAD
}

export function ordnerName(
  o: { rolle: string; name: string; pfad?: string; wiedervorlage?: boolean },
  t: (schluessel: string) => string,
): string {
  if (o.rolle === 'posteingang') return t('ordner.posteingang')
  if (istWiedervorlage(o)) return t('ordner.wiedervorlage')
  return o.name
}

/** Der Ordner, unter dem bei diesem Server die oberste Ebene liegt, oder null.
 *
 * ⚠️ **Dovecot bei Hetzner Webhosting meldet den Namensraum `INBOX.`**
 * (Issue #12): Jeder eigene Ordner heißt dort `INBOX.Name`, auch „Gesendet"
 * und „Papierkorb". Nach dem Pfad allein wären sie alle Unterordner des
 * Posteingangs. Thunderbird zeigt sie oben, und so auch nexmail: Was direkt
 * unter dieser Wurzel liegt, gehört auf die oberste Ebene, und unter die
 * Wurzel selbst lässt sich kein eigener Ordner legen.
 */
export function namensraumWurzel(namensraum: string | undefined): string | null {
  if (!namensraum || namensraum.length < 2) return null
  return namensraum.slice(0, -1)
}

/** Der nächstliegende Vorfahre in `liste`, der wirklich existiert.
 *
 * Ein Ordner ist Kind eines anderen, wenn sein Pfad mit dessen Pfad plus
 * **einem** Trennzeichen beginnt. Der Trenner wird nicht geraten (`/` bei
 * Gmail, `.` bei All-Inkl), sondern aus den Pfaden abgelesen. Die Wurzel des
 * Namensraums ist nie Vorfahre, siehe `namensraumWurzel`.
 */
export function elternVon<O extends { pfad: string; namensraum?: string }>(
  o: O,
  liste: readonly O[],
): O | undefined {
  const wurzel = namensraumWurzel(o.namensraum)
  let laengster: O | undefined
  for (const anderer of liste) {
    if (anderer.pfad === o.pfad) continue
    if (anderer.pfad === wurzel) continue
    if (!o.pfad.startsWith(anderer.pfad)) continue
    const rest = o.pfad.slice(anderer.pfad.length)
    // Genau ein Trennzeichen, dann der eigene Name - sonst ist es nur ein
    // zufällig gleicher Wortanfang („Archiv" und „Archivalien").
    if (rest.length < 2) continue
    const trenner = rest[0]
    if (/[a-z0-9äöüß]/i.test(trenner)) continue
    if (!laengster || anderer.pfad.length > laengster.pfad.length) laengster = anderer
  }
  return laengster
}
