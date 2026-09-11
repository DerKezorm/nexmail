/* Das Adressbuch.
 *
 * Aufteilung wie im Mailteil: links die Liste, rechts der Eintrag. Wer sich in
 * nexmail zurechtfindet, findet sich auch hier zurecht — eine zweite
 * Anordnung für dieselbe Sache wäre eine zweite Sache zum Lernen.
 *
 * ⚠️ **Aufgeschnapptes ist gekennzeichnet.** nexmail sammelt Empfänger aus
 * „Gesendet" ein; ohne sichtbaren Unterschied weiß später niemand mehr, was er
 * selbst gepflegt hat und was von allein kam — und traut sich deshalb nicht,
 * aufzuräumen.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  Download,
  Link2,
  Plus,
  RefreshCw,
  Star,
  Trash2,
  Unlink,
  Upload,
  UserRoundPlus,
  Users,
  X,
} from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import { Badge, Button, Checkbox, EmptyState, IconButton, Input, Select } from '../ds'
import { Buchfenster } from '../components/Buchfenster'
import { Kontaktkonflikt } from '../components/Kontaktkonflikt'
import type { Kontaktfassung } from '../components/Kontaktkonflikt'
import { useNachfrage } from '../components/Nachfrage'
import { appPfad } from '../lib/basis'
import { PUNKT_KLASSE } from '../lib/farben'
import { beschriftung, sichtbareKontakte } from '../lib/kontaktanzeige'
import {
  ADRESSE_ARTEN,
  ANSCHRIFT_ARTEN,
  EIGEN,
  NUMMER_ARTEN,
  artSetzen,
  auswahlWert,
  beschriftungText,
  felderAusKontakt,
  leereFelder,
  mitStern,
  neueAdresse,
  neueAnschrift,
  neueNummer,
  sternSetzen,
  zeileEntfernen,
  zeileHinzufuegen,
} from '../lib/kontaktfelder'
import type { Adresse, Anschrift, Kontaktfelder, Nummer, Weiteres } from '../lib/kontaktfelder'
import { servermeldung } from '../lib/servermeldung'
import type { Postfachfarbe } from '../daten/typen'

export interface Kontakt extends Kontaktfelder {
  id: number
  /** Der Anzeigename, abgeleitet: „Vorname Nachname", sonst die Firma. */
  name: string
  /** Die bevorzugte Adresse und Nummer, abgeleitet aus den Listen. */
  adresse: string
  telefon: string
  quelle: string
  verwendet: number
  /** In welchem Buch der Eintrag liegt. */
  adressbuch_id: string | null
  /** Was die Karte außerdem trägt, nur bei verbundenen Kontakten: nexmail
   *  zeigt es, ändert es nicht. */
  weiteres: Weiteres[]
  /** Die Karte trägt ein Foto; geholt wird es über eine eigene Adresse. */
  hat_foto: boolean
}

/** Was das Konfliktfenster von beiden Fassungen zeigt. */
function fassungAus(f: Kontaktfelder) {
  return {
    name: [f.vorname, f.nachname].filter(Boolean).join(' ') || f.firma,
    adresse: mitStern(f.adressen)?.adresse ?? '',
    telefon: mitStern(f.nummern)?.nummer ?? '',
    firma: f.firma,
    notiz: f.notiz,
  }
}

/** Ein neuer Kontakt beginnt mit je einer leeren Zeile: Wer „Neu" drückt,
 *  will tippen, nicht erst Zeilen anlegen. Leere Zeilen wirft der Server weg. */
function neuerEntwurf(): Kontaktfelder {
  return {
    ...leereFelder(),
    nummern: [{ ...neueNummer([]), bevorzugt: true }],
    adressen: [{ ...neueAdresse(), bevorzugt: true }],
  }
}

/* Ein Adressbuch: das lokale, das nicht wegkann, oder ein verbundenes
 * (gelesen und geschrieben, seit 0.15.0 ohne Beta-Schild: iCloud und Google
 * sind gemessen). Ein Buch ist der Ort eines Kontakts, davon genau einer;
 * eine Gruppe ist quer dazu. */
export interface Buch {
  id: string
  name: string
  farbe: number
  sichtbar: boolean
  ist_lokal: boolean
  /** "" (lebt nur hier) | "carddav" */
  art: string
  herkunft: string
  letzter_fehler: string
  kontakte: number
}

/* Der Stand eines Imports in ein verbundenes Buch: Jede Karte geht einzeln
 * zum Anbieter, deshalb läuft er in einem eigenen Faden, und die Oberfläche
 * fragt nach — dasselbe Muster wie der mbox-Import. */
interface Einlesestand {
  id: string
  dateiname: string
  laeuft: boolean
  fehler_satz: string
  gesamt: number
  gelesen: number
  neu: number
  uebersprungen: number
  fehler_gesamt: number
  fehler: string[]
  abgebrochen: boolean
}

interface Einleseantwort {
  neu: number
  ergaenzt: number
  vorgang: Einlesestand | null
}

interface Abgleichbericht {
  neu: number
  geaendert: number
  entfernt: number
  belegt: number
  fehler: Record<string, string>
}

/* Ein Verteiler — ein Eingabehelfer beim Adressieren, kein Mailbegriff.
 * In der Mail stehen nur die Einzeladressen der Mitglieder. */
export interface Gruppe {
  id: number
  name: string
  mitglieder: number
  mitglied_ids: number[]
  adressen: string[]
}

