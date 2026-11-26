/* Benachrichtigungen — Meldungen, wenn nexmail gar nicht offen ist.
 *
 * ⚠️ **Zwei Sorten Einstellung auf einer Seite, und die Trennung steht in der
 * Oberfläche.** Oben: die Erlaubnis, die zu *diesem Browser* gehört. Unten:
 * wobei gemeldet wird, das gilt für das Konto und damit auf allen Geräten.
 * Dieselbe Unterscheidung wie im Reiter Darstellung, wo die Dichte im Browser
 * wohnt und „Bilder immer laden" im Server — und wie dort sagt die Seite es
 * dazu. Eine Einstellung, die man am zweiten Gerät nicht wiederfindet und die
 * das nicht sagt, wirkt kaputt.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { appPfad } from '../lib/basis'
import { pfadVon } from './einstellungen/bereiche'
import { Box, Card, CheckboxRow, Notice, NotifyWays, SelectField } from '../vendor/nexui'
import { api } from '../api/client'
import * as push from '../lib/push'
import { PushSchrittFehler } from '../lib/pushlage'
import { servermeldung } from '../lib/servermeldung'

interface Einstellungen {
  push_termine: boolean
  push_mail: boolean
  push_mail_alle_ordner: boolean
  push_mail_nur_ungelesen: boolean
  push_mail_buendeln: boolean
  push_ruhezeit: boolean
  push_ruhezeit_von: string
  push_ruhezeit_bis: string
}

interface GeraetZeile {
  id: number
  geraet: string
  angelegt: string
  zuletzt_erreicht: string | null
  dieses: boolean
}

/* Halbe Stunden über den Tag — dieselbe Machart wie die Aufräumstufen unter
   Darstellung: eine feste Liste statt eines freien Zeitfelds, damit der Server
   nichts abweisen kann, was die Maske anbietet. */
const UHRZEITEN = Array.from({ length: 48 }, (_, i) => {
  const stunde = String(Math.floor(i / 2)).padStart(2, '0')
  return `${stunde}:${i % 2 ? '30' : '00'}`
})

