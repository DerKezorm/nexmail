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
import { appPfad, ohneBasis } from './lib/basis'
import { EinladungPage } from './pages/EinladungPage'
import { KennwortNeuPage, VergessenPage } from './pages/KennwortPage'
import { EinrichtungPage } from './pages/EinrichtungPage'
import { api } from './api/client'
import type { Ich, Stand } from './api/client'
import { useGemerkt } from './lib/haken'

type Modus = 'dark' | 'light'
type Lage = 'laedt' | 'einrichten' | 'anmelden' | 'drin' | 'server_weg'

export default function Start() {
  const [modus, setModus] = useGemerkt<Modus>('nexmail.modus', 'dark')
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
      // sonst tippt jemand fünfmal sein Kennwort in eine tote Oberfläche.
      setLage('server_weg')
    }
  }, [])

  /* ⚠️ **Eine leichte Auffrischung neben ``pruefen``.**
   *
   * ``ich`` wurde bis zum 01.09.2026 **einmal** beim Start geholt und nach
   * unten durchgereicht — keine Handlung frischte es auf. Wer den zweiten
   * Faktor ausschaltete, sah es erst nach F5. Der Betreiber: „das zeigt er mir aber
   * erst an, wenn ich mit F5 die seite neu lade … das ist an mehreren stellen
   * aufgefallen."
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

  return (
    <App
      modus={modus}
      aufModus={setModus}
      ich={ich}
      ichNeuLaden={() => void ichNeuLaden()}
      aufAbmelden={() => void pruefen()}
    />
  )
}
