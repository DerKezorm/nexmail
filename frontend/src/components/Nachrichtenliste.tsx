/* Die Nachrichtenliste.
 *
 * Aufbau je Zeile, wie in Outlook: Absender fett mit Datum rechts, darunter
 * der Betreff, darunter gedimmt der Anreisser. Der Anreisser ist kein
 * Schmuck - er spart das Oeffnen, und das ist der ganze Grund fuer die
 * dritte Zeile.
 *
 * Der farbige Punkt fuer das Postfach erscheint **nur** in "Alle
 * Posteingaenge". In einem einzelnen Ordner ist das Postfach ohnehin klar,
 * und ein Punkt, der immer dasselbe sagt, wird nicht mehr gelesen.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Archive,
  ChevronDown,
  ChevronRight,
  Clock,
  Flag,
  Mail,
  MailOpen,
  MessagesSquare,
  Paperclip,
  Trash2,
} from 'lucide-react'
import type { Datumsgruppe } from '../lib/format'
import { anzeigename, gruppeVon, kurzesDatum, planzeit } from '../lib/format'
import { PUNKT_KLASSE } from '../lib/farben'
import { Schlagwortmarke } from './Schlagwortmarke'
import type { WischAktion } from '../lib/wischen'
import { wischSchwelle } from '../lib/wischen'
import type { Konto, Nachricht, Postfachfarbe, Schlagwort } from '../daten/typen'
import { EmptyState, Select } from '../ds'
import { Check, Inbox } from 'lucide-react'
import { LANGDRUCK_MS, zuWeitGewandert } from '../lib/auswahl'

const GRUPPEN: Datumsgruppe[] = ['heute', 'gestern', 'diese_woche', 'aelter']

/** Wisch-Aktionen der schmalen Ansicht — was ein Zug nach links bzw. rechts
 *  tut. Fehlt das Ganze (breite Ansicht), wischt nichts. */
export interface Wischen {
  links: WischAktion
  rechts: WischAktion
  ausfuehren: (n: Nachricht, aktion: WischAktion) => void
}

interface Props {
  nachrichten: Nachricht[]
  konten: Konto[]
  gewaehlt: string | null
  aufWahl: (id: string, mitStrg: boolean, mitUmschalt: boolean) => void
  /** Kennungen der mehrfach ausgewaehlten Zeilen. */
  mehrfach: string[]
  /** Postfach-Punkt zeigen — nur in der zusammengefuehrten Ansicht. */
  postfachZeigen: boolean
  titel: string
  aufKontext: (e: React.MouseEvent, n: Nachricht) => void
  /** Beginnt ein Ziehen — gibt zurück, welche Nachrichten mitkommen. */
  aufZiehen?: (n: Nachricht) => string[]
  /** Aus „Darstellung": weniger Höhe je Zeile. */
  kompakt?: boolean
  /** Aus „Darstellung": den Anrisstext zeigen. */
  anreisserZeigen?: boolean
  /** Alle / nur ungelesene. `markiert` blendet den Umschalter aus — dort
   *  wäre er sinnlos, die Auswahl steht schon fest. */
  filter?: 'alle' | 'ungelesen' | 'markiert'
  aufFilter?: (f: 'alle' | 'ungelesen') => void
  /** Die Schlagwort-Definitionen — für die Farbmarken je Zeile und die
   *  Auswahl in der Filterzeile. */
  schlagworte?: Schlagwort[]
  /** Gewähltes Schlagwort-Atom. Leer heißt: alle.
   *  ⚠️ Gefiltert wird im **Server** (Parameter an /api/nachrichten), nicht
   *  hier — die Liste hält nur die neuesten Zeilen. */
  schlagwortFilter?: string
  aufSchlagwortFilter?: (atom: string) => void
  /** Ältere nachladen. Fehlt sie, gibt es kein Weiterlesen. */
  aufMehr?: () => void
  mehrLaedt?: boolean
  /** Es gibt nichts Älteres mehr. */
  amEnde?: boolean
  /** Gespräche zusammenfassen. `undefined` blendet den Umschalter aus. */
  gruppiert?: boolean
  aufGruppiert?: (an: boolean) => void
  /** Einen Strang aufklappen; gibt seine Nachrichten zurück. */
  aufStrang?: (schluessel: string) => Promise<Nachricht[]>
  /** Wischen am Finger — kommt nur in der schmalen Ansicht mit. */
  wischen?: Wischen
  /** Aufwach-Zeitpunkte der Wiedervorlage (Nachricht-Kennung → ISO). Zeilen
   *  mit Eintrag tragen ihre Marke — übersetzt, in Ortszeit. */
  aufwachZeiten?: Record<string, string>
  /** Der Auswahlmodus der schmalen Ansicht: Ein Tipp markiert statt öffnet,
   *  jede Zeile trägt einen Kreis, oben steht der Zähler. Nur schmal gesetzt. */
  auswahlmodus?: boolean
  /** Schaltet den Modus ein („Auswählen" im Kopf) oder aus („Fertig"). Fehlt
   *  er, gibt es den Knopf nicht — das ist der Schreibtisch. */
  aufAuswahlmodus?: (an: boolean) => void
  /** Langer Druck auf eine Zeile — nur schmal gesetzt. Am Schreibtisch gehört
   *  der lange Druck der Maus dem Ziehen in den Ordnerbaum. */
  aufLangdruck?: (n: Nachricht) => void
  /** Ob alle sichtbaren Zeilen gewählt sind — dann heißt der Knopf „Keine". */
  alleGewaehlt?: boolean
  aufAlleWaehlen?: () => void
}

