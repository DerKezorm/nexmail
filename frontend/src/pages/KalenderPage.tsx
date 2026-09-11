/* Der Kalender.
 *
 * Drei Entscheidungen, die man in der Zeichnung sehen soll:
 *
 * 1. **Ein fremder Kalender ist als fremd erkennbar** — Kettensymbol in der
 *    Spalte. In CalDAV schreibt nexmail; nur ein **abonnierter** ICS-Link ist
 *    gesperrt, und dort liegt es am Format: Er bietet keinen Weg zurück.
 * 2. **Wiederholungen stehen als Satz da, nicht als `RRULE`.** „Jede Woche
 *    montags" liest jeder; `FREQ=WEEKLY;BYDAY=MO` niemand.
 * 3. **Bei einer Reihe wird gefragt**, ob ein Termin, die folgenden oder alle
 *    gemeint sind — so hält es jedes Kalenderprogramm, weil das Format keine
 *    andere Antwort kennt.
 *
 * ⚠️ **Geladen wird immer nur das sichtbare Fenster**, mit etwas Rand.
 * Dieselbe Regel wie bei der Nachrichtenliste: Wer alles holt und dann
 * aussiebt, zeigt bei einem vollen Kalender drei Termine und behauptet damit,
 * mehr gebe es nicht.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Download,
  Link2,
  Menu,
  MoreHorizontal,
  Palette,
  PenLine,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Unlink,
  Upload,
  X,
} from 'lucide-react'
import { ApiFehler } from '../api/client'
import {
  kalenderAbgleichen,
  kalenderAendern,
  kalenderEntfernen,
  einladungVersenden,
  kalenderLaden,
  kontenLaden,
  konfliktAufloesen,
  terminAendern,
  terminAnlegen,
  terminEntfernen,
  termineLaden,
  termineSuchen,
} from '../api/laden'
import type { Beteiligter, KalenderZeile, TerminZeile, Umfang } from '../api/laden'
import type { Konto } from '../daten/typen'
import { Button, Checkbox, Dialog, EmptyState, Input, Select } from '../ds'
import { PUNKT_KLASSE } from '../lib/farben'
import { useSchmal } from '../lib/haken'
import { alsDatum, imTag } from '../lib/kalendertage'
import { farbpunkte, monatsraster, nachTagen, tagesliste } from '../lib/kalenderschmal'
import type { Wiederholung } from '../components/Wiederholungsfeld'
import {
  LEERE_WIEDERHOLUNG,
  Wiederholungsfeld,
  alsRrule,
} from '../components/Wiederholungsfeld'
import { Kalendereinfuhr } from '../components/Kalendereinfuhr'
import { Konfliktfenster } from '../components/Konfliktfenster'
import { Kalenderfenster } from '../components/Kalenderfenster'
import { Aktionsblatt } from '../components/Aktionsblatt'
import { Kontextmenue } from '../components/Kontextmenue'
import type { MenueEintrag } from '../components/Kontextmenue'
import { useNachfrage } from '../components/Nachfrage'
import { appPfad } from '../lib/basis'
import {
  endeGezogen,
  minutenAusPixeln,
  tageDazwischen,
  verschobenUmMinuten,
  verschobenUmTage,
} from '../lib/ziehen'
import type { Zeitraum } from '../lib/ziehen'
import { nebeneinander } from '../lib/ueberlappung'

type Sicht = 'monat' | 'woche' | 'tag'

/** Von wann bis wann das Zeitraster reicht. Nachts liegt fast nie etwas, und
 *  volle 24 Stunden drücken den Tag auf Streichholzhöhe. */
const VON_STUNDE = 7
const BIS_STUNDE = 21
/** Höhe einer Stunde im Raster, in Pixeln. */
const STUNDE_PX = 48

/** Ab hier gilt es als Zug und nicht mehr als Klick.
 *
 * ⚠️ **Ohne Schwelle öffnet kein Klick mehr einen Termin.** Eine Maus wackelt
 * beim Drücken um ein, zwei Pixel; jeder dieser Pixel wäre sonst ein
 * Verschieben um null Minuten — und der Klick fiele aus, weil er unterdrückt
 * wird. */
const ZUG_SCHWELLE_PX = 4

/** Der Kalendertag unter dem Zeiger, aus `data-tag` am Spalten- bzw. Tagesfeld.
 *
 * ⚠️ **Über das Element unter dem Zeiger, nicht über gemessene Geometrie.**
 * Spaltenbreiten hängen an Griffen, Rollbalken und der Sprache; wer sie
 * nachrechnet, rechnet irgendwann falsch. Der gezogene Block trägt während des
 * Zuges `pointer-events: none`, sonst fände man immer nur ihn selbst. */
function tagUnterZeiger(x: number, y: number): Date | null {
  const feld = document.elementFromPoint(x, y)?.closest('[data-tag]')
  const wert = feld?.getAttribute('data-tag')
  if (!wert) return null
  const [j, m, t] = wert.split('-').map(Number)
  return new Date(j, m - 1, t)
}

