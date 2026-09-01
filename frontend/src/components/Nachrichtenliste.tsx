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
import { ChevronDown, ChevronRight, Flag, MessagesSquare, Paperclip } from 'lucide-react'
import type { Datumsgruppe } from '../lib/format'
import { anzeigename, gruppeVon, kurzesDatum } from '../lib/format'
import { PUNKT_KLASSE } from '../lib/farben'
import type { Konto, Nachricht } from '../daten/typen'
import { EmptyState } from '../ds'
import { Inbox } from 'lucide-react'

const GRUPPEN: Datumsgruppe[] = ['heute', 'gestern', 'diese_woche', 'aelter']

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
  aufMehr,
  mehrLaedt = false,
  amEnde = false,
  gruppiert,
  aufGruppiert,
  aufStrang,
}: Props) {
  /* Welche Stränge offen sind, samt ihrer Nachrichten.
     ⚠️ **Aufgeklappt bleibt aufgeklappt, bis man wieder klickt.** Ein Strang,
     der sich beim nächsten Nachladen von selbst schließt, verliert genau die
     Nachricht, die man gerade gesucht hat. */
  const [offeneStraenge, setOffeneStraenge] = useState<Record<string, Nachricht[]>>({})
  const { t, i18n } = useTranslation()
  const ungelesen = nachrichten.filter((n) => !n.gelesen).length

  return (
    <div className="flex h-full min-h-0 flex-col border-r border-line-subtle bg-surface-1">
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-line-subtle px-3">
        <h2 className="truncate font-display text-[15px] font-medium text-fg-1">{titel}</h2>
        <span className="shrink-0 text-[11px] tabular-nums text-fg-4">
          {nachrichten.length === 1
            ? t('liste.anzahl_eine')
            : t('liste.anzahl_viele', { count: nachrichten.length })}
          {ungelesen > 0 && ` · ${t('liste.ungelesen', { count: ungelesen })}`}
        </span>
      
        {/* ⚠️ **Der Umschalter gehört über die Liste, nicht in ein Menü.**
            „Wo sind meine Mails hin?" ist die Frage, die ein versteckter
            Filter erzeugt. Sichtbar über der Liste beantwortet er sie, bevor
            sie entsteht. */}
        {filter !== undefined && aufFilter && filter !== 'markiert' && (
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

        {/* ⚠️ **Vorgabe aus, bis man ihr traut.** Falsch gruppiert steckt
            eine Mail in einem zugeklappten Strang, und man merkt es erst,
            wenn man sie sucht. Deshalb ein Umschalter und kein Zwang. */}
        {gruppiert !== undefined && aufGruppiert && (
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

interface ZeileProps {
  n: Nachricht
  farbe?: 1 | 2 | 3 | 4 | 5 | 6
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
  /** Gesetzt heißt: Diese Zeile ist der Kopf eines Gesprächs. */
  strangAnzahl?: number
  strangOffen?: boolean
  aufStrangKlappen?: () => void
  strangText?: string
}

function Zeile({
  strangAnzahl,
  strangOffen = false,
  aufStrangKlappen,
  strangText,
  n,
  farbe,
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
}: ZeileProps) {
  return (
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
      onClick={(e) => onClick(e.ctrlKey || e.metaKey, e.shiftKey)}
      onContextMenu={(e) => {
        // Rechtsklick waehlt die Zeile mit aus - aber nur, wenn sie nicht
        // ohnehin schon zur Mehrfachauswahl gehoert. Sonst wirkt das Menue
        // auf eine Nachricht, waehrend rechts eine andere offen ist, und man
        // loescht die falsche. Umgekehrt darf ein Rechtsklick auf eine
        // ausgewaehlte Zeile die Auswahl nicht wegwerfen.
        if (!mitausgewaehlt) onClick(false, false)
        aufKontext(e, n)
      }}
      aria-current={gewaehlt ? 'true' : undefined}
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
          {n.markiert && <Flag className="size-3 shrink-0 fill-current text-warning" />}
          {n.anhaenge.length > 0 && <Paperclip className="size-3 shrink-0 text-fg-4" />}
          <span className="shrink-0 text-[11px] tabular-nums text-fg-4">
            {kurzesDatum(n.datum, sprache)}
          </span>
        </div>

        <div className={'truncate text-[13px] ' + (n.gelesen ? 'text-fg-2' : 'font-medium text-fg-1')}>
          {n.betreff || keinBetreff}
        </div>

        {anreisserZeigen && (
          <div className="truncate text-[12px] text-fg-4">{n.anreisser}</div>
        )}
      </div>
    </button>
  )
}
