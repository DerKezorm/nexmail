/* Die Ordnerspalte — die Wahrheit darueber, wo eine Nachricht liegt.
 *
 * Aufbau von oben nach unten:
 *
 *   "Alle Posteingaenge"  — der Sammel-Blick, immer da
 *   Favoriten            — quer ueber alle Postfaecher, nur wenn welche da sind
 *   je Postfach ein Baum — einklappbar auf den blossen Namen
 *
 * Zwei Feinheiten, die man leicht falsch macht:
 *
 * 1. **Ein Favorit traegt den Punkt seines Postfachs.** Drei Postfaecher
 *    haben drei Ordner namens "Posteingang" - ohne Punkt waeren drei
 *    gleichnamige Zeilen untereinander nicht auseinanderzuhalten.
 * 2. **Ein eingeklapptes Postfach zeigt weiter seine Ungelesen-Zahl.** Sonst
 *    versteckt das Einklappen genau die Angabe, wegen der man hinsieht - und
 *    dann klappt man es doch wieder auf.
 *
 * Sonderordner zuerst, in der Reihenfolge, in der man sie braucht; darunter
 * die eigenen. Nicht abonnierte Ordner erscheinen gar nicht - iCloud und
 * Gmail legen welche an, die niemand sehen will.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Archive,
  Clock,
  Flag,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  Inbox,
  Plus,
  Send,
  ShieldAlert,
  Star,
  Trash2,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Konto, Ordner, OrdnerRolle } from '../daten/typen'
import { PUNKT_KLASSE } from '../lib/farben'

/* ⚠️ **„Markierte" ist ein Ziel, kein Ordner.**
 *
 * Es liegt in keinem Postfach, sondern quer über allen: Was man sich vormerkt,
 * merkt man sich als Mensch, nicht je Konto. Ein Filter über der Liste hätte
 * das nicht geleistet — der wirkt immer nur auf den gerade offenen Ordner.
 *
 * „Ausgang" genauso: Die Warteschlange liegt in nexmail, nicht beim Anbieter —
 * ein geplanter Versand gehört zu keinem IMAP-Ordner. */
export type Ziel =
  | { typ: 'alle' }
  | { typ: 'markiert' }
  | { typ: 'ausgang' }
  | { typ: 'ordner'; id: string }

const SYMBOL: Record<OrdnerRolle, ReactNode> = {
  posteingang: <Inbox />,
  gesendet: <Send />,
  entwuerfe: <FileText />,
  archiv: <Archive />,
  junk: <ShieldAlert />,
  papierkorb: <Trash2 />,
  eigen: <Folder />,
}

/** Reihenfolge der Sonderordner. Eigene haengen sich hinten an. */
const RANG: Record<OrdnerRolle, number> = {
  posteingang: 0,
  gesendet: 1,
  entwuerfe: 2,
  archiv: 3,
  junk: 4,
  papierkorb: 5,
  eigen: 6,
}

/* ⚠️ **„INBOX" ist ein Protokollwort, kein Name.** Der Ordner heißt auf jedem
 * IMAP-Server so, und kein Mensch nennt ihn so. Outlook zeigt „Posteingang",
 * also zeigt nexmail das auch.
 *
 * Bewusst **nur** für den Posteingang: Die übrigen Sonderordner tragen den
 * Namen, den der Betreiber auf seinem Server sieht. Wer dort „Spam" angelegt
 * hat, soll nicht „Junk" lesen. */
function anzeigename(o: { rolle: string; name: string }, t: (s: string) => string) {
  return o.rolle === 'posteingang' ? t('ordner.posteingang') : o.name
}


