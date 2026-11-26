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
import { oidcVariables, oidcWording, type OidcWording } from '../vendor/nexoidc/oidc'
import { kontenVariables } from '../vendor/nexkonten/konten'
import { postVariables } from '../vendor/nexpost/post'
import { ownLanguages } from '../vendor/nexsprachen/languages'
import type { Texts } from '../vendor/nexsprachen/sprachen'

export const SPRACHEN = [
  { code: 'de', name: 'Deutsch' },
  { code: 'en', name: 'English' },
] as const

export type Sprachcode = (typeof SPRACHEN)[number]['code']

const GEMERKT = 'nexmail.sprache'

/** Ein Sprachcode wie `nl`, `pt-BR` (wie das Modul sprachen ihn prüft). */
const CODE = /^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}))?$/

function basis(): string {
  // Wie `lib/basis` (BASIS), ohne den Import: diese Datei laden auch Tests ohne DOM.
  const meta = typeof document !== 'undefined' ? document.querySelector('meta[name="nexmail-basis"]')?.getAttribute('content') : null
  return (meta || import.meta.env.BASE_URL || '/').replace(/\/$/, '')
}

/** Die eigenen Sprachen des Betreibers (Modul sprachen, Server › Allgemein › Sprachen), mit nexmails Basis-Pfad. */
export const eigeneSprachen = ownLanguages({
  base: '/api/locales',
  fetcher: (pfad, init) => fetch(`${basis()}${pfad}`, { credentials: 'include', ...init }),
})

/** Die eingebauten Sprachen in der Form des Moduls (`useLanguageOptions`). */
export const EINGEBAUT = SPRACHEN.map((s) => ({ code: s.code, name: s.name }))

/** Die englischen Texte, wie i18next sie hat: die Vorlage für eine neue Sprache (`LanguagesCard template`). */
export async function englischeTexte(): Promise<Texts> {
  return (await LADER.en()).default as Texts
}

/** Die Texte für `code`: eine eingebaute Sprache samt Datei des Betreibers darüber, eine hinzugefügte über dem
 *  Englischen (was ihr fehlt, steht englisch da, nie als roher Schlüssel). Null, wenn nexmail die Sprache nicht kennt. */
async function texteFuer(code: string): Promise<object | null> {
  const eingebaut = SPRACHEN.some((s) => s.code === code) ? ((await LADER[code as Sprachcode]()).default as Texts) : null
  return eigeneSprachen.merged(code, eingebaut, (await LADER.en()).default as Texts)
}

/* ⚠️ **Die Zweige müssen statisch dastehen.** Ein `import(`./${code}.json`)`
   lässt Vite jede passende Datei einzeln bündeln — das funktioniert, aber der
   Bau kann dann nicht mehr sehen, welche es wirklich gibt, und ein Tippfehler
   fällt erst zur Laufzeit auf. */
const LADER: Record<Sprachcode, () => Promise<{ default: object }>> = {
  de: () =>
    mitAnmeldung(
      import('./de.json'),
      import('../vendor/nexoidc/oidc.de.json'),
      import('../vendor/nexkonten/konten.de.json'),
      import('../vendor/nexpost/post.de.json'),
    ),
  en: () =>
    mitAnmeldung(
      import('./en.json'),
      import('../vendor/nexoidc/oidc.en.json'),
      import('../vendor/nexkonten/konten.en.json'),
      import('../vendor/nexpost/post.en.json'),
    ),
}

/* ⚠️ **Die Wortlaute der Anmeldung über Anbieter kommen aus dem gemeinsamen Modul** (`vendor/nexoidc`): in jeder nex-App dieselben Sätze unter `oidc.*`, eingemischt über
   `oidcWording`. nexmails eigene Dateien tragen keinen Schlüssel `oidc`; geändert wird nur im Modul. */
async function mitAnmeldung(
  eigen: Promise<{ default: object }>,
  modul: Promise<{ default: OidcWording }>,
  konten: Promise<{ default: object }>,
  post: Promise<{ default: object }>,
): Promise<{ default: object }> {
  const [app, oidc, kontenmodul, postmodul] = await Promise.all([eigen, modul, konten, post])
  /* ⚠️ **Auch die Wortlaute des Kontenmoduls kommen aus dem Modul** (`vendor/nexkonten`, Namensraum `account`):
     Anmelden, Einrichten, Einladung, Profil und Passwort vergessen sagen in jeder nex-App dasselbe. nexmails eigene
     Dateien tragen keinen Schlüssel `account`. */
  return {
    default: {
      ...app.default,
      ...oidcWording(oidc.default, { singleAccount: false, invitations: true }),
      ...kontenmodul.default,
      // Die Wortlaute des Mailmoduls (Systempostausgang), Namensraum `mail`.
      ...postmodul.default,
    },
  }
}

