/* Signaturen — der Textbaustein unter der eigenen Post.
 *
 * ⚠️ **Derselbe Editor wie beim Schreiben.** Eine Signatur, die man in einem
 * anderen Feld baut als die Mail, sieht in der Mail anders aus — und man merkt
 * es erst beim Empfänger.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PenLine, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { EmptyState } from '../ds'
import { Button, CheckboxRow, Field, SelectField } from '../vendor/nexui'
import { Editor } from '../components/Editor'
import { servermeldung } from '../lib/servermeldung'

export interface SignaturZeile {
  id: number
  name: string
  konto_id: string
  html: string
  standard: boolean
}

interface KontoZeile {
  id: string
  adresse: string
}

function leer(): SignaturZeile {
  return { id: 0, name: '', konto_id: '', html: '<p></p>', standard: false }
}

export function Signaturen() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [liste, setListe] = useState<SignaturZeile[] | null>(null)
  const [konten, setKonten] = useState<KontoZeile[]>([])
  const [offen, setOffen] = useState<SignaturZeile | null>(null)
  const [fehler, setFehler] = useState('')

  const laden = useCallback(async () => {
    setListe(await api.holen<SignaturZeile[]>('/api/signaturen'))
  }, [])

  useEffect(() => {
    void laden().catch(() => setListe([]))
    void api.holen<KontoZeile[]>('/api/konten').then(setKonten).catch(() => setKonten([]))
  }, [laden])

  async function mit<T>(tun: () => Promise<T>) {
    setFehler('')
    try {
      const ergebnis = await tun()
      await laden()
      return ergebnis
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return null
    }
  }

  async function speichern(s: SignaturZeile) {
    const nutzdaten = { name: s.name, html: s.html, konto_id: s.konto_id, standard: s.standard }
    const ergebnis = await mit(() =>
      s.id
        ? api.aendern<SignaturZeile>(`/api/signaturen/${s.id}`, nutzdaten)
        : api.senden<SignaturZeile>('/api/signaturen', nutzdaten),
    )
    if (ergebnis) setOffen(null)
  }

  if (liste === null) return <div className="h-24" />

  if (offen) {
    return (
      <div className="flex max-w-[720px] flex-col gap-4">
        <Field label={t('signaturen.name')} value={offen.name} onChange={(e) => setOffen({ ...offen, name: e.target.value })} />
        <SelectField
          label={t('signaturen.postfach')}
          hints={[t('signaturen.postfach_hinweis')]}
          value={offen.konto_id}
          onChange={(e) => setOffen({ ...offen, konto_id: e.target.value })}
          options={[{ value: '', label: t('signaturen.alle_postfaecher') }, ...konten.map((k) => ({ value: k.id, label: k.adresse }))]}
        />

        <div className="flex min-h-[220px] flex-col overflow-hidden rounded-lg border border-line bg-surface-1">
          <Editor
            inhalt={offen.html}
            aufAendern={(html) => setOffen((alt) => (alt ? { ...alt, html } : alt))}
            // ⚠️ Kein Bild in der Signatur: Es fährt bei **jeder** Mail mit
            // und macht aus einem Zweizeiler ein Anhängsel von 200 kB.
            aufBild={async () => ''}
          />
        </div>

        <CheckboxRow checked={offen.standard} label={t('signaturen.standard')} hint={t('signaturen.standard_hinweis')} onChange={(an) => setOffen({ ...offen, standard: an })} />

        {fehler && <p className="text-[13px] text-danger">{fehler}</p>}

        <div className="flex items-center gap-2">
          <Button icon="Check" kind="primary" onClick={() => void speichern(offen)}>
            {t('signaturen.speichern')}
          </Button>
          <Button icon="X" kind="secondary" onClick={() => setOffen(null)}>
            {t('aktion.abbrechen')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button kind="primary" icon={Plus} onClick={() => setOffen(leer())}>
          {t('signaturen.neu')}
        </Button>
        <span className="flex-1" />
        {fehler && <span className="text-[13px] text-danger">{fehler}</span>}
      </div>

      {liste.length === 0 ? (
        <EmptyState
          icon={<PenLine />}
          title={t('signaturen.leer')}
          description={t('signaturen.leer_text')}
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {liste.map((s) => (
            <li
              key={s.id}
              className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5"
            >
              <button type="button" onClick={() => setOffen(s)} className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[13px] font-medium text-fg-1">
                  {s.name}
                  {s.standard && (
                    <span className="ml-2 text-[11px] font-normal text-accent-text">
                      {t('signaturen.standard_kurz')}
                    </span>
                  )}
                </span>
                <span className="block truncate text-[12px] text-fg-3">
                  {konten.find((k) => k.id === s.konto_id)?.adresse ??
                    t('signaturen.alle_postfaecher')}
                </span>
              </button>
              <Button kind="danger" size="sm" icon={Trash2} onClick={() =>
                  void (async () => {
                    const ja = await fragen({
                      titel: t('signaturen.entfernen'),
                      text: t('signaturen.entfernen_sicher', { name: s.name }),
                      knopf: t('signaturen.entfernen'),
                      gefaehrlich: true,
                    })
                    if (ja !== true) return
                    await mit(() => api.loeschen(`/api/signaturen/${s.id}`))
                  })()
                }>{t('signaturen.entfernen')}</Button>
            </li>
          ))}
        </ul>
      )}
      {nachfrage}
    </div>
  )
}
