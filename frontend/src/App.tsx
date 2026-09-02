/* nexmail — die Anwendung.
 *
 * Hier läuft der Zustand der Oberfläche zusammen. Seit Stufe 2 kommen die
 * Daten vom Server; die erfundenen Inhalte der Attrappe sind weg.
 *
 * ⚠️ **Was den Server verändert, wird auch dort verändert.** „Gelesen" und
 * „markiert" gehen als IMAP-Flag hinaus, bevor sie hier stehen. Eine
 * Anwendung, die das nur lokal merkt, macht ihrem Besitzer etwas vor: Auf dem
 * Telefon steht die Mail weiter ungelesen da, und beim nächsten Abgleich
 * springt sie hier zurück.
 *
 * Das gilt seit Stufe 3 auch für Verschieben, Archivieren und Löschen: Sie
 * gehen als IMAP-Befehl hinaus, und erst danach verschwindet die Zeile hier.
 * Geht es auf dem Server nicht, ändert sich auch hier nichts.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Archive,
  ChevronsDownUp,
  Clock,
  CornerUpLeft,
  CornerUpRight,
  Flag,
  ListChecks,
  FolderInput,
  FolderPlus,
  FolderX,
  Paperclip,
  PenLine,
  Plus,
  Printer,
  Mail,
  MailOpen,
  ReplyAll,
  ShieldAlert,
  SlidersHorizontal,
  Star,
  StarOff,
  Tag,
  Trash2,
} from 'lucide-react'
import { Kopfbanner } from './components/Kopfbanner'
import { NavRail } from './components/NavRail'
import type { Ansicht } from './components/NavRail'
import { UeberPage } from './pages/UeberPage'
import { Kopfleiste } from './components/Kopfleiste'
import type { Suchbereich } from './components/Kopfleiste'
import { Kontextmenue } from './components/Kontextmenue'
import { useNachfrage } from './components/Nachfrage'
import type { MenueEintrag } from './components/Kontextmenue'
import { VerfassenFenster } from './components/VerfassenFenster'
import type { Sendedaten, Verfassart } from './components/VerfassenFenster'
import type { Ziel } from './components/Ordnerspalte'
import { Lesebereich } from './components/Lesebereich'
import { MailPage } from './pages/MailPage'
import { AufgabenPage } from './pages/AufgabenPage'
import { KontaktePage } from './pages/KontaktePage'
import { EinstellungenPage } from './pages/EinstellungenPage'
import { Verwaltung } from './pages/Verwaltung'
import type { VerwaltungsReiter } from './pages/Verwaltung'
import type { Reiter } from './pages/EinstellungenPage'
import type { Ich } from './api/client'
import type { Suchbefund } from './api/laden'
import { api, ApiFehler } from './api/client'
import {
  abgleichen,
  SEITE,
  merkpunkt,
  kontenLaden,
  nachrichtLaden,
  strangLaden,
  nachrichtenLaden,
  ordnerLaden,
  ordnerAnlegen,
  ordnerEntfernen,
  ordnerUmbenennen,
  ordnerAlsGelesen,
  ordnerLeeren,
  schlagwortAnlegen,
  schlagwortSetzen,
  schlagworteLaden,
  suchen as ladenSuchen,
  verschieben,
  wiedervorlagenLaden,
  wiedervorlegen,
  zug,
  zurueckholen,
} from './api/laden'
import type { Rueckweg, VolleNachricht, WiedervorlageEintrag } from './api/laden'
import type { Ausgangseintrag, Konto, Nachricht, Ordner, Schlagwort } from './daten/typen'
import { Schlagwortmarke } from './components/Schlagwortmarke'
import { useGemerkt, useSchmal } from './lib/haken'
import { WISCH_LINKS_VORGABE, WISCH_RECHTS_VORGABE } from './lib/wischen'
import type { WischAktion } from './lib/wischen'
import { nachrichtDrucken } from './lib/drucken'
import type { Listenfilter } from './api/laden'
import { zeitzoneSetzen } from './lib/format'

type Modus = 'dark' | 'light'

interface AppProps {
  modus: Modus
  aufModus: (m: Modus) => void
  ich: Ich | null
  /** Den angemeldeten Benutzer neu holen — nach jeder Änderung an ihm. */
  ichNeuLaden?: () => void
  aufAbmelden: () => void
}

/** Wie lange eine Nachricht im Lesebereich stehen muss, bis sie als gelesen
 *  gilt. Outlooks Vorgabe. Einstellbar wird das später — der Wert steht
 *  deshalb hier oben und nicht mitten im Code. */
/** Vorgabe, bis jemand etwas anderes einstellt: zwei Sekunden. */
const GELESEN_NACH_VORGABE = 2

/* Die festen Zeitpunkte der Wiedervorlage — Ortszeit rein, ISO-UTC raus,
 * dasselbe Muster wie „Später senden" im Verfassen-Fenster. */

function heute18(): Date {
  const d = new Date()
  d.setHours(18, 0, 0, 0)
  return d
}

function morgen8(): Date {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(8, 0, 0, 0)
  return d
}

function naechsterMontag8(): Date {
  const d = new Date()
  // getDay(): So=0 … Sa=6. „Nächsten Montag" heißt nie heute — wer es am
  // Montagmorgen wählt, meint den in einer Woche.
  const tage = (8 - d.getDay()) % 7 || 7
  d.setDate(d.getDate() + tage)
  d.setHours(8, 0, 0, 0)
  return d
}

interface Menuelage {
  x: number
  y: number
  eintraege: MenueEintrag[]
}

