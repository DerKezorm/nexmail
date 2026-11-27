/* Der Torwächter: Einrichtung, Anmeldung oder die Anwendung.
 *
 * Die Entscheidung fällt der Server, nicht der Browser — zwei Abfragen,
 * einmal beim Laden:
 *
 *   /api/setup/status  →  gibt es überhaupt schon ein Konto?
 *   /api/auth/ich      →  bin ich angemeldet?
 *
 * ⚠️ **Der helle Modus wohnt hier und nicht in App.** Wer sich noch nicht
 * angemeldet hat, sieht trotzdem eine Oberfläche — und wenn er sie auf einem
 * hellen Bildschirm nicht lesen kann, kommt er nie bis zum Kennwortfeld.
 */
import { useCallback, useEffect, useState } from 'react'
import App from './App'
import { AnmeldePage } from './pages/AnmeldePage'
import { SitzungAbgelaufen } from './components/SitzungAbgelaufen'
import { appPfad, ohneBasis } from './lib/basis'
import { EinladungPage } from './pages/EinladungPage'
import { KennwortNeuPage, VergessenPage } from './pages/KennwortPage'
import { EinrichtungPage } from './pages/EinrichtungPage'
import { AdressePage } from './pages/AdressePage'
import { McpSeite, mcpSeiteVon } from './pages/McpSeite'
import { AppVerbinden, istAppVerbinden } from './pages/AppVerbinden'
import { NeuesPasswort } from './components/NeuesPasswort'
import { kontoSprache } from './i18n'
import { api } from './api/client'
import type { Ich, Stand } from './api/client'
import { useGemerkt } from './lib/haken'
import { gespeicherteBrowserwahl } from './lib/browserwahl'

type Modus = 'dark' | 'light'
/** Was gewählt ist: hell, dunkel oder wie das System (seit 24.11.2026, wie
 *  nexnotes und nextasks). */
export type Darstellungswahl = Modus | 'system'

/** Ob das System gerade dunkel will; folgt dem Umschalten live. */
function useSystemDunkel(): boolean {
  const frage = '(prefers-color-scheme: dark)'
  const [dunkel, setDunkel] = useState(() => window.matchMedia?.(frage).matches ?? true)
  useEffect(() => {
    const m = window.matchMedia?.(frage)
    if (!m) return
    const neu = () => setDunkel(m.matches)
    m.addEventListener('change', neu)
    return () => m.removeEventListener('change', neu)
  }, [])
  return dunkel
}
type Lage = 'laedt' | 'einrichten' | 'anmelden' | 'drin' | 'server_weg'

