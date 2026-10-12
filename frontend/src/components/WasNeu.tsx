/* „Was ist neu“: ein Banner unter der Kopfleiste nach einem Update, für jedes
 * Konto, und das Fenster mit dem Text der Version. Nach dem Vorbild von
 * nexdiary.
 *
 * ⚠️ **Gesehen merkt sich der Server, je Konto** (`benutzer.wasneu_gesehen`),
 * nicht der Browser. Sonst käme der Banner auf jedem Gerät noch einmal, und
 * nach dem Leeren der Browserdaten wieder.
 *
 * ⚠️ **Wegklicken wartet nicht auf den Server.** Der Banner ist sofort weg,
 * die Meldung geht hinterher. Scheitert sie, kommt er beim nächsten Laden
 * wieder; das ist der harmlose Fehler. In nexdeck wartete jeder Ausgang auf
 * die Antwort, und ohne Server ließ sich das Fenster nicht schließen.
 */
import { Sparkles, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, Dialog, IconButton } from '../ds'
import { api } from '../api/client'
import type { Ich } from '../api/client'
import type { WasNeuEintrag } from '../lib/wasneu'

export function WasNeuFenster({
  version,
  eintrag,
  onClose,
}: {
  version: string
  eintrag: WasNeuEintrag
  onClose: () => void
}) {
  const { t } = useTranslation()
  return (
    <Dialog
      open
      title={t('wasneu.titel', { version })}
      onClose={onClose}
      width={600}
      footer={<Button onClick={onClose}>{t('wasneu.verstanden')}</Button>}
    >
      <div data-testid="wasneu-fenster" className="flex flex-col gap-4">
        <p className="text-[13.5px] text-fg-2">{eintrag.lead}</p>
        <ul className="flex flex-col gap-3.5">
          {eintrag.sections.map((a) => (
            <li key={a.title}>
              <h3 className="text-[13.5px] font-semibold text-fg-1">{a.title}</h3>
              <p className="text-[13px] text-fg-2">{a.body}</p>
              <p className="mt-0.5 text-[12px] text-fg-3">
                <span className="font-semibold">{t('wasneu.wo')}</span> {a.where}
              </p>
            </li>
          ))}
        </ul>
        {eintrag.small.length > 0 && (
          <section>
            <h3 className="text-[11px] font-semibold tracking-wide text-fg-3 uppercase">
              {eintrag.smallTitle}
            </h3>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] text-fg-2">
              {eintrag.small.map((zeile) => (
                <li key={zeile}>{zeile}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Dialog>
  )
}

/** Unter der Kopfleiste, solange die laufende Version einen Text hat, den
 *  dieses Konto weder gelesen noch weggeklickt hat. */
export function WasNeuBanner({
  ich,
  eintrag,
  weg,
  aufZeigen,
  aufWeg,
}: {
  ich: Ich | null
  eintrag: WasNeuEintrag | null
  /** In dieser Sitzung schon weggeklickt oder gelesen. */
  weg: boolean
  aufZeigen: () => void
  aufWeg: () => void
}) {
  const { t } = useTranslation()
  if (!ich || !eintrag || weg || ich.wasneu_gesehen === ich.version) return null
  return (
    <div
      role="status"
      data-testid="wasneu-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-accent-line bg-accent-soft px-4 py-1.5 text-[13px] text-fg-1"
    >
      <Sparkles className="size-4 shrink-0 text-accent-text" aria-hidden />
      <span className="min-w-0 flex-1 font-medium">
        {t('wasneu.banner', { version: ich.version })}
      </span>
      <Button size="sm" onClick={aufZeigen}>
        {t('wasneu.zeigen')}
      </Button>
      <IconButton size="sm" icon={<X className="size-4" />} label={t('wasneu.wegklicken')} onClick={aufWeg} />
    </div>
  )
}

/** Den Stand „gesehen“ beim Server ablegen. Fehler bleiben hier: Dann kommt
 *  der Banner beim nächsten Laden eben wieder. */
export function gesehenMelden(nachher?: () => void): void {
  void api.senden('/api/auth/ich/wasneu-gesehen', {}).then(
    () => nachher?.(),
    () => undefined,
  )
}