export default function App({ modus, aufModus, ich, ichNeuLaden, aufAbmelden }: AppProps) {
  const { t, i18n } = useTranslation()
  const schmal = useSchmal()

  const [ansicht, setAnsicht] = useState<Ansicht>('mail')
  const [verwaltungsReiter, setVerwaltungsReiter] = useState<VerwaltungsReiter>('protokoll')
  const [ziel, setZiel] = useState<Ziel>({ typ: 'alle' })
  const [gewaehlt, setGewaehlt] = useState<string | null>(null)
  // Alle / nur ungelesene. Gemerkt, weil man selten wechselt und sich sonst
  // jedes Mal neu wundert, wo die Mails geblieben sind.
  const [listenfilter, setListenfilter] = useGemerkt<Listenfilter>('nexmail.filter', 'alle')
  /* Das gewählte Schlagwort. Leer heißt: alle Postfächer.
     ⚠️ **Hier oben, nicht in der Ordnerspalte.** Es beschränkt auch „Alle
     Posteingänge" und „Markierte", und die holt diese Ebene beim Server.
     Gemerkt: Wer morgens auf „arbeit" stellt, will nicht nach jedem Neuladen
     wieder umschalten. */
  const [gruppe, setGruppe] = useGemerkt('nexmail.gruppe', '')
  /* Wann eine offene Nachricht als gelesen gilt, in Sekunden.
     0 = sofort, −1 = nur von Hand. Eingestellt unter Darstellung. */
  const [gelesenNach] = useGemerkt<number>('nexmail.gelesen_nach', GELESEN_NACH_VORGABE)
  /* Gespräche zusammenfassen.
     ⚠️ **Vorgabe aus.** Falsch gruppiert steckt eine Mail in einem
     zugeklappten Strang, und man merkt es erst, wenn man sie sucht — deshalb
     erst einschalten, wenn man der Gruppierung an echter Post traut. */
  const [gruppiert, setGruppiert] = useGemerkt<boolean>('nexmail.gruppiert', false)
  /* Wie viele Aufgaben offen sind — für die Zahl an der Leiste.
     ⚠️ **Eine Aufgabenliste, die man erst sieht, wenn man hinklickt, wird
     vergessen.** Dann hätte man sie sich sparen können. */
  const [offeneAufgaben, setOffeneAufgaben] = useState(0)
  const aufgabenZaehlen = useCallback(async () => {
    try {
      const alle = await api.holen<Array<{ erledigt: string | null }>>('/api/aufgaben')
      setOffeneAufgaben(alle.filter((a) => !a.erledigt).length)
    } catch {
      // Die Zahl ist Beiwerk. Ein Fehler hier darf nicht die Mail-Ansicht
      // stören — die Aufgabenseite selbst meldet ihn deutlich genug.
    }
  }, [])

  useEffect(() => {
    void aufgabenZaehlen()
  }, [aufgabenZaehlen])

  /* Die wartenden Wiedervorlage-Eintraege. Daran haengen die Zahl an der
     Zeile des Wiedervorlage-Ordners und die Aufwach-Marken in der Liste. */
  const [wiedervorlagen, setWiedervorlagen] = useState<WiedervorlageEintrag[]>([])
  const wiedervorlagenNachsehen = useCallback(async () => {
    try {
      setWiedervorlagen(await wiedervorlagenLaden())
    } catch {
      // Zahl und Marken sind Beiwerk — der alte Bestand bleibt stehen, wie
      // bei den Aufgaben.
    }
  }, [])

  useEffect(() => {
    void wiedervorlagenNachsehen()
  }, [wiedervorlagenNachsehen])

  /* Der Postausgang — geplante und liegen gebliebene Sendungen. Die Zeile in
     der Ordnerspalte erscheint nur, wenn hier etwas liegt. */
  const [ausgaenge, setAusgaenge] = useState<Ausgangseintrag[]>([])
  const ausgangLaden = useCallback(async () => {
    try {
      setAusgaenge(await api.holen<Ausgangseintrag[]>('/api/verfassen/ausgang'))
    } catch {
      // ⚠️ Der alte Bestand bleibt stehen, wie bei den Postfächern: Eine
      // misslungene Auffrischung darf nicht wie ein geleerter Ausgang
      // aussehen — dann glaubte man, die geplante Mail sei draußen.
    }
  }, [])

  useEffect(() => {
    void ausgangLaden()
  }, [ausgangLaden])

  const [mehrLaedt, setMehrLaedt] = useState(false)
  const [amEnde, setAmEnde] = useState(false)
  /* ⚠️ **Eine Sperre, die sofort greift.** `mehrLaedt` steht erst nach dem
     nächsten Zeichnen; der Beobachter am Fuß feuert schneller und schöbe
     dieselbe Seite zweimal an. */
  const mehrLaedtRef = useRef(false)
  const [suche, setSuche] = useState('')
  const [bereich, setBereich] = useState<Suchbereich>('ordner')
  const [befund, setBefund] = useState<Suchbefund | null>(null)
  const [suchtLaeuft, setSuchtLaeuft] = useState(false)
  const suchUhr = useRef<number | undefined>(undefined)
  // Für welche Eingabe die laufende Suche gestartet wurde. Antworten zu einer
  // älteren Eingabe werden verworfen — sonst überschreibt eine langsame
  // Serversuche das Ergebnis der schnelleren, die danach kam.
  const suchtFuer = useRef('')

  const [konten, setKonten] = useState<Konto[]>([])
  const [ordner, setOrdner] = useState<Ordner[]>([])
  /* Die Schlagwort-Definitionen — Marken, Menü und Filterzeile hängen daran.
     Geladen mit dem Stamm: Der Abgleich kann fremde Atome mitbringen, und
     die sollen ohne F5 erscheinen. */
  const [schlagworte, setSchlagworte] = useState<Schlagwort[]>([])
  /* Das gewählte Schlagwort der Filterzeile (Atom). Leer heißt: alle.
     ⚠️ Gefiltert wird im **Server** — derselbe Grund wie beim
     ungelesen-Filter, siehe CLAUDE.md. */
  const [schlagwortFilter, setSchlagwortFilter] = useGemerkt('nexmail.schlagwort', '')
  const [nachrichten, setNachrichten] = useState<Nachricht[]>([])
  /* Spiegel des Bestands für Rückrufe, die den Zustand nur LESEN wollen.
     ⚠️ Nicht im `setNachrichten`-Rückruf nachsehen: React darf ihn zweimal
     ausführen, und ein Zähler, der dabei zweimal springt, ist falsch. */
  const nachrichtenRef = useRef<Nachricht[]>([])
  useEffect(() => {
    nachrichtenRef.current = nachrichten
  }, [nachrichten])
  const [offene, setOffene] = useState<VolleNachricht | null>(null)
  const [offeneLaedt, setOffeneLaedt] = useState(false)
  const [gleichtAb, setGleichtAb] = useState(false)

  const [menue, setMenue] = useState<Menuelage | null>(null)
  const [mehrfach, setMehrfach] = useState<string[]>([])
  // Eine Handlung, die nicht ging, und der Satz dazu. Verschwindet von
  // selbst — eine Meldung, die man wegklicken muss, wird weggeklickt.
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [stoerung, setStoerung] = useState('')
  // Aus welchem Postfach gerade eine Nachricht gezogen wird.
  const [ziehtAus, setZiehtAus] = useState('')
  const stoerUhr = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!stoerung) return
    window.clearTimeout(stoerUhr.current)
    stoerUhr.current = window.setTimeout(() => setStoerung(''), 6000)
    return () => window.clearTimeout(stoerUhr.current)
  }, [stoerung])

  const [rueckgaengig, setRueckgaengig] = useState<{ text: string; weg: Rueckweg } | null>(null)
  const rueckUhr = useRef<number | undefined>(undefined)

  /* „Senden rückholen": solange der Aufschub läuft, liegt die Nachricht im
     Ausgang und die Leiste unten bietet „Rückgängig" an. `daten` ist der
     Inhalt aus dem Verfassen-Fenster — er bleibt hier im Speicher, damit das
     Fenster nach dem Rückholen sofort wieder gefüllt aufgeht, statt den
     Umweg über den vom Abbruch angelegten Entwurf zu nehmen. */
  const [sendeRueck, setSendeRueck] = useState<{
    ausgangId: string
    bis: number
    daten: Sendedaten
  } | null>(null)
  const [sendeRest, setSendeRest] = useState(0)

  // Aus dem Reiter „Darstellung". Sie liegen im Browser, weil sie zum Gerät
  // gehören — siehe Darstellung.tsx.
  const [dichte] = useGemerkt<'kompakt' | 'normal'>('nexmail.dichte', 'normal')
  /* Wischen in der schmalen Ansicht — die Vorgabe folgt den Tasten:
     links = Loeschen (Entf), rechts = Archivieren (E). */
  const [wischLinks] = useGemerkt<WischAktion>('nexmail.wisch_links', WISCH_LINKS_VORGABE)
  const [wischRechts] = useGemerkt<WischAktion>('nexmail.wisch_rechts', WISCH_RECHTS_VORGABE)
  const [anreisserZeigen] = useGemerkt<boolean>('nexmail.anreisser', true)
  const [punkteZeigen] = useGemerkt<boolean>('nexmail.punkte', true)
  const [ordnerOffen, setOrdnerOffen] = useGemerkt('nexmail.ordnerOffen', true)
  const [ordnerBreite, setOrdnerBreite] = useGemerkt('nexmail.ordnerBreite', 232)
  const [listeBreite, setListeBreite] = useGemerkt('nexmail.listeBreite', 380)
  const [schubladeOffen, setSchubladeOffen] = useState(false)

  const [favoriten, setFavoriten] = useGemerkt<string[]>('nexmail.favoriten', [])
  const [eingeklappt, setEingeklappt] = useGemerkt<string[]>('nexmail.eingeklappt', [])

  const [verfassen, setVerfassen] = useState<{
    offen: boolean
    art: Verfassart
    bezug: Nachricht | null
    /** Gesetzt nach „Rückgängig" beim Senden: Das Fenster öffnet mit diesem
     *  Inhalt aus dem Speicher, statt eine Vorlage zu holen. */
    wiederauf?: Sendedaten | null
  }>({ offen: false, art: 'neu', bezug: null })

  const [reiter, setReiter] = useState<Reiter>('postfaecher')
  const [formularOffen, setFormularOffen] = useState(false)

  /* --- Laden ----------------------------------------------------------- */

  /* ⚠️ **Ein Fehler darf nicht wie Leere aussehen.**
   *
   * Am 01.09.2026 konnte der Server seine Datenbank kurz nicht öffnen
   * (`unable to open database file`). `kontenLaden()` warf, `void` schluckte
   * den Fehler, `konten` blieb auf seinem Anfangswert `[]` — und die
   * Oberfläche zeigte „Noch kein Postfach" und einen leeren Ordnerbaum.
   *
   * Der Betreiber: „meine eingestelten mails sind jetzt alle weg. also die
   * postfächer…" Es war nichts weg. Aber genau so sieht ein Datenverlust aus,
   * und das ist der Schrecken, den eine Anwendung niemandem machen darf.
   *
   * Deshalb drei Zustände statt zwei: **noch nicht geladen**, **geladen** und
   * **ging nicht** — und der dritte sagt es. */
  const [stammGeladen, setStammGeladen] = useState(false)
  const [stammFehler, setStammFehler] = useState('')

  const stammLaden = useCallback(async () => {
    try {
      const k = await kontenLaden()
      setKonten(k)
      setOrdner(await ordnerLaden(k))
      setSchlagworte(await schlagworteLaden())
      setStammGeladen(true)
      setStammFehler('')
    } catch (f) {
      // ⚠️ Der alte Bestand bleibt stehen. Ihn zu leeren hieße, den Schrecken
      // erst recht zu erzeugen — und er stimmt ja noch.
      setStammFehler(f instanceof ApiFehler && f.detail ? f.detail : t('stoerung.stamm'))
    }
  }, [t])

  useEffect(() => {
    void stammLaden()
  }, [stammLaden])

  /* Welche Postfächer das Schlagwort übrig lässt. Leer heißt: alle — auch
     dann, wenn das gemerkte Wort an keinem Postfach mehr hängt. Sonst stünde
     die Liste nach dem Entfernen eines Schlagworts leer da, ohne Grund. */
  const gefilterteKontoIds = gruppe
    ? konten
        .filter((k) => (k.tags ?? []).some((w) => w.toLowerCase() === gruppe.toLowerCase()))
        .map((k) => k.id)
    : []

  /* Der Schlagwort-Filter greift nur, solange es die Definition noch gibt.
     Ein gemerktes Atom, dessen Schlagwort gelöscht wurde, hieße sonst: leere
     Liste ohne sichtbaren Grund — dieselbe Regel wie beim gemerkten
     Postfach-Schlagwort. Und nicht bei „Markierte": Dort ist die Auswahl
     schon die Aussage, und die Filterzeile ist ausgeblendet — ein unsichtbar
     weiterwirkender Filter versteckte markierte Post. */
  const wirksamesSchlagwort = schlagworte.some(
    (s) => s.atom.toLowerCase() === schlagwortFilter.toLowerCase(),
  )
    ? schlagwortFilter
    : ''

  const listeLaden = useCallback(async () => {
    // Der Ausgang ist keine Nachrichtenliste - er kommt aus der eigenen
    // Warteschlange, nicht aus einem Ordner. Hier gibt es nichts zu holen.
    if (ziel.typ === 'ausgang') return
    const id = ziel.typ === 'ordner' ? Number(ziel.id) : null
    // ⚠️ Nur die Sammelansichten werden eingeschränkt. Wer einen bestimmten
    // Ordner anklickt, hat sein Postfach schon gewählt — dort noch einmal zu
    // filtern könnte eine leere Liste erzeugen, obwohl der Ordner voll ist.
    const nurDiese = ziel.typ === 'ordner' ? [] : gefilterteKontoIds
    const seite = await nachrichtenLaden(
      id,
      listenfilter,
      ziel.typ === 'markiert',
      nurDiese,
      '',
      SEITE,
      // ⚠️ Nicht bei „Markierte": Dort ist die Auswahl die Aussage — ein
      // Gespräch daraus zu machen versteckte gerade die markierte Mail.
      gruppiert && ziel.typ !== 'markiert',
      ziel.typ === 'markiert' ? '' : wirksamesSchlagwort,
    )
    setNachrichten(seite)
    // ⚠️ **Am Ende ist man, wenn die Seite nicht voll war** — nicht erst, wenn
    // eine leere zurückkommt. Sonst braucht jedes Ende eine überflüssige
    // Anfrage, und der Fuß behauptet so lange, es gebe noch etwas.
    setAmEnde(seite.length < SEITE)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ziel, listenfilter, gruppiert, wirksamesSchlagwort, gefilterteKontoIds.join(',')])

  /* Ältere nachladen.
   *
   * ⚠️ **Über einen Merkpunkt, nicht über einen Versatz.** Zwischen zwei
   * Seiten kann Post eintreffen; dann rutscht alles nach unten und Seite 2
   * begänne mit der letzten Zeile von Seite 1. Doppelte Einträge sehen aus wie
   * ein Abgleichfehler — man sucht die Ursache dann im IMAP.
   */
  const mehrLaden = useCallback(async () => {
    if (mehrLaedtRef.current || amEnde || nachrichten.length === 0) return
    mehrLaedtRef.current = true
    setMehrLaedt(true)
    try {
      const id = ziel.typ === 'ordner' ? Number(ziel.id) : null
      const nurDiese = ziel.typ === 'ordner' ? [] : gefilterteKontoIds
      const weiter = await nachrichtenLaden(
        id,
        listenfilter,
        ziel.typ === 'markiert',
        nurDiese,
        merkpunkt(nachrichten[nachrichten.length - 1]),
        SEITE,
        // ⚠️ **Auch beim Nachladen gruppieren.** Sonst kippt die Liste ab
        // Zeile 61 in die flache Ansicht zurück — und dieselbe Mail steht
        // dann zweimal da: einmal im Strang, einmal einzeln.
        gruppiert && ziel.typ !== 'markiert',
        // ⚠️ Und auch beim Nachladen das Schlagwort — sonst mischt Seite 2
        // wieder alles darunter.
        ziel.typ === 'markiert' ? '' : wirksamesSchlagwort,
      )
      // ⚠️ Doppelte trotzdem aussieben: Ein Abgleich, der zwischendurch lief,
      // kann eine Zeile verschoben haben. Zwei gleiche Kennungen in der Liste
      // wären ein React-Schlüsselkonflikt — und sichtbar doppelte Post.
      setNachrichten((bisher) => {
        const bekannt = new Set(bisher.map((n) => n.id))
        return [...bisher, ...weiter.filter((n) => !bekannt.has(n.id))]
      })
      if (weiter.length < SEITE) setAmEnde(true)
    } finally {
      mehrLaedtRef.current = false
      setMehrLaedt(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ziel, listenfilter, amEnde, gruppiert, nachrichten, wirksamesSchlagwort, gefilterteKontoIds.join(',')])

  useEffect(() => {
    void listeLaden()
  }, [listeLaden])

  useEffect(() => {
    if (gewaehlt === null) {
      setOffene(null)
      return
    }
    let abgebrochen = false
    setOffeneLaedt(true)
    nachrichtLaden(gewaehlt)
      .then((voll) => {
        // Wer weiterklickt, während die Mail noch lädt, soll nicht plötzlich
        // die vorige vor sich haben.
        if (!abgebrochen) setOffene(voll)
      })
      .catch(() => {
        if (!abgebrochen) setOffene(null)
      })
      .finally(() => {
        if (!abgebrochen) setOffeneLaedt(false)
      })
    return () => {
      abgebrochen = true
    }
  }, [gewaehlt])

  /* --- Auswahl --------------------------------------------------------- */

  const waehlen = useCallback(
    (id: string | null, strg = false, umschalt = false) => {
      if (id === null) {
        setGewaehlt(null)
        setMehrfach([])
        return
      }
      if (strg) {
        // Zur Auswahl hinzu oder heraus. Der Lesebereich bleibt, wo er ist -
        // wer sammelt, will nicht bei jedem Klick eine andere Mail sehen.
        setMehrfach((alt) => (alt.includes(id) ? alt.filter((x) => x !== id) : [...alt, id]))
        return
      }
      if (umschalt && gewaehlt) {
        const reihe = nachrichten.map((n) => n.id)
        const a = reihe.indexOf(gewaehlt)
        const b = reihe.indexOf(id)
        if (a >= 0 && b >= 0) {
          setMehrfach(reihe.slice(Math.min(a, b), Math.max(a, b) + 1))
          return
        }
      }
      setGewaehlt(id)
      setMehrfach([])
    },
    [gewaehlt, nachrichten],
  )

  /** Worauf eine Aktion wirkt: die Mehrfachauswahl, sonst die offene Mail. */
  const betroffene = useCallback(
    (id?: string) => {
      if (id && mehrfach.includes(id)) return mehrfach
      if (id) return [id]
      return mehrfach.length > 0 ? mehrfach : gewaehlt ? [gewaehlt] : []
    },
    [mehrfach, gewaehlt],
  )

  /* --- Ordnerzähler ---------------------------------------------------- */

  /* ⚠️ **Die Zeitzone muss stehen, bevor das erste Datum gezeichnet wird.**
     Sonst blitzt einmal die Zone des Browsers auf und springt danach um. */
  useEffect(() => {
    void api
      .holen<{ zeitzone: string }>('/api/einstellungen')
      .then((e) => zeitzoneSetzen(e.zeitzone ?? ''))
      .catch(() => undefined)
  }, [])

  /* --- Suchen ----------------------------------------------------------- */

  // ⚠️ **Die Suche läuft im Server, nicht im Browser.** Die Liste im Browser
  // hält 200 Zeilen des aktuellen Ordners — eine Suche darin fände nichts von
  // dem, was jemand sucht. Der Volltextindex geht über alle Nachrichten.
  const suchen = useCallback(
    async (text: string, wo: Suchbereich, beimAnbieter = false) => {
      const marke = `${text}|${wo}|${beimAnbieter}`
      suchtFuer.current = marke
      setSuchtLaeuft(true)
      try {
        const ergebnis = await ladenSuchen(
          text,
          wo,
          ziel.typ === 'ordner' ? Number(ziel.id) : null,
          ziel.typ === 'ordner'
            ? (ordner.find((o) => o.id === ziel.id)?.kontoId ?? null)
            : null,
          beimAnbieter,
        )
        if (suchtFuer.current === marke) setBefund(ergebnis)
      } catch {
        if (suchtFuer.current === marke) setBefund({ treffer: [], vollstaendig: false })
      } finally {
        if (suchtFuer.current === marke) setSuchtLaeuft(false)
      }
    },
    [ziel, ordner],
  )

  useEffect(() => {
    window.clearTimeout(suchUhr.current)
    const text = suche.trim()
    if (!text) {
      suchtFuer.current = ''
      setBefund(null)
      setSuchtLaeuft(false)
      return
    }
    // Kurz warten: sonst eine Abfrage je Tastendruck.
    suchUhr.current = window.setTimeout(() => void suchen(text, bereich), 250)
    return () => window.clearTimeout(suchUhr.current)
  }, [suche, bereich, suchen])

  // Liegt die geöffnete Nachricht im Entwurfsordner? Dann ist sie zum
  // Weiterschreiben da, nicht zum Beantworten.
  const offeneIstEntwurf = useMemo(
    () => Boolean(offene && ordner.find((o) => o.id === offene.ordnerId)?.rolle === 'entwuerfe'),
    [offene, ordner],
  )

  const ordnerMitZaehlern = useMemo(() => {
    /* ⚠️ **Eine Quelle, nicht zwei.** Bis zum 02.09.2026 zählte die
       Oberfläche für den GEÖFFNETEN Ordner selbst nach — über `nachrichten`,
       also über die Liste, wie sie gerade gefiltert und auf eine Seite
       begrenzt ist. Der Baum zeigte 16, ein Klick in den Ordner machte 11
       daraus, ein Klick daneben wieder 16. Der Betreiber: „Tatsächlich sind
       es 11." Bei einem Ordner mit mehr als einer Seite hätte dort obendrein
       die Seitengröße gestanden.

       Die Zahl kommt jetzt ausschließlich vom Server, der sie beim Abrufen
       zählt. Damit sie trotzdem sofort reagiert, wenn man eine Mail liest,
       wird sie um genau eins verschoben — siehe `zaehlerVerschieben`. Das ist
       vom Filter und von der Seitengröße unabhängig, eine örtliche Zählung
       ist es nicht. */
    return ordner
  }, [ordner])

  // Über **alle** Ordner: Der Reitertitel soll sagen, ob irgendwo Post
  // liegt — nicht, ob im gerade geöffneten Ordner welche liegt.
  const ungelesen = ordner
    .filter((o) => o.rolle === 'posteingang')
    .reduce((s, o) => s + o.ungelesen, 0)
  useEffect(() => {
    document.title = ungelesen > 0 ? `(${ungelesen}) nexmail` : 'nexmail'
  }, [ungelesen])

  /* --- Flags: erst der Server, dann die Anzeige ------------------------ */

  /** Den Ungelesen-Zähler eines Ordners um `schritt` verschieben.
   *
   * ⚠️ **Verschieben, nicht neu zählen.** Die geladene Liste ist gefiltert und
   * auf eine Seite begrenzt; wer über sie zählt, schreibt bei einem vollen
   * Ordner die Seitengröße in den Baum. Ein Schritt um eins stimmt dagegen
   * unabhängig davon, was gerade sichtbar ist — und der nächste Abruf holt die
   * gezählte Wahrheit vom Server nach. */
  const zaehlerVerschieben = useCallback((ordnerId: string, schritt: number) => {
    setOrdner((alle) =>
      alle.map((o) =>
        String(o.id) === String(ordnerId)
          ? { ...o, ungelesen: Math.max(0, o.ungelesen + schritt) }
          : o,
      ),
    )
  }, [])

  const flagSetzen = useCallback(
    async (id: string, wunsch: { gelesen?: boolean; markiert?: boolean }) => {
      const vorher = nachrichtenRef.current.find((n) => n.id === id)
      try {
        await api.senden(`/api/nachrichten/${id}/flags`, wunsch)
      } catch {
        // Ging es auf dem Server nicht, bleibt es auch hier, wie es war.
        return
      }
      setNachrichten((alle) => alle.map((n) => (n.id === id ? { ...n, ...wunsch } : n)))
      setOffene((o) => (o && o.id === id ? { ...o, ...wunsch } : o))
      // Der Baum soll es sofort zeigen, nicht erst beim nächsten Abruf.
      if (wunsch.gelesen !== undefined && vorher && vorher.gelesen !== wunsch.gelesen) {
        zaehlerVerschieben(vorher.ordnerId, wunsch.gelesen ? -1 : 1)
      }
    },
    [zaehlerVerschieben],
  )

  /* --- Schlagworte ------------------------------------------------------ */

  /** Ein Schlagwort an Mails setzen oder nehmen.
   *
   * ⚠️ **Erst der Server, dann die Anzeige** — der Endpunkt schreibt das
   * IMAP-Keyword zum Anbieter, bevor er lokal nachzieht; scheitert das,
   * bleibt auch hier alles, wie es war, und der Grund steht unten. Die
   * Kennungen des Servers werden übersetzt, kein roher Text.
   */
  const schlagwortSchalten = useCallback(
    async (ids: string[], atom: string, setzen: boolean) => {
      try {
        await schlagwortSetzen(ids, atom, setzen)
      } catch (f) {
        const detail = f instanceof ApiFehler ? f.detail : ''
        setStoerung(
          detail === 'schlagworte_nicht_unterstuetzt'
            ? t('schlagworte.fehler_nicht_unterstuetzt')
            : detail === 'schlagwort_ordner_veraltet'
              ? t('schlagworte.fehler_veraltet')
              : detail || t('anmeldung.fehler_allgemein'),
        )
        return
      }
      const anpassen = <T extends Nachricht>(n: T): T => {
        if (!ids.includes(n.id)) return n
        const ohne = (n.schlagworte ?? []).filter(
          (a) => a.toLowerCase() !== atom.toLowerCase(),
        )
        return { ...n, schlagworte: setzen ? [...ohne, atom] : ohne }
      }
      setNachrichten((alle) => alle.map(anpassen))
      setOffene((o) => (o ? anpassen(o) : o))
      // Die Zahl an der Definition (für die Lösch-Rückfrage) hängt daran.
      try {
        setSchlagworte(await schlagworteLaden())
      } catch {
        // Die Zahl ist Beiwerk — die Marken stimmen auch ohne sie.
      }
    },
    [t],
  )

  /** „Neues Schlagwort…": nach dem Namen fragen, anlegen, gleich setzen.
   *  Das Atom entsteht im Server aus dem Namen (Umlaute umgeschrieben,
   *  Kollision nummeriert). */
  const neuesSchlagwort = useCallback(
    async (ids: string[]) => {
      const name = await fragen({
        titel: t('schlagworte.neu_titel'),
        text: t('schlagworte.neu_text'),
        eingabe: {
          beschriftung: t('schlagworte.name'),
          platzhalter: t('schlagworte.name_platzhalter'),
        },
        knopf: t('schlagworte.anlegen'),
      })
      if (typeof name !== 'string' || !name.trim()) return
      let atom: string
      try {
        const definition = await schlagwortAnlegen(name.trim())
        atom = definition.atom
        setSchlagworte((v) => [...v, definition])
      } catch (f) {
        const detail = f instanceof ApiFehler ? f.detail : ''
        setStoerung(
          detail === 'schlagwort_name_vergeben'
            ? t('schlagworte.fehler_name_vergeben')
            : detail || t('anmeldung.fehler_allgemein'),
        )
        return
      }
      await schlagwortSchalten(ids, atom, true)
    },
    [fragen, schlagwortSchalten, t],
  )

  /** Das Untermenü „Schlagwort" — Kontextmenü der Liste und „Weitere
   *  Aktionen" im Lesebereich bauen es aus derselben Quelle. */
  const schlagwortUntermenue = useCallback(
    (n: Nachricht, ids: string[]): MenueEintrag[] => [
      ...schlagworte.map((s): MenueEintrag => {
        const gesetzt = (n.schlagworte ?? []).some(
          (a) => a.toLowerCase() === s.atom.toLowerCase(),
        )
        return {
          id: `schlagwort-${s.id}`,
          text: s.name,
          aktiv: gesetzt,
          symbol: <Schlagwortmarke farbe={s.farbe} />,
          tun: () => void schlagwortSchalten(ids, s.atom, !gesetzt),
        }
      }),
      {
        id: 'schlagwort-neu',
        text: t('schlagworte.neu'),
        symbol: <Plus />,
        trennerDavor: schlagworte.length > 0,
        tun: () => void neuesSchlagwort(ids),
      },
    ],
    [schlagworte, schlagwortSchalten, neuesSchlagwort, t],
  )

  /* --- Wiedervorlage ---------------------------------------------------- */

  /** Weglegen: Der Server verschiebt die Mail **erst per IMAP** in den
   *  Ordner „Wiedervorlage" und legt dann den Merker an — scheitert das
   *  Verschieben, entsteht keiner, und der Grund steht hier. */
  const wiedervorlegenAusfuehren = useCallback(
    async (ids: string[], wann: Date) => {
      try {
        for (const id of ids) await wiedervorlegen(id, wann.toISOString())
      } catch (f) {
        const detail = f instanceof ApiFehler ? f.detail : ''
        setStoerung(
          detail === 'wiedervorlage_ohne_kennung'
            ? t('wiedervorlage.fehler_ohne_kennung')
            : detail === 'wiedervorlage_kennung_unbrauchbar'
              ? t('wiedervorlage.fehler_kennung_unbrauchbar')
              : detail === 'wiedervorlage_ordner_fehlt'
                ? t('wiedervorlage.fehler_ordner')
                : detail || t('anmeldung.fehler_allgemein'),
        )
      }
      // Auch nach einem Fehlschlag mitten in einer Mehrfachauswahl: Baum
      // (neuer Ordner), Liste (Mail weg), Zahl und Marken sollen die
      // Wahrheit zeigen — dieselbe Reihenfolge wie nach jedem Zug.
      setGewaehlt(null)
      setMehrfach([])
      await stammLaden()
      await listeLaden()
      await wiedervorlagenNachsehen()
    },
    [stammLaden, listeLaden, wiedervorlagenNachsehen, t],
  )

  /** „Eigener Zeitpunkt …": datetime-local über die Nachfrage — der Browser
   *  liest Ortszeit, hinausgeschickt wird ISO in UTC. */
  const wiedervorlageEigen = useCallback(
    async (ids: string[]) => {
      const wert = await fragen({
        titel: t('wiedervorlage.eigen_titel'),
        text: t('wiedervorlage.eigen_text'),
        eingabe: { beschriftung: t('wiedervorlage.eigen_feld'), typ: 'datetime-local' },
        knopf: t('wiedervorlage.weglegen'),
      })
      if (typeof wert !== 'string' || !wert) return
      const wann = new Date(wert)
      if (Number.isNaN(wann.getTime()) || wann.getTime() <= Date.now()) {
        // Ein Zeitpunkt in der Vergangenheit hieße: sofort wieder oben —
        // das hat niemand gemeint. Sagen statt stumm ausführen.
        setStoerung(t('wiedervorlage.vergangen'))
        return
      }
      await wiedervorlegenAusfuehren(ids, wann)
    },
    [fragen, wiedervorlegenAusfuehren, t],
  )

  /** Einen wartenden Merker wegnehmen — die Mail bleibt, wo sie liegt.
   *  Der Ausweg, wenn ein Eintrag nicht mehr zurückkommen soll oder sein
   *  Aufwecken dauerhaft scheitert. */
  const wiedervorlageAufheben = useCallback(
    async (ids: string[]) => {
      const betroffene = wiedervorlagen.filter(
        (w) => w.nachricht_id !== null && ids.includes(String(w.nachricht_id)),
      )
      try {
        for (const w of betroffene) {
          await api.loeschen(`/api/nachrichten/wiedervorlage/${w.id}`)
        }
      } catch {
        setStoerung(t('anmeldung.fehler_allgemein'))
      }
      await wiedervorlagenNachsehen()
    },
    [wiedervorlagen, wiedervorlagenNachsehen, t],
  )

  /** Das Untermenü „Wiedervorlage" — Kontextmenü der Liste und „Weitere
   *  Aktionen" im Lesebereich bauen es aus derselben Quelle. */
  const wiedervorlageUntermenue = useCallback(
    (ids: string[]): MenueEintrag[] => {
      const eintraege: MenueEintrag[] = [
        {
          id: 'wv-heute',
          text: t('wiedervorlage.heute_abend'),
          // Nach 18 Uhr läge „Heute Abend" in der Vergangenheit — der Eintrag
          // sagt es, statt die Mail auf der Stelle zurückkommen zu lassen.
          deaktiviert: heute18().getTime() <= Date.now(),
          tun: () => void wiedervorlegenAusfuehren(ids, heute18()),
        },
        {
          id: 'wv-morgen',
          text: t('wiedervorlage.morgen'),
          tun: () => void wiedervorlegenAusfuehren(ids, morgen8()),
        },
        {
          id: 'wv-montag',
          text: t('wiedervorlage.montag'),
          tun: () => void wiedervorlegenAusfuehren(ids, naechsterMontag8()),
        },
        {
          id: 'wv-eigen',
          text: t('wiedervorlage.eigen'),
          trennerDavor: true,
          tun: () => void wiedervorlageEigen(ids),
        },
      ]
      // Trägt eine der gewählten Mails schon eine Aufwach-Marke, lässt sie
      // sich hier auch wieder wegnehmen — nur der Merker fällt, die Mail
      // bleibt liegen.
      const wartet = wiedervorlagen.some(
        (w) => w.nachricht_id !== null && ids.includes(String(w.nachricht_id)),
      )
      if (wartet) {
        eintraege.push({
          id: 'wv-aufheben',
          text: t('wiedervorlage.aufheben'),
          trennerDavor: true,
          tun: () => void wiedervorlageAufheben(ids),
        })
      }
      return eintraege
    },
    [wiedervorlagen, wiedervorlegenAusfuehren, wiedervorlageEigen, wiedervorlageAufheben, t],
  )

  /* Was die Ordnerspalte und die Liste aus den Eintraegen brauchen: die Zahl
     je Postfach und der Aufwach-Zeitpunkt je (aktueller) Nachrichtzeile. */
  const wiedervorlageZahlen: Record<string, number> = {}
  const aufwachZeiten: Record<string, string> = {}
  for (const w of wiedervorlagen) {
    wiedervorlageZahlen[w.konto_id] = (wiedervorlageZahlen[w.konto_id] ?? 0) + 1
    if (w.nachricht_id !== null) aufwachZeiten[String(w.nachricht_id)] = w.aufwachen
  }

  /* --- Die Zwei-Sekunden-Regel ----------------------------------------- */

  const uhr = useRef<number | undefined>(undefined)

  /* ⚠️ **„Als ungelesen markieren" muss halten.**
   *
   * Die Regel unten markiert die offene Nachricht nach zwei Sekunden als
   * gelesen. Wer sie ausdrücklich auf ungelesen setzt, während sie offen ist,
   * bekam sie dadurch sofort wieder zurückgesetzt — die Handlung sah aus, als
   * hätte sie nicht gewirkt. Outlook lässt sie ungelesen, bis man etwas
   * anderes anklickt; genau so verhält sich nexmail jetzt.
   *
   * Zurückgesetzt wird der Vermerk beim Wechsel der Nachricht: Beim nächsten
   * Öffnen gilt die Regel wieder. */
  const alsUngelesenGewollt = useRef<string | null>(null)

  useEffect(() => {
    window.clearTimeout(uhr.current)
    if (!offene || offene.gelesen) return
    if (alsUngelesenGewollt.current === offene.id) return
    // ⚠️ **−1 heißt: nur von Hand.** Wer das einstellt, will ausdrücklich,
    // dass Öffnen nichts verändert — dann darf hier auch keine Uhr laufen.
    if (gelesenNach < 0) return

    const id = offene.id
    uhr.current = window.setTimeout(
      () => void flagSetzen(id, { gelesen: true }),
      Math.max(0, gelesenNach) * 1000,
    )
    // Wer weiterblättert, bevor die Zeit um ist, hat die Nachricht nicht
    // gelesen — dann wird auch nichts markiert.
    return () => window.clearTimeout(uhr.current)
  }, [offene, flagSetzen, gelesenNach])

  // Beim Wechsel der Nachricht gilt die Regel wieder.
  useEffect(() => {
    if (alsUngelesenGewollt.current && alsUngelesenGewollt.current !== gewaehlt) {
      alsUngelesenGewollt.current = null
    }
  }, [gewaehlt])

  /* --- Handeln --------------------------------------------------------- */

  const merkeRueckweg = useCallback((text: string, weg: Rueckweg | null) => {
    if (!weg) return
    setRueckgaengig({ text, weg })
  }, [])

  /* Die 8 Sekunden der Rückgängig-Leiste. ⚠️ **Die Uhr läuft nur, solange
     die Leiste zu sehen ist.** Steht gerade die Sende-Leiste da, wird die
     Rückgängig-Leiste zurückgestellt — liefe ihre Uhr währenddessen weiter,
     verfiele der einzige Rückweg eines nachfragefreien Löschens unsichtbar
     hinter der Sende-Leiste. Erst wenn die verschwindet, beginnen die
     8 Sekunden. */
  useEffect(() => {
    if (!rueckgaengig || sendeRueck) return
    rueckUhr.current = window.setTimeout(() => setRueckgaengig(null), 8000)
    return () => window.clearTimeout(rueckUhr.current)
  }, [rueckgaengig, sendeRueck])

  const handeln = useCallback(
    async (
      tun: () => Promise<{ bewegt: number; rueckweg: Rueckweg | null }>,
      text: string,
    ) => {
      try {
        const ergebnis = await tun()
        merkeRueckweg(text, ergebnis.rueckweg)
      } catch (f) {
        // ⚠️ **Nicht schlucken.** Hier stand einmal ein leeres `catch` mit der
        // Begründung, es ändere sich ja nichts. Genau das war das Problem: Der
        // Betreiber klickt im Kontextmenü, nichts passiert, nichts steht da —
        // und die Anwendung wirkt kaputt, obwohl sie einen guten Grund hatte
        // („Die Nachricht liegt schon dort", „Dieses Postfach hat keinen
        // Archivordner"). Ein Grund, der nicht ankommt, ist kein Grund.
        setStoerung(
          f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'),
        )
      }
      setGewaehlt(null)
      setMehrfach([])
      await listeLaden()
      await stammLaden()
    },
    [merkeRueckweg, listeLaden, stammLaden, t],
  )

  /* Was ein Wisch tut — dieselben Wege wie die Tasten Entf und E bzw. das
     Kontextmenue, samt der Rueckgaengig-Leiste. Der Wisch ist nur eine
     weitere Hand am selben Hebel, kein eigener. */
  const wischAusfuehren = useCallback(
    (n: Nachricht, aktion: WischAktion) => {
      if (aktion === 'loeschen') {
        void handeln(() => zug('loeschen', [n.id]), t('rueck.geloescht'))
      } else if (aktion === 'archivieren') {
        void handeln(() => zug('archivieren', [n.id]), t('rueck.archiviert'))
      } else if (aktion === 'gelesen') {
        void flagSetzen(n.id, { gelesen: !n.gelesen })
      }
    },
    [handeln, flagSetzen, t],
  )

  async function zurueck() {
    if (!rueckgaengig) return
    const weg = rueckgaengig.weg
    setRueckgaengig(null)
    window.clearTimeout(rueckUhr.current)
    try {
      await zurueckholen(weg)
    } finally {
      await listeLaden()
      await stammLaden()
    }
  }

  /* --- Senden rückholen ------------------------------------------------- */

  /* Die ablaufende Zeit der Leiste. Läuft sie aus, ist die Nachricht fällig
     und der Versandplan schickt sie — die Leiste verschwindet, und der
     Ausgang zeigt den Rest der Wahrheit (bis zum Versand steht sie dort). */
  useEffect(() => {
    if (!sendeRueck) return
    const bis = sendeRueck.bis
    setSendeRest(Math.max(1, Math.ceil((bis - Date.now()) / 1000)))
    const takt = window.setInterval(() => {
      const rest = Math.ceil((bis - Date.now()) / 1000)
      if (rest <= 0) {
        setSendeRueck(null)
        void ausgangLaden()
        void listeLaden()
        void stammLaden()
      } else {
        setSendeRest(rest)
      }
    }, 250)
    return () => window.clearInterval(takt)
  }, [sendeRueck, ausgangLaden, listeLaden, stammLaden])

  /* ⚠️ Wenn der Versandplan eine geplante Mail hinausschickt, klickt niemand.
     Ohne dieses Nachsehen zeigte die offene Anwendung nach 18:00 weiter
     „Postausgang 1", und erst „Versand abbrechen" lieferte per 409 die
     Wahrheit. Deshalb: Liegt Geplantes, wird kurz nach der Planzeit neu
     geladen — und solange der Eintrag danach noch dasteht (der Versandplan
     greift im Minutentakt), alle 15 Sekunden wieder. Ohne geplante Einträge
     läuft hier gar nichts. */
  useEffect(() => {
    const geplant = ausgaenge.filter((a) => a.stand === 'wartet' && a.senden_ab)
    if (geplant.length === 0) return
    const naechste = Math.min(...geplant.map((a) => new Date(a.senden_ab as string).getTime()))
    const wartezeit = naechste <= Date.now() ? 15_000 : naechste - Date.now() + 5_000
    const uhr = window.setTimeout(() => {
      void ausgangLaden()
      // Die Mail kann jetzt draußen sein — dann gehören auch „Gesendet"
      // und die Zähler nachgezogen, ohne dass jemand von Hand abgleicht.
      void listeLaden()
      void stammLaden()
    }, wartezeit)
    return () => window.clearTimeout(uhr)
  }, [ausgaenge, ausgangLaden, listeLaden, stammLaden])

  async function sendenZurueckholen() {
    if (!sendeRueck) return
    const s = sendeRueck
    setSendeRueck(null)
    try {
      const ergebnis = await api.senden<{ entwurf_uid: number }>(
        `/api/verfassen/ausgang/${s.ausgangId}/abbrechen`,
        {},
      )
      // Das Fenster geht mit dem Inhalt aus dem Speicher wieder auf — nicht
      // mit dem Entwurf, den der Abbruch als Sicherheitsnetz abgelegt hat.
      // ⚠️ Aber es hängt an dessen UID: Senden oder Speichern räumt diese
      // Fassung dann auf. Ohne die UID bliebe nach jedem „Rückgängig" ein
      // Entwurf für immer im Ordner liegen — auf allen Geräten.
      setVerfassen({
        offen: true,
        art: 'neu',
        bezug: null,
        wiederauf: { ...s.daten, entwurf_uid: ergebnis.entwurf_uid ?? 0 },
      })
    } catch (f) {
      // ⚠️ Auch „schon unterwegs" (409) soll dastehen — der Satz des Servers,
      // nicht ein stilles Nichts. Das Fenster bleibt dann zu: Was draußen
      // ist, ist draußen.
      setStoerung(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    }
    void ausgangLaden()
    void stammLaden()
    void listeLaden()
  }

  /* --- Tastatur -------------------------------------------------------- */

  useEffect(() => {
    function beiTaste(e: KeyboardEvent) {
      // Nicht zuschlagen, während jemand tippt.
      const ziel = e.target as HTMLElement | null
      if (ziel?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (verfassen.offen || menue) return

      const ids = betroffene()
      if (ids.length === 0) return

      if (e.key === 'Delete') {
        e.preventDefault()
        void handeln(() => zug('loeschen', ids), t('rueck.geloescht'))
      }
      if (e.key.toLowerCase() === 'e' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault()
        void handeln(() => zug('archivieren', ids), t('rueck.archiviert'))
      }
      if (e.key === 'Escape' && mehrfach.length > 0) {
        setMehrfach([])
      }
    }
    document.addEventListener('keydown', beiTaste)
    return () => document.removeEventListener('keydown', beiTaste)
  }, [betroffene, handeln, mehrfach.length, menue, t, verfassen.offen])

  /* --- Abgleich -------------------------------------------------------- */

  /* ⚠️ **Der erste Abgleich eines echten Postfachs dauert Minuten.**
   *
   * Der Betreiber am 01.09.2026: „das hat ewig gedauert bis er was angezeigt hat.
   * (keine rückmeldung der gui, das er noch was macht)". Ein sich drehendes
   * Symbol am Rand genügt dafür nicht — man sitzt vor einer leeren Liste und
   * weiß nicht, ob überhaupt etwas passiert.
   *
   * Deshalb zwei Dinge: ein Band, das sagt, was läuft und dass es beim ersten
   * Mal dauert — und ein Nachladen im Takt, damit die Liste **während** des
   * Abgleichs wächst statt am Ende auf einmal.
   */
  async function jetztAbgleichen() {
    setGleichtAb(true)
    const puls = window.setInterval(() => {
      void stammLaden()
      void listeLaden()
    }, 4000)
    try {
      await abgleichen()
      await stammLaden()
      await listeLaden()
      // Eine geplante Mail kann inzwischen hinausgegangen sein - dann soll
      // der Postausgang das zeigen, statt weiter „wartet" zu behaupten.
      await ausgangLaden()
    } finally {
      window.clearInterval(puls)
      setGleichtAb(false)
    }
  }

  /* --- Postausgang: geplanten Versand abbrechen ------------------------- */

  async function ausgangAbbrechen(eintrag: Ausgangseintrag) {
    // ⚠️ Erst die Folgen, dann die Frage: Die Nachricht geht nicht hinaus,
    // aber ihr Inhalt landet als Entwurf im Postfach - nichts ist weg.
    const ja = await fragen({
      titel: t('ausgang.abbrechen'),
      text: t('ausgang.abbrechen_frage'),
      knopf: t('ausgang.abbrechen'),
    })
    if (ja !== true) return
    try {
      await api.senden(`/api/verfassen/ausgang/${eintrag.id}/abbrechen`, {})
    } catch (f) {
      // Auch ein 409 („schon unterwegs") soll dastehen - danach wird trotzdem
      // neu geladen, denn genau dann stimmt die Liste nicht mehr.
      setStoerung(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    }
    await ausgangLaden()
    // Der Entwurf liegt jetzt im Entwurfsordner - Baum und Liste sollen das
    // zeigen, ohne dass jemand von Hand abgleicht.
    await stammLaden()
    await listeLaden()
  }

  /* --- Kontextmenü ----------------------------------------------------- */

  function nachrichtKontext(e: React.MouseEvent, n: Nachricht) {
    e.preventDefault()
    const ids = betroffene(n.id)
    const mehrere = ids.length > 1

    // Verschieben-Ziele: nur Ordner desselben Postfachs, und nicht der, in
    // dem die Nachricht schon liegt.
    const ziele: MenueEintrag[] = ordner
      .filter((o) => o.kontoId === n.kontoId && o.id !== n.ordnerId && o.rolle !== 'entwuerfe')
      .map((o) => ({
        id: o.id,
        text: o.name,
        tun: () => void handeln(() => verschieben(ids, o.id), t('rueck.verschoben')),
      }))

    setMenue({
      x: e.clientX,
      y: e.clientY,
      eintraege: [
        {
          id: 'antworten',
          text: t('aktion.antworten'),
          symbol: <CornerUpLeft />,
          deaktiviert: mehrere,
          tun: () => setVerfassen({ offen: true, art: 'antwort', bezug: n }),
        },
        {
          id: 'allen',
          text: t('aktion.allen_antworten'),
          symbol: <ReplyAll />,
          deaktiviert: mehrere,
          tun: () => setVerfassen({ offen: true, art: 'allen', bezug: n }),
        },
        {
          id: 'weiter',
          text: t('aktion.weiterleiten'),
          symbol: <CornerUpRight />,
          deaktiviert: mehrere,
          tun: () => setVerfassen({ offen: true, art: 'weiter', bezug: n }),
        },
        {
          // Weiterleiten als Anhang: Die Originalmail fährt unverändert als
          // Roh-.eml mit — für den Empfänger, der sie prüfen soll.
          id: 'anhang',
          text: t('aktion.als_anhang'),
          symbol: <Paperclip />,
          deaktiviert: mehrere,
          tun: () => setVerfassen({ offen: true, art: 'anhang', bezug: n }),
        },
        {
          // Druckt genau eine Nachricht — die Druckseite kommt vom Server,
          // den Druckdialog stößt `nachrichtDrucken` an.
          id: 'drucken',
          text: t('aktion.drucken'),
          symbol: <Printer />,
          deaktiviert: mehrere,
          tun: () => nachrichtDrucken(n.id, i18n.language),
        },
        {
          id: 'gelesen',
          trennerDavor: true,
          text: n.gelesen ? t('aktion.ungelesen') : t('aktion.gelesen'),
          symbol: n.gelesen ? <Mail /> : <MailOpen />,
          tun: () => {
            const neuerStand = !n.gelesen
            // ⚠️ Vermerken, damit die Zwei-Sekunden-Regel es nicht sofort
            // wieder umdreht — siehe oben.
            if (!neuerStand) alsUngelesenGewollt.current = n.id
            for (const id of ids) void flagSetzen(id, { gelesen: neuerStand })
          },
        },
        {
          id: 'markieren',
          text: n.markiert ? t('aktion.markierung_entfernen') : t('aktion.markieren'),
          symbol: <Flag />,
          tun: () => {
            for (const id of ids) void flagSetzen(id, { markiert: !n.markiert })
          },
        },
        {
          /* Das Schlagwort-Untermenü: Farbpunkt + Name, Häkchen wenn gesetzt,
             Klick schaltet um — plus „Neues Schlagwort…". Dieselben Einträge
             stehen im Lesebereich unter „Weitere Aktionen". */
          id: 'schlagwort',
          text: t('schlagworte.menue'),
          symbol: <Tag />,
          unter: schlagwortUntermenue(n, ids),
        },
        {
          /* ⚠️ **Hier, gleich hinter „Markieren".** Ein Fähnchen und eine
             Aufgabe beantworten dieselbe Frage — „das noch" —, nur trägt das
             Fähnchen der Mailserver und die Aufgabe nexmail. Sie gehören
             nebeneinander, sonst sucht man das eine beim anderen. */
          id: 'aufgabe',
          text: t('aufgaben.machen'),
          symbol: <ListChecks />,
          tun: () => {
            void (async () => {
              try {
                for (const id of ids) {
                  await api.senden('/api/aufgaben', { nachricht_id: id })
                }
                await aufgabenZaehlen()
              } catch (f) {
                setStoerung(
                  f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'),
                )
              }
            })()
          },
        },
        {
          /* Die Wiedervorlage direkt neben der Aufgabe: Beide beantworten
             „das noch, aber später" — die Aufgabe merkt es sich nur, die
             Wiedervorlage legt die Mail selbst weg und bringt sie zum
             gewählten Zeitpunkt ungelesen zurück. */
          id: 'wiedervorlage',
          text: t('wiedervorlage.menue'),
          symbol: <Clock />,
          unter: wiedervorlageUntermenue(ids),
        },
        {
          id: 'verschieben',
          trennerDavor: true,
          text: t('aktion.verschieben'),
          symbol: <FolderInput />,
          unter: ziele,
        },
        {
          id: 'archivieren',
          text: t('aktion.archivieren'),
          symbol: <Archive />,
          tun: () => void handeln(() => zug('archivieren', ids), t('rueck.archiviert')),
        },
        {
          id: 'junk',
          text: t('aktion.junk'),
          symbol: <ShieldAlert />,
          tun: () => void handeln(() => zug('junk', ids), t('rueck.verschoben')),
        },
        {
          id: 'regel',
          trennerDavor: true,
          text: t('aktion.regel') + ' \u2014 ' + t('einstellungen.bald'),
          symbol: <SlidersHorizontal />,
          deaktiviert: true,
        },
        {
          id: 'loeschen',
          trennerDavor: true,
          text: t('aktion.loeschen'),
          symbol: <Trash2 />,
          gefaehrlich: true,
          tun: () => void handeln(() => zug('loeschen', ids), t('rueck.geloescht')),
        },
      ],
    })
  }

  function einklappenUmschalten(kontoId: string) {
    setEingeklappt(
      eingeklappt.includes(kontoId)
        ? eingeklappt.filter((id) => id !== kontoId)
        : [...eingeklappt, kontoId],
    )
  }

  /** Nach dem Namen fragen und den Ordner beim Anbieter anlegen.
   *
   * ⚠️ Der Name wird **gefragt**, nicht erfunden — und die Meldung des Servers
   * kommt zurück, wenn er ablehnt („Permission denied" statt „ging nicht").
   */
  async function neuerOrdner(kontoId: string, eltern: Ordner | null) {
    const frage = eltern
      ? t('ordner.neu_frage_unter', { name: eltern.name })
      : t('ordner.neu_frage')
    const name = await fragen({
      titel: t('ordner.neu'),
      text: frage,
      eingabe: { beschriftung: t('ordner.name'), platzhalter: t('ordner.name_platzhalter') },
      knopf: t('ordner.anlegen'),
    })
    if (typeof name !== 'string' || !name.trim()) return
    try {
      await ordnerAnlegen(kontoId, name.trim(), eltern ? Number(eltern.id) : null)
      await stammLaden()
    } catch (f) {
      setStoerung(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    }
  }

  function ordnerKontext(e: React.MouseEvent, o: Ordner) {
    e.preventDefault()
    const istFavorit = favoriten.includes(o.id)
    setMenue({
      x: e.clientX,
      y: e.clientY,
      eintraege: [
        {
          id: 'favorit',
          text: istFavorit ? t('ordner.favorit_weg') : t('ordner.favorit_hinzu'),
          symbol: istFavorit ? <StarOff /> : <Star />,
          tun: () =>
            setFavoriten(istFavorit ? favoriten.filter((id) => id !== o.id) : [...favoriten, o.id]),
        },
        {
          id: 'neu',
          trennerDavor: true,
          text: t('ordner.neu'),
          symbol: <FolderPlus />,
          tun: () => void neuerOrdner(o.kontoId, null),
        },
        {
          id: 'neu_unter',
          text: t('ordner.neu_unter'),
          symbol: <FolderPlus />,
          tun: () => void neuerOrdner(o.kontoId, o),
        },
        {
          id: 'einklappen',
          trennerDavor: true,
          text: eingeklappt.includes(o.kontoId)
            ? t('ordner.postfach_ausklappen')
            : t('ordner.postfach_einklappen'),
          symbol: <ChevronsDownUp />,
          tun: () => einklappenUmschalten(o.kontoId),
        },
        {
          id: 'alles_gelesen',
          trennerDavor: true,
          text: t('ordner.alles_gelesen'),
          symbol: <MailOpen />,
          // Nichts Ungelesenes: Dann wäre der Eintrag ein Klick ins Leere.
          deaktiviert: o.ungelesen === 0,
          tun: () =>
            void (async () => {
              try {
                await ordnerAlsGelesen(o.id)
                await stammLaden()
                await listeLaden()
              } catch (f) {
                setStoerung(
                  f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'),
                )
              }
            })(),
        },
        {
          id: 'leeren',
          trennerDavor: true,
          text: t('ordner.leeren'),
          symbol: <Trash2 />,
          gefaehrlich: true,
          // ⚠️ Der einzige Vorgang ohne Rückweg - deshalb nur Papierkorb
          // und Junk, und deshalb wird gefragt.
          deaktiviert: o.rolle !== 'papierkorb' && o.rolle !== 'junk',
          tun: () =>
            void (async () => {
              const ja = await fragen({
                titel: t('ordner.leeren'),
                text: t('ordner.leeren_sicher', { name: o.name }),
                knopf: t('ordner.leeren'),
                gefaehrlich: true,
              })
              if (ja !== true) return
              await handeln(async () => {
                const ergebnis = await ordnerLeeren(o.id)
                return { bewegt: ergebnis.bewegt, rueckweg: null }
              }, '')
            })(),
        },
        {
          id: 'umbenennen',
          trennerDavor: true,
          text: t('ordner.umbenennen'),
          symbol: <PenLine />,
          // ⚠️ Sonderordner nicht: Bei manchen Servern hängt ihre Rolle am
          // Namen, und ein umbenannter Papierkorb wäre danach keiner mehr.
          deaktiviert: o.rolle !== 'eigen',
          tun: () =>
            void (async () => {
              const name = await fragen({
                titel: t('ordner.umbenennen'),
                text: t('ordner.umbenennen_hinweis'),
                eingabe: { beschriftung: t('ordner.name'), vorgabe: o.name },
                knopf: t('ordner.umbenennen'),
              })
              if (typeof name !== 'string' || !name.trim() || name.trim() === o.name) return
              try {
                await ordnerUmbenennen(o.kontoId, Number(o.id), name.trim())
                await stammLaden()
              } catch (f) {
                setStoerung(
                  f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'),
                )
              }
            })(),
        },
        {
          id: 'entfernen',
          text: t('ordner.entfernen'),
          symbol: <FolderX />,
          gefaehrlich: true,
          // ⚠️ Sonderordner nicht: Wer seinen Papierkorb löscht, kann danach
          // keine Mail mehr löschen — und die Meldung dabei bringt niemand
          // mit dieser Handlung in Verbindung.
          deaktiviert: o.rolle !== 'eigen',
          tun: () =>
            void (async () => {
              const drin = nachrichten.filter((n) => n.ordnerId === o.id).length
              const ja = await fragen({
                titel: t('ordner.entfernen'),
                text: t('ordner.entfernen_sicher', { name: o.name, count: drin }),
                knopf: t('ordner.entfernen'),
                gefaehrlich: true,
              })
              if (ja !== true) return
              try {
                await ordnerEntfernen(o.kontoId, Number(o.id))
                await stammLaden()
              } catch (f) {
                setStoerung(
                  f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'),
                )
              }
            })(),
        },
      ],
    })
  }

  /* ⚠️ **„In eigenem Fenster öffnen" hatte nie eine Empfängerseite.** Der
     Knopf öffnete `?nachricht=<id>` — und niemand las den Parameter: Das neue
     Fenster zeigte die Startseite. Seit 0.1.0 so, aufgefallen erst am
     02.09.2026 beim Durchtesten. Hier ist die Empfängerseite: Steht der
     Parameter in der Adresse, zeigt dieses Fenster NUR die eine Nachricht —
     samt Antworten/Weiterleiten über dasselbe Verfassen-Fenster wie überall. */
  const soloId = useMemo(
    () => new URLSearchParams(window.location.search).get('nachricht'),
    [],
  )
  const [soloNachricht, setSoloNachricht] = useState<VolleNachricht | null>(null)
  const [soloStand, setSoloStand] = useState<'laedt' | 'da' | 'fehlt'>('laedt')
  useEffect(() => {
    if (!soloId) return
    nachrichtLaden(soloId)
      .then((n) => {
        setSoloNachricht(n)
        setSoloStand('da')
        document.title = `${n.betreff || t('liste.kein_betreff')} — nexmail`
      })
      .catch(() => setSoloStand('fehlt'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soloId])
  async function abmelden() {
    try {
      await api.senden('/api/auth/abmelden', {})
    } finally {
      aufAbmelden()
    }
  }

  function zuDenZugangsdaten() {
    // Zum Reiter Postfaecher - die betroffene Zeile traegt dort denselben
    // roten Hinweis, der Stift daneben oeffnet das Formular.
    setAnsicht('einstellungen')
    setReiter('postfaecher')
    setSchubladeOffen(false)
  }

  function postfachHinzufuegen() {
    setAnsicht('einstellungen')
    setReiter('postfaecher')
    setFormularOffen(true)
    setSchubladeOffen(false)
  }

  /* Nach saemtlichen Hooks, damit deren Reihenfolge in beiden Zweigen gleich
     bleibt. Das Fenster traegt bewusst weder NavRail noch Spalten: Es ist die
     eine Nachricht, sonst nichts — geschlossen wird es wie ein Fenster. */
  if (soloId) {
    return (
      <div className="flex h-full flex-col bg-canvas">
        {soloStand === 'fehlt' ? (
          <div className="flex flex-1 items-center justify-center p-6 text-sm text-fg-3">
            {t('fenster.nicht_ladbar')}
          </div>
        ) : (
          <Lesebereich
            nachricht={soloNachricht}
            laedt={soloStand === 'laedt'}
            imEigenenFenster
            aufVerfassen={(art, n) => setVerfassen({ offen: true, art, bezug: n })}
          />
        )}

        <VerfassenFenster
          offen={verfassen.offen}
          art={verfassen.art}
          bezug={verfassen.bezug}
          konten={konten}
          wiederauf={verfassen.wiederauf ?? null}
          aufRueckholbar={(ausgangId, bis, daten) => setSendeRueck({ ausgangId, bis, daten })}
          aufSchliessen={() => setVerfassen((v) => ({ ...v, offen: false }))}
        />
        {sendeRueck && (
          <div
            role="status"
            className="fixed bottom-5 left-1/2 z-[70] flex -translate-x-1/2 items-center gap-3 rounded-lg border border-line bg-surface-1 py-2 pr-2 pl-4 shadow-[var(--shadow-3)]"
          >
            <span className="text-[13px] tabular-nums text-fg-1">
              {t('rueck.wird_gesendet', { n: sendeRest })}
            </span>
            <button
              type="button"
              onClick={() => void sendenZurueckholen()}
              className="rounded-md px-2.5 py-1 text-[13px] font-medium text-accent-text transition-colors duration-[var(--dur-fast)] hover:bg-accent-soft"
            >
              {t('aktion.rueckgaengig')}
            </button>
          </div>
        )}
      </div>
    )
  }
  return (
    <div className="flex h-full flex-col">
      <Kopfbanner
        ich={ich}
        aufAbmelden={abmelden}
        /* ⚠️ Erst wenn wirklich geladen wurde. Vorher hieße „keine
            Postfächer" nur „noch nichts gehört". */
        ohnePostfach={stammGeladen && konten.length === 0}
        aufEinstellungen={() => setAnsicht('einstellungen')}
        modus={modus}
        aufModus={aufModus}
      />

      {/* ⚠️ **Abgewiesene Zugangsdaten muessen ins Gesicht.** Der Takt
          versuchte es bis zum 02.09.2026 alle zwei Minuten stumm neu; wer das
          Passwort beim Anbieter aendert, merkte nur, dass keine Post mehr
          kommt. Der Banner bleibt, bis eine Anmeldung wieder GELINGT - ein
          voruebergehend toter Server loest ihn absichtlich nicht aus. */}
      {konten.some((k) => k.stoerung === 'anmeldung') && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-danger/40 bg-danger/15 px-4 py-2 text-[13px] text-fg-1"
        >
          <span className="font-medium">
            {t('stoerung.zugangsdaten', {
              namen: konten
                .filter((k) => k.stoerung === 'anmeldung')
                .map((k) => k.anzeigename)
                .join(', '),
            })}
          </span>
          <span className="text-fg-3">{t('stoerung.zugangsdaten_folge')}</span>
          <button
            type="button"
            onClick={zuDenZugangsdaten}
            className="ml-auto rounded-md px-2.5 py-1 font-medium text-danger transition-colors duration-[var(--dur-fast)] hover:bg-danger/20"
          >
            {t('stoerung.zugangsdaten_knopf')}
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <NavRail
          ansicht={ansicht}
          aufAnsicht={setAnsicht}
          istBetreiber={Boolean(ich?.ist_betreiber)}
          offeneAufgaben={offeneAufgaben}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          {ansicht === 'mail' && (
            <>
              <Kopfleiste
                suche={suche}
                aufSuche={setSuche}
                bereich={bereich}
                aufBereich={setBereich}
                aufNeu={() => setVerfassen({ offen: true, art: 'neu', bezug: null })}
                aufSchublade={() => setSchubladeOffen(true)}
                ordnerOffen={ordnerOffen}
                aufOrdnerOffen={setOrdnerOffen}
                schmal={schmal}
                aufAbgleichen={() => void jetztAbgleichen()}
                gleichtAb={gleichtAb}
              />

              <MailPage
                konten={konten}
                ordner={ordnerMitZaehlern}
                nachrichten={nachrichten}
                offene={offene}
                offeneLaedt={offeneLaedt}
                ziel={ziel}
                aufZiel={setZiel}
                gewaehlt={gewaehlt}
                aufWahl={waehlen}
                suchbefund={befund}
                suchtLaeuft={suchtLaeuft}
                aufAnbietersuche={() => void suchen(suche.trim(), bereich, true)}
                mehrfach={mehrfach}
                suche={suche}
                ordnerBreite={ordnerBreite}
                aufOrdnerBreite={setOrdnerBreite}
                listeBreite={listeBreite}
                aufListeBreite={setListeBreite}
                ordnerOffen={ordnerOffen}
                schmal={schmal}
                schubladeOffen={schubladeOffen}
                aufSchublade={setSchubladeOffen}
                aufVerfassen={(art, n) => setVerfassen({ offen: true, art, bezug: n })}
                istEntwurf={offeneIstEntwurf}
                kompakt={dichte === 'kompakt'}
                anreisserZeigen={anreisserZeigen}
                punkteZeigen={punkteZeigen}
                filter={listenfilter}
                aufFilter={setListenfilter}
                schlagworte={schlagworte}
                schlagwortFilter={wirksamesSchlagwort}
                aufSchlagwortFilter={setSchlagwortFilter}
                aufSchlagwort={(n, atom, setzen) =>
                  void schlagwortSchalten([n.id], atom, setzen)
                }
                aufNeuesSchlagwort={(n) => void neuesSchlagwort([n.id])}
                gruppe={gruppe}
                aufGruppe={setGruppe}
                aufMehr={mehrLaden}
                mehrLaedt={mehrLaedt}
                amEnde={amEnde}
                gruppiert={gruppiert}
                aufGruppiert={setGruppiert}
                aufStrang={strangLaden}
                /* ⚠️ Nur schmal: Am Schreibtisch zieht die Maus Zeilen in
                   den Ordnerbaum — dort gibt es keinen Wisch. */
                wischen={
                  schmal
                    ? { links: wischLinks, rechts: wischRechts, ausfuehren: wischAusfuehren }
                    : undefined
                }
                ziehtAusKonto={ziehtAus}
                aufAbweisung={setStoerung}
                aufZiehen={(n) => {
                  // Merken, aus welchem Postfach gezogen wird — die
                  // Ordnerspalte kann Fremde damit begründet abweisen.
                  setZiehtAus(n.kontoId)
                  return betroffene(n.id)
                }}
                aufAblegen={(ordnerId, ids) => {
                  setZiehtAus('')
                  void handeln(() => verschieben(ids, ordnerId), t('rueck.verschoben'))
                }}
                aufPostfachHinzufuegen={postfachHinzufuegen}
                aufNachrichtKontext={nachrichtKontext}
                aufOrdnerKontext={ordnerKontext}
                favoriten={favoriten}
                eingeklappt={eingeklappt}
                aufEinklappen={einklappenUmschalten}
                ausgaenge={ausgaenge}
                aufAusgangAbbrechen={(e) => void ausgangAbbrechen(e)}
                wiedervorlageZahlen={wiedervorlageZahlen}
                aufwachZeiten={aufwachZeiten}
                wiedervorlageMenue={(n) => wiedervorlageUntermenue([n.id])}
              />
            </>
          )}

          {ansicht === 'aufgaben' && (
            <AufgabenPage
              konten={konten}
              aufAenderung={() => void aufgabenZaehlen()}
              /* ⚠️ Ein Klick führt zur **Mail**, nicht in ein Aufgabendetail.
                 Die Aufgabe ist ein Verweis; alles Weitere steht in der Mail. */
              aufMail={(nachrichtId: number) => {
                setAnsicht('mail')
                setGewaehlt(String(nachrichtId))
              }}
            />
          )}

          {ansicht === 'kontakte' && <KontaktePage />}

          {ansicht === 'ueber' && <UeberPage />}

          {ansicht === 'einstellungen' && (
            <EinstellungenPage
              ich={ich}
              ichNeuLaden={ichNeuLaden}
              reiter={reiter}
              aufReiter={setReiter}
              formularOffen={formularOffen}
              aufFormular={(offen) => {
                setFormularOffen(offen)
                if (!offen) void stammLaden()
              }}
              /* ⚠️ Der rote Zugangsdaten-Banner haengt an Apps eigener
                 Kontenliste. Ohne diese Leitung blieb er nach dem
                 Entfernen des Postfachs stehen (02.09.2026) - dieselbe
                 Falle wie beim zweiten Faktor: Was ich aendere, muss
                 ich auch sehen. */
              aufKontenGeaendert={() => void stammLaden()}
              /* Umbenennen, Farbwechsel und Löschen im Reiter Schlagworte
                 müssen in Liste und Lesebereich ankommen — dieselbe Leitung
                 wie beim Zugangsdaten-Banner. stammLaden holt auch die
                 Definitionen; listeLaden die Marken an den Zeilen. */
              aufSchlagworteGeaendert={() => {
                void stammLaden()
                void listeLaden()
              }}
            />
          )}

          {ansicht === 'verwaltung' && (
            <Verwaltung
              reiter={verwaltungsReiter}
              aufReiter={setVerwaltungsReiter}
              ich={ich}
            />
          )}
        </div>
      </div>

      {menue && (
        <Kontextmenue
          x={menue.x}
          y={menue.y}
          eintraege={menue.eintraege}
          aufSchliessen={() => setMenue(null)}
        />
      )}

      {/* Das Band während eines Abgleichs. Oben, über der Liste: Dort schaut
          man hin, wenn man auf Post wartet. */}
      {gleichtAb && (
        <div
          role="status"
          className="fixed top-14 left-1/2 z-[69] flex -translate-x-1/2 items-center gap-2.5 rounded-pill border border-line bg-surface-1 py-1.5 pr-4 pl-3 shadow-[var(--shadow-3)]"
        >
          <span
            aria-hidden
            className="size-3 animate-spin rounded-full border-[1.5px] border-accent border-t-transparent"
          />
          <span className="text-[12px] text-fg-2">{t('abgleich.laeuft')}</span>
        </div>
      )}

      {/* Was nicht ging, und warum. Sitzt an derselben Stelle wie der
          Rückweg — dort schaut man nach einer Handlung ohnehin hin. */}
      {stoerung && (
        <div
          role="alert"
          className="fixed bottom-5 left-1/2 z-[71] flex -translate-x-1/2 items-center gap-3 rounded-lg border border-danger bg-danger-soft px-4 py-2 shadow-[var(--shadow-3)]"
        >
          <span className="text-[13px] text-danger">{stoerung}</span>
        </div>
      )}

      {/* ⚠️ **Bleibt stehen, bis es wieder geht.** Anders als die Störung
          unten, die nach sechs Sekunden verschwindet: Wer seine Postfächer
          nicht sieht, soll nicht raten müssen, was er verpasst hat. Mit
          Knopf, damit man nicht die ganze Seite neu laden muss. */}
      {stammFehler && (
        <div
          role="alert"
          className="fixed top-[calc(var(--kopf-h,56px)+12px)] left-1/2 z-[71] flex max-w-[min(92vw,560px)] -translate-x-1/2 items-center gap-3 rounded-lg border border-danger bg-danger-soft px-4 py-2.5 shadow-[var(--shadow-3)]"
        >
          <span className="text-[13px] text-fg-1">{stammFehler}</span>
          <button
            type="button"
            onClick={() => void stammLaden()}
            className="shrink-0 rounded-md border border-line px-2.5 py-1 text-[12px] text-fg-1 transition-colors duration-[var(--dur-fast)] hover:border-accent"
          >
            {t('stoerung.nochmal')}
          </button>
        </div>
      )}

      {/* „Senden rückholen" — dieselbe Stelle und dasselbe Muster wie der
          Rückweg beim Verschieben/Löschen, nur mit ablaufender Zeit. Solange
          sie läuft, liegt die Nachricht noch im Ausgang und kommt zurück. */}
      {sendeRueck && (
        <div
          role="status"
          className="fixed bottom-5 left-1/2 z-[70] flex -translate-x-1/2 items-center gap-3 rounded-lg border border-line bg-surface-1 py-2 pr-2 pl-4 shadow-[var(--shadow-3)]"
        >
          <span className="text-[13px] tabular-nums text-fg-1">
            {t('rueck.wird_gesendet', { n: sendeRest })}
          </span>
          <button
            type="button"
            onClick={() => void sendenZurueckholen()}
            className="rounded-md px-2.5 py-1 text-[13px] font-medium text-accent-text transition-colors duration-[var(--dur-fast)] hover:bg-accent-soft"
          >
            {t('aktion.rueckgaengig')}
          </button>
        </div>
      )}

      {/* Der Rückweg. Er ist der Grund, warum Löschen ohne Nachfrage
          auskommt: Nachfragen bei jeder Nachricht erzieht dazu, sie
          wegzuklicken - dann schützen sie nicht mehr. Steht gerade die
          Sende-Leiste da, wartet er - zwei Leisten übereinander liest niemand. */}
      {!sendeRueck && rueckgaengig && (
        <div
          role="status"
          className="fixed bottom-5 left-1/2 z-[70] flex -translate-x-1/2 items-center gap-3 rounded-lg border border-line bg-surface-1 py-2 pr-2 pl-4 shadow-[var(--shadow-3)]"
        >
          <span className="text-[13px] text-fg-1">{rueckgaengig.text}</span>
          <button
            type="button"
            onClick={() => void zurueck()}
            className="rounded-md px-2.5 py-1 text-[13px] font-medium text-accent-text transition-colors duration-[var(--dur-fast)] hover:bg-accent-soft"
          >
            {t('aktion.rueckgaengig')}
          </button>
        </div>
      )}

      {/* Wie viele ausgewählt sind - sonst wirkt eine Aktion überraschend auf
          fünf Nachrichten statt auf eine. */}
      {mehrfach.length > 1 && (
        <div className="fixed bottom-5 left-5 z-[70] flex items-center gap-3 rounded-lg border border-line bg-surface-1 py-2 pr-2 pl-4 shadow-[var(--shadow-2)]">
          <span className="text-[13px] text-fg-1">
            {t('aktion.ausgewaehlt', { count: mehrfach.length })}
          </span>
          <button
            type="button"
            onClick={() => setMehrfach([])}
            className="rounded-md px-2.5 py-1 text-[13px] text-fg-3 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1"
          >
            {t('aktion.auswahl_aufheben')}
          </button>
        </div>
      )}

      {nachfrage}

      <VerfassenFenster
        offen={verfassen.offen}
        art={verfassen.art}
        bezug={verfassen.bezug}
        konten={konten}
        wiederauf={verfassen.wiederauf ?? null}
        aufRueckholbar={(ausgangId, bis, daten) => setSendeRueck({ ausgangId, bis, daten })}
        aufSchliessen={() => setVerfassen((v) => ({ ...v, offen: false }))}
        aufGesendet={() => {
          // Die gesendete Mail liegt jetzt in „Gesendet" - der Ordner soll
          // das auch zeigen, ohne dass man von Hand abgleicht. Und war es
          // ein geplanter Versand, steht er ab jetzt im Postausgang.
          void listeLaden()
          void stammLaden()
          void ausgangLaden()
        }}
      />
    </div>
  )
}
