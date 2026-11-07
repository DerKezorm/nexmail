/* Todo-Apps — was der Server über Verbindungen und Listen sagt.
 *
 * ⚠️ **Ein Ziel ist `<verbindung>:<liste>`, leer heißt nexmails eigene
 * Liste.** Die Oberfläche setzt es nie selbst zusammen, sie reicht weiter, was
 * `/api/aufgabenziele/listen` geliefert hat.
 */

export interface Verbindung {
  id: string
  art: string
  name: string
  /** Kennung, warum die App zuletzt nicht wollte — oder leer. */
  fehler: string
  angelegt: string
  zuletzt_abgeglichen: string | null
}

export interface ZielStand {
  standard: string
  verbindungen: Verbindung[]
}

export interface ZielListe {
  ziel: string
  name: string
}

export interface ZielGruppe {
  verbindung_id: string
  art: string
  name: string
  fehler: string
  listen: ZielListe[]
}

/** Was in der Oberfläche als Name der App steht. */
export const ARTNAME: Record<string, string> = {
  todoist: 'Todoist',
  nextasks: 'nextasks',
  webhook: 'Webhook',
}

export function gruppenname(g: { art: string; name: string }): string {
  const art = ARTNAME[g.art] ?? g.art
  // Wer die Verbindung „todoist" nennt, soll nicht „Todoist · todoist" lesen.
  const name = g.name.trim()
  return name && name.toLowerCase() !== art.toLowerCase() ? `${art} · ${name}` : art
}

/** Was an einer nextasks-Verbindung der Mensch selbst beheben muss.
 * ⚠️ Nur Kennungen ohne Werte: An der Verbindung steht nur die Kennung. */
export const NEXTASKS_ZU_BEHEBEN = ['nextasks_api_aus', 'nextasks_nur_lesen', 'nextasks_zu_alt']

/** Der Name einer Liste mit ihrer App davor („Todoist › Arbeit"). */
export function zielname(gruppen: ZielGruppe[], ziel: string): string {
  for (const g of gruppen) {
    const l = g.listen.find((x) => x.ziel === ziel)
    if (l) return `${gruppenname(g)} › ${l.name}`
  }
  return ''
}

/** Ein Tag als `JJJJ-MM-TT` in der Ortszeit des Browsers. */
export function tagText(d: Date): string {
  const zwei = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${zwei(d.getMonth() + 1)}-${zwei(d.getDate())}`
}

/** Die Schnellwahl im Fenster: heute, morgen, kommenden Montag. */
export function schnellwahl(heute: Date): { heute: string; morgen: string; woche: string } {
  const morgen = new Date(heute)
  morgen.setDate(heute.getDate() + 1)
  const montag = new Date(heute)
  // ⚠️ Am Montag selbst heißt „nächste Woche" der Montag in sieben Tagen.
  const bisMontag = ((8 - heute.getDay()) % 7) || 7
  montag.setDate(heute.getDate() + bisMontag)
  return { heute: tagText(heute), morgen: tagText(morgen), woche: tagText(montag) }
}
