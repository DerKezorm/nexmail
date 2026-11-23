/* Die Einstellungen, aufgebaut wie in nexnotes.
 *
 * ⚠️ **Wer eine nex-App kennt, findet sich in der anderen zurecht**
 * (22.11.2026). Deshalb dieselbe Seite: links oben das eigene Konto mit Bild und
 * Rolle, darunter die Gruppen „Mein Konto", „Mail" und (für den Betreiber)
 * „Server", ganz unten „Über nexmail". Rechts Titel, ein Satz dazu und der
 * Inhalt. Ist die Seite schmal (unter 700 px eigene Breite, nicht Fenster),
 * steht statt der Navigation eine Auswahl über dem Inhalt. Die Bereiche
 * stehen in `einstellungen/bereiche.ts`.
 *
 * Bis 0.30 waren das zwei Seiten mit Reitern (Einstellungen und Verwaltung)
 * plus KI und „Über" als eigene Punkte der Leiste.
 *
 * Eigene Seite und kein Fenster: Das Konto-Formular trägt zwei Serverblöcke
 * und einen Verbindungstest — in einem Fenster über der Mail-Ansicht wäre das
 * ein Guckloch.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Building2, FileText, Info, KeyRound, ListChecks, Mail, RefreshCw, Smartphone } from 'lucide-react'
import { Button, Dialog } from '../ds'
import type { Ich } from '../api/client'
import { Postfachkacheln } from '../components/Postfachkacheln'
import { PostfachHinzufuegen } from '../components/PostfachHinzufuegen'
import { useNachfrage } from '../components/Nachfrage'
import { Profilbild } from '../components/Profilbild'
import { Benachrichtigungen } from './Benachrichtigungen'
import { Darstellung } from './Darstellung'
import { KontoFormular } from './KontoFormular'
import { Schlagworte } from './Schlagworte'
import { ApiSchluessel } from './ApiSchluessel'
import { IphoneVerbinden } from './IphoneVerbinden'
import { Sicherheit } from './Sicherheit'
import { Regeln, type RegelVorlage } from './Regeln'
import { Abwesenheit } from './Abwesenheit'
import { Signaturen } from './Signaturen'
import { Textvorlagen } from './Textvorlagen'
import { TodoApps } from './TodoApps'
import { KiSeite } from './KiSeite'
import { UeberPage } from './UeberPage'
import { Benutzerverwaltung } from './Benutzerverwaltung'
import { OauthVerwaltung } from './OauthVerwaltung'
import { OidcVerwaltung } from './OidcVerwaltung'
import { Protokoll } from './Protokoll'
import { Sicherungen } from './Sicherungen'
import { Postausgang, ServerAllgemein } from './Verwaltung'
import { Profil } from './einstellungen/Profil'
import { KalenderUndBuecher } from './einstellungen/KalenderUndBuecher'
import { Karte } from './einstellungen/Karte'
import {
  GRUPPEN,
  UEBER,
  bereichDef,
  bereicheFuer,
  erlaubterBereich,
  ueberSichtbar,
  type Bereich,
} from './einstellungen/bereiche'
import { api } from '../api/client'
import type { KontoZeile } from '../api/client'

export type { Bereich } from './einstellungen/bereiche'

interface Props {
  bereich: Bereich
  aufBereich: (b: Bereich) => void
  formularOffen: boolean
  aufFormular: (offen: boolean) => void
  /** Das Fenster hinter der (+)-Kachel. Es steht in `App`, weil auch die
   *  Ordnerspalte dorthin führt („Postfach hinzufügen"). */
  wahlOffen: boolean
  aufWahl: (offen: boolean) => void
  ich: Ich | null
  /** ⚠️ Nach einer Betreiber-Übergabe ist man selbst keiner mehr; ohne
   *  Nachladen blieben die Bereiche „Server" stehen. */
  ichNeuLaden?: () => void
  /** „Abmelden" im Profil (seit 23.11.2026 der einzige Weg). */
  aufAbmelden: () => void
  /** Hell oder dunkel, unter Darstellung (seit 22.11.2026 nur dort). */
  modus: 'dark' | 'light'
  aufModus: (m: 'dark' | 'light') => void
  /** Nach Anlegen/AEndern/Entfernen: App-weite Kontenliste nachziehen (Banner!). */
  aufKontenGeaendert?: () => void
  /** Nach jeder AEnderung bei den Schlagworten: Marken und Menues der
   *  Mail-Ansicht nachziehen — was ich aendere, muss ich auch sehen. */
  aufSchlagworteGeaendert?: () => void
  /** „Regel erstellen …" aus dem Rechtsklick auf eine Mail. */
  regelvorlage?: RegelVorlage | null
  aufRegelvorlageGenommen?: () => void
  /** „Was ist neu“ noch einmal öffnen, unter „Über nexmail“. */
  aufWasNeu?: () => void
}

