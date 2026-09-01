/* Das Verfassen-Fenster.
 *
 * Eigenes Fenster über der App, Rest abgedunkelt — so entschieden, weil ein
 * eingebettetes Schreibfeld in der rechten Spalte mit dieser Formatierleiste
 * zu schmal würde.
 *
 * ⚠️ **Zur Ein-Ausgang-Regel:** Oben steht ein Kreuz UND unten „Verwerfen" —
 * das sieht nach zwei Ausgängen aus, ist aber keiner. Die Regel verbietet
 * zwei Knöpfe, die *dasselbe* tun. Hier schließt das Kreuz und behält den
 * Entwurf, „Verwerfen" wirft ihn weg. Wer den Unterschied wegkürzt, baut
 * genau die Falle, vor der die Regel schützt: ein Fenster, aus dem man nur
 * herauskommt, indem man seine Arbeit löscht.
 *
 * ⚠️ **Scheitert der Versand, bleibt das Fenster offen** und sagt, was los
 * ist. Die Mail liegt dann im Ausgang — geschlossen zu werden, während man
 * nicht weiß, ob sie draußen ist, ist der schlechteste aller Zustände.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Paperclip, PenLine, Send, Trash2, X } from 'lucide-react'
import { Button, IconButton } from '../ds'
import { Adressfeld } from './Adressfeld'
import { Editor } from './Editor'
import { api, ApiFehler } from '../api/client'
import type { Konto, Nachricht } from '../daten/typen'
import { groesse } from '../lib/format'

export type Verfassart = 'neu' | 'antwort' | 'allen' | 'weiter' | 'entwurf'

interface Anlage {
  dateiname: string
  mime_typ: string
  inhalt_b64: string
  cid: string
  groesse: number
}

interface Vorlage {
  konto_id: string
  an: string[]
  kopie: string[]
  betreff: string
  html: string
  in_reply_to: string
  references: string[]
  entwurf_uid?: number
  signatur?: string
}

interface Props {
  offen: boolean
  art: Verfassart
  bezug: Nachricht | null
  konten: Konto[]
  aufSchliessen: () => void
  aufGesendet?: () => void
}

export function VerfassenFenster({ offen, art, bezug, konten, aufSchliessen, aufGesendet }: Props) {
  const { t } = useTranslation()

  const [kontoId, setKontoId] = useState('')
  const [an, setAn] = useState('')
  const [kopie, setKopie] = useState('')
  const [blindkopie, setBlindkopie] = useState('')
  const [betreff, setBetreff] = useState('')
  const [html, setHtml] = useState('')
  const [anlagen, setAnlagen] = useState<Anlage[]>([])

  const [kopieZeigen, setKopieZeigen] = useState(false)
  const [blindZeigen, setBlindZeigen] = useState(false)
  const [sendet, setSendet] = useState(false)
  const [fehler, setFehler] = useState('')
  // Die UID der Fassung im Entwurfsordner. 0 heißt: noch nie gespeichert.
  // Wird beim Speichern gesetzt, damit das nächste Mal **ersetzt** wird —
  // sonst wächst der Entwurfsordner mit jedem Speichern.
  // ⚠️ **Zwei Adressen für dasselbe Bild.** Im Editor muss eine stehen, die
  // der Browser anzeigen kann (``blob:``); in der fertigen Mail eine, die der
  // Empfänger auflösen kann (``cid:``). Hier steht, welche zu welcher gehört —
  // beim Senden wird getauscht. Vorher stand ``cid:`` schon im Editor, und
  // das gab ein kaputtes Bildsymbol.
  const [bildquellen, setBildquellen] = useState<Record<string, string>>({})
  const [entwurfUid, setEntwurfUid] = useState(0)
  const [speichert, setSpeichert] = useState(false)
  const [laedt, setLaedt] = useState(false)

  /* --- Öffnen: Vorlage holen ------------------------------------------- */

  useEffect(() => {
    if (!offen) return
    setFehler('')
    setAnlagen([])
    setBlindkopie('')
    setBlindZeigen(false)

    setEntwurfUid(0)

    if (art === 'neu' || !bezug) {
      const konto = konten[0]?.id ?? ''
      setKontoId(konto)
      setAn('')
      setKopie('')
      setKopieZeigen(false)
      setBetreff('')
      setHtml('<p></p>')
      // Die Signatur kommt aus dem Server — eine neue Nachricht hat keine
      // Bezugsnachricht und geht deshalb nicht über /vorlage.
      if (konto) {
        void api
          .holen<{ html: string }>(`/api/verfassen/signatur/${konto}`)
          .then((s) => setHtml(s.html ? `<p></p>${s.html}` : '<p></p>'))
          .catch(() => undefined)
      }
      return
    }

    // ⚠️ Empfänger, Betreff, Kette und Zitat baut der Server. In der
    // Oberfläche müsste man dieselben Regeln ein zweites Mal pflegen — und
    // das Zitat ist fremdes HTML und gehört durch dieselbe Bereinigung wie
    // beim Anzeigen.
    setLaedt(true)
    api
      .holen<Vorlage>(`/api/verfassen/vorlage/${bezug.id}?art=${art}`)
      .then((v) => {
        setKontoId(v.konto_id)
        setAn(v.an.join(', '))
        setKopie(v.kopie.join(', '))
        setKopieZeigen(v.kopie.length > 0)
        setBetreff(v.betreff)
        // ⚠️ Beim Weiterschreiben **keine** Leerzeilen davor: Der Text ist
        // der eigene, nicht ein Zitat, unter das man schreibt.
        // ⚠️ Beim Weiterschreiben **keine** Signatur nachlegen: Sie steht im
        // Entwurf schon drin, und ein zweites Mal wäre sie doppelt.
        setHtml(
          art === 'entwurf'
            ? v.html || '<p></p>'
            : `<p></p>${v.signatur ?? ''}<p></p>${v.html}`,
        )
        setEntwurfUid(v.entwurf_uid ?? 0)
        setKette({ in_reply_to: v.in_reply_to, references: v.references })
      })
      .catch(() => setFehler(t('anmeldung.fehler_allgemein')))
      .finally(() => setLaedt(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offen, art, bezug?.id])

  const [kette, setKette] = useState<{ in_reply_to: string; references: string[] }>({
    in_reply_to: '',
    references: [],
  })

  // ⚠️ Eine ``blob:``-Adresse hält die Datei im Speicher, bis sie freigegeben
  // wird. Wer zehnmal ein Bildschirmfoto einfügt und das Fenster schließt,
  // hätte sie sonst alle zehn noch im Browser liegen.
  useEffect(() => {
    if (offen) return
    for (const anzeige of Object.keys(bildquellen)) URL.revokeObjectURL(anzeige)
    setBildquellen({})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offen])

  useEffect(() => {
    if (!offen) return
    function beiTaste(e: KeyboardEvent) {
      if (e.key === 'Escape') void schliessenUndBewahren()
    }
    document.addEventListener('keydown', beiTaste)
    return () => document.removeEventListener('keydown', beiTaste)
  }, [offen, aufSchliessen])

  if (!offen) return null

  /* --- Anhänge ---------------------------------------------------------- */

  async function alsBase64(datei: File): Promise<string> {
    const puffer = await datei.arrayBuffer()
    let roh = ''
    const bytes = new Uint8Array(puffer)
    for (let i = 0; i < bytes.length; i += 0x8000) {
      roh += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
    }
    return btoa(roh)
  }

  async function anhaengen(dateien: FileList | null) {
    if (!dateien) return
    for (const datei of Array.from(dateien)) {
      setAnlagen((alt) => [
        ...alt,
        {
          dateiname: datei.name,
          mime_typ: datei.type || 'application/octet-stream',
          inhalt_b64: '',
          cid: '',
          groesse: datei.size,
        },
      ])
      const b64 = await alsBase64(datei)
      setAnlagen((alt) =>
        alt.map((a) => (a.dateiname === datei.name && !a.inhalt_b64 ? { ...a, inhalt_b64: b64 } : a)),
      )
    }
  }

  /** Ein Bild im Text: als Anhang mit ``cid`` — nicht als data:-URI.
   *
   * ⚠️ **Zurück kommt eine ``blob:``-Adresse, keine ``cid:``.** Ein Browser
   * kann ``cid:`` nicht auflösen — im Editor stand dann ein kaputtes
   * Bildsymbol. Getauscht wird erst beim Senden, in ``nutzdaten``.
   *
   * ``data:`` wäre die bequemere Anzeige, taugt aber nicht: Der Editorinhalt
   * wanderte dann samt Bild in jede Entwurfsfassung, und ein
   * Bildschirmfoto bläht das auf Megabyte.
   */
  async function bildEinfuegen(datei: File): Promise<string> {
    const kennung = `bild${Date.now()}${Math.floor(Math.random() * 1000)}`
    const b64 = await alsBase64(datei)
    setAnlagen((alt) => [
      ...alt,
      {
        dateiname: datei.name || `${kennung}.png`,
        mime_typ: datei.type || 'image/png',
        inhalt_b64: b64,
        cid: kennung,
        groesse: datei.size,
      },
    ])
    const anzeige = URL.createObjectURL(datei)
    setBildquellen((alt) => ({ ...alt, [anzeige]: kennung }))
    return anzeige
  }

  function anlageWeg(index: number) {
    setAnlagen((alt) => alt.filter((_, i) => i !== index))
  }

  /* --- Senden ----------------------------------------------------------- */

  function adressen(roh: string): string[] {
    return roh
      .split(/[,;]/)
      .map((a) => a.trim())
      .filter(Boolean)
  }

  /** Was in beide Wege geht — Senden und Aufbewahren bauen dieselbe Mail. */
  function nutzdaten() {
    // ⚠️ **Hier wird die Anzeige-Adresse gegen die Mail-Adresse getauscht.**
    // Im Editor steht ``blob:…``, damit der Browser das Bild zeigen kann; in
    // der Mail muss ``cid:…`` stehen, sonst findet der Empfänger den Anhang
    // nicht. Eine ``blob:``-Adresse, die hinausginge, wäre beim Empfänger ein
    // kaputtes Bild — und beim Absender sähe alles richtig aus.
    let fertig = html
    for (const [anzeige, kennung] of Object.entries(bildquellen)) {
      fertig = fertig.split(anzeige).join(`cid:${kennung}`)
    }

    // Was der Betreiber wieder aus dem Text gelöscht hat, fährt nicht mit.
    // Sonst hängt an der Mail ein Bild, das niemand sieht und das trotzdem
    // zählt — bei einer 25-MB-Grenze macht das den Unterschied.
    const gebraucht = anlagen.filter((a) => !a.cid || fertig.includes(`cid:${a.cid}`))

    return {
      konto_id: kontoId,
      an: adressen(an),
      kopie: adressen(kopie),
      blindkopie: adressen(blindkopie),
      betreff,
      html: fertig,
      anlagen: gebraucht
        .filter((a) => a.inhalt_b64)
        .map(({ dateiname, mime_typ, inhalt_b64, cid }) => ({
          dateiname,
          mime_typ,
          inhalt_b64,
          cid,
        })),
      in_reply_to: kette.in_reply_to,
      references: kette.references,
      entwurf_uid: entwurfUid,
    }
  }

  /** Steht überhaupt etwas drin, das man aufbewahren müsste? */
  function hatInhalt() {
    const rumpf = html.replace(/<[^>]*>/g, '').trim()
    return Boolean(
      rumpf || betreff.trim() || an.trim() || kopie.trim() || blindkopie.trim() || anlagen.length,
    )
  }

  /* ⚠️ **Das Kreuz bewahrt auf, „Verwerfen" wirft weg.** Zwei Ausgänge, die
     Verschiedenes tun — das ist der eine erlaubte Fall von zwei Ausgängen an
     einem Fenster. Vorher taten beide dasselbe, weil es keinen Ort für einen
     Entwurf gab; jetzt gibt es ihn. */
  async function schliessenUndBewahren() {
    if (!hatInhalt() || !kontoId) {
      aufSchliessen()
      return
    }
    setSpeichert(true)
    try {
      const { uid } = await api.senden<{ uid: number }>('/api/verfassen/entwurf', nutzdaten())
      setEntwurfUid(uid)
      aufGesendet?.()
      aufSchliessen()
    } catch (f) {
      // ⚠️ **Nicht schließen, wenn das Aufbewahren scheitert.** Sonst ist der
      // Text weg, und nexmail hat es nicht einmal gesagt.
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('verfassen.entwurf_fehler'))
    } finally {
      setSpeichert(false)
    }
  }

  async function verwerfen() {
    if (entwurfUid && kontoId) {
      try {
        await api.loeschen(`/api/verfassen/entwurf/${entwurfUid}?konto_id=${kontoId}`)
        aufGesendet?.()
      } catch {
        // Weggeworfen ist weggeworfen: Der Betreiber wollte den Text nicht
        // mehr. Eine liegengebliebene Fassung ist kein Grund, ihn im Fenster
        // festzuhalten.
      }
    }
    aufSchliessen()
  }

  async function senden() {
    setFehler('')
    setSendet(true)
    try {
      const ergebnis = await api.senden<{ stand: string; fehler: string }>(
        '/api/verfassen/senden',
        nutzdaten(),
      )

      if (ergebnis.stand === 'gesendet') {
        aufGesendet?.()
        aufSchliessen()
        return
      }
      // Nicht draußen, aber auch nicht weg: Sie liegt im Ausgang.
      setFehler(t('verfassen.im_ausgang', { grund: ergebnis.fehler }))
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setSendet(false)
    }
  }

  const bereit = adressen(an).length + adressen(kopie).length + adressen(blindkopie).length > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--surface-overlay)] p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) void schliessenUndBewahren()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={art === 'neu' ? t('verfassen.titel_neu') : t('verfassen.titel_antwort')}
        className="flex h-full max-h-[760px] w-full max-w-[860px] flex-col overflow-hidden rounded-xl border border-line bg-surface-1 shadow-[var(--shadow-3)]"
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-line-subtle px-4 py-3">
          <PenLine className="size-4 shrink-0 text-fg-3" />
          <h2 className="min-w-0 flex-1 truncate font-display text-[16px] font-medium text-fg-1">
            {betreff || t('verfassen.titel_neu')}
          </h2>
          <IconButton
            icon={<X />}
            label={t('verfassen.schliessen_bewahrt')}
            size="sm"
            disabled={speichert}
            onClick={() => void schliessenUndBewahren()}
          />
        </div>

        <div className="shrink-0 divide-y divide-[var(--border-subtle)] border-b border-line-subtle">
          <Zeile beschriftung={t('verfassen.von')}>
            <select
              value={kontoId}
              onChange={(e) => setKontoId(e.target.value)}
              className="min-w-0 flex-1 cursor-pointer bg-transparent text-sm text-fg-1 outline-none"
            >
              {konten.map((k) => (
                <option key={k.id} value={k.id} className="bg-surface-1 text-fg-1">
                  {k.anzeigename} — {k.adresse}
                </option>
              ))}
            </select>
          </Zeile>

          <Zeile beschriftung={t('verfassen.an')}>
            <Adressfeld
              wert={an}
              aufAendern={setAn}
              platzhalter={t('verfassen.empfaenger_platzhalter')}
            />
            {!kopieZeigen && (
              <Umschalter text={t('verfassen.kopie_zeigen')} onClick={() => setKopieZeigen(true)} />
            )}
            {!blindZeigen && (
              <Umschalter text={t('verfassen.blindkopie_zeigen')} onClick={() => setBlindZeigen(true)} />
            )}
          </Zeile>

          {kopieZeigen && (
            <Zeile beschriftung={t('verfassen.kopie')}>
              <Adressfeld
                wert={kopie}
                aufAendern={setKopie}
                platzhalter={t('verfassen.empfaenger_platzhalter')}
              />
            </Zeile>
          )}

          {blindZeigen && (
            <Zeile beschriftung={t('verfassen.blindkopie')}>
              <Adressfeld
                wert={blindkopie}
                aufAendern={setBlindkopie}
                platzhalter={t('verfassen.empfaenger_platzhalter')}
              />
            </Zeile>
          )}

          <Zeile beschriftung={t('verfassen.betreff')}>
            <input
              value={betreff}
              onChange={(e) => setBetreff(e.target.value)}
              placeholder={t('verfassen.betreff_platzhalter')}
              className="min-w-0 flex-1 bg-transparent text-sm font-medium text-fg-1 outline-none placeholder:text-fg-4"
            />
          </Zeile>
        </div>

        {laedt ? (
          <div className="min-h-0 flex-1" />
        ) : (
          <Editor inhalt={html} aufAendern={setHtml} aufBild={bildEinfuegen} />
        )}

        {anlagen.length > 0 && (
          <ul className="flex shrink-0 list-none flex-wrap gap-2 border-t border-line-subtle px-4 py-2">
            {anlagen
              .filter((a) => !a.cid)
              .map((a, i) => (
                <li
                  key={`${a.dateiname}-${i}`}
                  className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-1.5"
                >
                  <Paperclip className="size-3.5 shrink-0 text-fg-4" />
                  <span className="max-w-[24ch] truncate text-[12px] text-fg-1">{a.dateiname}</span>
                  <span className="text-[11px] tabular-nums text-fg-4">{groesse(a.groesse, 'de')}</span>
                  <button
                    type="button"
                    onClick={() => anlageWeg(i)}
                    aria-label={t('aktion.loeschen')}
                    className="text-fg-4 hover:text-danger"
                  >
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
          </ul>
        )}

        {fehler && (
          <p
            role="alert"
            className="mb-0 shrink-0 border-t border-line-subtle bg-danger-soft px-4 py-2 text-[13px] text-fg-1"
          >
            {fehler}
          </p>
        )}

        <div className="flex shrink-0 items-center gap-2 border-t border-line-subtle px-4 py-3">
          <Button
            variant="primary"
            iconLeft={<Send className="size-4" />}
            loading={sendet}
            disabled={!bereit || !kontoId}
            onClick={() => void senden()}
          >
            {t('aktion.senden')}
          </Button>

          <label className="cursor-pointer">
            <input
              type="file"
              multiple
              className="sr-only"
              onChange={(e) => void anhaengen(e.target.files)}
            />
            <span className="inline-flex h-[var(--control-h-md)] items-center gap-2 rounded-md border border-transparent px-3.5 text-sm font-medium text-fg-2 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-1">
              <Paperclip className="size-4" />
              {t('verfassen.anhang')}
            </span>
          </label>

          <span className="flex-1" />
          <Button
            variant="danger"
            iconLeft={<Trash2 className="size-4" />}
            onClick={() => void verwerfen()}
          >
            {t('verfassen.verwerfen')}
          </Button>
        </div>
      </div>
    </div>
  )
}

function Zeile({ beschriftung, children }: { beschriftung: string; children: React.ReactNode }) {
  return (
    <div className="flex h-10 items-center gap-2 px-4">
      {/* 96 px, weil „BLINDKOPIE" gemessene 80 px braucht — bei den 64 px
          davor lief es ins Eingabefeld hinein. `truncate` steht daneben als
          Sicherung für eine dritte Sprache mit einem längeren Wort. */}
      <span
        title={beschriftung}
        className="w-24 shrink-0 truncate text-[12px] font-semibold tracking-[0.06em] text-fg-4 uppercase"
      >
        {beschriftung}
      </span>
      {children}
    </div>
  )
}

function Umschalter({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 rounded-sm px-1.5 py-0.5 text-[12px] text-fg-4 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 hover:text-fg-2"
    >
      {text}
    </button>
  )
}
