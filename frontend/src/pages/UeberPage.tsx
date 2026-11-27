/* Über nexmail: die `AboutPage` des Bausatzes ui (Bauplan „Einstellungen", „Über"): Version mit „Version x ist
 * erschienen", „Was ist neu" (Modul wasneu 0.1.0: „Neu in nexmail x“ und „Frühere Versionen“), Lizenz, Quelltext, Veröffentlichungen, „Einen Fehler gefunden?", die Karte
 * „Aktualisierungen" und „Gebaut mit".
 *
 * Die Karte „Aktualisierungen" kommt seit dem Durchgang „Module" aus dem Modul updates 0.1.1 (`useUpdates`, Wege unter
 * `/api/about`): Sie steht nur für Betreiber da (U2, U15). Ein Mitglied sieht seine Version, sonst nichts, und seine Seite
 * fragt nur nach Version und Lizenz. Der Satz, was hinausgeht, kommt aus dem Modul (`whatGoesOut`): eine Frage an
 * GitHub, sonst ruft nexmail von sich aus niemanden an (Postfächer, Kalender und alles andere gehören zu etwas, das
 * jemand eingerichtet hat). Keine Projektseite, solange die Seiten abgeschaltet sind (U18).
 *
 * nexmail hat keine Glocke, aber gekoppelte Geräte (updates 0.1.3, U24): der Hinweis unter „Einmal am Tag nachsehen“
 * sagt, dass der Hintergrund nur nachsieht, solange ein Gerät eines Betreibers Hinweise auf neue Versionen will.
 */
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import type { Ich } from '../api/client'
import { appPfad } from '../lib/basis'
import { zeitpunkt } from '../lib/format'
import { serverAbruf } from '../lib/serverAbruf'
import { AboutPage, Notice, type BuiltWith } from '../vendor/nexui'
import { dailyHint, useUpdates, useUpdatesTexts, whatGoesOut } from '../vendor/nexupdates/updates'
import { useAboutWhatsNew } from '../vendor/nexwasneu/useWhatsNew'

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

const LOGO = appPfad('/favicon.svg?v=2')

export function UeberPage({ ich }: { ich: Ich | null }) {
  const { t, i18n } = useTranslation()
  const news = useAboutWhatsNew({ app: 'nexmail', logo: LOGO, fetcher: serverAbruf, language: i18n.language })
  const wann = useCallback((iso: string) => zeitpunkt(iso, i18n.language), [i18n.language])
  const stand = useUpdates({ fetcher: serverAbruf, operator: Boolean(ich?.ist_betreiber), when: wann, language: i18n.language })
  const worte = useUpdatesTexts(i18n.language)

  if (!stand.about) return stand.problem ? <Notice tone="danger">{stand.problem}</Notice> : null
  return (
    <>
      <AboutPage
        app="nexmail"
        logo={LOGO}
        tagline={t('ueber.untertitel')}
        version={stand.about.version}
        licence={{ name: stand.about.license, href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
        source={stand.about.repo_url}
        releases={stand.about.releases_url}
        project={stand.about.project_url || null}
        updates={stand.updates}
        showUpdates={stand.showUpdates}
        operator={Boolean(ich?.ist_betreiber)}
        onDaily={stand.onDaily}
        onCheck={stand.onCheck}
        checking={stand.checking}
        builtWith={BAUSTEINE}
        problem={stand.problem}
        texts={{
          updatesWhatGoesOut: whatGoesOut(worte, 'nexmail'),
          // updates 0.1.3 (U24): keine Glocke, aber Geräte; der Hinweis sagt, wann der Hintergrund nachsieht.
          updatesDailyHint: dailyHint(worte, { bell: false, devices: true }),
        }}
        {...news.about}
      />
      {news.window}
    </>
  )
}
