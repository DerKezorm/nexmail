/* Mein Konto › Verbindungen „Auf diesem Gerät installieren" (Bauplan „Einstellungen", Verbindungen 2, E6, E28). Die
 * Karte steht immer da: „Installieren", solange der Browser seine eigene Frage anbietet (`beforeinstallprompt`), sonst
 * ein kurzer Weg für diesen Browser (Safari auf iPhone und iPad: Teilen › Zum Home-Bildschirm; Safari auf dem Mac:
 * Ablage › Zum Dock hinzufügen; Firefox kann es nicht; sonst das Menü), und in der installierten App, dass sie es schon
 * ist. Wie nexnotes `pwa/InstallCard.tsx`. */
import { Info, Share } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Buttons, Card } from '../../vendor/nexui'

type Frage = Event & { prompt: () => Promise<void> }

let gemerkt: Frage | null = null
const hoerer = new Set<() => void>()
if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    gemerkt = e as Frage
    hoerer.forEach((h) => h())
  })
  window.addEventListener('appinstalled', () => {
    gemerkt = null
    hoerer.forEach((h) => h())
  })
}

export type Installweg = 'ios' | 'safari' | 'firefox' | 'other'

// eslint-disable-next-line react-refresh/only-export-components
export function installweg(agent = typeof navigator === 'undefined' ? '' : navigator.userAgent): Installweg {
  if (/iPhone|iPad|iPod/.test(agent) || (/Macintosh/.test(agent) && typeof navigator !== 'undefined' && navigator.maxTouchPoints > 1)) return 'ios'
  if (/Firefox\//.test(agent)) return 'firefox'
  if (/Macintosh/.test(agent) && /Safari\//.test(agent) && !/Chrome|Chromium|CriOS|Edg|OPR|Firefox/.test(agent)) return 'safari'
  return 'other'
}

function Weg({ testId, teilen, children }: { testId: string; teilen?: boolean; children: string }) {
  const Symbol = teilen ? Share : Info
  return (
    <p className="m-0 flex items-start gap-2 text-sm text-[var(--nexui-text)]" data-testid={testId}>
      <Symbol className="mt-0.5 h-4 w-4 shrink-0 text-[var(--nexui-accent-text)]" aria-hidden /> {children}
    </p>
  )
}

export function Installieren() {
  const { t } = useTranslation()
  const [frage, setFrage] = useState<Frage | null>(gemerkt)
  const [gefragt, setGefragt] = useState(false)
  useEffect(() => {
    const neu = () => setFrage(gemerkt)
    hoerer.add(neu)
    return () => {
      hoerer.delete(neu)
    }
  }, [])
  const installiert =
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(display-mode: standalone)').matches
  const weg = installweg()
  return (
    <Card id="install" icon="Download" title={t('pwa.install.title')} subtitle={t('pwa.install.text')}>
      {installiert && <Weg testId="install-done">{t('pwa.install.installed')}</Weg>}
      {!installiert && frage && (
        <Buttons>
          <Button
            kind="primary"
            icon="Download"
            onClick={() => {
              setGefragt(true)
              void frage.prompt()
              gemerkt = null
              setFrage(null)
            }}
            testId="install"
          >
            {t('pwa.install.button')}
          </Button>
        </Buttons>
      )}
      {!installiert && !frage && gefragt && <Weg testId="install-asked">{t('pwa.install.asked')}</Weg>}
      {!installiert && !frage && !gefragt && (
        <Weg testId={`install-${weg}`} teilen={weg === 'ios'}>
          {t(`pwa.install.${weg}`)}
        </Weg>
      )}
    </Card>
  )
}
