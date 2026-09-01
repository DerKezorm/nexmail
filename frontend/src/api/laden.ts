/* Vom Server in die Formen, die die Oberfläche schon kennt.
 *
 * ⚠️ **Eine Schicht dazwischen, kein Durchgriff.** Die Bausteine der
 * Mail-Ansicht sind gegen `daten/typen.ts` gebaut und in der Attrappe
 * abgestimmt worden. Sie jetzt auf die Antwortformen des Servers umzuschreiben
 * hieße, jeden davon anzufassen — und dabei geht Abgestimmtes verloren. Also
 * wird hier übersetzt: eine Datei, eine Aufgabe.
 */
import { api } from './client'
import type { KontoZeile, OrdnerZeile } from './client'
import type { Anhang, Konto, Nachricht, Ordner, OrdnerRolle, Person, Postfachfarbe } from '../daten/typen'

interface ApiPerson {
  name: string
  adresse: string
}

interface ApiZeile {
  id: number
  konto_id: string
  ordner_id: number
  von: ApiPerson
  betreff: string
  anreisser: string
  datum: string
  gelesen: boolean
  markiert: boolean
  beantwortet: boolean
  hat_anhang: boolean
  strang_anzahl?: number
  strang_ungelesen?: number
  thread_key?: string
  groesse: number
}

interface ApiAnhang {
  id: number
  dateiname: string
  mime: string
  groesse: number
  inline: boolean
}

interface ApiVoll extends ApiZeile {
  an: ApiPerson[]
  kopie: ApiPerson[]
  html: string
  text: string
  geblockte_bilder: number
  anhaenge: ApiAnhang[]
}

function person(p: ApiPerson): Person {
  return { name: p.name, adresse: p.adresse }
}

function zeile(z: ApiZeile): Nachricht {
  return {
    id: String(z.id),
    kontoId: z.konto_id,
    ordnerId: String(z.ordner_id),
    von: person(z.von),
    an: [],
    betreff: z.betreff,
    anreisser: z.anreisser,
    koerper: '',
    datum: z.datum,
    gelesen: z.gelesen,
    markiert: z.markiert,
    beantwortet: z.beantwortet,
    // In der Liste steht nur, **ob** etwas dranhängt. Die Anhänge selbst
    // kommen erst beim Öffnen — sie liegen bis dahin gar nicht hier.
    anhaenge: z.hat_anhang ? [{ id: 'unbekannt', dateiname: '', groesse: 0, typ: '' }] : [],
    hatFremdbilder: false,
    strangAnzahl: z.strang_anzahl,
    strangUngelesen: z.strang_ungelesen,
    strangSchluessel: z.thread_key,
  }
}

export async function kontenLaden(): Promise<Konto[]> {
  const roh = await api.holen<KontoZeile[]>('/api/konten')
  return roh.map((k) => ({
    id: k.id,
    anzeigename: k.anzeigename,
    adresse: k.adresse,
    farbe: (k.farbe as Postfachfarbe) ?? 1,
    tags: k.tags ?? [],
  }))
}

export async function ordnerLaden(konten: Konto[]): Promise<Ordner[]> {
  const alle: Ordner[] = []
  for (const konto of konten) {
    const roh = await api.holen<OrdnerZeile[]>(`/api/konten/${konto.id}/ordner`)
    for (const o of roh) {
      if (!o.abonniert || !o.waehlbar) continue
      alle.push({
        // Die Kennung kommt vom Server als Zahl; die Oberfläche rechnet mit
        // Zeichenketten und wandelt beim Abfragen zurück.
        id: String(o.id),
        kontoId: konto.id,
        pfad: o.pfad,
        name: o.name,
        rolle: o.rolle as OrdnerRolle,
        // ⚠️ **Vom Server, nicht aus der geladenen Liste.** Die Oberfläche
        // hält nur die Nachrichten des offenen Ordners — wer daraus zählt,
        // zeigt bei allen anderen null.
        ungelesen: o.ungelesen ?? 0,
        anzahl: o.anzahl ?? 0,
      })
    }
  }
  return alle
}

