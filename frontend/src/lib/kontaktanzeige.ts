/* Wie ein Kontakt in einer Liste beschriftet wird.
 *
 * ⚠️ **Seit dem 05.09.2026 darf die Adresse fehlen.** Mit CardDAV ist nexmail
 * der zweite Client einer Kontaktliste, und die hat Menschen ohne Postfach:
 * die Werkstatt, die Oma. Die Liste zeigte bis dahin `name || adresse` und
 * darunter die Adresse; ein Kontakt ohne beides wäre eine leere Zeile gewesen.
 *
 * Genommen wird, was da ist: erst der Name, sonst die Adresse, sonst die
 * Nummer, sonst die Firma. Darunter steht das Nächste, das nicht schon oben
 * steht. Ohne Browser, damit die schnelle Prüfebene es laden kann. */
export interface Beschriftbar {
  name: string
  adresse: string
  telefon: string
  firma: string
}

export function beschriftung(k: Beschriftbar): { titel: string; unter: string } {
  const titel = k.name || k.adresse || k.telefon || k.firma
  const unter = [k.adresse, k.telefon, k.firma].find((w) => w && w !== titel) ?? ''
  return { titel, unter }
}

/** Welche Kontakte die Liste zeigt, nach den Haken an den Büchern.
 *
 * ⚠️ **Ein Kontakt, dessen Buch die Liste nicht kennt, bleibt sichtbar.**
 * Versteckt wird nur, was ausdrücklich abgehakt ist; alles andere wäre ein
 * Eintrag, der unsichtbar ist, ohne gelöscht zu sein, und das sieht aus wie
 * Datenverlust. */
export function sichtbareKontakte<K extends { adressbuch_id?: string | null }>(
  liste: K[],
  buecher: Array<{ id: string; sichtbar: boolean }>,
): K[] {
  const versteckt = new Set(buecher.filter((b) => !b.sichtbar).map((b) => b.id))
  return liste.filter((k) => !k.adressbuch_id || !versteckt.has(k.adressbuch_id))
}
