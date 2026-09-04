/* Das KI-Fenster über dem Editor — was, wie, und dann ansehen.
 *
 * Drei Stufen, und die erste ist bewusst NICHT „ganze Mail oder Markierung":
 * Wenn etwas markiert ist, hat der Mensch die Frage schon beantwortet; ist
 * nichts markiert, gibt es nur eine mögliche Antwort. Der Umfang wird deshalb
 * oben **gezeigt** und lässt sich umstellen — gefragt wird nach dem, was die
 * App nicht wissen kann.
 *
 * ⚠️ **Das Ergebnis ersetzt nichts von selbst.** Eine Umformulierung kann
 * still einen Termin oder einen Betrag verändern, und der Text geht danach als
 * Mail hinaus. Deshalb stehen alt und neu nebeneinander, und erst „Übernehmen"
 * fasst den Entwurf an. Bei „nur Rechtschreibung" ist das am wichtigsten: Wer
 * um Kommas bittet, liest den Absatz nicht noch einmal gegen.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Languages, SpellCheck, Sparkles, WandSparkles } from 'lucide-react'
import { api } from '../api/client'
import { Button, Dialog, Select } from '../ds'
import { servermeldung } from '../lib/servermeldung'

/** Die Töne, die „Umformulieren" anbietet — dieselben Kennungen wie im Server. */
const TOENE = [
  'foermlich',
  'behoerdlich',
  'einfach',
  'sachlich',
  'freundlich',
  'bestimmt',
  'entschaerft',
  'kuerzer',
  'ausfuehrlicher',
] as const

/** ⚠️ **Eine Liste, kein Freitextfeld.** Der Wert landet in der Anweisung an
 *  das Modell; ein offenes Feld hiesse, dass jeder sich seinen eigenen Auftrag
 *  erteilt — und dann ist die Zusage „ändert keine Fakten" nichts mehr wert.
 *  Der Server prüft dieselbe Liste noch einmal. */
const SPRACHEN = ['English', 'Deutsch', 'Français', 'Español', 'Italiano', 'Nederlands', 'Polski'] as const

/** Ein Zeilenumbruch — als Konstante, weil ein Escape auf dem Weg durch
 *  Werkzeuge schon mehr als einmal verlorengegangen ist. */
const UMBRUCH = String.fromCharCode(10)
const DREI_UMBRUECHE = new RegExp(UMBRUCH + '{3,}', 'g')

type Auftrag = 'rechtschreibung' | 'uebersetzen' | 'umformulieren'

export interface KiAuswahl {
  /** Der markierte Text als HTML — leer, wenn nichts markiert ist. */
  markiert: string
  /** Der ganze Entwurf als HTML, **ohne Zitat und ohne Signatur**. */
  ganz: string
}

interface Props {
  auswahl: KiAuswahl
  /** Setzt den bearbeiteten Text zurück in den Editor. */
  aufUebernehmen: (neu: string, aufMarkierung: boolean) => void
  aufSchliessen: () => void
}

function woerter(html: string): number {
  const d = document.createElement('div')
  d.innerHTML = html
  const text = (d.textContent ?? '').trim()
  return text ? text.split(/\s+/).length : 0
}

/** HTML zu lesbarem Text fürs Gegenüber.
 *
 *  ⚠️ **`textContent` allein reicht nicht.** Es klebt die Absätze aneinander
 *  („Herr Weber,vielen Dank"), und dann sieht der Vergleich aus wie ein Fehler
 *  des Modells. Die Blockenden werden deshalb vorher zu Zeilenumbrüchen — der
 *  Kasten steht auf `whitespace-pre-wrap`. */
function alsText(html: string): string {
  const mitUmbruch = html
    .replace(/<br\s*\/?>/gi, UMBRUCH)
    .replace(/<\/(p|div|li|h[1-6]|blockquote|tr)>/gi, (t) => t + UMBRUCH)
  const d = document.createElement('div')
  d.innerHTML = mitUmbruch
  return (d.textContent ?? '').replace(DREI_UMBRUECHE, UMBRUCH + UMBRUCH).trim()
}