export type Listenfilter = 'alle' | 'ungelesen' | 'markiert'

/** Wie viele Zeilen eine Seite hat.
 *
 * ⚠️ **Vorher waren es 200 und danach kam nichts mehr.** Kein Nachladen, kein
 * Blättern — an alles Ältere kam man nur noch über die Suche. Bei einem
 * Posteingang mit 1481 Nachrichten waren 1281 davon nicht erreichbar. Ein
 * Mail-Client, der an seine eigene Post nicht herankommt, ist im Kern kaputt.
 */
export const SEITE = 60

/** Der Merkpunkt, hinter dem weitergelesen wird. */
export function merkpunkt(n: Nachricht): string {
  return `${n.datum},${n.id}`
}

/** `ordnerId === null` heißt: alle Posteingänge. `nurMarkierte` überstimmt das
 *  und sucht postfachübergreifend. */
export async function nachrichtenLaden(
  ordnerId: number | null,
  filter: Listenfilter = 'alle',
  nurMarkierte = false,
  /** Auf diese Postfächer einschränken. Leer heißt: alle. */
  kontoIds: string[] = [],
  /** Weiterlesen hinter dieser Zeile — `<ISO-Datum>,<id>`. Leer heißt: von oben. */
  nach = '',
  grenze = SEITE,
  /** Einen Strang zu einer Zeile zusammenfassen. */
  gruppiert = false,
): Promise<Nachricht[]> {
  // ⚠️ **Gefiltert wird im Server.** Die Liste hier hält nur die neuesten 200
  // Zeilen — im Browser gefiltert fände „markiert" die Mail von vor drei
  // Monaten nie und meldete „keine".
  const frage = new URLSearchParams({ grenze: String(grenze) })
  if (nach) frage.set('nach', nach)
  if (gruppiert) frage.set('gruppiert', 'true')
  /* ⚠️ **Die Einschränkung geht mit zum Server**, sie wird nicht hier
     angewandt: Die Liste hält nur 200 Zeilen. Erst holen und dann aussieben
     hieße, bei vollem Posteingang drei Mails zu zeigen und zu behaupten, mehr
     gebe es nicht. Genau der Fehler, den `filter` weiter oben schon meidet. */
  if (kontoIds.length) frage.set('konto_ids', kontoIds.join(','))
  if (nurMarkierte) {
    frage.set('filter', 'markiert')
  } else {
    frage.set('filter', filter)
    if (ordnerId === null) frage.set('nur_posteingaenge', 'true')
    else frage.set('ordner_id', String(ordnerId))
  }
  const roh = await api.holen<ApiZeile[]>(`/api/nachrichten?${frage}`)
  return roh.map(zeile)
}

export async function ordnerAnlegen(
  kontoId: string,
  name: string,
  elternId: number | null,
): Promise<void> {
  await api.senden(`/api/konten/${kontoId}/ordner`, { name, eltern_id: elternId })
}

export async function ordnerEntfernen(kontoId: string, ordnerId: number): Promise<number> {
  const stand = await api.loeschen<{ nachrichten: number }>(
    `/api/konten/${kontoId}/ordner/${ordnerId}`,
  )
  return stand?.nachrichten ?? 0
}

export async function ordnerUmbenennen(
  kontoId: string,
  ordnerId: number,
  name: string,
): Promise<void> {
  await api.aendern(`/api/konten/${kontoId}/ordner/${ordnerId}`, { name })
}

export async function ordnerAlsGelesen(ordnerId: string): Promise<number> {
  const stand = await api.senden<{ bewegt: number }>(
    `/api/nachrichten/ordner/${ordnerId}/gelesen`,
    {},
  )
  return stand.bewegt
}

export interface Suchbefund {
  treffer: Nachricht[]
  /**
   * ⚠️ `false` heißt: Betreff und Absender wurden vollständig durchsucht, die
   * Texte nur, soweit sie schon geholt waren. Das **muss** in der Oberfläche
   * stehen — sonst schließt man aus null Treffern, dass es die Mail nicht
   * gibt.
   */
  vollstaendig: boolean
}

