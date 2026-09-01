/* Das nexmail-Zeichen einmal als PNG ablegen.
 *
 * ⚠️ Der Server hat keine Bildbibliothek (kein Pillow, kein cairosvg), und
 * eine dafuer nachzuziehen waere ein schweres Paket fuer ein einziges Bild.
 * Also wird hier gerastert und das Ergebnis eingecheckt. Wer das Logo aendert,
 * laesst dieses Skript einmal laufen.
 */
import { chromium } from '@playwright/test'
import { writeFileSync } from 'node:fs'

const SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256">
  <defs><linearGradient id="m" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#5fe4bb"/><stop offset="55%" stop-color="#23d19e"/>
    <stop offset="100%" stop-color="#02543e"/></linearGradient></defs>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="#0d1614"/>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="none" stroke="url(#m)" stroke-width="2.5" stroke-opacity=".55"/>
  <rect x="13" y="20" width="38" height="24" rx="4" fill="none" stroke="url(#m)" stroke-width="3.2" stroke-linejoin="round"/>
  <path d="M14.6 21.8 32 34.8 49.4 21.8Z" fill="url(#m)"/>
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
