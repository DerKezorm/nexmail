/* Eine nextasks-Aufgabe in nexmail: ansehen, ändern, neu anlegen (MAIL-2).
 *
 * ⚠️ **Gespeichert wird in nextasks, und nur was sich geändert hat** (AC-4,
 * `aenderungen()`). Die Wiederholung zeigt das Fenster nur an: `/api/v1` kann
 * sie nicht setzen, das geht in nextasks.
 *
 * ⚠️ **In einer Liste, in der das Konto nur lesen darf**, ist alles gesperrt
 * und es gibt kein Speichern (AC-4).
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ExternalLink, Mail, Plus, Repeat, Trash2 } from 'lucide-react'
import { Button, Checkbox, Dialog, Input, Select } from '../ds'
import { servermeldung } from '../lib/servermeldung'
import {
  aenderungen,
  fernaufgabe,
  fernAendern,
  fernAnlegen,
  fernLoeschen,
  mitglieder,
  schlagworteAus,
  type Fernaufgabe,
  type NtBereich,
  type NtPerson,
} from '../api/nextasks'

interface Props {
  /** Offen mit dieser Aufgabe (ändern) … */
  aufgabe: Fernaufgabe | null
  /** … oder neu in dieser Liste (`neu` gesetzt, `aufgabe` null). */
  neu: { listeId: string } | null
  bereiche: NtBereich[]
  /** nextasks kennt Mitglieder: Zuständige wählbar (sonst nur Anzeige). */
  mitgliederAn: boolean
  aufZu: () => void
  aufGespeichert: () => void
  aufMail: (nachrichtId: number) => void
}

const BESCHRIFTUNG = 'text-[12px] font-semibold uppercase tracking-[0.06em] text-fg-3'

