/* Darstellung — was jeder für sich einstellt.
 *
 * ⚠️ **Diese Einstellungen liegen im Browser, nicht im Server.** Sie gehören
 * zum Gerät: Am großen Bildschirm will man eine andere Dichte als am Telefon.
 * Das steht auch in der Oberfläche — eine Einstellung, die man am zweiten
 * Gerät nicht wiederfindet und die das nicht sagt, wirkt kaputt.
 *
 * ⚠️ **Die Zeitzone steht hier bewusst nicht.** Sie gilt für alle Benutzer und
 * liegt im Server; ihr Platz ist die Verwaltung. Zweimal dieselbe Einstellung
 * an zwei Orten heißt: Niemand weiß, welche gewinnt.
 *
 * Hell/Dunkel und Sprache stehen ebenfalls nicht hier, sondern oben rechts in
 * der Leiste: Man ändert sie beiläufig und will dafür keine Seite aufsuchen.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Image as ImageIcon, Inbox } from 'lucide-react'
import { AppearanceCard } from '../vendor/nexkonten/AccountCards'
import { Box, Button, Card, CheckboxRow, Notice, Row, Rows, SelectField } from '../vendor/nexui'
import { api } from '../api/client'
import { useGemerkt } from '../lib/haken'
import { WISCH_LINKS_VORGABE, WISCH_RECHTS_VORGABE } from '../lib/wischen'
import type { WischAktion } from '../lib/wischen'
import { DANACH_REIHE, danachAus } from '../lib/danach'
import type { Danach } from '../lib/danach'
import { servermeldung } from '../lib/servermeldung'

export type Dichte = 'kompakt' | 'normal'

/* Aufbewahrung in Tagen für Papierkorb und Junk. 0 heißt: nie von selbst
   leeren. ⚠️ Genau die Stufen, die der Server erlaubt (Positivliste in
   services/aufraeumen.py) — eine hier erfundene Stufe käme als 400 zurück. */
interface Aufraeumen {
  papierkorb_tage: number
  junk_tage: number
}

/* Bilder in fremden Mails — der globale Schalter und die freigegebenen
   Absender. ⚠️ **Liegt im Server, je Benutzer**, anders als der Rest dieser
   Seite: Das ist keine Frage des Bildschirms, sondern eine Entscheidung über
   die eigene Post. Derselbe Grund wie beim Aufräumen. */
interface Bilder {
  immer_laden: boolean
  absender: string[]
  /** Logos der Absenderdomains holen (Diskussion #4). */
  logos: boolean
}

const AUFRAEUMEN_STUFEN = [0, 7, 14, 30, 90] as const

/* Die vier Moeglichkeiten je Wischrichtung. Die Reihenfolge ist die der
   Vorgaben: aus, dann die beiden Aufraeum-Wege, dann der Umschalter. */
const WISCH_AKTIONEN: WischAktion[] = ['aus', 'archivieren', 'loeschen', 'gelesen']

interface Props {
  /** Nach dem Logo-Schalter: `ich` trägt seinen Stand, und die Liste baut
   *  daraus die Bildadresse. Ohne Auffrischen wirkte er erst nach F5. */
  ichNeuLaden?: () => void
  /** Hell oder dunkel. ⚠️ Seit dem 22.11.2026 nur noch hier, nicht mehr
   *  oben rechts in der Kopfleiste, wie in nexnotes unter
   *  „Darstellung". Liegt im Browser, wie bisher. */
  /** Hell, dunkel oder wie das System (seit 24.11.2026, wie nexnotes und nextasks). */
  modus?: 'dark' | 'light' | 'system'
  aufModus?: (m: 'dark' | 'light' | 'system') => void
}