/** Die Texte einer Sprache, wie sie in i18next landen (samt den Wortlauten der Anmeldung). Auch für Tests. */
export async function ressourcen(code: Sprachcode): Promise<object> {
  return (await LADER[code]()).default
}

/** Was jede i18next-Instanz von nexmail braucht; `spracheHochfahren` und die Tests nehmen dasselbe. */
export const GRUNDEINSTELLUNG = {
  /* ⚠️ **Kein `fallbackLng` auf eine Sprache, die gar nicht geladen ist.**
     Sonst sucht i18next bei einem fehlenden Schlüssel in einem Bündel, das
     es nicht gibt, und gibt den Schlüssel aus. Der Wächter `vollstaendig`
     auf der schnellen Prüfebene hält ohnehin fest, dass beide Sprachen
     dieselben Einträge kennen. */
  fallbackLng: false as const,
  // `{{app}}` und `{{slug}}` in den Wortlauten des Anmeldemoduls, `{{setupTokenEnv}}` und `{{minimum}}` in denen des
  // Kontenmoduls.
  interpolation: {
    escapeValue: false,
    defaultVariables: { ...oidcVariables('nexmail'), ...kontenVariables('nexmail'), ...postVariables('nexmail') },
  },
}

function startsprache(): string {
  const gemerkt = localStorage.getItem(GEMERKT)
  if (SPRACHEN.some((s) => s.code === gemerkt)) return gemerkt as Sprachcode
  // Eine Sprache des Betreibers; gibt es sie nicht mehr, fällt `spracheHochfahren` auf die des Browsers.
  if (gemerkt && CODE.test(gemerkt)) return gemerkt
  // Nur der Sprachteil zaehlt: "de-AT" ist Deutsch.
  const vomBrowser = navigator.language.slice(0, 2)
  return SPRACHEN.some((s) => s.code === vomBrowser) ? (vomBrowser as Sprachcode) : 'de'
}

const geladen = new Set<string>()

async function nachladen(code: string): Promise<boolean> {
  if (geladen.has(code)) return true
  const texte = await texteFuer(code)
  if (!texte) return false
  i18n.addResourceBundle(code, 'translation', texte, true, true)
  geladen.add(code)
  return true
}

/** Nach dem Hinzufügen oder Entfernen einer Sprache (`LanguagesCard onChange`): Liste und Texte neu holen. */
export function eigeneSprachenVergessen(): void {
  eigeneSprachen.forget()
  geladen.clear()
  if (i18n.language) geladen.add(i18n.language)
}

function browsersprache(): Sprachcode {
  const vomBrowser = navigator.language.slice(0, 2)
  return SPRACHEN.some((s) => s.code === vomBrowser) ? (vomBrowser as Sprachcode) : 'de'
}

/** i18next mit **einer** Sprache hochfahren. Muss vor dem ersten Zeichnen laufen.
 *
 * ⚠️ **Vor dem Zeichnen, nicht nebenher.** Wer die Sprache nachlädt, während
 * React schon rendert, zeigt für einen Moment die rohen Schlüssel — und das
 * sieht aus wie eine kaputte Übersetzung, nicht wie eine langsame.
 */
export async function spracheHochfahren(): Promise<void> {
  let code = startsprache()
  let texte = await texteFuer(code)
  if (!texte) {
    code = browsersprache()
    texte = (await LADER[code as Sprachcode]()).default
  }
  geladen.add(code)

  await i18n.use(initReactI18next).init({
    resources: { [code]: { translation: texte } },
    lng: code,
    ...GRUNDEINSTELLUNG,
  })
  document.documentElement.lang = code
}

/** Die Sprache des Kontos (seit dem Kontenmodul am Konto, wie in nexnotes): nach der Anmeldung übernommen, wenn sie
 *  gesetzt ist und eine ist, die nexmail kann. */
export async function kontoSprache(code: string | undefined): Promise<void> {
  const roh = code ?? ''
  // Eine Sprache des Betreibers genau so, eine eingebaute am Sprachteil („de-AT“ ist Deutsch).
  const ziel = (await eigeneSprachen.knows(roh, EINGEBAUT)) ? roh : roh.slice(0, 2)
  if (!ziel || i18n.language === ziel || !(await eigeneSprachen.knows(ziel, EINGEBAUT))) return
  await spracheSetzen(ziel)
}

export async function spracheSetzen(code: string): Promise<void> {
  if (!(await nachladen(code))) return
  localStorage.setItem(GEMERKT, code)
  await i18n.changeLanguage(code)
  document.documentElement.lang = code
}

export default i18n