export function KontaktePage() {
  const { t, i18n } = useTranslation()

  const [liste, setListe] = useState<Kontakt[]>([])
  const [suche, setSuche] = useState('')
  const [gewaehlt, setGewaehlt] = useState<number | null>(null)
  const [entwurf, setEntwurf] = useState<Kontaktfelder | null>(null)
  const [gruppen, setGruppen] = useState<Gruppe[]>([])
  const [gruppeGewaehlt, setGruppeGewaehlt] = useState<number | null>(null)
  const [gruppeNeu, setGruppeNeu] = useState(false)
  const [buecher, setBuecher] = useState<Buch[]>([])
  const [buchNeu, setBuchNeu] = useState(false)
  const [gleichtAb, setGleichtAb] = useState(false)
  const [fehler, setFehler] = useState('')
  const [meldung, setMeldung] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  /* Ein offener Konflikt: die eigene Fassung, wie sie gespeichert werden
     sollte. Solange er steht, ist nichts gespeichert. */
  const [konflikt, setKonflikt] = useState<{ id: number; meine: Kontaktfassung } | null>(null)
  /* Ein laufender Import in ein verbundenes Buch, solange er läuft und bis
     sein Ergebnis gelesen ist. */
  const [einlesen, setEinlesen] = useState<Einlesestand | null>(null)
  const dateifeld = useRef<HTMLInputElement>(null)
  const { fragen, fenster: nachfrage } = useNachfrage()

  const laden = useCallback(async (s: string) => {
    const roh = await api.holen<Kontakt[]>(`/api/kontakte?suche=${encodeURIComponent(s)}`)
    setListe(roh)
    return roh
  }, [])

  const gruppenLaden = useCallback(async () => {
    setGruppen(await api.holen<Gruppe[]>('/api/kontakte/gruppen'))
  }, [])

  const buecherLaden = useCallback(async () => {
    setBuecher(await api.holen<Buch[]>('/api/adressbuecher'))
  }, [])

  useEffect(() => {
    // Kurz warten, sonst eine Abfrage je Tastendruck.
    const uhr = window.setTimeout(() => void laden(suche).catch(() => setListe([])), 200)
    return () => window.clearTimeout(uhr)
  }, [suche, laden])

  useEffect(() => {
    void gruppenLaden().catch(() => setGruppen([]))
    void buecherLaden().catch(() => setBuecher([]))
    // Ein Import, der ein Neuladen der Seite überlebt hat, zeigt sich wieder.
    void api
      .holen<Einlesestand | null>('/api/kontakte/vcard/vorgang')
      .then((v) => v && setEinlesen(v))
      .catch(() => undefined)
  }, [gruppenLaden, buecherLaden])

  /* ⚠️ Nachfragen statt warten: Der Faden auf dem Server meldet sich nicht.
     Jede Sekunde, solange er läuft; danach einmal alles neu holen. */
  useEffect(() => {
    if (!einlesen?.laeuft) return
    const uhr = window.setInterval(() => {
      void api
        .holen<Einlesestand>(`/api/kontakte/vcard/vorgang/${einlesen.id}`)
        .then((stand) => {
          setEinlesen(stand)
          if (!stand.laeuft) {
            void laden(suche).catch(() => undefined)
            void buecherLaden().catch(() => undefined)
          }
        })
        .catch(() => setEinlesen(null))
    }, 1000)
    return () => window.clearInterval(uhr)
  }, [einlesen?.id, einlesen?.laeuft, laden, suche, buecherLaden])

  const offen = liste.find((k) => k.id === gewaehlt) ?? null
  const gruppeOffen = gruppen.find((g) => g.id === gruppeGewaehlt) ?? null
  /* Die Haken an den Büchern gelten für die Liste; ein Kontakt, dessen Buch
     die Liste nicht kennt, bleibt sichtbar. */
  const sichtbar = sichtbareKontakte(liste, buecher)
  const nachBuch = new Map(buecher.map((b) => [b.id, b]))

  async function mit<T>(tun: () => Promise<T>, erfolg = ''): Promise<T | null> {
    setFehler('')
    setMeldung('')
    setLaeuft(true)
    try {
      const ergebnis = await tun()
      await laden(suche)
      // Die Gruppen haengen an den Kontakten (Mitgliederzahl!) — nach jeder
      // Handlung frisch holen, sonst zaehlt die Liste Geloeschte weiter mit.
      // Die Buecher ebenso: Ihre Zahl steht in der Spalte.
      await gruppenLaden()
      await buecherLaden()
      if (erfolg) setMeldung(erfolg)
      return ergebnis
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      return null
    } finally {
      setLaeuft(false)
    }
  }

  /** ⚠️ Der Server nennt eine Kennung, die Oberfläche übersetzt. */
  function buchfehlertext(kennung: string): string {
    const schluessel = `kontakte.buch_fehler_${kennung}`
    return i18n.exists(schluessel) ? t(schluessel) : t('kontakte.buch_fehler_allgemein')
  }

  async function buchUmschalten(b: Buch, an: boolean) {
    // Sofort umschalten, damit der Haken nicht hakt; die gezählte Wahrheit
    // holt der nächste Abruf.
    setBuecher((alt) => alt.map((x) => (x.id === b.id ? { ...x, sichtbar: an } : x)))
    try {
      await api.flicken(`/api/adressbuecher/${b.id}`, { sichtbar: an })
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
      await buecherLaden().catch(() => undefined)
    }
  }

  async function jetztAbgleichen() {
    setGleichtAb(true)
    setFehler('')
    setMeldung('')
    try {
      const b = await api.senden<Abgleichbericht>('/api/adressbuecher/abgleichen', {})
      await laden(suche)
      await buecherLaden()
      const saetze = [
        b.neu + b.geaendert + b.entfernt > 0
          ? t('kontakte.buch_abgleich_fertig', {
              neu: b.neu,
              geaendert: b.geaendert,
              entfernt: b.entfernt,
            })
          : t('kontakte.buch_abgleich_nichts'),
      ]
      // ⚠️ Übergangene Karten werden genannt, sonst fehlen drüben Kontakte
      // und niemand weiss warum.
      if (b.belegt) saetze.push(t('kontakte.buch_abgleich_belegt', { count: b.belegt }))
      setMeldung(saetze.join(' '))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setGleichtAb(false)
    }
  }

  async function buchTrennen(b: Buch) {
    /* ⚠️ Die Rückfrage sagt, dass beim Anbieter nichts gelöscht wird. Ohne
       den Satz klingt „trennen" nach „weg". */
    const ja = await fragen({
      titel: t('kontakte.buch_trennen_frage', { name: b.name }),
      text: t('kontakte.buch_trennen_text', { count: b.kontakte, wo: b.herkunft }),
      knopf: t('kontakte.buch_trennen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(async () => {
      await api.loeschen(`/api/adressbuecher/${b.id}`)
      if (offen && offen.adressbuch_id === b.id) setGewaehlt(null)
    })
  }

  async function gruppeSpeichern(name: string, kontaktIds: number[]) {
    if (gruppeNeu) {
      const neu = await mit(async () => {
        const g = await api.senden<Gruppe>('/api/kontakte/gruppen', { name })
        if (kontaktIds.length > 0) {
          await api.aendern<Gruppe>(`/api/kontakte/gruppen/${g.id}/mitglieder`, {
            kontakt_ids: kontaktIds,
          })
        }
        return g
      })
      if (neu) {
        setGruppeNeu(false)
        setGruppeGewaehlt(neu.id)
      }
      return
    }
    if (!gruppeOffen) return
    await mit(async () => {
      if (name !== gruppeOffen.name) {
        await api.flicken<Gruppe>(`/api/kontakte/gruppen/${gruppeOffen.id}`, { name })
      }
      await api.aendern<Gruppe>(`/api/kontakte/gruppen/${gruppeOffen.id}/mitglieder`, {
        kontakt_ids: kontaktIds,
      })
    })
  }

  async function gruppeEntfernen(g: Gruppe) {
    // ⚠️ Die Rueckfrage nennt die Mitgliederzahl und sagt dazu, dass die
    // Kontakte bleiben — sonst liest jemand „entfernen" und fuerchtet um
    // sein Adressbuch.
    const ja = await fragen({
      titel: t('kontakte.gruppe_entfernen'),
      text:
        g.mitglieder === 0
          ? t('kontakte.gruppe_entfernen_text_leer', { name: g.name })
          : t('kontakte.gruppe_entfernen_text', { name: g.name, count: g.mitglieder }),
      knopf: t('kontakte.gruppe_entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await mit(async () => {
      await api.loeschen(`/api/kontakte/gruppen/${g.id}`)
      setGruppeGewaehlt(null)
    })
  }

  async function speichern(felder: Kontaktfelder, buchId: string) {
    if (entwurf && gewaehlt === null) {
      /* Ein neuer Kontakt entsteht in dem Buch, das im Formular gewählt ist;
         in einem verbundenen zuerst beim Anbieter. Was der ablehnt, gibt es
         hier gar nicht erst. */
      const neu = await mit(() =>
        api.senden<Kontakt>('/api/kontakte', { ...felder, adressbuch_id: buchId || null }),
      )
      if (neu) {
        setEntwurf(null)
        setGewaehlt(neu.id)
      }
      return
    }
    if (offen) await schreiben(offen.id, felder, false)
  }

  /* ⚠️ **Ein Konflikt ist keine Fehlermeldung, sondern eine Frage.** Jemand
     hat die Karte am Telefon geändert, seit sie hier offen ist. Die eigene
     Eingabe bleibt im Formular stehen (als Entwurf), und das Fenster fragt,
     welche Fassung gilt — dasselbe Muster wie beim Termin. */
  async function schreiben(id: number, felder: Kontaktfelder, erzwingen: boolean) {
    const fertig = await mit(async () => {
      try {
        await api.flicken<Kontakt>(`/api/kontakte/${id}`, { ...felder, erzwingen })
        return true
      } catch (f) {
        if (f instanceof ApiFehler && f.detail === 'kontakt_konflikt') {
          setEntwurf({ ...felder })
          setKonflikt({ id, meine: fassungAus(felder) })
          return false
        }
        throw f
      }
    })
    if (fertig) setEntwurf(null)
  }

  async function konfliktEntscheiden(wahl: 'meine' | 'andere') {
    if (!konflikt) return
    const { id } = konflikt
    setKonflikt(null)
    if (wahl === 'meine') {
      // Die eigene Eingabe steht als Entwurf im Formular; sie geht hinaus.
      if (entwurf) await schreiben(id, entwurf, true)
      return
    }
    const uebernommen = await mit(() => api.senden<Kontakt>(`/api/kontakte/${id}/konflikt`, {}))
    if (uebernommen) setEntwurf(null)
  }

  /* Ein Kontakt wechselt sein Buch. In ein verbundenes hinein hängt er sich
     an die Karte, die dort schon seine Adresse trägt, sonst entsteht sie.
     ⚠️ **Aus einem verbundenen heraus heisst: dort löschen** — und das wird
     gefragt, denn beim Anbieter gibt es kein Rückgängig. */
  async function verschieben(k: Kontakt, buchId: string) {
    const von = k.adressbuch_id ? nachBuch.get(k.adressbuch_id) : undefined
    const nach = nachBuch.get(buchId)
    if (!nach || von?.id === nach.id) return
    if (von?.art) {
      const ja = await fragen({
        titel: t('kontakte.verschieben_frage', { name: nach.name }),
        text: t('kontakte.verschieben_text', { wo: von.herkunft }),
        knopf: t('kontakte.verschieben_knopf'),
        gefaehrlich: true,
      })
      if (ja !== true) return
    }
    await mit(
      () => api.senden<Kontakt>(`/api/kontakte/${k.id}/verschieben`, { adressbuch_id: buchId }),
      t('kontakte.verschoben', { name: nach.name }),
    )
  }

  /* Löschen nimmt bei einem verbundenen Kontakt die Karte beim Anbieter mit.
     ⚠️ Genau davor wird gefragt; ein lokaler Eintrag geht wie bisher ohne
     Umweg, denn der ist mit einem Klick wieder angelegt. */
  async function entfernen(k: Kontakt) {
    const buch = k.adressbuch_id ? nachBuch.get(k.adressbuch_id) : undefined
    if (buch?.art) {
      const ja = await fragen({
        titel: t('kontakte.entfernen_frage', { name: beschriftung(k).titel }),
        text: t('kontakte.entfernen_text', { wo: buch.herkunft }),
        knopf: t('kontakte.entfernen'),
        gefaehrlich: true,
      })
      if (ja !== true) return
    }
    await mit(async () => {
      await api.loeschen(`/api/kontakte/${k.id}`)
      setGewaehlt(null)
    })
  }

  async function vcardEinlesen(datei: File) {
    const formular = new FormData()
    formular.append('datei', datei)
    /* Bei mehr als einem Buch entscheidet der Mensch, wohin — in ein
       verbundenes geht jede Karte zum Anbieter, das ist eine andere Sache
       als ein paar Zeilen im lokalen Buch. */
    if (buecher.length > 1) {
      const lokal = buecher.find((b) => b.ist_lokal)
      const antwort = await fragen({
        titel: t('kontakte.einlesen'),
        text: t('kontakte.einlesen_wohin', { datei: datei.name }),
        auswahl: {
          beschriftung: t('kontakte.buch_feld'),
          werte: buecher.map((b) => ({ wert: b.id, text: b.art ? `${b.name} · ${b.herkunft}` : b.name })),
          vorgabe: lokal?.id,
        },
        knopf: t('kontakte.einlesen_knopf'),
      })
      if (!antwort || typeof antwort !== 'object') return
      formular.append('adressbuch_id', antwort.wert)
    }
    const stand = await mit(() => api.formular<Einleseantwort>('/api/kontakte/vcard', formular))
    if (!stand) return
    if (stand.vorgang) {
      setEinlesen(stand.vorgang)
      return
    }
    setMeldung(t('kontakte.eingelesen', { neu: stand.neu, ergaenzt: stand.ergaenzt }))
  }

  async function einlesenAbbrechen() {
    if (!einlesen) return
    try {
      setEinlesen(await api.senden<Einlesestand>(`/api/kontakte/vcard/vorgang/${einlesen.id}/abbrechen`, {}))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  /** Der Satz zum Stand eines Imports: laufend, fertig oder gescheitert. */
  function einlesenText(stand: Einlesestand): string {
    if (stand.laeuft) return t('kontakte.einlesen_laeuft', { fertig: stand.gelesen, gesamt: stand.gesamt })
    const zahlen = t('kontakte.eingelesen_buch', {
      neu: stand.neu,
      uebersprungen: stand.uebersprungen,
      fehler: stand.fehler_gesamt,
    })
    if (stand.fehler_satz) {
      const schluessel = `serverfehler.${stand.fehler_satz}`
      return `${zahlen} ${t('kontakte.einlesen_gescheitert')} ${i18n.exists(schluessel) ? t(schluessel) : ''}`.trim()
    }
    return stand.abgebrochen ? `${zahlen} ${t('kontakte.einlesen_abgebrochen')}` : zahlen
  }

  return (
    <div className="flex min-h-0 flex-1 bg-canvas">
      {/* --- Liste --------------------------------------------------- */}
      <div className="flex w-[320px] shrink-0 flex-col border-r border-line">
        <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line-subtle px-2">
          <IconButton
            icon={<Plus />}
            label={t('kontakte.neu')}
            size="sm"
            onClick={() => {
              setGewaehlt(null)
              setGruppeGewaehlt(null)
              setGruppeNeu(false)
              setEntwurf(neuerEntwurf())
            }}
          />
          <IconButton
            icon={<UserRoundPlus />}
            label={t('kontakte.einsammeln')}
            size="sm"
            onClick={() =>
              void mit(
                () => api.senden<{ neu: number }>('/api/kontakte/einsammeln', {}),
                t('kontakte.eingesammelt'),
              )
            }
          />
          <span aria-hidden className="mx-1 h-5 w-px bg-line" />
          <IconButton
            icon={<Upload />}
            label={t('kontakte.einlesen')}
            size="sm"
            onClick={() => dateifeld.current?.click()}
          />
          <IconButton
            icon={<Download />}
            label={t('kontakte.ausfuehren')}
            size="sm"
            onClick={() => {
              window.location.href = appPfad('/api/kontakte/vcard')
            }}
          />
          <span className="flex-1" />
          <span className="pr-1 text-[11px] text-fg-4">{sichtbar.length}</span>
        </div>

        <input
          ref={dateifeld}
          type="file"
          accept=".vcf,text/vcard"
          className="sr-only"
          onChange={(e) => {
            const datei = e.target.files?.[0]
            if (datei) void vcardEinlesen(datei)
            e.target.value = ''
          }}
        />

        <div className="shrink-0 border-b border-line-subtle p-2">
          <Input
            placeholder={t('kontakte.suchen')}
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
          />
        </div>

        {/* --- Bücher: wo ein Kontakt liegt ------------------------------ */}
        <div className="shrink-0 border-b border-line-subtle">
          <div className="flex h-9 items-center gap-1.5 pr-1 pl-3">
            <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
              {t('kontakte.buecher')}
            </span>
            <span className="flex-1" />
            {buecher.some((b) => b.art) && (
              <IconButton
                icon={<RefreshCw className={gleichtAb ? 'animate-spin' : undefined} />}
                label={gleichtAb ? t('kontakte.buch_abgleich_laeuft') : t('kontakte.buch_abgleichen')}
                size="sm"
                onClick={() => void jetztAbgleichen()}
              />
            )}
            <IconButton
              icon={<Plus />}
              label={t('kontakte.buch_verbinden')}
              size="sm"
              onClick={() => setBuchNeu(true)}
            />
          </div>
          <div className="pb-1">
            {buecher.map((b) => (
              /* ⚠️ Der Farbfleck steht VOR dem Haken, wie beim Kalender: Der
                 Haken sagt „wird angezeigt", der Fleck sagt, welches Buch. */
              <div key={b.id} className="flex items-center gap-2 px-3 py-1 hover:bg-surface-2">
                <span
                  aria-hidden
                  className={`size-2.5 shrink-0 rounded-sm ${PUNKT_KLASSE[b.farbe as Postfachfarbe]}`}
                />
                <span className="min-w-0 flex-1 truncate text-[13px]">
                  <Checkbox
                    label={b.name}
                    checked={b.sichtbar}
                    onCheckedChange={(an) => void buchUmschalten(b, an)}
                  />
                </span>
                <span className="text-[11px] text-fg-4">{b.kontakte}</span>
                {/* ⚠️ Der Fehler steht am Buch, nicht in einem Banner. Bei
                    drei verbundenen Büchern sagt „fehlgeschlagen" nicht,
                    welches. */}
                {b.letzter_fehler ? (
                  <span title={buchfehlertext(b.letzter_fehler)}>
                    <AlertTriangle aria-hidden className="size-3.5 shrink-0 text-warning" />
                  </span>
                ) : b.art ? (
                  <span title={b.herkunft}>
                    <Link2 aria-hidden className="size-3.5 shrink-0 text-fg-4" />
                  </span>
                ) : null}
                {b.art && (
                  <IconButton
                    icon={<Unlink />}
                    label={t('kontakte.buch_trennen')}
                    size="sm"
                    onClick={() => void buchTrennen(b)}
                  />
                )}
              </div>
            ))}
            {/* Das Ergebnis eines Abgleichs gehört hierher, wenn rechts
                gerade kein Eintrag offen ist, der es zeigen könnte. */}
            {!(entwurf || offen || gruppeNeu || gruppeOffen) && (fehler || meldung) && (
              <p className={`px-3 pb-2 text-[12px] ${fehler ? 'text-danger' : 'text-accent-text'}`}>
                {fehler || meldung}
              </p>
            )}
            {/* Ein Import in ein verbundenes Buch: sein Stand, solange er
                läuft, und sein Ergebnis, bis es weggeklickt ist. */}
            {einlesen && (
              <div
                role="status"
                className={`mx-3 mb-2 flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[12px] ${einlesen.fehler_satz ? 'text-danger' : 'text-fg-2'}`}
              >
                <span className="min-w-0 flex-1">{einlesenText(einlesen)}</span>
                {einlesen.laeuft ? (
                  <Button size="sm" variant="ghost" onClick={() => void einlesenAbbrechen()}>
                    {t('kontakte.einlesen_abbrechen')}
                  </Button>
                ) : (
                  <IconButton icon={<X />} label={t('aktion.schliessen')} size="sm" onClick={() => setEinlesen(null)} />
                )}
              </div>
            )}
          </div>
        </div>

        {/* --- Gruppen: Verteiler als Eingabehelfer beim Adressieren --- */}
        <div className="shrink-0 border-b border-line-subtle">
          <div className="flex h-9 items-center gap-1 pr-1 pl-3">
            <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
              {t('kontakte.gruppen')}
            </span>
            <span className="flex-1" />
            <IconButton
              icon={<Plus />}
              label={t('kontakte.gruppe_neu')}
              size="sm"
              onClick={() => {
                setGewaehlt(null)
                setEntwurf(null)
                setGruppeGewaehlt(null)
                setGruppeNeu(true)
                setFehler('')
                setMeldung('')
              }}
            />
          </div>
          {gruppen.length === 0 ? (
            <p className="px-3 pb-2 text-[12px] text-fg-4">{t('kontakte.gruppe_leer')}</p>
          ) : (
            <div className="max-h-44 overflow-y-auto pb-1">
              {gruppen.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => {
                    setGewaehlt(null)
                    setEntwurf(null)
                    setGruppeNeu(false)
                    setGruppeGewaehlt(g.id)
                    setFehler('')
                    setMeldung('')
                  }}
                  className={
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left ' +
                    'transition-colors duration-[var(--dur-fast)] ' +
                    (g.id === gruppeGewaehlt && !gruppeNeu ? 'bg-accent-soft' : 'hover:bg-surface-2')
                  }
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">{g.name}</span>
                  <Badge tone="neutral">{t('kontakte.gruppe_zahl', { count: g.mitglieder })}</Badge>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {sichtbar.length === 0 ? (
            <p className="px-3 py-6 text-center text-[13px] text-fg-4">{t('kontakte.leer')}</p>
          ) : (
            sichtbar.map((k) => (
              <button
                key={k.id}
                type="button"
                onClick={() => {
                  setGewaehlt(k.id)
                  setEntwurf(null)
                  setGruppeGewaehlt(null)
                  setGruppeNeu(false)
                  setFehler('')
                  setMeldung('')
                }}
                className={
                  'flex w-full flex-col items-start gap-0.5 border-b border-line-subtle px-3 py-2 text-left ' +
                  'transition-colors duration-[var(--dur-fast)] ' +
                  (k.id === gewaehlt ? 'bg-accent-soft' : 'hover:bg-surface-2')
                }
              >
                <span className="flex w-full items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg-1">
                    {beschriftung(k).titel}
                  </span>
                  {/* ⚠️ Aufgeschnapptes muss man sehen — sonst traut sich
                      niemand, das Adressbuch aufzuräumen. */}
                  {k.quelle === 'gesammelt' && (
                    <Badge tone="neutral">{t('kontakte.gesammelt')}</Badge>
                  )}
                </span>
                {/* Ohne Adresse steht hier die Nummer: ein Kontakt darf seit
                    dem 05.09.2026 ohne Postfach leben. */}
                <span className="w-full truncate text-[12px] text-fg-3">{beschriftung(k).unter}</span>
              </button>
            ))
          )}
        </div>

        <div className="shrink-0 border-t border-line-subtle p-2">
          <Button
            size="sm"
            variant="ghost"
            fullWidth
            iconLeft={<Trash2 className="size-4" />}
            disabled={laeuft || !liste.some((k) => k.quelle === 'gesammelt')}
            onClick={() =>
              void mit(
                () => api.loeschen<{ entfernt: number }>('/api/kontakte/gesammelte'),
                t('kontakte.aufgeraeumt'),
              )
            }
          >
            {t('kontakte.gesammelte_weg')}
          </Button>
        </div>
      </div>

      {/* --- Eintrag ------------------------------------------------- */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {gruppeNeu || gruppeOffen ? (
          <GruppenFormular
            key={gruppeNeu ? 'gruppe-neu' : gruppeOffen!.id}
            gruppe={gruppeNeu ? null : gruppeOffen}
            laeuft={laeuft}
            fehler={fehler}
            meldung={meldung}
            aufSpeichern={gruppeSpeichern}
            aufEntfernen={gruppeOffen ? () => void gruppeEntfernen(gruppeOffen) : undefined}
          />
        ) : entwurf || offen ? (
          <Formular
            key={gewaehlt ?? 'neu'}
            werte={entwurf ?? felderAusKontakt(offen!)}
            neu={gewaehlt === null}
            laeuft={laeuft}
            fehler={fehler}
            meldung={meldung}
            buecher={buecher}
            buchId={offen?.adressbuch_id ?? buecher.find((b) => b.ist_lokal)?.id ?? ''}
            herkunft={offen?.adressbuch_id ? (nachBuch.get(offen.adressbuch_id)?.herkunft ?? '') : ''}
            weiteres={offen?.weiteres ?? []}
            foto={offen?.hat_foto ? appPfad(`/api/kontakte/${offen.id}/foto`) : ''}
            aufSpeichern={speichern}
            aufVerschieben={offen ? (buchId) => void verschieben(offen, buchId) : undefined}
            aufEntfernen={offen ? () => void entfernen(offen) : undefined}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              icon={<Users />}
              title={t('kontakte.keine_auswahl')}
              description={t('kontakte.keine_auswahl_text')}
            />
          </div>
        )}
      </div>

      {buchNeu && (
        <Buchfenster
          onClose={() => setBuchNeu(false)}
          onFertig={() => {
            void buecherLaden().catch(() => undefined)
            void laden(suche).catch(() => undefined)
          }}
        />
      )}

      {/* ⚠️ Das Konfliktfenster liegt über dem Formular; die eigene Eingabe
          steht darunter als Entwurf und geht bei „Abbrechen“ nicht verloren. */}
      {konflikt && (
        <Kontaktkonflikt
          kontaktId={konflikt.id}
          meine={konflikt.meine}
          aufSchliessen={() => setKonflikt(null)}
          aufWahl={(wahl) => void konfliktEntscheiden(wahl)}
        />
      )}

      {nachfrage}
    </div>
  )
}

/* Das Formular fuer eine Gruppe: Name plus Mehrfachauswahl aus dem Adressbuch.
 *
 * ⚠️ **Die Auswahl zeigt das ganze Adressbuch, nicht die gefilterte Liste
 * links.** Wer links nach „anna" gesucht hat, soll rechts trotzdem Bernd
 * ankreuzen koennen — deshalb holt das Formular seine Kontakte selbst und
 * bringt einen eigenen Filter mit. */
function GruppenFormular({
  gruppe,
  laeuft,
  fehler,
  meldung,
  aufSpeichern,
  aufEntfernen,
}: {
  gruppe: Gruppe | null
  laeuft: boolean
  fehler: string
  meldung: string
  aufSpeichern: (name: string, kontaktIds: number[]) => Promise<void>
  aufEntfernen?: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(gruppe?.name ?? '')
  const [gewaehlt, setGewaehlt] = useState<Set<number>>(new Set(gruppe?.mitglied_ids ?? []))
  const [alle, setAlle] = useState<Kontakt[] | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api
      .holen<Kontakt[]>('/api/kontakte')
      .then(setAlle)
      .catch(() => setAlle([]))
  }, [])

  const kern = filter.trim().toLowerCase()
  const sichtbar = (alle ?? []).filter(
    (k) =>
      !kern ||
      k.name.toLowerCase().includes(kern) ||
      k.adresse.toLowerCase().includes(kern) ||
      k.telefon.includes(kern),
  )

  return (
    <form
      className="flex max-w-[560px] flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        void aufSpeichern(name.trim(), [...gewaehlt])
      }}
    >
      <Input
        label={t('kontakte.gruppe_name')}
        value={name}
        autoFocus={gruppe === null}
        onChange={(e) => setName(e.target.value)}
      />

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('kontakte.gruppe_mitglieder')}
        </span>
        {alle !== null && alle.length === 0 ? (
          <p className="text-[13px] text-fg-4">{t('kontakte.gruppe_keine_kontakte')}</p>
        ) : (
          <div className="flex flex-col overflow-hidden rounded-md border border-line">
            <div className="border-b border-line-subtle p-2">
              <Input
                size="sm"
                placeholder={t('kontakte.gruppe_mitglieder_filtern')}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <div className="max-h-72 overflow-y-auto p-2">
              <div className="flex flex-col gap-1.5">
                {sichtbar.map((k) => (
                  <Checkbox
                    key={k.id}
                    label={beschriftung(k).titel}
                    description={beschriftung(k).unter || undefined}
                    checked={gewaehlt.has(k.id)}
                    onCheckedChange={(an) =>
                      setGewaehlt((alt) => {
                        const neu = new Set(alt)
                        if (an) neu.add(k.id)
                        else neu.delete(k.id)
                        return neu
                      })
                    }
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}
      {meldung && <p className="text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" loading={laeuft} disabled={!name.trim()}>
          {gruppe === null ? t('kontakte.anlegen') : t('kontakte.speichern')}
        </Button>
        {aufEntfernen && (
          <Button variant="danger" iconLeft={<Trash2 className="size-4" />} onClick={aufEntfernen}>
            {t('kontakte.gruppe_entfernen')}
          </Button>
        )}
      </div>
    </form>
  )
}

/* Das Formular eines Kontakts: die Felder, die iCloud und Google beide
 * kennen, dazu die drei Listen. Was nur Apple kennt, steht eingeklappt
 * darunter, nur lesend. Die Regeln (Stern, „Eigene …", leere Zeilen) wohnen in
 * `lib/kontaktfelder.ts`, ohne Browser. */
function Formular({
  werte,
  neu,
  laeuft,
  fehler,
  meldung,
  buecher,
  buchId,
  herkunft = '',
  weiteres = [],
  foto = '',
  aufSpeichern,
  aufVerschieben,
  aufEntfernen,
}: {
  werte: Kontaktfelder
  neu: boolean
  laeuft: boolean
  fehler: string
  meldung: string
  /** Alle Bücher, zur Wahl: bei einem neuen Kontakt, wo er entsteht; bei
      einem bestehenden, wohin er zieht. */
  buecher: Buch[]
  buchId: string
  /** Der Anbieter, wenn der Kontakt in einem verbundenen Buch liegt. */
  herkunft?: string
  weiteres?: Weiteres[]
  /** Die Adresse des Fotos der Karte, leer ohne Foto. Nur zeigen. */
  foto?: string
  aufSpeichern: (f: Kontaktfelder, buchId: string) => void
  aufVerschieben?: (buchId: string) => void
  aufEntfernen?: () => void
}) {
  const { t, i18n } = useTranslation()
  const [felder, setFelder] = useState<Kontaktfelder>(werte)
  /* Bei einem neuen Kontakt gehört das Buch zum Formular; bei einem
     bestehenden ist die Auswahl eine Handlung (verschieben) und zeigt den
     gespeicherten Stand. */
  const [buchNeu, setBuchNeu] = useState(buchId)

  useEffect(() => setFelder(werte), [werte])

  const setzen = (teil: Partial<Kontaktfelder>) => setFelder((alt) => ({ ...alt, ...teil }))
  const kennt = (s: string) => i18n.exists(s)
  const artText = (art: string) => (art === 'other' ? t('kontakte.art_other') : t(`kontakte.art_${art}`))
  /* Ein Geburtstag ohne Jahr („--06-14", wie Apple ihn hält) passt in kein
     Datumsfeld; er steht dann als Text, und die Auswahl bleibt dem Telefon. */
  const geburtstagAlsDatum = felder.geburtstag === '' || /^\d{4}-\d{2}-\d{2}$/.test(felder.geburtstag)

  const artWahl = (
    eintrag: { art: string; beschriftung: string },
    arten: readonly string[],
    aufWahl: (wert: string) => void,
  ) => (
    <Select aria-label={t('kontakte.art_wahl')} value={auswahlWert(eintrag)} onChange={(e) => aufWahl(e.target.value)}>
      {arten.map((a) => (
        <option key={a} value={a}>
          {artText(a)}
        </option>
      ))}
      <option value={EIGEN}>{t('kontakte.art_eigen')}</option>
    </Select>
  )

  const stern = (an: boolean, titel: string, aufKlick: () => void) => (
    <button
      type="button"
      aria-pressed={an}
      aria-label={titel}
      title={titel}
      onClick={aufKlick}
      className={`fokusrahmen grid size-8 shrink-0 place-items-center rounded-md ${an ? 'text-accent-text' : 'text-fg-4 hover:bg-surface-2 hover:text-fg-2'}`}
    >
      <Star aria-hidden className="size-4" fill={an ? 'currentColor' : 'none'} />
    </button>
  )

  const weg = (titel: string, aufKlick: () => void) => (
    <button
      type="button"
      aria-label={titel}
      title={titel}
      onClick={aufKlick}
      className="fokusrahmen grid size-8 shrink-0 place-items-center rounded-md text-fg-4 hover:bg-surface-2 hover:text-danger"
    >
      <X aria-hidden className="size-4" />
    </button>
  )

  const eigenFeld = (eintrag: { art: string; beschriftung: string }, aufText: (text: string) => void) =>
    auswahlWert(eintrag) === EIGEN && (
      <input
        aria-label={t('kontakte.beschriftung')}
        placeholder={t('kontakte.beschriftung')}
        value={eintrag.beschriftung}
        onChange={(e) => aufText(e.target.value)}
        className="fokusrahmen col-start-1 rounded-md border border-line bg-surface-1 px-3 py-1.5 text-sm text-fg-1 outline-none"
      />
    )

  const kopf = (titel: string, knopf: string, aufNeu: () => void) => (
    <div className="flex items-center gap-2">
      <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">{titel}</span>
      <button
        type="button"
        onClick={aufNeu}
        className="fokusrahmen ml-auto rounded-md px-2 py-1 text-[12.5px] font-medium text-accent-text hover:bg-accent-soft"
      >
        {knopf}
      </button>
    </div>
  )

  const nummernSetzen = (liste: Nummer[]) => setzen({ nummern: liste })
  const adressenSetzen = (liste: Adresse[]) => setzen({ adressen: liste })
  const anschriftenSetzen = (liste: Anschrift[]) => setzen({ anschriften: liste })
  const feldKlasse = 'fokusrahmen w-full rounded-md border border-line bg-surface-1 px-3 py-1.5 text-sm text-fg-1 outline-none'

  return (
    <form
      className="flex max-w-[640px] flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        aufSpeichern(felder, neu ? buchNeu : buchId)
      }}
    >
      {/* ⚠️ Wer einen verbundenen Kontakt bearbeitet, soll wissen, dass es
          sofort beim Anbieter ankommt — bevor er speichert, nicht danach. */}
      {herkunft && (
        <p className="rounded-md border border-line bg-surface-2 px-3 py-2 text-[12px] leading-relaxed text-fg-3">
          {`${t('kontakte.aus_buch', { wo: herkunft })}. `}
          {t('kontakte.verbunden_hinweis')}
        </p>
      )}
      {/* Das Buch steht nur zur Wahl, wenn es mehr als eines gibt: eine
          Auswahl mit einem Eintrag ist ein Klick, der nichts entscheidet. */}
      {buecher.length > 1 && (
        <div className="max-w-[300px]">
          <Select
            label={t('kontakte.buch_feld')}
            value={neu ? buchNeu : buchId}
            onChange={(e) => {
              if (neu) setBuchNeu(e.target.value)
              else aufVerschieben?.(e.target.value)
            }}
          >
            {buecher.map((b) => (
              <option key={b.id} value={b.id}>
                {b.art ? `${b.name} · ${b.herkunft}` : b.name}
              </option>
            ))}
          </Select>
        </div>
      )}

      <div className="flex items-start gap-4">
        {/* Das Foto der Karte, wie es vom Anbieter kommt. Geändert wird es am
            Telefon; hier bleibt es beim Speichern ohnehin stehen. */}
        {foto && (
          <img
            src={foto}
            alt={t('kontakte.foto_alt')}
            className="size-16 shrink-0 rounded-full border border-line object-cover"
          />
        )}
        <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
          <Input label={t('kontakte.vorname')} autoComplete="given-name" value={felder.vorname} onChange={(e) => setzen({ vorname: e.target.value })} />
          <Input label={t('kontakte.nachname')} autoComplete="family-name" value={felder.nachname} onChange={(e) => setzen({ nachname: e.target.value })} />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label={t('kontakte.spitzname')} value={felder.spitzname} onChange={(e) => setzen({ spitzname: e.target.value })} />
        <Input label={t('kontakte.position')} value={felder.titel} onChange={(e) => setzen({ titel: e.target.value })} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label={t('kontakte.firma')} autoComplete="organization" value={felder.firma} onChange={(e) => setzen({ firma: e.target.value })} />
        <Input label={t('kontakte.abteilung')} value={felder.abteilung} onChange={(e) => setzen({ abteilung: e.target.value })} />
      </div>

      {/* --- Telefon ------------------------------------------------ */}
      <div className="flex flex-col gap-2" data-liste="nummern">
        {kopf(t('kontakte.nummern'), t('kontakte.nummer_neu'), () =>
          nummernSetzen(zeileHinzufuegen(felder.nummern, neueNummer(felder.nummern))),
        )}
        {felder.nummern.length === 0 && <p className="text-[13px] text-fg-4">{t('kontakte.keine_nummer')}</p>}
        {felder.nummern.map((n, i) => (
          <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2 sm:grid-cols-[128px_minmax(0,1fr)_auto_auto]">
            {artWahl(n, NUMMER_ARTEN, (wert) => nummernSetzen(felder.nummern.map((x, j) => (j === i ? artSetzen(x, wert) : x))))}
            <input
              aria-label={t('kontakte.telefon')}
              type="tel"
              autoComplete="off"
              value={n.nummer}
              onChange={(e) => nummernSetzen(felder.nummern.map((x, j) => (j === i ? { ...x, nummer: e.target.value } : x)))}
              className={`${feldKlasse} col-span-3 font-mono text-[13px] sm:col-span-1`}
            />
            {stern(n.bevorzugt, t('kontakte.stern_nummer'), () => nummernSetzen(sternSetzen(felder.nummern, i)))}
            {weg(t('kontakte.zeile_entfernen'), () => nummernSetzen(zeileEntfernen(felder.nummern, i)))}
            {eigenFeld(n, (text) => nummernSetzen(felder.nummern.map((x, j) => (j === i ? { ...x, beschriftung: text } : x))))}
          </div>
        ))}
      </div>

      {/* --- E-Mail ------------------------------------------------- */}
      <div className="flex flex-col gap-2" data-liste="adressen">
        {kopf(t('kontakte.adressen'), t('kontakte.adresse_neu'), () =>
          adressenSetzen(zeileHinzufuegen(felder.adressen, neueAdresse())),
        )}
        {felder.adressen.length === 0 && <p className="text-[13px] text-fg-4">{t('kontakte.keine_adresse')}</p>}
        {felder.adressen.map((a, i) => (
          <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2 sm:grid-cols-[128px_minmax(0,1fr)_auto_auto]">
            {artWahl(a, ADRESSE_ARTEN, (wert) => adressenSetzen(felder.adressen.map((x, j) => (j === i ? artSetzen(x, wert) : x))))}
            <input
              aria-label={t('kontakte.adresse')}
              type="email"
              autoComplete="email"
              value={a.adresse}
              onChange={(e) => adressenSetzen(felder.adressen.map((x, j) => (j === i ? { ...x, adresse: e.target.value } : x)))}
              className={`${feldKlasse} col-span-3 font-mono text-[13px] sm:col-span-1`}
            />
            {stern(a.bevorzugt, t('kontakte.stern_adresse'), () => adressenSetzen(sternSetzen(felder.adressen, i)))}
            {weg(t('kontakte.zeile_entfernen'), () => adressenSetzen(zeileEntfernen(felder.adressen, i)))}
            {eigenFeld(a, (text) => adressenSetzen(felder.adressen.map((x, j) => (j === i ? { ...x, beschriftung: text } : x))))}
          </div>
        ))}
      </div>

      {/* --- Anschrift ---------------------------------------------- */}
      <div className="flex flex-col gap-2" data-liste="anschriften">
        {kopf(t('kontakte.anschriften'), t('kontakte.anschrift_neu'), () =>
          anschriftenSetzen(zeileHinzufuegen(felder.anschriften, neueAnschrift())),
        )}
        {felder.anschriften.length === 0 && <p className="text-[13px] text-fg-4">{t('kontakte.keine_anschrift')}</p>}
        {felder.anschriften.map((a, i) => {
          const aendern = (teil: Partial<Anschrift>) =>
            anschriftenSetzen(felder.anschriften.map((x, j) => (j === i ? { ...x, ...teil } : x)))
          return (
            <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-2 sm:grid-cols-[128px_minmax(0,1fr)_auto_auto]">
              {artWahl(a, ANSCHRIFT_ARTEN, (wert) => anschriftenSetzen(felder.anschriften.map((x, j) => (j === i ? artSetzen(x, wert) : x))))}
              <div className="col-span-3 flex flex-col gap-2 sm:col-span-1">
                <input aria-label={t('kontakte.strasse')} placeholder={t('kontakte.strasse')} autoComplete="street-address" value={a.strasse} onChange={(e) => aendern({ strasse: e.target.value })} className={feldKlasse} />
                <div className="grid grid-cols-[110px_1fr] gap-2 sm:grid-cols-[110px_1fr_1fr]">
                  <input aria-label={t('kontakte.plz')} placeholder={t('kontakte.plz')} autoComplete="postal-code" value={a.plz} onChange={(e) => aendern({ plz: e.target.value })} className={feldKlasse} />
                  <input aria-label={t('kontakte.ort')} placeholder={t('kontakte.ort')} autoComplete="address-level2" value={a.ort} onChange={(e) => aendern({ ort: e.target.value })} className={feldKlasse} />
                  <input aria-label={t('kontakte.land')} placeholder={t('kontakte.land')} autoComplete="country-name" value={a.land} onChange={(e) => aendern({ land: e.target.value })} className={`${feldKlasse} col-span-2 sm:col-span-1`} />
                </div>
              </div>
              {stern(a.bevorzugt, t('kontakte.stern_anschrift'), () => anschriftenSetzen(sternSetzen(felder.anschriften, i)))}
              {weg(t('kontakte.zeile_entfernen'), () => anschriftenSetzen(zeileEntfernen(felder.anschriften, i)))}
              {eigenFeld(a, (text) => aendern({ beschriftung: text }))}
            </div>
          )
        })}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {geburtstagAlsDatum ? (
          <Input label={t('kontakte.geburtstag')} type="date" value={felder.geburtstag} onChange={(e) => setzen({ geburtstag: e.target.value })} />
        ) : (
          <Input
            label={`${t('kontakte.geburtstag')} · ${t('kontakte.geburtstag_ohne_jahr')}`}
            value={felder.geburtstag}
            onChange={(e) => setzen({ geburtstag: e.target.value })}
          />
        )}
        <Input label={t('kontakte.webseite')} mono type="url" autoComplete="url" value={felder.webseite} onChange={(e) => setzen({ webseite: e.target.value })} />
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold tracking-[0.06em] text-fg-3 uppercase">
          {t('kontakte.notiz')}
        </span>
        <textarea
          rows={4}
          value={felder.notiz}
          onChange={(e) => setzen({ notiz: e.target.value })}
          className="fokusrahmen rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-fg-1 outline-none disabled:opacity-60"
        />
      </label>

      {/* --- Was nur Apple kennt: zeigen, nicht ändern ---------------- */}
      {weiteres.length > 0 && (
        <details className="rounded-md border border-line-subtle bg-surface-2">
          <summary className="cursor-pointer px-3 py-2 text-[13px] text-fg-2">
            {t('kontakte.weiteres', { count: weiteres.length })}
          </summary>
          <div className="px-3 pb-3 text-[13px] text-fg-2">
            <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
              {weiteres.map((w, i) => (
                <div key={i} className="contents">
                  <dt className="text-fg-4">
                    {t(`kontakte.weiteres_${w.art}`)}
                    {w.beschriftung ? ` · ${beschriftungText({ art: '', beschriftung: w.beschriftung }, t, kennt)}` : ''}
                  </dt>
                  <dd className="m-0 truncate">{w.text}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-[12px] text-fg-3">{t('kontakte.weiteres_hinweis')}</p>
          </div>
        </details>
      )}

      {fehler && <p className="text-[13px] text-danger">{fehler}</p>}
      {meldung && <p className="text-[13px] text-accent-text">{meldung}</p>}

      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" loading={laeuft}>
          {neu ? t('kontakte.anlegen') : t('kontakte.speichern')}
        </Button>
        {aufEntfernen && (
          <Button variant="danger" iconLeft={<Trash2 className="size-4" />} onClick={aufEntfernen}>
            {t('kontakte.entfernen')}
          </Button>
        )}
      </div>
    </form>
  )
}
