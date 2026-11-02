/* Das Fenster hinter „Zu Aufgabe machen", sobald eine Todo-App verbunden ist.
 *
 * ⚠️ **Ein Handgriff bleibt ein Handgriff.** Vorbelegt ist das Standardziel aus
 * den Einstellungen und der Betreff als Titel; Enter legt an. Wer nichts
 * ändern will, drückt nur Enter. Ohne verbundene App kommt dieses Fenster gar
 * nicht erst, dann bleibt es beim einen Klick von früher.
 *
 * ⚠️ **Gibt es zur Mail schon eine Aufgabe, sagt das Fenster wo**, statt eine
 * zweite anzulegen — auch wenn sie in einer anderen Liste liegt als der
 * gewählten. Der Server entscheidet das, nicht diese Seite.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink } from 'lucide-react'
import { api } from '../api/client'
import { Button, Dialog, Input, Select } from '../ds'
import { BASIS } from '../lib/basis'
import { servermeldung } from '../lib/servermeldung'
import {
  gruppenname,
  schnellwahl,
  zielname,
  type ZielGruppe,
  type ZielStand,
} from '../lib/aufgabenziele'
import type { AufgabenZeile } from '../pages/AufgabenPage'

export interface Mailkopf {
  id: number
  betreff: string
}

interface Props {
  /** Leer heißt: zu. */
  mails: Mailkopf[]
  aufZu: () => void
  /** Nach dem Anlegen, damit die Zahl an der Leiste stimmt. */
  aufFertig: () => void
}

interface Angelegt {
  aufgabe: AufgabenZeile
  neu: boolean
}

