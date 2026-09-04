/* Web Push im Browser — Erlaubnis holen, anmelden, abmelden.
 *
 * ⚠️ **Drei Dinge müssen zugleich stimmen, und sie fühlen sich für den
 * Benutzer alle gleich an.** Der Browser muss Push können, er muss die
 * Erlaubnis erteilt haben, und der Service Worker muss laufen. Fehlt eines,
 * passiert nichts — deshalb gibt jede Funktion hier einen benannten Grund
 * zurück und nicht `false`.
 */
import { ABGEMELDET_SCHLUESSEL } from './pushlage'
import { api } from '../api/client'
import { appPfad } from './basis'

/* Die Entscheidung selbst wohnt in `pushlage.ts` — ohne Browser-Bezug, damit
   die schnelle Pruefebene sie ohne jsdom pruefen kann. Hier steht nur, was
   wirklich einen Browser braucht. */
export type { PushLage, Umstaende } from './pushlage'
import { lageAus } from './pushlage'
import type { PushLage } from './pushlage'
export { lageAus }

export interface Anmeldung {
  endpunkt: string
  p256dh: string
  auth: string
}

/** Ob dieser Browser überhaupt in Frage kommt. */
export function moeglich(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/* ⚠️ **iOS liefert Push nur an Seiten auf dem Home-Bildschirm.** Safari zeigt
   im gewöhnlichen Reiter zwar `PushManager` an, aber `Notification.requestPermission`
   führt zu nichts — und sagt auch nicht, warum. Ohne diese Prüfung tippt
   jemand am iPhone auf „Erlauben", nichts passiert, und er hält nexmail für
   kaputt. */
function alsAppGestartet(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as { standalone?: boolean }).standalone === true
  )
}

/** Die Lage dieses Browsers, jetzt.
 *
 * ⚠️ **Asynchron, und das muss sie sein:** Ob dieses Gerät angemeldet ist,
 * steht im Service Worker und nicht in einer Eigenschaft von `window`.
 */
export async function lage(): Promise<PushLage> {
  const kannPush = moeglich()
  return lageAus({
    kannPush,
    istApple: /iPad|iPhone|iPod/.test(navigator.userAgent),
    alsApp: alsAppGestartet(),
    erlaubnis: kannPush ? Notification.permission : 'default',
    angemeldet: (await vorhandene()) !== null,
    abgemeldet: abgemeldet(),
  })
}

/** Den Service Worker registrieren — mehrfach aufrufbar. */
export async function arbeiter(): Promise<ServiceWorkerRegistration> {
  /* ⚠️ **`scope` wird ausdrücklich gesetzt.** Ein Worker bekommt sonst den
     Geltungsbereich seines eigenen Verzeichnisses; unter einem Vorbau wäre das
     zwar zufällig richtig, aber ohne ihn stünde der Worker an der Wurzel und
     zwei nexmail-Installationen auf derselben Domain überschrieben einander. */
  const wurzel = `${appPfad('/')}/`.replace(/\/+$/, '/')
  return navigator.serviceWorker.register(appPfad('/sw.js'), { scope: wurzel })
}

function alsAnmeldung(abo: PushSubscription): Anmeldung {
  const roh = abo.toJSON() as { endpoint?: string; keys?: Record<string, string> }
  return {
    endpunkt: roh.endpoint ?? '',
    p256dh: roh.keys?.p256dh ?? '',
    auth: roh.keys?.auth ?? '',
  }
}

