/* Der eine Weg zu einem neuen Postfach: das Fenster hinter der (+)-Kachel.
 *
 * ⚠️ **Erst wählen, dann eintragen.** Seit es Google und Microsoft gibt, ist
 * „Postfach hinzufügen" keine einzelne Maske mehr. Wer den IMAP-Server eines
 * Google-Kontos von Hand einträgt, macht dieselbe Arbeit, die die Zustimmung
 * schon erledigt hat — und scheitert am Ende an einem Passwort, das Google
 * gar nicht mehr annimmt.
 *
 * ⚠️ **Die Auswahl erscheint nur, wenn es etwas zu wählen gibt.** Hat der
 * Betreiber keine App eingetragen, bleibt IMAP der einzige Weg; dann ist eine
 * Seite mit einem einzigen Knopf reine Reiberei.
 *
 * ⚠️ **IMAP bleibt eine ganze Seite, kein Fensterinhalt.** Das Formular trägt
 * zwei Serverblöcke und einen Verbindungstest — in einem Fenster wäre das ein
 * Guckloch. Das Fenster ist die Weiche, nicht die Werkbank.
 *
 * ⚠️ **Der Weg über Google verlässt die Anwendung.** Die Zustimmung erteilt
 * ein Mensch beim Anbieter, danach lädt die Seite neu. Was danach noch fehlt
 * — Postfach anlegen, Kalender wählen — steht in `RUECKWEG` und wird hier
 * fortgesetzt; ohne das säße man nach der Zustimmung wieder am Anfang.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Calendar, Check, KeyRound, Mail, Server } from 'lucide-react'
import { ApiFehler, api } from '../api/client'
import type { KontoZeile } from '../api/client'
import { Button, Checkbox, Dialog } from '../ds'
import { RUECKWEG } from '../lib/oauthrueckweg'

/** Welche Anbieter einen eigenen Weg haben. IMAP steht immer daneben. */
type Anbieter = 'google' | 'microsoft'

/* ⚠️ **Nur Google spricht CalDAV.** Microsoft hat seinen Kalender hinter der
   Graph-API; ein Kalenderschritt, der dort ins Leere führt, wäre eine
   Sackgasse mit Beschriftung. Steht als offener Punkt in SPAETER.md. */
const MIT_KALENDER: Record<string, boolean> = { google: true, microsoft: false }

interface Zugang {
  id: string
  art: string
  adresse: string
  letzter_fehler: string
}

interface AnbieterZeile {
  art: string
  name: string
  eingerichtet: boolean
}

interface Gefunden {
  url: string
  name: string
  /** Steht schon in der Spalte — dann nicht noch einmal anbieten. */
  schon_verbunden?: boolean
}

interface Vorschlag {
  gefunden: boolean
  imap: { server: string; port: number; sicherheit: string; benutzer: string }
  smtp: { server: string; port: number; sicherheit: string; benutzer: string }
}

type Schritt = 'wahl' | 'zustimmung' | 'legt_an' | 'kalender' | 'fertig'

interface Props {
  offen: boolean
  aufSchliessen: () => void
  /** IMAP läuft weiter über das ganzseitige Formular — siehe oben. */
  aufImap: () => void
  /** Ein Postfach ist entstanden; die Kachelliste muss nachziehen. */
  aufAngelegt: () => void
  /** Was schon da ist. ⚠️ Eine Zustimmung, deren Postfach bereits steht, darf
   *  nicht als „Postfach anlegen" angeboten werden — der Server wiese es ab,
   *  und der Klick endete in einer Fehlermeldung statt in einem Weg. */
  konten: KontoZeile[]
}

