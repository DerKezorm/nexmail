/* Die Lage eines Browsers gegenüber Benachrichtigungen — als Entscheidung.
 *
 * ⚠️ **Ein eigenes Modul, und der Grund ist der Testlauf.** Die Entscheidung
 * stand zuerst in `push.ts`. Das Modul zieht über `api/client` und `lib/basis`
 * das Dokument herein (`document.querySelector` beim Laden), und die schnelle
 * Prüfebene läuft ausdrücklich mit `environment: 'node'` und ohne jsdom. Der
 * Test scheiterte deshalb schon beim Import, nicht an einer Zusicherung.
 *
 * jsdom dafür nachzuziehen wäre ein weiteres Paket in der Lieferkette, das
 * nichts trägt. Eine Datei ohne Browser-Bezug kostet nichts.
 */

/** Warum es hier weitergeht oder nicht. Die Oberfläche übersetzt die Kennung. */
export type PushLage =
  | 'bereit' // erlaubt UND angemeldet
  | 'erlaubt_ohne_anmeldung' // erlaubt, aber der Server kennt dieses Gerät nicht
  | 'offen' // der Browser hat noch nicht gefragt
  | 'abgelehnt' // der Browser hat Nein — nur in seinen Einstellungen zurückzunehmen
  | 'unmoeglich' // dieser Browser kann kein Push
  | 'kein_home' // iOS ohne Home-Bildschirm
  | 'abgemeldet' // erlaubt, aber hier bewusst abgemeldet — kein stilles Nachmelden

/** Woraus sich die Lage ergibt. Als Werte, damit sie prüfbar bleibt. */
export interface Umstaende {
  /** Service Worker, PushManager und Notification sind alle da. */
  kannPush: boolean
  istApple: boolean
  /** Vom Home-Bildschirm gestartet, nicht als gewöhnlicher Reiter. */
  alsApp: boolean
  erlaubnis: NotificationPermission
  /** Es gibt ein Abonnement für dieses Gerät. */
  angemeldet: boolean
  /** Hier wurde bewusst abgemeldet. ⚠️ **Eigener Wert, nicht aus
   *  `angemeldet` abzuleiten:** „nicht angemeldet" heißt sonst zweierlei —
   *  „der Server kennt mich nicht (heile das)" und „ich will das nicht
   *  (lass es)" —, und genau diese Vermengung ist der Fehler. */
  abgemeldet: boolean
}

/** Die Entscheidung, ohne Browser.
 *
 * ⚠️ **„Erlaubt" und „angemeldet" sind zwei Dinge, und sie zu vermengen war
 * ein echter Fehler.** Am 03.09.2026 aus dem Betrieb gemeldet: Auf dem iPhone
 * stand „Erlaubt auf diesem Gerät", und die Seite bot nur noch eine
 * Probemeldung an. Die Erlaubnis lebt im Browser und überlebt alles; die
 * Anmeldung lebt im Server und ist nach einem Umzug, einem gelöschten
 * Browserzustand oder einer frischen Installation weg. Wer aus dem einen auf
 * das andere schließt, zeigt einen Knopf, der mit 400 antwortet, und
 * verschweigt, dass hier nie etwas ankommen wird.
 *
 * ⚠️ **Die Reihenfolge ist die der Wahrheit, nicht die der Bequemlichkeit.**
 * Fehlt die Schnittstelle, ist die Erlaubnis bedeutungslos; und auf einem
 * iPhone im gewöhnlichen Reiter liefert iOS auch mit erteilter Erlaubnis
 * nichts aus. Beides muss vor der Erlaubnis stehen, sonst nennt die Meldung
 * den nächstbesten Grund statt des wahren.
 */
export function lageAus(u: Umstaende): PushLage {
  if (!u.kannPush) return 'unmoeglich'
  if (u.istApple && !u.alsApp) return 'kein_home'
  if (u.erlaubnis === 'denied') return 'abgelehnt'
  if (u.erlaubnis !== 'granted') return 'offen'
  if (u.angemeldet) return 'bereit'
  /* ⚠️ **Erst hier, nach `angemeldet`.** Wer sich abmeldet und danach von
     einem anderen Gerät aus wieder anmeldet, ist angemeldet — der Merker
     dieses Browsers darf das nicht überstimmen. */
  return u.abgemeldet ? 'abgemeldet' : 'erlaubt_ohne_anmeldung'
}


/** Der Schlüssel des Merkers im `localStorage`.
 *
 * ⚠️ **Warum es ihn überhaupt braucht.** `abmelden()` nimmt das Abonnement weg
 * (`unsubscribe`), aber **nicht die Erlaubnis** — die kann eine Seite gar nicht
 * zurückgeben. `sicherstellen()` prüft nur die Erlaubnis und legt danach ein
 * neues Abonnement an. Wer sein eigenes Gerät aus der Liste entfernte, bekam es
 * deshalb im selben Klick zurück: Die Seite lädt danach neu, und das Nachmelden
 * ist der erste Schritt beim Laden.
 *
 * ⚠️ **Die Selbstheilung bleibt, und sie ist gewollt.** Nach einem Umzug, einem
 * gelöschten Browserzustand oder einer frisch aufgesetzten Installation soll
 * ein erlaubtes Gerät stillschweigend nachgemeldet werden — ohne den Merker
 * wüsste niemand, warum plötzlich nichts mehr ankommt. Unterschieden wird
 * deshalb nach der **Absicht**, nicht nach dem Zustand.
 *
 * ⚠️ **Je Browser, nicht je Konto.** Die Abmeldung gilt diesem Gerät; wer sich
 * woanders anmeldet, hat damit nichts zu tun. `localStorage` ist genau die
 * richtige Reichweite — dieselbe wie die der Erlaubnis, um die es geht.
 */
export const ABGEMELDET_SCHLUESSEL = 'nexmail.push.abgemeldet'
