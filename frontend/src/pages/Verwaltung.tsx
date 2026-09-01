/* Die Verwaltung — was der Anwendung gehört, nicht dem Benutzer.
 *
 * ⚠️ **Zwei Einstellungsseiten, und der Unterschied ist die Zuständigkeit.**
 *
 * Unter „Einstellungen" im Benutzermenü steht, was **diesem Menschen** gehört:
 * seine Postfächer, seine Regeln, seine Signaturen, sein zweiter Faktor. Hier
 * steht, was der **Anwendung** gehört und für alle gilt: Protokoll, Server,
 * später Benutzerverwaltung und OIDC.
 *
 * Vermischt man beides, entsteht die Frage „ändere ich das gerade für mich
 * oder für alle?" — und die stellt sich bei jedem einzelnen Feld neu.
 *
 * ⚠️ **Nur der Betreiber sieht das.** Nicht ausgeblendet aus Höflichkeit,
 * sondern weil im Protokoll steht, wer wann was getan hat: Bei mehreren
 * Benutzern wäre das ein Fenster in fremde Vorgänge.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, ScrollText, Server } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import type { Ich } from '../api/client'
import { Button, EmptyState, Input, Select, Tabs } from '../ds'
import { Benutzerverwaltung } from './Benutzerverwaltung'
import { OidcVerwaltung } from './OidcVerwaltung'
import { Protokoll } from './Protokoll'

export type VerwaltungsReiter = 'protokoll' | 'server' | 'benutzer' | 'oidc'

interface Props {
  reiter: VerwaltungsReiter
  aufReiter: (r: VerwaltungsReiter) => void
  ich: Ich | null
}

export function Verwaltung({ reiter, aufReiter, ich }: Props) {
  const { t } = useTranslation()

  if (ich && !ich.ist_betreiber) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center bg-canvas">
        <EmptyState
          icon={<KeyRound />}
          title={t('verwaltung.nur_betreiber')}
          description={t('verwaltung.nur_betreiber_text')}
        />
      </div>
    )
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas">
      <div className="mx-auto max-w-[860px] px-6 py-6">
        <h1 className="mb-1 font-display text-[22px] font-medium text-fg-1">
          {t('verwaltung.titel')}
        </h1>
        <p className="mb-4 text-[13px] text-fg-3">{t('verwaltung.untertitel')}</p>

        <Tabs
          activeId={reiter}
          onSelect={(id) => aufReiter(id as VerwaltungsReiter)}
          tabs={[
            { id: 'protokoll', label: t('verwaltung.protokoll') },
            { id: 'server', label: t('verwaltung.server') },
            { id: 'benutzer', label: t('verwaltung.benutzer') },
            { id: 'oidc', label: t('verwaltung.oidc') },
          ]}
        />

        <div className="pt-5">
          {reiter === 'protokoll' ? (
            <Protokoll />
          ) : reiter === 'server' ? (
            <Serverdaten />
          ) : reiter === 'benutzer' ? (
            <Benutzerverwaltung />
          ) : (
            <OidcVerwaltung />
          )}
        </div>
      </div>
    </div>
  )
}

function Serverdaten() {
  const { t } = useTranslation()
  const [adresse, setAdresse] = useState('')
  const [zeitzone, setZeitzone] = useState('')
  const [fehler, setFehler] = useState('')
  const [gespeichert, setGespeichert] = useState(false)

  const laden = useCallback(async () => {
    const e = await api.holen<{ oeffentliche_adresse: string; zeitzone: string }>(
      '/api/einstellungen',
    )
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
      await api.aendern('/api/einstellungen', {
        oeffentliche_adresse: adresse.trim(),
        zeitzone: zeitzone.trim(),
      })
      setGespeichert(true)
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    }
  }

  return (
    <div className="flex max-w-[560px] flex-col gap-4">
      <Input
        label={t('verwaltung.oeffentliche_adresse')}
        hint={t('verwaltung.oeffentliche_adresse_hinweis')}
        placeholder="https://mail.example.org"
        value={adresse}
        onChange={(e) => setAdresse(e.target.value)}
      />
      <Input
        label={t('darstellung.zeitzone')}
        hint={t('verwaltung.zeitzone_hinweis')}
        placeholder="Europe/Berlin"
        value={zeitzone}
        onChange={(e) => setZeitzone(e.target.value)}
      />

      {fehler && <p className="mb-0 text-[13px] text-danger">{fehler}</p>}
      {gespeichert && !fehler && (
        <p className="mb-0 text-[13px] text-accent-text">{t('darstellung.gespeichert')}</p>
      )}

      <div>
        <Button variant="primary" iconLeft={<Server className="size-4" />} onClick={() => void speichern()}>
          {t('verwaltung.speichern')}
        </Button>
      </div>

      <p className="mb-0 flex items-start gap-2 text-[12px] text-fg-4">
        <ScrollText className="mt-0.5 size-3.5 shrink-0" />
        {t('verwaltung.gilt_fuer_alle')}
      </p>

      <Postausgang />
    </div>
  )
}

/** Der Postausgang, mit dem **nexmail selbst** Post verschickt.
 *
 * ⚠️ **Nicht das Postfach des Betreibers dafür nehmen.** Das wäre schnell
 * gebaut und dauerhaft falsch: Der Betreiber könnte sein Postfach nicht mehr
 * entfernen, ohne die Einladungen mitzunehmen; jede Systemmail käme von seiner
 * privaten Adresse; und ein Homelab ohne eingerichtetes Postfach könnte
 * niemanden einladen.
 */
