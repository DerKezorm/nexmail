/* Was man mit einer Nachricht tun kann.
 *
 * Bewusst reine Funktionen ueber einer Liste: keine React-Zustaende, keine
 * Seiteneffekte. In Stufe 3 wird aus jeder dieser Funktionen ein Aufruf an
 * den Server, und der Rest der Oberflaeche merkt davon nichts - sie ruft
 * weiter dieselben Namen mit denselben Werten auf.
 *
 * Sie sind ausserdem die Stelle, an der spaeter die Tests ansetzen: eine
 * Liste rein, eine Liste raus, kein Browser noetig.
 */
import type { Nachricht, Ordner, OrdnerRolle } from '../daten/typen'

/** Beschreibt, was rueckgaengig gemacht werden kann. */
export interface Rueckweg {
  /** Kurzer Satz fuer den Streifen unten. */
  text: string
  /** Der Zustand, der wiederhergestellt wird. */
  vorher: Nachricht[]
}

function aendern(alle: Nachricht[], id: string, wie: (n: Nachricht) => Nachricht): Nachricht[] {
  return alle.map((n) => (n.id === id ? wie(n) : n))
}

export function gelesenSetzen(alle: Nachricht[], id: string, gelesen: boolean): Nachricht[] {
  return aendern(alle, id, (n) => ({ ...n, gelesen }))
}

export function markierungSetzen(alle: Nachricht[], id: string, markiert: boolean): Nachricht[] {
  return aendern(alle, id, (n) => ({ ...n, markiert }))
}

export function verschieben(alle: Nachricht[], id: string, ordnerId: string): Nachricht[] {
  return aendern(alle, id, (n) => ({ ...n, ordnerId }))
}

/** Den Zielordner einer Rolle im selben Postfach finden.
 *
 *  Wichtig: **im selben Postfach.** Eine Nachricht aus dem GMX-Konto in den
 *  iCloud-Papierkorb zu schieben ginge auf einem echten Server gar nicht -
 *  und in der Attrappe saehe es aus, als ginge es. */
export function zielOrdner(ordner: Ordner[], kontoId: string, rolle: OrdnerRolle): Ordner | undefined {
  return ordner.find((o) => o.kontoId === kontoId && o.rolle === rolle)
}

/** Zaehler je Ordner aus den Nachrichten selbst ableiten.
 *
 *  Die Zahlen stehen deshalb NICHT fest in den Daten: Sobald etwas
 *  verschoben oder gelesen wird, muessten sie sonst an zwei Stellen
 *  nachgepflegt werden - und die zweite vergisst man. */
export function mitZaehlern(ordner: Ordner[], nachrichten: Nachricht[]): Ordner[] {
  return ordner.map((o) => {
    const drin = nachrichten.filter((n) => n.ordnerId === o.id)
    return { ...o, anzahl: drin.length, ungelesen: drin.filter((n) => !n.gelesen).length }
  })
}
