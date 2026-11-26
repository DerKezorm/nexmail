/* Server › Allgemein nach dem Bauplan „Einstellungen": nur Karten, aus dem Bausatz ui 1.1.0.
 *
 * 1. „Funktionen für alle Konten" (SlidersHorizontal): Kalender- und Adressbuchserver im eigenen Netz, Text der Mail
 *    an Webhooks. Beide wirken beim Anhaken, nicht über „Speichern".
 * 2. „Schnittstellen" (Modul schluessel): API für Mitglieder, iPhone-App erlauben.
 * 3. nexmails eigene Karte „Zeitzone des Servers".
 *
 * Die öffentliche Adresse steht seit dem Bauplan nur noch unter Server › Anmeldung.
 *
 * ⚠️ **Nur der Betreiber sieht das.** Was hier steht, gilt für alle Konten.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, modulAnfrage } from '../api/client'
import { InterfacesCard } from '../vendor/nexschluessel/InterfacesCard'
import { SprachenKarte } from './einstellungen/Sprachen'
import { servermeldung } from '../lib/servermeldung'
import { Button, Card, CheckboxRow, Field, Notice } from '../vendor/nexui'

export function ServerAllgemein({ dokuHref }: { dokuHref?: string }) {
  return (
    <>
      <FunktionenFuerAlle />
      {/* Modul schluessel: „Programmschnittstelle (API) für Mitglieder" und „iPhone-App erlauben" (ersetzt den Schalter
          in der alten Karte „API-Schlüssel" und den in „iPhone verbinden"). */}
      <InterfacesCard request={modulAnfrage} docsHref={dokuHref} />
      {/* Bauplan Allgemein 5 (E48): keine Karte „Grenzen“ (nexmail hat nichts zu begrenzen), kein „Web Push“ (nichts
          einzustellen, E33); danach nexmails eigene Karte. */}
      <SprachenKarte />
      <ZeitzoneDesServers />
    </>
  )
}

function FunktionenFuerAlle() {
  const { t } = useTranslation()
  return (
    // E48: die gemeinsame Karte „Funktionen für alle Konten“ (Bauplan Allgemein 2), überall mit demselben Satz.
    <Card id="features" icon="SlidersHorizontal" title={t('verwaltung.funktionen_titel')} subtitle={t('verwaltung.funktionen_text')}>
      <EigenesNetz />
      <WebhookMailtext />
    </Card>
  )
}

/** „Zeitzone des Servers" (nexmail): in ihr stehen Zeiten in Mails, Plänen und Sicherungen. Ein Feld mit eigenem
 *  Speichern, der Knopf auf Höhe des Felds. Die öffentliche Adresse bleibt dabei, wie sie ist. */
