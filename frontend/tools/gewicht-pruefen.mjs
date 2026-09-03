/* Die Waage an der Tür: Wie schwer ist der erste Besuch?
 *
 *   node tools/gewicht-pruefen.mjs        (nach `npm run build`)
 *
 * ⚠️ **Warum es das gibt.** Am 03.09.2026 nachgemessen: ein einziges Stück von
 * 1.089,93 kB, und nichts fragte je danach. Der Bau warnte zwar ab 500 kB,
 * aber eine Warnung, die den Bau durchgehen lässt, liest nach dem dritten Mal
 * keiner mehr. Diese Prüfung bricht ab. Übernommen aus Nexview, wo dieselbe
 * Waage steht — dieselbe Bedienung an beiden Stellen ist mehr wert als eine
 * eigene Idee.
 *
 * ⚠️ **UND DIE GRENZE WIRD BEIM FEHLSCHLAG NICHT HOCHGESETZT.** Das ist der
 * ganze Sinn der Sache. Eine Waage, an der man das Gewicht verstellt, sobald
 * sie anschlägt, misst nichts mehr — sie bestätigt nur noch jeden Zustand.
 * Schlägt sie an, gehört das Gewicht zurück.
 *
 * ⚠️ **Der nächste Schritt steht schon fest.** nexmail liefert heute nichts
 * nach: Der Editor (380,5 kB, 35 Prozent des JavaScript) und die Kalenderseite
 * (58,8 kB) hängen fest am Einstieg, obwohl beide erst auf Klick gebraucht
 * werden. Wer hier ansteht, legt sie hinter `lazy(...)`, statt die Zahl zu
 * ändern. Warum das nicht nebenbei geht, steht in `vite.config.ts`.
 *
 * Gemessen wird, was ein Besucher beim Öffnen wirklich herunterlädt: der
 * Einstieg samt allem, was **fest** daran hängt, dazu das Stilblatt.
 * Nachgeliefertes (`dynamicImports`) zählt nicht mit — das ist ja gerade das,
 * was ein normaler Besuch nie holt. Heute gibt es davon nichts.
 */

import { readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

/** Die Grenze in Kilobyte. Lies den Absatz oben, bevor du sie anfasst. */
const GRENZE_KB = 1200

/* 1 kB = 1000 Bytes, nicht 1024 — dieselbe Rechnung, die Vite beim Bauen
 * ausgibt. Sonst stünden im selben Protokoll zwei Zahlen für dieselbe Datei. */
const KILO = 1000

const hier = path.dirname(fileURLToPath(import.meta.url))
const DIST = path.join(hier, '..', 'dist')
const MANIFEST = path.join(DIST, '.vite', 'manifest.json')

let manifest
try {
  manifest = JSON.parse(readFileSync(MANIFEST, 'utf8'))
} catch {
  console.error(
    `Kein Bau gefunden (${path.relative(process.cwd(), MANIFEST)}).\n` +
      'Erst `npm run build`, dann diese Prüfung.',
  )
  process.exit(2)
}

const eintragSchluessel = Object.keys(manifest).find((k) => manifest[k].isEntry)
if (!eintragSchluessel) {
  console.error('Im Manifest steht kein Einstiegspunkt — stimmt die Bau-Einstellung noch?')
  process.exit(2)
}

/**
 * Alles einsammeln, was **fest** am Einstieg hängt.
 *
 * `imports` sind die festen Abhängigkeiten; die holt der Browser mit.
 * `dynamicImports` bleiben absichtlich draußen — das wäre der Nachschub.
 */
const fest = new Set()
function folgen(schluessel) {
  if (fest.has(schluessel) || !manifest[schluessel]) return
  fest.add(schluessel)
  for (const naechster of manifest[schluessel].imports ?? []) folgen(naechster)
}
folgen(eintragSchluessel)

const dateien = new Set()
for (const schluessel of fest) {
  const eintrag = manifest[schluessel]
  if (eintrag.file) dateien.add(eintrag.file)
  for (const stil of eintrag.css ?? []) dateien.add(stil)
}

/* ⚠️ **Bodenschwelle.** Findet die Waage nur eine Handvoll Dateien, hat sich
 * am Bau etwas geändert und sie wiegt Luft — dann meldet sie lebenslang
 * „in Ordnung". Vier Stücke plus Stilblatt sind der heutige Stand. */
if (dateien.size < 3) {
  console.error(
    `Nur ${dateien.size} Datei(en) am Einstieg gefunden. Das kann nicht stimmen;\n` +
      'entweder ist der Bau kaputt oder das Manifest hat eine andere Form.',
  )
  process.exit(2)
}

// ---------------------------------------------------------------------------

const groesse = (datei) => statSync(path.join(DIST, datei)).size
const kb = (bytes) => (bytes / KILO).toFixed(2).padStart(9)
const liste = [...dateien].sort((a, b) => groesse(b) - groesse(a))

let summe = 0
let gepackt = 0
console.log('Was ein Besucher beim Öffnen herunterlädt:\n')
for (const datei of liste) {
  const bytes = groesse(datei)
  const zip = gzipSync(readFileSync(path.join(DIST, datei))).length
  summe += bytes
  gepackt += zip
  console.log(`  ${kb(bytes)} kB   (gepackt ${kb(zip)} kB)   ${datei}`)
}
console.log(`\n  ${kb(summe)} kB   (gepackt ${kb(gepackt)} kB)   zusammen`)
console.log(`  ${kb(GRENZE_KB * KILO)} kB${' '.repeat(24)}Grenze\n`)

if (summe > GRENZE_KB * KILO) {
  console.error(
    `Zu schwer: ${(summe / KILO).toFixed(2)} kB statt höchstens ${GRENZE_KB} kB.\n\n` +
      'Die Grenze wird NICHT hochgesetzt. Der nächste Schritt steht im Kopf\n' +
      'dieser Datei: Editor und Kalenderseite hinter `lazy(...)` legen, dann\n' +
      'kommen sie erst, wenn jemand sie öffnet.\n\n' +
      'Soll die Grenze wirklich steigen, ist das eine Frage an den Betreiber.',
  )
  process.exit(1)
}

console.log('In Ordnung.')
