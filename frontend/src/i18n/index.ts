/* Sprachen.
 *
 * Deutsch und Englisch sind gebaut. Eine dritte Sprache ist eine Datei
 * daneben und ein Eintrag in SPRACHEN - sonst nichts. Deshalb steht hier
 * eine Liste und keine Handvoll verstreuter if-Zweige.
 *
 * ⚠️ Zwei Texte entstehen im Server und haben dort eine EIGENE Pflegestelle:
 * die Druckseiten-Beschriftungen (_DRUCK_TEXTE in routers/nachrichten.py)
 * und die Zitatkoepfe (zitat_text/zitat_html in services/verfassen.py).
 * Ohne Eintrag dort faellt eine dritte Sprache an diesen Stellen auf
 * Englisch zurueck.
 *
 * ⚠️ **Geladen wird nur die eine Sprache, die gilt.** Bis zum 03.09.2026
 * standen beide fest im Bündel: Jeder Besucher lud Deutsch **und** Englisch,
 * und die Hälfte davon las nie jemand. Aufgefallen ist es, als der Katalog der
 * Servermeldungen dazukam (185 Einträge je Sprache) und die Waage in
 * `tools/gewicht-pruefen.mjs` anschlug — die Grenze wird beim Anschlagen nicht
 * hochgesetzt, sondern das Gewicht gesenkt.
 *
 * ⚠️ **Die zweite Sprache kommt beim Umschalten nach**, nicht vorher. Das
 * kostet dort einen Augenblick und spart ihn bei jedem einzelnen Start.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

export const SPRACHEN = [
  { code: 'de', name: 'Deutsch' },
  { code: 'en', name: 'English' },
] as const

export type Sprachcode = (typeof SPRACHEN)[number]['code']

const GEMERKT = 'nexmail.sprache'

/* ⚠️ **Die Zweige müssen statisch dastehen.** Ein `import(`./${code}.json`)`
   lässt Vite jede passende Datei einzeln bündeln — das funktioniert, aber der
   Bau kann dann nicht mehr sehen, welche es wirklich gibt, und ein Tippfehler
   fällt erst zur Laufzeit auf. */
const LADER: Record<Sprachcode, () => Promise<{ default: object }>> = {
  de: () => import('./de.json'),
  en: () => import('./en.json'),
}

function startsprache(): Sprachcode {
  const gemerkt = localStorage.getItem(GEMERKT)
  if (SPRACHEN.some((s) => s.code === gemerkt)) return gemerkt as Sprachcode
  // Nur der Sprachteil zaehlt: "de-AT" ist Deutsch.
  const vomBrowser = navigator.language.slice(0, 2)
  return SPRACHEN.some((s) => s.code === vomBrowser) ? (vomBrowser as Sprachcode) : 'de'
}

const geladen = new Set<Sprachcode>()

async function nachladen(code: Sprachcode): Promise<void> {
  if (geladen.has(code)) return
  const modul = await LADER[code]()
  i18n.addResourceBundle(code, 'translation', modul.default, true, true)
  geladen.add(code)
}

/** i18next mit **einer** Sprache hochfahren. Muss vor dem ersten Zeichnen laufen.
 *
 * ⚠️ **Vor dem Zeichnen, nicht nebenher.** Wer die Sprache nachlädt, während
 * React schon rendert, zeigt für einen Moment die rohen Schlüssel — und das
 * sieht aus wie eine kaputte Übersetzung, nicht wie eine langsame.
 */
export async function spracheHochfahren(): Promise<void> {
  const code = startsprache()
  const modul = await LADER[code]()
  geladen.add(code)

  await i18n.use(initReactI18next).init({
    resources: { [code]: { translation: modul.default } },
    lng: code,
    /* ⚠️ **Kein `fallbackLng` auf eine Sprache, die gar nicht geladen ist.**
       Sonst sucht i18next bei einem fehlenden Schlüssel in einem Bündel, das
       es nicht gibt, und gibt den Schlüssel aus. Der Wächter `vollstaendig`
       auf der schnellen Prüfebene hält ohnehin fest, dass beide Sprachen
       dieselben Einträge kennen. */
    fallbackLng: false,
    interpolation: { escapeValue: false },
  })
  document.documentElement.lang = code
}

export async function spracheSetzen(code: Sprachcode): Promise<void> {
  localStorage.setItem(GEMERKT, code)
  await nachladen(code)
  await i18n.changeLanguage(code)
  document.documentElement.lang = code
}

export default i18n
