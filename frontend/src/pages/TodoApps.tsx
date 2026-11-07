/* Todo-Apps — die eigenen Verbindungen, nicht die des Betreibers.
 *
 * ⚠️ **Mehrere Verbindungen, wie bei den Kalendern.** Zwei Todoist-Konten
 * oder später eine zweite App sind gewollt; deshalb eine Liste mit
 * „Verbinden" darunter, nicht ein einzelner Zugang wie beim KI-Dienst.
 *
 * ⚠️ **Der Token geht nie zurück an die Oberfläche.** Die Zeile zeigt nur, ob
 * die App ihn zuletzt angenommen hat; wer einen neuen will, trennt und
 * verbindet neu. Dasselbe gilt für das Geheimnis eines Webhooks: Es steht
 * genau einmal da, gleich nach dem Verbinden.
 *
 * ⚠️ **Ein Webhook hat Einstellungen, eine Todoist-Verbindung nicht.** Adresse,
 * „Nur senden" und der Text der Mail lassen sich ändern, ohne neu zu
 * verbinden; sonst bekäme der Empfänger jedes Mal ein neues Geheimnis.
 *
 * ⚠️ **nextasks bekommt „Token erneuern".** Ein nextasks-Token läuft ab Werk
 * nach 90 Tagen ab; Trennen und neu Verbinden nähme jeder Aufgabe den
 * Abgleich. Der Server prüft das neue Token, bevor es das alte ersetzt.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ExternalLink, KeyRound, ListChecks, Send, Settings2, Unplug, Webhook } from 'lucide-react'
import nextasksLogo from '../assets/nextasks.svg'
import { api } from '../api/client'
import { Button, Checkbox, Dialog, Input, Select } from '../ds'
import { useNachfrage } from '../components/Nachfrage'
import { Klartext } from './ApiSchluessel'
import { servermeldung } from '../lib/servermeldung'
import {
  gruppenname,
  NEXTASKS_ZU_BEHEBEN,
  type Verbindung,
  type ZielGruppe,
  type ZielStand,
} from '../lib/aufgabenziele'

/** Wo man den Token findet — nur der Verweis, kein nacherzählter Weg. */
const TODOIST_TOKEN = 'https://app.todoist.com/app/settings/integrations/developer'

