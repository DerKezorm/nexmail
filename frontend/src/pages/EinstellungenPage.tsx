/* Die Einstellungen als eigene Seite mit Reitern.
 *
 * Eigene Seite und kein Fenster: Das Konto-Formular trägt zwei Serverblöcke
 * und einen Verbindungstest — in einem Fenster über der Mail-Ansicht wäre das
 * ein Guckloch.
 *
 * Die Postfächer kommen ab Stufe 1 vom Server. Regeln, Signaturen, Sicherheit
 * und Darstellung stehen als Reiter schon da, damit die Gliederung beurteilbar
 * ist.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw } from 'lucide-react'
import { Button, Dialog, Tabs } from '../ds'
import type { Ich } from '../api/client'
import { Postfachkacheln } from '../components/Postfachkacheln'
import { PostfachHinzufuegen } from '../components/PostfachHinzufuegen'
import { Benachrichtigungen } from './Benachrichtigungen'
import { Darstellung } from './Darstellung'
import { KontoFormular } from './KontoFormular'
import { Schlagworte } from './Schlagworte'
import { KiDienst } from './KiDienst'
import { Sicherheit } from './Sicherheit'
import { Regeln } from './Regeln'
import { Abwesenheit } from './Abwesenheit'
import { Signaturen } from './Signaturen'
import { Textvorlagen } from './Textvorlagen'
import { api } from '../api/client'
import type { KontoZeile } from '../api/client'

export type Reiter =
  | 'postfaecher'
  | 'regeln'
  | 'signaturen'
  | 'abwesenheit'
  | 'schlagworte'
  | 'sicherheit'
  | 'benachrichtigungen'
  | 'ki'
  | 'darstellung'

interface Props {
  reiter: Reiter
  aufReiter: (r: Reiter) => void
  formularOffen: boolean
  aufFormular: (offen: boolean) => void
  /** Das Fenster hinter der (+)-Kachel. Es steht in `App`, weil auch die
   *  Ordnerspalte dorthin führt („Postfach hinzufügen"). */
  wahlOffen: boolean
  aufWahl: (offen: boolean) => void
  /** Für den Reiter „Sicherheit": Zweiter Faktor und übrige Codes. */
  ich: Ich | null
  ichNeuLaden?: () => void
  /** Nach Anlegen/AEndern/Entfernen: App-weite Kontenliste nachziehen (Banner!). */
  aufKontenGeaendert?: () => void
  /** Nach jeder AEnderung im Reiter Schlagworte: Marken und Menues der
   *  Mail-Ansicht nachziehen — was ich aendere, muss ich auch sehen. */
  aufSchlagworteGeaendert?: () => void
}

export function EinstellungenPage({
  reiter,
  aufReiter,
  formularOffen,
  aufFormular,
  wahlOffen,
  aufWahl,
  ich,
  ichNeuLaden,
  aufKontenGeaendert,
  aufSchlagworteGeaendert,
}: Props) {
  // ⚠️ Bearbeiten und Anlegen benutzen dasselbe Formular. Getrennt zu
  // pflegen hieße zwei Stellen, an denen ein Feld fehlen kann.
  const [bearbeitet, setBearbeitet] = useState<KontoZeile | null>(null)
  const { t } = useTranslation()
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

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas">
      <div className="mx-auto w-full max-w-[900px] px-6 py-6">
        <h1 className="mb-4 font-display text-[24px] font-medium text-fg-1">
          {t('einstellungen.titel')}
        </h1>

        <Tabs
          activeId={reiter}
          onSelect={(id) => aufReiter(id as Reiter)}
          tabs={[
            {
              id: 'postfaecher',
              label: t('einstellungen.postfaecher'),
              count: konten?.length ?? 0,
            },
            { id: 'regeln', label: t('einstellungen.regeln') },
            { id: 'signaturen', label: t('einstellungen.signaturen') },
            { id: 'abwesenheit', label: t('einstellungen.abwesenheit') },
            { id: 'schlagworte', label: t('einstellungen.schlagworte') },
            { id: 'sicherheit', label: t('einstellungen.sicherheit') },
            { id: 'benachrichtigungen', label: t('einstellungen.benachrichtigungen') },
            { id: 'ki', label: t('einstellungen.ki') },
            { id: 'darstellung', label: t('einstellungen.darstellung') },
          ]}
        />

        <div className="pt-5">
          {reiter === 'postfaecher' ? (
            /* ⚠️ **Die Kacheln bleiben stehen, auch wenn ein Formular offen
               ist.** Vorher tauschte der Reiter seinen ganzen Inhalt aus; wer
               ein Postfach anlegte, sah den Bestand nicht mehr und danach
               eine Liste, von der er nicht wusste, ob sie neu geladen war. */
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
          ) : reiter === 'regeln' ? (
            <Regeln />
          ) : reiter === 'abwesenheit' ? (
            <Abwesenheit />
          ) : reiter === 'signaturen' ? (
            /* Die Textvorlagen wohnen im selben Reiter, als eigener Abschnitt
               darunter — beides sind Textbausteine für das Schreiben. */
            <div className="flex flex-col gap-6">
              <Signaturen />
              <section className="flex flex-col gap-4 border-t border-line-subtle pt-5">
                <div>
                  <h2 className="mb-1 text-[13px] font-semibold text-fg-1">
                    {t('textvorlagen.titel')}
                  </h2>
                  <p className="mb-0 text-[12px] text-fg-3">{t('textvorlagen.hinweis')}</p>
                </div>
                <Textvorlagen />
              </section>
            </div>
          ) : reiter === 'schlagworte' ? (
            <Schlagworte aufGeaendert={aufSchlagworteGeaendert} />
          ) : reiter === 'sicherheit' ? (
            <Sicherheit ich={ich} ichNeuLaden={ichNeuLaden} />
          ) : reiter === 'ki' ? (
            <KiDienst />
          ) : reiter === 'benachrichtigungen' ? (
            <Benachrichtigungen />
          ) : (
            // Alle Reiter sind gebaut — hier gibt es keinen Rest mehr.
            <Darstellung />
          )}
        </div>
      </div>

      {/* ⚠️ **Ein Fenster, nicht eine zweite Seite.** Anlegen und Bearbeiten
          gehen durch dieselbe Maske; sie einmal als Seite und einmal als
          Fenster zu zeigen wären zwei Anwendungen. */}
      <Dialog
        open={formularOffen}
        width={720}
        title={bearbeitet ? t('konto.bearbeiten_titel') : t('konto.hinzufuegen')}
        onClose={() => {
          aufFormular(false)
          setBearbeitet(null)
        }}
      >
        <KontoFormular
          key={bearbeitet?.id ?? 'neu'}
          imFenster
          naechsteFarbe={naechste}
          bestehend={bearbeitet}
          /* Was schon vergeben ist, wird angeboten — sonst entstehen
             „Arbeit" und „arbeit" nebeneinander. */
          bekannteTags={[...new Set((konten ?? []).flatMap((k) => k.tags ?? []))]}
          aufAbbrechen={() => {
            aufFormular(false)
            setBearbeitet(null)
          }}
          aufAngelegt={() => {
            aufFormular(false)
            setBearbeitet(null)
            laden()
            aufKontenGeaendert?.()
          }}
        />
      </Dialog>

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
          <Button variant="ghost" iconLeft={<RefreshCw className="size-4" />} onClick={aufNeuLaden}>
            {t('aktion.aktualisieren')}
          </Button>
        </div>
      )}
    </div>
  )
}
