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
 * Projektseite. Die Kachel füllt die **Adresse** vor (stimmt
 * sie nicht mehr, scheitert der Modellabruf laut) und verweist auf die Seite
 * des Anbieters. Was dort mit dem Text geschieht, steht in dessen Bedingungen,
 * nicht bei uns.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink, Unplug } from 'lucide-react'
import { api } from '../api/client'
import { Badge, Box, Button, Buttons, Card, CheckboxRow, Field, Notice, Segment, SelectField } from '../vendor/nexui'
import { useNachfrage } from '../components/Nachfrage'
import { KiVorgaenge } from '../components/KiVorgaenge'
import { servermeldung } from '../lib/servermeldung'

interface Stand {
  /** Ob der Betreiber es fuer diese Installation ueberhaupt erlaubt. */
  erlaubt: boolean
  aktiv: boolean
  /** Dürfen eingegangene Mails an den Dienst gehen? */
  fremde_post: boolean
  /** Hat der Betreiber das freigegeben? */
  fremde_post_erlaubt: boolean
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

export function KiDienst({ ichNeuLaden }: { ichNeuLaden?: () => void }) {
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
      ichNeuLaden?.()
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

  /* --- Der Betreiber hat es gesperrt ------------------------------------ */
  if (stand && !stand.erlaubt) {
    /* ⚠️ **Kein Formular, das man ausfuellen und dann nicht benutzen kann.** Ein Zugang, den man einrichtet und der
       beim ersten Handgriff abgewiesen wird, ist die schlechtere Auskunft. */
    return (
      <Card id="ai" icon="Sparkles" title={t('ki.dienst')}>
        <Notice tone="warn" title={t('ki.gesperrt')}>
          {t('ki.gesperrt_text')}
        </Notice>
      </Card>
    )
  }

  return (
    <>
      <Card id="ai" icon="Sparkles" title={t('ki.dienst')} subtitle={t('ki.warnung')}>
        <CheckboxRow
          label={t('ki.schalter')}
          hint={t('ki.schalter_hinweis')}
          checked={stand?.aktiv ?? false}
          disabled={speichert || (!stand?.aktiv && !steht)}
          onChange={(an) => void sichern({ aktiv: an })}
        />
        {!steht && <p className="m-0 text-sm">{t('ki.erst_einrichten')}</p>}

        {/* ⚠️ **Ein eigener Schalter unter dem ersten.** Der erste gilt dem eigenen Entwurf; hier geht Text hinaus, den
            jemand anderes geschrieben hat. Gesperrt nennt die Zeile den Grund. */}
        {stand?.aktiv &&
          (stand.fremde_post_erlaubt ? (
            <CheckboxRow
              label={t('ki.fremde_post')}
              hint={t('ki.fremde_post_hinweis')}
              checked={stand.fremde_post}
              disabled={speichert}
              onChange={(an) => void sichern({ fremde_post: an })}
            />
          ) : (
            <Notice tone="warn">{t('ki.fremde_post_gesperrt')}</Notice>
          ))}

        {/* --- Der eine Zugang, wenn er steht ------------------------------ */}
        {steht && !richtetEin && (
          <Box
            title={anbietername(stand!.url) || t('ki.eigener_dienst')}
            badge={<Badge tone="on">{t('ki.verbunden')}</Badge>}
            hint={`${stand!.url} · ${t('ki.modell')}: ${stand!.modell}${stand!.schluessel_da ? ` · ${t('ki.schluessel_liegt')}` : ''}`}
            actions={
              <Buttons>
                <Button kind="secondary" icon="Pencil" onClick={bearbeiten}>
                  {t('aktion.bearbeiten')}
                </Button>
                <Button kind="danger" icon={Unplug} disabled={speichert} onClick={() => void trennen()}>
                  {t('ki.trennen')}
                </Button>
              </Buttons>
            }
          >
            {gemeldet && <Notice tone="ok">{gemeldet}</Notice>}
            {fehler && <Notice tone="danger">{fehler}</Notice>}
          </Box>
        )}

        {/* --- Einrichten -------------------------------------------------- */}
        {richtetEin && (
          <>
            <Segment
              label={t('ki.dienst')}
              hints={[t('ki.dienst_hinweis')]}
              value={KACHELN.find((k) => k.url === url)?.id ?? ''}
              onChange={(id) => {
                const k = KACHELN.find((x) => x.id === id)
                if (k) kachelWaehlen(k.url)
              }}
              options={KACHELN.map((k) => ({ value: k.id, label: k.name }))}
            />
            {/* ⚠️ Ein Verweis statt einer Erklärung: Ein toter Link ist sichtbar, ein veralteter Satz nicht. */}
            {KACHELN.filter((k) => k.url === url).map((k) => (
              <Buttons key={k.id}>
                <Button kind="secondary" size="sm" icon={ExternalLink} href={k.wo}>
                  {t('ki.schluessel_holen', { name: k.name })}
                </Button>
              </Buttons>
            ))}

            <Box title={t('ki.zugang')}>
              <Field
                label={t('ki.adresse')}
                value={url}
                placeholder="https://…/v1/"
                onChange={(e) => {
                  setUrl(e.target.value)
                  setModelle(null)
                }}
                action={
                  <Button kind="secondary" icon="RefreshCw" disabled={!url.trim() || laedt} busy={laedt} onClick={() => void modelleHolen()}>
                    {t('ki.modelle_laden')}
                  </Button>
                }
                hints={[t('ki.modelle_laden_hinweis')]}
              />
              <Field
                type="password"
                label={t('ki.schluessel')}
                placeholder={stand?.schluessel_da ? t('ki.schluessel_liegt_da') : ''}
                hints={[t('ki.schluessel_hinweis')]}
                value={schluessel}
                onChange={(e) => setSchluessel(e.target.value)}
              />
              {/* ⚠️ Auswahl statt Freitext — ein Modellname ist ein Tippfehlerfeld. */}
              {modelle && !vonHand && (
                <SelectField
                  label={t('ki.modell')}
                  value={modell}
                  onChange={(e) => setModell(e.target.value)}
                  options={modelle.map((m) => ({ value: m.id, label: m.name ? `${m.name} (${m.id})` : m.id }))}
                />
              )}
              {(vonHand || (!modelle && modell)) && (
                <Field
                  label={t('ki.modell')}
                  value={modell}
                  hints={vonHand ? [t('ki.modell_von_hand')] : []}
                  onChange={(e) => setModell(e.target.value)}
                />
              )}
              {fehler && <Notice tone="danger">{fehler}</Notice>}
              {gemeldet && <Notice tone="ok">{gemeldet}</Notice>}
              <Buttons end>
                {steht && (
                  <Button kind="secondary" icon="X" onClick={() => setRichtetEin(false)} disabled={speichert}>
                    {t('aktion.abbrechen')}
                  </Button>
                )}
                <Button
                  kind="primary"
                  icon="Check"
                  disabled={!bereit || speichert}
                  onClick={() =>
                    void sichern(
                      {
                        url,
                        modell,
                        // ⚠️ Nicht mitgeschickt heisst unverändert — sonst verlöre man den Schlüssel, sobald man nur
                        // das Modell wechselt.
                        ...(schluessel.trim() ? { schluessel: schluessel.trim() } : {}),
                      },
                      () => setRichtetEin(false),
                    )
                  }
                >
                  {t('aktion.speichern')}
                </Button>
              </Buttons>
            </Box>
          </>
        )}
      </Card>

      {/* --- Was hinausging ---------------------------------------------- */}
      <KiVorgaenge tage={VORGANG_TAGE} />
      {nachfrage}
    </>
  )
}