export function Nachrichtenliste({
  nachrichten,
  konten,
  gewaehlt,
  aufWahl,
  mehrfach,
  postfachZeigen,
  titel,
  aufKontext,
  aufZiehen,
  kompakt = false,
  anreisserZeigen = true,
  filter,
  aufFilter,
  schlagworte = [],
  schlagwortFilter = '',
  aufSchlagwortFilter,
  aufMehr,
  mehrLaedt = false,
  amEnde = false,
  gruppiert,
  aufGruppiert,
  aufStrang,
  wischen,
  aufwachZeiten = {},
  auswahlmodus = false,
  aufAuswahlmodus,
  aufLangdruck,
  alleGewaehlt = false,
  aufAlleWaehlen,
}: Props) {
  /* Welche Stränge offen sind, samt ihrer Nachrichten.
     ⚠️ **Aufgeklappt bleibt aufgeklappt, bis man wieder klickt.** Ein Strang,
     der sich beim nächsten Nachladen von selbst schließt, verliert genau die
     Nachricht, die man gerade gesucht hat. */
  const [offeneStraenge, setOffeneStraenge] = useState<Record<string, Nachricht[]>>({})
  const { t, i18n } = useTranslation()
  const ungelesen = nachrichten.filter((n) => !n.gelesen).length

  /* Was in der zweiten Kopfzeile steht. Einmal benannt, weil die Zeile selbst
     wegfallen muss, wenn nichts davon zutrifft. */
  const zeigtFilter = filter !== undefined && Boolean(aufFilter) && filter !== 'markiert'
  const zeigtSchlagwortfilter =
    filter !== undefined && filter !== 'markiert' && Boolean(aufSchlagwortFilter) && schlagworte.length > 0
  const zeigtGruppiert = gruppiert !== undefined && Boolean(aufGruppiert)

  return (
    <div className="flex h-full min-h-0 flex-col border-r border-line-subtle bg-surface-1">
      {/* ⚠️ **Zwei Zeilen, nicht eine.** In einer Zeile standen Ordnername,
          Zahlen und drei Bedienelemente nebeneinander; sobald die Spalte
          schmaler wurde, schnitt es Ordnername und Schlagwort-Auswahl auf
          „Alle Pos…" und „Alle S…" zusammen. Am 02.09.2026 gemeldet: „Hier
          werden die Texte abgeschnitten. Das ist kacke."

          Oben steht seither, **wo man ist** und wie viel dort liegt; darunter,
          **wonach eingeschränkt wird**. „Gespräche" steht mit oben, weil die
          zweite Zeile sonst bei schmaler Spalte auf drei umbricht — sie ändert
          die Form der Liste, nicht ihren Inhalt. */}
      {auswahlmodus ? (
        /* Der Kopf im Auswahlmodus: links die Zahl, rechts „Alle" und
           „Fertig". Er ersetzt den Ordnerkopf, statt sich darunterzusetzen —
           auf 375 px zählt jede Zeile. `aria-live`, damit ein Vorleseprogramm
           die Zahl beim Antippen mitbekommt. */
        <div
          aria-live="polite"
          className="flex h-11 shrink-0 items-center gap-1 border-b border-accent-line px-1 pl-3"
        >
          <span className="min-w-0 flex-1 truncate text-[15px] font-semibold tabular-nums text-fg-1">
            {t('aktion.ausgewaehlt', { count: mehrfach.length })}
          </span>
          {aufAlleWaehlen && (
            <button
              type="button"
              onClick={aufAlleWaehlen}
              className="rounded-md px-2.5 py-1.5 text-[13px] font-medium text-accent-text hover:bg-accent-soft"
            >
              {alleGewaehlt ? t('aktion.keine') : t('aktion.alle')}
            </button>
          )}
          <button
            type="button"
            onClick={() => aufAuswahlmodus?.(false)}
            className="rounded-md px-2.5 py-1.5 text-[13px] font-medium text-accent-text hover:bg-accent-soft"
          >
            {t('aktion.fertig')}
          </button>
        </div>
      ) : (
      <div className="shrink-0 border-b border-line-subtle px-3 py-1.5">
        <div className="flex h-6 items-center gap-2">
          <h2 className="min-w-0 flex-1 truncate font-display text-[15px] font-medium text-fg-1">
            {titel}
          </h2>
          <span className="shrink-0 text-[11px] tabular-nums text-fg-4">
            {nachrichten.length === 1
              ? t('liste.anzahl_eine')
              : t('liste.anzahl_viele', { count: nachrichten.length })}
            {ungelesen > 0 && ` · ${t('liste.ungelesen', { count: ungelesen })}`}
          </span>

          {/* ⚠️ **Ein sichtbarer Weg in den Auswahlmodus**, neben dem langen
              Druck. Nur die Geste wäre ein Griff, den man nicht sieht — und
              den meldet niemand als „fehlt", sondern als „geht nicht". */}
          {aufAuswahlmodus && nachrichten.length > 0 && (
            <button
              type="button"
              onClick={() => aufAuswahlmodus(true)}
              className="shrink-0 rounded-md px-2 py-0.5 text-[12px] font-medium text-accent-text hover:bg-accent-soft"
            >
              {t('aktion.auswaehlen')}
            </button>
          )}

          {/* ⚠️ **Vorgabe aus, bis man ihr traut.** Falsch gruppiert steckt
              eine Mail in einem zugeklappten Strang, und man merkt es erst,
              wenn man sie sucht. Deshalb ein Umschalter und kein Zwang. */}
          {zeigtGruppiert && aufGruppiert && (
            <button
              type="button"
              aria-pressed={gruppiert}
              title={t('liste.gruppiert_hinweis')}
              onClick={() => aufGruppiert(!gruppiert)}
              className={
                'flex shrink-0 items-center gap-1 rounded-pill px-2.5 py-0.5 text-[11px] ' +
                'font-medium transition-colors duration-[var(--dur-fast)] ' +
                (gruppiert
                  ? 'bg-accent text-on-accent'
                  : 'border border-line text-fg-3 hover:bg-surface-3 hover:text-fg-1')
              }
            >
              <MessagesSquare aria-hidden className="size-3" />
              {t('liste.gruppiert')}
            </button>
          )}
        </div>

        {/* Die zweite Zeile entsteht nur, wenn es dort etwas zu bedienen gibt —
            bei „Markierte" bliebe sie sonst als leerer Streifen stehen. */}
        {(zeigtFilter || zeigtSchlagwortfilter) && (
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {/* ⚠️ **Der Umschalter gehört über die Liste, nicht in ein Menü.**
                „Wo sind meine Mails hin?" ist die Frage, die ein versteckter
                Filter erzeugt. Sichtbar über der Liste beantwortet er sie,
                bevor sie entsteht. */}
            {zeigtFilter && aufFilter && (
              <div className="flex shrink-0 items-center gap-0.5 rounded-pill border border-line bg-surface-2 p-0.5">
                {(['alle', 'ungelesen'] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    aria-pressed={filter === f}
                    onClick={() => aufFilter(f)}
                    className={
                      'rounded-pill px-2.5 py-0.5 text-[11px] font-medium transition-colors ' +
                      'duration-[var(--dur-fast)] ' +
                      (filter === f
                        ? 'bg-accent text-on-accent'
                        : 'text-fg-3 hover:bg-surface-3 hover:text-fg-1')
                    }
                  >
                    {t(`liste.filter_${f}`)}
                  </button>
                ))}
              </div>
            )}

            {/* Die Schlagwort-Auswahl — alle / je Definition. ⚠️ Gefiltert wird
                im Server; hier fällt nur die Wahl. Ohne Definitionen wäre die
                Auswahl ein Klick ins Leere und bleibt weg.

                ⚠️ **Feste Breite, kein `max-w`.** Der Baustein bringt seine
                eigene Hülle mit; eine Klasse am `select` bremst das Schrumpfen
                der Hülle nicht, und „Alle Schlagworte" stand dann als
                „Alle S…" da. */}
            {zeigtSchlagwortfilter && aufSchlagwortFilter && (
              <div className="w-[150px] shrink-0">
                <Select
                  size="sm"
                  aria-label={t('schlagworte.filter')}
                  value={schlagwortFilter}
                  onChange={(e) => aufSchlagwortFilter(e.target.value)}
                  className="text-[11px]"
                  options={[
                    { value: '', label: t('schlagworte.filter_alle') },
                    ...schlagworte.map((s) => ({ value: s.atom, label: s.name })),
                  ]}
                />
              </div>
            )}
          </div>
        )}
      </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {nachrichten.length === 0 ? (
          <EmptyState icon={<Inbox />} title={t('liste.leer_titel')} description={t('liste.leer_text')} />
        ) : (
          GRUPPEN.map((g) => {
            const drin = nachrichten.filter((n) => gruppeVon(n.datum) === g)
            if (drin.length === 0) return null
            return (
              <section key={g}>
                <h3 className="sticky top-0 z-10 bg-surface-2/95 px-3 py-1 text-[11px] font-semibold tracking-[0.06em] text-fg-4 uppercase backdrop-blur-sm">
                  {t(`liste.${g}`)}
                </h3>
                {drin.map((n) => {
                  const schluessel = n.strangSchluessel ?? ''
                  const istStrang = (n.strangAnzahl ?? 1) > 1 && Boolean(aufStrang)
                  const offen = Boolean(offeneStraenge[schluessel])

                  return (
                    <div key={n.id}>
                      <Zeile
                        n={n}
                        farbe={konten.find((k) => k.id === n.kontoId)?.farbe}
                        marken={markenVon(n, schlagworte)}
                        postfachZeigen={postfachZeigen}
                        gewaehlt={n.id === gewaehlt}
                        mitausgewaehlt={mehrfach.includes(n.id)}
                        onClick={(strg, umschalt) => aufWahl(n.id, strg, umschalt)}
                        aufKontext={aufKontext}
                        aufZiehen={aufZiehen}
                        kompakt={kompakt}
                        anreisserZeigen={anreisserZeigen}
                        sprache={i18n.language}
                        keinBetreff={t('liste.kein_betreff')}
                        wichtigHoch={t('liste.wichtig_hoch')}
                        aufwachText={
                          aufwachZeiten[n.id]
                            ? t('wiedervorlage.marke', {
                                wann: planzeit(aufwachZeiten[n.id], i18n.language),
                              })
                            : undefined
                        }
                        strangAnzahl={istStrang ? n.strangAnzahl : undefined}
                        strangOffen={offen}
                        aufStrangKlappen={
                          istStrang
                            ? async () => {
                                if (offen) {
                                  setOffeneStraenge((v) => {
                                    const kopie = { ...v }
                                    delete kopie[schluessel]
                                    return kopie
                                  })
                                  return
                                }
                                const mails = (await aufStrang?.(schluessel)) ?? []
                                setOffeneStraenge((v) => ({ ...v, [schluessel]: mails }))
                              }
                            : undefined
                        }
                        strangText={
                          offen ? t('liste.strang_zuklappen') : t('liste.strang_aufklappen')
                        }
                        wisch={auswahlmodus ? undefined : wischen}
                        auswahlmodus={auswahlmodus}
                        aufLangdruck={aufLangdruck}
                      />

                      {/* ⚠️ **Die Kopfzeile bleibt stehen.** Sie ist die
                          neueste Nachricht des Strangs; sie beim Aufklappen
                          auszublenden hieße, dass die Zeile unter dem Finger
                          verschwindet. */}
                      {offen &&
                        offeneStraenge[schluessel]
                          .filter((m) => m.id !== n.id)
                          .map((m) => (
                            <div key={m.id} className="border-l-2 border-line-subtle pl-3">
                              <Zeile
                                n={m}
                                farbe={konten.find((k) => k.id === m.kontoId)?.farbe}
                                marken={markenVon(m, schlagworte)}
                                postfachZeigen={postfachZeigen}
                                gewaehlt={m.id === gewaehlt}
                                mitausgewaehlt={mehrfach.includes(m.id)}
                                onClick={(strg, umschalt) => aufWahl(m.id, strg, umschalt)}
                                aufKontext={aufKontext}
                                aufZiehen={aufZiehen}
                                kompakt
                                anreisserZeigen={false}
                                sprache={i18n.language}
                                keinBetreff={t('liste.kein_betreff')}
                                wichtigHoch={t('liste.wichtig_hoch')}
                                aufwachText={
                                  aufwachZeiten[m.id]
                                    ? t('wiedervorlage.marke', {
                                        wann: planzeit(aufwachZeiten[m.id], i18n.language),
                                      })
                                    : undefined
                                }
                                wisch={auswahlmodus ? undefined : wischen}
                                auswahlmodus={auswahlmodus}
                                aufLangdruck={aufLangdruck}
                              />
                            </div>
                          ))}
                    </div>
                  )
                })}
              </section>
            )
          })
        )}

        {/* ⚠️ **Das Ende der Liste muss man sehen.** Ohne diesen Fuß hört sie
            einfach auf, und „mehr gibt es nicht" ist von „mehr wird nicht
            angezeigt" nicht zu unterscheiden. Genau der Zustand bis zum
            01.09.2026: Nach 200 Zeilen kam nichts, und nichts sagte es. */}
        {nachrichten.length > 0 && aufMehr && (
          <Fuss
            laedt={mehrLaedt}
            amEnde={amEnde}
            aufMehr={aufMehr}
            texte={{
              laedt: t('liste.mehr_laedt'),
              ende: t('liste.ende'),
              knopf: t('liste.mehr_knopf'),
            }}
          />
        )}
      </div>
    </div>
  )
}

/** Der Fuß der Liste: lädt selbsttätig nach, sobald er in Sicht kommt.
 *
 * ⚠️ **Und trägt trotzdem einen Knopf.** Das selbsttätige Nachladen hängt
 * daran, dass der Fuß je in Sichtweite gerät — bei einem Fenster ohne
 * Rollbalken tut er das nie, und die Liste wirkt am Ende. Der Knopf ist der
 * Weg, der immer geht.
 */
function Fuss({
  laedt,
  amEnde,
  aufMehr,
  texte,
}: {
  laedt: boolean
  amEnde: boolean
  aufMehr: () => void
  texte: { laedt: string; ende: string; knopf: string }
}) {
  const marke = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const el = marke.current
    if (!el || amEnde || laedt) return
    const wache = new IntersectionObserver(
      (eintraege) => {
        if (eintraege.some((e) => e.isIntersecting)) aufMehr()
      },
      // Etwas vorher anfangen, damit nachgeladen ist, bevor man unten ankommt.
      { rootMargin: '300px' },
    )
    wache.observe(el)
    return () => wache.disconnect()
  }, [amEnde, laedt, aufMehr])

  return (
    <div ref={marke} className="flex items-center justify-center px-3 py-4">
      {laedt ? (
        <span className="text-[12px] text-fg-4">{texte.laedt}</span>
      ) : amEnde ? (
        <span className="text-[12px] text-fg-4">{texte.ende}</span>
      ) : (
        <button
          type="button"
          onClick={aufMehr}
          className="rounded-pill border border-line px-3 py-1 text-[12px] text-fg-3 transition-colors duration-[var(--dur-fast)] hover:border-accent hover:text-fg-1"
        >
          {texte.knopf}
        </button>
      )}
    </div>
  )
}