interface Props {
  konten: Konto[]
  ordner: Ordner[]
  ziel: Ziel
  aufZiel: (z: Ziel) => void
  aufPostfachHinzufuegen: () => void
  aufKontext: (e: React.MouseEvent, o: Ordner) => void
  /** Kennungen der Ordner, die oben unter "Favoriten" stehen. */
  favoriten: string[]
  /** Kennungen der Postfaecher, deren Baum zugeklappt ist. */
  eingeklappt: string[]
  aufEinklappen: (kontoId: string) => void
  /** Fallengelassene Nachrichten in diesen Ordner verschieben. */
  aufAblegen?: (ordnerId: string, ids: string[]) => void
  /** Aus welchem Postfach die gezogenen Nachrichten kommen — leer heißt: es
   *  wird gerade nichts gezogen. */
  ziehtAusKonto?: string
  /** Ein Satz, warum ein Ordner den Zug nicht annehmen kann. */
  aufAbweisung?: (grund: string) => void
  /* ⚠️ **Das gewählte Schlagwort wohnt oben, nicht hier.** Es beschränkt
     nicht nur den Baum, sondern auch „Alle Posteingänge" und „Markierte" —
     und die holt `App` beim Server. Ein Zustand nur in dieser Spalte hieße:
     Der Baum zeigt „privat", die Liste zeigt alles. */
  gruppe: string
  aufGruppe: (wort: string) => void
  /** Wie viele Nachrichten im Postausgang warten — geplant oder liegen
   *  geblieben. 0 blendet die Zeile aus: Ein Ausgang, der fast immer leer
   *  ist, waere sonst eine Zeile, die fast immer nichts sagt. */
  ausgangZahl: number
  /** Wartende Wiedervorlage-Eintraege je Postfach (kontoId → Zahl). Die Zahl
   *  steht an der Zeile des Wiedervorlage-Ordners, wenn sie groesser 0 ist. */
  wiedervorlageZahlen?: Record<string, number>
}

/* Der Wiedervorlage-Ordner heisst auf jedem Server gleich — der Name ist im
 * Server festgelegt (services/wiedervorlage.ORDNER_NAME), oberste Ebene. */
const WIEDERVORLAGE_PFAD = 'Wiedervorlage'

