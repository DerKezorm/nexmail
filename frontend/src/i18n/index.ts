/* Sprachen.
 *
 * Deutsch und Englisch sind gebaut. Eine dritte Sprache ist eine Datei
 * daneben und ein Eintrag in SPRACHEN - sonst nichts. Deshalb steht hier
 * eine Liste und keine Handvoll verstreuter if-Zweige.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import de from './de.json'
import en from './en.json'

export const SPRACHEN = [
  { code: 'de', name: 'Deutsch' },
  { code: 'en', name: 'English' },
] as const

export type Sprachcode = (typeof SPRACHEN)[number]['code']

const GEMERKT = 'nexmail.sprache'

function startsprache(): Sprachcode {
  const gemerkt = localStorage.getItem(GEMERKT)
  if (SPRACHEN.some((s) => s.code === gemerkt)) return gemerkt as Sprachcode
  // Nur der Sprachteil zaehlt: "de-AT" ist Deutsch.
  const vomBrowser = navigator.language.slice(0, 2)
  return SPRACHEN.some((s) => s.code === vomBrowser) ? (vomBrowser as Sprachcode) : 'de'
}

void i18n.use(initReactI18next).init({
  resources: { de: { translation: de }, en: { translation: en } },
  lng: startsprache(),
  fallbackLng: 'de',
  interpolation: { escapeValue: false },
})

export function spracheSetzen(code: Sprachcode) {
  localStorage.setItem(GEMERKT, code)
  void i18n.changeLanguage(code)
  document.documentElement.lang = code
}

document.documentElement.lang = i18n.language

export default i18n
