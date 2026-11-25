/* Die Einstellungen nach dem Bauplan „Einstellungen" (nexlore, Development/nexapps/Baupläne), im Gerüst des Bausatzes
 * ui 1.1.0: `SettingsLayout` mit `SettingsNav` (oben das Konto, „Mein Konto", nexmails eigene Gruppe „Mail", „Server"
 * nur für Betreiber, abgesetzt „Über nexmail") und je Bereich eine `SettingsPage`: Titel, eine Zeile, darunter nur
 * Karten. Jeder Bereich hat seine Adresse (`/settings/<slug>`, `einstellungen/bereiche.ts`); die deutschen Namen von
 * vorher führen dorthin. `/settings` allein ist auf dem Handy die Liste, auf breiter Seite das Profil neben der
 * Navigation.
 *
 * Eigene Seite und kein Fenster: Das Postfach-Formular trägt zwei Serverblöcke und einen Verbindungstest; in einem
 * Fenster über der Mail-Ansicht wäre das ein Guckloch.
 */
import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Building2, FileText, Inbox, ListChecks, ListFilter, RefreshCw, Tag } from 'lucide-react'
import { Dialog } from '../ds'
import { Beschriftung } from '../ds/beschriftung'
import type { Ich } from '../api/client'
import { Postfachkacheln } from '../components/Postfachkacheln'
import { PostfachHinzufuegen } from '../components/PostfachHinzufuegen'
import { useNachfrage } from '../components/Nachfrage'
import { Profilbild } from '../components/Profilbild'
import { FaktorAusHinweis } from '../components/FaktorAusHinweis'
import { appPfad, ohneBasis } from '../lib/basis'
import {
  Button,
  NEXUI_TEXTS,
  NexuiLanguage,
  SettingsLayout,
  SettingsNav,
  SettingsPage,
  areaText,
  languageOf,
  type SettingsGroup,
  type SettingsLink,
} from '../vendor/nexui'
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
import { KiAnbieter, KiSeite } from './KiSeite'
import { UeberPage } from './UeberPage'
import { Benutzerverwaltung } from './Benutzerverwaltung'
import { OauthVerwaltung } from './OauthVerwaltung'
import { OidcVerwaltung } from './OidcVerwaltung'
import { Protokoll } from './Protokoll'
import { Sicherungen } from './Sicherungen'
import { Postausgang, ServerAllgemein } from './Verwaltung'
import { Profil } from './einstellungen/Profil'
import { NexApps } from './einstellungen/NexApps'
import { KalenderUndBuecher } from './einstellungen/KalenderUndBuecher'
import { Karte } from './einstellungen/Karte'
import {
  GRUPPEN,
  UEBER,
  bereichAusPfad,
  bereichDef,
  bereicheFuer,
  erlaubterBereich,
  pfadVon,
  type Bereich,
  type BereichDef,
} from './einstellungen/bereiche'
import { api } from '../api/client'
import type { KontoZeile } from '../api/client'

const APP = 'nexmail'

/** Wo der Hinweis „Zweiter Faktor ist abgeschaltet“ oben steht (`NOTICES` im Kontenmodul). */
const NOTHAMMER_BEREICHE: Bereich[] = ['profile', 'security', 'sign-in']

export type { Bereich } from './einstellungen/bereiche'

