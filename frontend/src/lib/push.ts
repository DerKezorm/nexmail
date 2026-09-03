/* Web Push im Browser — Erlaubnis holen, anmelden, abmelden.
 *
 * ⚠️ **Drei Dinge müssen zugleich stimmen, und sie fühlen sich für den
 * Benutzer alle gleich an.** Der Browser muss Push können, er muss die
 * Erlaubnis erteilt haben, und der Service Worker muss laufen. Fehlt eines,
 * passiert nichts — deshalb gibt jede Funktion hier einen benannten Grund
 * zurück und nicht `false`.
 */
import { api } from '../api/client'
import { appPfad } from './basis'

/** Warum es hier nicht weitergeht. Die Oberfläche übersetzt die Kennung. */
export type PushLage =
  | 'bereit' // erlaubt und angemeldet
  | 'offen' // der Browser hat noch nicht gefragt
  | 'abgelehnt' // der Browser hat Nein — nur in seinen Einstellungen zurückzunehmen
  | 'unmoeglich' // dieser Browser kann kein Push
  | 'kein_home' // iOS ohne Home-Bildschirm

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
function iosOhneHomeBildschirm(): boolean {
  const apfel = /iPad|iPhone|iPod/.test(navigator.userAgent)
  if (!apfel) return false
  const alsApp =
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as { standalone?: boolean }).standalone === true
  return !alsApp
}

export function lage(): PushLage {
  if (!moeglich()) return 'unmoeglich'
  if (iosOhneHomeBildschirm()) return 'kein_home'
  if (Notification.permission === 'granted') return 'bereit'
  if (Notification.permission === 'denied') return 'abgelehnt'
  return 'offen'
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

  const erlaubnis = await Notification.requestPermission()
  if (erlaubnis !== 'granted') throw new Error('push_abgelehnt')

  const reg = await arbeiter()
  await navigator.serviceWorker.ready

  const { oeffentlicher_schluessel } = await api.holen<{ oeffentlicher_schluessel: string }>(
    '/api/push/schluessel',
  )

  /* ⚠️ **Eine vorhandene Anmeldung wird wiederverwendet, nicht ersetzt.**
     `subscribe` wirft, wenn schon eine mit einem anderen Schlüssel besteht —
     und das passiert wirklich, nämlich nach einem Serverumzug. */
  const abo =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: alsBytes(oeffentlicher_schluessel) as BufferSource,
    }))

  const daten = alsAnmeldung(abo)
  await api.senden('/api/push/anmelden', daten)
  return daten
}

/** Dieses Gerät abmelden — im Browser **und** im Server.
 *
 * ⚠️ **Beides, und in dieser Reihenfolge.** Bleibt das Abonnement im Browser
 * stehen, meldet er sich beim nächsten Öffnen sofort wieder an, und der
 * Schalter wirkt kaputt.
 */
export async function abmelden(anmeldungId: number): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration(appPfad('/sw.js'))
  const abo = await reg?.pushManager.getSubscription()
  await abo?.unsubscribe()
  await api.loeschen(`/api/push/geraete/${anmeldungId}`)
}