/** Der Kalendertag, an dem ein Vorkommen hängt — als Ortszeit-Datum. */
function tagVon(e: TerminZeile): Date {
  if (e.ganztaegig) {
    const [j, m, t] = e.beginn.slice(0, 10).split('-').map(Number)
    return new Date(j, m - 1, t)
  }
  const d = new Date(e.beginn)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

interface Zug {
  /** Das gezogene Vorkommen — bei einer Reihe ist `id` allein nicht eindeutig. */
  ur: TerminZeile
  beginn: string
  ende: string
}

/** Ziehen und an der Kante längermachen.
 *
 * ⚠️ **Die Tastatur verliert nichts.** Die Blöcke bleiben Schaltflächen mit
 * ihrem `onClick`; wer nicht ziehen kann, ändert den Termin wie bisher im
 * Formular. Ziehen ist ein zweiter Weg, kein Ersatz.
 */
function useZiehen(aufFertig: (t: TerminZeile, z: Zeitraum) => void) {
  const [zug, setZug] = useState<Zug | null>(null)
  /** Wurde wirklich gezogen? Verhindert, dass der Zug als Klick ankommt. */
  const gezogen = useRef(false)

  const starten = useCallback(
    (
      ereignis: React.PointerEvent,
      termin: TerminZeile,
      art: 'ganz' | 'kante',
      stundeHoehe: number | null,
    ) => {
      // Nur die linke Taste; ein Rechtsklick gehört dem Kontextmenü.
      if (ereignis.button !== 0) return
      /* ⚠️ **Nicht mit dem Finger.** Dieselbe Geste rollt dort die Ansicht.
         Wer beides will, muss `touch-action: none` setzen und das Rollen
         selbst nachbauen — dann rollt der Kalender am Telefon nicht mehr,
         und das ist der teurere Verlust. Genau die umgekehrte Entscheidung
         wie in `lib/wischen.ts`, wo der Wisch **nur** dem Finger gehört.
         Am Telefon bleibt der Block eine Schaltfläche und öffnet das
         Formular; verloren geht dort nichts, nur der zweite Weg. */
      if (ereignis.pointerType === 'touch') return
      ereignis.preventDefault()
      ereignis.stopPropagation()
      const startX = ereignis.clientX
      const startY = ereignis.clientY
      const ursprung = tagVon(termin)
      gezogen.current = false
      let letzter: Zug | null = null

      function bewegen(e: PointerEvent) {
        const dx = e.clientX - startX
        const dy = e.clientY - startY
        if (!gezogen.current && Math.hypot(dx, dy) < ZUG_SCHWELLE_PX) return
        gezogen.current = true

        let neu: Zeitraum = { beginn: termin.beginn, ende: termin.ende }
        if (art === 'kante' && stundeHoehe) {
          neu = endeGezogen(neu, minutenAusPixeln(dy, stundeHoehe))
        } else {
          /* ⚠️ **Erst die Tage, dann die Minuten.** Der Tagessprung hält die
             Wanduhr fest, die Minuten sind eine Dauer — siehe `lib/ziehen.ts`.
             Andersherum verschöbe die Zeitumstellung das Ergebnis. */
          const ziel = tagUnterZeiger(e.clientX, e.clientY)
          if (ziel) neu = verschobenUmTage(neu, tageDazwischen(ursprung, ziel), termin.ganztaegig)
          if (stundeHoehe && !termin.ganztaegig) {
            neu = verschobenUmMinuten(neu, minutenAusPixeln(dy, stundeHoehe))
          }
        }
        letzter = { ur: termin, ...neu }
        setZug(letzter)
      }

      function loslassen() {
        window.removeEventListener('pointermove', bewegen)
        window.removeEventListener('pointerup', loslassen)
        window.removeEventListener('pointercancel', loslassen)
        setZug(null)
        /* ⚠️ **Nur bei echter Änderung hinausschicken.** Ein Zug, der wieder
           an seinem Ausgangspunkt endet, wäre sonst ein Schreibvorgang auf dem
           Server — bei einer Reihe samt Rückfrage „dieser · folgende · alle".
           Für nichts. */
        if (letzter && (letzter.beginn !== termin.beginn || letzter.ende !== termin.ende)) {
          aufFertig(termin, { beginn: letzter.beginn, ende: letzter.ende })
        }
      }

      window.addEventListener('pointermove', bewegen)
      window.addEventListener('pointerup', loslassen)
      window.addEventListener('pointercancel', loslassen)
    },
    [aufFertig],
  )

  /** Im Zug steht die Vorschau an der Stelle des Originals. */
  const mitVorschau = useCallback(
    (liste: TerminZeile[]): TerminZeile[] =>
      zug
        ? liste.map((e) =>
            e.id === zug.ur.id && e.beginn === zug.ur.beginn
              ? { ...e, beginn: zug.beginn, ende: zug.ende }
              : e,
          )
        : liste,
    [zug],
  )

  /** Der Klick nach einem Zug gehört nicht dem Öffnen. */
  const warEinZug = useCallback(() => {
    if (!gezogen.current) return false
    gezogen.current = false
    return true
  }, [])

  return { zug, starten, mitVorschau, warEinZug }
}

export function KalenderPage() {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [sicht, setSicht] = useState<Sicht>('monat')
  const [anker, setAnker] = useState(() => new Date())
  const [kalender, setKalender] = useState<KalenderZeile[] | null>(null)
  /* Die Postfächer — nur für die Absenderwahl der Einladung.
     ⚠️ **Ein Kalender gehört zu keinem Postfach.** Die Adresse, unter der
     eingeladen wird, muss deshalb gewählt werden; der Server prüft sie. */
  const [postfaecher, setPostfaecher] = useState<Konto[]>([])
  const [termine, setTermine] = useState<TerminZeile[]>([])
  const [fehler, setFehler] = useState('')
  const [offen, setOffen] = useState<TerminZeile | null>(null)
  const [neuAb, setNeuAb] = useState<{ beginn: Date; ganztaegig: boolean } | null>(null)
  const [kalenderNeu, setKalenderNeu] = useState(false)
  const [menue, setMenue] = useState<{ x: number; y: number; eintraege: MenueEintrag[] } | null>(
    null,
  )
  const [gleichtAb, setGleichtAb] = useState(false)
  const [einspielenIn, setEinspielenIn] = useState<KalenderZeile | null>(null)
  /* Die Suche. `wort` ist, was im Feld steht; `suche` ist das Ergebnis —
     `null` heißt „es wird gerade nicht gesucht", die Ansicht bleibt das
     Raster. */
  const [wort, setWort] = useState('')
  const [suche, setSuche] = useState<{
    treffer: TerminZeile[]
    abgeschnitten: boolean
  } | null>(null)
  const [stand, setStand] = useState('')
  const [reihenfrage, setReihenfrage] = useState<{
    titel: string
    was: 'aendern' | 'loeschen'
    weiter: (u: Umfang) => void
  } | null>(null)

  /* Schmal gibt es nur den Monat: Das Fenster folgt dann dem Monat, egal was
     am Schreibtisch zuletzt gewählt war — sonst lüde die Telefonansicht die
     Termine einer Woche und zeigte im Raster leere Tage. */
  const schmal = useSchmal()
  const [von, bis] = useMemo(
    () => spanne(anker, schmal ? 'monat' : sicht),
    [anker, sicht, schmal],
  )
  const sichtbare = useMemo(
    () => (kalender ?? []).filter((k) => k.sichtbar).map((k) => k.id),
    [kalender],
  )
  const nachId = useMemo(() => new Map((kalender ?? []).map((k) => [k.id, k])), [kalender])

  /** ⚠️ **Der Server nennt eine Kennung, die Oberfläche übersetzt.** Eine rohe
   *  Meldung durchzureichen hieße: auf Englisch bleibt sie deutsch. */
  const melden = useCallback(
    (f: unknown) => {
      const kennung = f instanceof ApiFehler ? f.detail : ''
      const schluessel = `kalender.fehler_${kennung}`
      setFehler(i18n.exists(schluessel) ? t(schluessel) : t('kalender.fehler_allgemein'))
    },
    [i18n, t],
  )

  const stammLaden = useCallback(async () => {
    try {
      // ⚠️ Ein Fehlschlag bei den Postfächern darf den Kalender nicht kosten;
      // ohne sie fehlt nur die Absenderwahl.
      void kontenLaden().then(setPostfaecher).catch(() => undefined)
      setKalender(await kalenderLaden())
    } catch {
      setKalender([])
      setFehler(t('kalender.laden_fehler'))
    }
  }, [t])

  const termineHolen = useCallback(async () => {
    if (kalender === null) return
    if (sichtbare.length === 0) {
      setTermine([])
      return
    }
    try {
      setTermine(await termineLaden(von, bis, sichtbare))
      setFehler('')
    } catch (f) {
      melden(f)
    }
  }, [kalender, sichtbare, von, bis, melden])

  /* Die Suche läuft beim Tippen, mit einer kurzen Pause dazwischen.
   *
   * ⚠️ **Ohne Pause eine Abfrage je Tastendruck.** „Besprechung" wären zwölf,
   * von denen elf schon veraltet sind, bevor die Antwort da ist — und die
   * Suche liest die Termintabelle.
   *
   * ⚠️ **Erst ab zwei Zeichen.** Ein einzelner Buchstabe trifft fast alles;
   * das Ergebnis wäre der abgeschnittene Deckel und keine Antwort.
   */
  useEffect(() => {
    const gesucht = wort.trim()
    if (gesucht.length < 2) {
      setSuche(null)
      return
    }
    let gilt = true
    const uhr = setTimeout(() => {
      void termineSuchen(gesucht, sichtbare)
        .then((e) => {
          // ⚠️ Eine verspätete Antwort darf ein neueres Ergebnis nicht
          // überschreiben — sonst steht nach dem Tippen der vorletzte Stand da.
          if (gilt) setSuche(e)
        })
        .catch((f) => {
          if (gilt) melden(f)
        })
    }, 250)
    return () => {
      gilt = false
      clearTimeout(uhr)
    }
  }, [wort, sichtbare, melden])

  useEffect(() => {
    void stammLaden()
  }, [stammLaden])
  useEffect(() => {
    void termineHolen()
  }, [termineHolen])

  async function jetztAbgleichen() {
    if (gleichtAb) return
    setGleichtAb(true)
    try {
      const bericht = await kalenderAbgleichen()
      await stammLaden()
      await termineHolen()
      const bewegt = bericht.neu + bericht.geaendert + bericht.entfernt
      setStand(
        bewegt
          ? t('kalender.abgleich_fertig', {
              neu: bericht.neu,
              geaendert: bericht.geaendert,
              entfernt: bericht.entfernt,
            })
          : t('kalender.abgleich_nichts'),
      )
    } catch (f) {
      melden(f)
    } finally {
      setGleichtAb(false)
    }
  }

  /** Einen Kalender ein- oder ausblenden — Spalte am Schreibtisch und Schublade
   *  am Telefon gehen denselben Weg. Sofort umschalten, damit der Haken nicht
   *  hakt; die gezählte Wahrheit holt der nächste Abruf. */
  async function sichtbarSetzen(k: KalenderZeile, an: boolean) {
    setKalender((alt) => (alt ?? []).map((x) => (x.id === k.id ? { ...x, sichtbar: an } : x)))
    try {
      await kalenderAendern(k.id, { sichtbar: an })
    } catch (f) {
      melden(f)
      await stammLaden()
    }
  }

  function schieben(richtung: number) {
    const d = new Date(anker)
    if (sicht === 'monat') d.setMonth(d.getMonth() + richtung)
    else if (sicht === 'woche') d.setDate(d.getDate() + 7 * richtung)
    else d.setDate(d.getDate() + richtung)
    setAnker(d)
  }

  function mitUmfang(termin: TerminZeile, was: 'aendern' | 'loeschen', tun: (u: Umfang) => void) {
    if (!termin.ausReihe) {
      tun('alle')
      return
    }
    setReihenfrage({ titel: termin.titel, was, weiter: tun })
  }

  /** Ein gezogener Termin — derselbe Weg wie „Speichern" im Formular.
   *
   * ⚠️ **Nur Beginn und Ende gehen hinaus.** Kein `rrule`, kein Titel: Ein
   * nicht mitgeschicktes Feld lässt der Server unverändert, und ein Zug ist
   * eine Aussage über die Zeit und über sonst nichts.
   *
   * ⚠️ **Beide Enden, obwohl der Server auch mit einem zurechtkäme.**
   * `termine.aendern` hält die Dauer, wenn nur der Beginn ankommt — am
   * 04.09.2026 nachgemessen, weil eine Mutationsprobe genau daran vorbeilief.
   * Geschickt werden trotzdem beide: Beim Ziehen an der Kante ändert sich nur
   * das Ende, und eine Stelle, die je nach Geste etwas anderes schickt, ist
   * eine Stelle mehr, an der man sich irren kann.
   *
   * ⚠️ **Bei einer Reihe wird gefragt.** Ein Zug ist billiger als ein
   * Formular, und genau deshalb muss die Frage bleiben: Sonst verschiebt eine
   * Handbewegung fünfzig Termine.
   *
   * ⚠️ **Nach einem Fehlschlag wird neu geladen.** Sonst bliebe der Block an
   * der neuen Stelle stehen, obwohl der Server abgelehnt hat — die Anzeige
   * behauptete etwas, das nirgends steht.
   */
  function verschieben(termin: TerminZeile, wohin: Zeitraum) {
    mitUmfang(termin, 'aendern', (umfang) => {
      void (async () => {
        try {
          await terminAendern(termin.id, {
            beginn: wohin.beginn,
            ende: wohin.ende,
            umfang,
            vorkommen: termin.beginn,
          })
        } catch (f) {
          melden(f)
        }
        await termineHolen()
      })()
    })
  }

  /** Nach dem Speichern fragen, ob die Einladung wirklich hinausgeht.
   *
   * ⚠️ **Auch beim Ändern gefragt.** Wer einen Tippfehler in der Notiz
   * ausbessert, schickt sonst allen eine neue Einladung — und das merkt er
   * erst an den Rückfragen. Der Termin ist zu diesem Zeitpunkt schon
   * gespeichert; „Nur speichern" verliert also nichts.
   */
  /** ⚠️ **Beim zweiten Mal steht etwas anderes da.** Eine „Einladung
   *  verschicken?" bei einem Termin, zu dem alle schon eingeladen sind, liest
   *  sich wie ein Versehen — verschickt wird eine Aktualisierung, und die
   *  Gegenstelle zeigt sie auch so an. */
  async function einladenFragen(
    terminId: number,
    anzahl: number,
    von: string,
    schonEingeladen = false,
  ) {
    const ja = await fragen({
      titel: t(schonEingeladen ? 'kalender.neueinladen_frage' : 'kalender.einladen_frage'),
      text: t(schonEingeladen ? 'kalender.neueinladen_text' : 'kalender.einladen_text', {
        count: anzahl,
        von,
      }),
      knopf: t(schonEingeladen ? 'kalender.neueinladen_knopf' : 'kalender.einladen_knopf'),
    })
    if (!ja) return
    try {
      await einladungVersenden(terminId)
    } catch (f) {
      melden(f)
    }
  }

  /** Vor dem Löschen: soll den Eingeladenen abgesagt werden?
   *
   * Gibt `null` zurück, wenn gar nicht gelöscht werden soll — sonst kostete
   * ein Zögern bei der Absage den Termin.
   *
   * ⚠️ **Der Haken ist hier vorbelegt, anders als sonst in `Nachfrage`.**
   * Die Hausregel dort („anhaken, nicht abwählen") gilt für Dinge, die
   * zusätzlich gelöscht werden — dort ist Vergessen harmlos. Hier ist es
   * umgekehrt: Ein gelöschter Termin ist nur bei uns gelöscht. Wer die Absage
   * vergisst, lässt alle anderen zum Termin erscheinen.
   */
  async function absageFragen(anzahl: number): Promise<boolean | null> {
    const antwort = await fragen({
      titel: t('kalender.absage_frage'),
      text: t('kalender.absage_text', { count: anzahl }),
      knopf: t('aktion.loeschen'),
      gefaehrlich: true,
      haken: { beschriftung: t('kalender.absage_haken'), vorgabe: true },
    })
    if (!antwort || typeof antwort !== 'object') return null
    return antwort.haken
  }

  function kalenderMenue(k: KalenderZeile): MenueEintrag[] {
    return [
      {
        id: 'umbenennen',
        text: t('kalender.umbenennen'),
        symbol: <PenLine />,
        tun: () =>
          void (async () => {
            const name = await fragen({
              titel: t('kalender.umbenennen'),
              text: t('kalender.umbenennen_frage'),
              eingabe: { beschriftung: t('kalender.name'), vorgabe: k.name },
              knopf: t('aktion.speichern'),
            })
            if (typeof name !== 'string' || !name.trim()) return
            try {
              await kalenderAendern(k.id, { name: name.trim() })
              await stammLaden()
            } catch (f) {
              melden(f)
            }
          })(),
      },
      {
        id: 'farbe',
        text: t('kalender.farbe_aendern'),
        symbol: <Palette />,
        // Die nächste der sechs geprüften Farben — zugeteilt, nicht gemischt.
        tun: () =>
          void (async () => {
            try {
              await kalenderAendern(k.id, { farbe: (k.farbe % 6) + 1 })
              await stammLaden()
            } catch (f) {
              melden(f)
            }
          })(),
      },
      {
        id: 'herunterladen',
        trennerDavor: true,
        text: t('kalender.ics_herunterladen'),
        symbol: <Download />,
        /* ⚠️ **Über `window.location`, nicht über `fetch`.** Sonst läge die
           Datei erst als Blob im Speicher des Browsers, und der Weg zum
           Speichern-Dialog wäre selbst gebaut — dieselbe Entscheidung wie beim
           mbox-Download. */
        tun: () => {
          window.location.href = appPfad(`/api/kalender/${k.id}/ics`)
        },
      },
      /* ⚠️ **Einspielen nur, wo es auch ankommt.** Bei einem CalDAV-Kalender
         gilt „erst der Server, dann die eigene Datenbank"; ein Eintrag, der zu
         einer Absage führt, ist schlechter als keiner. */
      ...(k.art
        ? []
        : [
            {
              id: 'einspielen',
              text: t('kalender.ics_einspielen'),
              symbol: <Upload />,
              tun: () => setEinspielenIn(k),
            },
          ]),
      {
        id: 'entfernen',
        trennerDavor: true,
        text: k.art ? t('kalender.trennen') : t('kalender.entfernen'),
        symbol: k.art ? <Unlink /> : <Trash2 />,
        gefaehrlich: true,
        tun: () =>
          void (async () => {
            const drin = termine.filter((e) => e.kalenderId === k.id).length
            const ja = await fragen({
              titel: t('kalender.entfernen_frage', { name: k.name }),
              /* ⚠️ Bei einer Gegenstelle sagt die Rückfrage, dass dort nichts
                 gelöscht wird. Ohne den Satz klingt „entfernen" nach „weg". */
              text:
                t('kalender.entfernen_sicher', { count: drin }) +
                (k.art ? ` ${t('kalender.entfernen_gegenstelle', { wo: k.herkunft })}` : ''),
              knopf: k.art ? t('kalender.trennen') : t('kalender.entfernen'),
              gefaehrlich: true,
            })
            if (ja !== true) return
            try {
              await kalenderEntfernen(k.id)
              await stammLaden()
            } catch (f) {
              melden(f)
            }
          })(),
      },
    ]
  }

  const titel =
    sicht === 'tag'
      ? anker.toLocaleDateString(i18n.language, { day: 'numeric', month: 'long', year: 'numeric' })
      : anker.toLocaleDateString(i18n.language, { month: 'long', year: 'numeric' })

  return (
    <div className="flex min-h-0 flex-1">
      {schmal ? (
        <KalenderSchmal
          anker={anker}
          aufAnker={setAnker}
          termine={termine}
          kalender={kalender ?? []}
          nachId={nachId}
          leer={kalender !== null && kalender.length === 0}
          aufTermin={setOffen}
          aufNeu={(d) =>
            setNeuAb({
              beginn:
                d.toDateString() === new Date().toDateString()
                  ? naechsteVolleStunde()
                  : mitTag(d, 9),
              ganztaegig: false,
            })
          }
          aufSichtbar={(k, an) => void sichtbarSetzen(k, an)}
          kalenderEintraege={kalenderMenue}
          aufKalenderNeu={() => setKalenderNeu(true)}
          aufAbgleichen={() => void jetztAbgleichen()}
          gleichtAb={gleichtAb}
          wort={wort}
          aufWort={setWort}
          suchergebnis={
            suche !== null ? (
              <Trefferliste
                treffer={suche.treffer}
                abgeschnitten={suche.abgeschnitten}
                kalender={nachId}
                aufTermin={(termin) => {
                  setAnker(new Date(termin.beginn))
                  setOffen(termin)
                  setWort('')
                }}
              />
            ) : null
          }
        />
      ) : (
      <>
      {/* --- Die Kalenderspalte ------------------------------------------ */}
      <aside className="flex w-[240px] shrink-0 flex-col gap-4 border-r border-line-subtle bg-surface-1 p-3">
        <Button
          variant="primary"
          fullWidth
          iconLeft={<CalendarPlus className="size-4" />}
          disabled={!(kalender ?? []).some((k) => !k.nurLesen)}
          onClick={() => setNeuAb({ beginn: naechsteVolleStunde(), ganztaegig: false })}
        >
          {t('kalender.neuer_termin')}
        </Button>

        <div className="flex flex-col gap-1">
          <h2 className="px-1 pb-1 text-[11px] font-semibold tracking-wide text-fg-4 uppercase">
            {t('kalender.meine')}
          </h2>
          {(kalender ?? []).map((k) => (
            /* ⚠️ **Der Farbfleck steht VOR dem Haken, nicht dahinter.** Der
               Haken sagt „wird angezeigt", der Fleck sagt „so sieht er im
               Raster aus" — zwei Aussagen, und die Farbe ist die, nach der man
               sucht. Thunderbird hält es genauso. */
            <div
              key={k.id}
              className="flex items-center gap-2 rounded-md px-1 py-1.5 hover:bg-surface-3"
              /* ⚠️ Dieselbe Bedienung wie am Ordner nebenan. Eine Liste, die
                 sich anders bedienen lässt als die Liste daneben, ist ein
                 Fehler — dasselbe hat der OIDC-Reiter schon einmal gekostet. */
              onContextMenu={(e) => {
                e.preventDefault()
                setMenue({ x: e.clientX, y: e.clientY, eintraege: kalenderMenue(k) })
              }}
            >
              <span aria-hidden className={`size-2.5 shrink-0 rounded-sm ${PUNKT_KLASSE[k.farbe]}`} />
              <span className="min-w-0 flex-1 truncate text-[13px]">
                <Checkbox
                  label={k.name}
                  checked={k.sichtbar}
                  onCheckedChange={(an) => void sichtbarSetzen(k, an)}
                />
              </span>
              {/* ⚠️ **Der Fehler steht am Kalender, nicht in einem Banner.**
                  Bei fünf verbundenen Kalendern sagt „Abgleich fehlgeschlagen"
                  nicht, welcher — und man sucht am falschen. */}
              {k.letzterFehler ? (
                <span
                  title={
                    i18n.exists(`kalender.fehler_${k.letzterFehler}`)
                      ? t(`kalender.fehler_${k.letzterFehler}`)
                      : t('kalender.fehler_allgemein')
                  }
                >
                  <AlertTriangle aria-hidden className="size-3.5 shrink-0 text-warning" />
                </span>
              ) : (
                k.art && (
                  <span title={`${k.herkunft}${k.nurLesen ? ` · ${t('kalender.nur_lesen')}` : ''}`}>
                    <Link2 aria-hidden className="size-3.5 shrink-0 text-fg-4" />
                  </span>
                )
              )}
            </div>
          ))}
        </div>

        <Button variant="ghost" size="sm" fullWidth onClick={() => setKalenderNeu(true)}>
          {t('kalender.hinzufuegen')}
        </Button>

        {/* ⚠️ Der Satz steht dort, wo die abonnierten Kalender stehen — und
            nur, wenn es wirklich einen gibt: ein Hinweis ohne Anlass wird nach
            dem zweiten Mal überlesen. */}
        {(kalender ?? []).some((k) => k.nurLesen) && (
          <p className="mt-auto text-[11px] leading-relaxed text-fg-4">
            {t('kalender.nur_lesen_hinweis')}
          </p>
        )}
      </aside>

      {/* --- Der Hauptbereich -------------------------------------------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-line-subtle px-4 py-2.5">
          <div className="flex items-center gap-1">
            <IconKnopf label={t('kalender.zurueck')} onClick={() => schieben(-1)}>
              <ChevronLeft />
            </IconKnopf>
            <IconKnopf label={t('kalender.vor')} onClick={() => schieben(1)}>
              <ChevronRight />
            </IconKnopf>
          </div>
          <Button variant="secondary" size="sm" onClick={() => setAnker(new Date())}>
            {t('kalender.heute')}
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-fg-1">{titel}</h1>

          {/* ⚠️ Nur, wenn es überhaupt etwas abzugleichen gibt. Ein Knopf, der
              bei einem rein eigenen Kalender nichts tun kann, verwirrt. */}
          {(kalender ?? []).some((k) => k.art) && (
            <IconKnopf
              label={gleichtAb ? t('kalender.abgleich_laeuft') : t('kalender.abgleichen')}
              onClick={() => void jetztAbgleichen()}
            >
              <RefreshCw className={gleichtAb ? 'animate-spin' : undefined} />
            </IconKnopf>
          )}

          {/* ⚠️ **Oben im Kopf, nicht in der Kalenderspalte.** Es sucht über
              alle sichtbaren Kalender; in der Spalte stünde es neben den
              einzelnen und sähe aus, als gehörte es zu einem davon. */}
          <div className="relative w-44 shrink-0">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-fg-4"
            />
            <input
              type="search"
              value={wort}
              onChange={(e) => setWort(e.target.value)}
              placeholder={t('kalender.suchen')}
              aria-label={t('kalender.suchen')}
              className="fokusrahmen h-[var(--control-h-sm)] w-full rounded-md border border-line bg-surface-3 pr-2 pl-7 text-[13px] text-fg-1 outline-none transition-[border-color,box-shadow] duration-[var(--dur-fast)] placeholder:text-fg-4 focus:border-accent focus:shadow-[var(--focus-ring)]"
            />
          </div>

          <div className="flex shrink-0 rounded-md border border-line p-0.5">
            {(['monat', 'woche', 'tag'] as Sicht[]).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={sicht === s}
                onClick={() => setSicht(s)}
                className={
                  'rounded-sm px-2.5 py-1 text-[12px] transition-colors duration-[var(--dur-fast)] ' +
                  (sicht === s
                    ? 'bg-accent-soft text-accent-text'
                    : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
                }
              >
                {t(`kalender.sicht_${s}`)}
              </button>
            ))}
          </div>
        </div>

        {suche !== null ? (
          <Trefferliste
            treffer={suche.treffer}
            abgeschnitten={suche.abgeschnitten}
            kalender={nachId}
            aufTermin={(termin) => {
              /* ⚠️ **Hinspringen UND öffnen.** Nur zu öffnen ließe die Frage
                 „wann ist das?" offen; nur hinzuspringen zwänge, den Termin im
                 Raster noch einmal zu suchen. */
              setAnker(new Date(termin.beginn))
              setOffen(termin)
              setWort('')
            }}
          />
        ) : kalender !== null && kalender.length === 0 ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              title={t('kalender.leer')}
              description={t('kalender.leer_text')}
              action={
                <Button variant="primary" onClick={() => setKalenderNeu(true)}>
                  {t('kalender.hinzufuegen')}
                </Button>
              }
            />
          </div>
        ) : sicht === 'monat' ? (
          <Monat
            anker={anker}
            termine={termine}
            kalender={nachId}
            aufTermin={setOffen}
            aufLeer={(d) => setNeuAb({ beginn: d, ganztaegig: true })}
            aufVerschieben={verschieben}
          />
        ) : (
          <Raster
            anker={anker}
            tage={sicht === 'woche' ? 7 : 1}
            termine={termine}
            kalender={nachId}
            aufTermin={setOffen}
            aufLeer={(d) => setNeuAb({ beginn: d, ganztaegig: false })}
            aufVerschieben={verschieben}
          />
        )}
      </div>
      </>
      )}

      {menue && (
        <Kontextmenue
          x={menue.x}
          y={menue.y}
          eintraege={menue.eintraege}
          aufSchliessen={() => setMenue(null)}
        />
      )}

      {einspielenIn && (
        <Kalendereinfuhr
          kalenderId={einspielenIn.id}
          kalenderName={einspielenIn.name}
          aufFertig={() => void termineHolen()}
          aufSchliessen={() => setEinspielenIn(null)}
        />
      )}

      {kalenderNeu && (
        <Kalenderfenster
          vorhanden={kalender ?? []}
          onClose={() => setKalenderNeu(false)}
          onFertig={() => void stammLaden()}
        />
      )}

      {(offen || neuAb) && (
        <Terminfenster
          key={offen ? `${offen.id}-${offen.beginn}` : 'neu'}
          termin={offen}
          vorgabe={neuAb}
          kalender={(kalender ?? []).filter((k) => !k.nurLesen)}
          gesperrt={Boolean(offen && nachId.get(offen.kalenderId)?.nurLesen)}
          herkunft={offen ? (nachId.get(offen.kalenderId)?.herkunft ?? '') : ''}
          postfaecher={postfaecher}
          aufEinladen={einladenFragen}
          aufAbsage={absageFragen}
          aufFehler={melden}
          aufUmfang={mitUmfang}
          onClose={() => {
            setOffen(null)
            setNeuAb(null)
          }}
          onFertig={() => {
            setOffen(null)
            setNeuAb(null)
            void termineHolen()
          }}
        />
      )}

      {reihenfrage && (
        <Reihenfrage
          titel={reihenfrage.titel}
          was={reihenfrage.was}
          onClose={() => setReihenfrage(null)}
          aufWahl={(u) => {
            const weiter = reihenfrage.weiter
            setReihenfrage(null)
            weiter(u)
          }}
        />
      )}

      {stand && !fehler && (
        <div
          role="status"
          className="fixed bottom-5 left-1/2 z-[70] flex -translate-x-1/2 items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-2 shadow-[var(--shadow-3)]"
          onAnimationEnd={() => setStand('')}
        >
          <span className="text-[13px] text-fg-2">{stand}</span>
          <button
            type="button"
            className="text-[12px] text-fg-4 hover:text-fg-1"
            onClick={() => setStand('')}
          >
            {t('aktion.schliessen')}
          </button>
        </div>
      )}

      {fehler && (
        <div
          role="alert"
          className="fixed bottom-5 left-1/2 z-[71] flex -translate-x-1/2 items-center gap-3 rounded-lg border border-danger bg-danger-soft px-4 py-2 shadow-[var(--shadow-3)]"
        >
          <span className="text-[13px] text-danger">{fehler}</span>
        </div>
      )}

      {nachfrage}
    </div>
  )
}

