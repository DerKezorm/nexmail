/* Postfach hinzufügen.
 *
 * Der Weg ist kurz gehalten: Adresse, Name, Kennwort. Sobald die Adresse
 * vollständig ist, fragt nexmail beim Anbieter nach den Serverdaten
 * (Autoconfig) und trägt sie ein.
 *
 * ⚠️ **Von Hand eintragen ist der Hauptweg, nicht der Notausgang.** Findet
 * niemand etwas, klappt der Block „Serverdaten" auf und man trägt sie selbst
 * ein — damit funktioniert jedes IMAP-Postfach, auch eines, von dem nexmail
 * nie gehört hat.
 *
 * ⚠️ **Der Test meldet beide Wege getrennt.** Wer beim ersten Fehler
 * abbricht, schickt den Betreiber durch zwei Runden: erst den Posteingang
 * reparieren, dann erfahren, dass der Postausgang auch nicht ging. Bei iCloud
 * ist genau das der Normalfall, weil dort die Benutzernamen verschieden sind.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, XCircle } from 'lucide-react'
import { Button, Input, Select } from '../ds'
import { Schlagwortfeld } from '../components/Schlagwortfeld'
import { ApiFehler, api } from '../api/client'
import type { Befund, KontoZeile, Vorschlag } from '../api/client'
import { PUNKT_KLASSE } from '../lib/farben'

interface Props {
  naechsteFarbe: 1 | 2 | 3 | 4 | 5 | 6
  aufAbbrechen: () => void
  aufAngelegt: (konto: KontoZeile) => void
  /** Gesetzt heißt: bearbeiten statt anlegen. */
  bestehend?: KontoZeile | null
  /** Schlagworte, die an anderen Postfächern schon hängen. */
  bekannteTags?: string[]
}

interface Felder {
  anzeigename: string
  tags: string[]
  absendername: string
  adresse: string
  passwort: string
  imap_server: string
  imap_port: number
  imap_sicherheit: string
  imap_benutzer: string
  smtp_server: string
  smtp_port: number
  smtp_sicherheit: string
  smtp_benutzer: string
}

const LEER: Felder = {
  anzeigename: '',
  tags: [],
  absendername: '',
  adresse: '',
  passwort: '',
  imap_server: '',
  imap_port: 993,
  imap_sicherheit: 'ssl',
  imap_benutzer: '',
  smtp_server: '',
  smtp_port: 587,
  smtp_sicherheit: 'starttls',
  smtp_benutzer: '',
}

const SICHERHEITEN = [
  { value: 'ssl', label: 'SSL/TLS' },
  { value: 'starttls', label: 'STARTTLS' },
]