/* Der Schlüssel kommt als base64url vom Server, `subscribe` will Bytes. */
function alsBytes(base64url: string): Uint8Array {
  const gepolstert = base64url.padEnd(base64url.length + ((4 - (base64url.length % 4)) % 4), '=')
  const roh = atob(gepolstert.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(roh, (z) => z.charCodeAt(0))
}

/** Die Anmeldung dieses Browsers, falls es eine gibt. */
export async function vorhandene(): Promise<Anmeldung | null> {
  if (!moeglich() || Notification.permission !== 'granted') return null
  const reg = await navigator.serviceWorker.getRegistration(appPfad('/sw.js'))
  const abo = await reg?.pushManager.getSubscription()
  return abo ? alsAnmeldung(abo) : null
}

/** Erlaubnis holen, anmelden, beim Server eintragen.
 *
 * ⚠️ **Der Browser fragt genau einmal.** Ein „Nein" lässt sich von hier aus
 * nie wieder aufheben — nur in den Website-Einstellungen des Browsers. Diese
 * Funktion darf deshalb nur aus einem Klick heraus laufen, nie beim Laden der
 * Seite: Eine Nachfrage, die aus dem Nichts kommt, klickt man weg, und danach
 * ist die Funktion für dieses Gerät dauerhaft zu.
 */
export async function anmelden(): Promise<Anmeldung> {
  if (!moeglich()) throw new Error('push_unmoeglich')

  /* ⚠️ **Kein `await` vor dieser Zeile.** Safari verlangt, dass die Nachfrage
     in derselben Aufgabe wie der Klick läuft; ein Umweg über eine Zusage
     davor, und sie kommt gar nicht erst hoch. */
  const erlaubnis = await Notification.requestPermission()
  if (erlaubnis === 'denied') throw new Error('push_abgelehnt')
  /* ⚠️ **„default" ist nicht „denied".** Manche Browser, iOS voran, geben die
     Nachfrage still zurück, ohne sie zu zeigen. Das als Ablehnung zu
     verbuchen hiesse: Der Knopf tut nichts und sagt nichts. */
  if (erlaubnis !== 'granted') throw new Error('push_keine_antwort')

  /* ⚠️ **Der Merker faellt hier, vor `sicherstellen()`.** Eine bewusste
     Neuanmeldung hebt eine bewusste Abmeldung auf — sonst gaebe der Knopf
     „Wieder anmelden" ohne jede Meldung auf, weil `sicherstellen()` den
     Merker sieht und null liefert. */
  merken(false)

  const daten = await sicherstellen()
  if (daten === null) throw new Error('push_anmeldung_gescheitert')
  return daten
}

/** Dafür sorgen, dass ein Browser mit erteilter Erlaubnis auch angemeldet ist.
 *
 * ⚠️ **Fragt nichts und darf deshalb beim Laden laufen.** Nur
 * `requestPermission` braucht einen Klick; `subscribe` mit längst erteilter
 * Erlaubnis nicht. Ohne diese Stelle bleibt ein Gerät für immer stumm, dessen
 * Erlaubnis noch steht, dessen Abonnement aber weg ist — nach einem Löschen
 * der Browserdaten, nach einem Serverumzug, oder weil der Server neu
 * aufgesetzt wurde und seine Tabelle leer ist. Die Erlaubnis überlebt das
 * alles, die Anmeldung nicht.
 */
export async function sicherstellen(): Promise<Anmeldung | null> {
  if (!moeglich() || Notification.permission !== 'granted') return null
  /* ⚠️ **Wer sich hier abgemeldet hat, wird nicht nachgemeldet.** Sonst
     macht das Nachmelden die Abmeldung im selben Klick wieder rückgängig —
     die Seite lädt danach neu, und dies ist der erste Schritt beim Laden. */
  if (abgemeldet()) return null

  const reg = await arbeiter()
  await navigator.serviceWorker.ready

  const { oeffentlicher_schluessel } = await api.holen<{ oeffentlicher_schluessel: string }>(
    '/api/push/schluessel',
  )

  /* ⚠️ **Ein vorhandenes Abonnement wird wiederverwendet, nicht ersetzt.**
     `subscribe` wirft, wenn schon eines mit einem anderen Schlüssel besteht —
     und das passiert wirklich, nämlich nach einem Serverumzug. */
  const abo =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: alsBytes(oeffentlicher_schluessel) as BufferSource,
    }))

  const daten = alsAnmeldung(abo)
  /* ⚠️ **Immer melden, auch bei einem vorhandenen Abonnement.** Der Server
     kennt es womöglich nicht; er legt dieselbe Adresse kein zweites Mal an. */
  await api.senden('/api/push/anmelden', daten)
  return daten
}

/** Dieses Gerät abmelden — im Browser **und** im Server.
 *
 * ⚠️ **Beides, und in dieser Reihenfolge.** Bleibt das Abonnement im Browser
 * stehen, meldet er sich beim nächsten Öffnen sofort wieder an, und der
 * Schalter wirkt kaputt.
 */
/** Steht der Merker, dass hier bewusst abgemeldet wurde? */
export function abgemeldet(): boolean {
  try {
    return localStorage.getItem(ABGEMELDET_SCHLUESSEL) === '1'
  } catch {
    /* Privater Modus, gesperrter Speicher: Dann gilt „nicht abgemeldet", also
       die Selbstheilung. Der schlechtere der beiden Fälle wäre, ein Gerät
       stumm zu lassen, dessen Besitzer nie abgemeldet hat. */
    return false
  }
}

function merken(wert: boolean): void {
  try {
    if (wert) localStorage.setItem(ABGEMELDET_SCHLUESSEL, '1')
    else localStorage.removeItem(ABGEMELDET_SCHLUESSEL)
  } catch {
    /* siehe oben */
  }
}

export async function abmelden(anmeldungId: number): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration(appPfad('/sw.js'))
  const abo = await reg?.pushManager.getSubscription()
  await abo?.unsubscribe()
  await api.loeschen(`/api/push/geraete/${anmeldungId}`)
  /* ⚠️ **Zuletzt, nicht zuerst.** Bricht das Abmelden ab, soll der Merker
     nicht stehen — sonst wäre das Gerät angemeldet und meldete sich nie
     wieder nach. */
  merken(true)
}
