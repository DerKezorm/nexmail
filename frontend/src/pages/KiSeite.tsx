/* Alles zur KI, seit dem Modul ki 0.1.0 aus dessen Bereichen (Bauplan „Einstellungen" E61, Entwurf KI-Anbieter):
 *
 * - **Server › KI-Anbieter** (`KiAnbieter`, nur Betreiber): `AiProviderArea` mit „KI-Dienst“, „Wer KI nutzen darf“
 *   (Hauptschalter „KI auf diesem Server erlaubt“, ab Werk zu; „Einer für alle“ oder „Jedes Konto selbst“; Rechner im
 *   eigenen Netz) und „Grenzen“; dazu nexmails eigene Karte „Eingegangene Post“ (der zweite Riegel des Betreibers).
 * - **Mein Konto › KI** (`KiSeite`): `AiAccountArea` mit „KI“ (KI für mich, wohin der Text geht), „Eigener Zugang“ (nur
 *   im Weg „Jedes Konto selbst“), „Was ging hinaus“; dazu nexmails eigene Karte „Eingegangene Post“ (der Haken der
 *   Person).
 *
 * Die alten Wege (`/api/ki`, `/api/ki/erlaubt`, `/api/ki/fremde-post`, `/api/ki/vorgaenge`) bleiben für alles, was sie
 * noch ruft; die Seite nutzt `/api/server/ai` und `/api/me/ai` des Moduls, die Haken für eingegangene Post die alten.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, modulAnfrage } from '../api/client'
import { zeitpunkt } from '../lib/format'
import { servermeldung } from '../lib/servermeldung'
import { AiAccountArea, AiProviderArea } from '../vendor/nexki'
import { Card, CheckboxRow, Notice } from '../vendor/nexui'

/** Ein Haken über einen der alten Wege, mit Fehlerzeile. */
function Haken({
  lesen,
  schreiben,
  titel,
  hinweis,
  testId,
}: {
  lesen: () => Promise<boolean>
  schreiben: (an: boolean) => Promise<boolean>
  titel: string
  hinweis: string
  testId: string
}) {
  const { t } = useTranslation()
  const [an, setAn] = useState<boolean | null>(null)
  const [fehler, setFehler] = useState('')
  useEffect(() => {
    lesen().then(setAn, () => setAn(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  async function umlegen(neu: boolean) {
    setFehler('')
    try {
      setAn(await schreiben(neu))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }
  return (
    <>
      <CheckboxRow label={titel} hint={hinweis} checked={an ?? false} disabled={an === null} onChange={(neu) => void umlegen(neu)} testId={testId} />
      {fehler && <Notice tone="danger">{fehler}</Notice>}
    </>
  )
}

/** Die Wörter der Aufträge für „Was ging hinaus“. */
function useAuftraege(): Record<string, string> {
  const { t } = useTranslation()
  return {
    rechtschreibung: t('ki.rechtschreibung'),
    uebersetzen: t('ki.uebersetzen'),
    umformulieren: t('ki.umformulieren'),
    zusammenfassen: t('ki.zusammenfassen'),
    frage: t('ki.frage'),
    antworten: t('ki.antworten'),
  }
}

/** Server › KI-Anbieter (nur Betreiber). */
export function KiAnbieter(_: { ichNeuLaden?: () => void }) {
  const { t, i18n } = useTranslation()
  return (
    <AiProviderArea request={modulAnfrage} app="nexmail" language={i18n.language}>
      <Card id="ai-received" icon="Mail" title={t('ki.fremde_post')} subtitle={t('verwaltung.ki_karte_text')}>
        <Haken
          lesen={async () => (await api.holen<{ erlaubt: boolean }>('/api/ki/fremde-post')).erlaubt}
          schreiben={async (an) => (await api.aendern<{ erlaubt: boolean }>('/api/ki/fremde-post', { erlaubt: an })).erlaubt}
          titel={t('verwaltung.ki_fremde_post')}
          hinweis={t('verwaltung.ki_fremde_post_hinweis')}
          testId="ki-fremde-post"
        />
      </Card>
    </AiProviderArea>
  )
}

/** Mein Konto › KI. */
export function KiSeite(_: { ichNeuLaden?: () => void }) {
  const { t, i18n } = useTranslation()
  const auftraege = useAuftraege()
  return (
    <AiAccountArea
      request={modulAnfrage}
      app="nexmail"
      language={i18n.language}
      tasks={auftraege}
      when={(iso, sprache) => zeitpunkt(iso, sprache)}
    >
      <Card id="ai-received-mine" icon="Mail" title={t('ki.fremde_post')} subtitle={t('ki.fremde_post_hinweis')}>
        <Haken
          lesen={async () => (await api.holen<{ fremde_post: boolean }>('/api/ki')).fremde_post}
          schreiben={async (an) => (await api.aendern<{ fremde_post: boolean }>('/api/ki', { fremde_post: an })).fremde_post}
          titel={t('ki.fremde_post_schalter')}
          hinweis={t('ki.fremde_post_gesperrt')}
          testId="ki-fremde-post-mein"
        />
      </Card>
    </AiAccountArea>
  )
}