export function NextasksAufgabe({ aufgabe, neu, bereiche, mitgliederAn, aufZu, aufGespeichert, aufMail }: Props) {
  const { t } = useTranslation()
  const offen = aufgabe !== null || neu !== null
  const [voll, setVoll] = useState<Fernaufgabe | null>(null)
  const [titel, setTitel] = useState('')
  const [notiz, setNotiz] = useState('')
  const [tag, setTag] = useState('')
  const [zeit, setZeit] = useState('')
  const [prio, setPrio] = useState(0)
  const [markiert, setMarkiert] = useState(false)
  const [schlagworte, setSchlagworte] = useState('')
  const [ort, setOrt] = useState('')
  const [zustaendige, setZustaendige] = useState<number[]>([])
  const [leute, setLeute] = useState<NtPerson[] | null>(null)
  const [teil, setTeil] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  /** Kennung dieses Anlegens; derselbe Wert zweimal ergibt eine Aufgabe (EC-10). */
  const [anfrage, setAnfrage] = useState('')
  const [fehler, setFehler] = useState('')

  /** Jede beschreibbare Liste und ihre Abschnitte als `liste|abschnitt`. */
  const orte = useMemo(
    () =>
      bereiche.flatMap((b) =>
        b.listen
          .filter((l) => l.beschreibbar || l.id === aufgabe?.liste_id)
          .flatMap((l) => [
            { wert: `${l.id}|`, text: `${b.name} › ${l.name}`, bereich: b },
            ...l.abschnitte.map((a) => ({ wert: `${l.id}|${a.id}`, text: `${b.name} › ${l.name} › ${a.name}`, bereich: b })),
          ]),
      ),
    [bereiche, aufgabe?.liste_id],
  )

  useEffect(() => {
    if (!offen) return
    setFehler('')
    setTeil('')
    setAnfrage(crypto.randomUUID())
    setLeute(null)
    const a = aufgabe
    setVoll(a)
    setTitel(a?.titel ?? '')
    setNotiz(a?.notiz ?? '')
    setTag(a?.faellig_tag ?? '')
    setZeit(a?.faellig_zeit ?? '')
    setPrio(a?.prioritaet ?? 0)
    setMarkiert(a?.markiert ?? false)
    setSchlagworte((a?.schlagworte ?? []).join(', '))
    setOrt(a ? `${a.liste_id}|${a.abschnitt_id ?? ''}` : `${neu?.listeId ?? ''}|`)
    setZustaendige((a?.zustaendige ?? []).map((z) => z.id))
    if (!a) return
    // Der Einzelabruf bringt die Teilaufgaben und den frischen Stand.
    let lebt = true
    void fernaufgabe(a.id)
      .then((f) => lebt && setVoll(f))
      .catch(() => undefined)
    return () => {
      lebt = false
    }
  }, [offen, aufgabe, neu])

  const bereich = orte.find((o) => o.wert === ort)?.bereich ?? null
  const listeId = ort.split('|')[0]
  const abschnittId = ort.split('|')[1] || null
  const schreibbar = aufgabe ? aufgabe.beschreibbar : true

  useEffect(() => {
    if (!offen || !mitgliederAn || !bereich?.geteilt) {
      setLeute(null)
      return
    }
    let lebt = true
    void mitglieder(bereich.id)
      .then((m) => lebt && setLeute(m))
      .catch(() => lebt && setLeute(null))
    return () => {
      lebt = false
    }
  }, [offen, mitgliederAn, bereich?.id, bereich?.geteilt])

  async function speichern() {
    if (laeuft || !titel.trim() || !listeId) return
    setLaeuft(true)
    setFehler('')
    try {
      const felder = {
        titel: titel.trim(),
        notiz,
        faellig_tag: tag || null,
        faellig_zeit: tag ? zeit || null : null,
        prioritaet: prio,
        markiert,
        schlagworte: schlagworteAus(schlagworte),
        zustaendige,
        liste_id: listeId,
        abschnitt_id: abschnittId,
      }
      if (aufgabe) {
        const nur = aenderungen(voll ?? aufgabe, felder)
        if (Object.keys(nur).length) await fernAendern(aufgabe.id, nur)
      } else {
        await fernAnlegen({
          ...felder,
          anfrage,
          notiz: notiz || undefined,
          schlagworte: felder.schlagworte.length ? felder.schlagworte : undefined,
          zustaendige: zustaendige.length ? zustaendige : undefined,
        })
      }
      aufGespeichert()
      aufZu()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function weg() {
    if (!aufgabe || laeuft) return
    setLaeuft(true)
    try {
      await fernLoeschen(aufgabe.id)
      aufGespeichert()
      aufZu()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function teilHaken(k: Fernaufgabe) {
    try {
      await fernAendern(k.id, { erledigt: !k.erledigt })
      if (aufgabe) setVoll(await fernaufgabe(aufgabe.id))
      aufGespeichert()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function teilNeu() {
    if (!aufgabe || !teil.trim()) return
    try {
      await fernAnlegen({ liste_id: aufgabe.liste_id, titel: teil.trim(), eltern_id: aufgabe.id })
      setTeil('')
      setVoll(await fernaufgabe(aufgabe.id))
      aufGespeichert()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  const personen: NtPerson[] = leute ?? aufgabe?.zustaendige ?? []

  return (
    <Dialog
      open={offen}
      width={560}
      title={aufgabe ? t('nextasks.aufgabe') : t('nextasks.neue_aufgabe')}
      onClose={aufZu}
      abweisbar={!laeuft}
      footer={
        <>
          {aufgabe && schreibbar && (
            <Button variant="ghost" iconLeft={<Trash2 className="size-4" />} onClick={() => void weg()} disabled={laeuft}>
              {t('nextasks.in_papierkorb')}
            </Button>
          )}
          <span className="flex-1" />
          <Button variant="secondary" onClick={aufZu} disabled={laeuft}>
            {schreibbar ? t('aktion.abbrechen') : t('aktion.schliessen')}
          </Button>
          {schreibbar && (
            <Button variant="primary" type="submit" form="nextasks-aufgabe" disabled={laeuft || !titel.trim() || !listeId}>
              {aufgabe ? t('aktion.speichern') : t('aufgaben.anlegen')}
            </Button>
          )}
        </>
      }
    >
      <form
        id="nextasks-aufgabe"
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void speichern()
        }}
      >
        <Input
          autoFocus={!aufgabe}
          label={t('aufgaben.titel')}
          value={titel}
          maxLength={500}
          disabled={!schreibbar}
          onChange={(e) => setTitel(e.target.value)}
        />

        <Select
          label={t('aufgaben.liste')}
          value={ort}
          disabled={!schreibbar}
          onChange={(e) => setOrt(e.target.value)}
        >
          {orte.map((o) => (
            <option key={o.wert} value={o.wert} className="bg-surface-1 text-fg-1">
              {o.text}
            </option>
          ))}
        </Select>

        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1.5">
            <span className={BESCHRIFTUNG}>{t('aufgaben.faellig')}</span>
            <input
              type="date"
              value={tag}
              disabled={!schreibbar}
              onChange={(e) => setTag(e.target.value)}
              className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className={BESCHRIFTUNG}>{t('nextasks.uhrzeit')}</span>
            <input
              type="time"
              value={zeit}
              disabled={!schreibbar || !tag}
              onChange={(e) => setZeit(e.target.value)}
              className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none disabled:opacity-50"
            />
          </label>
        </div>

        {voll?.wiederholung && (
          <p className="mb-0 flex items-center gap-1.5 text-[12px] text-fg-3">
            <Repeat className="size-3.5" aria-hidden />
            {t('nextasks.wiederholt')}
          </p>
        )}

        <div className="grid grid-cols-2 items-end gap-3">
          <Select
            label={t('nextasks.prioritaet')}
            value={String(prio)}
            disabled={!schreibbar}
            onChange={(e) => setPrio(Number(e.target.value))}
          >
            {[0, 1, 2, 3].map((p) => (
              <option key={p} value={p} className="bg-surface-1 text-fg-1">
                {t(`nextasks.prio_${p}`)}
              </option>
            ))}
          </Select>
          <div className="pb-1">
            <Checkbox
              label={t('nextasks.markiert')}
              checked={markiert}
              disabled={!schreibbar}
              onCheckedChange={setMarkiert}
            />
          </div>
        </div>

        {/* Zuständige nur in geteilten Bereichen; ohne die Mitglieder aus
            nextasks stehen sie nur da (EC-3). */}
        {bereich?.geteilt && personen.length > 0 && (
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className={`mb-1 p-0 ${BESCHRIFTUNG}`}>{t('nextasks.zustaendig')}</legend>
            {leute ? (
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {leute.map((p) => (
                  <Checkbox
                    key={p.id}
                    label={p.name || t('nextasks.ehemalig')}
                    checked={zustaendige.includes(p.id)}
                    disabled={!schreibbar}
                    onCheckedChange={(an) =>
                      setZustaendige((alt) => (an ? [...alt, p.id] : alt.filter((x) => x !== p.id)))
                    }
                  />
                ))}
              </div>
            ) : (
              <p className="mb-0 text-[13px] text-fg-2">
                {personen.map((p) => p.name || t('nextasks.ehemalig')).join(', ')}
              </p>
            )}
          </fieldset>
        )}

        <Input
          label={t('nextasks.schlagworte')}
          hint={t('nextasks.schlagworte_hinweis')}
          value={schlagworte}
          disabled={!schreibbar}
          onChange={(e) => setSchlagworte(e.target.value)}
        />

        <label className="flex flex-col gap-1.5">
          <span className={BESCHRIFTUNG}>{t('nextasks.notiz')}</span>
          <textarea
            rows={4}
            value={notiz}
            maxLength={20000}
            disabled={!schreibbar}
            onChange={(e) => setNotiz(e.target.value)}
            className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none"
          />
        </label>

        {aufgabe && (
          <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
            <legend className={`mb-1 p-0 ${BESCHRIFTUNG}`}>{t('nextasks.teilaufgaben')}</legend>
            {(voll?.teilaufgaben_liste ?? []).map((k) => (
              <span key={k.id} className="flex items-center gap-2 text-[13px]">
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={k.erledigt}
                  aria-label={k.erledigt ? t('aufgaben.wieder_offen') : t('aufgaben.abhaken')}
                  disabled={!schreibbar}
                  onClick={() => void teilHaken(k)}
                  className={
                    'flex size-4 shrink-0 items-center justify-center rounded border ' +
                    (k.erledigt ? 'border-accent bg-accent text-on-accent' : 'border-line-strong hover:border-accent')
                  }
                >
                  {k.erledigt && <Check className="size-3" />}
                </button>
                <span className={k.erledigt ? 'text-fg-3 line-through' : 'text-fg-1'}>{k.titel}</span>
              </span>
            ))}
            {schreibbar && (
              <span className="flex items-center gap-2">
                <Plus className="size-4 text-fg-4" aria-hidden />
                <input
                  value={teil}
                  placeholder={t('nextasks.teilaufgabe_neu')}
                  aria-label={t('nextasks.teilaufgabe_neu')}
                  onChange={(e) => setTeil(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      void teilNeu()
                    }
                  }}
                  className="min-w-0 flex-1 bg-transparent py-1 text-[13px] text-fg-1 outline-none placeholder:text-fg-4"
                />
              </span>
            )}
          </fieldset>
        )}

        {aufgabe && (aufgabe.link || aufgabe.mail?.nachricht_id) && (
          <div className="flex flex-wrap gap-4 text-[13px]">
            {aufgabe.mail?.nachricht_id != null && (
              <button
                type="button"
                onClick={() => {
                  aufMail(aufgabe.mail!.nachricht_id!)
                  aufZu()
                }}
                className="inline-flex items-center gap-1 text-accent-text hover:underline"
              >
                <Mail className="size-3.5" aria-hidden />
                {t('nextasks.zur_mail')}
              </button>
            )}
            {aufgabe.link && (
              <a
                href={aufgabe.link}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 text-accent-text hover:underline"
              >
                {t('nextasks.in_nextasks_oeffnen')}
                <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
          </div>
        )}

        {!schreibbar && <p className="mb-0 text-[12px] text-fg-4">{t('nextasks.nur_lesen')}</p>}

        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}
      </form>
    </Dialog>
  )
}
