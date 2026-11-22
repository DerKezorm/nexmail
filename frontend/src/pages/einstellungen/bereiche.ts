/* Die Bereiche der Einstellungen, aufgebaut wie in nexnotes.
 *
 * ⚠️ **Wer eine nex-App kennt, findet sich in der anderen zurecht.** Deshalb
 * dieselbe Gliederung wie nexnotes (`/settings/<bereich>`): links oben das
 * Konto, dann „Mein Konto" (Profil, Sicherheit, Darstellung, Benachrichtigungen,
 * Verbindungen), für den Betreiber „Server", ganz unten „Über nexmail".
 * Eigen ist nur die Gruppe „Mail" dazwischen: Postfächer, Regeln, Signaturen
 * und was sonst nur ein Mailprogramm hat.
 *
 * ⚠️ **Die Verwaltung ist keine eigene Seite mehr** (bis 0.30 ein Zahnrad in
 * der Leiste, nur für den Betreiber). Was der Anwendung gehört, steht als
 * Gruppe „Server" in denselben Einstellungen — die Frage „für mich oder für
 * alle?" beantwortet die Überschrift der Gruppe.
 *
 * ⚠️ **Die KI ebenso** (bis 0.30 ein Punkt in der Leiste, siehe `KiSeite.tsx`).
 * Riegel des Betreibers und eigener Zugang bleiben zusammen in EINEM Bereich.
 */
import type { LucideIcon } from 'lucide-react'
import {
  Bell,
  HardDrive,
  Inbox,
  Info,
  KeyRound,
  ListFilter,
  Mail,
  Palette,
  PenLine,
  Plane,
  Plug,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tag,
  UserRound,
  Users,
} from 'lucide-react'
import type { Ich } from '../../api/client'

export type Bereich =
  | 'profil'
  | 'sicherheit'
  | 'darstellung'
  | 'benachrichtigungen'
  | 'verbindungen'
  | 'postfaecher'
  | 'regeln'
  | 'signaturen'
  | 'abwesenheit'
  | 'schlagworte'
  | 'ki'
  | 'allgemein'
  | 'anmeldung'
  | 'mailversand'
  | 'speicher'
  | 'konten'
  | 'log'
  | 'ueber'

export type Gruppe = 'konto' | 'mail' | 'server'

export interface BereichDef {
  id: Bereich
  gruppe: Gruppe
  symbol: LucideIcon
}

/** In der Reihenfolge der Navigation. Die Texte stehen unter
 *  `einstellungen.bereiche.<id>.titel` und `.text`. */
export const BEREICHE: BereichDef[] = [
  { id: 'profil', gruppe: 'konto', symbol: UserRound },
  { id: 'sicherheit', gruppe: 'konto', symbol: ShieldCheck },
  { id: 'darstellung', gruppe: 'konto', symbol: Palette },
  { id: 'benachrichtigungen', gruppe: 'konto', symbol: Bell },
  { id: 'verbindungen', gruppe: 'konto', symbol: Plug },
  { id: 'postfaecher', gruppe: 'mail', symbol: Inbox },
  { id: 'regeln', gruppe: 'mail', symbol: ListFilter },
  { id: 'signaturen', gruppe: 'mail', symbol: PenLine },
  { id: 'abwesenheit', gruppe: 'mail', symbol: Plane },
  { id: 'schlagworte', gruppe: 'mail', symbol: Tag },
  { id: 'ki', gruppe: 'mail', symbol: Sparkles },
  { id: 'allgemein', gruppe: 'server', symbol: SlidersHorizontal },
  { id: 'anmeldung', gruppe: 'server', symbol: KeyRound },
  { id: 'mailversand', gruppe: 'server', symbol: Mail },
  { id: 'speicher', gruppe: 'server', symbol: HardDrive },
  { id: 'konten', gruppe: 'server', symbol: Users },
  { id: 'log', gruppe: 'server', symbol: ScrollText },
]

export const GRUPPEN: Gruppe[] = ['konto', 'mail', 'server']

/** „Über nexmail" steht unter den Gruppen, getrennt durch eine Linie. */
export const UEBER: BereichDef = { id: 'ueber', gruppe: 'server', symbol: Info }

/** Was dieses Konto öffnen darf.
 *
 * „Über nexmail" sieht jeder, wie in nexnotes (seit 22.11.2026); Schalter und
 * „Jetzt prüfen" darauf nur der Betreiber (`UeberPage`).
 * ⚠️ **KI für den Betreiber immer**, sonst nur mit `ki_erlaubt` — er muss den
 * Riegel finden, bevor irgendetwas eingeschaltet ist. */
export function bereicheFuer(ich: Ich | null): BereichDef[] {
  const betreiber = Boolean(ich?.ist_betreiber)
  return BEREICHE.filter((b) => {
    if (b.gruppe === 'server') return betreiber
    if (b.id === 'ki') return betreiber || Boolean(ich?.ki_erlaubt)
    return true
  })
}

export function ueberSichtbar(ich: Ich | null): boolean {
  return Boolean(ich)
}

/** Der Bereich, der wirklich gezeigt wird: Einer, den dieses Konto nicht
 *  öffnen darf (etwa nach einer Betreiber-Übergabe), wird zum Profil. */
export function erlaubterBereich(gewuenscht: Bereich, ich: Ich | null): Bereich {
  if (gewuenscht === 'ueber') return ueberSichtbar(ich) ? 'ueber' : 'profil'
  return bereicheFuer(ich).some((b) => b.id === gewuenscht) ? gewuenscht : 'profil'
}

export function bereichDef(id: Bereich): BereichDef {
  return id === 'ueber' ? UEBER : (BEREICHE.find((b) => b.id === id) ?? BEREICHE[0])
}