/* --- Die Frage bei einer Reihe ------------------------------------------ */

/** ⚠️ **Drei Ausgänge, und sie tun wirklich Verschiedenes** — das ist die
 *  Ausnahme von „ein Fenster, ein Ausgang". Jedes Kalenderprogramm fragt genau
 *  das, weil das Format keine andere Antwort kennt. */
function Reihenfrage({
  titel,
  was,
  onClose,
  aufWahl,
}: {
  titel: string
  was: 'aendern' | 'loeschen'
  onClose: () => void
  aufWahl: (u: Umfang) => void
}) {
  const { t } = useTranslation()
  return (
    <Dialog
      open
      width={440}
      title={t('kalender.umfang_titel')}
      description={t(`kalender.umfang_frage_${was}`, { titel })}
      onClose={onClose}
      /* ⚠️ **Abbrechen gehört in den Fuß, nicht zwischen die Wahlmöglichkeiten.**
         Der Dialog blendet sein Kreuz nur aus, wenn unten ein Ausgang steht —
         sonst stünden zwei nebeneinander, die dasselbe tun. Genau die Regel,
         die das Design-System erzwingt. */
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('aktion.abbrechen')}
        </Button>
      }
    >
      <div className="flex flex-col gap-2">
        {(['dieser', 'folgende', 'alle'] as Umfang[]).map((u) => (
          <Button
            key={u}
            variant={u === 'dieser' ? 'primary' : 'secondary'}
            fullWidth
            onClick={() => aufWahl(u)}
          >
            {t(`kalender.umfang_${u}`)}
          </Button>
        ))}
      </div>
    </Dialog>
  )
}

