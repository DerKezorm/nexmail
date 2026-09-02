/* Der Lesebereich.
 *
 * ⚠️ **Bereinigt wurde im Server, nicht hier.** Was ankommt, ist bereits durch
 * `nh3` gegangen und hat ausgeklinkte Bilder. Das ist wichtig herum: Ein
 * Browser, der bereinigen soll, hat den gefährlichen Inhalt schon geladen —
 * ein Zählpixel hätte dann längst gemeldet, dass die Mail geöffnet wurde.
 *
 * Die zweite Schicht sitzt trotzdem hier: `<iframe sandbox>` ohne
 * `allow-scripts`. Zwei Verteidigungen, weil eine davon irgendwann eine Lücke
 * hat.
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Archive,
  Check,
  Clock,
  CornerUpLeft,
  CornerUpRight,
  Download,
  Flag,
  ImageOff,
  MailOpen,
  ExternalLink,
  FileDown,
  MoreHorizontal,
  Paperclip,
  PenLine,
  Plus,
  Printer,
  ReplyAll,
  Tag,
  Trash2,
} from 'lucide-react'
import type { Nachricht, Schlagwort } from '../daten/typen'
import type { VolleNachricht } from '../api/laden'
import { absenderVergessen, bilderAnzeigen } from '../api/laden'
import { anzeigename, groesse, initialen, langesDatum } from '../lib/format'
import { Schlagwortmarke } from './Schlagwortmarke'
import { Button, EmptyState, IconButton } from '../ds'
import { Kontextmenue } from './Kontextmenue'
import type { MenueEintrag } from './Kontextmenue'
import { appPfad } from '../lib/basis'
import { nachrichtDrucken } from '../lib/drucken'

interface Props {
  nachricht: VolleNachricht | null
  laedt?: boolean
  aufVerfassen: (art: 'antwort' | 'allen' | 'weiter' | 'anhang' | 'entwurf', n: Nachricht) => void
  /** Liegt die Nachricht im Entwurfsordner? Dann ist sie zum Weiterschreiben da. */
  istEntwurf?: boolean
  /** Dieses Lesefenster IST schon das eigene Fenster - der Knopf dafuer
   *  entfaellt dann. Ein Fenster, das sich selbst noch einmal oeffnet,
   *  ergibt keinen Sinn - aufgefallen am 02.09.2026. */
  imEigenenFenster?: boolean
  /** Die Schlagwort-Definitionen — fuer die Marken im Kopf und das
   *  Untermenue unter „Weitere Aktionen". */
  schlagworte?: Schlagwort[]
  /** Ein Schlagwort an dieser Mail umschalten. Fehlt der Rueckruf (eigenes
   *  Fenster), gibt es das Untermenue nicht. */
  aufSchlagwort?: (n: Nachricht, atom: string, setzen: boolean) => void
  /** „Neues Schlagwort…" — fragt nach dem Namen und setzt es gleich. */
  aufNeuesSchlagwort?: (n: Nachricht) => void
  /** Das Untermenü „Wiedervorlage" — dieselben Einträge wie im Kontextmenü
   *  der Liste, aus derselben Quelle in `App` gebaut. Fehlt der Rückruf
   *  (eigenes Fenster), gibt es den Eintrag nicht. */
  wiedervorlageMenue?: (n: Nachricht) => MenueEintrag[]
}