interface Props {
  /** Der gezeigte Bereich; `null` ist `/settings` allein (auf dem Handy die Liste). */
  bereich: Bereich | null
  aufBereich: (b: Bereich | null) => void
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
  /** Die Wahl samt „Wie das System“ (seit 24.11.2026). */
  darstellung?: 'dark' | 'light' | 'system'
  aufDarstellung?: (w: 'dark' | 'light' | 'system') => void
  /** Nach Anlegen/AEndern/Entfernen: App-weite Kontenliste nachziehen (Banner!). */
  aufKontenGeaendert?: () => void
  /** Nach jeder AEnderung bei den Schlagworten: Marken und Menues der
   *  Mail-Ansicht nachziehen — was ich aendere, muss ich auch sehen. */
  aufSchlagworteGeaendert?: () => void
  /** „Regel erstellen …" aus dem Rechtsklick auf eine Mail. */
  regelvorlage?: RegelVorlage | null
  aufRegelvorlageGenommen?: () => void
  /** „Was ist neu“ noch einmal öffnen. Seit dem Bausatz ui 1.1.0 öffnet die Über-Seite ihr eigenes Fenster. */
  aufWasNeu?: () => void
}

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
  darstellung,
  aufDarstellung,
  aufKontenGeaendert,
  aufSchlagworteGeaendert,
  regelvorlage = null,
  aufRegelvorlageGenommen,
}: Props) {
  // ⚠️ Bearbeiten und Anlegen benutzen dasselbe Formular. Getrennt zu
  // pflegen hieße zwei Stellen, an denen ein Feld fehlen kann.
  const [bearbeitet, setBearbeitet] = useState<KontoZeile | null>(null)
  const { t, i18n } = useTranslation()
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

  // ⚠️ Solange `ich` fehlt, weiß niemand, ob „Server" erlaubt ist. Ohne diese Wartezeit sprang ein Betreiber beim
  // Laden kurz aufs Profil.
  const gewollt = gewuenscht ?? 'profile'
  const bereich = ich ? erlaubterBereich(gewollt, ich) : gewollt
  const dinge = t('einstellungen.dinge')
  const kit = NEXUI_TEXTS[languageOf(i18n.language)]
  const worte = (def: BereichDef) =>
    def.eigen || def.id === 'ai-provider'
      ? { titel: t(`einstellungen.bereiche.${def.id}.titel`), text: t(`einstellungen.bereiche.${def.id}.text`) }
      : { titel: areaText(kit, def.id, { app: APP, things: dinge })?.title ?? def.id, text: '' }
  const eigen = bereichDef(bereich)
  const eigeneWorte = eigen.eigen || eigen.id === 'ai-provider' ? worte(eigen) : null

  /* Der Link der Navigation: eine echte Adresse (Mittelklick, neuer Tab), ein gewöhnlicher Klick bleibt in der Seite. */
  const Verweis: SettingsLink = useCallback(
    ({ to, className, children, ...rest }) => (
      <a
        href={to}
        className={className}
        {...rest}
        onClick={(e: MouseEvent<HTMLAnchorElement>) => {
          if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
          e.preventDefault()
          const ziel = bereichAusPfad(ohneBasis(to) ?? to)
          aufBereich(ziel && 'bereich' in ziel ? ziel.bereich : null)
        }}
      >
        {children}
      </a>
    ),
    [aufBereich],
  )

  const gruppen: SettingsGroup[] = GRUPPEN.map((g) => ({
    id: g,
    title: g === 'mail' ? t('einstellungen.gruppe_mail') : undefined,
    areas: bereicheFuer(ich)
      .filter((b) => b.gruppe === g)
      .map((b) => ({
        slug: b.id,
        icon: b.symbol,
        href: appPfad(pfadVon(b.id)),
        title: b.eigen || b.id === 'ai-provider' ? worte(b).titel : undefined,
      })),
  }))

  function inhalt(): ReactNode {
    switch (bereich) {
      case 'profile':
        return <Profil ich={ich} ichNeuLaden={ichNeuLaden} aufAbmelden={aufAbmelden} />
      case 'security':
        return <Sicherheit ich={ich} ichNeuLaden={ichNeuLaden} />
      case 'appearance':
        return (
          <Darstellung
            ichNeuLaden={ichNeuLaden}
            modus={darstellung ?? modus}
            aufModus={aufDarstellung ?? ((m) => m !== 'system' && aufModus(m))}
          />
        )
      case 'notifications':
        return <Benachrichtigungen />
      case 'calendars':
        return <KalenderUndBuecher />
      case 'connections':
        return (
          <>
            {/* MAIL-1 AC-2: die nex-Apps zuerst, als Karten wie in nextime. */}
            <NexApps />
            <Karte id="todoapps" symbol={ListChecks} titel={t('einstellungen.aufgaben')}>
              {/* nextasks steht in seiner Karte oben (Befund 1 vom 24.11.2026). */}
              <TodoApps teil="ohne-nextasks" />
            </Karte>
            <Karte id="iphone" symbol="Smartphone" titel={t('einstellungen.iphone')}>
              <IphoneVerbinden istBetreiber={Boolean(ich?.ist_betreiber)} />
            </Karte>
            <Karte id="api" symbol="KeyRound" titel={t('einstellungen.api')}>
              <ApiSchluessel istBetreiber={Boolean(ich?.ist_betreiber)} />
            </Karte>
          </>
        )
      case 'mailboxes':
        /* ⚠️ **Die Kacheln bleiben stehen, auch wenn ein Formular offen
           ist.** Vorher tauschte der Reiter seinen ganzen Inhalt aus; wer
           ein Postfach anlegte, sah den Bestand nicht mehr und danach
           eine Liste, von der er nicht wusste, ob sie neu geladen war. */
        return (
          <Karte id="mailboxes" symbol={Inbox} titel={t('einstellungen.postfaecher')} text={t('einstellungen.bereiche.mailboxes.text')}>
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
          </Karte>
        )
      case 'rules':
        return (
          <Karte id="rules" symbol={ListFilter} titel={t('einstellungen.regeln')} text={t('einstellungen.bereiche.rules.text')}>
            <Regeln vorlage={regelvorlage} aufVorlageGenommen={aufRegelvorlageGenommen} />
          </Karte>
        )
      case 'signatures':
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
      case 'out-of-office':
        return <Abwesenheit />
      case 'tags':
        return (
          <Karte id="tags" symbol={Tag} titel={t('einstellungen.schlagworte')} text={t('einstellungen.bereiche.tags.text')}>
            <Schlagworte aufGeaendert={aufSchlagworteGeaendert} />
          </Karte>
        )
      case 'ai':
        return <KiSeite ichNeuLaden={ichNeuLaden} />
      case 'ai-provider':
        return <KiAnbieter ichNeuLaden={ichNeuLaden} />
      case 'general':
        return <ServerAllgemein />
      case 'sign-in':
        return <OidcVerwaltung />
      case 'mail':
        return (
          <>
            <Karte id="postausgang" symbol="Mail" titel={t('verwaltung.postausgang')}>
              <Postausgang />
            </Karte>
            <Karte id="oauth" symbol={Building2} titel={t('verwaltung.oauth')}>
              <OauthVerwaltung />
            </Karte>
          </>
        )
      case 'storage':
        return <Sicherungen ich={ich} />
      case 'accounts':
        return <Benutzerverwaltung ich={ich} ichNeuLaden={ichNeuLaden} />
      case 'log':
        return <Protokoll />
      case 'about':
        return <UeberPage ich={ich} />
    }
  }

  return (
    /* Beschriftungen normal geschrieben wie in nexnotes, auch in den Fenstern, die von hier aufgehen (25.11.2026). */
    <Beschriftung.Provider value="normal">
      <div className="min-h-0 flex-1 overflow-y-auto bg-canvas">
        <NexuiLanguage language={i18n.language}>
          <SettingsLayout
            list={gewuenscht === null}
            back={appPfad(pfadVon(null))}
            link={Verweis}
            nav={
              <SettingsNav
                app={APP}
                things={dinge}
                groups={gruppen}
                about={{ href: appPfad(pfadVon(UEBER.id)), slug: UEBER.id }}
                current={gewuenscht === null ? undefined : bereich}
                account={
                  ich
                    ? {
                        name: ich.anzeigename,
                        role: ich.ist_betreiber ? t('profil.rolle_betreiber') : t('profil.rolle_benutzer'),
                        picture: <Profilbild id={ich.id} name={ich.anzeigename} stand={ich.profilbild} groesse={40} />,
                      }
                    : undefined
                }
                link={Verweis}
              />
            }
          >
            <SettingsPage slug={bereich} app={APP} things={dinge} title={eigeneWorte?.titel} subtitle={eigeneWorte?.text || undefined}>
              {/* konten 0.3.3: Der Nothammer ist unten, deutlich oben auf den Kontoseiten und bei der Anmeldung. */}
              {ich?.zwei_faktor_aus && NOTHAMMER_BEREICHE.includes(bereich) && <FaktorAusHinweis />}
              {inhalt()}
            </SettingsPage>
          </SettingsLayout>
        </NexuiLanguage>

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
    </Beschriftung.Provider>
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
          <Button kind="secondary" icon={RefreshCw} onClick={aufNeuLaden}>
            {t('aktion.aktualisieren')}
          </Button>
        </div>
      )}
    </div>
  )
}
