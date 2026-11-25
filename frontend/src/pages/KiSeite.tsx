/* Alles zur KI, nach dem Bauplan „Einstellungen" auf zwei Bereiche verteilt:
 *
 * - **Server › KI-Anbieter** (`KiAnbieter`, nur Betreiber): die beiden Riegel des Betreibers, ob in dieser
 *   Installation überhaupt ein KI-Dienst benutzt werden darf und ob dabei auch eingegangene Post hinausgehen darf.
 * - **Mein Konto › KI** (`KiSeite`): der eigene Zugang und was nexmail damit tut (`KiDienst`).
 *
 * ⚠️ **Ein Riegel, der entscheidet, ob Mailtext das Haus verlassen darf, muss dort stehen, wo man ihn vermutet.** Am
 * 04.09.2026 lag er unten unter dem Postausgang und wurde nicht gefunden. Seit dem Bauplan steht er dort, wo jede
 * nex-App ihn hat: unter Server, Bereich „KI-Anbieter".
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { Card, CheckboxRow, Notice } from '../vendor/nexui'
import { servermeldung } from '../lib/servermeldung'
import { KiDienst } from './KiDienst'

/** Ob in dieser Installation überhaupt ein KI-Dienst benutzt werden darf.
 *
 * ⚠️ **Ab Werk zu.** Ohne diesen Riegel entscheidet jeder Benutzer für sich,
 * ob Text aus seinen Mails an einen fremden Dienst geht — und der Betreiber,
 * der dafür verantwortlich ist, kann es weder sehen noch verbieten. Für einen
 * Haushalt wäre das richtig, für jede Organisation das Gegenteil.
 *
 * ⚠️ **Zusperren löscht keinen Zugang.** Die Schlüssel der Benutzer bleiben
 * stehen; benutzt werden sie nur nicht. Sonst kostete ein versehentliches
 * Zumachen alle Zugänge.
 */
function KiRiegel({
  adresse,
  titel,
  hinweis,
  aufGeaendert,
  testId,
}: {
  adresse: string
  titel: string
  hinweis: string
  aufGeaendert: () => void
  testId?: string
}) {
  const { t } = useTranslation()
  const [erlaubt, setErlaubt] = useState<boolean | null>(null)
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    void api
      .holen<{ erlaubt: boolean }>(adresse)
      .then((r) => setErlaubt(r.erlaubt))
      .catch(() => undefined)
  }, [adresse])

  async function umlegen(an: boolean) {
    setFehler('')
    try {
      const r = await api.aendern<{ erlaubt: boolean }>(adresse, { erlaubt: an })
      setErlaubt(r.erlaubt)
      /* ⚠️ Der Teil darunter hängt daran: Aufsperren muss den eigenen Zugang
         sofort zeigen, Zusperren ihn sofort verstecken. Sonst sieht der
         Betreiber seinen eigenen Riegel erst nach F5 wirken — dieselbe
         Prüffrage wie „Was ich ändere, muss ich auch sehen". */
      aufGeaendert()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  return (
    <>
      <CheckboxRow
        label={titel}
        hint={hinweis}
        checked={erlaubt ?? false}
        disabled={erlaubt === null}
        onChange={(an) => void umlegen(an)}
        testId={testId}
      />
      {fehler && <Notice tone="danger">{fehler}</Notice>}
    </>
  )
}

/** Server › KI-Anbieter: die Riegel des Betreibers. */
export function KiAnbieter({ ichNeuLaden }: { ichNeuLaden?: () => void }) {
  const { t } = useTranslation()
  return (
    <Card id="ai-provider" icon="Sparkles" title={t('einstellungen.bereiche.ai-provider.titel')} subtitle={t('verwaltung.ki_karte_text')}>
      <KiRiegel
        adresse="/api/ki/erlaubt"
        titel={t('verwaltung.ki')}
        hinweis={t('verwaltung.ki_hinweis')}
        aufGeaendert={() => ichNeuLaden?.()}
        testId="ki-erlaubt"
      />
      <KiRiegel
        adresse="/api/ki/fremde-post"
        titel={t('verwaltung.ki_fremde_post')}
        hinweis={t('verwaltung.ki_fremde_post_hinweis')}
        aufGeaendert={() => ichNeuLaden?.()}
        testId="ki-fremde-post"
      />
    </Card>
  )
}

/** Mein Konto › KI: der eigene Zugang. Die Riegel des Betreibers stehen unter Server › KI-Anbieter. */
export function KiSeite({ ichNeuLaden }: { ichNeuLaden?: () => void }) {
  return <KiDienst ichNeuLaden={ichNeuLaden} />
}