/** Die Farbmarken einer Zeile: die Atome der Mail, mit Name und Farbe aus den
 *  Definitionen. Ein Atom ohne Definition (frisch vom Server, noch nie
 *  abgeglichen) erscheint trotzdem — mit dem Atom als Namen. */
function markenVon(n: Nachricht, definitionen: Schlagwort[]) {
  return (n.schlagworte ?? []).map((atom) => {
    const def = definitionen.find((d) => d.atom.toLowerCase() === atom.toLowerCase())
    return { atom, name: def?.name ?? atom, farbe: (def?.farbe ?? 1) as Postfachfarbe }
  })
}

interface ZeileProps {
  n: Nachricht
  farbe?: 1 | 2 | 3 | 4 | 5 | 6
  /** Die gesetzten Schlagworte als Farbmarken — mit Name für title/aria. */
  marken?: { atom: string; name: string; farbe: Postfachfarbe }[]
  postfachZeigen: boolean
  gewaehlt: boolean
  mitausgewaehlt: boolean
  onClick: (strg: boolean, umschalt: boolean) => void
  aufKontext: (e: React.MouseEvent, n: Nachricht) => void
  aufZiehen?: (n: Nachricht) => string[]
  kompakt?: boolean
  anreisserZeigen?: boolean
  sprache: string
  keinBetreff: string
  /** Vorlesbarer Name des Ausrufezeichens bei hoher Wichtigkeit. */
  wichtigHoch: string
  /** Fertig übersetzte Aufwach-Marke der Wiedervorlage — nur an Zeilen mit
   *  Eintrag gesetzt. Der Text kommt von oben, damit die Zeile keine eigene
   *  Übersetzung braucht (dasselbe Muster wie `keinBetreff`). */
  aufwachText?: string
  /** Gesetzt heißt: Diese Zeile ist der Kopf eines Gesprächs. */
  strangAnzahl?: number
  strangOffen?: boolean
  aufStrangKlappen?: () => void
  strangText?: string
  /** Wischen am Finger — nur in der schmalen Ansicht gesetzt. */
  wisch?: Wischen
  /** Auswahlmodus der schmalen Ansicht: Kreis links, Tipp markiert. */
  auswahlmodus?: boolean
  /** Langer Druck — nur in der schmalen Ansicht gesetzt. */
  aufLangdruck?: (n: Nachricht) => void
}

