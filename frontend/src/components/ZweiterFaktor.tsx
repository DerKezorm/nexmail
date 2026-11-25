/* Den zweiten Faktor einschalten — QR-Code, Probe, Wiederherstellungscodes.
 *
 * ⚠️ **Er ist eine Wahl, keine Pflicht** (01.09.2026). Vorher stand er als
 * Schritt 2 fest in der Ersteinrichtung, und man kam ohne Telefon nicht
 * heraus. Das sperrte genau die Leute aus, für die nexmail gedacht ist:
 * jemanden, der es abends im eigenen Netz aufsetzt.
 *
 * ⚠️ **Und deshalb wohnt er hier und nicht in der Anmeldung.** Ein Assistent
 * mitten im Anmelden lässt sich nicht abbrechen; ein Knopf in den
 * Einstellungen schon.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Copy, Download } from 'lucide-react'
import { api, ApiFehler } from '../api/client'
import { Button, Input } from '../ds'
import { servermeldung } from '../lib/servermeldung'

interface Start {
  geheimnis: string
  otpauth: string
  qr_svg: string
}

export function ZweiterFaktor({
  benutzername,
  aufFertig,
  aufAbbrechen,
}: {
  benutzername: string
  aufFertig: () => void
  aufAbbrechen?: () => void
}) {
  const { t } = useTranslation()
  const [start, setStart] = useState<Start | null>(null)
  const [codes, setCodes] = useState<string[] | null>(null)
  const [code, setCode] = useState('')
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  /* konten 0.3.4: Wartet schon eine Einrichtung (Seite neu geladen, anderer Reiter), zeigt sie denselben QR-Code
     noch einmal (`factor.pending_setup`); erst ohne eine (410) beginnt eine neue. */
  const holen = useCallback(async () => {
    try {
      try {
        setStart(await api.holen<Start>('/api/auth/zwei-faktor/einrichtung'))
      } catch (f) {
        if (!(f instanceof ApiFehler) || f.status !== 410) throw f
        setStart(await api.senden<Start>('/api/auth/zwei-faktor/starten', {}))
      }
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void holen()
  }, [holen])

  async function bestaetigen(e: React.FormEvent) {
    e.preventDefault()
    setFehler('')
    setLaeuft(true)
    try {
      const antwort = await api.senden<{ codes: string[] }>(
        '/api/auth/zwei-faktor/bestaetigen',
        { code: code.trim() },
      )
      // Hatte das Konto schon Codes (etwa neben einem Passkey), bleiben sie, und es gibt keine neuen zu zeigen.
      if (antwort.codes.length) setCodes(antwort.codes)
      else aufFertig()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      // Zehn Minuten vorbei (`enrolment_expired`): ein neuer QR-Code.
      if (f instanceof ApiFehler && f.status === 410) void holen()
    } finally {
      setLaeuft(false)
    }
  }

  /* --- Schritt 2: die Codes, danach ist Schluss ------------------------- */
  if (codes) {
    return <CodesZeigen codes={codes} benutzername={benutzername} aufFertig={aufFertig} />
  }

  /* --- Schritt 1: QR-Code und Probe ------------------------------------- */
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
        {/* ⚠️ Der QR-Code entsteht im eigenen Server, nicht bei einem fremden
            Dienst — ein Geheimnis, das man zum Zeichnen verschickt, ist keins
            mehr. */}
        {start ? (
          <div
            className="shrink-0 rounded-lg bg-white p-2"
            dangerouslySetInnerHTML={{ __html: start.qr_svg }}
          />
        ) : (
          <div className="size-[168px] shrink-0 rounded-lg bg-surface-2" />
        )}
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[12px] font-semibold tracking-[0.06em] text-fg-4 uppercase">
            {t('einrichtung.geheimnis_abtippen')}
          </p>
          <code className="block break-all rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-[13px] text-fg-1 select-all">
            {start?.geheimnis ?? '…'}
          </code>
        </div>
      </div>

      <form onSubmit={bestaetigen} className="flex flex-col gap-4">
        <Input
          label={t('einrichtung.code_eingabe')}
          value={code}
          mono
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          placeholder="000000"
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
        />

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={laeuft} disabled={code.length !== 6}>
            {t('sicherheit.faktor_pruefen')}
          </Button>
          {aufAbbrechen && (
            <Button variant="ghost" onClick={aufAbbrechen}>
              {t('aktion.abbrechen')}
            </Button>
          )}
        </div>
      </form>
    </div>
  )
}