const EINTRAG =
  'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[14px] transition-colors duration-[var(--dur-fast)] '
const LEISE = 'text-fg-2 hover:bg-surface-3 hover:text-fg-1'
const GEWAEHLT = 'bg-accent-soft font-medium text-accent-text ring-1 ring-accent/40'

export function EinstellungenPage({
  bereich: gewuenscht,
  aufBereich,
  formularOffen,
  aufFormular,
  wahlOffen,
  aufWahl,
  ich,
  ichNeuLaden,
  aufAbmelden,
  modus,
  aufModus,
  aufKontenGeaendert,
  aufSchlagworteGeaendert,
  regelvorlage = null,
  aufRegelvorlageGenommen,
  aufWasNeu,
}: Props) {
  // ⚠️ Bearbeiten und Anlegen benutzen dasselbe Formular. Getrennt zu
  // pflegen hieße zwei Stellen, an denen ein Feld fehlen kann.
  const [bearbeitet, setBearbeitet] = useState<KontoZeile | null>(null)
  const { t } = useTranslation()
  /* Ob im Postfach-Fenster etwas Ungespeichertes steht. ⚠️ Kreuz, Escape und
     Klick daneben gehen alle über `fensterZu`: Wer etwas eingetragen hat,
     wird gefragt, bevor es verloren geht. */
  const [ungespeichert, setUngespeichert] = useState(false)
  const { fragen, fenster: rueckfrage } = useNachfrage()
  /* ⚠️ Escape trifft beide Fenster: die Rückfrage UND das Postfach-Fenster
     darunter. Ohne diese Sperre fragte das untere gleich noch einmal. */
  const fragtGerade = useRef(false)
  async function fensterZu() {
    if (fragtGerade.current) return
    if (ungespeichert) {
      fragtGerade.current = true
      const ja = await fragen({
        titel: t('konto.ungespeichert_titel'),
        text: t('konto.ungespeichert_text'),
        knopf: t('konto.ungespeichert_verwerfen'),
        gefaehrlich: true,
      })
      // Erst nach dem Ereignis freigeben, das die Rückfrage schloss.
      window.setTimeout(() => (fragtGerade.current = false), 0)
      if (ja !== true) return
    }
    setUngespeichert(false)
    aufFormular(false)
    setBearbeitet(null)
  }
  const [konten, setKonten] = useState<KontoZeile[] | null>(null)

  const laden = useCallback(() => {
    api
      .holen<KontoZeile[]>('/api/konten')
      .then(setKonten)
      .catch(() => setKonten([]))
  }, [])

  useEffect(laden, [laden])

  // Welche Farbe ein neues Postfach bekäme. Wird zugeteilt, nicht gewählt —
  // deshalb wird sie hier nur angezeigt, nicht angeboten.
  const vergeben = new Set((konten ?? []).map((k) => k.farbe))
  let naechste: 1 | 2 | 3 | 4 | 5 | 6 = 1
  for (let n = 1; n <= 6; n++) {
    if (!vergeben.has(n)) {
      naechste = n as 1 | 2 | 3 | 4 | 5 | 6
      break
    }
  }

  // ⚠️ Solange `ich` fehlt, weiß niemand, ob „Server" erlaubt ist. Ohne diese
  // Wartezeit sprang ein Betreiber beim Laden kurz aufs Profil.
  const bereich = ich ? erlaubterBereich(gewuenscht, ich) : gewuenscht
  const Symbol = bereichDef(bereich).symbol
  const titel = t(`einstellungen.bereiche.${bereich}.titel`)
  const text = bereich === 'ki' ? t('ki.seite_lede') : t(`einstellungen.bereiche.${bereich}.text`)

  function inhalt(): ReactNode {
    switch (bereich) {
      case 'profil':
        return <Profil ich={ich} ichNeuLaden={ichNeuLaden} aufAbmelden={aufAbmelden} />
      case 'sicherheit':
        return <Sicherheit ich={ich} ichNeuLaden={ichNeuLaden} />
      case 'darstellung':
        return <Darstellung ichNeuLaden={ichNeuLaden} modus={modus} aufModus={aufModus} />
      case 'benachrichtigungen':
        return <Benachrichtigungen />
      case 'kalender':
        return <KalenderUndBuecher />
      case 'verbindungen':
        return (
          <>
            <Karte id="todoapps" symbol={ListChecks} titel={t('einstellungen.aufgaben')}>
              <TodoApps />
            </Karte>
            <Karte id="iphone" symbol={Smartphone} titel={t('einstellungen.iphone')}>
              <IphoneVerbinden istBetreiber={Boolean(ich?.ist_betreiber)} />
            </Karte>
            <Karte id="api" symbol={KeyRound} titel={t('einstellungen.api')}>
              <ApiSchluessel istBetreiber={Boolean(ich?.ist_betreiber)} />
            </Karte>
          </>
        )
      case 'postfaecher':
        /* ⚠️ **Die Kacheln bleiben stehen, auch wenn ein Formular offen
           ist.** Vorher tauschte der Reiter seinen ganzen Inhalt aus; wer
           ein Postfach anlegte, sah den Bestand nicht mehr und danach
           eine Liste, von der er nicht wusste, ob sie neu geladen war. */
        return (
          <Postfaecher
            konten={konten}
            aufHinzufuegen={() => {
              setBearbeitet(null)
              aufWahl(true)
            }}
            aufBearbeiten={(k) => {
              setBearbeitet(k)
              aufFormular(true)
            }}
            aufNeuLaden={() => {
              laden()
              aufKontenGeaendert?.()
            }}
          />
        )
      case 'regeln':
        return <Regeln vorlage={regelvorlage} aufVorlageGenommen={aufRegelvorlageGenommen} />
      case 'signaturen':
        /* Die Textvorlagen wohnen im selben Bereich, als eigene Karte —
           beides sind Textbausteine für das Schreiben. */
        return (
          <>
            <Karte id="signaturen" symbol={FileText} titel={t('einstellungen.signaturen')}>
              <Signaturen />
            </Karte>
            <Karte
              id="textvorlagen"
              symbol={FileText}
              titel={t('textvorlagen.titel')}
              text={t('textvorlagen.hinweis')}
            >
              <Textvorlagen />
            </Karte>
          </>
        )
      case 'abwesenheit':
        return <Abwesenheit />
      case 'schlagworte':
        return <Schlagworte aufGeaendert={aufSchlagworteGeaendert} />
      case 'ki':
        return <KiSeite istBetreiber={Boolean(ich?.ist_betreiber)} ichNeuLaden={ichNeuLaden} />
      case 'allgemein':
        return <ServerAllgemein />
      case 'anmeldung':
        return <OidcVerwaltung />
      case 'mailversand':
        return (
          <>
            <Karte id="postausgang" symbol={Mail} titel={t('verwaltung.postausgang')}>
              <Postausgang />
            </Karte>
            <Karte id="oauth" symbol={Building2} titel={t('verwaltung.oauth')}>
              <OauthVerwaltung />
            </Karte>
          </>
        )
      case 'speicher':
        return <Sicherungen />
      case 'konten':
        return <Benutzerverwaltung ichNeuLaden={ichNeuLaden} />
      case 'log':
        return <Protokoll />
      case 'ueber':
        return <UeberPage istBetreiber={Boolean(ich?.ist_betreiber)} aufWasNeu={aufWasNeu} />
    }
  }

  return (
    <div className="@container min-h-0 flex-1 overflow-y-auto bg-canvas">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-col gap-5 @min-[700px]:flex-row @min-[700px]:items-start @min-[700px]:gap-8">
          <Navigation ich={ich} bereich={bereich} aufBereich={aufBereich} />
          <Sprungwahl ich={ich} bereich={bereich} aufBereich={aufBereich} />

          <div className="flex min-w-0 flex-1 flex-col gap-5" data-testid={`einstellungen-${bereich}`}>
            <div>
              <h1 className="mb-0 flex items-center gap-2 font-display text-[24px] font-semibold tracking-tight text-fg-1">
                <Symbol className="size-5 text-fg-4 @min-[700px]:hidden" aria-hidden />
                {titel}
              </h1>
              {text && <p className="mt-1 mb-0 max-w-[720px] text-[14px] text-fg-3">{text}</p>}
            </div>
            <div className="flex flex-col gap-6" data-testid="einstellungen-inhalt">
              {inhalt()}
            </div>
          </div>
        </div>
      </div>

      {/* ⚠️ **Ein Fenster, nicht eine zweite Seite.** Anlegen und Bearbeiten
          gehen durch dieselbe Maske; sie einmal als Seite und einmal als
          Fenster zu zeigen wären zwei Anwendungen. */}
      <Dialog
        open={formularOffen}
        width={720}
        title={bearbeitet ? t('konto.bearbeiten_titel') : t('konto.hinzufuegen')}
        onClose={() => void fensterZu()}
      >
        <KontoFormular
          key={bearbeitet?.id ?? 'neu'}
          imFenster
          naechsteFarbe={naechste}
          bestehend={bearbeitet}
          /* Was schon vergeben ist, wird angeboten — sonst entstehen
             „Arbeit" und „arbeit" nebeneinander. */
          bekannteTags={[...new Set((konten ?? []).flatMap((k) => k.tags ?? []))]}
          aufAbbrechen={() => void fensterZu()}
          aufUngespeichert={setUngespeichert}
          aufAngelegt={() => {
            setUngespeichert(false)
            aufFormular(false)
            setBearbeitet(null)
            laden()
            aufKontenGeaendert?.()
          }}
        />
      </Dialog>

      {rueckfrage}

      {/* ⚠️ **Über der Seite, nicht im Reiter.** Der Rückweg von Google landet
          auf der Startseite; das Fenster muss auch dann aufgehen, wenn gerade
          ein anderer Reiter zuletzt offen war. */}
      <PostfachHinzufuegen
        offen={wahlOffen}
        konten={konten ?? []}
        aufSchliessen={() => aufWahl(false)}
        aufImap={() => {
          setBearbeitet(null)
          aufFormular(true)
        }}
        aufAngelegt={() => {
          laden()
          aufKontenGeaendert?.()
        }}
      />
    </div>
  )
}

