/* Serverdaten, die nexmail aus der Adresse erraet.
 *
 * ⚠️ **Nur iCloud ist geprueft.** Die Werte stammen aus Apples eigener
 * Anleitung (support.apple.com/102525, nachgesehen am 31.08.2026). Alle
 * anderen Eintraege sind aus dem Gedaechtnis und muessen in Stufe 1 gegen
 * die Seite des jeweiligen Anbieters gehalten werden, bevor sie jemandem
 * angezeigt werden. Deshalb steht an jedem, woher er kommt.
 *
 * Ab Stufe 1 kommt zusaetzlich die Autoconfig-Abfrage dazu; diese Liste
 * bleibt als Rueckfallebene fuer Anbieter, die keine anbieten.
 */

export type Verschluesselung = 'ssl' | 'starttls'

/** Woraus der Benutzername gebildet wird. Der Grund, warum iCloud so oft
 *  schiefgeht: Apple will bei IMAP etwas anderes als bei SMTP. */
export type Benutzerform = 'volle_adresse' | 'nur_name'

export interface Anbieter {
  id: string
  name: string
  /** Domaenen, an denen erkannt wird. */
  domaenen: string[]
  imap: { server: string; port: number; sicherheit: Verschluesselung; benutzer: Benutzerform }
  smtp: { server: string; port: number; sicherheit: Verschluesselung; benutzer: Benutzerform }
  /** Wird bei diesem Anbieter zwingend ein App-Passwort gebraucht? */
  appPasswort?: { noetig: true; wo: string }
  quelle: string
}

export const ANBIETER: Anbieter[] = [
  {
    id: 'icloud',
    name: 'iCloud',
    domaenen: ['icloud.com', 'me.com', 'mac.com'],
    // Die beiden Zeilen darunter sind der Grund fuer das ganze Anbieter-Profil:
    // Apple will beim Posteingang NUR den Namensteil und beim Postausgang die
    // vollstaendige Adresse. Wer beide gleich eintraegt, kann lesen aber nicht
    // senden - und iCloud meldet in beiden Faellen nur "Anmeldung
    // fehlgeschlagen", genau wie bei einem Tippfehler.
    imap: { server: 'imap.mail.me.com', port: 993, sicherheit: 'ssl', benutzer: 'nur_name' },
    smtp: { server: 'smtp.mail.me.com', port: 587, sicherheit: 'starttls', benutzer: 'volle_adresse' },
    appPasswort: { noetig: true, wo: 'account.apple.com' },
    quelle: 'support.apple.com/102525, nachgesehen 31.08.2026',
  },
  {
    id: 'gmx',
    name: 'GMX',
    domaenen: ['gmx.de', 'gmx.net', 'gmx.at', 'gmx.ch'],
    imap: { server: 'imap.gmx.net', port: 993, sicherheit: 'ssl', benutzer: 'volle_adresse' },
    smtp: { server: 'mail.gmx.net', port: 587, sicherheit: 'starttls', benutzer: 'volle_adresse' },
    quelle: 'ungeprueft — in Stufe 1 nachsehen',
  },
  {
    id: 'webde',
    name: 'WEB.DE',
    domaenen: ['web.de'],
    imap: { server: 'imap.web.de', port: 993, sicherheit: 'ssl', benutzer: 'volle_adresse' },
    smtp: { server: 'smtp.web.de', port: 587, sicherheit: 'starttls', benutzer: 'volle_adresse' },
    quelle: 'ungeprueft — in Stufe 1 nachsehen',
  },
  {
    id: 'mailbox',
    name: 'mailbox.org',
    domaenen: ['mailbox.org'],
    imap: { server: 'imap.mailbox.org', port: 993, sicherheit: 'ssl', benutzer: 'volle_adresse' },
    smtp: { server: 'smtp.mailbox.org', port: 587, sicherheit: 'starttls', benutzer: 'volle_adresse' },
    quelle: 'ungeprueft — in Stufe 1 nachsehen',
  },
  {
    id: 'gmail',
    name: 'Gmail',
    domaenen: ['gmail.com', 'googlemail.com'],
    imap: { server: 'imap.gmail.com', port: 993, sicherheit: 'ssl', benutzer: 'volle_adresse' },
    smtp: { server: 'smtp.gmail.com', port: 587, sicherheit: 'starttls', benutzer: 'volle_adresse' },
    appPasswort: { noetig: true, wo: 'myaccount.google.com' },
    quelle: 'ungeprueft — in Stufe 1 nachsehen',
  },
]

export function anbieterZu(adresse: string): Anbieter | null {
  const domaene = adresse.split('@')[1]?.toLowerCase().trim()
  if (!domaene) return null
  return ANBIETER.find((a) => a.domaenen.includes(domaene)) ?? null
}

export function benutzerAus(adresse: string, form: Benutzerform): string {
  return form === 'nur_name' ? (adresse.split('@')[0] ?? '') : adresse
}