function ZeitzoneDesServers() {
  const { t } = useTranslation()
  const [zeitzone, setZeitzone] = useState('')
  const [adresse, setAdresse] = useState('')
  const [fehler, setFehler] = useState('')
  const [gespeichert, setGespeichert] = useState(false)

  const laden = useCallback(async () => {
    const e = await api.holen<{ oeffentliche_adresse: string; zeitzone: string }>('/api/einstellungen')
    setAdresse(e.oeffentliche_adresse ?? '')
    setZeitzone(e.zeitzone ?? '')
  }, [])

  useEffect(() => {
    void laden().catch(() => undefined)
  }, [laden])

  async function speichern() {
    setFehler('')
    setGespeichert(false)
    try {
      await api.aendern('/api/einstellungen', { oeffentliche_adresse: adresse, zeitzone: zeitzone.trim() })
      setGespeichert(true)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  return (
    <Card id="server-time-zone" icon="Globe" title={t('verwaltung.zeitzone_titel')}>
      <Field
        label={t('darstellung.zeitzone')}
        hints={[t('verwaltung.zeitzone_hinweis')]}
        placeholder="Europe/Berlin"
        value={zeitzone}
        onChange={(e) => setZeitzone(e.target.value)}
        action={
          <Button kind="primary" icon="Check" onClick={() => void speichern()}>
            {t('aktion.speichern')}
          </Button>
        }
      />
      {fehler && <Notice tone="danger">{fehler}</Notice>}
      {gespeichert && !fehler && <Notice tone="ok">{t('darstellung.gespeichert')}</Notice>}
    </Card>
  )
}

/** Der Riegel für Kalender- und Adressbuchserver im eigenen Netz.
 *
 * ⚠️ **Er wirkt beim Umlegen, nicht über „Speichern".** Ein Schalter, der erst
 * nach einem zweiten Knopf gilt, steht auf „an" und tut nichts. Dieselbe Form
 * wie der Riegel der API-Schlüssel: gleiche Entscheidung, gleiche Bedienung.
 *
 * ⚠️ **Der Preis steht im Hinweis, nicht in einer README.** Mit der Freigabe
 * kann jeder Benutzer nexmail eine Adresse im Netz des Betreibers ansprechen
 * lassen. Wer nexmail allein benutzt, verliert nichts; wer Fremde eingeladen
 * hat, soll es lesen, bevor er umlegt.
 */
function EigenesNetz() {
  const { t } = useTranslation()
  const [erlaubt, setErlaubt] = useState<boolean | null>(null)
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    api
      .holen<{ erlaubt: boolean }>('/api/einstellungen/eigenes-netz')
      .then((e) => setErlaubt(e.erlaubt))
      .catch((f) => setFehler(servermeldung(f, t('anmeldung.fehler_allgemein'))))
  }, [t])

  async function umlegen(an: boolean) {
    setFehler('')
    try {
      const e = await api.aendern<{ erlaubt: boolean }>('/api/einstellungen/eigenes-netz', {
        erlaubt: an,
      })
      setErlaubt(e.erlaubt)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  return (
    <>
      <CheckboxRow
        label={t('verwaltung.eigenes_netz')}
        hint={t('verwaltung.eigenes_netz_hinweis')}
        checked={erlaubt ?? false}
        disabled={erlaubt === null}
        onChange={(an) => void umlegen(an)}
        testId="eigenes-netz"
      />
      {fehler && <Notice tone="danger">{fehler}</Notice>}
    </>
  )
}

/** Der Riegel für den Text der Mail an Webhooks (Issue #17).
 *
 * ⚠️ **Dieselbe Form wie das eigene Netz, und aus demselben Grund.** Mit der
 * Freigabe kann jeder Benutzer den Text seiner Mails an eine Adresse seiner
 * Wahl schicken lassen. Ob Mailtext das Haus verlässt, entscheidet der
 * Betreiber; der Benutzer schaltet es danach an seinem Webhook ein.
 */

function WebhookMailtext() {
  const { t } = useTranslation()
  const [erlaubt, setErlaubt] = useState<boolean | null>(null)
  const [fehler, setFehler] = useState('')

  useEffect(() => {
    api
      .holen<{ erlaubt: boolean }>('/api/einstellungen/webhook-mailtext')
      .then((e) => setErlaubt(e.erlaubt))
      .catch((f) => setFehler(servermeldung(f, t('anmeldung.fehler_allgemein'))))
  }, [t])

  async function umlegen(an: boolean) {
    setFehler('')
    try {
      const e = await api.aendern<{ erlaubt: boolean }>('/api/einstellungen/webhook-mailtext', {
        erlaubt: an,
      })
      setErlaubt(e.erlaubt)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  return (
    <>
      <CheckboxRow
        label={t('verwaltung.webhook_mailtext')}
        hint={t('verwaltung.webhook_mailtext_hinweis')}
        checked={erlaubt ?? false}
        disabled={erlaubt === null}
        onChange={(an) => void umlegen(an)}
        testId="webhook-mailtext"
      />
      {fehler && <Notice tone="danger">{fehler}</Notice>}
    </>
  )
}
