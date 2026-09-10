/* Der Auswahlmodus der schmalen Ansicht — die Regeln, ohne Browser.
 *
 * Am Rechner sammelt man Nachrichten mit Strg und Umschalt und wirkt auf die
 * Auswahl über Tastatur und Rechtsklick. Am Telefon gibt es keinen dieser
 * Wege, und auf dem iPhone löst ein langer Druck nicht einmal das
 * Kontextmenü aus. Der Weg dort ist der aus Outlook, Apple Mail und Gmail:
 * ein Modus, in dem ein Tipp markiert statt öffnet, ein Zähler oben und
 * eine Leiste unten für alles, was auf die Auswahl wirkt.
 *
 * Hier stehen nur die Entscheidungen, damit die schnelle Prüfebene sie laden
 * kann — dieselbe Trennung wie bei `wischen.ts` und `pushlage.ts`. Die
 * Gesten sitzen in `Nachrichtenliste.tsx`, die Leiste in
 * `Auswahlleiste.tsx`.
 */

/** Ab so vielen Millisekunden gilt ein Druck als lang. Outlook und Apple
 *  liegen bei rund einer halben Sekunde; deutlich kürzer feuert er beim
 *  Rollen, deutlich länger fühlt er sich kaputt an. */
export const LANGDRUCK_MS = 450

/** So weit darf der Finger dabei wandern. Darüber ist es Rollen oder ein
 *  Wisch, und der Druck bricht ab — sonst markierte jedes Rollen mit
 *  ruhendem Daumen eine Zeile. */
export const LANGDRUCK_TOLERANZ_PX = 8

export function zuWeitGewandert(
  x0: number,
  y0: number,
  x: number,
  y: number,
  toleranz = LANGDRUCK_TOLERANZ_PX,
): boolean {
  return Math.abs(x - x0) > toleranz || Math.abs(y - y0) > toleranz
}

/** Was der Gelesen-Knopf der Leiste tut. Sind alle gewählten gelesen, macht
 *  er sie ungelesen; sonst gelesen. ⚠️ Eine gemischte Auswahl wird gelesen —
 *  beim Aufräumen ist das der häufigere Wunsch, und Outlook entscheidet
 *  genauso. */
export function gelesenZiel(
  gewaehlte: ReadonlyArray<{ gelesen: boolean }>,
): 'gelesen' | 'ungelesen' {
  if (gewaehlte.length > 0 && gewaehlte.every((n) => n.gelesen)) return 'ungelesen'
  return 'gelesen'
}

/** Sind alle sichtbaren Zeilen in der Auswahl? Bei leerer Liste nein —
 *  sonst hieße der Knopf „Keine", obwohl es nichts zu nehmen gibt. */
export function sindAlleGewaehlt(sichtbare: readonly string[], auswahl: readonly string[]): boolean {
  return sichtbare.length > 0 && sichtbare.every((id) => auswahl.includes(id))
}

/** „Alle" schaltet um: Sind schon alle sichtbaren gewählt, nimmt es sie alle
 *  heraus; sonst nimmt es alle hinein. ⚠️ Nur die **sichtbaren** — die Liste
 *  hält eine Seite, und „alle" meint, was man vor sich hat. */
export function alleUmschalten(sichtbare: readonly string[], auswahl: readonly string[]): string[] {
  return sindAlleGewaehlt(sichtbare, auswahl) ? [] : [...sichtbare]
}

/** Was in der Leiste steht und deshalb im Blatt „Mehr" nicht noch einmal. */
export const IN_DER_LEISTE: readonly string[] = ['loeschen', 'archivieren', 'verschieben', 'gelesen']

/** Was nur auf genau eine Nachricht wirkt und in einer Auswahl keinen Sinn
 *  hat — im Kontextmenü stehen diese Einträge grau, im Blatt fehlen sie. */
export const NUR_EINZELN: readonly string[] = ['antworten', 'allen', 'weiter', 'anhang', 'drucken']

/** Die Einträge des Kontextmenüs, die ins Blatt „Mehr" gehören: alles außer
 *  dem, was die Leiste schon trägt, dem, was nur einzeln geht, und dem
 *  Platzhalter für Regeln. Die Reihenfolge bleibt die des Menüs. */
export function fuersMehrBlatt<T extends { id: string; deaktiviert?: boolean }>(eintraege: readonly T[]): T[] {
  return eintraege.filter(
    (e) => !IN_DER_LEISTE.includes(e.id) && !NUR_EINZELN.includes(e.id) && e.id !== 'regel',
  )
}
