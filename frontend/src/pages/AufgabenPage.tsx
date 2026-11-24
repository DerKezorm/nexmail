/* Aufgaben — Mails, die noch etwas von einem wollen.
 *
 * ⚠️ **Eine Aufgabe zeigt auf ihre Mail, sie kopiert sie nicht.** Ein Klick
 * öffnet die Mail; das Abhaken lässt sie, wo sie ist. nexmail wird kein
 * Aufgabenverwalter — es merkt sich nur, was noch offen ist.
 *
 * ⚠️ **Und sie überlebt ihre Mail.** Wer im Papierkorb aufräumt, soll nicht
 * lautlos seine Liste mitlöschen. Eine verwaiste Aufgabe steht weiter da, sagt
 * es und trägt trotzdem noch Betreff und Absender — sonst weiß niemand mehr,
 * worum es ging.
 *
 * ⚠️ **Mit nextasks liest die Ansicht live** (MAIL-2, seit 24.11.2026): Die
 * Listen von nextasks stehen in der Seitenleiste, ihre Aufgaben kommen bei
 * jedem Blick frisch von dort und lassen sich hier abhaken, ändern, anlegen.
 * Die Zeilen der Aufgaben, die aus Mails nach nextasks gingen, stehen dann
 * nicht doppelt da; sie kommen live mit ihrer Mail. Ist nextasks nicht
 * erreichbar, bleibt deren letzter Stand stehen (EC-1). Ohne nextasks ist die
 * Ansicht genau wie vorher (AC-13).
 *
 * ⚠️ **Eine Aufgabe in einer Todo-App gehört dieser App.** Sie steht hier
 * trotzdem, mit ihrer Liste und einem Link dorthin; Haken und Datum sind der
 * letzte Stand, den der Abgleich geholt hat. Abhaken geht über die App, das
 * Datum ändert man nur dort.
 */
import { Postfachzeichen } from '../components/Postfachzeichen'
import { createElement, useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CalendarClock,
  CalendarDays,
  Check,
  CircleCheck,
  ExternalLink,
  Flag,
  GripVertical,
  Inbox,
  Layers,
  ListChecks,
  ListTodo,
  Mail,
  MailWarning,
  Plus,
  Trash2,
  UserRound,
} from 'lucide-react'
import type { Ansichtsrahmen } from '../components/Ansichtsleiste'
import { api } from '../api/client'
import type { Konto } from '../daten/typen'
import { Button, EmptyState, IconButton } from '../ds'
import { Suchfeld } from '../components/Suchfeld'
import { NextasksAufgabe } from '../components/NextasksAufgabe'
import {
  fernaufgaben,
  fernAendern,
  fernLoeschen,
  nextasksLage,
  nextasksListen,
  type Fernaufgabe,
  type NextasksLage,
  type NtBereich,
  type Sammlung,
} from '../api/nextasks'
import type { ZielStand } from '../lib/aufgabenziele'
import { symbolFuer } from '../lib/nextasksSymbole'
import { FARBTOENE, tonVon } from '../lib/farbtoene'
import { servermeldung } from '../lib/servermeldung'
import { ARTNAME } from '../lib/aufgabenziele'

export interface AufgabenZeile {
  id: number
  nachricht_id: number | null
  konto_id: string
  betreff: string
  von_name: string
  von_adresse: string
  mail_datum: string | null
  erledigt: string | null
  faellig: string | null
  verwaist: boolean
  /** Leer heißt: nexmails eigene Aufgabe. Sonst die Todo-App, `todoist`. */
  fern_art: string
  fern_url: string
  fern_liste: string
  /** In der App gelöscht — die Zeile sagt es, statt zu verschwinden. */
  fern_geloescht: boolean
  /** Nach dem Trennen der Verbindung: nicht mehr abgeglichen. */
  fern_verbunden: boolean
}

/** Was die Liste zeigt (Seitenleiste, oben). `markiert` und `mir` gibt es nur
 *  mit nextasks; nexmails eigene Aufgaben kennen beides nicht. */
type Filter = Sammlung

/** Der Ton einer nextasks-Liste für ihr Symbol: benannte Farben wie in
 *  nextasks, eigene als `#rrggbb` (lesbar gemacht). */
export function listenTon(farbe: string): string {
  // Dieselben Töne wie nextasks (und wie die Postfächer, `lib/farbtoene.ts`).
  return tonVon(farbe.toLowerCase()) ?? FARBTOENE.gray
}