/** Die Wiederherstellungscodes, genau einmal gezeigt: nach dem Einschalten unter Sicherheit und nach dem Einrichten
 *  beim Anmelden („Zweiten Faktor für alle verlangen“). */
export function CodesZeigen({
  codes,
  benutzername,
  aufFertig,
}: {
  codes: string[]
  benutzername: string
  aufFertig: () => void
}) {
  const { t } = useTranslation()
  const [gesichert, setGesichert] = useState(false)
  const [kopiert, setKopiert] = useState(false)

  function kopieren() {
    void navigator.clipboard.writeText(codes.join('\n'))
    setKopiert(true)
    window.setTimeout(() => setKopiert(false), 2000)
  }

  function herunterladen() {
    const inhalt =
      `nexmail — Wiederherstellungscodes für ${benutzername}\n\n` +
      codes.map((c) => `  ${c}`).join('\n') +
      '\n\nJeder Code gilt genau einmal.\n'
    const blob = new Blob([inhalt], { type: 'text/plain;charset=utf-8' })
    const verweis = document.createElement('a')
    verweis.href = URL.createObjectURL(blob)
    verweis.download = `nexmail-wiederherstellungscodes-${benutzername}.txt`
    verweis.click()
    URL.revokeObjectURL(verweis.href)
    setGesichert(true)
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border border-line bg-surface-2 p-4">
        <h2 className="mb-1 font-display text-[16px] font-medium text-fg-1">
          {t('einrichtung.codes_titel')}
        </h2>
        <p className="mb-3 text-[13px] text-fg-3">
          {t('einrichtung.codes_text').replace(/\*\*/g, '')}
        </p>

        <ul className="mb-3 grid list-none grid-cols-2 gap-1.5 p-0">
          {codes.map((c) => (
            <li
              key={c}
              className="rounded-sm bg-surface-1 px-2 py-1.5 text-center font-mono text-[13px] tracking-wide text-fg-1 select-all"
            >
              {c}
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap gap-2">
          <Button size="sm" iconLeft={<Download className="size-4" />} onClick={herunterladen}>
            {t('einrichtung.codes_herunterladen')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            iconLeft={kopiert ? <Check className="size-4" /> : <Copy className="size-4" />}
            onClick={kopieren}
          >
            {kopiert ? t('einrichtung.codes_kopiert') : t('einrichtung.codes_kopieren')}
          </Button>
        </div>
      </section>

      <div className="flex gap-3 rounded-lg border border-warning/40 bg-warning-soft p-4">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="min-w-0">
          <p className="mb-1 text-[13px] font-medium text-fg-1">
            {t('einrichtung.warnung_titel')}
          </p>
          <p className="mb-0 text-[13px] text-fg-2">{t('einrichtung.warnung_text')}</p>
        </div>
      </div>

      {/* ⚠️ **Der Haken steht hier, nicht vor dem Code.** Erst hat man die
          Codes gesehen, dann bestätigt man, sie gesichert zu haben. */}
      <label className="flex cursor-pointer items-center gap-2.5 select-none">
        <input
          type="checkbox"
          checked={gesichert}
          onChange={(e) => setGesichert(e.target.checked)}
          className="size-4 shrink-0 accent-[var(--accent)]"
        />
        <span className="text-[13px] text-fg-1">{t('einrichtung.codes_gesichert')}</span>
      </label>

      <Button variant="primary" disabled={!gesichert} onClick={aufFertig}>
        {t('sicherheit.faktor_fertig')}
      </Button>
    </div>
  )
}
