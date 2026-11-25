/* nexmails Seite der Kontenliste des Kontenmoduls (konten 0.3.9/0.3.10): was nexmails Server für den Betreiber kann,
 * nexmails Eigenes an den festen Plätzen des Fensters „Verwalten“ und seine Zeilen so, wie das Modul sie kennt.
 *
 * ⚠️ **Die Feldnamen der Schnittstelle bleiben** (`GET /api/benutzer`, `benutzername`, `ist_betreiber` …): Die Zeile
 * wird hier einmal auf `ListedAccount` abgebildet, nirgends sonst.
 */
import { profilbildAdresse } from '../components/Profilbild'
import type { AccountCaps, ListedAccount, ListedInvite, OwnAction } from '../vendor/nexkonten/konten'

/** Eine Zeile von `GET /api/benutzer`. */
export interface BenutzerZeile {
  id: string
  benutzername: string
  anzeigename: string
  ist_betreiber: boolean
  /** Eine Authenticator-App ist eingerichtet. */
  zwei_faktor_aktiv: boolean
  angelegt: string
  postfaecher: number
  ki_erlaubt: boolean
  /** Die Kennung im Anmeldemodul, für „Verknüpfung lösen“. */
  nummer: number
  /** Die Anmeldeanbieter, mit denen das Konto verknüpft ist (`id` die Verknüpfung). */
  anbieter: Array<{ id: number; slug: string; label: string }>
  kontaktadresse?: string
  adresse_doppelt?: boolean
  hat_kennwort?: boolean
  /** Seit der Kontenliste des Moduls. */
  kontaktadresse_zaehlt?: boolean
  passkeys?: number
  gesperrt?: boolean
  /** Wann eine Sitzung oder ein gekoppeltes Gerät zuletzt da war; `null`: keine läuft, also unbekannt. */
  zuletzt_gesehen?: string | null
  /** Der Stand des Profilbilds; `null` ohne Bild. */
  profilbild?: string | null
}

/** Eine offene Einladung von `GET /api/benutzer` (abgelaufene inbegriffen). */
export interface EinladungsZeile {
  id: string
  benutzername: string
  anzeigename: string
  adresse: string
  laeuft_ab: string
  abgelaufen: boolean
  /** Dasselbe unter dem Namen des Moduls (konten 0.3.10). */
  expired?: boolean
  /** Nur in der Antwort auf das Einladen: der Link, und ob er auch per Mail ging. */
  link?: string
  gemailt?: boolean
}

/** Was nexmails Server für den Betreiber kann (`ACCOUNT_CAPS`, Bestandsaufnahme vom 25.11.2026): Namen ändern,
 *  Adresse entfernen, Link für ein neues Passwort, zweiten Faktor zurücksetzen, Anbieter lösen, löschen. Keine Rollen
 *  (der Betreiber-Haken wandert, er wird übergeben), kein Sperren, kein „Überall abmelden“, kein Zurückholen. */
export const APP_CAPS: AccountCaps = {
  rename: true,
  roles: false,
  emailRemove: true,
  resetLink: true,
  factorReset: true,
  signOut: false,
  unlink: true,
  blocking: false,
  remove: true,
  restore: false,
}

/** Der Name von nexmails eigenem Knopf und Haken im Fenster „Verwalten“. */
export const UEBERGEBEN = 'handOver'
export const KI_ERLAUBT = 'aiAllowed'

/** nexmails Eigenes im Fenster „Verwalten“: „Betreiber übergeben“ in „Ändern“ vor „Adresse entfernen“, nicht am
 *  eigenen Konto; „KI erlaubt“ als Haken in „Rechte“, sofort gespeichert. */
export function eigenes(zeile: Pick<BenutzerZeile, 'ki_erlaubt'>): OwnAction[] {
  return [
    {
      name: UEBERGEBEN,
      label: 'verwaltung.betreiber_uebergeben_knopf',
      group: 'change',
      button: 'handOver',
      before: 'account.emailRemove',
      notSelf: true,
    },
    { name: KI_ERLAUBT, label: 'verwaltung.ki_erlaubt', group: 'rights', checked: zeile.ki_erlaubt },
  ]
}

/** Die Fassung für die Prüfungen der Vorlage (`APP_OWN`): ein Konto, dem KI erlaubt ist. */
export const APP_OWN: readonly OwnAction[] = eigenes({ ki_erlaubt: true })

/** Eine Zeile so, wie die Liste des Moduls sie kennt. */
export function alsKonto(zeile: BenutzerZeile, eigeneId: string | undefined): ListedAccount {
  const adresse = zeile.kontaktadresse ?? ''
  return {
    id: zeile.id,
    username: zeile.benutzername,
    displayName: zeile.anzeigename ?? '',
    email: adresse,
    ...(adresse ? { emailConfirmed: zeile.kontaktadresse_zaehlt ?? true } : {}),
    emailDuplicate: Boolean(zeile.adresse_doppelt),
    operator: zeile.ist_betreiber,
    self: zeile.id === eigeneId,
    hasPassword: zeile.hat_kennwort ?? true,
    authenticator: zeile.zwei_faktor_aktiv,
    passkeys: zeile.passkeys ?? 0,
    providers: zeile.anbieter.map((a) => ({ id: a.id, label: a.label })),
    locked: Boolean(zeile.gesperrt),
    // ⚠️ Ohne laufende Sitzung weiß nexmail nicht, wann jemand zuletzt da war: dann keine Angabe statt „Nie“.
    ...(zeile.zuletzt_gesehen ? { lastSeenAt: zeile.zuletzt_gesehen } : {}),
    picture: zeile.profilbild ? profilbildAdresse(zeile.id, zeile.profilbild) : null,
  }
}

/** Eine offene Einladung so, wie die Liste des Moduls sie kennt (abgelaufene bleiben, bis sie zurückgenommen sind). */
export function alsEinladung(e: EinladungsZeile): ListedInvite {
  return {
    id: e.id,
    displayName: e.anzeigename,
    email: e.adresse,
    username: e.benutzername,
    expiresAt: e.laeuft_ab,
    expired: e.expired ?? e.abgelaufen,
  }
}