export function AufgabeAnlegen({ mails, aufZu, aufFertig }: Props) {
  const { t } = useTranslation()
  const offen = mails.length > 0
  const [gruppen, setGruppen] = useState<ZielGruppe[] | null>(null)
  const [ziel, setZiel] = useState('')
  const [titel, setTitel] = useState('')
  const [faellig, setFaellig] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  /** Was es schon gab — dann zeigt das Fenster das statt eines Formulars. */
  const [schonDa, setSchonDa] = useState<AufgabenZeile[]>([])

  useEffect(() => {
    if (!offen) return
    setTitel(mails.length === 1 ? mails[0].betreff : '')
    setFaellig('')
    setFehler('')
    setSchonDa([])
    setGruppen(null)
    let lebt = true
    void (async () => {
      try {
        const [stand, listen] = await Promise.all([
          api.holen<ZielStand>('/api/aufgabenziele'),
          api.holen<ZielGruppe[]>('/api/aufgabenziele/listen'),
        ])
        if (!lebt) return
        setGruppen(listen)
        // ⚠️ Ein Standard, dessen Liste gerade nicht kam, fällt auf die
        // eigene Liste zurück — sichtbar, nicht still beim Anlegen.
        const da = listen.some((g) => g.listen.some((l) => l.ziel === stand.standard))
        setZiel(da ? stand.standard : '')
      } catch (f) {
        if (!lebt) return
        setGruppen([])
        setZiel('')
        setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      }
    })()
    return () => {
      lebt = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offen, mails])

  const schnell = schnellwahl(new Date())

  async function anlegen() {
    setLaeuft(true)
    setFehler('')
    const gefunden: AufgabenZeile[] = []
    try {
      for (const m of mails) {
        const raus = await api.senden<Angelegt>('/api/aufgaben/mit-ziel', {
          nachricht_id: m.id,
          ziel,
          titel: mails.length === 1 ? titel : '',
          liste_name: ziel ? zielname(gruppen ?? [], ziel) : '',
          faellig: faellig || null,
          adresse: window.location.origin + BASIS,
        })
        if (!raus.neu) gefunden.push(raus.aufgabe)
      }
      aufFertig()
      if (gefunden.length) setSchonDa(gefunden)
      else aufZu()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      aufFertig()
    } finally {
      setLaeuft(false)
    }
  }

  const chip = (wert: string, text: string) => (
    <button
      key={text}
      type="button"
      aria-pressed={faellig === wert}
      onClick={() => setFaellig(wert)}
      className={
        'rounded-full border px-2.5 py-1 text-[12px] transition-colors duration-[var(--dur-fast)] ' +
        (faellig === wert
          ? 'border-accent bg-accent-soft text-accent-text'
          : 'border-line text-fg-2 hover:border-line-strong')
      }
    >
      {text}
    </button>
  )

  if (schonDa.length) {
    return (
      <Dialog
        open={offen}
        title={t('aufgaben.schon_da_titel')}
        onClose={aufZu}
        footer={
          <Button variant="primary" onClick={aufZu}>
            {t('aktion.schliessen')}
          </Button>
        }
      >
        <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[13px] text-fg-2">
          {schonDa.map((a) => (
            <li key={a.id} className="flex flex-col gap-0.5">
              <span className="text-fg-1">{a.betreff || t('liste.kein_betreff')}</span>
              <span className="flex items-center gap-2 text-[12px] text-fg-3">
                {a.fern_art ? (
                  <>
                    {a.fern_liste || gruppenname({ art: a.fern_art, name: '' })}
                    {a.fern_url && (
                      <a
                        href={a.fern_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-flex items-center gap-1 text-accent-text hover:underline"
                      >
                        {t('aufgaben.in_app_oeffnen')}
                        <ExternalLink className="size-3" aria-hidden />
                      </a>
                    )}
                  </>
                ) : (
                  t('aufgaben.in_nexmail')
                )}
              </span>
            </li>
          ))}
        </ul>
      </Dialog>
    )
  }

  return (
    <Dialog
      open={offen}
      title={mails.length > 1 ? t('aufgaben.mehrere_machen', { count: mails.length }) : t('aufgaben.machen')}
      onClose={aufZu}
      abweisbar={!laeuft}
      footer={
        <>
          <Button variant="ghost" onClick={aufZu} disabled={laeuft}>
            {t('aktion.abbrechen')}
          </Button>
          <Button
            variant="primary"
            type="submit"
            form="aufgabe-anlegen"
            disabled={laeuft || gruppen === null}
          >
            {t('aufgaben.anlegen')}
          </Button>
        </>
      }
    >
      <form
        id="aufgabe-anlegen"
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!laeuft && gruppen !== null) void anlegen()
        }}
      >
        {mails.length === 1 && (
          <Input
            autoFocus
            label={t('aufgaben.titel')}
            value={titel}
            maxLength={500}
            onChange={(e) => setTitel(e.target.value)}
          />
        )}

        <Select
          label={t('aufgaben.liste')}
          value={ziel}
          disabled={gruppen === null}
          onChange={(e) => setZiel(e.target.value)}
        >
          <option value="" className="bg-surface-1 text-fg-1">
            {t('todoapps.eigene_liste')}
          </option>
          {/* ⚠️ **Die App steht in jeder Zeile, keine Gruppen.** Eine
              geschlossene Auswahl zeigt nur die Zeile, nicht die Gruppe:
              Bei zwei Verbindungen stünde dort zweimal „Inbox". */}
          {(gruppen ?? []).flatMap((g) =>
            g.fehler
              ? [
                  <option key={g.verbindung_id} disabled value={`-${g.verbindung_id}`}>
                    {`${gruppenname(g)} › ${t('todoapps.liste_unerreichbar')}`}
                  </option>,
                ]
              : g.listen.map((l) => (
                  <option key={l.ziel} value={l.ziel} className="bg-surface-1 text-fg-1">
                    {`${gruppenname(g)} › ${l.name}`}
                  </option>
                )),
          )}
        </Select>

        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
            {t('aufgaben.faellig')}
          </span>
          <div className="flex flex-wrap items-center gap-2">
            {chip('', t('aufgaben.ohne_datum'))}
            {chip(schnell.heute, t('aufgaben.heute'))}
            {chip(schnell.morgen, t('aufgaben.morgen'))}
            {chip(schnell.woche, t('aufgaben.naechste_woche'))}
            <input
              type="date"
              aria-label={t('aufgaben.faellig')}
              value={faellig}
              onChange={(e) => setFaellig(e.target.value)}
              className="rounded-sm border border-line bg-surface-3 px-2 py-1 text-[12px] text-fg-1"
            />
          </div>
        </div>

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}
      </form>
    </Dialog>
  )
}
