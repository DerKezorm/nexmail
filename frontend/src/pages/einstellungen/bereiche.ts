/* Die Bereiche der Einstellungen nach dem Bauplan „Einstellungen" (nexlore, Development/nexapps/Baupläne), im Gerüst
 * des Bausatzes ui 1.1.0 (`SettingsNav`, `SettingsPage`).
 *
 * ⚠️ **Wer eine nex-App kennt, findet sich in der anderen zurecht.** Deshalb dieselben Gruppen und Adressen wie überall
 * (`/settings/<slug>`, englische Slugs): „Mein Konto" (Profil, Sicherheit, Darstellung, nexmails eigene Bereiche
 * Kalender und Adressbücher und KI, Benachrichtigungen, Verbindungen), nexmails eigene Gruppe „Mail" (Postfächer,
 * Regeln, Signaturen, Abwesenheit, Schlagworte), „Server" nur für Betreiber (Allgemein, Verbindungen, Anmeldung, Mail,
 * Speicher und Sicherung, KI-Anbieter, Konten, Log) und abgesetzt „Über nexmail" für jeden.
 *
 * Server › Verbindungen (`server-connections`, E67, ui 1.2.1) hält „Andere nex-Apps“ und „Schnittstellen“, die vorher
 * unter Allgemein standen: `/settings/general#nex-apps` und `#interfaces` führen mit ihrem Anker dorthin.
 *
 * ⚠️ **Die deutschen Namen von vorher bleiben gültig** (`ALTE_NAMEN`): `/settings/postfaecher`,
 * `/einstellungen/regeln` und jeder Aufruf mit einem alten Namen führt dauerhaft auf den englischen. Die Antwort des
 * Anmeldeanbieters nach dem Verknüpfen (`/konto/sicherheit`) bleibt, wie sie ist (`lib/kontorueckweg.ts`).
 */
import { CalendarDays, Inbox, ListFilter, PenLine, Plane, Tag } from 'lucide-react'

import type { GeneralPart, IconLike } from '../../vendor/nexui'
import type { Ich } from '../../api/client'

export type Bereich =
  | 'profile'
  | 'security'
  | 'appearance'
  | 'calendars'
  | 'ai'
  | 'notifications'
  | 'connections'
  | 'mailboxes'
  | 'rules'
  | 'signatures'
  | 'out-of-office'
  | 'tags'
  | 'general'
  | 'server-connections'
  | 'sign-in'
  | 'mail'
  | 'storage'
  | 'ai-provider'
  | 'accounts'
  | 'log'
  | 'about'

export type Gruppe = 'account' | 'mail' | 'server'

export interface BereichDef {
  id: Bereich
  gruppe: Gruppe
  symbol: IconLike
  /** Ein Bereich nur von nexmail: Titel und Zeile unter `einstellungen.bereiche.<id>` (sonst aus dem Bausatz). */
  eigen?: boolean
}

/** In der Reihenfolge der Navigation (Bauplan, „Reihenfolge Mein Konto" und „Reihenfolge Server"). */
export const BEREICHE: BereichDef[] = [
  { id: 'profile', gruppe: 'account', symbol: 'UserRound' },
  { id: 'security', gruppe: 'account', symbol: 'ShieldCheck' },
  { id: 'appearance', gruppe: 'account', symbol: 'Palette' },
  { id: 'calendars', gruppe: 'account', symbol: CalendarDays, eigen: true },
  { id: 'ai', gruppe: 'account', symbol: 'Sparkles', eigen: true },
  { id: 'notifications', gruppe: 'account', symbol: 'Bell' },
  { id: 'connections', gruppe: 'account', symbol: 'Plug' },
  { id: 'mailboxes', gruppe: 'mail', symbol: Inbox, eigen: true },
  { id: 'rules', gruppe: 'mail', symbol: ListFilter, eigen: true },
  { id: 'signatures', gruppe: 'mail', symbol: PenLine, eigen: true },
  { id: 'out-of-office', gruppe: 'mail', symbol: Plane, eigen: true },
  { id: 'tags', gruppe: 'mail', symbol: Tag, eigen: true },
  { id: 'general', gruppe: 'server', symbol: 'SlidersHorizontal' },
  { id: 'server-connections', gruppe: 'server', symbol: 'Plug' },
  { id: 'sign-in', gruppe: 'server', symbol: 'KeyRound' },
  { id: 'mail', gruppe: 'server', symbol: 'Mail' },
  { id: 'storage', gruppe: 'server', symbol: 'HardDrive' },
  { id: 'ai-provider', gruppe: 'server', symbol: 'Sparkles' },
  { id: 'accounts', gruppe: 'server', symbol: 'Users' },
  { id: 'log', gruppe: 'server', symbol: 'ScrollText' },
]

export const GRUPPEN: Gruppe[] = ['account', 'mail', 'server']

/** ui 1.1.3 (U-3): die Karten, die nexmail unter Server › Allgemein zeigt, in ihrer Reihenfolge (`ServerAllgemein`);
 *  der Untertitel nennt nur sie. Die Karte „Zeitzone des Servers“ ist nexmails eigene und hat kein Wort im Satz.
 *  „Andere nex-Apps“ und „Schnittstellen“ stehen seit E67 unter Server › Verbindungen. */
