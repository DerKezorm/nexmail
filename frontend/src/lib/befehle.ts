/* Was die Befehlspalette anbietet und wie sie sucht.
 *
 * ⚠️ **Eine Quelle, drei Formen.** Die Handgriffe an einer Mail kommen aus
 * `nachrichtEintraege`, wie Rechtsklick und Blatt am Telefon. Eine eigene Liste
 * hieße, dass die Palette etwas anbietet, was das Menü nicht mehr kann.
 */
import type { ReactNode } from 'react'
import type { MenueEintrag } from '../components/Kontextmenue'

export interface Befehl {
  id: string
  text: string
  gruppe: string
  symbol?: ReactNode
  gefaehrlich?: boolean
  tun: () => void
}

/** Wie viele Zeilen die Palette zeigt: Wer mehr sehen müsste, tippt weiter. */
export const HOECHSTENS = 40

/** Trennt die Stufen eines Untermenüs in einer Zeile. */
const WEG = ' › '

/** Ein Menü flach machen: „Verschieben › Archiv" ist ein Befehl.
 *
 *  ⚠️ **Gesperrtes fällt weg.** Im Menü erklärt der graue Eintrag, dass es den
 *  Handgriff gibt; hier wäre er eine Zeile, die beim Drücken nichts tut. */
export function ausMenue(eintraege: MenueEintrag[], gruppe: string, davor = ''): Befehl[] {
  return eintraege.flatMap((e): Befehl[] => {
    if (e.deaktiviert) return []
    const text = `${davor}${e.text}`
    if (e.unter) return ausMenue(e.unter, gruppe, `${text}${WEG}`)
    if (!e.tun) return []
    return [{ id: `${gruppe}-${davor}${e.id}`, text, gruppe, symbol: e.symbol, gefaehrlich: e.gefaehrlich, tun: e.tun }]
  })
}

/** Klein und ohne Akzente: „loschen" soll „Löschen" finden. */
function geglaettet(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
}

/** Findet, was alle Wörter enthält; was mit dem ersten beginnt, steht oben.
 *
 *  ⚠️ **Ohne Eingabe weder `nurGesucht` noch Untermenüs.** Sonst stünden vor dem
 *  ersten Tastendruck Dutzende Ordner und Verschieben-Ziele da. */
export function befehleFiltern(befehle: Befehl[], suche: string, nurGesucht: Set<string>): Befehl[] {
  const woerter = geglaettet(suche).split(/\s+/).filter(Boolean)
  if (woerter.length === 0) {
    return befehle
      .filter((b) => !nurGesucht.has(b.gruppe) && !b.text.includes(WEG))
      .slice(0, HOECHSTENS)
  }
  const treffer = befehle.filter((b) => {
    const text = geglaettet(b.text)
    return woerter.every((w) => text.includes(w))
  })
  const vorn = (b: Befehl) => (geglaettet(b.text).startsWith(woerter[0]) ? 0 : 1)
  return [...treffer].sort((a, b) => vorn(a) - vorn(b)).slice(0, HOECHSTENS)
}