/** Die Navigation links, wie in nexnotes (`settings/SettingsNav.tsx`). */
function Navigation({
  ich,
  bereich,
  aufBereich,
}: {
  ich: Ich | null
  bereich: Bereich
  aufBereich: (b: Bereich) => void
}) {
  const { t } = useTranslation()
  const bereiche = bereicheFuer(ich)
  const gruppen = GRUPPEN.filter((g) => bereiche.some((b) => b.gruppe === g))
  return (
    <nav
      aria-label={t('einstellungen.titel')}
      className="hidden w-60 shrink-0 @min-[700px]:sticky @min-[700px]:top-0 @min-[700px]:block"
      data-testid="einstellungen-navigation"
    >
      {ich && (
        <div className="mb-4 flex items-center gap-3 px-2.5">
          <Profilbild id={ich.id} name={ich.anzeigename} stand={ich.profilbild} groesse={40} />
          <div className="min-w-0">
            <p className="mb-0 truncate font-semibold text-fg-1" title={ich.anzeigename}>
              {ich.anzeigename}
            </p>
            <p className="mb-0 text-[12px] text-fg-4">
              {ich.ist_betreiber ? t('profil.rolle_betreiber') : t('profil.rolle_benutzer')}
            </p>
          </div>
        </div>
      )}
      {gruppen.map((g) => (
        <div key={g} className="mb-4">
          <p
            id={`einstellungen-gruppe-${g}`}
            className="mb-0 px-2.5 pb-1.5 text-[11px] font-semibold tracking-wider text-fg-4 uppercase"
          >
            {t(`einstellungen.gruppen.${g}`)}
          </p>
          <ul aria-labelledby={`einstellungen-gruppe-${g}`} className="m-0 flex list-none flex-col gap-0.5 p-0">
            {bereiche
              .filter((b) => b.gruppe === g)
              .map(({ id, symbol: Symbol }) => {
                const hier = id === bereich
                return (
                  <li key={id}>
                    <button
                      type="button"
                      aria-current={hier ? 'page' : undefined}
                      onClick={() => aufBereich(id)}
                      className={EINTRAG + (hier ? GEWAEHLT : LEISE)}
                      data-testid={`einstellungen-nav-${id}`}
                    >
                      <Symbol className="size-4 shrink-0" strokeWidth={1.8} aria-hidden />
                      <span className="min-w-0 truncate">{t(`einstellungen.bereiche.${id}.titel`)}</span>
                    </button>
                  </li>
                )
              })}
          </ul>
        </div>
      ))}
      {ueberSichtbar(ich) && (
        <div className="border-t border-line-subtle pt-2">
          <button
            type="button"
            aria-current={bereich === UEBER.id ? 'page' : undefined}
            onClick={() => aufBereich(UEBER.id)}
            className={EINTRAG + (bereich === UEBER.id ? GEWAEHLT : LEISE)}
            data-testid="einstellungen-nav-ueber"
          >
            <Info className="size-4 shrink-0" strokeWidth={1.8} aria-hidden />
            <span className="min-w-0 truncate">{t('einstellungen.bereiche.ueber.titel')}</span>
          </button>
        </div>
      )}
    </nav>
  )
}

