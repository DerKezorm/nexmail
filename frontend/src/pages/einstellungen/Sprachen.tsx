/* Server › Allgemein › Sprachen (Bauplan „Einstellungen“, Allgemein 5; E48, wie nexnotes): die eingebauten Sprachen
 * und die des Betreibers als `Chip`, „Vorlage herunterladen“ (secondary, Download), „Sprachcode“ mit `Field action`
 * „Sprache hochladen“ (secondary, Upload; die Datei wählt man beim Klick). Eine hinzugefügte Sprache steht danach in der
 * Sprachauswahl (Profil, Anmeldeseite); was ihr fehlt, steht englisch da. */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { vorlage, zusatzsprachen, zusatzsprachenVergessen, type Zusatzsprache } from '../../i18n'
import { servermeldung } from '../../lib/servermeldung'
import { Button, Buttons, Card, Chip, Field, Notice } from '../../vendor/nexui'

function speichern(name: string, datei: Blob): void {
  const adresse = URL.createObjectURL(datei)
  const verweis = document.createElement('a')
  verweis.href = adresse
  verweis.download = name
  document.body.appendChild(verweis)
  verweis.click()
  verweis.remove()
  setTimeout(() => URL.revokeObjectURL(adresse), 1000)
}

export function SprachenKarte() {
  const { t } = useTranslation()
  const [liste, setListe] = useState<Zusatzsprache[]>([])
  const [code, setCode] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const [fertig, setFertig] = useState(false)

  const laden = useCallback(() => {
    zusatzsprachenVergessen()
    void zusatzsprachen().then((l) => setListe([...l].sort((a, b) => a.name.localeCompare(b.name))))
  }, [])
  useEffect(laden, [laden])

  async function mit(arbeit: () => Promise<unknown>, gut = false) {
    setLaeuft(true)
    setFehler('')
    setFertig(false)
    try {
      await arbeit()
      setFertig(gut)
      laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Card id="languages" icon="Globe" title={t('sprachen.titel')} subtitle={t('sprachen.text')}>
      <div className="flex flex-wrap gap-2" data-testid="languages-list">
        <Chip>{`Deutsch · ${t('sprachen.eingebaut')}`}</Chip>
        <Chip>{`English · ${t('sprachen.eingebaut')}`}</Chip>
        {liste.map((e) => (
          <Chip
            key={e.code}
            name={e.name}
            disabled={laeuft}
            testId={`language-${e.code}`}
            onRemove={() => void mit(() => api.loeschen(`/api/locales/${encodeURIComponent(e.code)}`))}
          >
            {`${e.name} (${e.code}) · ${t('sprachen.texte', { count: e.keys })}`}
          </Chip>
        ))}
      </div>
      <Buttons>
        <Button kind="secondary" icon="Download" onClick={() => void vorlage().then((b) => speichern('nexmail-language-template.json', b))} testId="language-template">
          {t('sprachen.vorlage')}
        </Button>
      </Buttons>
      <Field
        label={t('sprachen.code')}
        hints={[t('sprachen.code_hinweis')]}
        value={code}
        onChange={(ev) => setCode(ev.target.value.trim())}
        placeholder="nl"
        data-testid="language-code"
        action={
          <Button
            kind="secondary"
            icon="Upload"
            disabled={!code}
            busy={laeuft}
            accept="application/json,.json"
            onFile={(datei) => void mit(() => api.datei(`/api/locales/${encodeURIComponent(code)}`, datei), true)}
            testId="language-upload"
          >
            {t('sprachen.hochladen')}
          </Button>
        }
      />
      {fehler && <Notice tone="danger">{fehler}</Notice>}
      {fertig && <Notice tone="ok">{t('sprachen.hochgeladen')}</Notice>}
    </Card>
  )
}
