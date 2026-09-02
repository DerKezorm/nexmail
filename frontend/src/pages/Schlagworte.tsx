/* Einstellungen -> Schlagworte: die Definitionen verwalten.
 *
 * Umbenennen aendert nur den Anzeige-Namen — das Atom ist das IMAP-Keyword
 * und steht auf den Mailservern; es umzubenennen hiesse, jede markierte Mail
 * ueberall anzufassen. Loeschen entfernt das Keyword von allen Mails, die
 * nexmail KENNT (der Server macht das je Konto und Ordner gebuendelt), und
 * dann die Definition — die Rueckfrage nennt die Zahl.
 *
 * ⚠️ Die Farben sind die sechs geprueften Postfachfarben — keine eigene
 * Palette, und jeder Farbknopf traegt einen vorlesbaren Namen: Farbe allein
 * ist keine Auskunft.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Tag, Trash2 } from 'lucide-react'
import { Button, EmptyState, IconButton, Input } from '../ds'
import { api, ApiFehler } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { PUNKT_KLASSE } from '../lib/farben'
import { Schlagwortmarke } from '../components/Schlagwortmarke'
import type { Postfachfarbe, Schlagwort } from '../daten/typen'

const FARBEN: Postfachfarbe[] = [1, 2, 3, 4, 5, 6]

/** Die Vorschau des Atoms — dieselbe Umschrift wie im Server
 *  (services/schlagworte.atom_aus_name). Nur eine Vorschau: Bei einer
 *  Kollision haengt der Server eine Zahl an. */
export function atomVorschau(name: string): string {
  const umschrift: Record<string, string> = {
    ä: 'ae', ö: 'oe', ü: 'ue', Ä: 'Ae', Ö: 'Oe', Ü: 'Ue', ß: 'ss',
  }
  const wort = name
    .trim()
    .replace(/[äöüÄÖÜß]/g, (z) => umschrift[z] ?? z)
    .replace(/\s+/g, '_')
    .replace(/[^A-Za-z0-9_-]+/g, '')
    .slice(0, 80)
  return wort || 'Schlagwort'
}

interface Props {
  /** Nach jeder AEnderung: die Mail-Ansicht nachziehen — was ich aendere,
   *  muss ich auch sehen. */
  aufGeaendert?: () => void
}

