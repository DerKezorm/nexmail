/* Über nexmail: Fassung, Herkunft, Lizenz, Update-Stand.
 *
 * ⚠️ **Der Schalter für die Update-Nachfrage steht hier**, nicht in den
 * Einstellungen — auf der Seite, auf der auch das Ergebnis erscheint. Wer
 * wissen will, was da nach draußen geht, schaut dorthin, wo es ankommt.
 *
 * ⚠️ **Und die Seite sagt, dass etwas hinausgeht.** nexmail liefert sogar die
 * Schriften mit, damit es beim Öffnen niemanden anfunkt; eine tägliche
 * Nachfrage bei GitHub ist die einzige Ausnahme davon. Eine Ausnahme, die man
 * verschweigt, ist ein gebrochenes Versprechen.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { Badge, Button, Switch } from '../ds'
import { Logo } from '../components/Logo'
import { servermeldung } from '../lib/servermeldung'

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

/** Ein Verweis nach außen — immer in einem neuen Reiter. */
function Aussen({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-accent-text underline decoration-accent/40 underline-offset-4 transition-colors hover:decoration-accent"
    >
      {children}
    </a>
  )
}

function Zeile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line/60 py-2.5 last:border-b-0">
      <dt className="text-[13px] text-fg-3">{label}</dt>
      <dd className="text-[13px] font-medium text-fg-1">{children}</dd>
    </div>
  )
}

