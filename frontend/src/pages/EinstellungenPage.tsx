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
import { Inbox, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Badge, Button, EmptyState, IconButton, Tabs } from '../ds'
import type { Ich } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Darstellung } from './Darstellung'
import { KontoFormular } from './KontoFormular'
import { Sicherheit } from './Sicherheit'
import { Regeln } from './Regeln'
import { Signaturen } from './Signaturen'
import { PUNKT_KLASSE } from '../lib/farben'
import { api } from '../api/client'
import type { KontoZeile } from '../api/client'

export type Reiter = 'postfaecher' | 'regeln' | 'signaturen' | 'sicherheit' | 'darstellung'

interface Props {
  reiter: Reiter
  aufReiter: (r: Reiter) => void
  formularOffen: boolean
  aufFormular: (offen: boolean) => void
  /** Für den Reiter „Sicherheit": Zweiter Faktor und übrige Codes. */
  ich: Ich | null
  ichNeuLaden?: () => void
}

export function EinstellungenPage({
  reiter,
  aufReiter,
  formularOffen,
  aufFormular,
  ich,
  ichNeuLaden,
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
            { id: 'sicherheit', label: t('einstellungen.sicherheit') },
            { id: 'darstellung', label: t('einstellungen.darstellung') },
          ]}
        />

        <div className="pt-5">
          {reiter === 'postfaecher' ? (
            formularOffen ? (
              <KontoFormular
                key={bearbeitet?.id ?? 'neu'}
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
                }}
              />
            ) : (
              <Postfachliste
                konten={konten}
                aufHinzufuegen={() => {
                  setBearbeitet(null)
                  aufFormular(true)
                }}
                aufBearbeiten={(k) => {
                  setBearbeitet(k)
                  aufFormular(true)
                }}
                aufNeuLaden={laden}
              />
            )
          ) : reiter === 'regeln' ? (
            <Regeln />
          ) : reiter === 'signaturen' ? (
            <Signaturen />
          ) : reiter === 'sicherheit' ? (
            <Sicherheit ich={ich} ichNeuLaden={ichNeuLaden} />
          ) : (
            // Alle Reiter sind gebaut — hier gibt es keinen Rest mehr.
            <Darstellung />
          )}
        </div>
      </div>
    </div>
  )
}

interface ListenProps {
  konten: KontoZeile[] | null
  aufHinzufuegen: () => void
  aufBearbeiten: (konto: KontoZeile) => void
  aufNeuLaden: () => void
}

function Postfachliste({ konten, aufHinzufuegen, aufBearbeiten, aufNeuLaden }: ListenProps) {
  const { t, i18n } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [entfernt, setEntfernt] = useState<string | null>(null)

  if (konten === null) {
    return <div className="h-24" />
  }

  if (konten.length === 0) {
    return (
      <EmptyState
        icon={<Inbox />}
        title={t('konto.kein_postfach')}
        description={t('konto.kein_postfach_text')}
        action={
          <Button variant="primary" iconLeft={<Plus className="size-4" />} onClick={aufHinzufuegen}>
            {t('konto.hinzufuegen')}
          </Button>
        }
      />
    )
  }

  async function entfernen(konto: KontoZeile) {
    const ja = await fragen({
      titel: t('konto.entfernen'),
      text: t('konto.entfernen_sicher', { name: konto.anzeigename }),
      knopf: t('konto.entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    setEntfernt(konto.id)
    try {
      await api.loeschen(`/api/konten/${konto.id}`)
      aufNeuLaden()
    } finally {
      setEntfernt(null)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex list-none flex-col gap-2 p-0">
        {konten.map((k) => (
          <li
            key={k.id}
            className="flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
          >
            <span
              aria-hidden
              className={`size-3 shrink-0 rounded-full ${PUNKT_KLASSE[k.farbe as 1 | 2 | 3 | 4 | 5 | 6]}`}
            />
            <div className="min-w-0 flex-1">
              {/* ⚠️ **Die Schlagworte gehören neben den Namen, nicht unter
                  die Serverzeile.** Wer hier steht, will wissen, welches
                  Postfach zu welcher Welt gehört — das ist eine Eigenschaft
                  des Postfachs, keine Fußnote zur Technik. */}
              <div className="mb-0 flex min-w-0 items-center gap-2">
                <p className="mb-0 truncate text-sm font-medium text-fg-1">{k.anzeigename}</p>
                {(k.tags ?? []).map((w) => (
                  <span
                    key={w}
                    className="shrink-0 rounded-pill bg-accent-soft px-2 py-0.5 text-[11px] text-accent-text"
                  >
                    {w}
                  </span>
                ))}
              </div>
              <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{k.adresse}</p>
              <p className="mb-0 truncate text-[11px] text-fg-4">
                {k.imap_server} · {k.anzahl_ordner}{' '}
                {t('konto.ordner_gefunden', { count: k.anzahl_ordner }).replace(/^\d+\s/, '')}
                {' · '}
                {k.zuletzt_geprueft
                  ? t('konto.geprueft_am', {
                      wann: new Date(k.zuletzt_geprueft).toLocaleString(i18n.language, {
                        dateStyle: 'short',
                        timeStyle: 'short',
                      }),
                    })
                  : t('konto.nie_geprueft')}
              </p>
            </div>

            {k.letzter_fehler ? (
              <Badge tone="danger" dot>
                {k.letzter_fehler.slice(0, 40)}
              </Badge>
            ) : (
              <Badge tone="success" dot>
                {t('einstellungen.aktiv')}
              </Badge>
            )}

            <IconButton
              icon={<Pencil />}
              label={t('einstellungen.bearbeiten')}
              size="sm"
              onClick={() => aufBearbeiten(k)}
            />
            <IconButton
              icon={<Trash2 />}
              label={t('einstellungen.entfernen')}
              size="sm"
              disabled={entfernt === k.id}
              onClick={() => void entfernen(k)}
            />
          </li>
        ))}
      </ul>

      <div className="flex gap-2">
        <Button iconLeft={<Plus className="size-4" />} onClick={aufHinzufuegen}>
          {t('konto.hinzufuegen')}
        </Button>
        <Button variant="ghost" iconLeft={<RefreshCw className="size-4" />} onClick={aufNeuLaden}>
          {t('aktion.aktualisieren')}
        </Button>
      </div>
      {nachfrage}
    </div>
  )
}