export async function suchen(
  text: string,
  bereich: 'ordner' | 'postfach' | 'alle',
  ordnerId: number | null,
  kontoId: string | null,
  beimAnbieter = false,
): Promise<Suchbefund> {
  const roh = await api.senden<{ treffer: ApiZeile[]; vollstaendig: boolean }>('/api/suche', {
    text,
    bereich,
    ordner_id: ordnerId,
    konto_id: kontoId,
    beim_anbieter: beimAnbieter,
  })
  return { treffer: roh.treffer.map(zeile), vollstaendig: roh.vollstaendig }
}

export interface VolleNachricht extends Nachricht {
  html: string
  text: string
  geblockteBilder: number
  echteAnhaenge: Anhang[]
}

export async function nachrichtLaden(id: string): Promise<VolleNachricht> {
  const roh = await api.holen<ApiVoll>(`/api/nachrichten/${id}`)
  return {
    ...zeile(roh),
    an: roh.an.map(person),
    kopie: roh.kopie.map(person),
    koerper: roh.html || `<pre>${escapen(roh.text)}</pre>`,
    html: roh.html,
    text: roh.text,
    geblockteBilder: roh.geblockte_bilder,
    hatFremdbilder: roh.geblockte_bilder > 0,
    echteAnhaenge: roh.anhaenge
      .filter((a) => !a.inline)
      .map((a) => ({
        id: String(a.id),
        dateiname: a.dateiname,
        groesse: a.groesse,
        typ: a.mime,
      })),
    anhaenge: roh.anhaenge
      .filter((a) => !a.inline)
      .map((a) => ({
        id: String(a.id),
        dateiname: a.dateiname,
        groesse: a.groesse,
        typ: a.mime,
      })),
  }
}

export async function bilderAnzeigen(id: string): Promise<string> {
  const antwort = await api.senden<{ html: string }>(`/api/nachrichten/${id}/bilder`, {})
  return antwort.html
}

export async function abgleichen(): Promise<{ neu: number; entfernt: number; ordner: number }> {
  return api.senden('/api/nachrichten/abgleichen', {})
}

/* Eine reine Textmail wird in <pre> gezeigt. Ohne Maskierung stünde darin
 * fremder Text, der wie HTML aussieht — und der Rahmen ist zwar abgeschottet,
 * aber es gibt keinen Grund, ihm zusätzlich Arbeit zu machen. */
function escapen(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

// --- Handeln ------------------------------------------------------------ //

export interface Rueckweg {
  konto_id: string
  quelle_pfad: string
  ziel_pfad: string
  message_ids: string[]
  text: string
}

export interface Zugergebnis {
  bewegt: number
  rueckweg: Rueckweg | null
}

export async function zug(
  weg: 'loeschen' | 'archivieren' | 'junk',
  ids: string[],
): Promise<Zugergebnis> {
  return api.senden(`/api/nachrichten/${weg}`, { ids: ids.map(Number) })
}

export async function verschieben(ids: string[], ordnerId: string): Promise<Zugergebnis> {
  return api.senden('/api/nachrichten/verschieben', {
    ids: ids.map(Number),
    ordner_id: Number(ordnerId),
  })
}

export async function zurueckholen(weg: Rueckweg): Promise<Zugergebnis> {
  return api.senden('/api/nachrichten/zurueck', weg)
}

export async function ordnerLeeren(ordnerId: string): Promise<Zugergebnis> {
  return api.senden(`/api/nachrichten/ordner/${Number(ordnerId)}/leeren`, {})
}

/** Alle Nachrichten eines Gesprächs — über alle Ordner, älteste zuerst.
 *
 * ⚠️ **Älteste zuerst**, anders als die Liste. Ein Gespräch liest man von
 * vorn; die Liste zeigt, was zuletzt passiert ist.
 */
export async function strangLaden(schluessel: string): Promise<Nachricht[]> {
  const roh = await api.holen<ApiZeile[]>(
    `/api/nachrichten/strang/${encodeURIComponent(schluessel)}`,
  )
  return roh.map(zeile)
}