export function UeberPage() {
  const { t, i18n } = useTranslation()
  const [daten, setDaten] = useState<Auskunft | null>(null)
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  const laden = useCallback(() => {
    api
      .holen<Auskunft>('/api/ueber')
      .then((a) => {
        setDaten(a)
        setFehler('')
      })
      .catch((e: unknown) => setFehler(servermeldung(e)))
  }, [])

  useEffect(laden, [laden])

  async function jetztPruefen() {
    setLaeuft(true)
    try {
      setDaten(await api.senden<Auskunft>('/api/ueber/pruefen', {}))
      setFehler('')
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

  /* ⚠️ Die Bausteine hier sind bewusst dieselben wie überall. Eine
     „Über"-Seite mit eigenem Aussehen ist der klassische Ort, an dem ein
     Design-System zum ersten Mal verlassen wird. */
  const bausteine = [
    { name: 'FastAPI', url: 'https://fastapi.tiangolo.com', lizenz: 'MIT' },
    { name: 'SQLAlchemy', url: 'https://www.sqlalchemy.org', lizenz: 'MIT' },
    { name: 'SQLite', url: 'https://sqlite.org', lizenz: 'Public Domain' },
    { name: 'IMAPClient', url: 'https://github.com/mjs/imapclient', lizenz: 'BSD-3' },
    { name: 'nh3', url: 'https://nh3.readthedocs.io', lizenz: 'MIT' },
    { name: 'py-vapid', url: 'https://github.com/mozilla-services/vapid', lizenz: 'MPL-2.0' },
    {
      name: 'http-ece',
      url: 'https://github.com/martinthomson/encrypted-content-encoding',
      lizenz: 'MIT',
    },
    { name: 'React', url: 'https://react.dev', lizenz: 'MIT' },
    { name: 'Vite', url: 'https://vite.dev', lizenz: 'MIT' },
    { name: 'Tailwind CSS', url: 'https://tailwindcss.com', lizenz: 'MIT' },
    { name: 'Tiptap', url: 'https://tiptap.dev', lizenz: 'MIT' },
    { name: 'lucide', url: 'https://lucide.dev', lizenz: 'ISC' },
    { name: 'i18next', url: 'https://www.i18next.com', lizenz: 'MIT' },
  ]

  const schriften = [
    { name: 'IBM Plex Sans', url: 'https://github.com/IBM/plex' },
    { name: 'Space Grotesk', url: 'https://github.com/floriankarsten/space-grotesk' },
    { name: 'JetBrains Mono', url: 'https://github.com/JetBrains/JetBrainsMono' },
  ]

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas">
      <div className="mx-auto w-full max-w-[720px] px-6 py-8">
        <div className="flex items-center gap-3">
          <Logo className="h-9 w-9" />
          <div>
            <h1 className="font-display text-[22px] font-medium text-fg-1">nexmail</h1>
            <p className="text-[13px] text-fg-3">{t('ueber.untertitel')}</p>
          </div>
        </div>

        {fehler && (
          <p className="mt-4 rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[13px] text-fg-1">
            {fehler}
          </p>
        )}

        {daten && (
          <>
            <dl className="mt-6 rounded-xl border border-line bg-surface-1 px-4 py-2">
              <Zeile label={t('ueber.fassung')}>
                <span className="flex items-center gap-2">
                  {daten.version}
                  {daten.neuer_da && (
                    <Badge tone="accent">{t('ueber.neu_da', { version: daten.neueste })}</Badge>
                  )}
                </span>
              </Zeile>
              <Zeile label={t('ueber.lizenz')}>
                <Aussen href="https://www.gnu.org/licenses/agpl-3.0.html">{daten.lizenz}</Aussen>
              </Zeile>
              <Zeile label={t('ueber.quelltext')}>
                <Aussen href={daten.repo_adresse}>github.com/DerKezorm/nexmail</Aussen>
              </Zeile>
              <Zeile label={t('ueber.projektseite')}>
                <Aussen href={daten.projektseite}>
                  {daten.projektseite.replace(/^https:\/\//, '')}
                </Aussen>
              </Zeile>
              <Zeile label={t('ueber.fehler_melden')}>
                <Aussen href={`${daten.repo_adresse}/issues/new`}>
                  {t('ueber.fehler_melden_link')}
                </Aussen>
              </Zeile>
            </dl>

            {/* --- Update-Nachfrage ------------------------------------- */}
            <section className="mt-5 rounded-xl border border-line bg-surface-1 p-4">
              <Switch
                checked={daten.update_pruefen}
                onCheckedChange={(an) => void schalten(an)}
                label={t('ueber.taeglich_nachsehen')}
                description={t('ueber.taeglich_nachsehen_text')}
              />

              <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                <Button variant="ghost" onClick={() => void jetztPruefen()} loading={laeuft}>
                  {t('ueber.jetzt_pruefen')}
                </Button>

                {daten.geprueft && (
                  <span className="text-[12px] text-fg-3">
                    {daten.neuer_da ? (
                      <>
                        {t('ueber.neu_da', { version: daten.neueste })} ·{' '}
                        <Aussen href={daten.release_adresse}>{t('ueber.zum_release')}</Aussen>
                      </>
                    ) : (
                      t('ueber.aktuell')
                    )}
                    {daten.geprueft_am && (
                      <span className="ml-2 text-fg-4">
                        {t('ueber.zuletzt_geprueft', {
                          wann: new Date(daten.geprueft_am).toLocaleString(i18n.language),
                        })}
                      </span>
                    )}
                  </span>
                )}
              </div>

              <p className="mt-3 text-[12px] leading-relaxed text-fg-3">
                ⚠️ {t('ueber.was_hinausgeht')}
              </p>
            </section>
          </>
        )}

        {/* --- Gebaut mit ---------------------------------------------- */}
        <section className="mt-5 rounded-xl border border-line bg-surface-1 p-4">
          <h2 className="text-[14px] font-medium text-fg-1">{t('ueber.gebaut_mit')}</h2>
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1.5 text-[13px]">
            {bausteine.map((b) => (
              <li key={b.name}>
                <Aussen href={b.url}>{b.name}</Aussen>
                <span className="ml-1 text-[11px] text-fg-4">({b.lizenz})</span>
              </li>
            ))}
          </ul>

          <h3 className="mt-4 text-[11px] font-medium tracking-wide text-fg-3 uppercase">
            {t('ueber.schriften')}
          </h3>
          <p className="mt-1 text-[12px] leading-relaxed text-fg-3">
            {t('ueber.schriften_text')}
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[13px]">
            {schriften.map((s) => (
              <li key={s.name}>
                <Aussen href={s.url}>{s.name}</Aussen>
                <span className="ml-1 text-[11px] text-fg-4">(OFL-1.1)</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