export function Ordnerspalte({
  konten,
  ordner,
  ziel,
  aufZiel,
  aufPostfachHinzufuegen,
  aufKontext,
  favoriten,
  eingeklappt,
  aufEinklappen,
  aufAblegen,
  ziehtAusKonto = '',
  aufAbweisung,
  gruppe,
  aufGruppe,
  ausgangZahl,
  wiedervorlageZahlen = {},
}: Props) {
  // Über welchem Ordner der Zeiger gerade schwebt. ⚠️ Ohne sichtbares Ziel
  // ist Ziehen ein Ratespiel: Man lässt los und weiß erst hinterher, wo es
  // gelandet ist.
  const [ueber, setUeber] = useState<string | null>(null)



  /** Warum dieser Ordner den gerade gezogenen Zug nicht annehmen kann. */
  function abweisungFuer(o: Ordner): string {
    if (!ziehtAusKonto || o.kontoId === ziehtAusKonto) return ''
    // ⚠️ IMAP kennt kein Verschieben über Kontogrenzen. Das ist keine Lücke
    // in nexmail, sondern eine Eigenschaft des Protokolls — und genau deshalb
    // muss es dastehen statt still nicht zu funktionieren.
    return t('ordner.fremdes_postfach')
  }
  const { t } = useTranslation()

  // ⚠️ Die Zahl an „Alle Posteingänge" folgt demselben Schlagwort wie die
  // Liste dahinter. Eine Zahl, die mehr verspricht als der Klick zeigt, ist
  // schlimmer als keine.
  /* Alle vergebenen Schlagworte, in der Reihenfolge der Postfächer.
     ⚠️ **Verglichen wird klein geschrieben, angezeigt die erste Schreibweise.**
     Sonst stünden „Arbeit" und „arbeit" als zwei Pillen nebeneinander, die
     gleich aussehen und Verschiedenes filtern. Dieselbe Regel wie im Server. */
  const schlagworte: string[] = []
  for (const k of konten) {
    for (const w of k.tags ?? []) {
      if (!schlagworte.some((v) => v.toLowerCase() === w.toLowerCase())) schlagworte.push(w)
    }
  }

  // Ein Schlagwort, das an keinem Postfach mehr hängt, darf nicht alles
  // ausblenden — sonst steht die Spalte nach dem Löschen eines Postfachs leer
  // da und niemand weiß, warum.
  const gewaehlt = schlagworte.some((w) => w.toLowerCase() === gruppe.toLowerCase()) ? gruppe : ''
  const sichtbareKonten = gewaehlt
    ? konten.filter((k) => (k.tags ?? []).some((w) => w.toLowerCase() === gewaehlt.toLowerCase()))
    : konten

  const ungelesenGesamt = ordner
    .filter((o) => o.rolle === 'posteingang')
    .filter((o) => sichtbareKonten.some((k) => k.id === o.kontoId))
    .reduce((s, o) => s + o.ungelesen, 0)


  // Reihenfolge wie angeheftet, nicht alphabetisch: Wer etwas nach oben legt,
  // legt es an eine Stelle.
  const angeheftet = favoriten
    .map((id) => ordner.find((o) => o.id === id))
    .filter((o): o is Ordner => Boolean(o))
    /* ⚠️ **Favoriten folgen dem Schlagwort, „Alle Posteingänge" nicht.**
       Das ist kein Versehen: „Alle Posteingänge" ist ausdrücklich der Ort, an
       dem nichts fehlt — ein Favorit dagegen ist ein Ordner in genau einem
       Postfach, und ein Arbeitsordner unter „privat" wäre dieselbe
       Vermischung, die der Umschalter aufheben soll. */
    .filter((o) => sichtbareKonten.some((k) => k.id === o.kontoId))

  function farbeVon(kontoId: string) {
    return konten.find((k) => k.id === kontoId)?.farbe
  }


  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-1">
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {/* ⚠️ **Der Umschalter steht über dem, was er filtert.** In einem Menü
            versteckt erzeugt ein Filter die Frage „wo sind meine Postfächer
            hin?" — sichtbar beantwortet er sie, bevor sie entsteht. Erst ab
            zwei Schlagworten: Bei einem gäbe es nichts umzuschalten. */}
        {schlagworte.length > 1 && (
          <div
            role="group"
            aria-label={t('ordner.gruppe_hinweis')}
            className="mb-2 flex flex-wrap gap-1 px-0.5"
          >
            {['', ...schlagworte].map((w) => (
              <button
                key={w || '__alle__'}
                type="button"
                aria-pressed={gewaehlt === w}
                onClick={() => aufGruppe(w)}
                className={
                  'rounded-pill px-2.5 py-0.5 text-[11px] font-medium transition-colors ' +
                  'duration-[var(--dur-fast)] ' +
                  (gewaehlt === w
                    ? 'bg-accent text-on-accent'
                    : 'border border-line text-fg-3 hover:bg-surface-3 hover:text-fg-1')
                }
              >
                {w || t('ordner.gruppe_alle')}
              </button>
            ))}
          </div>
        )}

        <Zeile
          symbol={<Inbox />}
          /* ⚠️ **„Alle Posteingänge" folgt dem Schlagwort** — am 01.09.2026
              zuerst andersherum entschieden und noch am selben Tag gedreht:
              „alle postfächer und markiert soll sich nur auf die ausgewählte
              tag gruppe beziehen". Eine Sammelansicht, die den Filter
              ignoriert, macht das Umschalten wertlos. */
          name={t('ordner.alle_posteingaenge')}
          ungelesen={ungelesenGesamt}
          aktiv={ziel.typ === 'alle'}
          onClick={() => aufZiel({ typ: 'alle' })}
        />

        <Zeile
          symbol={<Flag />}
          name={t('ordner.markierte')}
          ungelesen={0}
          aktiv={ziel.typ === 'markiert'}
          onClick={() => aufZiel({ typ: 'markiert' })}
        />

        {/* Der Postausgang — nur sichtbar, wenn etwas wartet. Die Zahl sagt
            wie viel; das Schlagwort filtert hier nicht, denn die Warteschlange
            gehört zu keinem Postfachbaum. */}
        {ausgangZahl > 0 && (
          <Zeile
            symbol={<Clock />}
            name={t('ordner.postausgang')}
            ungelesen={ausgangZahl}
            aktiv={ziel.typ === 'ausgang'}
            onClick={() => aufZiel({ typ: 'ausgang' })}
          />
        )}

        {angeheftet.length > 0 && (
          <section className="mt-4">
            <div className="flex items-center gap-2 px-2 pb-1">
              <Star className="size-3 shrink-0 fill-current text-warning" />
              <span className="truncate text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
                {t('ordner.favoriten')}
              </span>
            </div>
            {angeheftet.map((o) => (
              <Zeile
                key={`fav-${o.id}`}
                symbol={SYMBOL[o.rolle]}
                /* ⚠️ **Der Punkt allein genügt nicht.** Zwei Postfächer haben
                   beide einen „Posteingang"; unter „Favoriten" stünde er
                   zweimal gleich, und nur die Farbe unterschiede sie — das
                   liest niemand ab. Der Name des Postfachs muss dastehen. */
                name={`${anzeigename(o, t)} (${
                  konten.find((k) => k.id === o.kontoId)?.anzeigename ?? '?'
                })`}
                punkt={farbeVon(o.kontoId)}
                ungelesen={o.ungelesen}
                wartend={o.pfad === WIEDERVORLAGE_PFAD ? (wiedervorlageZahlen[o.kontoId] ?? 0) : 0}
                aktiv={ziel.typ === 'ordner' && ziel.id === o.id}
                onClick={() => aufZiel({ typ: 'ordner', id: o.id })}
                onContextMenu={(e) => aufKontext(e, o)}
                ablegbar={Boolean(aufAblegen)}
                abweisung={abweisungFuer(o)}
                ueber={ueber === o.id}
                aufUeber={(an) => setUeber(an ? o.id : null)}
                aufAblegen={(ids) => aufAblegen?.(o.id, ids)}
                aufAbweisungZeile={aufAbweisung}
              />
            ))}
          </section>
        )}

        {sichtbareKonten.map((k) => {
          const zu = eingeklappt.includes(k.id)
          const meine = baumBilden(ordner.filter((o) => o.kontoId === k.id))
          const ungelesenHier = meine.reduce(
            (s, { ordner: o }) => s + (o.rolle === 'papierkorb' ? 0 : o.ungelesen),
            0,
          )

          return (
            <section key={k.id} className="mt-4">
              <button
                type="button"
                onClick={() => aufEinklappen(k.id)}
                aria-expanded={!zu}
                title={zu ? t('ordner.postfach_ausklappen') : t('ordner.postfach_einklappen')}
                className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors duration-[var(--dur-fast)] hover:bg-surface-3"
              >
                {zu ? (
                  <ChevronRight className="size-3.5 shrink-0 text-fg-4" />
                ) : (
                  <ChevronDown className="size-3.5 shrink-0 text-fg-4" />
                )}
                <span aria-hidden className={`size-2 shrink-0 rounded-full ${PUNKT_KLASSE[k.farbe]}`} />
                <span className="min-w-0 flex-1 truncate text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
                  {k.anzeigename}
                </span>
                {/* Zugeklappt zeigt der Kopf, was darunter liegt. */}
                {zu && ungelesenHier > 0 && (
                  <span className="shrink-0 text-[11px] font-semibold tabular-nums text-fg-3">
                    {ungelesenHier}
                  </span>
                )}
              </button>

              {!zu &&
                meine.map(({ ordner: o, tiefe }) => (
                  <Zeile
                    key={o.id}
                    tiefe={tiefe}
                    symbol={SYMBOL[o.rolle]}
                    name={anzeigename(o, t)}
                    ungelesen={o.ungelesen}
                    wartend={o.pfad === WIEDERVORLAGE_PFAD ? (wiedervorlageZahlen[o.kontoId] ?? 0) : 0}
                    stern={favoriten.includes(o.id)}
                    aktiv={ziel.typ === 'ordner' && ziel.id === o.id}
                    onContextMenu={(e) => aufKontext(e, o)}
                    onClick={() => aufZiel({ typ: 'ordner', id: o.id })}
                    ablegbar={Boolean(aufAblegen)}
                    abweisung={abweisungFuer(o)}
                    ueber={ueber === o.id}
                    aufUeber={(an) => setUeber(an ? o.id : null)}
                    aufAblegen={(ids) => aufAblegen?.(o.id, ids)}
                    aufAbweisungZeile={aufAbweisung}
                  />
                ))}
            </section>
          )
        })}
      </div>

      <div className="shrink-0 border-t border-line-subtle p-2">
        <button
          type="button"
          onClick={aufPostfachHinzufuegen}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-3 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1"
        >
          <Plus className="size-4 shrink-0" />
          {t('ordner.postfach_hinzufuegen')}
        </button>
      </div>
    </div>
  )
}