export function Benachrichtigungen() {
  const { t, i18n } = useTranslation()
  /* ⚠️ Die Lage steht erst nach einer Rückfrage beim Service Worker fest,
     deshalb nicht als Anfangswert. Bis dahin gilt „noch nicht erlaubt" —
     das ist der harmlose Irrtum von beiden. */
  const [lage, setLage] = useState<push.PushLage>('offen')
  const [einst, setEinst] = useState<Einstellungen | null>(null)
  const [geraete, setGeraete] = useState<GeraetZeile[] | null>(null)
  /* ⚠️ Drei Zustände, nicht zwei: noch nicht geladen · geladen · ging nicht.
     Ein Fehler, der wie eine leere Liste aussieht, ist der Schrecken aus
     „Ein Fehler darf nicht wie Leere aussehen". */
  const [fehler, setFehler] = useState<string | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [probeGesagt, setProbeGesagt] = useState(false)

  /* ⚠️ **Scheitert der Browser, sagt der Satz, woran** (Issue #10). Der Grund
     steht wörtlich dabei, so wie der Browser ihn nennt; nur damit lässt sich
     ein Proxy, der `sw.js` verbiegt, von einem abgeschalteten Push-Dienst
     unterscheiden. */
  function meldung(e: unknown): string {
    if (e instanceof PushSchrittFehler) {
      return e.schritt === 'arbeiter'
        ? t('push.fehler_arbeiter', { grund: e.grund })
        : t('push.fehler_abo', { grund: e.grund })
    }
    return servermeldung(e)
  }

  const laden = useCallback(async () => {
    try {
      /* ⚠️ **Erst nachanmelden, dann lesen.** Ein Browser, dessen Erlaubnis
         noch steht, dessen Abonnement der Server aber nicht kennt, heilt sich
         hier von selbst — ohne jemanden zu fragen, denn nur die Nachfrage
         braucht einen Klick. Scheitert es, bleibt die Seite trotzdem
         bedienbar; der Kasten oben sagt dann, was los ist. */
      await push.sicherstellen().catch(() => null)
      const eigen = await push.vorhandene()
      const [e, g] = await Promise.all([
        api.holen<Einstellungen>('/api/push/einstellungen'),
        api.holen<GeraetZeile[]>(
          `/api/push/geraete${eigen ? `?endpunkt=${encodeURIComponent(eigen.endpunkt)}` : ''}`,
        ),
      ])
      setEinst(e)
      setGeraete(g)
      setFehler(null)
      setLage(await push.lage())
    } catch (e) {
      setFehler(servermeldung(e))
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  async function stellen(teil: Partial<Einstellungen>) {
    if (!einst) return
    const neu = { ...einst, ...teil }
    setEinst(neu) // sofort sichtbar, die Wahrheit holt der Server gleich nach
    try {
      setEinst(await api.aendern<Einstellungen>('/api/push/einstellungen', neu))
    } catch (e) {
      setFehler(servermeldung(e))
      void laden()
    }
  }

  async function erlauben() {
    setLaeuft(true)
    setFehler(null)
    try {
      await push.anmelden()
      await laden()
    } catch (e) {
      /* ⚠️ Der Browser sagt „denied", sobald jemand die Nachfrage wegklickt —
         und danach fragt er nie wieder. Die Lage wird deshalb neu gelesen,
         damit der Kasten sofort den richtigen Satz zeigt statt weiter zum
         Klicken einzuladen. */
      setLage(await push.lage())
      const kennung = e instanceof Error ? e.message : String(e)
      /* „Abgelehnt“ braucht keine Fehlermeldung: Der Kasten sagt es schon,
         und ein bewusstes Nein ist kein Fehler. Alles andere sehr wohl — ein
         Klick, der nichts tut und nichts sagt, ist derselbe Fehler wie ein
         gesperrter Knopf. */
      if (kennung === 'push_keine_antwort') setFehler(t('push.keine_antwort'))
      else if (kennung !== 'push_abgelehnt') setFehler(meldung(e))
    } finally {
      setLaeuft(false)
    }
  }

  /** Die Anmeldung nachholen, wenn die Erlaubnis steht und der Server das
   *  Gerät trotzdem nicht kennt. Fragt nichts, meldet aber den Fehlschlag. */
  async function nachholen() {
    setLaeuft(true)
    setFehler(null)
    try {
      await push.sicherstellen()
      await laden()
    } catch (e) {
      setFehler(meldung(e))
    } finally {
      setLaeuft(false)
    }
  }

  async function probe() {
    setProbeGesagt(false)
    try {
      await api.senden('/api/push/probe', {})
      setProbeGesagt(true)
    } catch (e) {
      setFehler(servermeldung(e))
    }
  }

  async function geraetWeg(zeile: GeraetZeile) {
    try {
      if (zeile.dieses) await push.abmelden(zeile.id)
      else await api.loeschen(`/api/push/geraete/${zeile.id}`)
      await laden()
    } catch (e) {
      setFehler(servermeldung(e))
    }
  }

  const datum = (wert: string) =>
    new Date(wert).toLocaleDateString(i18n.language, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })

  const dieser = geraete?.find((g) => g.dieses) ?? null
  const gesperrt = lage === 'unmoeglich' || lage === 'abgelehnt' || lage === 'kein_home'

  return (
    <>
      {fehler && <Notice tone="danger">{fehler}</Notice>}

      {/* Bauplan „Einstellungen": erste Karte „Auf welchem Weg" (Bausatz `NotifyWays`). nexmail meldet über diesen
          Browser (Web Push) und die iPhone-App, nicht per Mail. */}
      <NotifyWays
        subtitle={t('push.geraet_hinweis')}
        browser={{
          on: lage === 'bereit',
          onTurnOn: () => void (lage === 'erlaubt_ohne_anmeldung' ? nachholen() : erlauben()),
          onTurnOff: () => dieser && void geraetWeg(dieser),
          onProbe: () => void probe(),
          busy: laeuft,
          probing: probeGesagt,
          disabled: gesperrt,
          note: (
            <>
              {t(`push.lage_${lage}`)}. {t(`push.lage_${lage}_hinweis`)} {t('push.ios_hinweis')}
            </>
          ),
        }}
        browsers={{
          items: (geraete ?? []).map((g) => ({
            id: String(g.id),
            name: g.geraet || t('push.unbekanntes_geraet'),
            current: g.dieses,
            detail: `${t('push.angemeldet_am', { datum: datum(g.angelegt) })} · ${
              g.zuletzt_erreicht ? t('push.zuletzt_erreicht', { datum: datum(g.zuletzt_erreicht) }) : t('push.nie_erreicht')
            }`,
          })),
          onRemove: (id) => {
            const zeile = geraete?.find((g) => String(g.id) === id)
            if (zeile) void geraetWeg(zeile)
          },
        }}
        devices={{ href: appPfad(pfadVon('connections')) }}
      />

      {/* nexmails eigene Karte: worüber du hörst. */}
      <Card id="notify-what" icon="Bell" title={t('push.wobei_titel')} subtitle={t('push.wobei_hinweis')}>
        {einst && (
          <>
            <CheckboxRow
              checked={einst.push_termine}
              label={t('push.termine')}
              hint={t('push.termine_hinweis')}
              onChange={(an) => stellen({ push_termine: an })}
            />
            <CheckboxRow
              checked={einst.push_mail}
              label={t('push.mail')}
              hint={t('push.mail_hinweis')}
              onChange={(an) => stellen({ push_mail: an })}
            />
            {einst.push_mail && (
              <Box title={t('push.mail')}>
                <SelectField
                  label={t('push.ordner')}
                  value={einst.push_mail_alle_ordner ? 'alle' : 'posteingang'}
                  onChange={(e) => stellen({ push_mail_alle_ordner: e.target.value === 'alle' })}
                  options={[
                    { value: 'posteingang', label: t('push.ordner_posteingang') },
                    { value: 'alle', label: t('push.ordner_alle') },
                  ]}
                  hints={[einst.push_mail_alle_ordner ? t('push.ordner_alle_hinweis') : t('push.ordner_posteingang_hinweis')]}
                />
                <CheckboxRow
                  checked={einst.push_mail_nur_ungelesen}
                  label={t('push.nur_ungelesen')}
                  hint={t('push.nur_ungelesen_hinweis')}
                  onChange={(an) => stellen({ push_mail_nur_ungelesen: an })}
                />
                <CheckboxRow
                  checked={einst.push_mail_buendeln}
                  label={t('push.buendeln')}
                  hint={t('push.buendeln_hinweis')}
                  onChange={(an) => stellen({ push_mail_buendeln: an })}
                />
              </Box>
            )}
          </>
        )}
      </Card>

      <Card id="quiet-hours" icon="BellOff" title={t('push.ruhezeit')} subtitle={t('push.ruhezeit_hinweis')}>
        {einst && (
          <>
            <CheckboxRow checked={einst.push_ruhezeit} label={t('push.ruhezeit')} onChange={(an) => stellen({ push_ruhezeit: an })} />
            {einst.push_ruhezeit && (
              <div className="flex flex-wrap gap-4">
                <SelectField
                  label={t('push.ruhezeit_von')}
                  value={einst.push_ruhezeit_von}
                  onChange={(e) => stellen({ push_ruhezeit_von: e.target.value })}
                  options={UHRZEITEN.map((u) => ({ value: u, label: u }))}
                />
                <SelectField
                  label={t('push.ruhezeit_bis')}
                  value={einst.push_ruhezeit_bis}
                  onChange={(e) => stellen({ push_ruhezeit_bis: e.target.value })}
                  options={UHRZEITEN.map((u) => ({ value: u, label: u }))}
                />
              </div>
            )}
          </>
        )}
      </Card>
    </>
  )
}
