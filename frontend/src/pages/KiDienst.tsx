/* KI-Dienst — der eigene Zugang, nicht der des Betreibers.
 *
 * ⚠️ **Genau EIN Zugang, nicht mehrere.** Ein zweiter hätte keinen Nutzen —
 * umformuliert wird immer mit einem Modell — aber vier Nebenwirkungen: Welcher
 * gilt? Was passiert beim Löschen des aktiven? Wie sieht man, welcher Schlüssel
 * gerade Geld kostet? Steht ein Zugang, zeigt die Seite deshalb **eine Zeile**
 * mit Bearbeiten und Trennen. Die Einrichtung erscheint nur, wenn keiner da ist
 * oder jemand ausdrücklich bearbeitet.
 *
 * ⚠️ **Hier steht KEIN Anbietertext.** Preise, Kontingente und Bedingungen
 * ändern sich, und eine Oberfläche, die sie zusammenfasst, altert lautlos —
 * dieselbe Falle wie bei `lib/anbieter.ts`, bei der Fassungsnummer auf der
 * Projektseite und in SPAETER.md. Die Kachel füllt die **Adresse** vor (stimmt
 * sie nicht mehr, scheitert der Modellabruf laut) und verweist auf die Seite
 * des Anbieters. Was dort mit dem Text geschieht, steht in dessen Bedingungen,
 * nicht bei uns.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ExternalLink, Pencil, Unplug } from 'lucide-react'
import { api } from '../api/client'
import { Button, Input, Select, Switch } from '../ds'
import { useNachfrage } from '../components/Nachfrage'
import { KiVorgaenge } from '../components/KiVorgaenge'
import { servermeldung } from '../lib/servermeldung'

interface Stand {
  aktiv: boolean
  url: string
  modell: string
  schluessel_da: boolean
}

interface ModellZeile {
  id: string
  name: string
}

/** ⚠️ **Nur Adresse und Verweis, sonst nichts.** Alles Weitere altert. */
const KACHELN = [
  { id: 'claude', name: 'Claude', url: 'https://api.anthropic.com/v1/', wo: 'https://platform.claude.com/settings/keys' },
  { id: 'gemini', name: 'Gemini', url: 'https://generativelanguage.googleapis.com/v1beta/openai/', wo: 'https://aistudio.google.com/apikey' },
  { id: 'openai', name: 'ChatGPT', url: 'https://api.openai.com/v1/', wo: 'https://platform.openai.com/api-keys' },
  { id: 'lokal', name: 'Ollama', url: 'http://localhost:11434/v1/', wo: 'https://ollama.com' },
] as const

/** ⚠️ **Muss zu `kidienst.VORGANG_TAGE` im Server passen.** Laufen sie
 *  auseinander, verspricht die Oberfläche eine andere Frist als die, nach
 *  der wirklich gelöscht wird — ein Test hält beide aneinander. */
const VORGANG_TAGE = 14

/** Der Name zur Adresse — oder nichts, wenn es keine der bekannten ist. */
function anbietername(url: string): string {
  return KACHELN.find((k) => k.url === url)?.name ?? ''
}

