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
  <defs><linearGradient id="m" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
    <stop offset="0" stop-color="#34c795"/><stop offset=".5" stop-color="#0e8f68"/>
    <stop offset="1" stop-color="#06513d"/></linearGradient></defs>
  <rect x="12" y="18" width="40" height="28" rx="5" fill="none" stroke="url(#m)" stroke-width="4.2"/>
  <path d="M15 21.5 32 34.5 49 21.5" fill="none" stroke="#12b886" stroke-width="4.2"
        stroke-linecap="round" stroke-linejoin="round"/>`

/* Helle Fassung (weisse Kachel), wie das App-Symbol der iPhone-App. */
function eckig(groesse) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
    width="${groesse}" height="${groesse}">
    <rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>
    <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none"
          stroke="#0e8f68" stroke-opacity=".35" stroke-width="1.5"/>
    ${MARKE}
  </svg>`
}

function maskierbar(groesse) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
    width="${groesse}" height="${groesse}">
    <rect width="64" height="64" fill="#fff"/>
    <g transform="translate(32 32) scale(0.78) translate(-32 -32)">${MARKE}</g>
  </svg>`
}

/* ⚠️ **Das Abzeichen ist einfarbig und wird eingefärbt.** Android legt
   es als kleine Silhouette in die Statusleiste: Alles, was nicht durchsichtig
   ist, wird weiß. Ein farbiges Bild wird dort zu einem weißen Klotz. */
function silhouette(groesse) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
    width="${groesse}" height="${groesse}">
    <rect x="10" y="16" width="44" height="32" rx="6" fill="none"
          stroke="#ffffff" stroke-width="5"/>
    <path d="M14 20.5 32 34.5 50 20.5" fill="none" stroke="#ffffff" stroke-width="5"
          stroke-linecap="round" stroke-linejoin="round"/>
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
