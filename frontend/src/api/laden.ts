/* Vom Server in die Formen, die die Oberfläche schon kennt.
 *
 * ⚠️ **Eine Schicht dazwischen, kein Durchgriff.** Die Bausteine der
 * Mail-Ansicht sind gegen `daten/typen.ts` gebaut und in der Attrappe
 * abgestimmt worden. Sie jetzt auf die Antwortformen des Servers umzuschreiben
 * hieße, jeden davon anzufassen — und dabei geht Abgestimmtes verloren. Also
 * wird hier übersetzt: eine Datei, eine Aufgabe.
 */
import { api } from './client'
import type { Wiederholung } from '../components/Wiederholungsfeld'
import type { KontoZeile, OrdnerZeile } from './client'
import type {
  Anhang,
  Konto,
  Nachricht,
  Ordner,
  OrdnerRolle,
  Person,
  Postfachfarbe,
  Schlagwort,
} from '../daten/typen'

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
  wichtigkeit?: string
  strang_anzahl?: number
  strang_ungelesen?: number
  thread_key?: string
  groesse: number
  schlagworte?: string[]
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
  absender_freigegeben: boolean
  faerbt_sich_selbst: boolean
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
    wichtigkeit:
      z.wichtigkeit === 'hoch' || z.wichtigkeit === 'niedrig' ? z.wichtigkeit : 'normal',
    // In der Liste steht nur, **ob** etwas dranhängt. Die Anhänge selbst
    // kommen erst beim Öffnen — sie liegen bis dahin gar nicht hier.
    anhaenge: z.hat_anhang ? [{ id: 'unbekannt', dateiname: '', groesse: 0, typ: '' }] : [],
    hatFremdbilder: false,
    strangAnzahl: z.strang_anzahl,
    strangUngelesen: z.strang_ungelesen,
    strangSchluessel: z.thread_key,
    schlagworte: z.schlagworte ?? [],
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
    aliase: k.aliase ?? [],
    stoerung: k.stoerung ?? '',
  }))
}

/** Die Ordner aller Postfaecher.
 *
 * ⚠️ **Nebenlaeufig, nicht nacheinander.** Bis zum 03.09.2026 stand hier
 * ein ``await`` in der Schleife: bei fuenf Postfaechern fuenf Umlaeufe
 * hintereinander, und das nach **jedem** Handgriff — ``stammLaden`` laeuft
 * nach jedem Verschieben, Loeschen, Archivieren und Lesen (27 Aufrufstellen in
 * ``App.tsx``). Gemessen am Entwicklungsstand mit vier Postfaechern: 40 ms
 * seriell gegen die Dauer des langsamsten Abrufs.
 *
 * ⚠️ **Die Reihenfolge bleibt die der Postfaecher.** ``Promise.all`` haelt
 * sie ein; wer die Ergebnisse in der Reihenfolge ihres Eintreffens anhaengte,
 * bekaeme einen Ordnerbaum, der bei jedem Laden anders sortiert ist.
 */
