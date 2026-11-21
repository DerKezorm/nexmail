/* Das nexmail-Zeichen einmal als PNG ablegen.
 *
 * ⚠️ Der Server hat keine Bildbibliothek (kein Pillow, kein cairosvg), und
 * eine dafuer nachzuziehen waere ein schweres Paket fuer ein einziges Bild.
 * Also wird hier gerastert und das Ergebnis eingecheckt. Helle Fassung, weil
 * die Mail eine weisse Karte hat (``mailvorlage.py``). Wer das Logo aendert,
 * laesst dieses Skript einmal laufen.
 */
import { chromium } from '@playwright/test'
import { writeFileSync } from 'node:fs'

const SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256">
  <defs><linearGradient id="m" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
    <stop offset="0" stop-color="#34c795"/><stop offset=".5" stop-color="#0e8f68"/>
    <stop offset="1" stop-color="#06513d"/></linearGradient></defs>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" stroke="#0e8f68" stroke-opacity=".35" stroke-width="1.5"/>
  <rect x="12" y="18" width="40" height="28" rx="5" fill="none" stroke="url(#m)" stroke-width="4.2"/>
  <path d="M15 21.5 32 34.5 49 21.5" fill="none" stroke="#12b886" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 256, height: 256 } })
await page.setContent(
  `<body style="margin:0;background:transparent">${SVG}</body>`,
)
await page.locator('svg').screenshot({
  path: '../backend/app/vorlagen/logo.png',
  omitBackground: true,
})
await browser.close()
console.log('logo.png geschrieben')