export function Darstellung({ ichNeuLaden, modus, aufModus }: Props = {}) {
  const { t } = useTranslation()
  const [dichte, setDichte] = useGemerkt<Dichte>('nexmail.dichte', 'normal')
  const [anreisser, setAnreisser] = useGemerkt<boolean>('nexmail.anreisser', true)
  const [punkte, setPunkte] = useGemerkt<boolean>('nexmail.punkte', true)
  /* Der Kreis vor jedem Absender. Im Browser: ob die Liste dafür Platz
     hergibt, ist eine Frage des Bildschirms. Was darin steht und ob dafür
     etwas geholt wird, steht unten bei den Bildern und liegt im Server. */
  const [absenderbilder, setAbsenderbilder] = useGemerkt<boolean>('nexmail.absenderbilder', true)
  /* ⚠️ **Im Browser, nicht im Server — anders als „Bilder immer laden"
     weiter unten.** Ob eine fremde Mail eingedunkelt wird, entscheidet der
     Bildschirm, vor dem man sitzt: am hellen Arbeitsplatz will man das weiße
     Blatt, abends nicht. Bilder dagegen holt der **Server**, und der muss
     wissen, ob er darf. */
  const [eindunkeln, setEindunkeln] = useGemerkt<boolean>('nexmail.mails_eindunkeln', false)
  /* Wann eine offene Nachricht als gelesen gilt — in Sekunden.
     `0` heißt sofort, `-1` heißt: nur von Hand.
     ⚠️ **Outlooks Auswahl, nicht eine eigene.** „Wer Outlook bedienen kann,
     soll sich hier zu Hause fühlen" — und diese Einstellung ist genau die,
     die dort jeder kennt, der sie je gesucht hat. */
  const [gelesenNach, setGelesenNach] = useGemerkt<number>('nexmail.gelesen_nach', 2)
  /* Was nach Löschen, Archivieren oder Verschieben aufgeht. Wieder Outlooks
     Einstellung, dazu „die neueste" (Issue #6). ⚠️ Derselbe Schlüssel wie in
     `App`, der ab dem nächsten Handgriff gilt, ohne F5. */
  const [danachGemerkt, setDanach] = useGemerkt<Danach>('nexmail.danach', 'nichts')
  const danach = danachAus(danachGemerkt)
  /* „Senden rückholen" — wie viele Sekunden eine gesendete Nachricht noch
     zurückzuholen ist. Der Wert wird beim Senden als Aufschub mitgeschickt
     (`senden_ab = jetzt + Aufschub`); der Server hält sie so lange im Ausgang.
     ⚠️ **Vorgabe aus.** Wer nichts einstellt, merkt keinen Unterschied — jede
     Mail geht wie bisher sofort hinaus. */
  const [rueckholen, setRueckholen] = useGemerkt<number>('nexmail.rueckholen', 0)
  /* Wisch-Aktionen der schmalen Ansicht. ⚠️ Dieselben Schluessel liest `App`
     — wer hier umstellt, wischt ab dem naechsten Zug anders, ohne F5. */
  const [wischLinks, setWischLinks] = useGemerkt<WischAktion>(
    'nexmail.wisch_links',
    WISCH_LINKS_VORGABE,
  )
  const [wischRechts, setWischRechts] = useGemerkt<WischAktion>(
    'nexmail.wisch_rechts',
    WISCH_RECHTS_VORGABE,
  )

  /* ⚠️ Anders als der Rest der Seite liegt das Aufräumen im Server, je
     Benutzer — es löscht endgültig und darf nicht je Gerät verschieden sein.
     Drei Zustände statt zwei: noch nicht geladen · geladen · ging nicht.
     Ein Fehler darf nicht wie „aus" aussehen — wer „90 Tage" eingestellt hat
     und ein stilles „Nie" sieht, traut der Einstellung nie wieder. */
  const [aufraeumen, setAufraeumen] = useState<Aufraeumen | null>(null)
  const [aufraeumenFehler, setAufraeumenFehler] = useState('')

  const aufraeumenLaden = useCallback(() => {
    setAufraeumenFehler('')
    api
      .holen<Aufraeumen>('/api/einstellungen/aufraeumen')
      .then(setAufraeumen)
      .catch(() => setAufraeumenFehler(t('anmeldung.fehler_allgemein')))
  }, [t])

  useEffect(aufraeumenLaden, [aufraeumenLaden])

  const aufraeumenStellen = (feld: keyof Aufraeumen, wert: number) => {
    if (!aufraeumen) return
    const neu = { ...aufraeumen, [feld]: wert }
    setAufraeumen(neu)
    api.aendern<Aufraeumen>('/api/einstellungen/aufraeumen', neu).catch((f) => {
      // Der alte Stand gilt weiter — also wieder anzeigen, was der Server hat.
      setAufraeumenFehler(
        servermeldung(f, t('anmeldung.fehler_allgemein')),
      )
      api.holen<Aufraeumen>('/api/einstellungen/aufraeumen').then(setAufraeumen).catch(() => {})
    })
  }

  /* Dieselben drei Zustände wie beim Aufräumen: noch nicht geladen · geladen ·
     ging nicht. Ein Fehler darf nicht wie „aus" aussehen. */
  const [bilder, setBilder] = useState<Bilder | null>(null)
  const [bilderFehler, setBilderFehler] = useState('')

  const bilderLaden = useCallback(() => {
    setBilderFehler('')
    api
      .holen<Bilder>('/api/einstellungen/bilder')
      .then(setBilder)
      .catch(() => setBilderFehler(t('anmeldung.fehler_allgemein')))
  }, [t])

  useEffect(bilderLaden, [bilderLaden])

  const bilderStellen = (immer: boolean) => {
    if (!bilder) return
    setBilder({ ...bilder, immer_laden: immer })
    api
      .aendern<Bilder>('/api/einstellungen/bilder', { immer_laden: immer })
      .then(setBilder)
      .catch((f) => {
        setBilderFehler(
          servermeldung(f, t('anmeldung.fehler_allgemein')),
        )
        bilderLaden()
      })
  }

  const logosStellen = (an: boolean) => {
    if (!bilder) return
    setBilder({ ...bilder, logos: an })
    api
      .aendern<Bilder>('/api/einstellungen/bilder', { logos: an })
      .then((neu) => {
        setBilder(neu)
        ichNeuLaden?.()
      })
      .catch((f) => {
        setBilderFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
        bilderLaden()
      })
  }

  const absenderEntfernen = (adresse: string) => {
    api
      .senden<Bilder>('/api/einstellungen/bilder/absender/entfernen', { adresse })
      .then(setBilder)
      .catch(() => setBilderFehler(t('anmeldung.fehler_allgemein')))
  }

  const stufenText = (n: number) =>
    n === 0 ? t('darstellung.aufraeumen_aus') : t('darstellung.aufraeumen_tage', { n })

  return (
    <>
      {/* konten 1.1.0 (E5, E17): „Aussehen" zuerst, gilt für das Konto auf allen Geräten. */}
      {modus && aufModus && <AppearanceCard theme={modus} onChange={(m) => aufModus(m)} />}

      <Card id="list" icon={Inbox} title={t('darstellung.liste_titel')} subtitle={t('darstellung.nur_dieses_geraet')}>
        <SelectField
          label={t('darstellung.dichte')}
          hints={[t('darstellung.dichte_hinweis')]}
          value={dichte}
          onChange={(e) => setDichte(e.target.value as Dichte)}
          options={[
            { value: 'normal', label: t('darstellung.dichte_normal') },
            { value: 'kompakt', label: t('darstellung.dichte_kompakt') },
          ]}
        />
        <SelectField
          label={t('darstellung.gelesen')}
          hints={[t('darstellung.gelesen_hinweis')]}
          value={String(gelesenNach)}
          onChange={(e) => setGelesenNach(Number(e.target.value))}
          options={[
            { value: '0', label: t('darstellung.gelesen_sofort') },
            { value: '2', label: t('darstellung.gelesen_sekunden', { n: 2 }) },
            { value: '5', label: t('darstellung.gelesen_sekunden', { n: 5 }) },
            { value: '10', label: t('darstellung.gelesen_sekunden', { n: 10 }) },
            { value: '-1', label: t('darstellung.gelesen_hand') },
          ]}
        />
        <SelectField
          label={t('darstellung.danach')}
          hints={[t('darstellung.danach_hinweis')]}
          value={danach}
          onChange={(e) => setDanach(e.target.value as Danach)}
          options={DANACH_REIHE.map((d) => ({ value: d, label: t(`darstellung.danach_${d}`) }))}
        />
        <SelectField
          label={t('darstellung.rueckholen')}
          hints={[t('darstellung.rueckholen_hinweis')]}
          value={String(rueckholen)}
          onChange={(e) => setRueckholen(Number(e.target.value))}
          options={[
            { value: '0', label: t('darstellung.rueckholen_aus') },
            { value: '5', label: t('darstellung.rueckholen_sekunden', { n: 5 }) },
            { value: '10', label: t('darstellung.rueckholen_sekunden', { n: 10 }) },
            { value: '30', label: t('darstellung.rueckholen_sekunden', { n: 30 }) },
          ]}
        />
        <SelectField
          label={t('darstellung.wisch_links')}
          hints={[t('darstellung.wisch_hinweis')]}
          value={wischLinks}
          onChange={(e) => setWischLinks(e.target.value as WischAktion)}
          options={WISCH_AKTIONEN.map((a) => ({ value: a, label: t(`darstellung.wisch_${a}`) }))}
        />
        <SelectField
          label={t('darstellung.wisch_rechts')}
          value={wischRechts}
          onChange={(e) => setWischRechts(e.target.value as WischAktion)}
          options={WISCH_AKTIONEN.map((a) => ({ value: a, label: t(`darstellung.wisch_${a}`) }))}
        />
        <CheckboxRow
          checked={anreisser}
          label={t('darstellung.anreisser')}
          hint={t('darstellung.anreisser_hinweis')}
          onChange={setAnreisser}
        />
        <CheckboxRow
          checked={absenderbilder}
          label={t('darstellung.absenderbilder')}
          hint={t('darstellung.absenderbilder_hinweis')}
          onChange={setAbsenderbilder}
        />
        <CheckboxRow checked={punkte} label={t('darstellung.punkte')} hint={t('darstellung.punkte_hinweis')} onChange={setPunkte} />
        <CheckboxRow
          checked={eindunkeln}
          label={t('darstellung.eindunkeln')}
          hint={t('darstellung.eindunkeln_hinweis')}
          onChange={setEindunkeln}
        />
      </Card>

      {/* Der eine Satz, der die Folge nennt: endgültig, auch auf dem Server. */}
      <Card id="cleanup" icon="Trash2" title={t('darstellung.aufraeumen_titel')} subtitle={t('darstellung.aufraeumen_hinweis')}>
        {aufraeumenFehler && (
          <Notice tone="danger">
            {aufraeumenFehler}{' '}
            <Button kind="secondary" size="sm" icon="RefreshCw" onClick={aufraeumenLaden}>
              {t('stoerung.nochmal')}
            </Button>
          </Notice>
        )}
        {aufraeumen && (
          <>
            <SelectField
              label={t('darstellung.aufraeumen_papierkorb')}
              value={String(aufraeumen.papierkorb_tage)}
              onChange={(e) => aufraeumenStellen('papierkorb_tage', Number(e.target.value))}
              options={AUFRAEUMEN_STUFEN.map((n) => ({ value: String(n), label: stufenText(n) }))}
            />
            <SelectField
              label={t('darstellung.aufraeumen_junk')}
              value={String(aufraeumen.junk_tage)}
              onChange={(e) => aufraeumenStellen('junk_tage', Number(e.target.value))}
              options={AUFRAEUMEN_STUFEN.map((n) => ({ value: String(n), label: stufenText(n) }))}
            />
          </>
        )}
      </Card>

      <Card id="images" icon={ImageIcon} title={t('darstellung.bilder_titel')} subtitle={t('darstellung.bilder_hinweis')}>
        {bilderFehler && (
          <Notice tone="danger">
            {bilderFehler}{' '}
            <Button kind="secondary" size="sm" icon="RefreshCw" onClick={bilderLaden}>
              {t('stoerung.nochmal')}
            </Button>
          </Notice>
        )}
        {bilder && (
          <>
            <CheckboxRow
              checked={bilder.immer_laden}
              label={t('darstellung.bilder_immer')}
              hint={t('darstellung.bilder_immer_hinweis')}
              onChange={bilderStellen}
            />
            <CheckboxRow
              checked={bilder.logos}
              label={t('darstellung.logos')}
              hint={t('darstellung.logos_hinweis')}
              onChange={logosStellen}
            />
            <Box title={t('darstellung.bilder_absender')} hint={bilder.absender.length === 0 ? t('darstellung.bilder_absender_leer') : undefined}>
              {bilder.absender.length > 0 && (
                <Rows label={t('darstellung.bilder_absender')}>
                  {bilder.absender.map((adresse) => (
                    <Row
                      key={adresse}
                      name={<span className="font-mono text-xs">{adresse}</span>}
                      action={
                        <Button
                          kind="danger"
                          size="sm"
                          icon="Trash2"
                          aria-label={t('darstellung.bilder_absender_entfernen', { adresse })}
                          onClick={() => absenderEntfernen(adresse)}
                        >
                          {t('einstellungen.entfernen')}
                        </Button>
                      }
                    />
                  ))}
                </Rows>
              )}
            </Box>
          </>
        )}
      </Card>
    </>
  )
}
