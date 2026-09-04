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
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronsDown, ChevronsUp, Clock, FileText, Minus, Paperclip, PenLine, Send, Trash2, X } from 'lucide-react'
import type { Editor as TiptapEditor } from '@tiptap/react'
import { Button, IconButton } from '../ds'
import { Adressfeld } from './Adressfeld'
import { Editor } from './Editor'
import type { TextvorlagenZeile } from '../pages/Textvorlagen'
import { useNachfrage } from './Nachfrage'
import { api } from '../api/client'
import type { Konto, Nachricht } from '../daten/typen'
import { eigenerText, erwaehntAnhang } from '../lib/anhang'
import { groesse } from '../lib/format'
import { useGemerkt } from '../lib/haken'
import { servermeldung } from '../lib/servermeldung'

export type Verfassart = 'neu' | 'antwort' | 'allen' | 'weiter' | 'anhang' | 'entwurf'

/** Was beim Senden zum Server geht — und was „Senden rückholen" braucht, um
 *  das Fenster mit demselben Inhalt wieder zu öffnen. Der Inhalt bleibt dafür
 *  im Speicher des Browsers; er wird NICHT aus dem Entwurf zurückgeladen, den
 *  der Abbruch anlegt — der Umweg über MIME und Bereinigung könnte nur
 *  verlieren, nie gewinnen. */
export interface Sendedaten {
  konto_id: string
  /** Unter welcher Adresse gesendet wird. Leer = die Hauptadresse. */
  von_adresse: string
  an: string[]
  kopie: string[]
  blindkopie: string[]
  betreff: string
  html: string
  anlagen: Array<{ dateiname: string; mime_typ: string; inhalt_b64: string; cid: string }>
  in_reply_to: string
  references: string[]
  entwurf_uid: number
  wichtigkeit: 'hoch' | 'normal' | 'niedrig'
}

interface Anlage {
  dateiname: string
  mime_typ: string
  inhalt_b64: string
  cid: string
  groesse: number
}

interface Vorlage {
  konto_id: string
  /** Der Absender, den der Server für diese Antwort vorschlägt. */
  von_adresse?: string
  an: string[]
  kopie: string[]
  /** Nur beim Weiterschreiben eines Entwurfs gefüllt — die Bcc-Zeile schreibt
   *  der Abbruch eigens hinein, gewöhnliche Post trägt keine. */
  blindkopie?: string[]
  betreff: string
  html: string
  in_reply_to: string
  references: string[]
  entwurf_uid?: number
  signatur?: string
  /** Beim Weiterleiten als Anhang die Roh-.eml, beim Weiterschreiben eines
   *  Entwurfs dessen Anhänge — Bilder im Text tragen ihre cid. */
  anlagen?: Array<{ dateiname: string; mime_typ: string; inhalt_b64: string; cid?: string }>
}

interface Props {
  offen: boolean
  art: Verfassart
  bezug: Nachricht | null
  konten: Konto[]
  /** Gesetzt beim Wieder-Öffnen nach „Rückgängig": Der Inhalt kommt aus dem
   *  Speicher, nicht vom Server — Vorlage und Signatur werden nicht geholt. */
  wiederauf?: Sendedaten | null
  aufSchliessen: () => void
  aufGesendet?: () => void
  /** Die Nachricht ist mit Aufschub eingereiht — bis `bis` (ms-Zeitstempel)
   *  lässt sie sich über den Ausgangseintrag `ausgangId` zurückholen. */
  aufRueckholbar?: (ausgangId: string, bis: number, daten: Sendedaten) => void
}

/** Base64 zurück in Bytes — für die Anzeige wieder eingefügter Bilder. */
function b64ZuBlob(b64: string, typ: string): Blob {
  const roh = atob(b64)
  const bytes = new Uint8Array(roh.length)
  for (let i = 0; i < roh.length; i++) bytes[i] = roh.charCodeAt(i)
  return new Blob([bytes], { type: typ || 'application/octet-stream' })
}

