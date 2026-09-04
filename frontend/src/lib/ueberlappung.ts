/* Wie sich gleichzeitige Termine die Breite einer Tagesspalte teilen.
 *
 * ⚠️ **Vorher verdeckten sie einander vollständig.** Die Blöcke standen
 * `absolute left-1 right-1`; zwei Termine zur selben Zeit lagen exakt
 * übereinander, und der obere verbarg den unteren restlos. Am 04.09.2026
 * aufgefallen, als ein gezogener Termin auf einem anderen landete: Er war
 * danach nicht mehr zu sehen, und das sieht aus wie verloren, nicht wie
 * verdeckt.
 *
 * ⚠️ **Ohne Browser, damit es prüfbar bleibt** — dieselbe Trennung wie bei
 * `ziehen.ts` und `lesegrund.ts`. Was hier falsch ist, versteckt einen echten
 * Termin, und das merkt man erst, wenn man ihn sucht.
 */

/** Nur die beiden Ränder zählen; alles andere gehört der Ansicht. */
export interface Zeitspanne {
  /** ISO mit Zone. */
  beginn: string
  ende: string
}

/** Wo ein Termin in seiner Gruppe steht. */
export interface Lage {
  /** Die nullbasierte Spalte innerhalb der Gruppe. */
  spalte: number
  /** Wie viele Spalten die Gruppe insgesamt braucht. */
  spalten: number
}

/** Die Lage je Termin, in derselben Reihenfolge wie die Eingabe.
 *
 * ⚠️ **Die Rückgabe ist stellengleich, nicht umsortiert.** Gerechnet wird auf
 * einer sortierten Kopie; wer die sortierte Liste zurückgäbe, brächte die
 * Reihenfolge der Ansicht durcheinander, und beim nächsten Zeichnen sprängen
 * die Blöcke.
 */
export function nebeneinander(termine: Zeitspanne[]): Lage[] {
  const punkte = termine.map((t, stelle) => ({
    stelle,
    von: new Date(t.beginn).getTime(),
    bis: new Date(t.ende).getTime(),
  }))

  /* Früher zuerst; bei gleichem Beginn der längere zuerst. Ohne die zweite
     Regel hinge es an der Reihenfolge des Servers, welcher Termin links
     steht — und die kann sich zwischen zwei Abrufen ändern. */
  const sortiert = [...punkte].sort((a, b) => a.von - b.von || b.bis - a.bis || a.stelle - b.stelle)

  const raus: Lage[] = termine.map(() => ({ spalte: 0, spalten: 1 }))

  /** Die Termine der laufenden Gruppe und das Ende jeder belegten Spalte. */
  let gruppe: number[] = []
  let spaltenEnden: number[] = []

  function gruppeAbschliessen() {
    const breite = Math.max(1, spaltenEnden.length)
    for (const stelle of gruppe) raus[stelle].spalten = breite
    gruppe = []
    spaltenEnden = []
  }

  for (const p of sortiert) {
    /* ⚠️ **Eine Gruppe endet erst, wenn ALLE ihre Spalten frei sind.** Sie
       ist transitiv: A überschneidet B, B überschneidet C, A und C aber
       nicht — trotzdem gehören alle drei in dieselbe Gruppe, sonst rechnete
       B mit einer anderen Breite als A und die Blöcke lägen wieder
       übereinander. */
    if (spaltenEnden.length > 0 && spaltenEnden.every((ende) => ende <= p.von)) {
      gruppeAbschliessen()
    }

    /* ⚠️ **`<=`, nicht `<`.** Ein Termin, der genau dann beginnt, wenn der
       vorige endet, überschneidet sich nicht — er darf dieselbe Spalte
       bekommen. Sonst rutschte jede lückenlose Tagesplanung in immer neue
       Spalten und wäre am Ende fingerbreit. */
    let spalte = spaltenEnden.findIndex((ende) => ende <= p.von)
    if (spalte === -1) {
      spalte = spaltenEnden.length
      spaltenEnden.push(p.bis)
    } else {
      spaltenEnden[spalte] = p.bis
    }

    raus[p.stelle].spalte = spalte
    gruppe.push(p.stelle)
  }
  gruppeAbschliessen()

  return raus
}