export function Schlagworte({ aufGeaendert }: Props) {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()

  /* ⚠️ Drei Zustaende statt zwei: noch nicht geladen (null) · geladen ·
     ging nicht. Ein Fehler darf nicht wie „keine Schlagworte" aussehen. */
  const [zeilen, setZeilen] = useState<Schlagwort[] | null>(null)
  const [ladefehler, setLadefehler] = useState('')
  const [stoerung, setStoerung] = useState('')
  const [neuerName, setNeuerName] = useState('')
  const [beschaeftigt, setBeschaeftigt] = useState(false)

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<Schlagwort[]>('/api/schlagworte'))
      setLadefehler('')
    } catch (f) {
      // Der alte Bestand bleibt stehen — ihn zu leeren erzeugte genau den
      // Schrecken, den ein Datenverlust macht.
      setLadefehler(f instanceof ApiFehler && f.detail ? f.detail : t('stoerung.stamm'))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  function fehlerText(f: unknown): string {
    const detail = f instanceof ApiFehler ? f.detail : ''
    if (detail === 'schlagwort_name_vergeben') return t('schlagworte.fehler_name_vergeben')
    if (detail === 'schlagwort_name_leer') return t('schlagworte.fehler_name_leer')
    if (detail === 'schlagwort_ordner_veraltet') return t('schlagworte.fehler_veraltet')
    return detail || t('anmeldung.fehler_allgemein')
  }

  async function anlegen() {
    const name = neuerName.trim()
    if (!name) return
    setBeschaeftigt(true)
    setStoerung('')
    try {
      await api.senden('/api/schlagworte', { name })
      setNeuerName('')
      await laden()
      aufGeaendert?.()
    } catch (f) {
      setStoerung(fehlerText(f))
    } finally {
      setBeschaeftigt(false)
    }
  }

  async function umbenennen(zeile: Schlagwort) {
    const name = await fragen({
      titel: t('schlagworte.umbenennen'),
      // ⚠️ Erst die Folgen: Nur die Anzeige aendert sich, das Keyword auf
      // dem Server bleibt — das steht im Text, bevor jemand zustimmt.
      text: t('schlagworte.umbenennen_hinweis', { atom: zeile.atom }),
      eingabe: { beschriftung: t('schlagworte.name'), vorgabe: zeile.name },
      knopf: t('schlagworte.umbenennen'),
    })
    if (typeof name !== 'string' || !name.trim() || name.trim() === zeile.name) return
    setStoerung('')
    try {
      await api.flicken(`/api/schlagworte/${zeile.id}`, { name: name.trim() })
      await laden()
      aufGeaendert?.()
    } catch (f) {
      setStoerung(fehlerText(f))
    }
  }

  async function farbeSetzen(zeile: Schlagwort, farbe: Postfachfarbe) {
    if (farbe === zeile.farbe) return
    setStoerung('')
    try {
      await api.flicken(`/api/schlagworte/${zeile.id}`, { farbe })
      await laden()
      aufGeaendert?.()
    } catch (f) {
      setStoerung(fehlerText(f))
    }
  }

  async function entfernen(zeile: Schlagwort) {
    const ja = await fragen({
      titel: t('schlagworte.entfernen'),
      /* ⚠️ Die Rueckfrage nennt die Zahl der betroffenen Mails — und sagt
         dazu, was das Loeschen NICHT abdeckt: Mails, die nexmail nie
         abgeglichen hat, behalten das Keyword auf dem Server. */
      text:
        t('schlagworte.entfernen_sicher', { name: zeile.name, count: zeile.anzahl }) +
        ' ' +
        t('schlagworte.entfernen_hinweis'),
      knopf: t('schlagworte.entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    setStoerung('')
    try {
      await api.loeschen(`/api/schlagworte/${zeile.id}`)
      await laden()
      aufGeaendert?.()
    } catch (f) {
      setStoerung(fehlerText(f))
    }
  }

  const vorschau = neuerName.trim() ? atomVorschau(neuerName) : ''

  return (
    <div className="flex flex-col gap-4">
      {ladefehler && (
        <div
          role="alert"
          className="flex items-center gap-3 rounded-lg border border-danger bg-danger-soft px-4 py-2.5"
        >
          <span className="min-w-0 flex-1 text-[13px] text-fg-1">{ladefehler}</span>
          <Button size="sm" onClick={() => void laden()}>
            {t('stoerung.nochmal')}
          </Button>
        </div>
      )}

      {stoerung && (
        <div role="alert" className="rounded-lg border border-danger bg-danger-soft px-4 py-2.5">
          <span className="text-[13px] text-danger">{stoerung}</span>
        </div>
      )}

      {zeilen !== null && zeilen.length === 0 && !ladefehler ? (
        <EmptyState
          icon={<Tag />}
          title={t('schlagworte.leer_titel')}
          description={t('schlagworte.leer_text')}
        />
      ) : (
        <ul className="flex list-none flex-col gap-2 p-0">
          {(zeilen ?? []).map((zeile) => (
            <li
              key={zeile.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
            >
              <Schlagwortmarke farbe={zeile.farbe} gross />
              <div className="min-w-0 flex-1">
                <p className="mb-0 truncate text-sm font-medium text-fg-1">{zeile.name}</p>
                {/* Das Atom sichtbar dazu: Es ist das, was Thunderbird und
                    das Telefon zeigen — wer dort sucht, braucht diese Form. */}
                <p className="mb-0 truncate font-mono text-[12px] text-fg-4">
                  {zeile.atom} · {t('schlagworte.anzahl_mails', { count: zeile.anzahl })}
                </p>
              </div>

              {/* Die Palette: sechs Knoepfe, jeder mit vorlesbarem Namen.
                  aria-pressed sagt, welcher gilt — der Ring zeigt es. */}
              <div
                className="flex shrink-0 items-center gap-1.5"
                role="group"
                aria-label={t('schlagworte.farbe_waehlen', { name: zeile.name })}
              >
                {FARBEN.map((farbe) => (
                  <button
                    key={farbe}
                    type="button"
                    aria-label={t(`schlagworte.farbe_${farbe}`)}
                    aria-pressed={zeile.farbe === farbe}
                    onClick={() => void farbeSetzen(zeile, farbe)}
                    className={
                      `h-5 w-7 rounded-[4px] ${PUNKT_KLASSE[farbe]} ` +
                      'transition-shadow duration-[var(--dur-fast)] ' +
                      (zeile.farbe === farbe
                        ? 'ring-2 ring-[var(--text-1)] ring-offset-2 ring-offset-[var(--surface-1)]'
                        : 'opacity-70 hover:opacity-100')
                    }
                  />
                ))}
              </div>

              <IconButton
                icon={<Pencil />}
                label={t('schlagworte.umbenennen')}
                size="sm"
                onClick={() => void umbenennen(zeile)}
              />
              <IconButton
                icon={<Trash2 />}
                label={t('schlagworte.entfernen')}
                size="sm"
                onClick={() => void entfernen(zeile)}
              />
            </li>
          ))}
        </ul>
      )}

      {/* Anlegen: Name eintippen, das Atom steht als Vorschau daneben —
          niemand soll erst nach dem Speichern erfahren, was auf dem Server
          landet. */}
      <div className="flex max-w-[480px] flex-col gap-2">
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <Input
              label={t('schlagworte.name')}
              placeholder={t('schlagworte.name_platzhalter')}
              value={neuerName}
              onChange={(e) => setNeuerName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && neuerName.trim()) {
                  e.preventDefault()
                  void anlegen()
                }
              }}
            />
          </div>
          <Button
            iconLeft={<Plus className="size-4" />}
            disabled={!neuerName.trim() || beschaeftigt}
            onClick={() => void anlegen()}
          >
            {t('schlagworte.anlegen')}
          </Button>
        </div>
        {vorschau && (
          <p className="mb-0 text-[12px] text-fg-4">
            {t('schlagworte.atom_vorschau')}{' '}
            <span className="font-mono text-fg-3">{vorschau}</span>
          </p>
        )}
      </div>

      {nachfrage}
    </div>
  )
}
