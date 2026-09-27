/* Die Adresse des Bildes vor einem Absender (Diskussion #4).
 *
 * Ohne Browser, damit die schnelle Prüfebene sie laden kann.
 */

/** `logo` heißt: Diese Zeile darf nach dem Markenlogo fragen. Das setzt
 *  `App` nur, wenn der Schalter an ist **und** die Mail die Absenderprüfung
 *  bestanden hat; ohne das fragt die Zeile nur nach dem Kontaktfoto. Wer den
 *  Schalter umlegt, bekommt damit eine neue Adresse und frische Antworten
 *  statt der gemerkten. Die Mailadresse steht kodiert; ein `+` oder `&` darin
 *  bräche sonst die Abfrage. */
export function absenderbildQuelle(adresse: string, logo: boolean, basis: (p: string) => string): string {
  if (!adresse) return ''
  return basis(`/api/absenderbild?adresse=${encodeURIComponent(adresse)}${logo ? '&logo=1' : ''}`)
}
