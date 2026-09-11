/* Kalendertage, ohne Browser: Liegt ein Vorkommen an einem Tag, und wie
 * heißt ein Tag als `JJJJ-MM-TT`? Beides braucht die Kalenderseite und die
 * Rechnung der schmalen Ansicht (`kalenderschmal.ts`); zwei Kopien liefen
 * auseinander, und dann zeigte das Telefon einen Termin an einem anderen Tag
 * als der Rechner. */

export interface TagVorkommen {
  beginn: string
  ende: string
  ganztaegig: boolean
}

/** Der Kalendertag als `JJJJ-MM-TT` — aus den örtlichen Feldern, nicht über
 *  `toISOString()`: Das rechnete erst nach UTC um und verschöbe den Tag. */
export function alsDatum(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Liegt der Termin an diesem Tag? Ganztägige spannen über mehrere. */
export function imTag(e: TagVorkommen, d: Date): boolean {
  /* ⚠️ **Ein ganztägiger Termin ist ein DATUM, kein Zeitpunkt.**
   *
   * Er steht als UTC-Mitternacht in der Datenbank (`2026-09-14T00:00:00Z` bis
   * `2026-09-15T00:00:00Z`, das Ende ausschließend). `new Date(...)` macht
   * daraus in Berlin den 14. um **02:00** und das Ende am 15. um 02:00 — und
   * damit ragt der Termin in den 15. hinein. Genau so gemeldet am 03.09.2026:
   * „Der Termin wird mir in Google für den 14. angezeigt, in nexmail steht er
   * von 14–15."
   *
   * Westlich von Greenwich wäre es andersherum: Dort begänne er am 13.
   * Verglichen wird deshalb der **Kalendertag**, nie eine Ortszeit. */
  if (e.ganztaegig) {
    const tag = alsDatum(d)
    return e.beginn.slice(0, 10) <= tag && tag < e.ende.slice(0, 10)
  }
  const a = new Date(e.beginn)
  const b = new Date(e.ende)
  const tagAnfang = new Date(d)
  tagAnfang.setHours(0, 0, 0, 0)
  const tagEnde = new Date(tagAnfang)
  tagEnde.setDate(tagEnde.getDate() + 1)
  return a < tagEnde && b > tagAnfang
}