interface ZeileProps {
  symbol: ReactNode
  name: string
  ungelesen: number
  /** Wartende Wiedervorlage-Eintraege dieses Kontos — nur an der Zeile des
   *  Wiedervorlage-Ordners gesetzt, 0 blendet die Marke aus. */
  wartend?: number
  aktiv: boolean
  onClick: () => void
  onContextMenu?: (e: React.MouseEvent) => void
  /** Postfach-Punkt — nur bei Favoriten, wo die Herkunft sonst fehlt. */
  punkt?: 1 | 2 | 3 | 4 | 5 | 6
  /** Kleiner Stern im Baum, wenn der Ordner oben angeheftet ist. */
  stern?: boolean
  /** Wie tief im Baum — 0 ist die oberste Ebene. */
  tiefe?: number
  /** Nimmt dieser Ordner gezogene Nachrichten an? */
  ablegbar?: boolean
  /** ⚠️ Gesetzt heißt: Der Ordner nimmt den Zug **nicht** an, und warum. */
  abweisung?: string
  ueber?: boolean
  aufUeber?: (an: boolean) => void
  aufAblegen?: (ids: string[]) => void
  aufAbweisungZeile?: (grund: string) => void
}

/* ⚠️ **Ein Unterordner gehört unter seinen Ordner, nicht ans Ende der Liste.**
 *
 * Vorher war die Spalte flach: sortiert nach Rolle, dann nach Namen. Ein
 * `INBOX/Rechnungen` bekam die Rolle „eigen" und landete damit ganz unten —
 * weit weg von dem Ordner, in dem er liegt. Das sah aus wie ein
 * Darstellungsfehler und war eine fehlende Funktion.
 *
 * Der Ebenentrenner ist je Server verschieden (`/` bei Gmail, `.` bei
 * All-Inkl). Er wird deshalb **nicht geraten**, sondern aus den Pfaden
 * abgelesen: Ein Ordner ist Kind eines anderen, wenn sein Pfad mit dessen
 * Pfad plus **einem** Trennzeichen beginnt.
 */
