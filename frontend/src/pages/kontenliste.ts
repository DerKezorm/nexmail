/* nexmails Seite der Kontenliste des Kontenmoduls (konten 0.3.9/0.3.10): was nexmails Server für den Betreiber kann,
 * nexmails Eigenes an den festen Plätzen des Fensters „Verwalten“ und seine Zeilen so, wie das Modul sie kennt.
 *
 * ⚠️ **Die Feldnamen der Schnittstelle bleiben** (`GET /api/benutzer`, `benutzername`, `ist_betreiber` …): Die Zeile
 * wird hier einmal auf `ListedAccount` abgebildet, nirgends sonst.
 */
import { profilbildAdresse } from '../components/Profilbild'
import { capsOf, type AccountCaps, type ListedAccount, type ListedInvite, type OwnAction } from '../vendor/nexkonten/konten'

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
  /** konten 1.1.0: vom Betreiber gesperrt seit, gelöscht am, endgültig weg am (ISO; `null` nicht). */
  gesperrt_seit?: string | null
  geloescht_am?: string | null
  endgueltig_am?: string | null
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

/** Was nexmails Server für den Betreiber kann: Namen ändern, Adresse entfernen, Link für ein neues Passwort, zweiten
 *  Faktor zurücksetzen, Anbieter lösen (nexmails eigene, wie vor konten 1.1.0), dazu seit konten 1.1.0 überall gleich
 *  Rollen (mehrere Betreiber), Sperren, Löschen mit 30 Tagen Zurückholen und „KI erlaubt“ (`capsOf`). Kein „Überall
 *  abmelden“. „Betreiber übergeben“ fällt weg (Bauplan „Einstellungen“). */
export const APP_CAPS: AccountCaps = capsOf('nexmail', {
  rename: true,
  emailRemove: true,
  resetLink: true,
  factorReset: true,
  signOut: false,
  unlink: true,
})

/** nexmail hat seit konten 1.1.0 nichts Eigenes mehr im Fenster „Verwalten“: „KI erlaubt“ ist ein Recht des Moduls. */
export function eigenes(): OwnAction[] {
  return []
}

/** Die Fassung für die Prüfungen der Vorlage (`APP_OWN`). */
export const APP_OWN: readonly OwnAction[] = eigenes()

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
    blocked: Boolean(zeile.gesperrt_seit || zeile.geloescht_am),
    blockedAt: zeile.gesperrt_seit ?? null,
    deletedAt: zeile.geloescht_am ?? null,
    purgeAt: zeile.endgueltig_am ?? null,
    rights: zeile.ki_erlaubt ? ['ai'] : [],
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