export const ALLGEMEIN_TEILE: readonly GeneralPart[] = ['features', 'languages']

/** Die Karten, die Server › Allgemein für Server › Verbindungen verlassen haben (E67), nach ihrem Anker. */
const AUS_ALLGEMEIN = new Set(['#nex-apps', '#interfaces'])

/** „Über nexmail" steht unter den Gruppen, getrennt durch eine Linie. */
export const UEBER: BereichDef = { id: 'about', gruppe: 'account', symbol: 'Info' }

/** Die Namen der Bereiche bis zum Bauplan „Einstellungen" (deutsch) und ihr Bereich heute. */
export const ALTE_NAMEN: Record<string, Bereich> = {
  profil: 'profile',
  sicherheit: 'security',
  darstellung: 'appearance',
  benachrichtigungen: 'notifications',
  verbindungen: 'connections',
  kalender: 'calendars',
  postfaecher: 'mailboxes',
  regeln: 'rules',
  signaturen: 'signatures',
  abwesenheit: 'out-of-office',
  schlagworte: 'tags',
  ki: 'ai',
  allgemein: 'general',
  anmeldung: 'sign-in',
  mailversand: 'mail',
  speicher: 'storage',
  konten: 'accounts',
  ueber: 'about',
}

const ALLE = new Set<string>([...BEREICHE.map((b) => b.id), UEBER.id])

/** Ein Name (neu oder alt) als Bereich, sonst null. */
export function bereichVon(name: string | null | undefined): Bereich | null {
  if (!name) return null
  if (ALLE.has(name)) return name as Bereich
  return ALTE_NAMEN[name] ?? null
}

/** Was dieses Konto öffnen darf.
 *
 * „Über nexmail" sieht jeder; Schalter und „Jetzt nachsehen" darauf nur der Betreiber.
 * ⚠️ **KI (persönlich) für den Betreiber immer**, sonst nur mit `ki_erlaubt`: Er muss den Riegel finden, bevor
 * irgendetwas eingeschaltet ist. Der Riegel selbst steht seit dem Bauplan unter Server › KI-Anbieter. */
export function bereicheFuer(ich: Ich | null): BereichDef[] {
  const betreiber = Boolean(ich?.ist_betreiber)
  return BEREICHE.filter((b) => {
    if (b.gruppe === 'server') return betreiber
    if (b.id === 'ai') return betreiber || Boolean(ich?.ki_erlaubt)
    return true
  })
}

export function ueberSichtbar(ich: Ich | null): boolean {
  return Boolean(ich)
}

/** Der Bereich, der wirklich gezeigt wird: Einer, den dieses Konto nicht öffnen darf (etwa nachdem es kein Betreiber
 *  mehr ist), wird zum Profil. */
export function erlaubterBereich(gewuenscht: Bereich, ich: Ich | null): Bereich {
  if (gewuenscht === 'about') return ueberSichtbar(ich) ? 'about' : 'profile'
  return bereicheFuer(ich).some((b) => b.id === gewuenscht) ? gewuenscht : 'profile'
}

export function bereichDef(id: Bereich): BereichDef {
  return id === 'about' ? UEBER : (BEREICHE.find((b) => b.id === id) ?? BEREICHE[0])
}

/** Die Adresse eines Bereichs (ohne Vorbau; `appPfad` setzt ihn davor). Ohne Bereich die Liste (Handy). */
export function pfadVon(bereich: Bereich | null): string {
  return bereich ? `/settings/${bereich}` : '/settings'
}

/**
 * Was eine Adresse über die Einstellungen sagt: `null` (keine Adresse der Einstellungen), `{ liste: true }`
 * (`/settings` allein: die Liste auf dem Handy, das Profil daneben auf breiter Seite) oder `{ bereich, ersetzen }`,
 * wobei `ersetzen` heißt, dass die Adresse ein alter Name war und auf den neuen umgeschrieben wird (Suche und Anker
 * bleiben). `/einstellungen` und `/einstellungen/<alter Name>` führen ebenso hierher.
 *
 * E67: Allgemein mit dem Anker einer umgezogenen Karte (`#nex-apps`, `#interfaces`: das „Einrichten“ der Karten von
 * vorher, gespeicherte Links, der Link aus einer Partner-App) führt nach Server › Verbindungen. Beides sind Bereiche
 * nur des Betreibers; wer keiner ist, landet wie bei Allgemein auf dem Profil (`erlaubterBereich`).
 */
export function bereichAusPfad(pfad: string, anker = ''): { liste: true } | { bereich: Bereich; ersetzen: boolean } | null {
  const treffer = /^\/(settings|einstellungen)(?:\/([^/?#]+))?\/?$/.exec(pfad)
  if (!treffer) return null
  const [, wurzel, name] = treffer
  if (!name) return wurzel === 'settings' ? { liste: true } : { bereich: 'profile', ersetzen: true }
  const bereich = bereichVon(decodeURIComponent(name))
  if (!bereich) return { bereich: 'profile', ersetzen: true }
  if (bereich === 'general' && AUS_ALLGEMEIN.has(anker)) return { bereich: 'server-connections', ersetzen: true }
  return { bereich, ersetzen: wurzel !== 'settings' || name !== bereich }
}