export function KiDienst() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [stand, setStand] = useState<Stand | null>(null)
  /** Wahr, solange die Einrichtung offen steht. Bei einem stehenden Zugang
   *  nur, wenn jemand ausdrücklich „Bearbeiten" gedrückt hat. */
  const [richtetEin, setRichtetEin] = useState(false)
  const [url, setUrl] = useState('')
  const [schluessel, setSchluessel] = useState('')
  const [modell, setModell] = useState('')
  const [modelle, setModelle] = useState<ModellZeile[] | null>(null)
  /** Wahr, wenn der Dienst keine Liste kann — dann Freitext statt Sackgasse. */
  const [vonHand, setVonHand] = useState(false)
  const [laedt, setLaedt] = useState(false)
  const [speichert, setSpeichert] = useState(false)
  const [fehler, setFehler] = useState('')
  const [gemeldet, setGemeldet] = useState('')

  const laden = useCallback(async () => {
    try {
      const raus = await api.holen<Stand>('/api/ki')
      setStand(raus)
      /* Ohne Zugang steht die Einrichtung offen — sonst zeigt die Seite eine
         leere Zeile und einen Knopf, der sie füllt. Ein Schritt zu viel. */
      if (!raus.modell) setRichtetEin(true)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  function bearbeiten() {
    setUrl(stand?.url ?? '')
    setModell(stand?.modell ?? '')
    setModelle(null)
    setVonHand(Boolean(stand?.modell))
    setSchluessel('')
    setFehler('')
    setGemeldet('')
    setRichtetEin(true)
  }

  function kachelWaehlen(neu: string) {
    setUrl(neu)
    /* ⚠️ **Die Modellliste UND das Modell gehören zur alten Adresse.**
       Am 04.09.2026 aus dem Betrieb gemeldet: Nach dem Einrichten von Claude
       zeigte ein Klick auf Gemini weiterhin `claude-sonnet-5` im Feld. Beim
       Speichern wäre das ein Zugang gewesen, der garantiert scheitert — und
       die Meldung dazu hätte auf den Schlüssel gezeigt, nicht auf das Modell. */
    setModelle(null)
    setModell('')
    setVonHand(false)
    setFehler('')
    setGemeldet('')
  }

  async function modelleHolen() {
    setFehler('')
    setGemeldet('')
    setLaedt(true)
    try {
      const raus = await api.senden<ModellZeile[]>('/api/ki/modelle', {
        url,
        schluessel: schluessel.trim(),
      })
      setModelle(raus)
      setVonHand(false)
      if (!raus.some((m) => m.id === modell)) setModell(raus[0]?.id ?? '')
    } catch (f) {
      const satz = servermeldung(f, t('anmeldung.fehler_allgemein'))
      /* ⚠️ „Kennt keine Liste" ist kein Fehlschlag, sondern ein anderer Weg. */
      if (satz === t('serverfehler.ki_kennt_keine_liste')) setVonHand(true)
      setFehler(satz)
    } finally {
      setLaedt(false)
    }
  }

  async function sichern(aenderung: Record<string, unknown>, danach?: () => void) {
    setFehler('')
    setGemeldet('')
    setSpeichert(true)
    try {
      const raus = await api.aendern<Stand>('/api/ki', aenderung)
      setStand(raus)
      setSchluessel('')
      setGemeldet(t('ki.gespeichert'))
      danach?.()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setSpeichert(false)
    }
  }

  async function trennen() {
    /* ⚠️ **Der Schlüssel ist danach weg**, nicht nur der Schalter aus. Das ist
       der Unterschied zum Ausschalten, und deshalb wird gefragt. */
    const ja = await fragen({
      titel: t('ki.trennen'),
      text: t('ki.trennen_frage', { name: anbietername(stand?.url ?? '') || t('ki.eigener_dienst') }),
      knopf: t('ki.trennen'),
      gefaehrlich: true,
    })
    if (!ja) return
    await sichern({ aktiv: false, url: '', modell: '', schluessel: '' }, () => {
      setRichtetEin(true)
      setUrl('')
      setModell('')
      setModelle(null)
      setVonHand(false)
    })
  }

  const bereit = Boolean(url.trim() && modell.trim())
  const steht = Boolean(stand?.modell)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {/* --- Der Schalter ------------------------------------------------ */}
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
        <div className="flex items-start justify-between gap-3">
          <p className="mb-0 text-[13px] text-fg-2">{t('ki.schalter_hinweis')}</p>
          <Switch
            label={t('ki.schalter')}
            checked={stand?.aktiv ?? false}
            disabled={speichert || (!stand?.aktiv && !steht)}
            onCheckedChange={(an) => void sichern({ aktiv: an })}
          />
        </div>
        {!steht && <p className="mb-0 text-[12px] text-fg-4">{t('ki.erst_einrichten')}</p>}
      </section>

      {/* --- Der eine Zugang, wenn er steht ------------------------------ */}
      {steht && !richtetEin && (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('ki.verbunden')}</h2>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <span className="text-[13px] font-semibold text-fg-1">
                {anbietername(stand!.url) || t('ki.eigener_dienst')}
              </span>
              <span className="truncate text-[12px] text-fg-3">{stand!.url}</span>
              <span className="text-[12px] text-fg-3">
                {t('ki.modell')}: {stand!.modell}
                {stand!.schluessel_da && ` · ${t('ki.schluessel_liegt')}`}
              </span>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button variant="ghost" iconLeft={<Pencil className="size-4" />} onClick={bearbeiten}>
                {t('aktion.bearbeiten')}
              </Button>
              <Button
                variant="ghost"
                iconLeft={<Unplug className="size-4" />}
                disabled={speichert}
                onClick={() => void trennen()}
              >
                {t('ki.trennen')}
              </Button>
            </div>
          </div>
          {gemeldet && <p className="mb-0 text-[13px] text-success-text">{gemeldet}</p>}
          {fehler && (
            <p role="alert" className="mb-0 text-[13px] text-danger">
              {fehler}
            </p>
          )}
        </section>
      )}

      {/* --- Einrichten -------------------------------------------------- */}
      {richtetEin && (
        <>
          <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
            <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('ki.dienst')}</h2>
            <p className="mb-0 text-[13px] text-fg-2">{t('ki.dienst_hinweis')}</p>

            <div className="flex flex-wrap gap-2">
              {KACHELN.map((k) => (
                <button
                  key={k.id}
                  type="button"
                  aria-pressed={url === k.url}
                  onClick={() => kachelWaehlen(k.url)}
                  className={`rounded-md border px-3 py-1.5 text-[13px] transition-colors ${
                    url === k.url
                      ? 'border-accent bg-accent-soft text-accent'
                      : 'border-line bg-surface-3 text-fg-2 hover:border-line-strong'
                  }`}
                >
                  {k.name}
                </button>
              ))}
            </div>

            {/* ⚠️ Ein Verweis statt einer Erklärung: Ein toter Link ist sichtbar,
                ein veralteter Satz nicht. */}
            {KACHELN.filter((k) => k.url === url).map((k) => (
              <a
                key={k.id}
                href={k.wo}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex w-fit items-center gap-1.5 text-[12px] text-accent hover:underline"
              >
                {t('ki.schluessel_holen', { name: k.name })}
                <ExternalLink className="size-3.5" aria-hidden />
              </a>
            ))}
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
            <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('ki.zugang')}</h2>

            <Input
              label={t('ki.adresse')}
              value={url}
              placeholder="https://…/v1/"
              onChange={(e) => {
                setUrl(e.target.value)
                setModelle(null)
              }}
            />
            <Input
              type="password"
              label={t('ki.schluessel')}
              placeholder={stand?.schluessel_da ? t('ki.schluessel_liegt_da') : ''}
              hint={t('ki.schluessel_hinweis')}
              value={schluessel}
              onChange={(e) => setSchluessel(e.target.value)}
            />

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="ghost"
                disabled={!url.trim() || laedt}
                loading={laedt}
                onClick={() => void modelleHolen()}
              >
                {t('ki.modelle_laden')}
              </Button>
              <span className="text-[12px] text-fg-4">{t('ki.modelle_laden_hinweis')}</span>
            </div>

            {/* ⚠️ Auswahl statt Freitext — ein Modellname ist ein Tippfehlerfeld. */}
            {modelle && !vonHand && (
              <Select
                label={t('ki.modell')}
                value={modell}
                onChange={(e) => setModell(e.target.value)}
              >
                {modelle.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name ? `${m.name} — ${m.id}` : m.id}
                  </option>
                ))}
              </Select>
            )}

            {(vonHand || (!modelle && modell)) && (
              <Input
                label={t('ki.modell')}
                value={modell}
                hint={vonHand ? t('ki.modell_von_hand') : undefined}
                onChange={(e) => setModell(e.target.value)}
              />
            )}

            {fehler && (
              <p role="alert" className="mb-0 text-[13px] text-danger">
                {fehler}
              </p>
            )}
            {gemeldet && <p className="mb-0 text-[13px] text-success-text">{gemeldet}</p>}

            <div className="flex justify-end gap-2">
              {steht && (
                <Button variant="ghost" onClick={() => setRichtetEin(false)} disabled={speichert}>
                  {t('aktion.abbrechen')}
                </Button>
              )}
              <Button
                variant="primary"
                disabled={!bereit || speichert}
                onClick={() =>
                  void sichern(
                    {
                      url,
                      modell,
                      // ⚠️ Nicht mitgeschickt heisst unverändert — sonst verlöre
                      // man den Schlüssel, sobald man nur das Modell wechselt.
                      ...(schluessel.trim() ? { schluessel: schluessel.trim() } : {}),
                    },
                    () => setRichtetEin(false),
                  )
                }
              >
                {t('aktion.speichern')}
              </Button>
            </div>
          </section>
        </>
      )}

      {/* --- Was hinausging ---------------------------------------------- */}
      <KiVorgaenge tage={VORGANG_TAGE} />

      {/* --- Was das heißt ----------------------------------------------- */}
      <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-3">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <p className="mb-0 text-[13px] text-warning-text">{t('ki.warnung')}</p>
      </div>
      {nachfrage}
    </div>
  )
}
