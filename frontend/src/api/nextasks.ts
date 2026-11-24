/* nextasks live (MAIL-2): Listen und Aufgaben, wie nexmails Server sie aus
 * nextasks holt. Nichts davon wird in nexmail gespeichert.
 *
 * ⚠️ **Ändern schickt nur Geändertes.** `aenderungen()` vergleicht mit dem
 * Stand beim Öffnen; was gleich blieb, geht nicht hinaus. So überschreibt
 * nexmail nie ein Feld, das jemand anderes inzwischen in nextasks geändert hat
 * (dort gewinnt je Feld die spätere Änderung).
 */
import { api } from './client'

export interface NextasksLage {
  verbunden: boolean
  verbindung_id: string
  name: string
  /** nextasks kennt die Mitglieder eines Bereichs (Zuständige wählen). */
  mitglieder: boolean
  fehler: string
  zeitzone: string
  /** Weitere nextasks-Verbindungen aus der Zeit vor MAIL-2; sie zählen nicht. */
  weitere: Array<{ id: string; name: string; adresse: string }>
}

export interface NtAbschnitt {
  id: string
  name: string
}

export interface NtListe {
  id: string
  name: string
  farbe: string
  symbol: string
  beschreibbar: boolean
  offen: number
  gewaehlt: boolean
  abschnitte: NtAbschnitt[]
}

export interface NtBereich {
  id: string
  name: string
  symbol: string
  ausgeblendet: boolean
  beschreibbar: boolean
  geteilt: boolean
  listen: NtListe[]
}

export interface NtPerson {
  id: number
  name: string
}

export interface NtMail {
  aufgabe_id: number
  nachricht_id: number | null
  konto_id: string
  betreff: string
  von_name: string
  von_adresse: string
  verwaist: boolean
}

export interface Fernaufgabe {
  id: string
  liste_id: string
  liste_name: string
  bereich_id: string
  bereich_name: string
  abschnitt_id: string | null
  abschnitt_name: string
  eltern_id: string | null
  titel: string
  notiz: string
  notiz_text: string
  url: string | null
  faellig_tag: string | null
  faellig_zeit: string | null
  wiederholung: string | null
  markiert: boolean
  prioritaet: number
  schlagworte: string[]
  zustaendige: NtPerson[]
  erledigt: boolean
  erledigt_am: string | null
  papierkorb: boolean
  teilaufgaben: { offen: number; gesamt: number }
  link: string | null
  beschreibbar: boolean
  mail: NtMail | null
  /** Nur im Einzelabruf. */
  teilaufgaben_liste?: Fernaufgabe[]
}

/** Was die Seitenleiste oben zeigt; `markiert` und `mir` gibt es nur mit nextasks. */
export type Sammlung = 'offen' | 'heute' | 'datum' | 'erledigt' | 'markiert' | 'mir'

/** Was sich an einer Aufgabe ändern lässt (AC-4). */
export interface Felder {
  titel?: string
  notiz?: string
  faellig_tag?: string | null
  faellig_zeit?: string | null
  prioritaet?: number
  markiert?: boolean
  schlagworte?: string[]
  zustaendige?: number[]
  liste_id?: string
  abschnitt_id?: string | null
  erledigt?: boolean
  papierkorb?: boolean
}

export function nextasksLage(): Promise<NextasksLage> {
  return api.holen<NextasksLage>('/api/nextasks/lage')
}

export async function nextasksListen(alle = false): Promise<NtBereich[]> {
  const raus = await api.holen<{ bereiche: NtBereich[] }>(`/api/nextasks/listen?alle=${alle}`)
  return raus.bereiche
}

export function listeWaehlen(listeId: string, gewaehlt: boolean): Promise<unknown> {
  return api.flicken(`/api/nextasks/listen/${encodeURIComponent(listeId)}`, { gewaehlt })
}

