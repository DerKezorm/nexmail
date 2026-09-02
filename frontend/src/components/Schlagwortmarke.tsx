/* Die Farbmarke eines Schlagworts.
 *
 * ⚠️ **Ein Rechteck, kein Punkt.** Der runde Punkt gehört dem **Postfach** —
 * in der Ordnerspalte, am linken Rand der Zeile, in den Aufgaben. Zwei
 * gleiche Formen in derselben Zeile für zwei verschiedene Dinge heißt: Man
 * liest die falsche Auskunft und traut danach keiner von beiden mehr. Outlook
 * hält es genauso, dort sind Kategorien farbige Kästchen.
 *
 * Am 02.09.2026 gemeldet: „Der Kreis für die Schlagworte ist doof. Mach
 * daraus Rechtecke. Sonst verwechselt man es mit den Kreis, die für ein
 * Postfach stehen."
 *
 * ⚠️ **Farbe allein ist keine Auskunft.** Wo die Marke für sich steht (in der
 * Nachrichtenliste), trägt sie den Namen als `title` **und** `aria-label` —
 * sonst ist sie für Vorleseprogramme und für Farbfehlsichtige ein Nichts. Wo
 * der Name direkt daneben steht, ist sie schmückend und wird ausgeblendet.
 */
import type { Postfachfarbe } from '../daten/typen'
import { PUNKT_KLASSE } from '../lib/farben'

interface Props {
  farbe: Postfachfarbe
  /** Der Name des Schlagworts. Fehlt er, gilt die Marke als schmückend. */
  name?: string
  /** Für Listen und Paletten, in denen mehr Platz ist. */
  gross?: boolean
  className?: string
}

export function Schlagwortmarke({ farbe, name, gross = false, className = '' }: Props) {
  const masse = gross ? 'h-3 w-4.5' : 'h-2.5 w-4'
  const gemeinsam = `${masse} shrink-0 rounded-[3px] ${PUNKT_KLASSE[farbe]} ${className}`

  if (!name) {
    return <span aria-hidden className={gemeinsam} />
  }
  return <span role="img" aria-label={name} title={name} className={gemeinsam} />
}