export function KiFenster({ auswahl, aufUebernehmen, aufSchliessen }: Props) {
  const { t } = useTranslation()
  /* Markiertes gewinnt — wer etwas ausgewählt hat, meint es auch. */
  const [aufMarkierung, setAufMarkierung] = useState(Boolean(auswahl.markiert.trim()))
  const [auftrag, setAuftrag] = useState<Auftrag | null>(null)
  const [ton, setTon] = useState<string>(TOENE[0])
  const [sprache, setSprache] = useState<string>(SPRACHEN[0])
  const [ergebnis, setErgebnis] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  const quelle = aufMarkierung ? auswahl.markiert : auswahl.ganz
  const anzahl = woerter(quelle)

  async function losschicken(was: Auftrag) {
    setFehler('')
    setLaeuft(true)
    try {
      const raus = await api.senden<{ text: string }>('/api/ki/text', {
        text: quelle,
        auftrag: was,
        ziel: was === 'umformulieren' ? ton : was === 'uebersetzen' ? sprache : '',
      })
      setErgebnis(raus.text)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  /* --- Stufe 3: das Ergebnis ------------------------------------------- */
  if (ergebnis) {
    return (
      <Dialog
        open
        width={860}
        title={t('ki.ergebnis')}
        description={t('ki.ergebnis_hinweis')}
        onClose={aufSchliessen}
        footer={
          <>
            <Button variant="ghost" onClick={() => setErgebnis('')}>
              {t('ki.noch_einmal')}
            </Button>
            <Button variant="ghost" onClick={aufSchliessen}>
              {t('ki.verwerfen')}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                aufUebernehmen(ergebnis, aufMarkierung)
                aufSchliessen()
              }}
            >
              <Check className="size-4" aria-hidden />
              {t('ki.uebernehmen')}
            </Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Gegenueber titel={t('ki.vorher')} text={alsText(quelle)} />
          <Gegenueber titel={t('ki.nachher')} text={alsText(ergebnis)} hervor />
        </div>
      </Dialog>
    )
  }

  /* --- Stufe 1 und 2 ---------------------------------------------------- */
  return (
    <Dialog
      open
      width={560}
      title={t('ki.titel')}
      onClose={aufSchliessen}
      /* ⚠️ Solange die Anfrage läuft, nicht wegklickbar — sonst ist das Fenster
         weg und das Ergebnis kommt nirgendwo an. Dieselbe Regel wie überall. */
      abweisbar={!laeuft}
      footer={
        <>
          <Button variant="ghost" onClick={aufSchliessen} disabled={laeuft}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant="primary"
            disabled={!auftrag || anzahl === 0 || laeuft}
            loading={laeuft}
            onClick={() => auftrag && void losschicken(auftrag)}
          >
            {t('ki.los')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {/* ⚠️ Gezeigt, nicht gefragt — der Sonderfall bleibt einen Klick weit weg. */}
        <p className="mb-0 flex flex-wrap items-baseline gap-x-2 text-[13px] text-fg-2">
          <span>
            {aufMarkierung ? t('ki.umfang_markiert') : t('ki.umfang_ganz')}
            {' · '}
            {t('ki.woerter', { anzahl })}
          </span>
          {auswahl.markiert.trim() && (
            <button
              type="button"
              className="text-[12px] text-accent hover:underline"
              onClick={() => setAufMarkierung((a) => !a)}
            >
              {aufMarkierung ? t('ki.lieber_ganz') : t('ki.lieber_markiert')}
            </button>
          )}
        </p>

        <div className="flex flex-col gap-2">
          <Wahl
            symbol={<SpellCheck className="size-4" aria-hidden />}
            titel={t('ki.rechtschreibung')}
            text={t('ki.rechtschreibung_text')}
            gewaehlt={auftrag === 'rechtschreibung'}
            aufWahl={() => setAuftrag('rechtschreibung')}
          />
          <Wahl
            symbol={<WandSparkles className="size-4" aria-hidden />}
            titel={t('ki.umformulieren')}
            text={t('ki.umformulieren_text')}
            gewaehlt={auftrag === 'umformulieren'}
            aufWahl={() => setAuftrag('umformulieren')}
          >
            <Select label={t('ki.ton')} value={ton} onChange={(e) => setTon(e.target.value)}>
              {TOENE.map((x) => (
                <option key={x} value={x}>
                  {t(`ki.ton_${x}`)}
                </option>
              ))}
            </Select>
          </Wahl>
          <Wahl
            symbol={<Languages className="size-4" aria-hidden />}
            titel={t('ki.uebersetzen')}
            text={t('ki.uebersetzen_text')}
            gewaehlt={auftrag === 'uebersetzen'}
            aufWahl={() => setAuftrag('uebersetzen')}
          >
            <Select
              label={t('ki.zielsprache')}
              value={sprache}
              onChange={(e) => setSprache(e.target.value)}
            >
              {SPRACHEN.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </Select>
          </Wahl>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        <p className="mb-0 text-[12px] text-fg-4">{t('ki.geht_hinaus')}</p>
      </div>
    </Dialog>
  )
}

function Wahl({
  symbol,
  titel,
  text,
  gewaehlt,
  aufWahl,
  children,
}: {
  symbol: React.ReactNode
  titel: string
  text: string
  gewaehlt: boolean
  aufWahl: () => void
  children?: React.ReactNode
}) {
  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        gewaehlt ? 'border-accent bg-accent-soft' : 'border-line bg-surface-2'
      }`}
    >
      <button
        type="button"
        aria-pressed={gewaehlt}
        onClick={aufWahl}
        className="flex w-full items-start gap-2.5 text-left"
      >
        <span className={gewaehlt ? 'mt-0.5 text-accent' : 'mt-0.5 text-fg-3'}>{symbol}</span>
        <span className="flex flex-col gap-0.5">
          <span className="text-[13px] font-semibold text-fg-1">{titel}</span>
          <span className="text-[12px] text-fg-3">{text}</span>
        </span>
      </button>
      {/* Die zweite Stufe steht erst da, wenn sie gebraucht wird. */}
      {gewaehlt && children && <div className="mt-3">{children}</div>}
    </div>
  )
}

function Gegenueber({ titel, text, hervor = false }: { titel: string; text: string; hervor?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-4">
        {hervor && <Sparkles className="size-3.5 text-accent" aria-hidden />}
        {titel}
      </span>
      <div
        className={`max-h-[320px] overflow-y-auto whitespace-pre-wrap rounded-md border p-3 text-[13px] leading-relaxed ${
          hervor ? 'border-accent/40 bg-accent-soft text-fg-1' : 'border-line bg-surface-2 text-fg-2'
        }`}
      >
        {text}
      </div>
    </div>
  )
}