export async function fernaufgaben(wunsch: {
  liste?: string | null
  sammlung?: Sammlung
  suche?: string
}): Promise<Fernaufgabe[]> {
  const raus: Fernaufgabe[] = []
  let cursor: string | null = null
  // Seitenweise, höchstens zehn Seiten: mehr liest auf einem Bildschirm niemand (EC-9).
  for (let seite = 0; seite < 10; seite++) {
    const p = new URLSearchParams()
    if (wunsch.liste) p.set('liste', wunsch.liste)
    if (wunsch.sammlung) p.set('sammlung', wunsch.sammlung)
    if (wunsch.suche) p.set('suche', wunsch.suche)
    if (cursor) p.set('cursor', cursor)
    const antwort: { aufgaben: Fernaufgabe[]; weiter: string | null } = await api.holen(
      `/api/nextasks/aufgaben?${p.toString()}`,
    )
    raus.push(...antwort.aufgaben)
    cursor = antwort.weiter
    if (!cursor) break
  }
  return raus
}

export function fernaufgabe(id: string): Promise<Fernaufgabe> {
  return api.holen<Fernaufgabe>(`/api/nextasks/aufgaben/${encodeURIComponent(id)}`)
}

export function fernAnlegen(
  felder: Felder & {
    liste_id: string
    titel: string
    eltern_id?: string | null
    /** Einmal je Fenster: Ein zweiter Klick legt nichts Zweites an (EC-10). */
    anfrage?: string
  },
): Promise<Fernaufgabe> {
  return api.senden<Fernaufgabe>('/api/nextasks/aufgaben', felder)
}

export function fernAendern(id: string, felder: Felder): Promise<Fernaufgabe> {
  return api.flicken<Fernaufgabe>(`/api/nextasks/aufgaben/${encodeURIComponent(id)}`, felder)
}

export function fernLoeschen(id: string): Promise<unknown> {
  return api.loeschen(`/api/nextasks/aufgaben/${encodeURIComponent(id)}`)
}

export function mitglieder(bereichId: string): Promise<NtPerson[]> {
  return api.holen<NtPerson[]>(`/api/nextasks/bereiche/${encodeURIComponent(bereichId)}/mitglieder`)
}

/** Nur was sich gegenüber `vorher` geändert hat. */
export function aenderungen(vorher: Fernaufgabe, nachher: Required<Omit<Felder, 'erledigt' | 'papierkorb'>>): Felder {
  const raus: Felder = {}
  if (nachher.titel !== vorher.titel) raus.titel = nachher.titel
  if (nachher.notiz !== vorher.notiz) raus.notiz = nachher.notiz
  if ((nachher.faellig_tag || null) !== vorher.faellig_tag) raus.faellig_tag = nachher.faellig_tag || null
  // Ohne Tag keine Uhrzeit; nextasks leert sie mit dem Tag ohnehin.
  const zeit = nachher.faellig_tag ? nachher.faellig_zeit || null : null
  if (zeit !== vorher.faellig_zeit && nachher.faellig_tag) raus.faellig_zeit = zeit
  if (nachher.prioritaet !== vorher.prioritaet) raus.prioritaet = nachher.prioritaet
  if (nachher.markiert !== vorher.markiert) raus.markiert = nachher.markiert
  const sw = (a: string[]) => [...a].sort().join('\n')
  if (sw(nachher.schlagworte) !== sw(vorher.schlagworte)) raus.schlagworte = nachher.schlagworte
  const zs = (a: number[]) => [...a].sort((x, y) => x - y).join(',')
  if (zs(nachher.zustaendige) !== zs(vorher.zustaendige.map((z) => z.id))) raus.zustaendige = nachher.zustaendige
  if (nachher.liste_id !== vorher.liste_id) {
    raus.liste_id = nachher.liste_id
    raus.abschnitt_id = nachher.abschnitt_id
  } else if ((nachher.abschnitt_id || null) !== vorher.abschnitt_id) {
    raus.abschnitt_id = nachher.abschnitt_id || null
  }
  return raus
}

/** Schlagworte aus einem Feld „einkauf, mail“. */
export function schlagworteAus(text: string): string[] {
  return [...new Set(text.split(',').map((s) => s.trim()).filter(Boolean))]
}