function Postausgang() {
  const { t } = useTranslation()
  const [f, setF] = useState({
    server: '',
    port: 587,
    sicherheit: 'starttls',
    benutzer: '',
    absender: '',
    absendername: 'nexmail',
  })
  const [passwort, setPasswort] = useState('')
  const [liegtVor, setLiegtVor] = useState(false)
  const [probeAn, setProbeAn] = useState('')
  const [fehler, setFehler] = useState('')
  const [meldung, setMeldung] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  const laden = useCallback(async () => {
    const a = await api.holen<typeof f & { passwort_liegt_vor: boolean }>(
      '/api/einstellungen/postausgang',
    )
    setF({
      server: a.server,
      port: a.port,
      sicherheit: a.sicherheit,
      benutzer: a.benutzer,
      absender: a.absender,
      absendername: a.absendername,
    })
    setLiegtVor(a.passwort_liegt_vor)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    void laden().catch(() => undefined)
  }, [laden])

  async function mit(tun: () => Promise<unknown>, gut: string) {
    setFehler('')
    setMeldung('')
    setLaeuft(true)
    try {
      await tun()
      setMeldung(gut)
      await laden()
    } catch (fehl) {
      setFehler(fehl instanceof ApiFehler && fehl.detail ? fehl.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <section className="mt-4 flex flex-col gap-4 border-t border-line-subtle pt-6">
      <div>
        <h2 className="mb-1 text-[13px] font-semibold text-fg-1">{t('verwaltung.postausgang')}</h2>
        <p className="mb-0 text-[12px] text-fg-3">{t('verwaltung.postausgang_hinweis')}</p>
      </div>

      <div className="grid grid-cols-[1fr_120px_150px] gap-3">
        <Input
          label={t('konto.smtp_server')}
          placeholder="smtp.example.org"
          value={f.server}
          onChange={(e) => setF({ ...f, server: e.target.value })}
        />
        <Input
          label={t('konto.port')}
          inputMode="numeric"
          value={String(f.port)}
          onChange={(e) => setF({ ...f, port: Number(e.target.value.replace(/\D/g, '')) || 0 })}
        />
        <Select
          label={t('konto.verschluesselung')}
          value={f.sicherheit}
          onChange={(e) => setF({ ...f, sicherheit: e.target.value })}
          options={[
            { value: 'starttls', label: 'STARTTLS' },
            { value: 'ssl', label: 'SSL/TLS' },
            { value: 'keine', label: t('konto.keine') },
          ]}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Input
          label={t('konto.benutzername')}
          value={f.benutzer}
          onChange={(e) => setF({ ...f, benutzer: e.target.value })}
        />
        <Input
          label={t('konto.passwort')}
          type="password"
          autoComplete="new-password"
          hint={liegtVor ? t('verwaltung.postausgang_liegt_vor') : undefined}
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Input
          label={t('verwaltung.postausgang_absender')}
          placeholder="nexmail@example.org"
          value={f.absender}
          onChange={(e) => setF({ ...f, absender: e.target.value })}
        />
        <Input
          label={t('verwaltung.postausgang_absendername')}
          value={f.absendername}
          onChange={(e) => setF({ ...f, absendername: e.target.value })}
        />
      </div>

      {fehler && <p className="mb-0 text-[13px] text-danger">{fehler}</p>}
      {meldung && !fehler && <p className="mb-0 text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex flex-wrap items-end gap-2">
        <Button
          variant="primary"
          loading={laeuft}
          onClick={() =>
            void mit(
              () =>
                api.aendern('/api/einstellungen/postausgang', {
                  ...f,
                  // ⚠️ Leer heißt „unverändert", nicht „kein Kennwort" — sonst
                  // verliert den Zugang, wer nur den Absendernamen ändert.
                  passwort: passwort ? passwort : null,
                }),
              t('darstellung.gespeichert'),
            )
          }
        >
          {t('verwaltung.speichern')}
        </Button>

        {/* ⚠️ **Die Probe ist kein Beiwerk.** Ein Postausgang, der erst bei
            der ersten Einladung scheitert, lässt den Betreiber glauben, sie
            sei unterwegs — und den Eingeladenen warten. */}
        <div className="w-[220px]">
          <Input
            label={t('verwaltung.postausgang_probe_an')}
            placeholder="name@example.com"
            value={probeAn}
            onChange={(e) => setProbeAn(e.target.value)}
          />
        </div>
        <Button
          disabled={!probeAn.includes('@')}
          onClick={() =>
            void mit(
              () => api.senden('/api/einstellungen/postausgang/probe', { an: probeAn.trim() }),
              t('verwaltung.postausgang_probe_ok'),
            )
          }
        >
          {t('verwaltung.postausgang_probe')}
        </Button>
      </div>
    </section>
  )
}