export async function ordnerLaden(konten: Konto[]): Promise<Ordner[]> {
  const antworten = await Promise.all(
    konten.map((konto) => api.holen<OrdnerZeile[]>(`/api/konten/${konto.id}/ordner`)),
  )

  const alle: Ordner[] = []
  for (const [i, konto] of konten.entries()) {
    for (const o of antworten[i]) {
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
  /** Nur Mails mit diesem Schlagwort-Atom. Leer heißt: alle. */
  schlagwort = '',
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
  /* ⚠️ **Auch der Schlagwort-Filter läuft im Server** — dieselbe Regel wie
     beim ungelesen-Filter: Im Browser gefiltert fände er die markierte Mail
     von vor drei Monaten nie und meldete „keine". */
  if (schlagwort) frage.set('schlagwort', schlagwort)
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
  /** Ist dieser Absender dauerhaft freigegeben? Dann bietet der Balken das
   *  nicht noch einmal an — und er erscheint ohnehin nicht, weil die Bilder
   *  schon drin sind. */
  absenderFreigegeben: boolean
  /** Legt die Mail eigene Farben fest? Dann rechnet sie mit hellem Grund. */
  faerbtSichSelbst: boolean
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
    absenderFreigegeben: roh.absender_freigegeben,
    faerbtSichSelbst: roh.faerbt_sich_selbst,
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

/* Die Bilder holen — der Server tut es, nicht der Browser.
 *
 * ⚠️ **Was zurückkommt, enthält keine fremde Adresse mehr.** Jedes Bild zeigt
 * auf `/api/bilder/<Marke>`; nur so kommt es an der Inhaltsregel vorbei, die
 * der abgeschottete Lesebereich erbt. Von 0.1.0 bis 0.3.0 stand hier die echte
 * Adresse, und der Knopf tat deshalb sichtbar nichts.
 *
 * `absenderMerken` ist der zweite Knopf im Hinweisbalken: „Immer von diesem
 * Absender". */
export async function bilderAnzeigen(id: string, absenderMerken = false): Promise<string> {
  const antwort = await api.senden<{ html: string }>(`/api/nachrichten/${id}/bilder`, {
    absender_merken: absenderMerken,
  })
  return antwort.html
}

/** Eine Absender-Freigabe zurücknehmen — der „Rückgängig" im Balken und der
 *  Papierkorb in den Einstellungen gehen beide hier durch. */
export async function absenderVergessen(adresse: string): Promise<void> {
  await api.senden('/api/einstellungen/bilder/absender/entfernen', { adresse })
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

// --- Schlagworte --------------------------------------------------------- //

export async function schlagworteLaden(): Promise<Schlagwort[]> {
  return api.holen<Schlagwort[]>('/api/schlagworte')
}

export async function schlagwortAnlegen(name: string): Promise<Schlagwort> {
  return api.senden<Schlagwort>('/api/schlagworte', { name })
}

/** Ein Schlagwort an Mails hängen oder von ihnen nehmen.
 *
 * ⚠️ Der Server schreibt es **erst als IMAP-Keyword zum Anbieter** und zieht
 * dann seine Datenbank nach — geht es dort nicht, ändert sich auch hier
 * nichts. Ein Server ohne eigene Keywords antwortet mit der Kennung
 * `schlagworte_nicht_unterstuetzt`; die Aufrufstelle übersetzt sie.
 */
export async function schlagwortSetzen(
  ids: string[],
  atom: string,
  setzen: boolean,
): Promise<void> {
  const pfad = `/api/nachrichten/schlagworte/${encodeURIComponent(atom)}`
  const koerper = { ids: ids.map(Number) }
  if (setzen) await api.senden(pfad, koerper)
  else await api.loeschen(pfad, koerper)
}

// --- Wiedervorlage -------------------------------------------------------- //

/** Ein wartender Wiedervorlage-Eintrag, Feldnamen wie beim Server.
 *  `nachricht_id` ist die **aktuelle** Zeile der Mail, frisch über die
 *  Message-ID nachgeschlagen — daran hängt die Aufwach-Marke in der Liste. */
export interface WiedervorlageEintrag {
  id: number
  konto_id: string
  nachricht_id: number | null
  message_id: string
  /** ISO-UTC — wann die Mail zurückkommt. */
  aufwachen: string
  zurueck_pfad: string
  betreff: string
}

export async function wiedervorlagenLaden(): Promise<WiedervorlageEintrag[]> {
  return api.holen<WiedervorlageEintrag[]>('/api/nachrichten/wiedervorlage')
}

/** Eine Mail bis zu einem Zeitpunkt weglegen.
 *
 * ⚠️ Der Server verschiebt sie **erst per IMAP** in den Ordner „Wiedervorlage"
 * und legt dann den Merker an — scheitert das Verschieben, entsteht keiner.
 * Zweimal weggelegt ersetzt den Eintrag, erzeugt keinen zweiten.
 */
export async function wiedervorlegen(
  nachrichtId: string,
  aufwachenIso: string,
): Promise<WiedervorlageEintrag> {
  return api.senden<WiedervorlageEintrag>('/api/nachrichten/wiedervorlage', {
    nachricht_id: Number(nachrichtId),
    aufwachen: aufwachenIso,
  })
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

/* --- Termin-Einladungen -------------------------------------------------- */

export interface EinladungPerson {
  name: string
  adresse: string
}

export interface Einladung {
  uid: string
  methode: string
  titel: string
  beschreibung: string
  ort: string
  /** ISO-8601 mit Zeitzone — oder `JJJJ-MM-TT` bei einem ganzen Tag. */
  beginn: string
  ende: string
  ganztaegig: boolean
  /** Gesetzt, wenn die Zeitzone der Einladung unbekannt war. Dann steht die
   *  Zeit so da, wie sie kam, und die Karte nennt den Namen dazu. */
  fremdeZeitzone: string
  wiederholtSich: boolean
  abgesagt: boolean
  organisator: EinladungPerson
  teilnehmer: EinladungPerson[]
  /** `zusage` | `vorbehalt` | `absage` — leer, solange nicht geantwortet. */
  antwort: string
  antwortAm: string | null
  /** Liegt der Termin schon in einem Kalender? */
  imKalender: boolean
}

interface ApiEinladung {
  uid: string
  methode: string
  titel: string
  beschreibung: string
  ort: string
  beginn: string
  ende: string
  ganztaegig: boolean
  fremde_zeitzone: string
  wiederholt_sich: boolean
  abgesagt: boolean
  organisator: EinladungPerson
  teilnehmer: EinladungPerson[]
  antwort: string
  antwort_am: string | null
  im_kalender?: boolean
}

function einladung(roh: ApiEinladung): Einladung {
  return {
    uid: roh.uid,
    methode: roh.methode,
    titel: roh.titel,
    beschreibung: roh.beschreibung,
    ort: roh.ort,
    beginn: roh.beginn,
    ende: roh.ende,
    ganztaegig: roh.ganztaegig,
    fremdeZeitzone: roh.fremde_zeitzone,
    wiederholtSich: roh.wiederholt_sich,
    abgesagt: roh.abgesagt,
    organisator: roh.organisator,
    teilnehmer: roh.teilnehmer,
    antwort: roh.antwort,
    antwortAm: roh.antwort_am,
    imKalender: Boolean(roh.im_kalender),
  }
}

/** Die Einladung in dieser Nachricht — `null`, wenn keine darin steckt. */
export async function einladungLaden(id: string): Promise<Einladung | null> {
  const roh = await api.holen<ApiEinladung | null>(`/api/termine/${id}`)
  return roh ? einladung(roh) : null
}

/** Zusagen, mit Vorbehalt zusagen oder absagen. */
export async function terminAntworten(
  id: string,
  antwort: 'zusage' | 'vorbehalt' | 'absage',
): Promise<Einladung> {
  return einladung(await api.senden<ApiEinladung>(`/api/termine/${id}/antwort`, { antwort }))
}

/* --- Umzug: Post hinein und hinaus ------------------------------------- */

export interface Umzugsstand {
  id: string
  dateiname: string
  laeuft: boolean
  /** Leer heißt: lief durch. Sonst der Satz, an dem er gescheitert ist. */
  fehler: string
  gelesen: number
  importiert: number
  uebersprungen: number
  ohneKennung: number
  fehlerJeMail: string[]
  fehlerGesamt: number
  abgeschnitten: boolean
  abgebrochen: boolean
}

interface ApiUmzugsstand {
  id: string
  dateiname: string
  laeuft: boolean
  fehler: string
  gelesen: number
  importiert: number
  uebersprungen: number
  ohne_kennung: number
  fehler_je_mail: string[]
  fehler_gesamt: number
  abgeschnitten: boolean
  abgebrochen: boolean
}

function umzugsstand(s: ApiUmzugsstand): Umzugsstand {
  return {
    id: s.id,
    dateiname: s.dateiname,
    laeuft: s.laeuft,
    fehler: s.fehler,
    gelesen: s.gelesen,
    importiert: s.importiert,
    uebersprungen: s.uebersprungen,
    ohneKennung: s.ohne_kennung,
    fehlerJeMail: s.fehler_je_mail,
    fehlerGesamt: s.fehler_gesamt,
    abgeschnitten: s.abgeschnitten,
    abgebrochen: s.abgebrochen,
  }
}

export async function postEinspielen(ordnerId: number, datei: File): Promise<Umzugsstand> {
  const formular = new FormData()
  formular.append('datei', datei)
  formular.append('ordner_id', String(ordnerId))
  return umzugsstand(await api.formular<ApiUmzugsstand>('/api/austausch/import', formular))
}

export async function umzugStand(id: string): Promise<Umzugsstand> {
  return umzugsstand(await api.holen<ApiUmzugsstand>(`/api/austausch/vorgang/${id}`))
}

/** Der gerade laufende Import — damit ein Neuladen der Seite ihn nicht verliert. */
export async function laufenderUmzug(): Promise<Umzugsstand | null> {
  const roh = await api.holen<ApiUmzugsstand | null>('/api/austausch/vorgang')
  return roh ? umzugsstand(roh) : null
}

export async function umzugAbbrechen(id: string): Promise<Umzugsstand> {
  return umzugsstand(
    await api.senden<ApiUmzugsstand>(`/api/austausch/vorgang/${id}/abbrechen`, {}),
  )
}

export interface Exportvorschau {
  /** Wie viele Nachrichten nexmail von diesem Ordner kennt. */
  bekannt: number
  /** Wie viele beim Anbieter liegen. */
  gesamt: number
  zipGrenze: number
}

export async function exportVorschau(ordnerId: number): Promise<Exportvorschau> {
  const roh = await api.holen<{ bekannt: number; gesamt: number; zip_grenze: number }>(
    `/api/austausch/vorschau/${ordnerId}`,
  )
  return { bekannt: roh.bekannt, gesamt: roh.gesamt, zipGrenze: roh.zip_grenze }
}

/* --- Kalender ---------------------------------------------------------- */

export interface KalenderZeile {
  id: string
  name: string
  farbe: Postfachfarbe
  sichtbar: boolean
  /** "" (nur hier) | "caldav" | "ics" */
  art: string
  herkunft: string
  nurLesen: boolean
  letzterFehler: string
}

/** Organisator oder Teilnehmer eines Termins. */
export interface Beteiligter {
  name: string
  adresse: string
  /** `NEEDS-ACTION` | `ACCEPTED` | `DECLINED` | `TENTATIVE` | … */
  antwort: string
  rolle: string
}

type ApiBeteiligter = Beteiligter

export interface TerminZeile {
  id: number
  kalenderId: string
  titel: string
  /** Minuten vor dem Beginn, **-1 heißt keine**. */
  erinnerung: number
  /** Der Beginn **dieses Vorkommens**, nicht der der Reihe. */
  beginn: string
  ende: string
  ganztaegig: boolean
  ort: string
  beschreibung: string
  ausReihe: boolean
  /** Kennung für die Übersetzung: `taeglich`, `woechentlich`, … */
  wiederholung: string
  /** Wochentage als `MO`/`TU`/… — die Oberfläche macht daraus Namen. */
  wiederholungTage: string[]
  wiederholungIntervall: number
  /** Dieselbe Regel, zerlegt für das **Formular**.
   *
   * ⚠️ **Nicht `wiederholung*` dafür nehmen.** Die Felder darüber sind für
   * einen SATZ gedacht: Bei „jedem ersten Donnerstag" melden sie `allgemein`
   * und **keine** Wochentage, weil „donnerstags" gelogen wäre. Ein Formular,
   * das damit gefüllt wird, zeigt „Keine" — und nimmt die Wiederholung beim
   * Speichern mit. */
  regel: Wiederholung
  /** ⚠️ Die Regel enthält etwas, das die Maske nicht abbildet — dann wird sie
   *  als Ganzes gehalten, nicht zerlegt angeboten. */
  regelFremd: boolean
  /** ⚠️ **Nur zum Anzeigen.** Beim Zurückschreiben bleiben sie unangetastet;
   *  wer sie ändern könnte, müsste auch einladen können. */
  organisator: Beteiligter | null
  teilnehmer: Beteiligter[]
  rrule: string
  ausEinladung: boolean
  /** Ob schon eine Einladung hinausgegangen ist — davon haengt ab, ob beim
   *  Loeschen nach einer Absage gefragt wird. */
  eingeladen: boolean
}

/** ``dieser`` gilt nur für dieses Vorkommen, ``folgende`` ab hier, ``alle``. */
export type Umfang = 'dieser' | 'folgende' | 'alle'

interface ApiKalender {
  id: string
  name: string
  farbe: number
  sichtbar: boolean
  art: string
  herkunft: string
  nur_lesen: boolean
  letzter_fehler: string
}

interface ApiTermin {
  id: number
  kalender_id: string
  titel: string
  beginn: string
  ende: string
  ganztaegig: boolean
  ort: string
  beschreibung: string
  aus_reihe: boolean
  wiederholung: string
  wiederholung_tage: string[]
  wiederholung_intervall: number
  regel_freq: string
  regel_intervall: number
  regel_tage: string[]
  regel_monatsart: string
  regel_ordinal: number
  regel_ende: string
  regel_anzahl: number
  regel_bis: string
  regel_fremd: boolean
  organisator: ApiBeteiligter | null
  teilnehmer: ApiBeteiligter[]
  rrule: string
  aus_einladung: boolean
  eingeladen: boolean
  erinnerung: number
}

function kalenderZeile(k: ApiKalender): KalenderZeile {
  return {
    id: k.id,
    name: k.name,
    farbe: (k.farbe as Postfachfarbe) ?? 1,
    sichtbar: k.sichtbar,
    art: k.art,
    herkunft: k.herkunft,
    nurLesen: k.nur_lesen,
    letzterFehler: k.letzter_fehler,
  }
}

function terminZeile(t: ApiTermin): TerminZeile {
  return {
    id: t.id,
    kalenderId: t.kalender_id,
    titel: t.titel,
    beginn: t.beginn,
    ende: t.ende,
    ganztaegig: t.ganztaegig,
    ort: t.ort,
    beschreibung: t.beschreibung,
    ausReihe: t.aus_reihe,
    wiederholung: t.wiederholung,
    wiederholungTage: t.wiederholung_tage ?? [],
    wiederholungIntervall: t.wiederholung_intervall ?? 1,
    regel: {
      freq: t.regel_freq ?? '',
      intervall: t.regel_intervall ?? 1,
      tage: t.regel_tage ?? [],
      monatsart: t.regel_monatsart ?? 'tag',
      ordinal: t.regel_ordinal ?? 1,
      endeArt: t.regel_ende ?? 'nie',
      anzahl: t.regel_anzahl || 10,
      bis: t.regel_bis ?? '',
    },
    regelFremd: t.regel_fremd ?? false,
    organisator: t.organisator ?? null,
    teilnehmer: t.teilnehmer ?? [],
    rrule: t.rrule,
    ausEinladung: t.aus_einladung,
    eingeladen: t.eingeladen ?? false,
    erinnerung: t.erinnerung ?? -1,
  }
}

export async function kalenderLaden(): Promise<KalenderZeile[]> {
  return (await api.holen<ApiKalender[]>('/api/kalender')).map(kalenderZeile)
}

export async function kalenderAnlegen(name: string, farbe = 0): Promise<KalenderZeile> {
  return kalenderZeile(await api.senden<ApiKalender>('/api/kalender', { name, farbe }))
}

export async function kalenderAendern(
  id: string,
  aenderung: { name?: string; farbe?: number; sichtbar?: boolean },
): Promise<KalenderZeile> {
  return kalenderZeile(await api.flicken<ApiKalender>(`/api/kalender/${id}`, aenderung))
}

export async function kalenderEntfernen(id: string): Promise<number> {
  const weg = await api.loeschen<{ termine: number }>(`/api/kalender/${id}`)
  return weg?.termine ?? 0
}

export async function termineLaden(
  von: Date,
  bis: Date,
  nurKalender?: string[],
): Promise<TerminZeile[]> {
  const frage = new URLSearchParams({ von: von.toISOString(), bis: bis.toISOString() })
  for (const id of nurKalender ?? []) frage.append('kalender', id)
  return (await api.holen<ApiTermin[]>(`/api/kalender/termine?${frage}`)).map(terminZeile)
}

export interface Terminwunsch {
  kalenderId: string
  titel: string
  beginn: string
  ende?: string
  ganztaegig?: boolean
  ort?: string
  beschreibung?: string
  rrule?: string
  /** Minuten vor dem Beginn, **-1 heißt keine**. */
  erinnerung?: number
  /** Wer eingeladen werden soll. ⚠️ Beim Ändern heißt `undefined`
   *  **unverändert** — nur eine wirklich mitgeschickte Liste lässt den Server
   *  die Teilnehmer im Original ersetzen. */
  teilnehmer?: { adresse: string; name: string }[]
  /** Unter welcher Adresse eingeladen wird. Der Server prüft sie gegen die
   *  Postfächer; ein Kalender gehört zu keinem. */
  absender?: string
}

/** Eine fällige Erinnerung, wie das Sammelfenster sie zeigt. */
export interface FaelligeErinnerung {
  id: number
  terminId: number
  titel: string
  ort: string
  kalender: string
  farbe: Postfachfarbe
  beginn: string
  ganztaegig: boolean
  vorlauf: number
}

interface ApiErinnerung {
  id: number
  termin_id: number
  titel: string
  ort: string
  kalender: string
  farbe: number
  beginn: string
  ganztaegig: boolean
  vorlauf: number
}

export async function erinnerungenLaden(): Promise<FaelligeErinnerung[]> {
  return (await api.holen<ApiErinnerung[]>('/api/erinnerungen/faellig')).map((e) => ({
    id: e.id,
    terminId: e.termin_id,
    titel: e.titel,
    ort: e.ort,
    kalender: e.kalender,
    farbe: (e.farbe as Postfachfarbe) ?? 1,
    beginn: e.beginn,
    ganztaegig: e.ganztaegig,
    vorlauf: e.vorlauf,
  }))
}

export async function erinnerungErledigt(id: number): Promise<void> {
  await api.senden(`/api/erinnerungen/${id}/erledigt`, {})
}

export async function erinnerungSchlummern(id: number, minuten: number): Promise<void> {
  await api.senden(`/api/erinnerungen/${id}/schlummern`, { minuten })
}

/** Die Einladung zu einem Termin verschicken.
 *
 * ⚠️ **Ein eigener Aufruf, kein Nebeneffekt des Speicherns.** Es ist die
 * zweite Stelle, an der nexmail von sich aus Post an Fremde schickt; sie
 * gehoert hinter eine ausdrueckliche Handlung.
 */
export async function einladungVersenden(terminId: number): Promise<number> {
  const antwort = await api.senden<{ empfaenger: number }>(
    `/api/kalender/termine/${terminId}/einladen`,
    {},
  )
  return antwort.empfaenger
}

/** Termine nach Titel, Ort und Beschreibung suchen.
 *
 * ⚠️ **Gesucht wird im Server.** Wer alles holt und dann aussiebt, findet nur,
 * was zufaellig schon geladen war — dieselbe Regel wie bei der
 * Nachrichtenliste.
 */
export async function termineSuchen(
  wort: string,
  kalenderIds: string[],
): Promise<{ treffer: TerminZeile[]; abgeschnitten: boolean }> {
  const frage = new URLSearchParams({ q: wort })
  for (const id of kalenderIds) frage.append('kalender', id)
  const roh = await api.holen<{ treffer: ApiTermin[]; abgeschnitten: boolean }>(
    `/api/kalender/suche?${frage}`,
  )
  return { treffer: roh.treffer.map(terminZeile), abgeschnitten: roh.abgeschnitten }
}

export async function terminAnlegen(wunsch: Terminwunsch): Promise<TerminZeile> {
  return terminZeile(
    await api.senden<ApiTermin>('/api/kalender/termine', {
      kalender_id: wunsch.kalenderId,
      titel: wunsch.titel,
      beginn: wunsch.beginn,
      ende: wunsch.ende ?? null,
      ganztaegig: wunsch.ganztaegig ?? false,
      ort: wunsch.ort ?? '',
      beschreibung: wunsch.beschreibung ?? '',
      rrule: wunsch.rrule ?? '',
      erinnerung: wunsch.erinnerung ?? -1,
      teilnehmer: wunsch.teilnehmer ?? [],
      absender: wunsch.absender ?? '',
    }),
  )
}

export async function terminAendern(
  id: number,
  aenderung: Partial<Omit<Terminwunsch, 'kalenderId'>> & {
    umfang?: Umfang
    /** Der Beginn des angeklickten Vorkommens — ohne ihn geht „nur dieser" nicht. */
    vorkommen?: string
  },
): Promise<TerminZeile> {
  return terminZeile(
    await api.flicken<ApiTermin>(`/api/kalender/termine/${id}`, {
      titel: aenderung.titel ?? null,
      beginn: aenderung.beginn ?? null,
      ende: aenderung.ende ?? null,
      ganztaegig: aenderung.ganztaegig ?? null,
      ort: aenderung.ort ?? null,
      beschreibung: aenderung.beschreibung ?? null,
      rrule: aenderung.rrule ?? null,
      // ⚠️ `null` heißt **unverändert** — nur ein wirklich mitgeschickter
      // Wert ersetzt den `VALARM` im Original. Sonst bliebe von einem fremden
      // Alarm nichts übrig, sobald jemand den Titel ändert.
      erinnerung: aenderung.erinnerung ?? null,
      // ⚠️ ``null`` heisst hier **unveraendert** — siehe oben.
      teilnehmer: aenderung.teilnehmer ?? null,
      absender: aenderung.absender ?? null,
      umfang: aenderung.umfang ?? 'alle',
      vorkommen: aenderung.vorkommen ?? null,
    }),
  )
}

export async function terminEntfernen(
  id: number,
  umfang: Umfang = 'alle',
  vorkommen?: string,
  absagen = false,
): Promise<void> {
  const frage = new URLSearchParams({ umfang })
  if (vorkommen) frage.set('vorkommen', vorkommen)
  // ⚠️ Nur mitschicken, wenn wirklich abgesagt werden soll. Der Server nimmt
  // das als Erlaubnis, Post an Fremde zu verschicken.
  if (absagen) frage.set('absagen', 'true')
  await api.loeschen(`/api/kalender/termine/${id}?${frage}`)
}

export interface GefundenerKalender {
  url: string
  name: string
  /** Steht schon in der Spalte. ⚠️ Ein zweites Mal verbinden hiesse: jeder
   *  Termin doppelt, und beim Entfernen einer der beiden Zeilen verschwindet
   *  ein Termin, den man gerade offen hatte. */
  schon_verbunden?: boolean
}

export async function kalenderPruefen(zugang: {
  art: string
  adresse?: string
  benutzer: string
  passwort: string
  /** Statt eines Passworts: eine erteilte Zustimmung (Google). */
  oauthZugangId?: string
}): Promise<GefundenerKalender[]> {
  return api.senden<GefundenerKalender[]>('/api/kalender/pruefen', {
    art: zugang.art,
    adresse: zugang.adresse ?? '',
    benutzer: zugang.benutzer,
    passwort: zugang.passwort,
    oauth_zugang_id: zugang.oauthZugangId ?? '',
  })
}

export async function kalenderVerbinden(wunsch: {
  art: string
  adresse?: string
  benutzer: string
  passwort: string
  oauthZugangId?: string
  auswahl: GefundenerKalender[]
}): Promise<KalenderZeile[]> {
  const roh = await api.senden<ApiKalender[]>('/api/kalender/verbinden', {
    art: wunsch.art,
    adresse: wunsch.adresse ?? '',
    benutzer: wunsch.benutzer,
    passwort: wunsch.passwort,
    oauth_zugang_id: wunsch.oauthZugangId ?? '',
    auswahl: wunsch.auswahl,
  })
  return roh.map(kalenderZeile)
}

export async function kalenderAbonnieren(
  url: string,
  name: string,
  farbe = 0,
): Promise<KalenderZeile> {
  return kalenderZeile(await api.senden<ApiKalender>('/api/kalender/abo', { url, name, farbe }))
}

export interface Abgleichbericht {
  neu: number
  geaendert: number
  entfernt: number
  hochgeladen: number
  /** Je Kalender eine Kennung — die Oberfläche übersetzt sie. */
  fehler: Record<string, string>
}

export async function kalenderAbgleichen(): Promise<Abgleichbericht> {
  return api.senden<Abgleichbericht>('/api/kalender/abgleichen', {})
}

/** Den Termin einer Einladung in einen Kalender übernehmen. */
export async function terminUebernehmen(
  nachrichtId: string,
  kalenderId = '',
): Promise<Einladung> {
  return einladung(
    await api.senden<ApiEinladung>(`/api/termine/${nachrichtId}/uebernehmen`, {
      kalender_id: kalenderId,
    }),
  )
}
