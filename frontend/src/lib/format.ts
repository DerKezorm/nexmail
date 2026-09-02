/* Datum, Groesse, Namen — alles, was in der Liste und im Lesebereich
 * lesbar aussehen muss.
 *
 * Die Sprache kommt immer von aussen herein. Ein fest eingebautes "de-DE"
 * waere in der englischen Fassung sofort falsch, und zwar unauffaellig: Das
 * Datum stuende einfach in der falschen Reihenfolge.
 */
import type { Person } from '../daten/typen'

/* ⚠️ **Die Zeitzone kommt aus den Einstellungen, nicht vom Browser.**
 *
 * Ein Container läuft fast immer in UTC, der Betreiber nicht — und der
 * Browser kann auf einem dritten Gerät in einer vierten Zone stehen. Ohne
 * eine feste Zone zeigte dieselbe Mail auf dem Telefon eine andere Uhrzeit
 * als am Schreibtisch, und niemand könnte sagen, welche stimmt.
 *
 * Leer heißt bewusst „die des Browsers": Wer nichts einstellt, bekommt das
 * Verhalten, das er von jeder anderen Anwendung kennt.
 */
let _zone = ''

export function zeitzoneSetzen(zone: string): void {
  _zone = zone
}

export function zeitzone(): string {
  return _zone
}

/** Die Formatierungsangaben mit der eingestellten Zone. */
function mitZone<T extends Intl.DateTimeFormatOptions>(angaben: T): T {
  return _zone ? { ...angaben, timeZone: _zone } : angaben
}

/** Datumsteile in der eingestellten Zone — für Tagesvergleiche. */
function teileIn(d: Date): { jahr: number; monat: number; tag: number } {
  if (!_zone) return { jahr: d.getFullYear(), monat: d.getMonth() + 1, tag: d.getDate() }
  const f = new Intl.DateTimeFormat('en-CA', {
    timeZone: _zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  const [jahr, monat, tag] = f.format(d).split('-').map(Number)
  return { jahr, monat, tag }
}

export type Datumsgruppe = 'heute' | 'gestern' | 'diese_woche' | 'aelter'

function tagesbeginn(d: Date): number {
  // ⚠️ In der eingestellten Zone, nicht in der des Browsers — sonst rutscht
  // „heute" um Mitternacht herum um einen Tag.
  const { jahr, monat, tag } = teileIn(d)
  return Date.UTC(jahr, monat - 1, tag)
}

/** In welche Ueberschrift der Liste eine Nachricht gehoert. */
export function gruppeVon(iso: string, jetzt = new Date()): Datumsgruppe {
  const tage = Math.round((tagesbeginn(jetzt) - tagesbeginn(new Date(iso))) / 86_400_000)
  if (tage <= 0) return 'heute'
  if (tage === 1) return 'gestern'
  if (tage < 7) return 'diese_woche'
  return 'aelter'
}

/** Kurzform fuer die Liste: heute die Uhrzeit, sonst der Tag. */
export function kurzesDatum(iso: string, sprache: string, jetzt = new Date()): string {
  const d = new Date(iso)
  const gruppe = gruppeVon(iso, jetzt)
  if (gruppe === 'heute') {
    return d.toLocaleTimeString(sprache, mitZone({ hour: '2-digit', minute: '2-digit' }))
  }
  if (teileIn(d).jahr === teileIn(jetzt).jahr) {
    return d.toLocaleDateString(sprache, mitZone({ day: '2-digit', month: 'short' }))
  }
  return d.toLocaleDateString(
    sprache,
    mitZone({ day: '2-digit', month: '2-digit', year: '2-digit' }),
  )
}

/** Lange Form fuer den Kopf einer geoeffneten Nachricht. */
export function langesDatum(iso: string, sprache: string): string {
  return new Date(iso).toLocaleString(
    sprache,
    mitZone({
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }),
  )
}

/** Ein Zeitpunkt aus dem Protokoll — dort steht er in UTC. */
export function protokollzeit(roh: string, sprache: string): string {
  // ⚠️ Das ``Z`` ist nötig: Ohne Zonenangabe liest der Browser die Zeichenkette
  // als **Ortszeit** und verschiebt sie ein zweites Mal.
  const d = new Date(roh.replace(' ', 'T') + 'Z')
  if (Number.isNaN(d.getTime())) return roh
  return d.toLocaleString(
    sprache,
    mitZone({ day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }),
  )
}

/** Der Zeitpunkt eines geplanten Versands — Wochentag, Tag und Uhrzeit.
 *  In der eingestellten Zone wie jedes andere Datum; „18:00" soll hier
 *  dasselbe heissen wie in der Liste daneben. */
export function planzeit(iso: string, sprache: string): string {
  return new Date(iso).toLocaleString(
    sprache,
    mitZone({ weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }),
  )
}

/** Dateigroessen. Bewusst mit einer Nachkommastelle ab Megabyte - "3 MB"
 *  fuer alles zwischen 2,5 und 3,4 MB verschleiert genau dann etwas, wenn es
 *  um das Anhang-Limit des Anbieters geht. */
export function groesse(bytes: number, sprache: string): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`
  return `${(bytes / 1024 / 1024).toLocaleString(sprache, { maximumFractionDigits: 1 })} MB`
}

/** Was in der Liste als Absender steht. Ohne Namen die Adresse - nie leer. */
export function anzeigename(p: Person): string {
  return p.name || p.adresse
}

/** Zwei Buchstaben fuer den Kreis vor der Nachricht. */
export function initialen(p: Person): string {
  const quelle = p.name || p.adresse
  const teile = quelle.split(/[\s.@_-]+/).filter(Boolean)
  if (teile.length === 0) return '?'
  if (teile.length === 1) return teile[0]!.slice(0, 2).toUpperCase()
  return (teile[0]![0]! + teile[1]![0]!).toUpperCase()
}