export function VerfassenFenster({
  offen,
  art,
  bezug,
  konten,
  wiederauf,
  aufSchliessen,
  aufGesendet,
  aufRueckholbar,
}: Props) {
  const { t } = useTranslation()

  const [kontoId, setKontoId] = useState('')
  /* ⚠️ **Leer heißt „die Hauptadresse".** Nicht der ausgeschriebene Wert:
     Wer die Hauptadresse eines Postfachs ändert, hätte sonst eine Wahl, die
     auf eine Adresse zeigt, die es nicht mehr gibt — und der Server wiese sie
     zu Recht ab. */
  const [vonAdresse, setVonAdresse] = useState('')
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
  /* Die eingesetzte Signatur, wie sie hereinkam — für die Anhang-Erinnerung.
     Die schneidet sie vor der Prüfung ab: „Anlagen: siehe unten" in einer
     Signatur ist keine Ankündigung dieser einen Mail. Beim Weiterschreiben
     eines Entwurfs bleibt sie leer; die Signatur steckt dort schon im Text
     und lässt sich nicht mehr sicher vom eigenen unterscheiden. */
  const [signaturHtml, setSignaturHtml] = useState('')
  /* Die Wichtigkeit der Nachricht. Ein Knopf, drei Stufen im Kreis —
     Vorgabe normal, und normal erzeugt beim Senden keine Kopfzeile. */
  const [wichtigkeit, setWichtigkeit] = useState<'hoch' | 'normal' | 'niedrig'>('normal')
  const [speichert, setSpeichert] = useState(false)
  const [laedt, setLaedt] = useState(false)

  /* „Später senden": das kleine Aufklappmenü neben dem Senden-Knopf. Der
     eigene Zeitpunkt kommt aus einem datetime-local-Feld - der Browser liest
     ihn als Ortszeit, hinausgeschickt wird ISO in UTC. */
  const [planOffen, setPlanOffen] = useState(false)
  const [eigenerZeitpunkt, setEigenerZeitpunkt] = useState('')
  const planRef = useRef<HTMLDivElement | null>(null)

  /* Das Menü „Vorlage": wiederkehrende Antworten aus den Einstellungen. Ein
     Klick fügt den Baustein an der Schreibmarke ein — dafür hält `editorRef`
     die Tiptap-Instanz. Keine Vorlagen ist kein leeres Menü: Der eine
     Eintrag sagt es und verweist auf die Einstellungen. */
  const [vorlagen, setVorlagen] = useState<TextvorlagenZeile[] | null>(null)
  /* ⚠️ Ein gescheiterter Abruf ist von „da ist nichts" zu unterscheiden —
     sonst behauptet das Menue „Noch keine Vorlagen", obwohl es welche gibt. */
  const [vorlagenFehler, setVorlagenFehler] = useState(false)
  const [vorlagenOffen, setVorlagenOffen] = useState(false)
  const vorlagenRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<TiptapEditor | null>(null)

  /* „Senden rückholen" aus Einstellungen → Darstellung, in Sekunden. 0 heißt
     aus — dann verhält sich Senden exakt wie bisher. Eingestellt geht die
     Nachricht als kurzer Plan hinaus (senden_ab = jetzt + Aufschub), und die
     Leiste unten bietet so lange „Rückgängig" an. */
  const [rueckholen] = useGemerkt<number>('nexmail.rueckholen', 0)

  /* Die Anhang-Erinnerung fragt über useNachfrage — nie über window.confirm.
     ⚠️ Solange sie offen steht, darf Escape nicht nebenbei das ganze
     Verfassen-Fenster schließen: Beide Zuhörer hängen am Dokument, und ohne
     die Sperre täte ein „Abbrechen" per Taste zwei Dinge auf einmal. */
  const { fragen, fenster: nachfrage } = useNachfrage()
  const frageOffen = useRef(false)

  useEffect(() => {
    if (!planOffen) return
    function beiKlick(e: MouseEvent) {
      if (planRef.current && !planRef.current.contains(e.target as Node)) setPlanOffen(false)
    }
    document.addEventListener('mousedown', beiKlick)
    return () => document.removeEventListener('mousedown', beiKlick)
  }, [planOffen])

  useEffect(() => {
    if (!vorlagenOffen) return
    function beiKlick(e: MouseEvent) {
      if (vorlagenRef.current && !vorlagenRef.current.contains(e.target as Node)) {
        setVorlagenOffen(false)
      }
    }
    document.addEventListener('mousedown', beiKlick)
    return () => document.removeEventListener('mousedown', beiKlick)
  }, [vorlagenOffen])

  /* Die Vorlagen kommen beim Öffnen des Fensters — nicht erst beim Öffnen des
     Menüs, sonst stünde dort beim ersten Klick kurz gar nichts. Ein Fehlschlag
     wird als solcher gemerkt: Das Menü sagt dann „ließ sich nicht laden" mit
     einem Eintrag zum Nachholen — nicht „Noch keine Vorlagen". */
  const vorlagenLaden = useCallback(async () => {
    try {
      setVorlagen(await api.holen<TextvorlagenZeile[]>('/api/textvorlagen'))
      setVorlagenFehler(false)
    } catch {
      setVorlagenFehler(true)
    }
  }, [])

  useEffect(() => {
    if (!offen) return
    setVorlagenOffen(false)
    void vorlagenLaden()
  }, [offen, vorlagenLaden])

  /* --- Öffnen: Vorlage holen ------------------------------------------- */

  useEffect(() => {
    if (!offen) return
    setFehler('')
    setAnlagen([])
    setBlindkopie('')
    setBlindZeigen(false)
    setPlanOffen(false)
    setEigenerZeitpunkt('')

    setEntwurfUid(0)
    setWichtigkeit('normal')
    setSignaturHtml('')

    if (wiederauf) {
      /* Wieder-Öffnen nach „Rückgängig": alles kommt aus dem Speicher.
       * ⚠️ **Die Entwurfs-UID ist die vom Abbruch angelegte Fassung.** Der
       * Abbruch legt den Inhalt als Sicherheitsnetz in den Entwurfsordner
       * und meldet die UID zurück — daran hängt dieses Fenster: Senden oder
       * Speichern ersetzt sie, statt sie für immer liegen zu lassen.
       * ⚠️ **Bilder brauchen wieder eine `blob:`-Adresse.** Im gemerkten HTML
       * steht `cid:` (so ging es zum Server), und die alten `blob:`-Adressen
       * sind beim Schließen freigegeben worden — sie zu behalten hieße
       * kaputte Bildsymbole. */
      setEntwurfUid(wiederauf.entwurf_uid || 0)
      setKontoId(wiederauf.konto_id)
      setVonAdresse(wiederauf.von_adresse ?? '')
      setAn(wiederauf.an.length ? wiederauf.an.join(', ') + ', ' : '')
      setKopie(wiederauf.kopie.length ? wiederauf.kopie.join(', ') + ', ' : '')
      setKopieZeigen(wiederauf.kopie.length > 0)
      setBlindkopie(wiederauf.blindkopie.length ? wiederauf.blindkopie.join(', ') + ', ' : '')
      setBlindZeigen(wiederauf.blindkopie.length > 0)
      setBetreff(wiederauf.betreff)
      let inhalt = wiederauf.html
      const quellen: Record<string, string> = {}
      for (const a of wiederauf.anlagen) {
        if (!a.cid) continue
        const anzeige = URL.createObjectURL(b64ZuBlob(a.inhalt_b64, a.mime_typ))
        inhalt = inhalt.split(`cid:${a.cid}`).join(anzeige)
        quellen[anzeige] = a.cid
      }
      setBildquellen(quellen)
      setHtml(inhalt || '<p></p>')
      setAnlagen(
        wiederauf.anlagen.map((a) => ({
          ...a,
          // Die Größe fährt in den Sendedaten nicht mit - aus Base64 lässt
          // sie sich fürs Anzeigen genau genug zurückrechnen.
          groesse: Math.floor((a.inhalt_b64.length * 3) / 4),
        })),
      )
      setWichtigkeit(wiederauf.wichtigkeit)
      setKette({ in_reply_to: wiederauf.in_reply_to, references: wiederauf.references })
      return
    }

    if (art === 'neu' || !bezug) {
      const konto = konten[0]?.id ?? ''
      setKontoId(konto)
      setVonAdresse('')
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
          .then((s) => {
            setSignaturHtml(s.html ?? '')
            setHtml(s.html ? `<p></p>${s.html}` : '<p></p>')
          })
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
        // ⚠️ Auf eine Mail an die Zweitadresse wird von dort geantwortet —
        // der Server hat das entschieden, hier wird es nur übernommen.
        setVonAdresse(v.von_adresse ?? '')
        setAn(v.an.length ? v.an.join(', ') + ', ' : '')
        setKopie(v.kopie.length ? v.kopie.join(', ') + ', ' : '')
        setKopieZeigen(v.kopie.length > 0)
        // ⚠️ Ein wieder geöffneter Entwurf bringt seine Blindkopie mit — sie
        // stillschweigend fallen zu lassen verlöre Empfänger, und das Senden
        // der verstümmelten Fassung räumte über die UID auch noch die
        // vollständige weg.
        setBlindkopie((v.blindkopie ?? []).join(', '))
        setBlindZeigen((v.blindkopie ?? []).length > 0)
        setBetreff(v.betreff)
        // ⚠️ Beim Weiterschreiben **keine** Leerzeilen davor: Der Text ist
        // der eigene, nicht ein Zitat, unter das man schreibt.
        // ⚠️ Beim Weiterschreiben **keine** Signatur nachlegen: Sie steht im
        // Entwurf schon drin, und ein zweites Mal wäre sie doppelt.
        let inhalt =
          art === 'entwurf'
            ? v.html || '<p></p>'
            : `<p></p>${v.signatur ?? ''}<p></p>${v.html}`
        // Anhänge aus der Vorlage: die Roh-.eml beim Weiterleiten als Anhang,
        // die Anhänge des Entwurfs beim Weiterschreiben - beim Senden gehen
        // sie denselben Weg wie jeder von Hand angehängte Anhang. Bilder im
        // Text brauchen dazu eine `blob:`-Adresse, wie im wiederauf-Zweig:
        // `cid:` kann der Browser nicht anzeigen.
        const mitgebracht = (v.anlagen ?? []).map((a) => ({
          ...a,
          cid: a.cid ?? '',
          // Die Größe fährt in der Vorlage nicht mit - aus Base64 lässt
          // sie sich fürs Anzeigen genau genug zurückrechnen.
          groesse: Math.floor((a.inhalt_b64.length * 3) / 4),
        }))
        const quellen: Record<string, string> = {}
        for (const a of mitgebracht) {
          if (!a.cid) continue
          const anzeige = URL.createObjectURL(b64ZuBlob(a.inhalt_b64, a.mime_typ))
          inhalt = inhalt.split(`cid:${a.cid}`).join(anzeige)
          quellen[anzeige] = a.cid
        }
        setBildquellen(quellen)
        setHtml(inhalt)
        setEntwurfUid(v.entwurf_uid ?? 0)
        setSignaturHtml(art === 'entwurf' ? '' : (v.signatur ?? ''))
        setKette({ in_reply_to: v.in_reply_to, references: v.references })
        setAnlagen(mitgebracht)
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
      // Steht die Anhang-Nachfrage offen, gehört Escape ihr allein.
      if (e.key === 'Escape' && !frageOffen.current) void schliessenUndBewahren()
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
      von_adresse: vonAdresse,
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
      wichtigkeit,
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
      setFehler(servermeldung(f, t('verfassen.entwurf_fehler')))
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
    /* Die Anhang-Erinnerung: Steht im eigenen Text etwas von einem Anhang und
       hängt keiner dran, wird einmal nachgefragt. Abbrechen lässt das Fenster
       unverändert offen; mit Anhang oder ohne Treffer ändert sich nichts am
       bisherigen Weg. ⚠️ Gezählt werden **alle** Anlagen, auch eingefügte
       Bilder: Wer „anbei das Foto" schreibt und es in den Text setzt, hat es
       dran — eine Nachfrage wäre da schlicht falsch. */
    if (anlagen.length === 0 && erwaehntAnhang(eigenerText(html, signaturHtml))) {
      frageOffen.current = true
      const trotzdem = await fragen({
        titel: t('verfassen.anhang_frage_titel'),
        text: t('verfassen.anhang_frage_text'),
        knopf: t('aktion.senden'),
      })
      frageOffen.current = false
      if (trotzdem !== true) return
    }

    setFehler('')
    setSendet(true)
    try {
      const daten = nutzdaten()

      if (rueckholen > 0) {
        /* „Senden rückholen": derselbe Endpunkt wie „Später senden", nur mit
           dem Aufschub als **Dauer**. Der Server rechnet sie auf seine eigene
           Uhr um und hält die Nachricht so lange im Ausgang — genau dort holt
           „Rückgängig" sie wieder heraus.
           ⚠️ Ein Zeitpunkt von hier hinge an der Client-Uhr: Ginge sie nach,
           wäre er beim Server schon vorbei, die Mail ginge sofort hinaus, und
           das Rückholen wäre bei jedem Senden still wirkungslos. `bis` dient
           nur der ablaufenden Leiste — ein reiner Countdown, keine Uhrzeit. */
        const bis = Date.now() + rueckholen * 1000
        const ergebnis = await api.senden<{
          id: string
          stand: string
          fehler: string
          senden_ab: string | null
        }>('/api/verfassen/senden', { ...daten, rueckhol_sekunden: rueckholen })

        if (ergebnis.senden_ab) {
          aufGesendet?.()
          aufRueckholbar?.(ergebnis.id, bis, daten)
          aufSchliessen()
          return
        }
        // ⚠️ War der Zeitpunkt beim Eintreffen schon vorbei (träges Netz),
        // sendet der Server sofort - dann gibt es nichts zurückzuholen, und
        // eine Leiste, die es trotzdem verspräche, wäre eine Lüge.
        if (ergebnis.stand === 'gesendet') {
          aufGesendet?.()
          aufSchliessen()
          return
        }
        setFehler(t('verfassen.im_ausgang', { grund: ergebnis.fehler }))
        return
      }

      const ergebnis = await api.senden<{ stand: string; fehler: string }>(
        '/api/verfassen/senden',
        daten,
      )

      if (ergebnis.stand === 'gesendet') {
        aufGesendet?.()
        aufSchliessen()
        return
      }
      // Nicht draußen, aber auch nicht weg: Sie liegt im Ausgang.
      setFehler(t('verfassen.im_ausgang', { grund: ergebnis.fehler }))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setSendet(false)
    }
  }

  /* --- Später senden ----------------------------------------------------- */

  function heute18(): Date {
    const d = new Date()
    d.setHours(18, 0, 0, 0)
    return d
  }

  function morgen8(): Date {
    const d = new Date()
    d.setDate(d.getDate() + 1)
    d.setHours(8, 0, 0, 0)
    return d
  }

  async function planen(zeitpunkt: Date) {
    setPlanOffen(false)
    setFehler('')
    setSendet(true)
    try {
      const ergebnis = await api.senden<{ stand: string; fehler: string; senden_ab: string | null }>(
        '/api/verfassen/senden',
        { ...nutzdaten(), senden_ab: zeitpunkt.toISOString() },
      )
      // ⚠️ Ein schon abgelaufener Zeitpunkt geht sofort hinaus - dann meldet
      // der Server „gesendet" statt eines Plans. Beides ist ein Erfolg.
      if (ergebnis.stand === 'gesendet' || ergebnis.senden_ab) {
        aufGesendet?.()
        aufSchliessen()
        return
      }
      setFehler(t('verfassen.im_ausgang', { grund: ergebnis.fehler }))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
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
            {/* ⚠️ **Eine Liste von ADRESSEN, nicht von Postfächern.** Aliasse
                als zweite Auswahl daneben hätten zwei Listen ergeben, die
                voneinander abhängen — und die Frage „welches Postfach?" stellt
                sich für den Schreibenden gar nicht, er wählt eine Absender-
                adresse. Wer keine Zweitadresse hat, merkt von alldem nichts:
                Die Liste sieht aus wie vorher. */}
            <select
              value={`${kontoId}|${vonAdresse}`}
              onChange={(e) => {
                const trenner = e.target.value.indexOf('|')
                setKontoId(e.target.value.slice(0, trenner))
                setVonAdresse(e.target.value.slice(trenner + 1))
              }}
              className="min-w-0 flex-1 cursor-pointer bg-transparent text-sm text-fg-1 outline-none"
            >
              {konten.flatMap((k) => [
                <option key={k.id} value={`${k.id}|`} className="bg-surface-1 text-fg-1">
                  {k.anzeigename} — {k.adresse}
                </option>,
                ...(k.aliase ?? []).map((a) => (
                  <option
                    key={`${k.id}-${a.adresse}`}
                    value={`${k.id}|${a.adresse}`}
                    className="bg-surface-1 text-fg-1"
                  >
                    {a.name || k.anzeigename} — {a.adresse}
                  </option>
                )),
              ])}
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
          <Editor
            inhalt={html}
            aufAendern={setHtml}
            aufBild={bildEinfuegen}
            aufEditor={(e) => {
              editorRef.current = e
            }}
          />
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

          {/* „Später senden" — dieselben Voraussetzungen wie Senden: Ohne
              Empfänger gibt es auch nichts zu planen. */}
          <div ref={planRef} className="relative">
            <Button
              iconLeft={<Clock className="size-4" />}
              disabled={!bereit || !kontoId || sendet}
              aria-expanded={planOffen}
              aria-haspopup="menu"
              onClick={() => setPlanOffen((o) => !o)}
            >
              {t('verfassen.spaeter')}
            </Button>

            {planOffen && (
              <div
                role="menu"
                aria-label={t('verfassen.spaeter')}
                className="absolute bottom-full left-0 z-10 mb-1 w-64 rounded-lg border border-line bg-surface-1 p-1 shadow-[var(--shadow-3)]"
              >
                <button
                  type="button"
                  role="menuitem"
                  // Nach 18 Uhr wäre „heute 18:00" ein Zeitpunkt in der
                  // Vergangenheit - der Eintrag sagt es, statt sofort zu senden.
                  disabled={heute18().getTime() <= Date.now()}
                  onClick={() => void planen(heute18())}
                  className="block w-full rounded-md px-2.5 py-1.5 text-left text-[13px] text-fg-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t('verfassen.spaeter_heute')}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => void planen(morgen8())}
                  className="block w-full rounded-md px-2.5 py-1.5 text-left text-[13px] text-fg-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3"
                >
                  {t('verfassen.spaeter_morgen')}
                </button>
                <div className="mt-1 border-t border-line-subtle px-2.5 pt-2 pb-1.5">
                  <label className="block text-[12px] text-fg-3">
                    {t('verfassen.spaeter_eigen')}
                    <input
                      type="datetime-local"
                      value={eigenerZeitpunkt}
                      onChange={(e) => setEigenerZeitpunkt(e.target.value)}
                      className="mt-1 w-full rounded-md border border-line bg-surface-2 px-2 py-1 text-[13px] text-fg-1 outline-none focus:border-accent"
                    />
                  </label>
                  <Button
                    size="sm"
                    variant="primary"
                    className="mt-2"
                    disabled={
                      !eigenerZeitpunkt || new Date(eigenerZeitpunkt).getTime() <= Date.now()
                    }
                    onClick={() => void planen(new Date(eigenerZeitpunkt))}
                  >
                    {t('verfassen.spaeter_planen')}
                  </Button>
                </div>
              </div>
            )}
          </div>

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

          {/* „Vorlage" — ein Klick fügt den Baustein an der Schreibmarke
              ein. Dasselbe Menümuster wie „Später senden" und das Mehr-Menü
              des Lesebereichs (aria-haspopup). */}
          <div ref={vorlagenRef} className="relative">
            <Button
              variant="ghost"
              iconLeft={<FileText className="size-4" />}
              aria-expanded={vorlagenOffen}
              aria-haspopup="menu"
              onClick={() => setVorlagenOffen((o) => !o)}
            >
              {t('verfassen.vorlage')}
            </Button>

            {vorlagenOffen && (
              <div
                role="menu"
                aria-label={t('verfassen.vorlage')}
                className="absolute bottom-full left-0 z-10 mb-1 max-h-72 w-64 overflow-y-auto rounded-lg border border-line bg-surface-1 p-1 shadow-[var(--shadow-3)]"
              >
                {vorlagenFehler ? (
                  /* ⚠️ Ein Fehler darf nicht wie Leere aussehen: Der Eintrag
                     sagt, dass der Abruf scheiterte, und holt auf Klick nach. */
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void vorlagenLaden()}
                    className="w-full px-2.5 py-1.5 text-left text-[13px] text-danger hover:bg-surface-3"
                  >
                    {t('verfassen.vorlagen_fehler')}
                  </button>
                ) : (vorlagen ?? []).length === 0 ? (
                  /* ⚠️ Kein leeres Menü: Der eine Eintrag sagt, dass es keine
                     Vorlagen gibt — und wo man sie anlegt. */
                  <p
                    role="menuitem"
                    aria-disabled="true"
                    className="mb-0 px-2.5 py-1.5 text-[13px] text-fg-3"
                  >
                    {t('verfassen.vorlagen_leer')}
                  </p>
                ) : (
                  (vorlagen ?? []).map((v) => (
                    <button
                      key={v.id}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setVorlagenOffen(false)
                        // An der Schreibmarke, nicht ans Ende: Tiptap fügt an
                        // der aktuellen Auswahl ein.
                        editorRef.current?.chain().focus().insertContent(v.inhalt_html).run()
                      }}
                      className="block w-full truncate rounded-md px-2.5 py-1.5 text-left text-[13px] text-fg-1 transition-colors duration-[var(--dur-fast)] hover:bg-surface-3"
                    >
                      {v.name}
                    </button>
                  ))
                )}
              </div>
            )}
          </div>

          {/* Wichtigkeit: ein Knopf, drei Stufen im Kreis — Vorgabe normal.
              ⚠️ Der Name trägt die aktuelle Stufe. Ein Symbol, das nur die
              Farbe wechselt, wäre für Vorleseprogramme kein Umschalter. */}
          <IconButton
            icon={
              wichtigkeit === 'hoch' ? (
                <ChevronsUp className="text-danger" />
              ) : wichtigkeit === 'niedrig' ? (
                <ChevronsDown />
              ) : (
                <Minus />
              )
            }
            label={t(`verfassen.wichtigkeit_${wichtigkeit}`)}
            active={wichtigkeit !== 'normal'}
            onClick={() =>
              setWichtigkeit((w) => (w === 'normal' ? 'hoch' : w === 'hoch' ? 'niedrig' : 'normal'))
            }
          />

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

      {/* Die Anhang-Nachfrage legt sich über das Fenster; ihr eigener Schleier
          fängt jeden Klick ab, bevor er das Verfassen-Fenster schlösse. */}
      {nachfrage}
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
