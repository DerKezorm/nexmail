/* Textvorlagen — wiederkehrende Antworten für das Verfassen-Fenster.
 *
 * ⚠️ **Derselbe Editor wie beim Schreiben** — dieselbe Entscheidung wie bei
 * den Signaturen: Ein Baustein, der in einem anderen Feld entsteht als die
 * Mail, sieht in der Mail anders aus, und man merkt es erst beim Empfänger.
 *
 * Die Reihenfolge lässt sich ziehen (dasselbe Muster wie bei den Aufgaben) —
 * sie ist die Reihenfolge im Menü „Vorlage" des Verfassen-Fensters.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, GripVertical, Plus, Trash2 } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Button, EmptyState, IconButton, Input } from '../ds'
import { Editor } from '../components/Editor'

export interface TextvorlagenZeile {
  id: number
  name: string
  inhalt_html: string
  reihenfolge: number
}

function leer(): TextvorlagenZeile {
  return { id: 0, name: '', inhalt_html: '<p></p>', reihenfolge: 0 }
}

export function Textvorlagen() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  /* ⚠️ Drei Zustaende statt zwei: noch nicht geladen (null) · geladen ·
     ging nicht. Ein gescheiterter Abruf darf nicht wie „Noch keine
     Textvorlagen" aussehen — der Bestand bleibt stehen, und ein Knopf holt
     nach. Dasselbe Muster wie bei den Schlagworten nebenan. */
  const [liste, setListe] = useState<TextvorlagenZeile[] | null>(null)
  const [ladefehler, setLadefehler] = useState('')
  const [offen, setOffen] = useState<TextvorlagenZeile | null>(null)
  const [fehler, setFehler] = useState('')
  const [gezogen, setGezogen] = useState<number | null>(null)
  const [ueber, setUeber] = useState<number | null>(null)

  const laden = useCallback(async () => {
    try {
      setListe(await api.holen<TextvorlagenZeile[]>('/api/textvorlagen'))
      setLadefehler('')
    } catch {
      setLadefehler(t('textvorlagen.laden_ging_nicht'))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  /* Kennungen des Servers werden übersetzt — kein roher Text. */
  function uebersetzt(f: unknown): string {
    const detail = f instanceof ApiFehler ? f.detail : ''
    if (detail === 'textvorlage_name_vergeben') return t('textvorlagen.fehler_name_vergeben')
    if (detail === 'textvorlage_name_fehlt') return t('textvorlagen.fehler_name_fehlt')
    return t('anmeldung.fehler_allgemein')
  }

  async function mit<T>(tun: () => Promise<T>) {
    setFehler('')
    try {
      const ergebnis = await tun()
      await laden()
      return ergebnis
    } catch (f) {
      setFehler(uebersetzt(f))
      return null
    }
  }

  async function speichern(v: TextvorlagenZeile) {
    const nutzdaten = { name: v.name, inhalt_html: v.inhalt_html }
    const ergebnis = await mit(() =>
      v.id
        ? api.aendern<TextvorlagenZeile>(`/api/textvorlagen/${v.id}`, nutzdaten)
        : api.senden<TextvorlagenZeile>('/api/textvorlagen', nutzdaten),
    )
    if (ergebnis) setOffen(null)
  }

  async function ablegen(zielId: number) {
    if (liste === null || gezogen === null || gezogen === zielId) return
    const ohne = liste.filter((v) => v.id !== gezogen)
    const platz = ohne.findIndex((v) => v.id === zielId)
    const neu = [...ohne.slice(0, platz), liste.find((v) => v.id === gezogen)!, ...ohne.slice(platz)]
    // ⚠️ Erst zeichnen, dann schicken — eine Reihenfolge, die nach dem
    // Loslassen zurückspringt und dann sitzt, fühlt sich kaputt an.
    setListe(neu)
    setGezogen(null)
    setUeber(null)
    await mit(() => api.aendern('/api/textvorlagen/reihenfolge', { ids: neu.map((v) => v.id) }))
  }

  if (liste === null && !ladefehler) return <div className="h-24" />

  if (offen) {
    return (
      <div className="flex max-w-[720px] flex-col gap-4">
        <Input
          label={t('textvorlagen.name')}
          value={offen.name}
          onChange={(e) => setOffen({ ...offen, name: e.target.value })}
        />

        <div className="flex min-h-[220px] flex-col overflow-hidden rounded-lg border border-line bg-surface-1">
          <Editor
            inhalt={offen.inhalt_html}
            aufAendern={(html) => setOffen((alt) => (alt ? { ...alt, inhalt_html: html } : alt))}
            // ⚠️ Kein Bild in der Vorlage — dieselbe Entscheidung wie bei den
            // Signaturen: Es führe bei jedem Einfügen als Anhang mit.
            aufBild={async () => ''}
          />
        </div>

        {fehler && <p className="text-[13px] text-danger">{fehler}</p>}

        <div className="flex items-center gap-2">
          <Button variant="primary" onClick={() => void speichern(offen)}>
            {t('textvorlagen.speichern')}
          </Button>
          <Button variant="ghost" onClick={() => setOffen(null)}>
            {t('aktion.abbrechen')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {ladefehler && (
        <div
          role="alert"
          className="flex items-center gap-3 rounded-lg border border-danger bg-danger-soft px-4 py-2.5"
        >
          <span className="min-w-0 flex-1 text-[13px] text-fg-1">{ladefehler}</span>
          <Button size="sm" onClick={() => void laden()}>
            {t('stoerung.nochmal')}
          </Button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button variant="primary" iconLeft={<Plus className="size-4" />} onClick={() => setOffen(leer())}>
          {t('textvorlagen.neu')}
        </Button>
        <span className="flex-1" />
        {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
      </div>

      {/* ⚠️ „Noch keine Textvorlagen" erst, wenn wirklich geladen WURDE —
          ein Fehler darf nicht wie Leere aussehen. */}
      {liste !== null && liste.length === 0 && !ladefehler ? (
        <EmptyState
          icon={<FileText />}
          title={t('textvorlagen.leer')}
          description={t('textvorlagen.leer_text')}
        />
      ) : (
        <ul className="flex list-none flex-col gap-2 p-0">
          {(liste ?? []).map((v) => (
            <li
              key={v.id}
              draggable
              onDragStart={() => setGezogen(v.id)}
              onDragEnd={() => {
                setGezogen(null)
                setUeber(null)
              }}
              onDragOver={(e) => {
                e.preventDefault()
                setUeber(v.id)
              }}
              onDrop={() => void ablegen(v.id)}
              className={
                'flex items-center gap-3 rounded-lg border bg-surface-2 px-3 py-2.5 ' +
                'transition-colors duration-[var(--dur-fast)] ' +
                (ueber === v.id ? 'border-accent' : 'border-line')
              }
            >
              {/* ⚠️ Der Griff ist sichtbar, nicht geraten — dieselbe Regel
                  wie bei den Aufgaben. */}
              <span
                aria-hidden
                title={t('textvorlagen.ziehen')}
                className="shrink-0 cursor-grab text-fg-4"
              >
                <GripVertical className="size-4" />
              </span>
              <button type="button" onClick={() => setOffen(v)} className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[13px] font-medium text-fg-1">{v.name}</span>
                <span className="block truncate text-[12px] text-fg-3">
                  {v.inhalt_html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()}
                </span>
              </button>
              <IconButton
                icon={<Trash2 />}
                label={t('textvorlagen.entfernen')}
                size="sm"
                onClick={() =>
                  void (async () => {
                    const ja = await fragen({
                      titel: t('textvorlagen.entfernen'),
                      text: t('textvorlagen.entfernen_sicher', { name: v.name }),
                      knopf: t('textvorlagen.entfernen'),
                      gefaehrlich: true,
                    })
                    if (ja !== true) return
                    await mit(() => api.loeschen(`/api/textvorlagen/${v.id}`))
                  })()
                }
              />
            </li>
          ))}
        </ul>
      )}
      {nachfrage}
    </div>
  )
}