/** Die schmale Seite: eine Auswahl mit den Gruppen, wie in nexnotes. */
function Sprungwahl({
  ich,
  bereich,
  aufBereich,
}: {
  ich: Ich | null
  bereich: Bereich
  aufBereich: (b: Bereich) => void
}) {
  const { t } = useTranslation()
  const bereiche = bereicheFuer(ich)
  const gruppen = GRUPPEN.filter((g) => bereiche.some((b) => b.gruppe === g))
  return (
    <label className="block @min-[700px]:hidden" data-testid="einstellungen-sprung">
      <span className="sr-only">{t('einstellungen.springen')}</span>
      <select
        value={bereich}
        onChange={(e) => aufBereich(e.target.value as Bereich)}
        className="h-10 w-full rounded-md border border-line bg-surface-2 px-3 text-[14px] text-fg-1"
      >
        {gruppen.map((g) => (
          <optgroup key={g} label={t(`einstellungen.gruppen.${g}`)}>
            {bereiche
              .filter((b) => b.gruppe === g)
              .map((b) => (
                <option key={b.id} value={b.id}>
                  {t(`einstellungen.bereiche.${b.id}.titel`)}
                </option>
              ))}
          </optgroup>
        ))}
        {ueberSichtbar(ich) && <option value={UEBER.id}>{t('einstellungen.bereiche.ueber.titel')}</option>}
      </select>
    </label>
  )
}