/** Das Symbol einer Liste oder eines Bereichs wie in nextasks (MAIL-2). */
function NtSymbol({ name, ton, klein = false }: { name: string; ton?: string; klein?: boolean }) {
  return createElement(symbolFuer(name), {
    className: `${klein ? 'size-3' : 'size-4'} shrink-0`,
    style: ton ? { color: ton } : undefined,
    'aria-hidden': true,
  })
}

/** Ein Ziel `<verbindung>:<liste>/<abschnitt>` → die nextasks-Liste. */
function listeAusZiel(ziel: string, verbindungId: string): string | null {
  const [v, rest] = ziel.split(':')
  return v === verbindungId && rest ? rest.split('/')[0] : null
}

/** Wo eine Aufgabe liegt: leer heißt nexmails eigene Liste, sonst der Name
 *  der App samt Liste, wie ihn der Server schickt („Todoist › Arbeit“). */
export function ortVon(z: AufgabenZeile): string {
  if (!z.fern_art) return ''
  return z.fern_liste || ARTNAME[z.fern_art] || z.fern_art
}

/** Der heutige Tag als `JJJJ-MM-TT` in der Zeit des Browsers. Fristen tragen
 *  Mitternacht UTC, also zählt nur ihr Datumsteil. */
function heuteText(jetzt = new Date()): string {
  const m = String(jetzt.getMonth() + 1).padStart(2, '0')
  const d = String(jetzt.getDate()).padStart(2, '0')
  return `${jetzt.getFullYear()}-${m}-${d}`
}

export function passt(z: AufgabenZeile, filter: Filter, heute = heuteText()): boolean {
  if (filter === 'erledigt') return Boolean(z.erledigt)
  if (z.erledigt) return false
  if (filter === 'markiert' || filter === 'mir') return false
  if (filter === 'heute') return Boolean(z.faellig && z.faellig.slice(0, 10) <= heute)
  if (filter === 'datum') return Boolean(z.faellig)
  return true
}

interface Props {
  /** Werkzeugleiste und Seitenspalte, von `App` gebaut wie in der Mail. */
  rahmen: Ansichtsrahmen
  konten: Konto[]
  /** Die Mail zu einer Aufgabe öffnen. */
  aufMail: (nachrichtId: number) => void
  /** Nach jeder Änderung, damit die Zahl an der Leiste stimmt. */
  aufAenderung?: () => void
}