export function TodoApps() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [stand, setStand] = useState<ZielStand | null>(null)
  const [gruppen, setGruppen] = useState<ZielGruppe[] | null>(null)
  const [zugang, setZugang] = useState('')
  const [name, setName] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  /** Das Geheimnis eines eben verbundenen Webhooks, genau einmal. */
  const [geheimnis, setGeheimnis] = useState<string | null>(null)
  /** Welcher Webhook seine Einstellungen aufgeklappt hat. */
  const [offen, setOffen] = useState<string | null>(null)

  const laden = useCallback(async () => {
    try {
      const s = await api.holen<ZielStand>('/api/aufgabenziele')
      setStand(s)
      setFehler('')
      // Die Listen nur, wenn es etwas zu wählen gibt: Sie kosten je
      // Verbindung eine Anfrage bei der App.
      setGruppen(
        s.verbindungen.length
          ? await api.holen<ZielGruppe[]>('/api/aufgabenziele/listen')
          : [],
      )
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function verbinden() {
    setLaeuft(true)
    setFehler('')
    try {
      await api.senden('/api/aufgabenziele', { art: 'todoist', zugang, name })
      setZugang('')
      setName('')
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function trennen(v: Verbindung) {
    const ja = await fragen({
      titel: t('todoapps.trennen'),
      text: t('todoapps.trennen_frage', { name: gruppenname(v) }),
      knopf: t('todoapps.trennen'),
      gefaehrlich: true,
    })
    if (!ja) return
    try {
      await api.loeschen(`/api/aufgabenziele/${v.id}`)
      await laden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  async function standardSetzen(ziel: string) {
    try {
      setStand(await api.aendern<ZielStand>('/api/aufgabenziele/standard', { ziel }))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }

  if (stand === null && !fehler) return <div className="h-24" />

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <p className="mb-0 text-[13px] text-fg-2">{t('todoapps.einleitung')}</p>

      {fehler && (
        <p role="alert" className="mb-0 rounded-md border border-danger bg-surface-1 px-3 py-2 text-[13px] text-fg-1">
          {fehler}
        </p>
      )}

      {stand && stand.verbindungen.length > 0 && (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
          <h2 className="mb-0 text-[13px] font-semibold text-fg-1">{t('todoapps.verbunden')}</h2>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {stand.verbindungen.map((v) => (
              <li key={v.id} className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold text-fg-1">
                    {v.art === 'nextasks' && <NextasksLogo />}
                    {gruppenname(v)}
                  </span>
                  {/* ⚠️ Ein abgelehnter Token muss hier stehen. Sonst sieht
                      eine App, die nichts mehr meldet, aus wie eine, in der
                      nichts passiert. */}
                  {v.fehler ? (
                    <span className="flex items-center gap-1 text-[12px] text-warning">
                      <AlertTriangle className="size-3.5" aria-hidden />
                      {/* Nur der abgelehnte Token hat einen eigenen Satz:
                          Er ist der eine Fall, in dem der Mensch etwas tun
                          muss. Alles andere versucht der Takt weiter. */}
                      {v.fehler === 'todoist_zugang_ungueltig'
                        ? t('todoapps.token_abgelehnt')
                        : v.fehler === 'nextasks_zugang_ungueltig'
                          ? t('todoapps.nextasks_token_abgelehnt')
                          : NEXTASKS_ZU_BEHEBEN.includes(v.fehler)
                            ? t(`serverfehler.${v.fehler}`)
                            : v.art === 'webhook'
                              ? t('todoapps.webhook_klemmt')
                              : t('todoapps.klemmt')}
                    </span>
                  ) : (
                    <span className="text-[12px] text-fg-3">{t('todoapps.in_ordnung')}</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-1">
                  {v.art === 'nextasks' && (
                    <Button
                      variant="ghost"
                      iconLeft={<KeyRound className="size-4" />}
                      aria-expanded={offen === v.id}
                      onClick={() => setOffen(offen === v.id ? null : v.id)}
                    >
                      {t('todoapps.nextasks_token_neu')}
                    </Button>
                  )}
                  {v.art === 'webhook' && (
                    <Button
                      variant="ghost"
                      iconLeft={<Settings2 className="size-4" />}
                      aria-expanded={offen === v.id}
                      onClick={() => setOffen(offen === v.id ? null : v.id)}
                    >
                      {t('todoapps.einstellungen')}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    iconLeft={<Unplug className="size-4" />}
                    onClick={() => void trennen(v)}
                  >
                    {t('todoapps.trennen')}
                  </Button>
                </div>
                {v.art === 'webhook' && offen === v.id && (
                  <WebhookEinstellungen verbindung={v} aufGeaendert={() => void laden()} />
                )}
                {v.art === 'nextasks' && offen === v.id && (
                  <NextasksErneuern
                    verbindung={v}
                    aufGespeichert={() => {
                      setOffen(null)
                      void laden()
                    }}
                  />
                )}
              </li>
            ))}
          </ul>

          <Select
            label={t('todoapps.standard')}
            hint={t('todoapps.standard_hinweis')}
            value={stand.standard}
            onChange={(e) => void standardSetzen(e.target.value)}
          >
            <option value="" className="bg-surface-1 text-fg-1">
              {t('todoapps.eigene_liste')}
            </option>
            {/* Die App in jeder Zeile, aus demselben Grund wie im Fenster
                „Zu Aufgabe machen": Geschlossen zeigt die Auswahl keine Gruppe. */}
            {(gruppen ?? []).flatMap((g) =>
              g.listen.map((l) => (
                <option key={l.ziel} value={l.ziel} className="bg-surface-1 text-fg-1">
                  {`${gruppenname(g)} › ${l.name}`}
                </option>
              )),
            )}
            {/* Eine Wahl, deren Liste gerade nicht kam, bleibt sichtbar
                gewählt, statt still auf die eigene Liste zu springen. */}
            {stand.standard &&
              !(gruppen ?? []).some((g) => g.listen.some((l) => l.ziel === stand.standard)) && (
                <option value={stand.standard}>{t('todoapps.liste_unerreichbar')}</option>
              )}
          </Select>
        </section>
      )}

      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
        <h2 className="mb-0 flex items-center gap-2 text-[13px] font-semibold text-fg-1">
          <ListChecks className="size-4 text-fg-3" aria-hidden />
          {t('todoapps.todoist_verbinden')}
        </h2>
        <p className="mb-0 text-[12px] text-fg-3">
          {t('todoapps.todoist_hinweis')}{' '}
          <a
            href={TODOIST_TOKEN}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-accent-text hover:underline"
          >
            {t('todoapps.todoist_wo')}
            <ExternalLink className="size-3" aria-hidden />
          </a>
        </p>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (zugang.trim()) void verbinden()
          }}
        >
          <Input
            label={t('todoapps.token')}
            type="password"
            autoComplete="off"
            mono
            value={zugang}
            onChange={(e) => setZugang(e.target.value)}
          />
          <Input
            label={t('todoapps.name')}
            hint={t('todoapps.name_hinweis')}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
          />
          <div>
            <Button type="submit" variant="primary" disabled={!zugang.trim() || laeuft}>
              {laeuft ? t('todoapps.prueft') : t('todoapps.verbinden')}
            </Button>
          </div>
        </form>
      </section>

      <NextasksVerbinden aufVerbunden={() => void laden()} />

      <WebhookVerbinden
        aufVerbunden={(g) => {
          setGeheimnis(g)
          void laden()
        }}
      />

      <Dialog
        open={geheimnis !== null}
        width={520}
        title={t('todoapps.webhook_verbunden_titel')}
        abweisbar={false}
        onClose={() => setGeheimnis(null)}
        footer={
          <Button variant="primary" onClick={() => setGeheimnis(null)}>
            {t('aktion.schliessen')}
          </Button>
        }
      >
        {geheimnis && (
          <Klartext
            schluessel={geheimnis}
            hinweis={t('todoapps.webhook_geheimnis_einmal')}
            mitAdresse={false}
          />
        )}
      </Dialog>

      {nachfrage}
    </div>
  )
}

interface WebhookStand {
  url: string
  nur_senden: boolean
  mit_text: boolean
  mailtext_erlaubt: boolean
}

/** Ein neuer Webhook. nexmail schickt vor dem Speichern ein `ping`; antwortet
 * die Adresse nicht mit 2xx, steht der Grund hier und nichts ist gespeichert. */
function WebhookVerbinden({ aufVerbunden }: { aufVerbunden: (geheimnis: string) => void }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [eigenes, setEigenes] = useState('')
  const [nurSenden, setNurSenden] = useState(false)
  const [mitText, setMitText] = useState(false)
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  async function verbinden() {
    setLaeuft(true)
    setFehler('')
    try {
      const r = await api.senden<{ geheimnis: string }>('/api/aufgabenziele/webhook', {
        url,
        name,
        geheimnis: eigenes,
        nur_senden: nurSenden,
        mit_text: mitText,
      })
      setUrl('')
      setName('')
      setEigenes('')
      setNurSenden(false)
      setMitText(false)
      aufVerbunden(r.geheimnis)
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
      <h2 className="mb-0 flex items-center gap-2 text-[13px] font-semibold text-fg-1">
        <Webhook className="size-4 text-fg-3" aria-hidden />
        {t('todoapps.webhook_verbinden')}
      </h2>
      <p className="mb-0 text-[12px] text-fg-3">{t('todoapps.webhook_hinweis')}</p>
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (url.trim() && !laeuft) void verbinden()
        }}
      >
        <Input
          label={t('todoapps.webhook_adresse')}
          hint={t('todoapps.webhook_adresse_hinweis')}
          placeholder="https://"
          type="url"
          mono
          value={url}
          maxLength={500}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Input
          label={t('todoapps.name')}
          hint={t('todoapps.webhook_name_hinweis')}
          value={name}
          maxLength={80}
          onChange={(e) => setName(e.target.value)}
        />
        <Input
          label={t('todoapps.webhook_geheimnis')}
          hint={t('todoapps.webhook_geheimnis_hinweis')}
          type="password"
          autoComplete="off"
          mono
          value={eigenes}
          maxLength={200}
          onChange={(e) => setEigenes(e.target.value)}
        />
        <Checkbox
          label={t('todoapps.webhook_nur_senden')}
          description={t('todoapps.webhook_nur_senden_hinweis')}
          checked={nurSenden}
          onCheckedChange={setNurSenden}
        />
        <Checkbox
          label={t('todoapps.webhook_mit_text')}
          description={t('todoapps.webhook_mit_text_hinweis')}
          checked={mitText}
          onCheckedChange={setMitText}
        />
        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}
        <div>
          <Button type="submit" variant="primary" disabled={!url.trim() || laeuft}>
            {laeuft ? t('todoapps.prueft') : t('todoapps.verbinden')}
          </Button>
        </div>
      </form>
    </section>
  )
}

/** Adresse, „Nur senden" und Text der Mail eines verbundenen Webhooks, dazu
 * „Test senden". ⚠️ Eine neue Adresse bekommt erst ihr `ping`; scheitert es,
 * bleibt die alte, und der Grund steht hier. */
function WebhookEinstellungen({
  verbindung,
  aufGeaendert,
}: {
  verbindung: Verbindung
  aufGeaendert: () => void
}) {
  const { t } = useTranslation()
  const [stand, setStand] = useState<WebhookStand | null>(null)
  const [url, setUrl] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [meldung, setMeldung] = useState('')
  const [fehler, setFehler] = useState('')
  const pfad = `/api/aufgabenziele/${verbindung.id}`

  useEffect(() => {
    api
      .holen<WebhookStand>(`${pfad}/webhook`)
      .then((s) => {
        setStand(s)
        setUrl(s.url)
      })
      .catch((f) => setFehler(servermeldung(f, t('anmeldung.fehler_allgemein'))))
  }, [pfad, t])

  async function speichern(neu: WebhookStand) {
    setLaeuft(true)
    setFehler('')
    setMeldung('')
    try {
      const s = await api.aendern<WebhookStand>(`${pfad}/webhook`, {
        url: neu.url,
        nur_senden: neu.nur_senden,
        mit_text: neu.mit_text,
      })
      setStand(s)
      setUrl(s.url)
      setMeldung(t('todoapps.gespeichert'))
      aufGeaendert()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  async function testen() {
    setLaeuft(true)
    setFehler('')
    setMeldung('')
    try {
      await api.senden(`${pfad}/test`, {})
      setMeldung(t('todoapps.test_angekommen'))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
      // Der Fehler steht danach auch an der Verbindung, oder er ist weg.
      aufGeaendert()
    }
  }

  return (
    <div className="flex w-full flex-col gap-3 rounded-md border border-line bg-surface-1 p-3">
      {stand && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (url.trim() && !laeuft) void speichern({ ...stand, url })
          }}
        >
          <Input
            label={t('todoapps.webhook_adresse')}
            hint={t('todoapps.webhook_adresse_hinweis')}
            type="url"
            mono
            value={url}
            maxLength={500}
            onChange={(e) => setUrl(e.target.value)}
          />
          {/* Die Schalter speichern sofort, mit der gespeicherten Adresse:
              Eine halb getippte neue soll dabei nicht mitgehen. */}
          <Checkbox
            label={t('todoapps.webhook_nur_senden')}
            description={t('todoapps.webhook_nur_senden_hinweis')}
            checked={stand.nur_senden}
            disabled={laeuft}
            onCheckedChange={(an) => void speichern({ ...stand, nur_senden: an })}
          />
          <Checkbox
            label={t('todoapps.webhook_mit_text')}
            description={
              stand.mailtext_erlaubt
                ? t('todoapps.webhook_mit_text_hinweis')
                : t('todoapps.webhook_mit_text_gesperrt')
            }
            checked={stand.mit_text}
            disabled={laeuft}
            onCheckedChange={(an) => void speichern({ ...stand, mit_text: an })}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={laeuft || !url.trim() || url === stand.url}>
              {t('todoapps.adresse_speichern')}
            </Button>
            <Button
              variant="ghost"
              iconLeft={<Send className="size-4" />}
              disabled={laeuft}
              onClick={() => void testen()}
            >
              {t('todoapps.test_senden')}
            </Button>
          </div>
        </form>
      )}
      {meldung && !fehler && (
        <p role="status" className="mb-0 text-[13px] text-accent-text">
          {meldung}
        </p>
      )}
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
    </div>
  )
}

/** Das Zeichen von nextasks: weißer Grund, Haken. Schmückt nur, liest sich nicht vor. */
function NextasksLogo() {
  return <img src={nextasksLogo} alt="" aria-hidden className="size-4 shrink-0 rounded-[4px]" />
}

/** nextasks verbinden: Adresse und Token. nexmail fragt vor dem Speichern
 * `/api/v1/me`; ein Token, das nur lesen darf, oder ein zu altes nextasks
 * steht hier mit Grund da, und nichts ist gespeichert. */
function NextasksVerbinden({ aufVerbunden }: { aufVerbunden: () => void }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [name, setName] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')

  async function verbinden() {
    setLaeuft(true)
    setFehler('')
    try {
      await api.senden('/api/aufgabenziele/nextasks', { url, token, name })
      setUrl('')
      setToken('')
      setName('')
      aufVerbunden()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface-2 p-4">
      <h2 className="mb-0 flex items-center gap-2 text-[13px] font-semibold text-fg-1">
        <NextasksLogo />
        {t('todoapps.nextasks_verbinden')}
      </h2>
      <p className="mb-0 text-[12px] text-fg-3">{t('todoapps.nextasks_hinweis')}</p>
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (url.trim() && token.trim() && !laeuft) void verbinden()
        }}
      >
        <Input
          label={t('todoapps.nextasks_adresse')}
          hint={t('todoapps.nextasks_adresse_hinweis')}
          placeholder="https://"
          type="url"
          mono
          value={url}
          maxLength={500}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Input
          label={t('todoapps.token')}
          type="password"
          autoComplete="off"
          mono
          value={token}
          maxLength={500}
          onChange={(e) => setToken(e.target.value)}
        />
        <Input
          label={t('todoapps.name')}
          hint={t('todoapps.nextasks_name_hinweis')}
          value={name}
          maxLength={80}
          onChange={(e) => setName(e.target.value)}
        />
        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}
        <div>
          <Button type="submit" variant="primary" disabled={!url.trim() || !token.trim() || laeuft}>
            {laeuft ? t('todoapps.prueft') : t('todoapps.verbinden')}
          </Button>
        </div>
      </form>
    </section>
  )
}

/** Neues Token für eine verbundene nextasks-Instanz, die Adresse vorbelegt.
 * ⚠️ Das alte Token kommt nie zurück an die Oberfläche; das Feld ist leer. */
function NextasksErneuern({
  verbindung,
  aufGespeichert,
}: {
  verbindung: Verbindung
  aufGespeichert: () => void
}) {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const pfad = `/api/aufgabenziele/${verbindung.id}/nextasks`

  useEffect(() => {
    api
      .holen<{ url: string }>(pfad)
      .then((s) => setUrl(s.url))
      .catch((f) => setFehler(servermeldung(f, t('anmeldung.fehler_allgemein'))))
  }, [pfad, t])

  async function speichern() {
    setLaeuft(true)
    setFehler('')
    try {
      await api.aendern(pfad, { url, token })
      setToken('')
      aufGespeichert()
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <form
      className="flex w-full flex-col gap-3 rounded-md border border-line bg-surface-1 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (url.trim() && token.trim() && !laeuft) void speichern()
      }}
    >
      <p className="mb-0 text-[12px] text-fg-3">{t('todoapps.nextasks_token_neu_hinweis')}</p>
      <Input
        label={t('todoapps.nextasks_adresse')}
        type="url"
        mono
        value={url}
        maxLength={500}
        onChange={(e) => setUrl(e.target.value)}
      />
      <Input
        label={t('todoapps.token')}
        type="password"
        autoComplete="off"
        mono
        value={token}
        maxLength={500}
        onChange={(e) => setToken(e.target.value)}
      />
      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}
      <div>
        <Button type="submit" disabled={!url.trim() || !token.trim() || laeuft}>
          {laeuft ? t('todoapps.prueft') : t('aktion.speichern')}
        </Button>
      </div>
    </form>
  )
}