/* --- Die Trefferliste ---------------------------------------------------- */

/** Was die Suche gefunden hat.
 *
 * ⚠️ **Eine Liste, kein Raster.** Treffer liegen über Jahre verstreut; in ein
 * Raster gezeichnet sähe man immer nur den einen Monat, in dem man gerade
 * steht — also fast nie den gesuchten Termin.
 */
function Trefferliste({
  treffer,
  abgeschnitten,
  kalender,
  aufTermin,
}: {
  treffer: TerminZeile[]
  abgeschnitten: boolean
  kalender: Map<string, KalenderZeile>
  aufTermin: (t: TerminZeile) => void
}) {
  const { t, i18n } = useTranslation()

  if (treffer.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState title={t('kalender.suche_leer')} description={t('kalender.suche_leer_text')} />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="px-4 py-2 text-[12px] text-fg-4">
        {t('kalender.suche_treffer', { count: treffer.length })}
      </div>
      {treffer.map((e) => (
        <button
          key={`${e.id}-${e.beginn}`}
          type="button"
          onClick={() => aufTermin(e)}
          className="flex items-start gap-2.5 border-b border-line-subtle px-4 py-2.5 text-left hover:bg-surface-3"
        >
          <span
            aria-hidden
            className={`mt-1.5 size-2 shrink-0 rounded-pill ${
              PUNKT_KLASSE[kalender.get(e.kalenderId)?.farbe ?? 1]
            }`}
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] text-fg-1">{e.titel}</span>
            <span className="block truncate text-[12px] text-fg-4">
              {new Date(e.beginn).toLocaleDateString(i18n.language, {
                weekday: 'short',
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })}
              {!e.ganztaegig && ` · ${uhrzeit(e.beginn, i18n.language)}`}
              {e.ort && ` · ${e.ort}`}
            </span>
          </span>
          {/* ⚠️ **Bei einer Reihe steht das NÄCHSTE Vorkommen da**, und das
              muss man sehen — sonst hält man das Datum für den einzigen
              Termin dieser Sorte. */}
          {e.ausReihe && (
            <span className="mt-0.5 shrink-0 text-[11px] text-fg-4">
              {t('kalender.suche_reihe')}
            </span>
          )}
        </button>
      ))}
      {/* ⚠️ **Abgeschnitten wird gesagt.** Sonst ist „mehr gibt es nicht" von
          „mehr wird nicht gezeigt" nicht zu unterscheiden — dieselbe Regel wie
          am Fuß der Nachrichtenliste. */}
      {abgeschnitten && (
        <div className="px-4 py-2.5 text-[12px] text-fg-4">{t('kalender.suche_mehr')}</div>
      )}
    </div>
  )
}

/* --- Die schmale Ansicht (Telefon) --------------------------------------- */

/** Der Kalender auf dem Telefon: der Monat als Raster mit Punkten und darunter
 *  die Termine des angetippten Tages, oder die fortlaufende Terminübersicht.
 *  Die Kalenderliste wohnt in einer Schublade wie die Ordner bei der Post,
 *  „Neuer Termin" ist der runde Knopf unten rechts. Vorher als klickbare
 *  Attrappe abgestimmt.
 *
 *  ⚠️ **Kein Wochen- und kein Tagesraster am Telefon.** Auf 375 px ist die
 *  Stundenspalte die halbe Breite, und Ziehen gibt es am Finger ohnehin nicht
 *  (siehe „Termine ziehen"). Die Uhrzeit steht in der Liste; wer sie ändern
 *  will, öffnet den Termin.
 *
 *  ⚠️ **Der gewählte Tag hängt am Monat.** Wechselt der Monat über die Pfeile
 *  oder „Heute", wandert er mit — sonst zeigte die Liste unten einen Tag, den
 *  das Raster darüber nicht zeigt. Ein Tipp auf einen Tag des Nachbarmonats
 *  wechselt den Monat gleich mit. */