export function AufgabenPage({ rahmen, konten, aufMail, aufAenderung }: Props) {
  const { t } = useTranslation()
  const [zeilen, setZeilen] = useState<AufgabenZeile[] | null>(null)
  const [fehler, setFehler] = useState('')
  const [gezogen, setGezogen] = useState<number | null>(null)
  const [ueber, setUeber] = useState<number | null>(null)
  const [filter, setFilter] = useState<Filter>('offen')
  /** `null` heißt: überall; leer heißt: nexmails eigene Liste. */
  const [ort, setOrt] = useState<string | null>(null)
  /* --- nextasks live (MAIL-2) ---------------------------------------- */
  const [lage, setLage] = useState<NextasksLage | null>(null)
  const [bereiche, setBereiche] = useState<NtBereich[]>([])
  const [fern, setFern] = useState<Fernaufgabe[] | null>(null)
  const [fernFehler, setFernFehler] = useState('')
  /** Die gewählte nextasks-Liste; dann zeigt die Ansicht nur sie. */
  const [ntListe, setNtListe] = useState<string | null>(null)
  const [suche, setSuche] = useState('')
  const [standardListe, setStandardListe] = useState<string | null>(null)
  const [geoeffnet, setGeoeffnet] = useState<Fernaufgabe | null>(null)
  const [neuIn, setNeuIn] = useState<{ listeId: string } | null>(null)
  const unterwegs = useRef(new Set<string>())
  const verbunden = Boolean(lage?.verbunden)

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<AufgabenZeile[]>('/api/aufgaben'))
      setFehler('')
    } catch (f) {
      // ⚠️ Ein Fehler darf nicht wie eine leere Liste aussehen — dieselbe
      // Regel wie bei den Postfächern.
      setFehler(servermeldung(f, t('aufgaben.laden_ging_nicht')))
    }
  }, [t])

  useEffect(() => {
    void (async () => {
      await laden()
      /* ⚠️ **Erst zeigen, dann nachsehen.** Die Liste steht sofort mit dem
         letzten Stand da; was die Todo-Apps inzwischen sagen, kommt einen
         Augenblick später. Scheitert das, bleibt der letzte Stand stehen —
         der Grund steht an der Verbindung in den Einstellungen. */
      try {
        await api.senden('/api/aufgaben/abgleichen', {})
        await laden()
        aufAenderung?.()
      } catch {
        /* Der letzte Stand bleibt; siehe oben. */
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laden])

  const lageLaden = useCallback(async () => {
    try {
      const l = await nextasksLage()
      setLage(l)
      if (!l.verbunden) return
      setBereiche(await nextasksListen())
      const stand = await api.holen<ZielStand>('/api/aufgabenziele').catch(() => null)
      setStandardListe(stand ? listeAusZiel(stand.standard, l.verbindung_id) : null)
    } catch {
      setLage(null)
    }
  }, [])

  const fernLaden = useCallback(async () => {
    if (!verbunden) return
    // Eine lokale Ortswahl (eigene Liste, Todoist …) zeigt keine nextasks-Aufgaben.
    if (ntListe === null && ort !== null) {
      setFern([])
      return
    }
    try {
      setFern(await fernaufgaben({ liste: ntListe, sammlung: filter, suche: suche.trim() || undefined }))
      setFernFehler('')
    } catch (f) {
      setFern(null)
      setFernFehler(servermeldung(f, t('nextasks.nicht_erreichbar')))
    }
  }, [verbunden, ntListe, ort, filter, suche, t])

  useEffect(() => {
    void lageLaden()
  }, [lageLaden])

  useEffect(() => {
    const warte = setTimeout(() => void fernLaden(), suche ? 250 : 0)
    return () => clearTimeout(warte)
  }, [fernLaden, suche])

  /* ⚠️ **Neues aus nextasks kommt von selbst** (AC-15): alle 60 s, nur bei
     sichtbarem Reiter, Listen samt Zahlen mit. */
  useEffect(() => {
    if (!verbunden) return
    const takt = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      void fernLaden()
      void nextasksListen().then(setBereiche).catch(() => undefined)
    }, 60_000)
    return () => clearInterval(takt)
  }, [verbunden, fernLaden])

  async function fernMit(id: string, tun: () => Promise<unknown>) {
    // ⚠️ Ein Doppelklick schickt nichts zweimal (EC-10).
    if (unterwegs.current.has(id)) return
    unterwegs.current.add(id)
    try {
      await tun()
      await Promise.all([fernLaden(), laden()])
      void nextasksListen().then(setBereiche).catch(() => undefined)
      aufAenderung?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      unterwegs.current.delete(id)
    }
  }

  async function mit(tun: () => Promise<unknown>) {
    try {
      await tun()
      await laden()
      aufAenderung?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function ablegen(zielId: number) {
    if (zeilen === null || gezogen === null || gezogen === zielId) return
    const ohne = zeilen.filter((z) => z.id !== gezogen)
    const platz = ohne.findIndex((z) => z.id === zielId)
    const neu = [...ohne.slice(0, platz), zeilen.find((z) => z.id === gezogen)!, ...ohne.slice(platz)]
    // ⚠️ Erst hier zeichnen, dann schicken: Eine Reihenfolge, die nach dem
    // Loslassen erst zurückspringt und dann sitzt, fühlt sich kaputt an.
    setZeilen(neu)
    setGezogen(null)
    setUeber(null)
    await mit(() => api.aendern('/api/aufgaben/reihenfolge', { ids: neu.map((z) => z.id) }))
  }

  /* Mit laufendem nextasks stehen dessen Aufgaben live da; die Zeilen der
     Aufgaben, die aus Mails dorthin gingen, wären doppelt. */
  const live = verbunden && fern !== null
  const alle = (zeilen ?? []).filter((z) => !(live && z.fern_art === 'nextasks'))
  const heute = heuteText()
  const gesucht = suche.trim().toLowerCase()
  const trifft = (z: AufgabenZeile) =>
    !gesucht || [z.betreff, z.von_name, z.von_adresse].some((w) => w.toLowerCase().includes(gesucht))
  const amOrt = (z: AufgabenZeile, o: string | null) => o === null || ortVon(z) === o
  const sichtbar = ntListe !== null ? [] : alle.filter((z) => passt(z, filter, heute) && amOrt(z, ort) && trifft(z))
  /* Mit nextasks: beides zusammen, nach Fälligkeit (AC-12); ohne Datum hinten. */
  type Eintrag = { art: 'lokal'; z: AufgabenZeile; tag: string } | { art: 'fern'; f: Fernaufgabe; tag: string }
  const eintraege: Eintrag[] = [
    ...sichtbar.map((z): Eintrag => ({ art: 'lokal', z, tag: z.faellig?.slice(0, 10) ?? '' })),
    ...(fern ?? []).map((f): Eintrag => ({ art: 'fern', f, tag: f.faellig_tag ? `${f.faellig_tag}T${f.faellig_zeit ?? ''}` : '' })),
  ]
  if (verbunden) eintraege.sort((a, b) => (a.tag && b.tag ? a.tag.localeCompare(b.tag) : a.tag ? -1 : b.tag ? 1 : 0))
  const ntListeName = bereiche.flatMap((b) => b.listen).find((l) => l.id === ntListe)
  /* Die Orte in der Reihenfolge, in der sie zuerst vorkommen; nexmails eigene
     Liste immer vorn. Ohne verbundene App bleibt der Block weg. */
  const orte = [...new Set(alle.map(ortVon))].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : 0))
  const zahlAm = (o: string | null) => alle.filter((z) => passt(z, filter, heute) && amOrt(z, o)).length

  const FILTER: ReadonlyArray<{ id: Filter; symbol: React.ReactNode; text: string }> = [
    { id: 'offen', symbol: <ListTodo />, text: t('aufgaben.filter_offen') },
    { id: 'heute', symbol: <CalendarClock />, text: t('aufgaben.filter_heute') },
    { id: 'datum', symbol: <CalendarDays />, text: t('aufgaben.filter_datum') },
    ...(verbunden
      ? [
          { id: 'markiert' as const, symbol: <Flag />, text: t('nextasks.filter_markiert') },
          { id: 'mir' as const, symbol: <UserRound />, text: t('nextasks.filter_mir') },
        ]
      : []),
    { id: 'erledigt', symbol: <CircleCheck />, text: t('aufgaben.filter_erledigt') },
  ]

  const zeilenKlasse = (an: boolean) =>
    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] ' +
    'transition-colors duration-[var(--dur-fast)] [&_svg]:size-4 [&_svg]:shrink-0 ' +
    (an ? 'bg-accent-soft text-accent-text' : 'text-fg-2 hover:bg-surface-3 hover:text-fg-1')

  /* ⚠️ **Die Seitenleiste der Aufgaben** (gemeldet am 23.11.2026, wie die
     Seitenleiste von nextasks): oben, was gezeigt wird (je mit Zahl), darunter,
     wo die Aufgaben liegen. Ohne verbundene Todo-App gibt es nur einen Ort,
     dann fällt der zweite Block weg. Die Zahl am Ort folgt dem Filter. */
  const seitenleiste = (
    <nav aria-label={t('aufgaben.filter_titel')} className="flex flex-col gap-0.5 p-2">
      {FILTER.map((f) => {
        // Mit nextasks wären die Zahlen nur halb (dessen Aufgaben kommen je Blick); dann ohne.
        const zahl = verbunden ? 0 : alle.filter((z) => passt(z, f.id, heute) && amOrt(z, ort)).length
        return (
          <button
            key={f.id}
            type="button"
            aria-current={filter === f.id ? 'page' : undefined}
            onClick={() => {
              setFilter(f.id)
              rahmen.zeigen()
            }}
            className={zeilenKlasse(filter === f.id)}
          >
            {f.symbol}
            <span className="min-w-0 flex-1 truncate">{f.text}</span>
            {zahl > 0 && <span className="text-[11px] tabular-nums text-fg-4">{zahl}</span>}
          </button>
        )
      })}

      {verbunden && (
        <>
          <h2 className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wide text-fg-4 uppercase">
            {t('aufgaben.orte')}
          </h2>
          <button
            type="button"
            aria-current={ort === null && ntListe === null ? 'page' : undefined}
            onClick={() => {
              setOrt(null)
              setNtListe(null)
              rahmen.zeigen()
            }}
            className={zeilenKlasse(ort === null && ntListe === null)}
          >
            <Layers />
            <span className="min-w-0 flex-1 truncate">{t('aufgaben.ort_alle')}</span>
          </button>
          {/* Die Bereiche von nextasks mit ihren Listen (AC-1); ausgeblendete
              stehen am Ende, leiser. */}
          {bereiche.map((b) => (
            <div key={b.id} className={'flex flex-col gap-0.5 ' + (b.ausgeblendet ? 'opacity-60' : '')}>
              <span className="mt-3 mb-0.5 flex items-center gap-2 px-2.5 text-[11px] font-semibold tracking-wide text-fg-3 uppercase">
                <NtSymbol name={b.symbol} klein />
                {b.name}
              </span>
              {b.listen.map((l) => {
                return (
                  <button
                    key={l.id}
                    type="button"
                    aria-current={ntListe === l.id ? 'page' : undefined}
                    onClick={() => {
                      setNtListe(l.id)
                      setOrt(null)
                      rahmen.zeigen()
                    }}
                    className={zeilenKlasse(ntListe === l.id)}
                  >
                    <NtSymbol name={l.symbol} ton={listenTon(l.farbe)} />
                    <span className="min-w-0 flex-1 truncate">{l.name}</span>
                    {l.offen > 0 && <span className="text-[11px] tabular-nums text-fg-4">{l.offen}</span>}
                  </button>
                )
              })}
            </div>
          ))}
          {orte.length > 0 && (
            <span className="mt-2 px-2.5 text-[12px] font-medium text-fg-3">{t('nextasks.weitere_orte')}</span>
          )}
          {orte.map((o) => (
            <button
              key={o || '__nexmail__'}
              type="button"
              aria-current={ort === o && ntListe === null ? 'page' : undefined}
              onClick={() => {
                setOrt(o)
                setNtListe(null)
                rahmen.zeigen()
              }}
              className={zeilenKlasse(ort === o && ntListe === null)}
            >
              {o ? <ExternalLink /> : <Inbox />}
              <span className="min-w-0 flex-1 truncate">{o || t('aufgaben.ort_nexmail')}</span>
              <span className="text-[11px] tabular-nums text-fg-4">{zahlAm(o)}</span>
            </button>
          ))}
        </>
      )}

      {!verbunden && orte.length > 1 && (
        <>
          <h2 className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wide text-fg-4 uppercase">
            {t('aufgaben.orte')}
          </h2>
          <button
            type="button"
            aria-current={ort === null ? 'page' : undefined}
            onClick={() => {
              setOrt(null)
              rahmen.zeigen()
            }}
            className={zeilenKlasse(ort === null)}
          >
            <Layers />
            <span className="min-w-0 flex-1 truncate">{t('aufgaben.ort_alle')}</span>
            <span className="text-[11px] tabular-nums text-fg-4">{zahlAm(null)}</span>
          </button>
          {orte.map((o) => (
            <button
              key={o || '__nexmail__'}
              type="button"
              aria-current={ort === o ? 'page' : undefined}
              onClick={() => {
                setOrt(o)
                rahmen.zeigen()
              }}
              className={zeilenKlasse(ort === o)}
            >
              {o ? <ExternalLink /> : <Inbox />}
              <span className="min-w-0 flex-1 truncate">{o || t('aufgaben.ort_nexmail')}</span>
              <span className="text-[11px] tabular-nums text-fg-4">{zahlAm(o)}</span>
            </button>
          ))}
        </>
      )}
    </nav>
  )

  const filterName = FILTER.find((f) => f.id === filter)?.text ?? t('nav.aufgaben')
  const titel = ntListeName ? `${ntListeName.name} · ${filterName}` : filterName

  function neueAufgabe() {
    const beschreibbar = bereiche.flatMap((b) => b.listen).filter((l) => l.beschreibbar)
    const wahl =
      [ntListe, standardListe].find((id) => id && beschreibbar.some((l) => l.id === id)) ?? beschreibbar[0]?.id
    if (wahl) setNeuIn({ listeId: wahl })
  }

  /* Eine nextasks-Aufgabe als Zeile: Haken, Titel, darunter Liste, Frist,
     Priorität, Zuständige, Teilaufgaben und die Mail, aus der sie kam. */
  const listeVon = (id: string) => bereiche.flatMap((b) => b.listen).find((l) => l.id === id)
  const fernZeile = (f: Fernaufgabe) => {
    const liste = listeVon(f.liste_id)
    const ueberfaellig = Boolean(f.faellig_tag && !f.erledigt && f.faellig_tag < heute)
    const datum = f.faellig_tag
      ? new Date(`${f.faellig_tag}T00:00:00Z`).toLocaleDateString(undefined, { timeZone: 'UTC' })
      : ''
    return (
      <li
        key={`nt-${f.id}`}
        data-nextasks={f.id}
        className={
          'flex items-start gap-3 rounded-lg border border-line bg-surface-1 px-3 py-2.5 ' +
          (f.erledigt ? 'opacity-60' : '')
        }
      >
        <button
          type="button"
          role="checkbox"
          aria-checked={f.erledigt}
          aria-label={f.erledigt ? t('aufgaben.wieder_offen') : t('aufgaben.abhaken')}
          disabled={!f.beschreibbar}
          onClick={() => void fernMit(f.id, () => fernAendern(f.id, { erledigt: !f.erledigt }))}
          className={
            'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border ' +
            'transition-colors duration-[var(--dur-fast)] disabled:opacity-50 ' +
            (f.erledigt ? 'border-accent bg-accent text-on-accent' : 'border-line-strong hover:border-accent')
          }
        >
          {f.erledigt && <Check className="size-3.5" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            {f.prioritaet > 0 && (
              <span className="shrink-0 text-[12px] font-semibold text-danger" aria-label={t(`nextasks.prio_${f.prioritaet}`)}>
                {'!'.repeat(f.prioritaet)}
              </span>
            )}
            <button
              type="button"
              onClick={() => setGeoeffnet(f)}
              className={
                'min-w-0 flex-1 truncate text-left text-[13px] hover:text-accent-text ' +
                (f.erledigt ? 'text-fg-3 line-through' : 'text-fg-1')
              }
            >
              {f.titel}
            </button>
            {f.markiert && <Flag className="size-3.5 shrink-0 text-warning" aria-label={t('nextasks.markiert')} />}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-fg-4">
            {ntListe === null && (
              <span className="flex min-w-0 items-center gap-1">
                {liste && <NtSymbol name={liste.symbol} ton={listenTon(liste.farbe)} klein />}
                <span className="truncate">
                  {f.liste_name}
                  {f.abschnitt_name ? ` › ${f.abschnitt_name}` : ''}
                </span>
              </span>
            )}
            {datum && (
              <span className={ueberfaellig ? 'text-danger' : ''}>
                {datum}
                {f.faellig_zeit ? ` ${f.faellig_zeit}` : ''}
              </span>
            )}
            {f.teilaufgaben.gesamt > 0 && (
              <span>{t('nextasks.teile', { offen: f.teilaufgaben.gesamt - f.teilaufgaben.offen, gesamt: f.teilaufgaben.gesamt })}</span>
            )}
            {f.zustaendige.length > 0 && (
              <span className="flex items-center gap-1">
                <UserRound className="size-3" aria-hidden />
                {f.zustaendige.map((p) => p.name || t('nextasks.ehemalig')).join(', ')}
              </span>
            )}
            {f.mail && (
              <button
                type="button"
                disabled={f.mail.nachricht_id === null}
                onClick={() => f.mail?.nachricht_id != null && aufMail(f.mail.nachricht_id)}
                className="flex min-w-0 items-center gap-1 hover:text-accent-text disabled:cursor-default"
                title={t('nextasks.zur_mail')}
              >
                {f.mail.verwaist ? <MailWarning className="size-3 text-warning" /> : <Mail className="size-3" />}
                <span className="truncate">{f.mail.von_name || f.mail.von_adresse}</span>
                {f.mail.verwaist && <span className="text-warning">{t('aufgaben.mail_weg')}</span>}
              </button>
            )}
            {f.link && (
              <a
                href={f.link}
                target="_blank"
                rel="noreferrer noopener"
                aria-label={t('nextasks.in_nextasks_oeffnen')}
                title={t('nextasks.in_nextasks_oeffnen')}
                className="text-fg-4 hover:text-accent-text"
              >
                <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
          </div>
        </div>
        {f.beschreibbar && (
          <IconButton
            icon={<Trash2 />}
            label={t('nextasks.in_papierkorb')}
            onClick={() => void fernMit(f.id, () => fernLoeschen(f.id))}
          />
        )}
      </li>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-canvas">
      {rahmen.kopf(
        verbunden
          ? {
              haupt: rahmen.schmal ? (
                <IconButton icon={<Plus />} label={t('nextasks.neue_aufgabe')} variant="outline" onClick={neueAufgabe} />
              ) : (
                <Button variant="primary" iconLeft={<Plus className="size-4" />} onClick={neueAufgabe}>
                  {t('nextasks.neue_aufgabe')}
                </Button>
              ),
              suche: (
                <Suchfeld
                  wert={suche}
                  aufWert={setSuche}
                  platzhalter={t('nextasks.suchen')}
                  tasten
                  ohneKuerzel={rahmen.schmal}
                  className="w-full"
                />
              ),
            }
          : {},
      )}
    <div className="flex min-h-0 flex-1">
      {rahmen.spalte(seitenleiste)}
    {rahmen.ersatz ? (
      <div className="flex min-w-0 flex-1 flex-col">{rahmen.ersatz}</div>
    ) : (
    <div className="min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-[720px] flex-col gap-4 px-6 py-6">
        {/* Schmal gibt es keine Seitenspalte; die Filter stehen dann hier. */}
        {rahmen.schmal && (
          <div className="flex flex-wrap gap-1.5">
            {FILTER.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={
                  'rounded-pill border px-3 py-1 text-[12px] ' +
                  (filter === f.id ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-fg-3')
                }
              >
                {f.text}
              </button>
            ))}
            {verbunden &&
              bereiche.flatMap((b) => b.listen).map((l) => (
                <button
                  key={l.id}
                  type="button"
                  aria-pressed={ntListe === l.id}
                  onClick={() => {
                    setNtListe(ntListe === l.id ? null : l.id)
                    setOrt(null)
                  }}
                  className={
                    'rounded-pill border px-3 py-1 text-[12px] ' +
                    (ntListe === l.id ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-fg-3')
                  }
                >
                  {l.name}
                </button>
              ))}
          </div>
        )}
        <div className="flex items-baseline gap-3">
          <h1 className="mb-0 font-display text-[20px] font-medium text-fg-1">
            {titel}
          </h1>
          <span className="text-[12px] text-fg-4">
            {filter === 'erledigt'
              ? t('aufgaben.erledigt_zahl', { count: eintraege.length })
              : t('aufgaben.offen', { count: eintraege.length })}
          </span>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 rounded-md border border-danger bg-danger-soft px-3 py-2 text-[13px] text-fg-1">
            {fehler}
          </p>
        )}

        {/* ⚠️ nextasks nicht erreichbar: leiser Hinweis, die eigenen
            Aufgaben stehen trotzdem da (EC-1). */}
        {verbunden && fernFehler && (
          <p className="mb-0 rounded-md border border-line bg-surface-2 px-3 py-2 text-[12px] text-fg-3">
            {fernFehler}
          </p>
        )}

        {zeilen !== null && eintraege.length === 0 && !fehler && (
          <EmptyState
            icon={<ListChecks />}
            title={alle.length === 0 ? t('aufgaben.leer_titel') : t('aufgaben.filter_leer')}
            description={alle.length === 0 ? t('aufgaben.leer_text') : undefined}
          />
        )}

        <ul className="flex list-none flex-col gap-1.5 p-0">
          {eintraege.map((e) => e.art === 'fern' ? fernZeile(e.f) : ((z: AufgabenZeile) => {
            const farbe = konten.find((k) => k.id === z.konto_id)
            const faellig = z.faellig ? new Date(z.faellig) : null
            const ueberfaellig = Boolean(faellig && !z.erledigt && faellig < new Date())
            const inApp = Boolean(z.fern_art && z.fern_verbunden && !z.fern_geloescht)

            return (
              <li
                key={z.id}
                draggable={!z.erledigt && !verbunden}
                onDragStart={() => setGezogen(z.id)}
                onDragEnd={() => {
                  setGezogen(null)
                  setUeber(null)
                }}
                onDragOver={(e) => {
                  e.preventDefault()
                  setUeber(z.id)
                }}
                onDrop={() => void ablegen(z.id)}
                className={
                  'flex items-start gap-3 rounded-lg border bg-surface-1 px-3 py-2.5 ' +
                  'transition-colors duration-[var(--dur-fast)] ' +
                  (ueber === z.id ? 'border-accent ' : 'border-line ') +
                  (z.erledigt ? 'opacity-60 ' : '')
                }
              >
                {/* ⚠️ Der Griff ist sichtbar, nicht geraten. Eine Zeile, die
                    sich ziehen lässt und das nicht zeigt, zieht niemand. */}
                <span
                  aria-hidden
                  className={
                    'mt-1 shrink-0 ' + (z.erledigt || verbunden ? 'text-transparent' : 'cursor-grab text-fg-4')
                  }
                >
                  <GripVertical className="size-4" />
                </span>

                <button
                  type="button"
                  role="checkbox"
                  aria-checked={Boolean(z.erledigt)}
                  aria-label={
                    z.erledigt ? t('aufgaben.wieder_offen') : t('aufgaben.abhaken')
                  }
                  onClick={() =>
                    void mit(() =>
                      api.flicken(`/api/aufgaben/${z.id}`, { erledigt: !z.erledigt }),
                    )
                  }
                  className={
                    'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border ' +
                    'transition-colors duration-[var(--dur-fast)] ' +
                    (z.erledigt
                      ? 'border-accent bg-accent text-on-accent'
                      : 'border-line-strong hover:border-accent')
                  }
                >
                  {z.erledigt && <Check className="size-3.5" />}
                </button>

                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    {farbe && <Postfachzeichen konto={farbe} />}
                    <button
                      type="button"
                      disabled={z.nachricht_id === null}
                      onClick={() => z.nachricht_id !== null && aufMail(z.nachricht_id)}
                      className={
                        'min-w-0 flex-1 truncate text-left text-[13px] ' +
                        (z.erledigt ? 'text-fg-3 line-through ' : 'text-fg-1 ') +
                        (z.nachricht_id === null ? 'cursor-default' : 'hover:text-accent-text')
                      }
                    >
                      {z.betreff || t('liste.kein_betreff')}
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 pl-4 text-[11px] text-fg-4">
                    <span className="truncate">{z.von_name || z.von_adresse}</span>

                    {/* ⚠️ Die verwaiste Aufgabe sagt es. Sonst klickt man ins
                        Leere und hält nexmail für kaputt. */}
                    {z.verwaist && (
                      <span className="flex items-center gap-1 text-warning">
                        <MailWarning className="size-3" />
                        {t('aufgaben.mail_weg')}
                      </span>
                    )}

                    {z.fern_art && (
                      <span className="flex items-center gap-1">
                        {z.fern_liste || ARTNAME[z.fern_art] || z.fern_art}
                        {/* Eine in der App gelöschte Aufgabe hat dort keine
                            Seite mehr; der Link führte ins Leere. */}
                        {z.fern_url && !z.fern_geloescht && (
                          <a
                            href={z.fern_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            aria-label={t('aufgaben.in_app_oeffnen')}
                            title={t('aufgaben.in_app_oeffnen')}
                            className="text-fg-4 hover:text-accent-text"
                          >
                            <ExternalLink className="size-3" aria-hidden />
                          </a>
                        )}
                      </span>
                    )}

                    {z.fern_geloescht && (
                      <span className="flex items-center gap-1 text-warning">
                        <MailWarning className="size-3" />
                        {t('aufgaben.in_app_geloescht')}
                      </span>
                    )}

                    {/* ⚠️ **Das Datum einer App-Aufgabe nur lesen.** Geändert
                        wird es in der App; hier wäre es beim nächsten
                        Abgleich still wieder überschrieben. */}
                    {inApp ? (
                      faellig && (
                        <span className={ueberfaellig ? 'text-danger' : ''}>
                          {faellig.toLocaleDateString(undefined, { timeZone: 'UTC' })}
                        </span>
                      )
                    ) : (
                    <>
                    {/* ⚠️ **Ohne Datum bleibt hier nur das Kalendersymbol.**
                        Ein leeres `<input type="date">` malt „tt.mm.jjjj" hin,
                        und das stünde bei den meisten Aufgaben — die haben
                        keine Frist. Die schmale Breite schneidet den
                        Platzhalter weg; der eingebaute Kalenderknopf bleibt
                        anklickbar. Ein zweites Symbol daneben wäre eins zu
                        viel: Der Browser bringt seines mit. */}
                    <label
                      className="flex items-center"
                      title={t('aufgaben.faellig')}
                    >
                      <span className="sr-only">{t('aufgaben.faellig')}</span>
                      <input
                        type="date"
                        aria-label={t('aufgaben.faellig')}
                        value={faellig ? faellig.toISOString().slice(0, 10) : ''}
                        onChange={(e) =>
                          void mit(() =>
                            api.flicken(`/api/aufgaben/${z.id}`, {
                              faellig: e.target.value ? `${e.target.value}T00:00:00Z` : null,
                              faellig_setzen: true,
                            }),
                          )
                        }
                        className={
                          'rounded-sm border border-transparent bg-transparent py-0.5 ' +
                          'text-[11px] hover:border-line ' +
                          (faellig ? 'w-[6.5rem] px-1 ' : 'w-[1.4rem] px-0 ') +
                          (ueberfaellig ? 'text-danger' : 'text-fg-4')
                        }
                      />
                    </label>
                    </>
                    )}

                    {/* ⚠️ **Das Eingangsdatum der Mail steht hier nicht.**
                        Zwei unbeschriftete Daten nebeneinander liest niemand
                        richtig — man hält das eine für das andere. Hier zählt
                        die Frist; wann die Mail kam, steht in der Mail, und
                        die ist einen Klick entfernt. */}
                  </div>
                </div>

                <IconButton
                  icon={<Trash2 />}
                  label={z.fern_art ? t('aufgaben.entfernen_nur_hier') : t('aufgaben.entfernen')}
                  onClick={() => void mit(() => api.loeschen(`/api/aufgaben/${z.id}`))}
                />
              </li>
            )
          })(e.z))}
        </ul>
      </div>
    </div>
    )}
    </div>
      <NextasksAufgabe
        aufgabe={geoeffnet}
        neu={neuIn}
        bereiche={bereiche}
        mitgliederAn={Boolean(lage?.mitglieder)}
        aufZu={() => {
          setGeoeffnet(null)
          setNeuIn(null)
        }}
        aufGespeichert={() => {
          void fernLaden()
          void laden()
          void nextasksListen().then(setBereiche).catch(() => undefined)
          aufAenderung?.()
        }}
        aufMail={aufMail}
      />
    </div>
  )
}