export function Lesebereich({
  nachricht,
  laedt = false,
  aufVerfassen,
  istEntwurf = false,
  imEigenenFenster = false,
  schlagworte = [],
  aufSchlagwort,
  aufNeuesSchlagwort,
  wiedervorlageMenue,
}: Props) {
  const { t, i18n } = useTranslation()
  const [freigegeben, setFreigegeben] = useState<string | null>(null)
  /* Die Adresse, die gerade dauerhaft freigegeben wurde — für die
     Bestätigungszeile samt „Rückgängig". `null` heißt: nichts gemerkt. */
  const [gemerkt, setGemerkt] = useState<string | null>(null)
  const [bilderFehler, setBilderFehler] = useState(false)
  // Das Menü hinter „Weitere Aktionen" — dieselbe Kontextmenü-Zutat wie beim
  // Rechtsklick in der Liste, nur unter dem Knopf aufgeklappt.
  const [mehrMenue, setMehrMenue] = useState<{ x: number; y: number } | null>(null)

  // Beim Wechsel der Nachricht sind Bilder wieder geblockt. Alles andere wäre
  // eine Erlaubnis, die man einmal gibt und danach nie wieder sieht.
  useEffect(() => {
    setFreigegeben(null)
    setGemerkt(null)
    setBilderFehler(false)
  }, [nachricht?.id])

  /* ⚠️ **Der Balken bleibt stehen und sagt es, wenn es schiefgeht.** Ein
     geschluckter Fehler und ein Knopf ohne Wirkung sind derselbe Fehler — und
     genau der stand hier drei Fassungen lang. */
  const bilderZeigen = async (merken: boolean) => {
    if (!nachricht) return
    setBilderFehler(false)
    try {
      const html = await bilderAnzeigen(nachricht.id, merken)
      setFreigegeben(html)
      if (merken) setGemerkt(nachricht.von.adresse)
    } catch {
      setBilderFehler(true)
    }
  }

  const inhalt = freigegeben ?? nachricht?.koerper ?? ''
  const seite = useMemo(() => (nachricht ? rahmenInhalt(inhalt) : ''), [nachricht, inhalt])

  if (laedt) {
    return <div className="h-full bg-canvas" />
  }

  if (!nachricht) {
    return (
      <div className="flex h-full items-center justify-center bg-canvas">
        <EmptyState
          icon={<MailOpen />}
          title={t('liste.keine_auswahl_titel')}
          description={t('liste.keine_auswahl_text')}
        />
      </div>
    )
  }

  const anhaenge = nachricht.echteAnhaenge ?? []

  return (
    <article className="flex h-full min-h-0 flex-col bg-canvas">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line-subtle px-2">
        {/* ⚠️ **Auf einen Entwurf antwortet man nicht.** Er ist die eigene,
            halbfertige Nachricht — die einzige sinnvolle Handlung ist
            weiterschreiben. Antworten und Weiterleiten stünden hier nur
            herum und würden Unsinn erzeugen. */}
        {istEntwurf ? (
          <Button
            size="sm"
            variant="primary"
            iconLeft={<PenLine className="size-4" />}
            onClick={() => aufVerfassen('entwurf', nachricht)}
          >
            {t('aktion.weiterschreiben')}
          </Button>
        ) : (
          <>
            <IconButton icon={<CornerUpLeft />} label={t('aktion.antworten')} onClick={() => aufVerfassen('antwort', nachricht)} />
            <IconButton icon={<ReplyAll />} label={t('aktion.allen_antworten')} onClick={() => aufVerfassen('allen', nachricht)} />
            <IconButton icon={<CornerUpRight />} label={t('aktion.weiterleiten')} onClick={() => aufVerfassen('weiter', nachricht)} />
          </>
        )}
        <span aria-hidden className="mx-1 h-5 w-px bg-line" />
        <IconButton icon={<Archive />} label={t('aktion.archivieren')} />
        <IconButton icon={<Trash2 />} label={t('aktion.loeschen')} />
        <IconButton icon={<Flag />} label={t('aktion.markieren')} active={nachricht.markiert} />
        <span className="flex-1" />

        {/* ⚠️ **Beides führt an nexmail vorbei — mit Absicht.**
            Die `.eml` ist die Mail, wie sie ankam: alles drin, nichts
            bereinigt. Genau das braucht man, um sie aufzubewahren oder
            jemandem zu zeigen, der sie prüfen soll. Und das eigene Fenster
            zeigt sie groß — in derselben abgeschotteten Umgebung, nicht
            roher. */}
        <IconButton
          icon={<FileDown />}
          label={t('aktion.herunterladen')}
          onClick={() => {
            window.location.href = appPfad(`/api/nachrichten/${nachricht.id}/roh`)
          }}
        />
        {/* Die Druckseite kommt vom Server: eigenständig, skriptfrei, ohne
            die ausgeklinkten Bildadressen. Der Druckdialog wird von hier
            angestoßen, weil das Dokument selbst nichts ausführen darf. */}
        <IconButton
          icon={<Printer />}
          label={t('aktion.drucken')}
          onClick={() => nachrichtDrucken(nachricht.id, i18n.language)}
        />
        {!imEigenenFenster && (
        <IconButton
          icon={<ExternalLink />}
          label={t('aktion.im_fenster')}
          onClick={() => {
            window.open(
              `${window.location.pathname}?nachricht=${nachricht.id}`,
              '_blank',
              'noopener,width=900,height=800',
            )
          }}
        />
        )}
        {/* „Weitere Aktionen": klappt ein Menü unter dem Knopf auf. Bei einem
            Entwurf gibt es den Knopf nicht — sein einziger Eintrag leitet
            weiter, und auf einen Entwurf antwortet oder leitet man nicht. */}
        {!istEntwurf && (
          <IconButton
            icon={<MoreHorizontal />}
            label={t('aktion.mehr')}
            aria-haspopup="menu"
            aria-expanded={mehrMenue !== null}
            onClick={(e) => {
              const kasten = e.currentTarget.getBoundingClientRect()
              setMehrMenue({ x: kasten.right, y: kasten.bottom + 4 })
            }}
          />
        )}
        {mehrMenue && (
          <Kontextmenue
            x={mehrMenue.x}
            y={mehrMenue.y}
            eintraege={[
              {
                id: 'anhang',
                text: t('aktion.als_anhang'),
                symbol: <Paperclip />,
                tun: () => aufVerfassen('anhang', nachricht),
              },
              // „Wiedervorlage" — dieselben Zeitpunkte wie im Kontextmenü
              // der Liste, aus derselben Quelle gebaut.
              ...(wiedervorlageMenue
                ? [
                    {
                      id: 'wiedervorlage',
                      text: t('wiedervorlage.menue'),
                      symbol: <Clock />,
                      unter: wiedervorlageMenue(nachricht),
                    } satisfies MenueEintrag,
                  ]
                : []),
              // Das Schlagwort-Untermenue — dieselben Eintraege wie im
              // Kontextmenue der Liste: Farbpunkt + Name, Haekchen wenn
              // gesetzt, Klick schaltet um.
              ...(aufSchlagwort
                ? [
                    {
                      id: 'schlagwort',
                      text: t('schlagworte.menue'),
                      symbol: <Tag />,
                      unter: [
                        ...schlagworte.map((s): MenueEintrag => {
                          const gesetzt = (nachricht.schlagworte ?? []).some(
                            (a) => a.toLowerCase() === s.atom.toLowerCase(),
                          )
                          return {
                            id: `schlagwort-${s.id}`,
                            text: s.name,
                            aktiv: gesetzt,
                            symbol: <Schlagwortmarke farbe={s.farbe} />,
                            tun: () => aufSchlagwort(nachricht, s.atom, !gesetzt),
                          }
                        }),
                        ...(aufNeuesSchlagwort
                          ? [
                              {
                                id: 'schlagwort-neu',
                                text: t('schlagworte.neu'),
                                symbol: <Plus />,
                                trennerDavor: schlagworte.length > 0,
                                tun: () => aufNeuesSchlagwort(nachricht),
                              } satisfies MenueEintrag,
                            ]
                          : []),
                      ],
                    } satisfies MenueEintrag,
                  ]
                : []),
            ]}
            aufSchliessen={() => setMehrMenue(null)}
          />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <header className="border-b border-line-subtle px-6 py-4">
          <h1 className="mb-3 font-display text-[20px] leading-snug font-medium text-fg-1">
            {/* ⚠️ Nicht nur Farbe: das Zeichen plus ein vorlesbarer Name. */}
            {nachricht.wichtigkeit === 'hoch' && (
              <span role="img" aria-label={t('lesen.wichtig_hoch')} className="mr-2 font-bold text-danger">
                !
              </span>
            )}
            {nachricht.betreff || t('liste.kein_betreff')}
          </h1>

          {/* Die Schlagworte — hier beschriftet, nicht nur als Punkt: Im
              Lesebereich ist Platz, und der Name IST die Auskunft. */}
          {(nachricht.schlagworte ?? []).length > 0 && (
            <ul className="mb-3 flex list-none flex-wrap gap-1.5 p-0">
              {(nachricht.schlagworte ?? []).map((atom) => {
                const def = schlagworte.find(
                  (s) => s.atom.toLowerCase() === atom.toLowerCase(),
                )
                return (
                  <li
                    key={atom}
                    className="flex items-center gap-1.5 rounded-pill border border-line bg-surface-2 px-2 py-0.5 text-[11px] text-fg-2"
                  >
                    <Schlagwortmarke farbe={def?.farbe ?? 1} />
                    {def?.name ?? atom}
                  </li>
                )
              })}
            </ul>
          )}

          {/* Niedrig ist im Lesebereich ein Satz, kein Zeichen — wer die Mail
              schon offen hat, braucht keinen Alarm, nur die Auskunft. */}
          {nachricht.wichtigkeit === 'niedrig' && (
            <p className="mb-3 text-[12px] text-fg-4">{t('lesen.wichtig_niedrig')}</p>
          )}

          <div className="flex items-start gap-3">
            <span
              aria-hidden
              className="flex size-9 shrink-0 items-center justify-center rounded-pill bg-surface-3 text-[12px] font-semibold text-fg-2"
            >
              {initialen(nachricht.von)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm font-medium text-fg-1">{anzeigename(nachricht.von)}</span>
                <span className="font-mono text-[12px] text-fg-4">&lt;{nachricht.von.adresse}&gt;</span>
              </div>
              {nachricht.an.length > 0 && (
                <div className="mt-0.5 text-[12px] text-fg-3">
                  <span className="text-fg-4">{t('lesen.an')}: </span>
                  {nachricht.an.map(anzeigename).join(', ')}
                  {nachricht.kopie && nachricht.kopie.length > 0 && (
                    <>
                      <span className="text-fg-4"> · {t('lesen.kopie')}: </span>
                      {nachricht.kopie.map(anzeigename).join(', ')}
                    </>
                  )}
                </div>
              )}
            </div>
            <time className="shrink-0 text-[12px] text-fg-4" dateTime={nachricht.datum}>
              {langesDatum(nachricht.datum, i18n.language)}
            </time>
          </div>
        </header>

        {nachricht.geblockteBilder > 0 && freigegeben === null && (
          <div className="mx-6 mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-3">
            <ImageOff className="size-4 shrink-0 text-warning" />
            <p className="mb-0 min-w-[140px] flex-1 text-[13px] text-fg-2">
              {bilderFehler ? t('lesen.bilder_ging_nicht') : t('lesen.bilder_geblockt')}
            </p>
            <Button size="sm" onClick={() => void bilderZeigen(false)}>
              {t('lesen.bilder_anzeigen')}
            </Button>
            {/* ⚠️ **Nur, wenn der Absender noch nicht freigegeben ist.** Sonst
                stünde hier ein Knopf, der nichts ändert — und der Balken
                erscheint bei einem freigegebenen Absender ohnehin nicht. */}
            {!nachricht.absenderFreigegeben && (
              <Button size="sm" variant="ghost" onClick={() => void bilderZeigen(true)}>
                {t('lesen.bilder_immer')}
              </Button>
            )}
          </div>
        )}

        {/* ⚠️ **Eine Handlung, die man nicht sieht, gibt es nicht.** „Immer
            laden" ändert etwas Dauerhaftes an einem Ort, den man sonst nur in
            den Einstellungen wiederfindet — also sagt es die Anwendung hier,
            und der Fehlklick ist im selben Atemzug zurückzunehmen. */}
        {gemerkt && (
          <div className="mx-6 mt-4 flex flex-wrap items-center gap-2">
            <Check className="size-4 shrink-0 text-success" />
            <p className="mb-0 min-w-[140px] flex-1 text-[12px] text-fg-4">
              {t('lesen.bilder_immer_gemerkt', { adresse: gemerkt })}
            </p>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                const adresse = gemerkt
                setGemerkt(null)
                void absenderVergessen(adresse).catch(() => setGemerkt(adresse))
              }}
            >
              {t('aktion.rueckgaengig')}
            </Button>
          </div>
        )}

        {/* sandbox ohne allow-scripts: Der Rahmen darf nichts ausführen,
            nichts an die App weitergeben und kein Formular abschicken. */}
        <iframe
          title={nachricht.betreff}
          sandbox=""
          srcDoc={seite}
          className="min-h-[420px] w-full border-0 bg-transparent px-2"
        />

        {anhaenge.length > 0 && (
          <div className="border-t border-line-subtle px-6 py-4">
            <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
              <Paperclip className="size-3.5" />
              {anhaenge.length === 1
                ? t('lesen.anhaenge_eine')
                : t('lesen.anhaenge_viele', { count: anhaenge.length })}
            </div>
            <ul className="flex list-none flex-wrap gap-2 p-0">
              {anhaenge.map((a) => (
                <li key={a.id}>
                  {/* Immer als Download, nie zur Anzeige: Ein HTML-Anhang, den
                      der Browser rendert, liefe unter nexmails eigener
                      Herkunft — also an der ganzen Bereinigung vorbei. */}
                  <a
                    href={`/api/nachrichten/${nachricht.id}/anhang/${a.id}`}
                    download={a.dateiname}
                    className="flex items-center gap-2 rounded-md border border-line bg-surface-1 px-3 py-2 text-left transition-colors duration-[var(--dur-fast)] hover:border-line-strong hover:bg-surface-3"
                  >
                    <Download className="size-4 shrink-0 text-fg-4" />
                    <span className="min-w-0">
                      <span className="block max-w-[22ch] truncate text-[13px] text-fg-1">
                        {a.dateiname}
                      </span>
                      <span className="block text-[11px] tabular-nums text-fg-4">
                        {groesse(a.groesse, i18n.language)}
                      </span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </article>
  )
}

/* Die Seite im Rahmen.
 *
 * Nur noch das Stylesheet — das Ausklinken der Bilder hat der Server erledigt.
 * Die vier Farbwerte werden hereingereicht, weil der Rahmen keine Variablen
 * des Elternfensters sieht.
 */
function rahmenInhalt(koerper: string): string {
  const stil = `
    :root { color-scheme: light dark; }
    body {
      margin: 0; padding: 16px 24px;
      font: 400 14px/1.6 var(--nm-sans);
      color: var(--nm-text); background: transparent;
      overflow-wrap: break-word;
    }
    p { margin: 0 0 12px; }
    a { color: var(--nm-accent); }
    b, strong { color: var(--nm-strong); }
    code, pre { font-family: var(--nm-mono); font-size: .92em; }
    pre { white-space: pre-wrap; }
    img { max-width: 100%; height: auto; }
    img:not([src]) { display: none; }
    table { max-width: 100%; }
  `

  const wurzel = getComputedStyle(document.documentElement)
  const vars = [
    `--nm-sans:${wurzel.getPropertyValue('--font-sans')}`,
    `--nm-mono:${wurzel.getPropertyValue('--font-mono')}`,
    `--nm-text:${wurzel.getPropertyValue('--text-2')}`,
    `--nm-strong:${wurzel.getPropertyValue('--text-1')}`,
    `--nm-accent:${wurzel.getPropertyValue('--text-accent')}`,
  ].join(';')

  return `<!doctype html><html><head><meta charset="utf-8">
<style>:root{${vars}}${stil}</style></head><body>${koerper}</body></html>`
}