interface ListenProps {
  konten: KontoZeile[] | null
  aufHinzufuegen: () => void
  aufBearbeiten: (konto: KontoZeile) => void
  aufNeuLaden: () => void
}

function Postfaecher({ konten, aufHinzufuegen, aufBearbeiten, aufNeuLaden }: ListenProps) {
  const { t } = useTranslation()

  // ⚠️ **Drei Zustände, nicht zwei** — noch nicht geladen sieht sonst aus wie
  // „da ist nichts", und genau so sieht ein Datenverlust aus.
  if (konten === null) {
    return <div className="h-24" />
  }

  return (
    <div className="flex flex-col gap-3">
      <Postfachkacheln
        konten={konten}
        aufHinzufuegen={aufHinzufuegen}
        aufBearbeiten={aufBearbeiten}
        aufNeuLaden={aufNeuLaden}
      />

      {/* Beim ersten Mal steht neben der einen Kachel sonst nichts, was sagt,
          was hier passieren soll. */}
      {konten.length === 0 && (
        <p className="mb-0 text-[13px] text-fg-3">{t('konto.kein_postfach_text')}</p>
      )}

      {konten.length > 0 && (
        <div>
          <Button variant="ghost" iconLeft={<RefreshCw className="size-4" />} onClick={aufNeuLaden}>
            {t('aktion.aktualisieren')}
          </Button>
        </div>
      )}
    </div>
  )
}