function KalenderSchmal({
  anker,
  aufAnker,
  termine,
  kalender,
  nachId,
  leer,
  aufTermin,
  aufNeu,
  aufSichtbar,
  kalenderEintraege,
  aufKalenderNeu,
  aufAbgleichen,
  gleichtAb,
  wort,
  aufWort,
  suchergebnis,
}: {
  anker: Date
  aufAnker: (d: Date) => void
  termine: TerminZeile[]
  kalender: KalenderZeile[]
  nachId: Map<string, KalenderZeile>
  /** Es gibt noch gar keinen Kalender — dann steht die Einladung da. */
  leer: boolean
  aufTermin: (t: TerminZeile) => void
  aufNeu: (tag: Date) => void
  aufSichtbar: (k: KalenderZeile, an: boolean) => void
  /** ⚠️ Dieselben Einträge wie im Kontextmenü am Schreibtisch — eine Quelle,
      zwei Formen, wie beim Aktionsblatt der Post. Am Telefon gibt es keinen
      Rechtsklick; ohne den Knopf gab es umbenennen, Farbe, ICS und trennen
      dort gar nicht (0.12.0). */
  kalenderEintraege: (k: KalenderZeile) => MenueEintrag[]
  aufKalenderNeu: () => void
  aufAbgleichen: () => void
  gleichtAb: boolean
  wort: string
  aufWort: (w: string) => void
  suchergebnis: React.ReactNode
}) {
  const { t, i18n } = useTranslation()
  const [sicht, setSicht] = useState<'monat' | 'liste'>('monat')
  const [gewaehlt, setGewaehlt] = useState(() => new Date(anker))
  const [schublade, setSchublade] = useState(false)
  const [suchtSichtbar, setSuchtSichtbar] = useState(false)
  /* Der Kalender, dessen Menü als Blatt offen ist. */
  const [blatt, setBlatt] = useState<KalenderZeile | null>(null)

  useEffect(() => {
    setGewaehlt(new Date(anker))
  }, [anker])

  const heute = new Date()
  const istHeute = (d: Date) => d.toDateString() === heute.toDateString()
  const tage = monatsraster(anker)
  const wochentage = tage
    .slice(0, 7)
    .map((d) => d.toLocaleDateString(i18n.language, { weekday: 'short' }))
  const titel = anker.toLocaleDateString(i18n.language, { month: 'long', year: 'numeric' })
  const langesDatum = (d: Date) =>
    d.toLocaleDateString(i18n.language, {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
  const kurzesDatum = (d: Date) =>
    d.toLocaleDateString(i18n.language, { weekday: 'short', day: 'numeric', month: 'short' })
  const monatsanfang = new Date(anker.getFullYear(), anker.getMonth(), 1)
  const naechsterMonat = new Date(anker.getFullYear(), anker.getMonth() + 1, 1)

  /* ⚠️ Erst auf den Ersten, dann den Monat wechseln: Vom 31. aus überspränge
     `setMonth` sonst einen Monat, der keinen 31. hat. */
  function monatSchieben(richtung: number) {
    const d = new Date(anker)
    d.setDate(1)
    d.setMonth(d.getMonth() + richtung)
    aufAnker(d)
  }

  const zeile = (e: TerminZeile) => (
    <button
      key={`${e.id}-${e.beginn}`}
      type="button"
      onClick={() => aufTermin(e)}
      className="grid w-full grid-cols-[56px_3px_1fr] gap-2.5 border-b border-line-subtle px-3.5 py-2 text-left transition-colors duration-[var(--dur-fast)] active:bg-surface-3"
    >
      <span className="pt-px text-[12.5px] leading-snug tabular-nums text-fg-3">
        {e.ganztaegig ? (
          <span className="text-[11px] tracking-[0.04em] uppercase">{t('kalender.ganztaegig')}</span>
        ) : (
          <>
            {uhrzeit(e.beginn, i18n.language)}
            <span className="block text-fg-4">{uhrzeit(e.ende, i18n.language)}</span>
          </>
        )}
      </span>
      <span
        aria-hidden
        className={`rounded-sm ${PUNKT_KLASSE[nachId.get(e.kalenderId)?.farbe ?? 1]}`}
      />
      <span className="min-w-0">
        <span className="block truncate text-[14px] font-medium text-fg-1">{e.titel}</span>
        {e.ort && <span className="block truncate text-[12.5px] text-fg-3">{e.ort}</span>}
      </span>
    </button>
  )

  const tagesTermine = tagesliste(termine, gewaehlt)
  const uebersicht = nachTagen(termine, monatsanfang, naechsterMonat)

  return (
    /* ⚠️ `overflow-hidden` ist kein Schmuck: Die zugeschobene Schublade steht
       um ihre Breite nach links versetzt und läge sonst über der NavRail —
       unsichtbar, aber sie fing dort jeden Tipp ab. Dieselbe Zeile trägt die
       Schublade der Post. */
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-surface-1">
      {/* --- Der Kopf: Schublade, Monat, Pfeile, Heute, Suche, Ansicht ------- */}
      <div className="shrink-0 border-b border-line-subtle px-1.5 pt-1 pb-2">
        <div className="flex items-center gap-0.5">
          <IconKnopf label={t('kalender.kalender_waehlen')} onClick={() => setSchublade(true)}>
            <Menu />
          </IconKnopf>
          <IconKnopf label={t('kalender.zurueck')} onClick={() => monatSchieben(-1)}>
            <ChevronLeft />
          </IconKnopf>
          <h1 className="min-w-0 flex-1 truncate px-1 font-display text-[16px] font-medium text-fg-1">
            {titel}
          </h1>
          <IconKnopf label={t('kalender.vor')} onClick={() => monatSchieben(1)}>
            <ChevronRight />
          </IconKnopf>
          <button
            type="button"
            onClick={() => aufAnker(new Date())}
            className="rounded-md px-2 py-1.5 text-[12.5px] font-medium text-accent-text hover:bg-accent-soft"
          >
            {t('kalender.heute')}
          </button>
          <IconKnopf label={t('kalender.suchen')} onClick={() => setSuchtSichtbar((v) => !v)}>
            <Search />
          </IconKnopf>
        </div>
        <div className="mt-1.5 flex items-center gap-2 px-1.5">
          <div className="flex shrink-0 rounded-pill border border-line bg-surface-2 p-0.5">
            {(['monat', 'liste'] as const).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={sicht === s}
                onClick={() => setSicht(s)}
                className={
                  'rounded-pill px-3 py-1 text-[12px] font-medium transition-colors duration-[var(--dur-fast)] ' +
                  (sicht === s ? 'bg-accent text-on-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
                }
              >
                {t(`kalender.sicht_${s}`)}
              </button>
            ))}
          </div>
          {kalender.some((k) => k.art) && (
            <span className="ml-auto">
              <IconKnopf
                label={gleichtAb ? t('kalender.abgleich_laeuft') : t('kalender.abgleichen')}
                onClick={aufAbgleichen}
              >
                <RefreshCw className={gleichtAb ? 'animate-spin' : undefined} />
              </IconKnopf>
            </span>
          )}
        </div>
        {(suchtSichtbar || wort) && (
          <div className="relative mt-2 px-1.5">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-4 size-3.5 -translate-y-1/2 text-fg-4"
            />
            <input
              type="search"
              value={wort}
              autoFocus
              onChange={(e) => aufWort(e.target.value)}
              placeholder={t('kalender.suchen')}
              aria-label={t('kalender.suchen')}
              className="fokusrahmen h-[var(--control-h-sm)] w-full rounded-md border border-line bg-surface-3 pr-2 pl-8 text-[14px] text-fg-1 outline-none placeholder:text-fg-4 focus:border-accent"
            />
          </div>
        )}
      </div>

      {/* --- Der Inhalt --------------------------------------------------- */}
      {suchergebnis ? (
        suchergebnis
      ) : leer ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            title={t('kalender.leer')}
            description={t('kalender.leer_text')}
            action={
              <Button variant="primary" onClick={aufKalenderNeu}>
                {t('kalender.hinzufuegen')}
              </Button>
            }
          />
        </div>
      ) : sicht === 'monat' ? (
        <div className="min-h-0 flex-1 overflow-y-auto pb-20">
          <div className="grid grid-cols-7 px-1 pt-1.5 text-center text-[11px] tracking-[0.04em] text-fg-4 uppercase">
            {wochentage.map((w) => (
              <span key={w}>{w}</span>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-0.5 px-1 pb-1.5">
            {tage.map((d) => {
              const fremd = d.getMonth() !== anker.getMonth()
              const gew = d.toDateString() === gewaehlt.toDateString()
              const punkte = farbpunkte(termine, d)
              return (
                <button
                  key={alsDatum(d)}
                  type="button"
                  aria-pressed={gew}
                  aria-label={langesDatum(d)}
                  onClick={() => {
                    setGewaehlt(d)
                    if (fremd) aufAnker(d)
                  }}
                  className="flex min-h-[50px] flex-col items-center gap-1 rounded-lg pt-1.5 pb-1 transition-colors duration-[var(--dur-fast)] active:bg-surface-3"
                >
                  <span
                    className={
                      'flex size-[26px] items-center justify-center rounded-pill text-[13.5px] tabular-nums ' +
                      (gew
                        ? 'bg-accent font-semibold text-on-accent'
                        : istHeute(d)
                          ? 'font-semibold text-accent-text ring-1 ring-accent ring-inset'
                          : fremd
                            ? 'text-fg-4'
                            : 'text-fg-1')
                    }
                  >
                    {d.getDate()}
                  </span>
                  <span className="flex h-1.5 gap-[3px]">
                    {punkte.map((id) => (
                      <span
                        key={id}
                        aria-hidden
                        className={`size-1.5 rounded-pill ${PUNKT_KLASSE[nachId.get(id)?.farbe ?? 1]}`}
                      />
                    ))}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="border-t border-line-subtle">
            <div className="sticky top-0 z-[1] bg-surface-2/95 px-3.5 py-1.5 text-[11px] font-semibold tracking-[0.06em] text-fg-4 uppercase backdrop-blur-sm">
              {istHeute(gewaehlt) && (
                <span className="text-accent-text">{t('kalender.heute')} · </span>
              )}
              {langesDatum(gewaehlt)}
            </div>
            {tagesTermine.length === 0 ? (
              <div className="px-3.5 py-4 text-[13px] text-fg-3">
                {t('kalender.kein_termin_tag')}{' '}
                <button
                  type="button"
                  onClick={() => aufNeu(gewaehlt)}
                  className="font-medium text-accent-text underline underline-offset-2"
                >
                  {t('kalender.termin_hier')}
                </button>
              </div>
            ) : (
              tagesTermine.map(zeile)
            )}
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto pb-20">
          {uebersicht.length === 0 ? (
            <div className="px-3.5 py-6 text-[13px] text-fg-3">{t('kalender.keine_termine_monat')}</div>
          ) : (
            uebersicht.map(({ tag, termine: drin }) => (
              <div key={alsDatum(tag)}>
                <div className="sticky top-0 z-[1] flex items-baseline gap-2 bg-surface-2/95 px-3.5 py-1.5 backdrop-blur-sm">
                  <span
                    className={
                      'text-[14px] font-semibold ' + (istHeute(tag) ? 'text-accent-text' : 'text-fg-1')
                    }
                  >
                    {kurzesDatum(tag)}
                  </span>
                  {istHeute(tag) && (
                    <span className="text-[11px] font-semibold tracking-[0.06em] text-accent-text uppercase">
                      {t('kalender.heute')}
                    </span>
                  )}
                </div>
                {drin.map(zeile)}
              </div>
            ))
          )}
        </div>
      )}

      {/* --- Neuer Termin: der runde Knopf in Daumennähe ------------------- */}
      {!leer && kalender.some((k) => !k.nurLesen) && (
        <button
          type="button"
          aria-label={t('kalender.neuer_termin')}
          onClick={() => aufNeu(gewaehlt)}
          className="absolute right-4 bottom-4 z-10 flex size-[52px] items-center justify-center rounded-2xl bg-accent text-on-accent shadow-[var(--shadow-3)] transition-transform duration-[var(--dur-fast)] active:scale-95"
        >
          <Plus className="size-6" />
        </button>
      )}

      {/* --- Die Schublade mit den Kalendern ------------------------------- */}
      <div
        hidden={!schublade}
        className="absolute inset-0 z-40 bg-[var(--surface-overlay)]"
        onClick={() => setSchublade(false)}
      />
      <aside
        className={
          'absolute inset-y-0 left-0 z-40 flex w-[280px] max-w-[85vw] flex-col border-r border-line bg-surface-1 ' +
          'shadow-[var(--shadow-3)] transition-transform duration-[var(--dur-mid)] ' +
          (schublade ? 'translate-x-0' : '-translate-x-full')
        }
        aria-hidden={!schublade}
      >
        <div className="flex h-10 shrink-0 items-center justify-between border-b border-line-subtle px-2">
          <span className="px-1 text-[11px] font-semibold tracking-wide text-fg-4 uppercase">
            {t('kalender.meine')}
          </span>
          <IconKnopf label={t('aktion.schliessen')} onClick={() => setSchublade(false)}>
            <X />
          </IconKnopf>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {kalender.map((k) => (
            <div key={k.id} className="flex items-center gap-2 rounded-md px-1 py-2">
              <span aria-hidden className={`size-2.5 shrink-0 rounded-sm ${PUNKT_KLASSE[k.farbe]}`} />
              <span className="min-w-0 flex-1 truncate text-[14px]">
                <Checkbox
                  label={k.name}
                  checked={k.sichtbar}
                  onCheckedChange={(an) => aufSichtbar(k, an)}
                />
              </span>
              {k.letzterFehler ? (
                <AlertTriangle aria-hidden className="size-3.5 shrink-0 text-warning" />
              ) : (
                k.art && <Link2 aria-hidden className="size-3.5 shrink-0 text-fg-4" />
              )}
              <IconKnopf label={t('kalender.mehr_zu', { name: k.name })} onClick={() => setBlatt(k)}>
                <MoreHorizontal />
              </IconKnopf>
            </div>
          ))}
          <Button
            variant="ghost"
            size="sm"
            fullWidth
            onClick={() => {
              setSchublade(false)
              aufKalenderNeu()
            }}
          >
            {t('kalender.hinzufuegen')}
          </Button>
          {kalender.some((k) => k.nurLesen) && (
            <p className="mt-3 px-1 text-[11px] leading-relaxed text-fg-4">
              {t('kalender.nur_lesen_hinweis')}
            </p>
          )}
        </div>
      </aside>

      {/* Das Menü eines Kalenders, als Blatt von unten; die Rückfragen dahinter
          (umbenennen, entfernen) gehören der Seite und stehen über allem. */}
      {blatt && (
        <Aktionsblatt
          titel={blatt.name}
          eintraege={kalenderEintraege(blatt)}
          aufSchliessen={() => setBlatt(null)}
          nachHandlung={() => setSchublade(false)}
        />
      )}
    </div>
  )
}

/* --- Monat -------------------------------------------------------------- */

function Monat({
  anker,
  termine,
  kalender,
  aufTermin,
  aufLeer,
  aufVerschieben,
}: {
  anker: Date
  termine: TerminZeile[]
  kalender: Map<string, KalenderZeile>
  aufTermin: (t: TerminZeile) => void
  aufLeer: (d: Date) => void
  aufVerschieben: (t: TerminZeile, wohin: Zeitraum) => void
}) {
  const { t, i18n } = useTranslation()
  const heute = new Date()
  const { zug, starten, mitVorschau, warEinZug } = useZiehen(aufVerschieben)

  // Montag der Woche, in der der Erste liegt. ⚠️ In Deutschland beginnt die
  // Woche am Montag; `getDay()` zählt ab Sonntag.
  const erster = new Date(anker.getFullYear(), anker.getMonth(), 1)
  const start = new Date(erster)
  start.setDate(erster.getDate() - ((erster.getDay() + 6) % 7))

  const tage = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    return d
  })
  const wochentage = tage
    .slice(0, 7)
    .map((d) => d.toLocaleDateString(i18n.language, { weekday: 'short' }))

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid grid-cols-7 border-b border-line-subtle">
        {wochentage.map((w) => (
          <div key={w} className="px-2 py-1.5 text-[11px] font-medium text-fg-4">
            {w}
          </div>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-7 grid-rows-6">
        {tage.map((d) => {
          const fremderMonat = d.getMonth() !== anker.getMonth()
          const istHeute = d.toDateString() === heute.toDateString()
          const drin = mitVorschau(termine).filter((e) => imTag(e, d))
          return (
            <div
              key={d.toISOString()}
              data-tag={alsDatum(d)}
              onDoubleClick={() => aufLeer(mitTag(d, 0))}
              className={
                'flex min-h-0 flex-col gap-0.5 overflow-hidden border-r border-b border-line-subtle p-1 ' +
                (fremderMonat ? 'bg-surface-2' : '')
              }
            >
              <div
                className={
                  'flex size-5 shrink-0 items-center justify-center rounded-pill text-[11px] ' +
                  (istHeute
                    ? 'bg-accent font-semibold text-on-accent'
                    : fremderMonat
                      ? 'text-fg-4'
                      : 'text-fg-3')
                }
              >
                {d.getDate()}
              </div>
              {drin.slice(0, 3).map((e) => {
                const fest = kalender.get(e.kalenderId)?.nurLesen ?? false
                const wandert = Boolean(zug) && zug?.ur.id === e.id
                return (
                <button
                  key={`${e.id}-${e.beginn}`}
                  type="button"
                  onPointerDown={fest ? undefined : (p) => starten(p, e, 'ganz', null)}
                  onClick={() => {
                    if (warEinZug()) return
                    aufTermin(e)
                  }}
                  /* ⚠️ **Während des Zuges darf der Block nicht selbst unter
                     dem Zeiger liegen** — sonst findet `tagUnterZeiger` immer
                     ihn statt der Tageszelle darunter. */
                  style={wandert ? { pointerEvents: 'none' } : undefined}
                  className={
                    'flex items-center gap-1.5 rounded-sm px-1 py-0.5 text-left hover:bg-surface-3 ' +
                    (fest ? '' : 'cursor-grab ') +
                    (wandert ? 'opacity-70' : '')
                  }
                >
                  <span
                    aria-hidden
                    className={`size-1.5 shrink-0 rounded-pill ${
                      PUNKT_KLASSE[kalender.get(e.kalenderId)?.farbe ?? 1]
                    }`}
                  />
                  <span className="min-w-0 flex-1 truncate text-[11px] text-fg-2">
                    {!e.ganztaegig && (
                      <span className="text-fg-4">{uhrzeit(e.beginn, i18n.language)} </span>
                    )}
                    {e.titel}
                  </span>
                </button>
                )
              })}
              {drin.length > 3 && (
                <span className="px-1 text-[11px] text-fg-4">
                  {t('kalender.weitere', { count: drin.length - 3 })}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* --- Woche und Tag ------------------------------------------------------ */

function Raster({
  anker,
  tage,
  termine,
  kalender,
  aufTermin,
  aufLeer,
  aufVerschieben,
}: {
  anker: Date
  tage: number
  termine: TerminZeile[]
  kalender: Map<string, KalenderZeile>
  aufTermin: (t: TerminZeile) => void
  aufLeer: (d: Date) => void
  aufVerschieben: (t: TerminZeile, wohin: Zeitraum) => void
}) {
  const { i18n } = useTranslation()
  const heute = new Date()
  const { zug, starten, mitVorschau, warEinZug } = useZiehen(aufVerschieben)
  const gezeigte = mitVorschau(termine)

  const start = new Date(anker)
  if (tage === 7) start.setDate(anker.getDate() - ((anker.getDay() + 6) % 7))
  start.setHours(0, 0, 0, 0)

  const spalten = Array.from({ length: tage }, (_, i) => {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    return d
  })
  const stunden = Array.from({ length: BIS_STUNDE - VON_STUNDE }, (_, i) => VON_STUNDE + i)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div
        className="sticky top-0 z-10 grid border-b border-line-subtle bg-surface-1"
        style={{ gridTemplateColumns: `48px repeat(${tage}, minmax(0,1fr))` }}
      >
        <div />
        {spalten.map((d) => {
          const istHeute = d.toDateString() === heute.toDateString()
          return (
            <div key={d.toISOString()} className="px-2 py-1.5 text-[11px]">
              <span className="text-fg-4">
                {d.toLocaleDateString(i18n.language, { weekday: 'short' })}{' '}
              </span>
              <span
                className={
                  istHeute
                    ? 'ml-0.5 inline-flex size-5 items-center justify-center rounded-pill bg-accent font-semibold text-on-accent'
                    : 'text-fg-2'
                }
              >
                {d.getDate()}
              </span>
            </div>
          )
        })}
      </div>

      {/* Die ganztägigen oben, außerhalb des Zeitrasters — sie haben keine
          Uhrzeit, und im Raster müsste man sie irgendwohin lügen. */}
      <div
        className="grid border-b border-line-subtle"
        style={{ gridTemplateColumns: `48px repeat(${tage}, minmax(0,1fr))` }}
      >
        <div />
        {spalten.map((d) => (
          <div
            key={d.toISOString()}
            data-tag={alsDatum(d)}
            className="flex flex-col gap-0.5 border-l border-line-subtle p-1"
          >
            {gezeigte
              .filter((e) => e.ganztaegig && imTag(e, d))
              .map((e) => {
                const fest = kalender.get(e.kalenderId)?.nurLesen ?? false
                const wandert = zug?.ur.id === e.id
                return (
                <button
                  key={`${e.id}-${e.beginn}`}
                  type="button"
                  onPointerDown={fest ? undefined : (p) => starten(p, e, 'ganz', null)}
                  onClick={() => {
                    if (warEinZug()) return
                    aufTermin(e)
                  }}
                  style={wandert ? { pointerEvents: 'none' } : undefined}
                  className={
                    'flex items-center gap-1.5 rounded-sm bg-surface-3 px-1.5 py-0.5 text-left ' +
                    (fest ? '' : 'cursor-grab ') +
                    (wandert ? 'opacity-70' : '')
                  }
                >
                  <span
                    aria-hidden
                    className={`h-3 w-1 shrink-0 rounded-pill ${
                      PUNKT_KLASSE[kalender.get(e.kalenderId)?.farbe ?? 1]
                    }`}
                  />
                  <span className="min-w-0 flex-1 truncate text-[11px] text-fg-2">{e.titel}</span>
                </button>
                )
              })}
          </div>
        ))}
      </div>

      <div
        className="relative grid flex-1"
        style={{ gridTemplateColumns: `48px repeat(${tage}, minmax(0,1fr))` }}
      >
        <div className="flex flex-col">
          {stunden.map((h) => (
            <div
              key={h}
              style={{ height: STUNDE_PX }}
              className="pr-1 text-right text-[10px] leading-none text-fg-4"
            >
              {String(h).padStart(2, '0')}:00
            </div>
          ))}
        </div>
        {spalten.map((d) => (
          <div
            key={d.toISOString()}
            data-tag={alsDatum(d)}
            className="relative border-l border-line-subtle"
          >
            {stunden.map((h) => (
              <div
                key={h}
                style={{ height: STUNDE_PX }}
                onDoubleClick={() => aufLeer(mitTag(d, h))}
                className="border-b border-line-subtle"
              />
            ))}
            {tagesTermine(gezeigte, d).map(({ termin: e, lage }) => {
                const fest = kalender.get(e.kalenderId)?.nurLesen ?? false
                const wandert = zug?.ur.id === e.id
                const a = new Date(e.beginn)
                const b = new Date(e.ende)
                const oben = (a.getHours() + a.getMinutes() / 60 - VON_STUNDE) * STUNDE_PX
                const hoch = Math.max(20, ((b.getTime() - a.getTime()) / 3_600_000) * STUNDE_PX)
                /* ⚠️ **Gerechnet in Prozent, nicht in Pixeln.** Die Spalte
                   verändert ihre Breite mit dem Griff zwischen Liste und
                   Kalender; eine ausgerechnete Pixelbreite stünde nach dem
                   ersten Ziehen daneben. */
                const breite = 100 / lage.spalten
                return (
                  <button
                    key={`${e.id}-${e.beginn}`}
                    type="button"
                    onPointerDown={fest ? undefined : (p) => starten(p, e, 'ganz', STUNDE_PX)}
                    onClick={() => {
                      if (warEinZug()) return
                      aufTermin(e)
                    }}
                    style={{
                      top: oben,
                      height: hoch,
                      left: `calc(${lage.spalte * breite}% + 4px)`,
                      width: `calc(${breite}% - 5px)`,
                      ...(wandert ? { pointerEvents: 'none' } : {}),
                    }}
                    className={
                      'group absolute flex gap-1.5 overflow-hidden rounded-md bg-surface-3 p-1 text-left hover:bg-surface-2 ' +
                      /* ⚠️ **Der Angefasste gehört nach vorn.** Sonst
                         verschwindet er beim Ziehen unter seinem Nachbarn,
                         und man zieht etwas, das man nicht mehr sieht. */
                      (wandert ? 'z-10 ' : '') +
                      (fest ? '' : 'cursor-grab ') +
                      (wandert ? 'opacity-70 ring-1 ring-accent' : '')
                    }
                  >
                    <span
                      aria-hidden
                      className={`w-1 shrink-0 rounded-pill ${
                        PUNKT_KLASSE[kalender.get(e.kalenderId)?.farbe ?? 1]
                      }`}
                    />
                    {/* ⚠️ **Ein halbstündiger Block ist 24 px hoch.** Zwei
                        Zeilen passen da nicht hinein — die zweite wird
                        abgeschnitten und sieht aus wie ein Zeichenfehler.
                        Unter 40 px steht die Uhrzeit deshalb hinter dem Titel
                        statt darunter. */}
                    <span className="min-w-0">
                      <span className="block truncate text-[11px] font-medium text-fg-1">
                        {e.titel}
                        {hoch < 40 && (
                          <span className="font-normal text-fg-4">
                            {' '}
                            {uhrzeit(e.beginn, i18n.language)}
                          </span>
                        )}
                      </span>
                      {hoch >= 40 && (
                        <span className="block truncate text-[10px] text-fg-4">
                          {uhrzeit(e.beginn, i18n.language)}
                        </span>
                      )}
                    </span>
                    {/* Der Griff an der Unterkante.
                        ⚠️ **Ein `span`, keine zweite Schaltfläche.** Eine
                        Schaltfläche in einer Schaltfläche ist ungültiges HTML,
                        und Vorleseprogramme melden dann zwei Ziele, von denen
                        eines nichts sagt. Er ist bewusst nicht mit der Tastatur
                        erreichbar: Die Dauer stellt man dort im Formular ein,
                        wo sie einen Namen und eine Einheit hat.

                        ⚠️ **Er muss sichtbar sein, sonst gibt es ihn nicht.**
                        Der erste Bau war 6 px hoch und ohne jeden Hinweis —
                        am 04.09.2026 aus dem Betrieb gemeldet: „ich kann da
                        nix ziehen". Er funktionierte, man fand ihn nur nicht.
                        Jetzt 8 px, und beim Überfahren erscheint der Balken,
                        den jeder Kalender an dieser Stelle zeigt. */}
                    {!fest && (
                      <span
                        aria-hidden
                        onPointerDown={(p) => starten(p, e, 'kante', STUNDE_PX)}
                        className="absolute inset-x-0 bottom-0 flex h-2 cursor-ns-resize items-end justify-center"
                      >
                        <span className="mb-0.5 h-0.5 w-6 rounded-pill bg-fg-3 opacity-0 transition-opacity group-hover:opacity-80" />
                      </span>
                    )}
                  </button>
                )
              })}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Die zeitgebundenen Termine eines Tages, jeder mit seiner Spalte.
 *
 * ⚠️ **Die Aufteilung gilt je Tag, nicht je Woche.** Zwei Termine an
 * verschiedenen Tagen überschneiden sich nie, auch wenn ihre Uhrzeiten
 * gleich sind; gemeinsam gerechnet bekämen sie unnötig schmale Spalten.
 */
function tagesTermine(alle: TerminZeile[], tag: Date) {
  const drin = alle.filter((e) => !e.ganztaegig && imTag(e, tag))
  const lagen = nebeneinander(drin)
  return drin.map((termin, i) => ({ termin, lage: lagen[i] }))
}

/* --- Das Terminfenster -------------------------------------------------- */

/** Der Punkt vor einem Teilnehmer. ⚠️ **Der Ton ist Bedeutung, nicht
 *  Schmuck** — Zusage grün, Absage rot, alles Offene grau. */
const ANTWORT_PUNKT: Record<string, string> = {
  ACCEPTED: 'bg-success',
  DECLINED: 'bg-danger',
  TENTATIVE: 'bg-warning',
}

/** Vorläufe in Minuten. ⚠️ Dieselbe Reihe wie ``VORLAEUFE`` im Server —
 *  laufen sie auseinander, weist er still ab, was die Maske anbietet. */
const VORLAEUFE = [-1, 0, 5, 10, 15, 30, 60, 120, 1440]

function Terminfenster({
  termin,
  vorgabe,
  kalender,
  gesperrt,
  herkunft,
  postfaecher,
  aufEinladen,
  aufAbsage,
  aufFehler,
  aufUmfang,
  onClose,
  onFertig,
}: {
  termin: TerminZeile | null
  vorgabe: { beginn: Date; ganztaegig: boolean } | null
  kalender: KalenderZeile[]
  gesperrt: boolean
  herkunft: string
  postfaecher: Konto[]
  aufEinladen: (
    terminId: number,
    anzahl: number,
    von: string,
    schonEingeladen?: boolean,
  ) => Promise<void>
  aufAbsage: (anzahl: number) => Promise<boolean | null>
  aufFehler: (f: unknown) => void
  aufUmfang: (t: TerminZeile, was: 'aendern' | 'loeschen', tun: (u: Umfang) => void) => void
  onClose: () => void
  onFertig: () => void
}) {
  const { t, i18n } = useTranslation()
  const sprache = i18n.language
  const [titel, setTitel] = useState(termin?.titel ?? '')
  const ganzZuerst = termin?.ganztaegig ?? vorgabe?.ganztaegig ?? false
  /* ⚠️ **Ein angeklickter Tag ist ein Kalendertag, kein Zeitpunkt.**
   * `vorgabe.beginn` ist die örtliche Mitternacht der Zelle; über
   * `toISOString()` wird daraus in Berlin `22:00Z des Vortags` — und im Feld
   * stünde der Tag davor. Für ganztägig wird deshalb der örtliche Kalendertag
   * genommen, nicht der Zeitpunkt. */
  const vorgabeTag = vorgabe ? `${alsDatum(vorgabe.beginn)}T00:00` : ''
  const [beginn, setBeginn] = useState(
    termin
      ? fuerFeld(termin.beginn, ganzZuerst)
      : ganzZuerst
        ? vorgabeTag
        : fuerFeld(vorgabe?.beginn.toISOString() ?? '', false),
  )
  const [ende, setEnde] = useState(
    termin
      ? fuerEndeFeld(termin.ende, ganzZuerst)
      : ganzZuerst
        ? vorgabeTag
        : fuerFeld(stundeSpaeter(vorgabe?.beginn), false),
  )
  const [ganztaegig, setGanztaegig] = useState(ganzZuerst)
  const [ort, setOrt] = useState(termin?.ort ?? '')
  const [notiz, setNotiz] = useState(termin?.beschreibung ?? '')
  /* ⚠️ **Eine fremde Regel wird nicht zerlegt.** Was diese Maske nicht
     abbildet, bleibt als Ganzes stehen — sie zu zerlegen hiesse, sie beim
     Speichern zu zerstören. Der Server sagt mit `wiederholungFremd`, welcher
     Fall vorliegt. */
  const fremdeRegel = Boolean(termin?.regelFremd && termin.rrule)
  const [wdh, setWdh] = useState<Wiederholung>(
    termin && !termin.regelFremd ? termin.regel : LEERE_WIEDERHOLUNG,
  )
  const rrule = fremdeRegel ? (termin?.rrule ?? '') : alsRrule(wdh)
  const [erinnerung, setErinnerung] = useState(termin?.erinnerung ?? -1)
  /* ⚠️ **Nur mitschicken, wenn jemand es angefasst hat.** Der Server ersetzt
     den `VALARM` im Original nur dann — sonst verlöre ein fremder Termin
     seinen Alarm, bloß weil hier der Titel geändert wurde. */
  const erinnerungBeruehrt = useRef(false)
  /* Die Teilnehmer dieses Termins.
     ⚠️ **Nur mitschicken, wenn jemand sie angefasst hat** — dieselbe Regel wie
     bei der Erinnerung, und aus dem schwereren Grund: Bei einem Termin, zu dem
     man eingeladen wurde, würfe ein Mitschicken die Zusagen der anderen weg
     und machte einen zum Organisator. */
  const [leute, setLeute] = useState<Beteiligter[]>(termin?.teilnehmer ?? [])
  const leuteBeruehrt = useRef(false)
  const [neueAdresse, setNeueAdresse] = useState('')

  /** Alle Adressen, unter denen eingeladen werden kann — Postfach und Aliasse. */
  const absenderWahl = postfaecher.flatMap((k) => [
    { adresse: k.adresse, wer: k.anzeigename },
    ...(k.aliase ?? []).map((a) => ({ adresse: a.adresse, wer: a.name || k.anzeigename })),
  ])
  const [absender, setAbsender] = useState(
    termin?.organisator?.adresse || absenderWahl[0]?.adresse || '',
  )

  function personDazu(roh: string) {
    const adresse = roh.trim().toLowerCase()
    setNeueAdresse('')
    if (!adresse) return
    // Groß/klein trennt niemanden — dieselbe Regel wie im Server.
    if (leute.some((p) => p.adresse.toLowerCase() === adresse)) return
    leuteBeruehrt.current = true
    setLeute([...leute, { name: '', adresse, antwort: 'NEEDS-ACTION', rolle: '' }])
  }

  function personWeg(adresse: string) {
    leuteBeruehrt.current = true
    setLeute(leute.filter((p) => p.adresse !== adresse))
  }
  const [kalenderId, setKalenderId] = useState(termin?.kalenderId ?? kalender[0]?.id ?? '')
  /** Der Kalender, in dem dieser Termin liegt — für die Zeile ganz oben. */
  const dieser = termin ? kalender.find((k) => k.id === termin.kalenderId) : undefined
  const [laeuft, setLaeuft] = useState(false)
  /* Ein offener Konflikt: die eigene Fassung und der Weg, sie doch zu
     schreiben. Solange er steht, ist nichts gespeichert. */
  const [konflikt, setKonflikt] = useState<{
    zeile: TerminZeile
    nochmal: (erzwingen: boolean) => Promise<unknown>
  } | null>(null)

  async function speichern() {
    setLaeuft(true)
    try {
      if (!termin) {
        const neu = await terminAnlegen({
          kalenderId,
          titel,
          beginn: ausFeld(beginn, ganztaegig),
          ende: ausEndeFeld(ende, ganztaegig),
          ganztaegig,
          ort,
          beschreibung: notiz,
          rrule,
          erinnerung,
          teilnehmer: leute.map((p) => ({ adresse: p.adresse, name: p.name })),
          absender: leute.length ? absender : '',
        })
        if (leute.length) await aufEinladen(neu.id, leute.length, absender)
        onFertig()
        return
      }
      // ⚠️ Bei einer Reihe erst fragen — sonst ändert ein Tippfehler im Titel
      // stillschweigend fünfzig Termine.
      aufUmfang(termin, 'aendern', (umfang) => {
        void (async () => {
          const schreiben = (erzwingen: boolean) =>
            terminAendern(termin.id, {
              titel,
              beginn: ausFeld(beginn, ganztaegig),
              ende: ausEndeFeld(ende, ganztaegig),
              ganztaegig,
              ort,
              beschreibung: notiz,
              erinnerung: erinnerungBeruehrt.current ? erinnerung : undefined,
              teilnehmer: leuteBeruehrt.current
                ? leute.map((p) => ({ adresse: p.adresse, name: p.name }))
                : undefined,
              absender: leuteBeruehrt.current && leute.length ? absender : undefined,
              // Die Regel gehört der Reihe: Bei „nur dieser" bleibt sie außen vor.
              rrule: umfang === 'dieser' ? undefined : rrule,
              umfang,
              vorkommen: termin.beginn,
              erzwingen,
            })

          try {
            await schreiben(false)
            if (leute.length)
              await aufEinladen(termin.id, leute.length, absender, termin.eingeladen)
            onFertig()
          } catch (f) {
            /* ⚠️ **Ein Konflikt ist keine Fehlermeldung, sondern eine Frage.**
               Die eigene Änderung steht noch im Formular; sie wegzuwerfen, weil
               jemand anders schneller war, wäre die schlechteste der drei
               möglichen Antworten — und bis zum 04.09.2026 die einzige. */
            if (f instanceof ApiFehler && f.detail === 'termin_konflikt') {
              setKonflikt({
                /* Die eigene Fassung, wie sie gespeichert werden sollte —
                   nicht die gespeicherte: Verglichen wird, was der Mensch
                   gerade eingetippt hat. */
                zeile: {
                  ...termin,
                  titel,
                  ort,
                  beschreibung: notiz,
                  beginn: ausFeld(beginn, ganztaegig),
                  ende: ausEndeFeld(ende, ganztaegig) ?? termin.ende,
                  ganztaegig,
                },
                nochmal: schreiben,
              })
              setLaeuft(false)
              return
            }
            aufFehler(f)
            setLaeuft(false)
          }
        })()
      })
    } catch (f) {
      aufFehler(f)
      setLaeuft(false)
    }
  }

  function loeschen() {
    if (!termin) return
    aufUmfang(termin, 'loeschen', (umfang) => {
      void (async () => {
        try {
          /* ⚠️ **Nur wenn schon eingeladen wurde.** Ein Termin mit
           * Teilnehmern, zu dem nie eine Einladung hinausging, hat keine
           * Gegenstelle, die etwas erfahren müsste. */
          let absagen = false
          if (termin.eingeladen && termin.teilnehmer.length) {
            const antwort = await aufAbsage(termin.teilnehmer.length)
            if (antwort === null) return
            absagen = antwort
          }
          await terminEntfernen(termin.id, umfang, termin.beginn, absagen)
          onFertig()
        } catch (f) {
          aufFehler(f)
        }
      })()
    })
  }

  /* ⚠️ **Das Konfliktfenster steht VOR dem Terminfenster, nicht darin.** Zwei
     offene Fenster übereinander wären zwei Ausgänge, und der Mensch soll genau
     eine Frage vor sich haben. Das Terminfenster ist so lange nicht sichtbar,
     seine Eingaben bleiben aber stehen. */
  if (konflikt) {
    return (
      <Konfliktfenster
        termin={konflikt.zeile}
        sprache={sprache}
        aufSchliessen={() => setKonflikt(null)}
        aufWahl={(wahl) =>
          void (async () => {
            setKonflikt(null)
            setLaeuft(true)
            try {
              if (wahl === 'meine') await konflikt.nochmal(true)
              else await konfliktAufloesen(konflikt.zeile.id)
              onFertig()
            } catch (f) {
              aufFehler(f)
              setLaeuft(false)
            }
          })()
        }
      />
    )
  }

  return (
    <Dialog
      open
      width={520}
      title={termin ? termin.titel : t('kalender.neuer_termin')}
      onClose={onClose}
      footer={
        <>
          {termin && !gesperrt && (
            <Button variant="danger" onClick={loeschen}>
              {t('aktion.loeschen')}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant="primary"
            disabled={gesperrt || !titel.trim() || laeuft}
            loading={laeuft}
            onClick={() => void speichern()}
          >
            {t('aktion.speichern')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-sm">
        {/* ⚠️ **Aus welchem Kalender der Termin ist, gehört nach oben.** Bei
            mehreren verbundenen Kalendern sagt der Titel allein nichts darüber,
            wo der Eintrag wirklich liegt — und wer ihn löscht, will vorher
            wissen, wo. Beim Anlegen steht dafür weiter unten die Auswahl; ein
            bestehender Termin wird hier nicht verschoben, das wäre bei CalDAV
            ein Umzug zwischen zwei Sammlungen. */}
        {termin && dieser && (
          <p className="mb-0 flex items-center gap-2 text-[12px] text-fg-3">
            <span
              aria-hidden
              className={`size-2.5 shrink-0 rounded-full ${PUNKT_KLASSE[dieser.farbe]}`}
            />
            <span className="truncate">{dieser.name}</span>
            {dieser.herkunft && (
              <span className="truncate text-fg-4">· {dieser.herkunft}</span>
            )}
          </p>
        )}

        {gesperrt && (
          <p className="rounded-md bg-warning-soft px-3 py-2 text-[12px] text-warning">
            {t('kalender.gesperrt', { wo: herkunft })}
          </p>
        )}

        <Input
          label={t('kalender.titel')}
          value={titel}
          disabled={gesperrt}
          onChange={(e) => setTitel(e.target.value)}
        />

        <Checkbox
          label={t('kalender.ganztaegig')}
          checked={ganztaegig}
          disabled={gesperrt}
          onCheckedChange={setGanztaegig}
        />

        <div className="flex gap-3">
          <Input
            label={t('kalender.beginn')}
            type={ganztaegig ? 'date' : 'datetime-local'}
            value={ganztaegig ? beginn.slice(0, 10) : beginn}
            disabled={gesperrt}
            onChange={(e) => setBeginn(e.target.value)}
          />
          <Input
            label={t('kalender.ende')}
            type={ganztaegig ? 'date' : 'datetime-local'}
            value={ganztaegig ? ende.slice(0, 10) : ende}
            disabled={gesperrt}
            onChange={(e) => setEnde(e.target.value)}
          />
        </div>

        <Input
          label={t('kalender.ort')}
          value={ort}
          disabled={gesperrt}
          onChange={(e) => setOrt(e.target.value)}
        />

        {fremdeRegel ? (
          /* ⚠️ **Benannt, nicht zerlegt.** Eine Regel aus einem anderen
              Programm bleibt stehen; sie hier in Bausteine zu zwingen hieße,
              sie beim Speichern zu zerstören. */
          <div className="flex flex-col gap-1">
            <span className="text-[12px] font-medium text-fg-3">
              {t('kalender.wiederholung')}
            </span>
            <span className="text-[13px] text-fg-1">
              {termin ? wiederholungsSatz(termin, t, sprache) : t('kalender.wdh_allgemein')}
            </span>
            <span className="text-[11px] leading-relaxed text-fg-4">
              {t('kalender.wdh_fremd')}
            </span>
          </div>
        ) : (
          <Wiederholungsfeld
            wert={wdh}
            aufAendern={setWdh}
            gesperrt={gesperrt}
            beginn={beginn ? new Date(beginn) : undefined}
          />
        )}

        {!termin && kalender.length > 1 && (
          <Select
            label={t('kalender.kalender_feld')}
            value={kalenderId}
            onChange={(e) => setKalenderId(e.target.value)}
          >
            {kalender.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </Select>
        )}

        {/* ⚠️ **Der Alarm gehört zum Termin, nicht zur Anzeige.** Er fährt als
            `VALARM` über CalDAV mit — wer ihn hier setzt, wird auch auf dem
            Telefon erinnert, und ein Alarm aus einem anderen Programm steht
            hier. */}
        <Select
          label={t('kalender.erinnerung')}
          value={String(erinnerung)}
          disabled={gesperrt}
          onChange={(e) => {
            erinnerungBeruehrt.current = true
            setErinnerung(Number(e.target.value))
          }}
        >
          {VORLAEUFE.map((min) => (
            <option key={min} value={min}>
              {min < 0 ? t('kalender.erinnerung_keine') : vorlaufSatz(min, t)}
            </option>
          ))}
          {/* Ein Vorlauf aus einem anderen Programm, den die Liste nicht
              kennt — er bleibt stehen, statt beim Speichern zu verschwinden. */}
          {erinnerung >= 0 && !VORLAEUFE.includes(erinnerung) && (
            <option value={erinnerung}>{vorlaufSatz(erinnerung, t)}</option>
          )}
        </Select>

        <Input
          label={t('kalender.notiz')}
          value={notiz}
          disabled={gesperrt}
          onChange={(e) => setNotiz(e.target.value)}
        />

        {/* ⚠️ **Bearbeitbar, seit nexmail einladen kann.** Angefasst wird die
            Liste im Original aber nur, wenn hier wirklich jemand dazukam oder
            wegfiel — sonst bliebe von den Zusagen eines fremden Termins
            nichts übrig. Den Riegel dafür hält `leuteBeruehrt`. */}
        <div className="flex flex-col gap-1.5 border-t border-line-subtle pt-3">
          {/* ⚠️ **Kein „0 Teilnehmer".** Die Zählung steht erst da, wenn es
              etwas zu zählen gibt; das Feld darunter bleibt, sonst käme man
              nie zum ersten Teilnehmer. */}
          {leute.length > 0 && (
            <span className="text-[12px] font-medium text-fg-3">
              {t('kalender.teilnehmer', { count: leute.length })}
            </span>
          )}
          {termin?.organisator && (
            <p className="mb-0 truncate text-[12px] text-fg-3">
              {t('kalender.organisator', {
                wer: termin.organisator.name || termin.organisator.adresse,
              })}
            </p>
          )}
          <ul className="flex list-none flex-col gap-1 p-0">
            {leute.map((b) => (
              <li key={b.adresse || b.name} className="flex items-center gap-2 text-[12px]">
                <span
                  aria-hidden
                  className={`size-2 shrink-0 rounded-full ${ANTWORT_PUNKT[b.antwort] ?? 'bg-fg-4'}`}
                />
                <span className="min-w-0 flex-1 truncate text-fg-1">
                  {b.name || b.adresse}
                </span>
                {/* ⚠️ Der Zusagestand gehört dazu — ohne ihn ist eine
                    Teilnehmerliste eine Namensliste. */}
                <span className="shrink-0 text-fg-4">
                  {t(`kalender.antwort_${b.antwort.toLowerCase() || 'unbekannt'}`, {
                    defaultValue: t('kalender.antwort_unbekannt'),
                  })}
                </span>
                {!gesperrt && (
                  <button
                    type="button"
                    aria-label={t('kalender.teilnehmer_entfernen', { wer: b.adresse })}
                    onClick={() => personWeg(b.adresse)}
                    className="shrink-0 rounded-sm p-0.5 text-fg-4 hover:bg-surface-3 hover:text-fg-1"
                  >
                    <X className="size-3.5" aria-hidden />
                  </button>
                )}
              </li>
            ))}
          </ul>
          {!gesperrt && leute.length > 0 && absenderWahl.length > 0 && (
            /* ⚠️ **Je Termin gewählt, nicht am Kalender hinterlegt.** Ein
               Kalender gehört zu keinem Postfach; wer den Vereinstermin aus
               dem privaten Kalender heraus anlegt, soll trotzdem als Verein
               einladen können. */
            <Select
              label={t('kalender.einladung_von')}
              value={absender}
              onChange={(e) => setAbsender(e.target.value)}
            >
              {absenderWahl.map((a) => (
                <option key={a.adresse} value={a.adresse}>
                  {a.wer} — {a.adresse}
                </option>
              ))}
            </Select>
          )}
          {/* ⚠️ **Verworfen, aber nicht verschwiegen.** Nur wer eingeladen
              wurde, kann antworten — sonst trüge sich ein Fremder in eine
              Teilnehmerliste ein, indem er eine Antwort schickt. Lautlos
              wegwerfen ist aber genauso falsch: Am 04.09.2026 antwortete
              Outlook unter der eigenen Absenderidentität statt unter der
              eingeladenen Adresse, und von außen sah es aus, als sei der
              Rückkanal kaputt. */}
          {(termin?.fremdeAntworten?.length ?? 0) > 0 && (
            <div className="flex flex-col gap-1 rounded-sm bg-surface-3 p-2">
              <span className="text-[12px] font-medium text-fg-3">
                {t('kalender.fremde_antwort_kopf', {
                  count: termin!.fremdeAntworten.length,
                })}
              </span>
              {termin!.fremdeAntworten.map((f) => (
                <p key={f.adresse} className="mb-0 text-[12px] text-fg-3">
                  <span className="text-fg-1">{f.adresse}</span>
                  {' — '}
                  {t(`kalender.antwort_${(f.antwort || '').toLowerCase()}`, {
                    defaultValue: t('kalender.antwort_unbekannt'),
                  })}
                </p>
              ))}
              <p className="mb-0 text-[12px] text-fg-4">
                {t('kalender.fremde_antwort_hinweis')}
              </p>
            </div>
          )}
          {!gesperrt && (
            <Input
              type="email"
              value={neueAdresse}
              onChange={(e) => setNeueAdresse(e.target.value)}
              onKeyDown={(e) => {
                /* ⚠️ **Enter fügt hinzu und schickt das Formular nicht ab.**
                   Ohne das Abfangen speichert der erste Enter den Termin,
                   bevor der Teilnehmer überhaupt in der Liste steht. */
                if (e.key === 'Enter') {
                  e.preventDefault()
                  personDazu(neueAdresse)
                }
              }}
              onBlur={() => personDazu(neueAdresse)}
              placeholder={t('kalender.teilnehmer_platzhalter')}
              hint={t('kalender.teilnehmer_hinweis')}
            />
          )}
        </div>

        {termin?.ausEinladung && (
          <p className="text-[12px] text-fg-4">{t('kalender.aus_einladung')}</p>
        )}
      </div>
    </Dialog>
  )
}

/* --- Kleinkram ---------------------------------------------------------- */

function IconKnopf({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-8 items-center justify-center rounded-md text-fg-3 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1 [&_svg]:size-4"
    >
      {children}
    </button>
  )
}

/** Welches Fenster geladen wird — mit Rand, damit Blättern nicht flackert. */
function spanne(anker: Date, sicht: Sicht): [Date, Date] {
  const von = new Date(anker)
  const bis = new Date(anker)
  if (sicht === 'monat') {
    von.setDate(1)
    von.setDate(von.getDate() - 7)
    bis.setMonth(bis.getMonth() + 1, 1)
    bis.setDate(bis.getDate() + 7)
  } else if (sicht === 'woche') {
    von.setDate(anker.getDate() - ((anker.getDay() + 6) % 7) - 1)
    bis.setTime(von.getTime())
    bis.setDate(von.getDate() + 9)
  } else {
    von.setDate(anker.getDate() - 1)
    bis.setDate(anker.getDate() + 2)
  }
  von.setHours(0, 0, 0, 0)
  bis.setHours(0, 0, 0, 0)
  return [von, bis]
}

/* `imTag` und `alsDatum` wohnen seit der schmalen Ansicht in
   `lib/kalendertage.ts` — dort rechnet die Telefonansicht ohne Browser damit,
   und zwei Kopien liefen auseinander. */

function uhrzeit(iso: string, sprache: string): string {
  return new Date(iso).toLocaleTimeString(sprache, { hour: '2-digit', minute: '2-digit' })
}

/** „15 Minuten vorher" — aus Minuten, in der eingestellten Sprache. */
function vorlaufSatz(minuten: number, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (minuten === 0) return t('kalender.erinnerung_beginn')
  if (minuten % 1440 === 0) return t('kalender.erinnerung_tage', { count: minuten / 1440 })
  if (minuten % 60 === 0) return t('kalender.erinnerung_stunden', { count: minuten / 60 })
  return t('kalender.erinnerung_minuten', { count: minuten })
}

function mitTag(d: Date, stunde: number): Date {
  const raus = new Date(d)
  raus.setHours(stunde, 0, 0, 0)
  return raus
}

function naechsteVolleStunde(): Date {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return d
}

function stundeSpaeter(d?: Date): string {
  const raus = new Date(d ?? new Date())
  raus.setHours(raus.getHours() + 1)
  return raus.toISOString()
}

/** Für ein `datetime-local`-Feld — das will Ortszeit ohne Zone. */
function fuerFeld(iso?: string, ganztaegig = false): string {
  if (!iso) return ''
  /* ⚠️ **Ganztägig geht NICHT durch die Ortszeit.** Der Wert ist ein
   * Kalendertag; `new Date(...)` macht daraus einen Zeitpunkt, und westlich
   * von Greenwich steht danach der Vortag im Feld. */
  if (ganztaegig) return `${iso.slice(0, 10)}T00:00`
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

/** ⚠️ Und zurück: Der Browser liest den Wert als **Ortszeit**, der Server will
 *  ISO mit Zone. Ohne die Umrechnung landet jeder Termin um den Zeitversatz
 *  verschoben — dasselbe Muster wie bei „Später senden". */
/** Das Ende eines ganztägigen Termins fürs Feld — der **letzte Tag**.
 *
 * ⚠️ **Gespeichert wird ausschließend, gezeigt wird einschließend.** Ein
 * eintägiger Termin am 14. steht als 14. → 15. in der Datenbank (RFC 5545), und
 * genau so gab ihn Google zurück. Im Feld „Ende" den 15. anzuzeigen liest sich
 * als zweitägiger Termin — Google, Outlook und Apple zeigen dort alle den 14.
 * Am 03.09.2026 gemeldet: „in nexmail steht er von 14–15".
 */
function fuerEndeFeld(iso: string | undefined, ganztaegig: boolean): string {
  if (!ganztaegig || !iso) return fuerFeld(iso, ganztaegig)
  const tag = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  tag.setUTCDate(tag.getUTCDate() - 1)
  return `${tag.toISOString().slice(0, 10)}T00:00`
}

/** Und zurück: Der letzte Tag wird wieder zum ausschließenden Ende. */
function ausEndeFeld(wert: string, ganztaegig: boolean): string {
  if (!ganztaegig || !wert) return ausFeld(wert, ganztaegig)
  const tag = new Date(`${wert.slice(0, 10)}T00:00:00Z`)
  tag.setUTCDate(tag.getUTCDate() + 1)
  return `${tag.toISOString().slice(0, 10)}T00:00:00Z`
}

function ausFeld(wert: string, ganztaegig = false): string {
  if (!wert) return new Date().toISOString()
  /* ⚠️ **Und zurück genauso.** `new Date("2026-09-14T00:00").toISOString()`
   * ergibt in Berlin `2026-09-13T22:00:00Z` — der Termin landete einen Tag zu
   * früh in der Datenbank und stand danach über zwei Tage. Ein Kalendertag
   * wird als UTC-Mitternacht abgelegt, ohne Umrechnung. */
  if (ganztaegig) return `${wert.slice(0, 10)}T00:00:00Z`
  return new Date(wert.length === 10 ? `${wert}T00:00` : wert).toISOString()
}

/** „Jede Woche · Mo, Do" — aus Kennung, Tagen und Intervall.
 *
 * ⚠️ **Die Wochentagsnamen kommen vom Browser**, nicht aus unseren
 * Übersetzungsdateien. Sonst stünden dort vierzehn Wörter, die `Intl` in jeder
 * Sprache ohnehin kennt — und in der dritten Sprache fehlten sie wieder.
 */
function wiederholungsSatz(
  termin: TerminZeile,
  t: (k: string, o?: Record<string, unknown>) => string,
  sprache: string,
): string {
  if (!termin.wiederholung) return ''
  const stamm =
    termin.wiederholungIntervall > 1
      ? t('kalender.wdh_alle_n', { count: termin.wiederholungIntervall })
      : t(`kalender.wdh_${termin.wiederholung}`, {
          defaultValue: t('kalender.wdh_allgemein'),
        })
  if (termin.wiederholungTage.length === 0) return stamm

  // ⚠️ Ein fester Bezugstag, der ein Montag ist — von dort aus zählen die
  // Kürzel. Der 5. Januar 2026 ist einer.
  const REIHE = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
  const namen = termin.wiederholungTage
    .map((tag) => {
      const i = REIHE.indexOf(tag)
      if (i < 0) return ''
      const d = new Date(2026, 0, 5 + i)
      return d.toLocaleDateString(sprache, { weekday: 'short' })
    })
    .filter(Boolean)
  return namen.length ? `${stamm} · ${namen.join(', ')}` : stamm
}