interface Knoten {
  ordner: Ordner
  tiefe: number
}

function baumBilden(liste: Ordner[]): Knoten[] {
  const nachPfad = new Map(liste.map((o) => [o.pfad, o]))

  /** Der nächstliegende Vorfahre, der wirklich existiert. */
  function elternVon(o: Ordner): Ordner | undefined {
    let laengster: Ordner | undefined
    for (const anderer of liste) {
      if (anderer.pfad === o.pfad) continue
      if (!o.pfad.startsWith(anderer.pfad)) continue
      const rest = o.pfad.slice(anderer.pfad.length)
      // Genau ein Trennzeichen, dann der eigene Name - sonst ist es nur ein
      // zufällig gleicher Wortanfang („Archiv" und „Archivalien").
      if (rest.length < 2) continue
      const trenner = rest[0]
      if (/[a-z0-9äöüß]/i.test(trenner)) continue
      if (!laengster || anderer.pfad.length > laengster.pfad.length) laengster = anderer
    }
    return laengster
  }

  const kinder = new Map<string, Ordner[]>()
  const wurzeln: Ordner[] = []
  for (const o of liste) {
    const eltern = elternVon(o)
    if (eltern) {
      const bisher = kinder.get(eltern.pfad) ?? []
      bisher.push(o)
      kinder.set(eltern.pfad, bisher)
    } else {
      wurzeln.push(o)
    }
  }

  const sortieren = (a: Ordner, b: Ordner) =>
    RANG[a.rolle] - RANG[b.rolle] || a.name.localeCompare(b.name)

  const ergebnis: Knoten[] = []
  function hinzu(o: Ordner, tiefe: number) {
    ergebnis.push({ ordner: o, tiefe })
    for (const kind of (kinder.get(o.pfad) ?? []).slice().sort(sortieren)) {
      // ⚠️ Nicht tiefer als drei Ebenen einrücken: Danach bleibt in einer
      // 220 px breiten Spalte kein Platz mehr für den Namen.
      hinzu(kind, Math.min(tiefe + 1, 3))
    }
  }
  for (const o of wurzeln.slice().sort(sortieren)) hinzu(o, 0)

  // Was durch einen Zirkel verlorenging, kommt hinten dran - lieber
  // unsortiert sichtbar als still verschwunden.
  if (ergebnis.length !== liste.length) {
    const drin = new Set(ergebnis.map((k) => k.ordner.id))
    for (const o of liste) if (!drin.has(o.id)) ergebnis.push({ ordner: o, tiefe: 0 })
  }
  void nachPfad
  return ergebnis
}