export function PostfachHinzufuegen({
  offen,
  aufSchliessen,
  aufImap,
  aufAngelegt,
  konten,
}: Props) {
  const { t, i18n } = useTranslation()

  const [schritt, setSchritt] = useState<Schritt>('wahl')
  const [art, setArt] = useState<Anbieter>('google')
  const [zugaenge, setZugaenge] = useState<Zugang[] | null>(null)
  const [anbieter, setAnbieter] = useState<AnbieterZeile[]>([])
  const [zugang, setZugang] = useState<Zugang | null>(null)
  const [konto, setKonto] = useState<KontoZeile | null>(null)
  const [gefunden, setGefunden] = useState<Gefunden[] | null>(null)
  const [gewaehlt, setGewaehlt] = useState<string[]>([])
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  const meldung = useCallback(
    (kennung: string) => {
      const schluessel = `oauth.fehler_${kennung}`
      return i18n.exists(schluessel) ? t(schluessel) : t('oauth.fehler_allgemein')
    },
    [i18n, t],
  )

  const laden = useCallback(async () => {
    try {
      setZugaenge(await api.holen<Zugang[]>('/api/mailoauth/zugaenge'))
    } catch {
      setZugaenge([])
    }
    /* ⚠️ **Was nicht eingerichtet ist, wird nicht angeboten.** Ein Knopf, der
       nur in eine Fehlermeldung führt, ist eine Sackgasse mit Beschriftung —
       dieselbe Regel wie beim gesperrten Google-Eintrag im Kalender.

       ⚠️ **`/moeglich`, nicht `/anbieter`.** Letzteres steht nur dem Betreiber
       offen; ein gewöhnlicher Benutzer bekäme dort eine Absage und sähe dann
       nie einen Google-Weg, obwohl es einen gibt. */
    try {
      setAnbieter(await api.holen<AnbieterZeile[]>('/api/mailoauth/moeglich'))
    } catch {
      setAnbieter([])
    }
  }, [])

  useEffect(() => {
    if (offen) void laden()
  }, [offen, laden])

  /* --- Zurück vom Anbieter ---------------------------------------------- */

  // ⚠️ Genau einmal. Ohne die Sperre liefe das Anlegen bei jedem Zeichnen neu.
  const fortgesetzt = useRef(false)

  useEffect(() => {
    if (!offen || fortgesetzt.current) return
    if (RUECKWEG.weiter !== 'postfach') return
    fortgesetzt.current = true
    if (RUECKWEG.stand !== 'ok') {
      setSchritt('zustimmung')
      setFehler(meldung(RUECKWEG.stand))
      return
    }
    void (async () => {
      /* ⚠️ **„Abruf gescheitert" ist nicht „Zustimmung unbekannt".** Ein
         leerer Rückfall aus dem `catch` sähe genauso aus wie eine Liste ohne
         den Eintrag — und schickte den Benutzer die Zustimmung neu erteilen,
         obwohl sie steht. Am 03.09.2026 genau so gesehen, als der
         Entwicklungsserver währenddessen neu lud. */
      const alle = await api.holen<Zugang[]>('/api/mailoauth/zugaenge').catch(() => null)
      if (alle === null) {
        setSchritt('zustimmung')
        setFehler(t('postfachneu.zugaenge_nicht_geladen'))
        return
      }
      setZugaenge(alle)
      const treffer = alle.find((z) => z.id === RUECKWEG.zugang)
      if (!treffer) {
        setSchritt('zustimmung')
        setFehler(meldung('oauth_zugang_unbekannt'))
        return
      }
      setArt(treffer.art as Anbieter)
      await postfachAnlegen(treffer)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offen, meldung, t])

  /* --- Die Schritte ------------------------------------------------------ */

  async function zustimmungHolen(fuer: Anbieter) {
    setFehler('')
    try {
      const { ziel } = await api.senden<{ ziel: string }>(`/api/mailoauth/${fuer}/start`, {
        zweck: 'postfach',
      })
      // Eine echte Navigation, kein fetch: Die Zustimmung erteilt der Mensch
      // beim Anbieter, nicht nexmail in seinem Namen.
      window.location.href = ziel
    } catch (f) {
      setFehler(meldung(f instanceof ApiFehler ? f.detail : ''))
    }
  }

  /** Steht für diese Zustimmung schon ein Postfach?
   *
   * ⚠️ **`bestand` wird mitgegeben, nicht aus `konten` gelesen.** Nach dem
   * Rückweg vom Anbieter läuft dieser Griff, während die Seite ihre Kachelliste
   * noch holt: `konten` ist dann leer, die Antwort „nein" falsch, und das
   * Fenster legte ein Postfach an, das es schon gibt. Genau so gemeldet am
   * 03.09.2026 („er sagt zwar hinzugefügt, mir wird aber keine Kachel
   * angezeigt").
   */
  function schonDa(z: Zugang, bestand: KontoZeile[] = konten) {
    const adresse = (z.adresse || '').toLowerCase()
    return Boolean(adresse) && bestand.some((k) => k.adresse.toLowerCase() === adresse)
  }

  async function postfachAnlegen(fuer: Zugang) {
    setZugang(fuer)
    setFehler('')
    // Frisch nachsehen statt der Anzeige zu glauben — siehe `schonDa`.
    const bestand = await api.holen<KontoZeile[]>('/api/konten').catch(() => konten)
    /* ⚠️ **Was schon steht, wird nicht noch einmal angelegt.** Der Rückweg vom
       Anbieter führt auch dann hierher, wenn jemand nur die Zustimmung erneuert
       hat; ein zweiter Anlauf liefe in „Dieses Postfach ist schon
       eingerichtet" — richtig, aber keine Antwort auf das, was er wollte. */
    if (schonDa(fuer, bestand)) {
      if (!MIT_KALENDER[fuer.art]) {
        setSchritt('fertig')
        return
      }
      await kalenderSuchen(fuer)
      return
    }
    setSchritt('legt_an')
    setLaeuft(true)
    try {
      /* Die Serverdaten kennt nexmail schon — dieselbe Suche wie im
         Formular. Sie von Hand eintragen zu lassen wäre genau die Arbeit, die
         die Zustimmung gerade abgenommen hat. */
      const vorschlag = await api.senden<Vorschlag>('/api/konten/vorschlag', {
        adresse: fuer.adresse,
      })
      if (!vorschlag.gefunden) {
        /* Kein Rateversuch. Weiter geht es über das Formular — dort steht die
           Zustimmung in der Auswahl, und die Server trägt man von Hand ein. */
        setFehler(t('postfachneu.keine_serverdaten'))
        setSchritt('zustimmung')
        return
      }
      const neu = await api.senden<KontoZeile>('/api/konten', {
        anzeigename: '',
        absendername: '',
        adresse: fuer.adresse,
        imap_server: vorschlag.imap.server,
        imap_port: vorschlag.imap.port,
        imap_sicherheit: vorschlag.imap.sicherheit,
        imap_benutzer: vorschlag.imap.benutzer || fuer.adresse,
        imap_passwort: '',
        smtp_server: vorschlag.smtp.server,
        smtp_port: vorschlag.smtp.port,
        smtp_sicherheit: vorschlag.smtp.sicherheit,
        smtp_benutzer: vorschlag.smtp.benutzer || fuer.adresse,
        smtp_passwort: '',
        oauth_zugang_id: fuer.id,
      })
      setKonto(neu)
      aufAngelegt()
      if (!MIT_KALENDER[fuer.art]) {
        setSchritt('fertig')
        return
      }
      await kalenderSuchen(fuer)
    } catch (f) {
      const kennung = f instanceof ApiFehler ? f.detail : ''
      setFehler(kennung || t('anmeldung.fehler_allgemein'))
      setSchritt('zustimmung')
    } finally {
      setLaeuft(false)
    }
  }

  async function kalenderSuchen(fuer: Zugang) {
    setSchritt('kalender')
    setFehler('')
    setLaeuft(true)
    try {
      const liste = await api.senden<Gefunden[]>('/api/kalender/pruefen', {
        art: fuer.art,
        oauth_zugang_id: fuer.id,
      })
      setGefunden(liste)
      /* Vorgabe: alle an — außer denen, die schon dastehen. Wer nur einen
         will, hakt drei ab; wer alle will, klickte sonst fünfmal. Ein schon
         verbundener Kalender bliebe dagegen in der Absage stecken. */
      setGewaehlt(liste.filter((k) => !k.schon_verbunden).map((k) => k.url))
    } catch (f) {
      /* ⚠️ **Ein misslungener Kalenderabruf darf das Postfach nicht
         entwerten** — es steht schon, hier geht es nur noch um eine Zugabe.
         ⚠️ **Aber sein Grund darf nicht verschwinden.** Zuerst stand hier ein
         blankes `catch`, und die Folge war „keine Kalender gefunden" bei einem
         Konto, das welche hat: Google wies ab, weil im Cloud-Projekt die
         CalDAV-API fehlte, und niemand konnte das der Anzeige ansehen. */
      const kennung = f instanceof ApiFehler ? f.detail : ''
      const schluessel = `kalender.fehler_${kennung}`
      setFehler(i18n.exists(schluessel) ? t(schluessel) : t('kalender.fehler_allgemein'))
      setGefunden([])
    } finally {
      setLaeuft(false)
    }
  }

  async function kalenderUebernehmen() {
    if (!zugang) return
    setLaeuft(true)
    setFehler('')
    try {
      await api.senden('/api/kalender/verbinden', {
        art: zugang.art,
        oauth_zugang_id: zugang.id,
        auswahl: (gefunden ?? []).filter((k) => gewaehlt.includes(k.url)),
      })
      setSchritt('fertig')
    } catch (f) {
      setFehler(f instanceof ApiFehler && f.detail ? f.detail : t('anmeldung.fehler_allgemein'))
    } finally {
      setLaeuft(false)
    }
  }

  const schliessen = useCallback(() => {
    setSchritt('wahl')
    setZugang(null)
    setKonto(null)
    setGefunden(null)
    setFehler('')
    fortgesetzt.current = false
    aufSchliessen()
  }, [aufSchliessen])

  /* --- Was gezeigt wird --------------------------------------------------- */

  const offene = anbieter.filter((a) => a.eingerichtet).map((a) => a.art as Anbieter)
  const meine = (zugaenge ?? []).filter((z) => z.art === art)

  /* ⚠️ **Nur eine Möglichkeit heißt: keine Auswahl.** Hat der Betreiber keine
     App eingetragen, führt der Weg gleich ins Formular — eine Seite mit einem
     einzigen Knopf ist ein Klick, der nichts entscheidet. */
  const nurImap = anbieter.length > 0 && offene.length === 0

  useEffect(() => {
    if (offen && nurImap && schritt === 'wahl' && RUECKWEG.weiter !== 'postfach') {
      schliessen()
      aufImap()
    }
  }, [offen, nurImap, schritt, schliessen, aufImap])

  if (!offen) return null

  return (
    <Dialog
      open
      width={560}
      /* ⚠️ **Nicht wegklickbar, solange etwas läuft.** Das Anlegen dauert
         Sekunden — in denen klickt man; ein Klick daneben schloss das Fenster,
         die Arbeit lief weiter, und die Frage nach den Kalendern kam nie. */
      abweisbar={!laeuft && schritt !== 'legt_an'}
      title={t('postfachneu.hinzufuegen_titel')}
      description={schritt === 'wahl' ? t('postfachneu.hinzufuegen_text') : undefined}
      onClose={schliessen}
      footer={fussleiste()}
    >
      {fehler && (
        <p className="mb-3 flex items-start gap-2 rounded-md bg-danger-soft px-3 py-2 text-[12px] leading-relaxed text-danger">
          <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" />
          <span>{fehler}</span>
        </p>
      )}

      {schritt === 'wahl' && (
        <div className="flex flex-col gap-2">
          <Weg
            symbol={<Server className="size-5" />}
            titel={t('postfachneu.weg_imap')}
            text={t('postfachneu.weg_imap_text')}
            aufKlick={() => {
              schliessen()
              aufImap()
            }}
          />
          {offene.map((a) => (
            <Weg
              key={a}
              symbol={<Mail className="size-5" />}
              titel={t(`postfachneu.weg_${a}`)}
              text={t(`postfachneu.weg_${a}_text`)}
              aufKlick={() => {
                setArt(a)
                setFehler('')
                setSchritt('zustimmung')
              }}
            />
          ))}
        </div>
      )}

      {schritt === 'zustimmung' && (
        <div className="flex flex-col gap-3">
          <p className="mb-0 text-[13px] leading-relaxed text-fg-3">
            {t(`postfachneu.zustimmung_${art}`)}
          </p>

          {/* ⚠️ **Mehrere Konten desselben Anbieters sind der Normalfall.**
              Wer dienstlich und privat bei Google ist, soll nicht wählen
              müssen — deshalb steht neben den erteilten Zustimmungen immer
              auch der Weg zu einer weiteren. */}
          {meine.length > 0 && (
            <ul className="flex list-none flex-col gap-2 p-0">
              {meine.map((z) => (
                <li key={z.id}>
                  <button
                    type="button"
                    disabled={laeuft}
                    onClick={() => void postfachAnlegen(z)}
                    className="flex w-full items-center gap-3 rounded-lg border border-line bg-surface-1 px-3 py-2.5 text-left transition-colors duration-[var(--dur-fast)] hover:border-accent disabled:opacity-60"
                  >
                    <KeyRound aria-hidden className="size-4 shrink-0 text-fg-4" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">
                      {z.adresse || z.art}
                    </span>
                    {z.letzter_fehler ? (
                      <span className="shrink-0 text-[12px] text-warning">
                        {t('oauth.abgelaufen')}
                      </span>
                    ) : (
                      <span className="shrink-0 text-[12px] text-accent-text">
                        {schonDa(z) ? t('postfachneu.schon_da') : t('postfachneu.dieses_nehmen')}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div>
            <Button variant="secondary" size="sm" onClick={() => void zustimmungHolen(art)}>
              {meine.length > 0 ? t('postfachneu.weiteres_konto') : t(`oauth.verbinden_${art}`)}
            </Button>
          </div>
        </div>
      )}

      {schritt === 'legt_an' && <p className="mb-0 text-[13px] text-fg-3">{t('postfachneu.legt_an')}</p>}

      {schritt === 'kalender' && (
        <div className="flex flex-col gap-3">
          <p className="mb-0 flex items-start gap-2 text-[13px] leading-relaxed text-fg-3">
            <Calendar aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-4" />
            <span>{t('postfachneu.kalender_frage')}</span>
          </p>
          {laeuft && <p className="mb-0 text-[12px] text-fg-4">{t('postfachneu.kalender_sucht')}</p>}
          {/* ⚠️ Nicht neben einem Fehler. „Kein Kalender" widerspricht der
              Meldung darüber, und dann glaubt man keiner von beiden. */}
          {!laeuft && !fehler && (gefunden ?? []).length === 0 && (
            <p className="mb-0 text-[12px] text-fg-4">{t('postfachneu.kalender_keine')}</p>
          )}
          <div className="flex flex-col gap-1.5">
            {(gefunden ?? []).map((k) => (
              <Checkbox
                key={k.url}
                label={k.name}
                description={k.schon_verbunden ? t('kalender.schon_verbunden') : undefined}
                disabled={k.schon_verbunden}
                checked={gewaehlt.includes(k.url)}
                onCheckedChange={(an) =>
                  setGewaehlt((alt) => (an ? [...alt, k.url] : alt.filter((u) => u !== k.url)))
                }
              />
            ))}
          </div>
        </div>
      )}

      {schritt === 'fertig' && (
        <p className="mb-0 flex items-start gap-2 text-[13px] leading-relaxed text-fg-1">
          <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
          <span>
            {t('postfachneu.fertig', {
              name: konto?.anzeigename || konto?.adresse || zugang?.adresse || '',
            })}
          </span>
        </p>
      )}
    </Dialog>
  )

  function fussleiste() {
    if (schritt === 'wahl') {
      return (
        <Button variant="ghost" onClick={schliessen}>
          {t('aktion.abbrechen')}
        </Button>
      )
    }
    if (schritt === 'zustimmung') {
      return (
        <Button variant="ghost" onClick={() => setSchritt('wahl')}>
          {t('aktion.zurueck')}
        </Button>
      )
    }
    if (schritt === 'kalender') {
      return (
        <>
          <Button variant="ghost" onClick={() => setSchritt('fertig')}>
            {t('postfachneu.kalender_ueberspringen')}
          </Button>
          <Button
            variant="primary"
            loading={laeuft}
            disabled={laeuft || gewaehlt.length === 0}
            onClick={() => void kalenderUebernehmen()}
          >
            {t('postfachneu.kalender_uebernehmen')}
          </Button>
        </>
      )
    }
    if (schritt === 'fertig') {
      return (
        <Button
          variant="primary"
          onClick={() => {
            aufAngelegt()
            schliessen()
          }}
        >
          {t('aktion.fertig')}
        </Button>
      )
    }
    // „Legt an" hat keinen Ausgang: Es dauert Sekunden und endet von selbst.
    return undefined
  }
}

function Weg({
  symbol,
  titel,
  text,
  aufKlick,
}: {
  symbol: ReactNode
  titel: string
  text: string
  aufKlick: () => void
}) {
  return (
    <button
      type="button"
      onClick={aufKlick}
      className="flex items-start gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3 text-left transition-colors duration-[var(--dur-fast)] hover:border-accent"
    >
      <span aria-hidden className="mt-0.5 shrink-0 text-fg-3">
        {symbol}
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-fg-1">{titel}</span>
        <span className="block text-[12px] leading-relaxed text-fg-3">{text}</span>
      </span>
    </button>
  )
}
