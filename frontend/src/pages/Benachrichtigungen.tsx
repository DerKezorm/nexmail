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
import { Trash2 } from 'lucide-react'
import { Button, IconButton, Select, Switch } from '../ds'
import { api, ApiFehler } from '../api/client'
import * as push from '../lib/push'

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
  const [lage, setLage] = useState<push.PushLage>(() => push.lage())
  const [einst, setEinst] = useState<Einstellungen | null>(null)
  const [geraete, setGeraete] = useState<GeraetZeile[] | null>(null)
  /* ⚠️ Drei Zustände, nicht zwei: noch nicht geladen · geladen · ging nicht.
     Ein Fehler, der wie eine leere Liste aussieht, ist der Schrecken aus
     „Ein Fehler darf nicht wie Leere aussehen". */
  const [fehler, setFehler] = useState<string | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [probeGesagt, setProbeGesagt] = useState(false)

  const laden = useCallback(async () => {
    try {
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
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
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
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
      void laden()
    }
  }

  async function erlauben() {
    setLaeuft(true)
    setFehler(null)
    try {
      await push.anmelden()
      setLage(push.lage())
      await laden()
    } catch (e) {
      /* ⚠️ Der Browser sagt „denied", sobald jemand die Nachfrage wegklickt —
         und danach fragt er nie wieder. Die Lage wird deshalb neu gelesen,
         damit der Kasten sofort den richtigen Satz zeigt statt weiter zum
         Klicken einzuladen. */
      setLage(push.lage())
      const kennung = e instanceof Error ? e.message : String(e)
      if (kennung !== 'push_abgelehnt') setFehler(kennung)
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
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    }
  }

  async function geraetWeg(zeile: GeraetZeile) {
    try {
      if (zeile.dieses) await push.abmelden(zeile.id)
      else await api.loeschen(`/api/push/geraete/${zeile.id}`)
      setLage(push.lage())
      await laden()
    } catch (e) {
      setFehler(e instanceof ApiFehler ? e.detail : String(e))
    }
  }

  const datum = (wert: string) =>
    new Date(wert).toLocaleDateString(i18n.language, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })

  return (
    <div className="flex flex-col gap-6">
      {fehler && (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger-text">
          {fehler}
        </p>
      )}

      {/* --- Dieses Gerät ------------------------------------------------ */}
      <section className="flex flex-col gap-4">
        <div>
          <h2 className="mb-1 text-[13px] font-semibold text-fg-1">
            {t('push.geraet_titel')}
          </h2>
          <p className="text-[12px] text-fg-3">{t('push.geraet_hinweis')}</p>
        </div>

        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-accent-line bg-accent-soft px-4 py-3.5">
          <div className="min-w-[230px] flex-1">
            <b className="block text-[13.5px] font-semibold text-fg-1">
              {t(`push.lage_${lage}`)}
            </b>
            <span className="text-[12px] text-fg-3">{t(`push.lage_${lage}_hinweis`)}</span>
          </div>
          {lage === 'bereit' ? (
            <Button variant="secondary" onClick={probe}>
              {probeGesagt ? t('push.probe_unterwegs') : t('push.probe')}
            </Button>
          ) : (
            <Button
              onClick={erlauben}
              disabled={laeuft || lage === 'unmoeglich' || lage === 'abgelehnt'}
            >
              {t('push.erlauben')}
            </Button>
          )}
        </div>

        {/* ⚠️ Steht immer da, nicht nur auf einem iPhone: Wer am Rechner für
            sein Telefon nachsieht, findet den Schritt sonst nie. */}
        <div>
          <b className="block text-[13px] font-medium text-fg-1">{t('push.ios_titel')}</b>
          <span className="text-[12px] text-fg-4">{t('push.ios_hinweis')}</span>
        </div>
      </section>

      {/* --- Wobei ------------------------------------------------------- */}
      <section className="flex flex-col gap-4 border-t border-line-subtle pt-5">
        <div>
          <h2 className="mb-1 text-[13px] font-semibold text-fg-1">{t('push.wobei_titel')}</h2>
          <p className="text-[12px] text-fg-3">{t('push.wobei_hinweis')}</p>
        </div>

        {einst && (
          <>
            <Switch
              checked={einst.push_termine}
              label={t('push.termine')}
              description={t('push.termine_hinweis')}
              onCheckedChange={(an) => stellen({ push_termine: an })}
            />

            <Switch
              checked={einst.push_mail}
              label={t('push.mail')}
              description={t('push.mail_hinweis')}
              onCheckedChange={(an) => stellen({ push_mail: an })}
            />

            {einst.push_mail && (
              <div className="ml-4 flex flex-col gap-4 border-l-2 border-line-subtle pl-4">
                <Select
                  label={t('push.ordner')}
                  value={einst.push_mail_alle_ordner ? 'alle' : 'posteingang'}
                  onChange={(e) =>
                    stellen({ push_mail_alle_ordner: e.target.value === 'alle' })
                  }
                  options={[
                    { value: 'posteingang', label: t('push.ordner_posteingang') },
                    { value: 'alle', label: t('push.ordner_alle') },
                  ]}
                  hint={
                    einst.push_mail_alle_ordner
                      ? t('push.ordner_alle_hinweis')
                      : t('push.ordner_posteingang_hinweis')
                  }
                />
                <Switch
                  checked={einst.push_mail_nur_ungelesen}
                  label={t('push.nur_ungelesen')}
                  description={t('push.nur_ungelesen_hinweis')}
                  onCheckedChange={(an) => stellen({ push_mail_nur_ungelesen: an })}
                />
                <Switch
                  checked={einst.push_mail_buendeln}
                  label={t('push.buendeln')}
                  description={t('push.buendeln_hinweis')}
                  onCheckedChange={(an) => stellen({ push_mail_buendeln: an })}
                />
              </div>
            )}

            <Switch
              checked={einst.push_ruhezeit}
              label={t('push.ruhezeit')}
              description={t('push.ruhezeit_hinweis')}
              onCheckedChange={(an) => stellen({ push_ruhezeit: an })}
            />

            {einst.push_ruhezeit && (
              <div className="ml-4 flex flex-wrap gap-4 border-l-2 border-line-subtle pl-4">
                <Select
                  label={t('push.ruhezeit_von')}
                  value={einst.push_ruhezeit_von}
                  onChange={(e) => stellen({ push_ruhezeit_von: e.target.value })}
                  options={UHRZEITEN}
                />
                <Select
                  label={t('push.ruhezeit_bis')}
                  value={einst.push_ruhezeit_bis}
                  onChange={(e) => stellen({ push_ruhezeit_bis: e.target.value })}
                  options={UHRZEITEN}
                />
              </div>
            )}
          </>
        )}
      </section>

      {/* --- Geräte ------------------------------------------------------ */}
      <section className="flex flex-col gap-4 border-t border-line-subtle pt-5">
        <div>
          <h2 className="mb-1 text-[13px] font-semibold text-fg-1">
            {t('push.geraete_titel')}
          </h2>
          <p className="text-[12px] text-fg-3">{t('push.geraete_hinweis')}</p>
        </div>

        {geraete === null ? null : geraete.length === 0 ? (
          <p className="text-[13px] text-fg-4">{t('push.keine_geraete')}</p>
        ) : (
          <ul className="flex flex-col">
            {geraete.map((g) => (
              <li
                key={g.id}
                className="flex items-center gap-3 border-b border-line-subtle py-2.5 last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <span
                    className={`block truncate text-[13px] ${g.dieses ? 'text-accent' : 'text-fg-2'}`}
                  >
                    {g.geraet || t('push.unbekanntes_geraet')}
                    {g.dieses && ` ${t('push.dieses')}`}
                  </span>
                  <span className="text-[12px] text-fg-4">
                    {t('push.angemeldet_am', { datum: datum(g.angelegt) })}
                    {g.zuletzt_erreicht
                      ? ` · ${t('push.zuletzt_erreicht', { datum: datum(g.zuletzt_erreicht) })}`
                      : ` · ${t('push.nie_erreicht')}`}
                  </span>
                </div>
                <IconButton
                  icon={<Trash2 />}
                  size="sm"
                  label={t('push.geraet_entfernen')}
                  onClick={() => geraetWeg(g)}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