/** Farbe und Symbol, die hinter der Zeile erscheinen, wenn man sie zieht.
 *  ⚠️ Nur Tokens: danger fuer Loeschen, accent fuer Archivieren, info fuer
 *  den Gelesen-Umschalter — dieselben Farben, die die Aktionen auch sonst
 *  tragen. */
function wischBild(aktion: WischAktion, gelesen: boolean) {
  switch (aktion) {
    case 'loeschen':
      return { Symbol: Trash2, klasse: 'bg-danger' }
    case 'archivieren':
      return { Symbol: Archive, klasse: 'bg-accent' }
    case 'gelesen':
      return { Symbol: gelesen ? Mail : MailOpen, klasse: 'bg-info' }
    default:
      return null
  }
}

function Zeile({
  strangAnzahl,
  strangOffen = false,
  aufStrangKlappen,
  strangText,
  n,
  farbe,
  marken = [],
  postfachZeigen,
  gewaehlt,
  mitausgewaehlt,
  onClick,
  aufKontext,
  aufZiehen,
  kompakt = false,
  anreisserZeigen = true,
  sprache,
  keinBetreff,
  wichtigHoch,
  aufwachText,
  wisch,
  auswahlmodus = false,
  aufLangdruck,
}: ZeileProps) {
  /* --- Wischen: die Zeile mit dem Finger zur Seite ziehen --------------- */
  const [zugX, setZugX] = useState(0)
  /* Nur beim Zurueckschnappen laeuft eine Transition. Waehrend des Ziehens
     muss die Zeile am Finger kleben — eine Transition dort macht sie zaeh. */
  const [schnappt, setSchnappt] = useState(false)
  /* Die Lage des laufenden Zugs. `modus` entscheidet sich frueh und dann nie
     wieder: 'waagerecht' gehoert die Geste der Zeile, bei 'aus' dem Rollen
     des Browsers (`touch-action: pan-y` laesst ihm genau das). */
  const lage = useRef<{
    id: number
    x0: number
    y0: number
    breite: number
    modus: 'offen' | 'waagerecht' | 'aus'
  } | null>(null)
  /* ⚠️ Nach dem Loslassen feuert der Browser noch ein `click` auf die Zeile.
     Ohne diese Merke oeffnete jeder Wisch zusaetzlich die Nachricht. */
  const gewischt = useRef(false)

  /* --- Langer Druck: der Weg in den Auswahlmodus ------------------------ */
  /* Die Uhr läuft ab `pointerdown`; Bewegung über die Toleranz, Loslassen
     und Verlassen brechen sie ab. Feuert sie, ist der folgende `click` kein
     Öffnen mehr — dieselbe Merke wie `gewischt` beim Wisch. */
  const druckUhr = useRef<number | undefined>(undefined)
  const druckStart = useRef<{ x: number; y: number } | null>(null)
  const gehalten = useRef(false)
  /* Womit zuletzt gedrückt wurde. Ein `contextmenu` sagt es nicht selbst —
     und nur das vom Finger (Android macht aus dem langen Druck eines) soll
     schmal verworfen werden; die Maus behält ihr Menü auch im schmalen
     Fenster. */
  const letzterZeiger = useRef<string>('mouse')

  function druckAbbrechen() {
    window.clearTimeout(druckUhr.current)
    druckUhr.current = undefined
    druckStart.current = null
  }

  function druckBeginn(e: React.PointerEvent<HTMLButtonElement>) {
    letzterZeiger.current = e.pointerType
    if (!aufLangdruck || !e.isPrimary) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    gehalten.current = false
    druckStart.current = { x: e.clientX, y: e.clientY }
    druckUhr.current = window.setTimeout(() => {
      druckUhr.current = undefined
      druckStart.current = null
      gehalten.current = true
      // Ein kurzes Zittern sagt „gemerkt" — wo der Browser es kann.
      if (typeof navigator.vibrate === 'function') navigator.vibrate(10)
      aufLangdruck(n)
    }, LANGDRUCK_MS)
  }

  function druckZug(e: React.PointerEvent<HTMLButtonElement>) {
    const start = druckStart.current
    if (!start || druckUhr.current === undefined) return
    if (zuWeitGewandert(start.x, start.y, e.clientX, e.clientY)) druckAbbrechen()
  }

  useEffect(() => () => window.clearTimeout(druckUhr.current), [])

  function wischBeginn(e: React.PointerEvent<HTMLButtonElement>) {
    // ⚠️ **Nur der Finger wischt.** Die Maus zieht Zeilen in den Ordnerbaum
    // (HTML-Drag); dieselbe Bewegung auch als Wisch zu deuten hiesse, dass
    // ein angefangenes Verschieben eine Mail loescht.
    if (!wisch || e.pointerType !== 'touch') return
    gewischt.current = false
    setSchnappt(false)
    lage.current = {
      id: e.pointerId,
      x0: e.clientX,
      y0: e.clientY,
      breite: e.currentTarget.clientWidth,
      modus: 'offen',
    }
  }

  function wischZug(e: React.PointerEvent<HTMLButtonElement>) {
    const z = lage.current
    if (!wisch || !z || e.pointerId !== z.id) return
    const dx = e.clientX - z.x0
    const dy = e.clientY - z.y0
    if (z.modus === 'offen') {
      // Erst entscheiden, wem die Geste gehoert — und dabei bleiben. Eine
      // Geste, die mitten im Zug die Deutung wechselt, rollt und wischt
      // gleichzeitig.
      if (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) {
        z.modus = 'waagerecht'
        try {
          e.currentTarget.setPointerCapture(e.pointerId)
        } catch {
          // Synthetische Zeiger (Tests) haben keinen fangbaren Zeiger — egal.
        }
      } else if (Math.abs(dy) > 8) {
        z.modus = 'aus'
      } else {
        return
      }
    }
    if (z.modus !== 'waagerecht') return
    // Eine ausgeschaltete Richtung gibt nicht nach. Gaebe die Zeile trotzdem
    // etwas Weg, saehe es aus, als kaeme gleich eine Aktion — und beim
    // Loslassen passierte nichts.
    const aktion = dx < 0 ? wisch.links : wisch.rechts
    setZugX(aktion === 'aus' ? 0 : dx)
  }

  function wischEnde(e: React.PointerEvent<HTMLButtonElement>) {
    const z = lage.current
    if (!wisch || !z || e.pointerId !== z.id) return
    lage.current = null
    if (z.modus === 'waagerecht') {
      gewischt.current = true
      const dx = e.clientX - z.x0
      const aktion = dx < 0 ? wisch.links : wisch.rechts
      // `pointercancel` heisst: Der Browser hat die Geste an sich gerissen.
      // Dann darf hier nichts mehr passieren, egal wie weit gezogen war.
      if (e.type === 'pointerup' && aktion !== 'aus' && Math.abs(dx) >= wischSchwelle(z.breite)) {
        wisch.ausfuehren(n, aktion)
      }
    }
    setSchnappt(true)
    setZugX(0)
  }

  const wischAktion = wisch && zugX !== 0 ? (zugX < 0 ? wisch.links : wisch.rechts) : null
  const bild = wischAktion ? wischBild(wischAktion, n.gelesen) : null
  const ueberSchwelle = Math.abs(zugX) >= wischSchwelle(lage.current?.breite ?? 0)

  return (
    <div className="relative overflow-hidden">
      {/* Farbe und Symbol hinter der Zeile sagen VOR dem Loslassen, was
          passieren wird. Volle Deckung erst ab der Schwelle — das ist die
          Rueckmeldung „jetzt gilt es", ohne ein Wort. */}
      {bild && (
        <div
          aria-hidden
          className={
            `absolute inset-0 flex items-center px-5 ${bild.klasse} ` +
            (zugX < 0 ? 'justify-end' : 'justify-start')
          }
          style={{ opacity: ueberSchwelle ? 1 : 0.55 }}
        >
          <bild.Symbol className="size-5 text-on-accent" />
        </div>
      )}
    <button
      type="button"
      // ⚠️ **Ziehen statt Menü — der Weg, den Outlook-Leute zuerst probieren.**
      // Mitgegeben werden die Kennungen als Text; das Ablegen im Ordnerbaum
      // liest sie wieder. Ein eigener MIME-Typ wäre sauberer, aber Firefox
      // gibt in `dragover` nur die *Typen* preis, nicht den Inhalt — und ohne
      // Inhalt kann der Ordner nicht entscheiden, ob er das annehmen darf.
      draggable={Boolean(aufZiehen)}
      onDragStart={(e) => {
        const ids = aufZiehen?.(n) ?? []
        if (ids.length === 0) return
        e.dataTransfer.setData('text/nexmail-nachrichten', JSON.stringify(ids))
        e.dataTransfer.setData('text/plain', String(ids.length))
        e.dataTransfer.effectAllowed = 'move'
      }}
      onClick={(e) => {
        // ⚠️ Nach einem Wisch kommt noch ein Klick hinterher — der darf die
        // Nachricht nicht oeffnen: Man wollte wegwischen, nicht lesen.
        if (gewischt.current) {
          gewischt.current = false
          return
        }
        // Dasselbe nach einem langen Druck: Er hat schon markiert.
        if (gehalten.current) {
          gehalten.current = false
          return
        }
        // Im Auswahlmodus markiert ein Tipp, wie ein Strg-Klick am Rechner.
        if (auswahlmodus) {
          onClick(true, false)
          return
        }
        onClick(e.ctrlKey || e.metaKey, e.shiftKey)
      }}
      onPointerDown={(e) => {
        druckBeginn(e)
        if (wisch) wischBeginn(e)
      }}
      onPointerMove={(e) => {
        druckZug(e)
        if (wisch) wischZug(e)
      }}
      onPointerUp={(e) => {
        druckAbbrechen()
        if (wisch) wischEnde(e)
      }}
      onPointerCancel={(e) => {
        druckAbbrechen()
        if (wisch) wischEnde(e)
      }}
      onPointerLeave={druckAbbrechen}
      /* `touch-action: pan-y`: Senkrecht rollt der Browser wie immer, nur
         waagerechte Zuege kommen ueberhaupt als Pointer-Events hier an. */
      style={{
        ...(wisch
          ? {
              touchAction: 'pan-y',
              transform: `translateX(${zugX}px)`,
              transition: schnappt ? 'transform var(--dur-fast) ease-out' : 'none',
            }
          : undefined),
        /* ⚠️ Ohne diese beiden zeigt das iPhone beim langen Druck seine
           eigene Sprechblase und markiert Text — statt der Zeile. */
        ...(aufLangdruck ? { WebkitTouchCallout: 'none', userSelect: 'none' } : undefined),
      }}
      onContextMenu={(e) => {
        // ⚠️ Schmal gehoert der lange Druck dem Auswahlmodus. Android macht
        // daraus ein `contextmenu`; das Schreibtisch-Menue soll dort nicht
        // zusaetzlich aufgehen, und die Sprechblase des Browsers auch nicht.
        if (aufLangdruck && (letzterZeiger.current !== 'mouse' || gehalten.current)) {
          e.preventDefault()
          return
        }
        // Rechtsklick waehlt die Zeile mit aus - aber nur, wenn sie nicht
        // ohnehin schon zur Mehrfachauswahl gehoert. Sonst wirkt das Menue
        // auf eine Nachricht, waehrend rechts eine andere offen ist, und man
        // loescht die falsche. Umgekehrt darf ein Rechtsklick auf eine
        // ausgewaehlte Zeile die Auswahl nicht wegwerfen.
        if (!mitausgewaehlt) onClick(false, false)
        aufKontext(e, n)
      }}
      aria-current={gewaehlt ? 'true' : undefined}
      aria-pressed={auswahlmodus ? mitausgewaehlt : undefined}
      className={
        'relative flex w-full gap-2.5 border-b border-line-subtle px-3 text-left ' +
        (kompakt ? 'py-1 ' : 'py-2 ') +
        'transition-colors duration-[var(--dur-fast)] ' +
        (gewaehlt
          ? 'bg-accent-soft'
          : mitausgewaehlt
            ? 'bg-surface-3 ring-1 ring-inset ring-accent-line'
            : 'hover:bg-surface-3')
      }
    >
      {/* Der Balken links sagt "ungelesen". Er sitzt am Rand und nicht in der
          Zeile, damit die Textspalten aller Zeilen buendig bleiben. */}
      {!n.gelesen && (
        <span aria-hidden className="absolute top-2 bottom-2 left-0 w-[3px] rounded-pill bg-accent" />
      )}

      {/* Der Kreis des Auswahlmodus — links, wie in Outlook und Apple Mail.
          Gefüllt mit Haken heißt gewählt; der Zustand steht zusätzlich in
          `aria-pressed` am Knopf, das Bild allein wäre stumm. */}
      {auswahlmodus && (
        <span
          aria-hidden
          className={
            'mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full border ' +
            'transition-colors duration-[var(--dur-fast)] ' +
            (mitausgewaehlt ? 'border-accent bg-accent text-on-accent' : 'border-line')
          }
        >
          {mitausgewaehlt && <Check className="size-3.5" strokeWidth={3} />}
        </span>
      )}

      <div className="mt-1 flex w-2 shrink-0 flex-col items-center gap-1">
        {postfachZeigen && farbe && (
          <span aria-hidden className={`size-2 rounded-full ${PUNKT_KLASSE[farbe]}`} />
        )}
      </div>

      {/* ⚠️ **Ein eigener Knopf, kein Klick auf die Zeile.** Die Zeile öffnet
          die Mail — das darf das Aufklappen nicht überschreiben, sonst kommt
          man an die neueste Nachricht eines Gesprächs nicht mehr heran. */}
      {strangAnzahl !== undefined && aufStrangKlappen && (
        <span
          role="button"
          tabIndex={0}
          aria-label={strangText}
          aria-expanded={strangOffen}
          onClick={(e) => {
            e.stopPropagation()
            aufStrangKlappen()
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              e.stopPropagation()
              aufStrangKlappen()
            }
          }}
          className="mt-0.5 flex shrink-0 items-center gap-0.5 rounded-sm px-1 text-[11px] text-fg-3 hover:bg-surface-3 hover:text-fg-1"
        >
          {strangOffen ? (
            <ChevronDown aria-hidden className="size-3" />
          ) : (
            <ChevronRight aria-hidden className="size-3" />
          )}
          <span className="tabular-nums">{strangAnzahl}</span>
        </span>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span
            className={
              'min-w-0 flex-1 truncate text-[13px] ' +
              (n.gelesen ? 'text-fg-2' : 'font-semibold text-fg-1')
            }
          >
            {anzeigename(n.von)}
          </span>
          {/* Die Farbmarken der gesetzten Schlagworte. ⚠️ Rechtecke, keine
              Punkte — der Punkt links am Rand gehört dem Postfach, und zwei
              gleiche Formen in einer Zeile liest man falsch. */}
          {marken.map((m) => (
            <Schlagwortmarke key={m.atom} farbe={m.farbe} name={m.name} />
          ))}
          {/* ⚠️ Nicht nur Farbe: Das Zeichen selbst plus ein vorlesbarer Name.
              Niedrig erscheint in der Liste bewusst gar nicht — ein Zeichen
              für „unwichtig" wäre lauter als die Post, die es meint. */}
          {n.wichtigkeit === 'hoch' && (
            <span
              role="img"
              aria-label={wichtigHoch}
              className="shrink-0 text-[13px] leading-none font-bold text-danger"
            >
              !
            </span>
          )}
          {n.markiert && <Flag className="size-3 shrink-0 fill-current text-warning" />}
          {n.anhaenge.length > 0 && <Paperclip className="size-3 shrink-0 text-fg-4" />}
          <span className="shrink-0 text-[11px] tabular-nums text-fg-4">
            {kurzesDatum(n.datum, sprache)}
          </span>
        </div>

        <div className={'truncate text-[13px] ' + (n.gelesen ? 'text-fg-2' : 'font-medium text-fg-1')}>
          {n.betreff || keinBetreff}
        </div>

        {/* Die Aufwach-Marke der Wiedervorlage — klein, übersetzt, Ortszeit.
            Die Uhr ist Beiwerk (aria-hidden); die Auskunft ist der Text. */}
        {aufwachText && (
          <div className="flex items-center gap-1 text-[11px] text-fg-3">
            <Clock aria-hidden className="size-3 shrink-0" />
            <span className="truncate">{aufwachText}</span>
          </div>
        )}

        {anreisserZeigen && (
          <div className="truncate text-[12px] text-fg-4">{n.anreisser}</div>
        )}
      </div>
    </button>
    </div>
  )
}
