/* Über nexmail: die `AboutPage` des Bausatzes ui 1.1.0 (Bauplan „Einstellungen", „Über"): Version mit „Version x ist
 * erschienen", „Was ist neu", Lizenz, Quelltext, Veröffentlichungen, Projektseite, „Einen Fehler gefunden?", die Karte
 * „Aktualisierungen" und „Gebaut mit". Jedes Konto sieht sie; der Schalter für die tägliche Nachfrage und „Jetzt
 * nachsehen" gehören dem Betreiber, weil die Frage für die ganze Installation hinausgeht.
 *
 * ⚠️ **Die Seite sagt, dass etwas hinausgeht.** nexmail liefert sogar die Schriften mit, damit es beim Öffnen niemanden
 * anfunkt; die Nachfrage bei GitHub (höchstens einmal in 24 Stunden) ist die einzige Verbindung, die zu nichts
 * Eingerichtetem gehört.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, type Ich } from '../api/client'
import { appPfad } from '../lib/basis'
import { servermeldung } from '../lib/servermeldung'
import { useWasNeu } from '../lib/wasneu'
import { AboutPage, Notice, type BuiltWith } from '../vendor/nexui'

interface Auskunft {
  version: string
  repo_adresse: string
  release_adresse: string
  projektseite: string
  lizenz: string
  update_pruefen: boolean
  geprueft: boolean
  neueste: string | null
  neuer_da: boolean
  geprueft_am: string | null
}

const BAUSTEINE: BuiltWith[] = [
  { name: 'FastAPI', url: 'https://fastapi.tiangolo.com', licence: 'MIT' },
  { name: 'SQLAlchemy', url: 'https://www.sqlalchemy.org', licence: 'MIT' },
  { name: 'SQLite', url: 'https://sqlite.org', licence: 'Public Domain' },
  { name: 'IMAPClient', url: 'https://github.com/mjs/imapclient', licence: 'BSD-3' },
  { name: 'nh3', url: 'https://nh3.readthedocs.io', licence: 'MIT' },
  { name: 'py-vapid', url: 'https://github.com/mozilla-services/vapid', licence: 'MPL-2.0' },
  { name: 'http-ece', url: 'https://github.com/martinthomson/encrypted-content-encoding', licence: 'MIT' },
  { name: 'React', url: 'https://react.dev', licence: 'MIT' },
  { name: 'Vite', url: 'https://vite.dev', licence: 'MIT' },
  { name: 'Tailwind CSS', url: 'https://tailwindcss.com', licence: 'MIT' },
  { name: 'Tiptap', url: 'https://tiptap.dev', licence: 'MIT' },
  { name: 'Lucide', url: 'https://lucide.dev', licence: 'ISC' },
  { name: 'i18next', url: 'https://www.i18next.com', licence: 'MIT' },
  { name: 'Inter', url: 'https://github.com/rsms/inter', licence: 'OFL-1.1' },
]

export function UeberPage({ ich }: { ich: Ich | null }) {
  const { t, i18n } = useTranslation()
  const [daten, setDaten] = useState<Auskunft | null>(null)
  const [fehler, setFehler] = useState<string | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const wasNeu = useWasNeu(ich?.version, i18n.language)

  const laden = useCallback(() => {
    api
      .holen<Auskunft>('/api/ueber')
      .then((a) => {
        setDaten(a)
        setFehler(null)
      })
      .catch((e: unknown) => setFehler(servermeldung(e)))
  }, [])
  useEffect(laden, [laden])

  async function jetztPruefen() {
    setLaeuft(true)
    try {
      setDaten(await api.senden<Auskunft>('/api/ueber/pruefen', {}))
      setFehler(null)
    } catch (e) {
      setFehler(servermeldung(e))
    } finally {
      setLaeuft(false)
    }
  }

  async function schalten(an: boolean) {
    if (daten) setDaten({ ...daten, update_pruefen: an })
    try {
      setDaten(await api.aendern<Auskunft>('/api/ueber/pruefen', { update_pruefen: an }))
    } catch (e) {
      setFehler(servermeldung(e))
      laden()
    }
  }

  if (!daten) return fehler ? <Notice tone="danger">{fehler}</Notice> : null
  return (
    <AboutPage
      app="nexmail"
      logo={appPfad('/favicon.svg?v=2')}
      tagline={t('ueber.untertitel')}
      version={daten.version}
      licence={{ name: daten.lizenz, href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
      source={daten.repo_adresse}
      releases={`${daten.repo_adresse}/releases`}
      project={daten.projektseite && daten.projektseite !== daten.repo_adresse ? daten.projektseite : null}
      whatsNew={wasNeu}
      updates={{
        checkDaily: daten.update_pruefen,
        checked: daten.geprueft,
        latest: daten.neueste,
        newer: daten.neuer_da,
        checkedAt: daten.geprueft_am ? new Date(daten.geprueft_am).toLocaleString(i18n.language) : null,
        releaseUrl: daten.release_adresse,
      }}
      operator={Boolean(ich?.ist_betreiber)}
      onDaily={(an) => void schalten(an)}
      onCheck={() => void jetztPruefen()}
      checking={laeuft}
      builtWith={BAUSTEINE}
      problem={fehler}
      texts={{ updatesWhatGoesOut: t('ueber.was_hinausgeht') }}
    />
  )
}