export default function Start() {
  /* ⚠️ **Derselbe Schlüssel wie vorher**, jetzt mit `system` als drittem Wert:
     Wer hell oder dunkel gewählt hatte, behält es. Die Umschalter auf den
     Seiten vor der Anmeldung setzen ausdrücklich hell oder dunkel. */
  const [wahl, setModus] = useGemerkt<Darstellungswahl>('nexmail.modus', 'dark')
  const systemDunkel = useSystemDunkel()
  const modus: Modus = wahl === 'system' ? (systemDunkel ? 'dark' : 'light') : wahl
  const [lage, setLage] = useState<Lage>('laedt')
  const [ich, setIch] = useState<Ich | null>(null)
  /* Der Schlüssel aus der Adresse. Einmal beim Start gelesen — danach räumt
     die Seite ihn aus dem Verlauf, damit er nicht im Browserverlauf steht. */
  const [einladung, setEinladung] = useState(() => {
    /* ⚠️ **Erst den Vorbau abziehen.** Unter `https://mail.example.org/nexmail`
       heißt der Pfad `/nexmail/einladung/…`; ein Muster auf `^/einladung/`
       traf dort nie zu, und die Seite zeigte stumm die Anmeldung — der
       Eingeladene sah eine Maske, in die er nichts eintragen kann. */
    const pfad = ohneBasis(window.location.pathname)
    const treffer = pfad ? /^\/einladung\/(.+)$/.exec(pfad) : null
    return treffer ? decodeURIComponent(treffer[1]) : ''
  })

  /* Der Rücksetz-Schlüssel, genauso gelesen — und aus demselben Grund vor der
     Anmeldung: Wer ihn öffnet, kommt gerade nicht hinein. */
  const [kennwortschluessel, setKennwortschluessel] = useState(() => {
    const pfad = ohneBasis(window.location.pathname)
    const treffer = pfad ? /^\/kennwort\/(.+)$/.exec(pfad) : null
    return treffer ? decodeURIComponent(treffer[1]) : ''
  })
  const [vergessen, setVergessen] = useState(false)

  /* Der Link, der eine neue Adresse bestätigt (Kontenmodul), genauso gelesen: Er muss auch ohne Anmeldung gehen. */
  const [adressschluessel, setAdressschluessel] = useState(() => {
    const pfad = ohneBasis(window.location.pathname)
    const treffer = pfad ? /^\/adresse\/(.+)$/.exec(pfad) : null
    return treffer ? decodeURIComponent(treffer[1]) : ''
  })

  /* Die Sprache hängt seit dem Kontenmodul am Konto: nach der Anmeldung übernehmen. */
  useEffect(() => {
    void kontoSprache(ich?.sprache)
  }, [ich?.sprache])

  useEffect(() => {
    if (modus === 'light') document.documentElement.setAttribute('data-theme', 'light')
    else document.documentElement.removeAttribute('data-theme')
  }, [modus])

  const pruefen = useCallback(async () => {
    try {
      const stand = await api.holen<Stand>('/api/setup/status')
      if (!stand.eingerichtet) {
        setLage('einrichten')
        return
      }
      try {
        setIch(await api.holen<Ich>('/api/auth/ich'))
        setLage('drin')
      } catch {
        // 401 ist hier kein Fehler, sondern die Antwort.
        setLage('anmelden')
      }
    } catch {
      // Der Server antwortet gar nicht. Das ist etwas anderes als "nicht
      // angemeldet", und es darf nicht wie eine Anmeldemaske aussehen -
      // sonst tippt jemand fünfmal sein Passwort in eine tote Oberfläche.
      setLage('server_weg')
    }
  }, [])

  /* ⚠️ **Eine leichte Auffrischung neben ``pruefen``.**
   *
   * ``ich`` wurde bis zum 01.09.2026 **einmal** beim Start geholt und nach
   * unten durchgereicht — keine Handlung frischte es auf. Wer den zweiten
   * Faktor ausschaltete, sah es erst nach F5. Aufgefallen
   * ist das an mehreren Stellen.
   *
   * Und bewusst **nicht** ``pruefen()``: Das wechselt bei einem Fehlschlag auf
   * die Anmeldemaske. Eine misslungene Auffrischung darf niemanden hinauswerfen
   * — sie lässt dann einfach den alten Stand stehen. */
  const ichNeuLaden = useCallback(async () => {
    try {
      setIch(await api.holen<Ich>('/api/auth/ich'))
    } catch {
      // Bleibt, wie es war.
    }
  }, [])

  useEffect(() => {
    void pruefen()
  }, [pruefen])

  /* ⚠️ **Hell oder dunkel gilt seit konten 1.1.0 für das Konto auf allen Geräten** (E5). Hat das Konto noch keine
     Wahl (nur Konten von vor 1.1.0), übernimmt der Server einmal den Wert, den dieser Browser wirklich gespeichert hat
     (`nexmail.modus`), sonst nexmails bisherige Vorgabe „dunkel“ (E45); danach folgt der Browser dem Konto.
     Der Wert im Browser bleibt für die Seiten vor der Anmeldung. */
  const kontoTheme = ich?.theme
  useEffect(() => {
    if (!ich) return
    if (kontoTheme === '') {
      void api
        .senden<Ich>('/api/auth/ich/theme/browser', { wert: gespeicherteBrowserwahl() })
        .then(setIch)
        .catch(() => undefined)
    } else if (kontoTheme && kontoTheme !== wahl && ['light', 'dark', 'system'].includes(kontoTheme)) {
      setModus(kontoTheme as Darstellungswahl)
    }
    // Nur wenn sich das Konto ändert, nicht bei jedem Umschalten hier (das schreibt `darstellungSetzen`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ich?.id, kontoTheme])

  const darstellungSetzen = useCallback(
    (neu: Darstellungswahl) => {
      setModus(neu)
      void api
        .aendern<Ich>('/api/auth/ich/theme', { theme: neu })
        .then(setIch)
        .catch(() => undefined)
    },
    [setModus],
  )

  if (lage === 'laedt') {
    return <div className="h-full bg-canvas" />
  }

  if (lage === 'server_weg') {
    return (
      <div className="flex h-full items-center justify-center bg-canvas p-6 text-center">
        <div className="max-w-[420px]">
          <h1 className="mb-2 font-display text-[20px] text-fg-1">Kein Kontakt zum Server</h1>
          <p className="mb-4 text-[13px] text-fg-3">
            nexmail läuft, aber der Server antwortet nicht. Im Entwicklungsbetrieb fehlt
            meist nur <code className="font-mono">uvicorn</code>.
          </p>
          <button
            type="button"
            onClick={() => void pruefen()}
            className="rounded-md border border-line bg-surface-3 px-3.5 py-2 text-sm text-fg-1 transition-colors duration-[var(--dur-fast)] hover:border-line-strong"
          >
            Noch einmal versuchen
          </button>
        </div>
      </div>
    )
  }

  /* ⚠️ **Der Einladungslink kommt vor allem anderen** — auch vor der
     Ersteinrichtung und vor der Anmeldung. Wer ihn öffnet, hat kein Konto und
     soll keine Anmeldemaske sehen, in die er nichts eintragen kann. */
  if (einladung) {
    return (
      <EinladungPage
        schluessel={einladung}
        modus={modus}
        aufModus={setModus}
        aufFertig={() => {
          setEinladung('')
          void pruefen()
        }}
      />
    )
  }

  /* ⚠️ Auch der Rücksetz-Link kommt vor der Anmeldung — dieselbe Begründung
     wie bei der Einladung. */
  if (kennwortschluessel) {
    return (
      <KennwortNeuPage
        schluessel={kennwortschluessel}
        modus={modus}
        aufModus={setModus}
        aufFertig={() => {
          setKennwortschluessel('')
          window.history.replaceState(null, '', appPfad('/'))
          void pruefen()
        }}
      />
    )
  }

  if (adressschluessel) {
    return (
      <AdressePage
        schluessel={adressschluessel}
        modus={modus}
        aufModus={setModus}
        aufFertig={() => {
          setAdressschluessel('')
          window.history.replaceState(null, '', appPfad('/'))
          void pruefen()
        }}
      />
    )
  }

  if (lage === 'einrichten') {
    return <EinrichtungPage modus={modus} aufModus={setModus} aufFertig={() => void pruefen()} />
  }

  if (vergessen) {
    return (
      <VergessenPage modus={modus} aufModus={setModus} aufZurueck={() => setVergessen(false)} />
    )
  }

  if (lage === 'anmelden') {
    return (
      <AnmeldePage
        modus={modus}
        aufModus={setModus}
        aufFertig={() => void pruefen()}
        aufVergessen={() => setVergessen(true)}
      />
    )
  }

  /* Modul mcp: Zustimmung eines KI-Programms und Seite einer Rückfrage, nur angemeldet (davor kam die Anmeldung). */
  const mcpSeite = mcpSeiteVon(window.location.pathname)
  if (mcpSeite) {
    return <McpSeite seite={mcpSeite} />
  }

  /* Modul geraete: die Anmeldung einer App im Browser (/app-connect), nur angemeldet (davor kam die Anmeldung). */
  if (istAppVerbinden(window.location.pathname)) {
    return <AppVerbinden ich={ich} />
  }

  return (
    <>
      <App
        modus={modus}
        aufModus={setModus}
        darstellung={wahl}
        aufDarstellung={darstellungSetzen}
        ich={ich}
        ichNeuLaden={() => void ichNeuLaden()}
        aufAbmelden={() => void pruefen()}
      />
      {/* Nach einem neuen Passwort über einen Link, einmal: was noch Zugriff hat, und „Alle trennen“. */}
      {ich?.neues_passwort && <NeuesPasswort aufErledigt={ichNeuLaden} />}
      {/* konten 0.3.5: Endet die Sitzung, während nexmail offen ist, meldet man sich hier neu an; die Seite bleibt. */}
      <SitzungAbgelaufen ich={ich} aufFertig={() => void ichNeuLaden()} />
    </>
  )
}
