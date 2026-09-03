/* Die Symbole für den Home-Bildschirm einmal rastern.
 *
 * ⚠️ **Ohne sie gibt es auf dem Telefon keine Meldungen.** Apple liefert Web
 * Push nur an Seiten, die auf dem Home-Bildschirm liegen, und dorthin kommt
 * nur, was ein Manifest mit Symbolen hat. Ein fehlendes Symbol ist deshalb
 * nicht ein hässliches Kachelbild, sondern eine Funktion, die stumm ausbleibt.
 *
 * ⚠️ **Zwei Sorten, und die zweite ist nicht dieselbe in anderer Größe.**
 * Android beschneidet ein „maskable"-Symbol auf eine Form seiner Wahl —
 * Kreis, Squircle, Tropfen. Alles außerhalb der inneren 80 Prozent kann
 * wegfallen. Wer dasselbe Bild für beide nimmt, verliert dort den Rand des
 * Zeichens; deshalb steht das Zeichen hier kleiner in einer vollen Fläche.
 *
 * ⚠️ **Gerastert wird mit Playwright, wie beim Logo im Server.** Das Frontend
 * hat keine Bildbibliothek, und eine dafür nachzuziehen wäre ein schweres
 * Paket für vier Bilder. Wer das Zeichen ändert, lässt dieses Skript einmal
 * laufen:  node tools/symbole.mjs
 */
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

/* Dasselbe Zeichen wie in backend/app/vorlagen/logo-rastern.mjs.
   ⚠️ Wer es hier ändert, ändert es dort mit — sonst sieht die Systemmail
   anders aus als das Symbol auf dem Telefon. */
const MARKE = `
  <defs><linearGradient id="m" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#5fe4bb"/><stop offset="55%" stop-color="#23d19e"/>
    <stop offset="100%" stop-color="#02543e"/></linearGradient></defs>
  <rect x="13" y="20" width="38" height="24" rx="4" fill="none"
        stroke="url(#m)" stroke-width="3.2" stroke-linejoin="round"/>
  <path d="M14.6 21.8 32 34.8 49.4 21.8Z" fill="url(#m)"/>`

/** Das gewöhnliche Symbol: gerundete Kachel, Zeichen fast randlos. */
function eckig(groesse) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
    width="${groesse}" height="${groesse}">
    <rect x="2" y="2" width="60" height="60" rx="16" fill="#0d1614"/>
    <rect x="2" y="2" width="60" height="60" rx="16" fill="none"
          stroke="url(#m)" stroke-width="2.5" stroke-opacity=".55"/>
    ${MARKE}
  </svg>`
}

/** Das beschneidbare: volle Fläche, Zeichen in der sicheren Mitte. */
function maskierbar(groesse) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
    width="${groesse}" height="${groesse}">
    <rect width="64" height="64" fill="#0d1614"/>
    <g transform="translate(32 32) scale(0.72) translate(-32 -32)">${MARKE}</g>
  </svg>`
}

/* ⚠️ **Das Meldungssymbol ist einfarbig und wird eingefärbt.** Android legt
   es als kleine Silhouette in die Statusleiste: Alles, was nicht durchsichtig
   ist, wird weiß. Ein farbiges Bild wird dort zu einem weißen Klotz. */
function silhouette(groesse) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
    width="${groesse}" height="${groesse}">
    <rect x="13" y="20" width="38" height="24" rx="4" fill="none"
          stroke="#ffffff" stroke-width="3.6" stroke-linejoin="round"/>
    <path d="M14.6 21.8 32 34.8 49.4 21.8Z" fill="#ffffff"/>
  </svg>`
}

const BILDER = [
  ['public/symbol-192.png', eckig(192), 192],
  ['public/symbol-512.png', eckig(512), 512],
  ['public/symbol-maskierbar-512.png', maskierbar(512), 512],
  ['public/meldung-96.png', silhouette(96), 96],
]

mkdirSync('public', { recursive: true })
const browser = await chromium.launch()
for (const [pfad, svg, groesse] of BILDER) {
  const seite = await browser.newPage({ viewport: { width: groesse, height: groesse } })
  await seite.setContent(`<body style="margin:0;background:transparent">${svg}</body>`)
  await seite.locator('svg').screenshot({ path: pfad, omitBackground: true })
  await seite.close()
  console.log('geschrieben:', pfad)
}
await browser.close()