export function KontoFormular({
  naechsteFarbe,
  aufAbbrechen,
  aufAngelegt,
  bestehend = null,
  bekannteTags = [],
}: Props) {
  const { t } = useTranslation()

  /* ⚠️ **Das Passwortfeld bleibt leer, und das ist Absicht.** nexmail kann
     ein gespeichertes Passwort nicht anzeigen — es liegt verschlüsselt da.
     Leer heißt beim Bearbeiten „unverändert"; würde es als leeres Passwort
     übernommen, verlöre jeder seinen Zugang, der nur den Anzeigenamen
     ändert. */
  const [felder, setFelder] = useState<Felder>(
    bestehend
      ? {
          anzeigename: bestehend.anzeigename,
          tags: bestehend.tags ?? [],
          absendername: bestehend.absendername ?? '',
          adresse: bestehend.adresse,
          passwort: '',
          imap_server: bestehend.imap_server,
          imap_port: bestehend.imap_port,
          imap_sicherheit: bestehend.imap_sicherheit,
          imap_benutzer: bestehend.imap_benutzer,
          smtp_server: bestehend.smtp_server,
          smtp_port: bestehend.smtp_port,
          smtp_sicherheit: bestehend.smtp_sicherheit,
          smtp_benutzer: bestehend.smtp_benutzer,
        }
      : LEER,
  )
  /* ⚠️ **Das Passwortfeld sieht beim Bearbeiten belegt aus — und ist es
     auch, nur nicht hier.** nexmail kann ein gespeichertes Passwort nicht
     anzeigen: Es liegt verschlüsselt in der Datenbank und verlässt den Server
     nie. Ein leeres Feld sah dagegen aus, als wäre nichts gespeichert, und
     man tippte es unnötig neu ein.
  
     Deshalb stehen Punkte darin, solange niemand das Feld anfasst. Wird es
     angefasst, wird es geleert und der neue Wert gilt. Kein Platzhalter-Wort
     als heimliche Kennung: Sonst könnte ein echtes Passwort genau so lauten. */
  const [passwortBeruehrt, setPasswortBeruehrt] = useState(false)
  const [vorschlag, setVorschlag] = useState<Vorschlag | null>(null)
  const [sucht, setSucht] = useState(false)
  const [serverOffen, setServerOffen] = useState(false)

  const [befund, setBefund] = useState<Befund | null>(null)
  const [testet, setTestet] = useState(false)
  const [legtAn, setLegtAn] = useState(false)
  const [fehler, setFehler] = useState('')

  const uhr = useRef<number | undefined>(undefined)

  // ⚠️ **Die Anbietersuche dauert bis zu drei Sekunden** — sie fragt drei
  // fremde Server der Reihe nach. In dieser Zeit tippt man weiter, und dann
  // sind zwei Anfragen gleichzeitig unterwegs. Kommt die ältere zuletzt
  // zurück, überschreibt sie die jüngere: Die Felder unten stehen richtig
  // gefüllt da, während darüber „Für diese Adresse liefert niemand
  // Serverdaten“ steht. Genau das ist passiert.
  //
  // Deshalb trägt jede Antwort die Adresse mit, für die sie geholt wurde.
  // Passt sie nicht mehr zum Feld, wird sie weggeworfen.
  const laeuftFuer = useRef('')

  function setzen(teil: Partial<Felder>) {
    setFelder((alt) => ({ ...alt, ...teil }))
    // Jede Änderung entwertet den letzten Test. Sonst legt man ein Postfach
    // an, das mit anderen Daten geprüft wurde als denen, die gespeichert werden.
    setBefund(null)
  }

  /* --- Serverdaten suchen, sobald die Adresse vollständig aussieht ------ */

  useEffect(() => {
    const adresse = felder.adresse.trim()
    window.clearTimeout(uhr.current)

    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(adresse)) {
      setVorschlag(null)
      return
    }

    // Kurz warten: Sonst fragt nexmail bei jedem getippten Buchstaben nach.
    uhr.current = window.setTimeout(() => {
      setSucht(true)
      laeuftFuer.current = adresse
      api
        .senden<Vorschlag>('/api/konten/vorschlag', { adresse })
        .then((gefunden) => {
          // Veraltete Antwort - inzwischen steht eine andere Adresse im Feld.
          if (laeuftFuer.current !== adresse) return
          setVorschlag(gefunden)
          if (gefunden.gefunden) {
            setzen({
              imap_server: gefunden.imap.server,
              imap_port: gefunden.imap.port,
              imap_sicherheit: gefunden.imap.sicherheit,
              imap_benutzer: gefunden.imap.benutzer,
              smtp_server: gefunden.smtp.server,
              smtp_port: gefunden.smtp.port,
              smtp_sicherheit: gefunden.smtp.sicherheit,
              smtp_benutzer: gefunden.smtp.benutzer,
            })
          } else {
            // Nichts gefunden: Der Block klappt auf, weil jetzt Handarbeit
            // ansteht — und weil ein zugeklappter Block hier wie eine
            // Sackgasse aussähe.
            setServerOffen(true)
            setzen({ imap_benutzer: adresse, smtp_benutzer: adresse })
          }
        })
        .catch(() => {
          if (laeuftFuer.current === adresse) setVorschlag(null)
        })
        .finally(() => {
          if (laeuftFuer.current === adresse) setSucht(false)
        })
    }, 500)

    return () => window.clearTimeout(uhr.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [felder.adresse])

  /* --- Prüfen und anlegen ---------------------------------------------- */

  function nutzdaten() {
    return {
      anzeigename: felder.anzeigename,
      tags: felder.tags,
      absendername: felder.absendername,
      adresse: felder.adresse.trim(),
      imap_server: felder.imap_server.trim(),
      imap_port: felder.imap_port,
      imap_sicherheit: felder.imap_sicherheit,
      imap_benutzer: felder.imap_benutzer.trim(),
      imap_passwort: felder.passwort,
      smtp_server: felder.smtp_server.trim(),
      smtp_port: felder.smtp_port,
      smtp_sicherheit: felder.smtp_sicherheit,
      smtp_benutzer: felder.smtp_benutzer.trim(),
      smtp_passwort: felder.passwort,
    }
  }

  async function testen() {
    setFehler('')
    setTestet(true)
    try {
      setBefund(await api.senden<Befund>('/api/konten/pruefen', nutzdaten()))
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setTestet(false)
    }
  }

  async function anlegen() {
    setFehler('')
    setLegtAn(true)
    try {
      aufAngelegt(
        bestehend
          ? await api.aendern<KontoZeile>(`/api/konten/${bestehend.id}`, nutzdaten())
          : await api.senden<KontoZeile>('/api/konten', nutzdaten()),
      )
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setLegtAn(false)
    }
  }

  const vollstaendig =
    felder.adresse.includes('@') &&
    // Beim Bearbeiten ist ein leeres Passwortfeld erlaubt: Es heißt
    // „unverändert", nicht „leer".
    (Boolean(bestehend) || felder.passwort.length > 0) &&
    felder.imap_server &&
    felder.smtp_server &&
    felder.imap_benutzer &&
    felder.smtp_benutzer

  const benutzerVerschieden =
    Boolean(felder.imap_benutzer) &&
    Boolean(felder.smtp_benutzer) &&
    felder.imap_benutzer !== felder.smtp_benutzer

  return (
    <div className="flex max-w-[640px] flex-col gap-4">
      <Input
        label={t('konto.adresse')}
        placeholder={t('konto.adresse_platzhalter')}
        value={felder.adresse}
        mono
        autoFocus
        autoComplete="email"
        onChange={(e) => setzen({ adresse: e.target.value })}
        hint={sucht ? t('konto.suche_laeuft') : undefined}
      />

      {/* ⚠️ Der „nichts gefunden“-Hinweis verschwindet, sobald die Felder
          stehen — egal woher. Ein Hinweis, der dem Formular unter ihm
          widerspricht, lässt den Betreiber an der Anwendung zweifeln, und
          zwar zu Recht. */}
      {vorschlag && !sucht && !(!vorschlag.gefunden && felder.imap_server && felder.smtp_server) && (
        <Hinweis
          art={vorschlag.gefunden ? 'info' : 'warnung'}
          text={
            !vorschlag.gefunden
              ? t('konto.nichts_gefunden')
              : vorschlag.quelle === 'autoconfig'
                ? t('konto.gefunden_autoconfig', { name: vorschlag.anbietername || '—' })
                : t('konto.gefunden_tabelle', { name: vorschlag.anbietername || '—' })
          }
        />
      )}

      {vorschlag?.quelle?.includes('ungeprueft') && <Hinweis art="warnung" text={t('konto.ungeprueft')} />}

      {/* ⚠️ **Zwei Namen, zwei Zwecke.** Der eine steht in der Ordnerspalte
          („Privat", „Arbeit"), der andere im Absender jeder Mail, die
          hinausgeht — und den liest der Empfänger. Ein Feld für beides hieß:
          Wer sein Postfach „Arbeit" nennt, verschickt Post von „Arbeit". */}
      <Input
        label={t('konto.anzeigename')}
        hint={t('konto.anzeigename_hinweis')}
        placeholder={t('konto.anzeigename_platzhalter')}
        value={felder.anzeigename}
        onChange={(e) => setzen({ anzeigename: e.target.value })}
      />

      <Input
        label={t('konto.absendername')}
        hint={t('konto.absendername_hinweis')}
        placeholder={felder.anzeigename || t('konto.absendername_platzhalter')}
        value={felder.absendername}
        onChange={(e) => setzen({ absendername: e.target.value })}
      />

      {/* ⚠️ **Hier, nicht unter „Erweitert".** Wer ein Postfach anlegt, weiß
          in dem Moment, ob es privat oder dienstlich ist — später sucht das
          niemand nach. */}
      <Schlagwortfeld
        werte={felder.tags}
        aufAendern={(tags) => setzen({ tags })}
        vorschlaege={bekannteTags}
      />

      <Input
        label={t('konto.passwort')}
        type="password"
        autoComplete="new-password"
        hint={bestehend && !passwortBeruehrt ? t('konto.passwort_liegt_vor') : undefined}
        value={bestehend && !passwortBeruehrt ? '••••••••••' : felder.passwort}
        onFocus={() => {
          if (bestehend && !passwortBeruehrt) {
            setPasswortBeruehrt(true)
            setzen({ passwort: '' })
          }
        }}
        onChange={(e) => {
          setPasswortBeruehrt(true)
          setzen({ passwort: e.target.value })
        }}
      />

      {vorschlag?.app_passwort_noetig && (
        <div className="flex gap-3 rounded-lg border border-info/40 bg-info-soft px-4 py-3">
          <Info className="mt-0.5 size-4 shrink-0 text-info" />
          <div className="min-w-0">
            <p className="mb-1 text-[13px] font-medium text-fg-1">
              {t('konto.icloud_hinweis_titel')}
            </p>
            <p className="mb-0 text-[13px] text-fg-2">
              {t('konto.icloud_hinweis_text')} ({vorschlag.app_passwort_wo})
            </p>
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-4 py-3">
        <span aria-hidden className={`size-3 shrink-0 rounded-full ${PUNKT_KLASSE[naechsteFarbe]}`} />
        <div className="min-w-0 flex-1">
          <p className="mb-0 text-[13px] text-fg-1">{t('konto.farbe')}</p>
          <p className="mb-0 text-[12px] text-fg-4">{t('konto.farbe_hinweis')}</p>
        </div>
      </div>

      {/* --- Serverdaten ------------------------------------------------- */}

      <div>
        <button
          type="button"
          onClick={() => setServerOffen(!serverOffen)}
          className="flex items-center gap-1.5 text-[13px] text-fg-3 transition-colors duration-[var(--dur-fast)] hover:text-fg-1"
        >
          {serverOffen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          {serverOffen ? t('konto.serverdaten_verbergen') : t('konto.serverdaten_zeigen')}
        </button>

        {serverOffen && (
          <div className="mt-3 flex flex-col gap-4 rounded-lg border border-line bg-surface-2 p-4">
            {benutzerVerschieden && (
              <p className="mb-0 text-[12px] text-fg-4">{t('konto.benutzer_verschieden')}</p>
            )}

            <Serverblock
              titel={t('konto.imap')}
              server={felder.imap_server}
              port={felder.imap_port}
              sicherheit={felder.imap_sicherheit}
              benutzer={felder.imap_benutzer}
              aufAendern={(teil) =>
                setzen({
                  imap_server: teil.server ?? felder.imap_server,
                  imap_port: teil.port ?? felder.imap_port,
                  imap_sicherheit: teil.sicherheit ?? felder.imap_sicherheit,
                  imap_benutzer: teil.benutzer ?? felder.imap_benutzer,
                })
              }
            />
            <Serverblock
              titel={t('konto.smtp')}
              server={felder.smtp_server}
              port={felder.smtp_port}
              sicherheit={felder.smtp_sicherheit}
              benutzer={felder.smtp_benutzer}
              aufAendern={(teil) =>
                setzen({
                  smtp_server: teil.server ?? felder.smtp_server,
                  smtp_port: teil.port ?? felder.smtp_port,
                  smtp_sicherheit: teil.sicherheit ?? felder.smtp_sicherheit,
                  smtp_benutzer: teil.benutzer ?? felder.smtp_benutzer,
                })
              }
            />
          </div>
        )}
      </div>

      {/* --- Befund ------------------------------------------------------ */}

      {befund && (
        <div className="flex flex-col gap-2">
          <Zeile ok={befund.imap.ok} titel={t('konto.test_imap')} text={befund.imap.text} />
          <Zeile ok={befund.smtp.ok} titel={t('konto.test_smtp')} text={befund.smtp.text} />
          {befund.ok && (
            <p className="mb-0 text-[12px] text-fg-4">
              {t('konto.ordner_gefunden', { count: befund.ordner.length })}
              {' · '}
              {befund.ordner
                .filter((o) => o.rolle !== 'eigen')
                .map((o) => o.name)
                .join(', ')}
            </p>
          )}
        </div>
      )}

      {fehler && (
        <p role="alert" className="mb-0 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-[13px] text-fg-1">
          {fehler}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button loading={testet} disabled={!vollstaendig} onClick={testen}>
          {testet ? t('konto.test_laeuft') : t('konto.testen')}
        </Button>
        {/* ⚠️ **Beim Anlegen ist der Test Pflicht, beim Bearbeiten nicht.**
            Ein Postfach, das neu in der Liste steht und nicht funktioniert,
            sieht aus wie ein Fehler von nexmail — deshalb erst prüfen. Wer
            aber nur den Anzeigenamen ändert, müsste sonst sein Passwort neu
            eintippen, nur um den Test bestehen zu können. Das ist die Art
            Hürde, an der man aufhört, etwas zu pflegen. */}
        <Button
          variant="primary"
          loading={legtAn}
          disabled={bestehend ? !vollstaendig : !befund?.ok}
          onClick={anlegen}
          title={!bestehend && !befund?.ok ? t('konto.zuerst_testen') : undefined}
        >
          {legtAn
            ? t('konto.wird_hinzugefuegt')
            : bestehend
              ? t('konto.speichern')
              : t('konto.hinzufuegen')}
        </Button>
        <Button variant="ghost" onClick={aufAbbrechen}>
          {t('aktion.abbrechen')}
        </Button>
      </div>
    </div>
  )
}

/* --- Bausteine ---------------------------------------------------------- */

function Hinweis({ art, text }: { art: 'info' | 'warnung'; text: string }) {
  const info = art === 'info'
  return (
    <div
      className={
        'flex gap-3 rounded-lg border px-4 py-3 text-[13px] text-fg-2 ' +
        (info ? 'border-info/40 bg-info-soft' : 'border-warning/40 bg-warning-soft')
      }
    >
      {info ? (
        <Info className="mt-0.5 size-4 shrink-0 text-info" />
      ) : (
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
      )}
      <p className="mb-0 min-w-0">{text}</p>
    </div>
  )
}

function Zeile({ ok, titel, text }: { ok: boolean; titel: string; text: string }) {
  return (
    <div
      className={
        'flex gap-3 rounded-lg border px-4 py-3 ' +
        (ok ? 'border-success/40 bg-success-soft' : 'border-danger/40 bg-danger-soft')
      }
    >
      {ok ? (
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
      ) : (
        <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />
      )}
      <div className="min-w-0">
        <p className="mb-0 text-[13px] font-medium text-fg-1">{titel}</p>
        {!ok && <p className="mb-0 text-[13px] text-fg-2">{text}</p>}
      </div>
    </div>
  )
}

interface BlockProps {
  titel: string
  server: string
  port: number
  sicherheit: string
  benutzer: string
  aufAendern: (teil: Partial<{ server: string; port: number; sicherheit: string; benutzer: string }>) => void
}

function Serverblock({ titel, server, port, sicherheit, benutzer, aufAendern }: BlockProps) {
  const { t } = useTranslation()
  return (
    <fieldset className="min-w-0 border-0 p-0">
      <legend className="mb-2 p-0 text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
        {titel}
      </legend>
      {/* ⚠️ **132 px, nicht 96.** Gemessen: „VERSCHLÜSSELUNG" ist 115 px breit
          und lief über den Rand; das Auswahlfeld braucht mit Polster und Pfeil
          rund 102 px und zeigte „STARTTI". Deutsche Beschriftungen sind
          durchweg länger als die englischen, an denen man so eine Spalte
          unwillkürlich bemisst. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_132px]">
        <Input
          label={t('konto.server')}
          value={server}
          mono
          size="sm"
          onChange={(e) => aufAendern({ server: e.target.value })}
        />
        <Input
          label={t('konto.port')}
          value={String(port)}
          mono
          size="sm"
          inputMode="numeric"
          onChange={(e) => aufAendern({ port: Number(e.target.value.replace(/\D/g, '')) || 0 })}
        />
        <Input
          label={t('konto.benutzer')}
          value={benutzer}
          mono
          size="sm"
          onChange={(e) => aufAendern({ benutzer: e.target.value })}
        />
        <Select
          label={t('konto.sicherheit')}
          size="sm"
          value={sicherheit}
          options={SICHERHEITEN}
          onChange={(e) => aufAendern({ sicherheit: e.target.value })}
        />
      </div>
    </fieldset>
  )
}