function Zeile({
  symbol,
  name,
  ungelesen,
  wartend = 0,
  aktiv,
  onClick,
  onContextMenu,
  punkt,
  stern,
  tiefe = 0,
  ablegbar = false,
  abweisung = '',
  ueber = false,
  aufUeber,
  aufAblegen,
  aufAbweisungZeile,
}: ZeileProps) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onClick}
      onContextMenu={onContextMenu}
      onDragOver={
        ablegbar
          ? (e) => {
              // ⚠️ **``preventDefault`` ist hier keine Formsache.** Ohne das
              // lehnt der Browser das Ablegen ab, und der Ordner wirkt tot.
              e.preventDefault()
              // ⚠️ **Ein Ordner, der nicht darf, sagt warum.** Vorher nahm er
              // den Zug einfach nicht an — für den Betreiber sah das aus wie
              // ein hakendes Ziehen, nicht wie eine Regel.
              e.dataTransfer.dropEffect = abweisung ? 'none' : 'move'
              if (!ueber) aufUeber?.(true)
            }
          : undefined
      }
      onDragLeave={ablegbar ? () => aufUeber?.(false) : undefined}
      onDrop={
        ablegbar
          ? (e) => {
              e.preventDefault()
              aufUeber?.(false)
              if (abweisung) {
                aufAbweisungZeile?.(abweisung)
                return
              }
              try {
                const ids = JSON.parse(e.dataTransfer.getData('text/nexmail-nachrichten') || '[]')
                if (Array.isArray(ids) && ids.length > 0) aufAblegen?.(ids)
              } catch {
                // Was hier ankommt und kein nexmail-Paket ist, geht uns nichts
                // an - eine Datei vom Schreibtisch etwa.
              }
            }
          : undefined
      }
      aria-current={aktiv ? 'true' : undefined}
      // Einrücken über Polster, nicht über einen Rand: So bleibt die ganze
      // Zeile anklickbar und als Ablageziel erreichbar.
      style={tiefe > 0 ? { paddingLeft: 8 + tiefe * 14 } : undefined}
      className={
        'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] ' +
        'transition-colors duration-[var(--dur-fast)] [&>svg]:size-4 [&>svg]:shrink-0 ' +
        (ueber && abweisung
          ? 'bg-danger-soft ring-1 ring-danger ring-inset text-danger cursor-not-allowed'
          : ueber
          ? 'bg-accent-soft ring-1 ring-accent-line ring-inset text-accent-text'
          : aktiv
            ? 'bg-accent-soft font-medium text-accent-text'
            : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')
      }
    >
      {punkt && <span aria-hidden className={`size-2 shrink-0 rounded-full ${PUNKT_KLASSE[punkt]}`} />}
      {symbol}
      <span className="min-w-0 flex-1 truncate">{name}</span>
      {stern && <Star className="size-3 shrink-0 fill-current text-warning opacity-70" />}
      {/* Wartende Wiedervorlagen dieses Kontos. Die Uhr sagt, dass es keine
          Ungelesen-Zahl ist — und der vorlesbare Name sagt es Vorlesehilfen. */}
      {wartend > 0 && (
        <span
          role="img"
          aria-label={t('wiedervorlage.wartend', { count: wartend })}
          title={t('wiedervorlage.wartend', { count: wartend })}
          className="flex shrink-0 items-center gap-0.5 text-[11px] font-semibold tabular-nums text-fg-3"
        >
          <Clock aria-hidden className="size-3" />
          {wartend}
        </span>
      )}
      {ungelesen > 0 && (
        <span className="shrink-0 text-[11px] font-semibold tabular-nums text-fg-3">{ungelesen}</span>
      )}
    </button>
  )
}
