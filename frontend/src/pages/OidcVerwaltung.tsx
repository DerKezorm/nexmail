/* Anmelde-Anbieter — der Reiter „OIDC" in der Verwaltung.
 *
 * ⚠️ **Ab Werk ist die Liste leer, und dann ändert sich nichts.** Keine Knöpfe
 * auf der Anmeldeseite, keine offenen Adressen. Eine Installation, deren
 * Betreiber nie einen Anbieter einrichtet, weiß von OIDC nichts.
 *
 * ⚠️ **Die Rückkehr-Adresse steht zum Abschreiben da.** Sie muss beim Anbieter
 * hinterlegt werden, und wer sie abtippt, vertippt sich — dann meldet der
 * Anbieter nur ein nichtssagendes `invalid_grant`.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Copy, KeyRound, Pencil, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { useNachfrage } from '../components/Nachfrage'
import { Badge, Button, Dialog, IconButton, Input, Switch } from '../ds'
import { servermeldung } from '../lib/servermeldung'

interface AnbieterZeile {
  id: string
  kuerzel: string
  anzeigename: string
  issuer: string
  client_id: string
  scopes: string
  aktiv: boolean
  geheimnis_liegt_vor: boolean
  rueckkehr_adresse: string
}

const LEER = {
  kuerzel: '',
  anzeigename: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid email profile',
  aktiv: true,
}

export function OidcVerwaltung() {
  const { t } = useTranslation()
  const { fragen, fenster: nachfrage } = useNachfrage()
  const [zeilen, setZeilen] = useState<AnbieterZeile[] | null>(null)
  const [fehler, setFehler] = useState('')
  const [offen, setOffen] = useState<AnbieterZeile | 'neu' | null>(null)

  const laden = useCallback(async () => {
    try {
      setZeilen(await api.holen<AnbieterZeile[]>('/api/oidc/anbieter'))
      setFehler('')
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  async function entfernen(a: AnbieterZeile) {
    const ja = await fragen({
      titel: t('oidc.entfernen'),
      text: t('oidc.entfernen_text', { name: a.anzeigename }),
      knopf: t('oidc.entfernen'),
      gefaehrlich: true,
    })
    if (ja !== true) return
    await api.loeschen(`/api/oidc/anbieter/${a.id}`)
    await laden()
  }

  if (zeilen === null && !fehler) return <div className="h-24" />

  return (
    <div className="flex max-w-[720px] flex-col gap-5">
      <p className="mb-0 text-[13px] text-fg-3">{t('oidc.was_ist_das')}</p>

      {fehler && (
        <p role="alert" className="mb-0 text-[13px] text-danger">
          {fehler}
        </p>
      )}

      <ul className="flex list-none flex-col gap-2 p-0">
        {(zeilen ?? []).map((a) => (
          <li
            key={a.id}
            className="flex items-start gap-3 rounded-lg border border-line bg-surface-1 px-4 py-3"
          >
            <KeyRound aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-4" />
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <p className="mb-0 truncate text-sm font-medium text-fg-1">{a.anzeigename}</p>
                {!a.aktiv && <Badge tone="warning">{t('oidc.aus')}</Badge>}
              </div>
              <p className="mb-0 truncate font-mono text-[12px] text-fg-4">{a.issuer}</p>
              <Rueckkehr adresse={a.rueckkehr_adresse} />
            </div>
            {/* ⚠️ **Ein sichtbarer Stift, kein anklickbarer Name.** Vorher
                öffnete ein Klick auf den Namen das Formular — und nichts zeigte
                das. Der Betreiber am 01.09.2026: „es fehlt leider ein button zum
                editieren. Ich lösche und lege neu an." Eine Handlung, die man
                nicht sieht, gibt es nicht; und die Postfachliste daneben hat
                ihren Stift seit jeher. */}
            <IconButton
              icon={<Pencil />}
              label={t('oidc.bearbeiten')}
              onClick={() => setOffen(a)}
            />
            <IconButton
              icon={<Trash2 />}
              label={t('oidc.entfernen')}
              onClick={() => void entfernen(a)}
            />
          </li>
        ))}
      </ul>

      <div>
        <Button variant="primary" onClick={() => setOffen('neu')}>
          {t('oidc.hinzufuegen')}
        </Button>
      </div>

      {offen && (
        <Formular
          bestehend={offen === 'neu' ? null : offen}
          aufSchliessen={() => setOffen(null)}
          aufFertig={() => {
            setOffen(null)
            void laden()
          }}
        />
      )}

      {nachfrage}
    </div>
  )
}

/** Die Adresse, die beim Anbieter hinterlegt werden muss — mit Kopierknopf.
 *
 * ⚠️ **Wer sie abtippt, vertippt sich.** Und der Anbieter meldet dann nur ein
 * `invalid_grant`, das auf alles Mögliche zeigt.
 */
function Rueckkehr({ adresse }: { adresse: string }) {
  const { t } = useTranslation()
  const [kopiert, setKopiert] = useState(false)

  if (!adresse) {
    return (
      <p className="mb-0 flex items-center gap-1.5 text-[11px] text-warning">
        <AlertTriangle className="size-3 shrink-0" />
        {t('oidc.keine_adresse')}
      </p>
    )
  }

  return (
    <div className="mt-1 flex items-center gap-1.5">
      <span className="text-[11px] text-fg-4">{t('oidc.rueckkehr')}</span>
      <code className="truncate rounded-sm bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-2 select-all">
        {adresse}
      </code>
      <button
        type="button"
        aria-label={t('oidc.kopieren')}
        onClick={() => {
          void navigator.clipboard.writeText(adresse)
          setKopiert(true)
          window.setTimeout(() => setKopiert(false), 2000)
        }}
        className="shrink-0 rounded-sm p-0.5 text-fg-4 hover:bg-surface-3 hover:text-fg-1"
      >
        {kopiert ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  )
}

function Formular({
  bestehend,
  aufSchliessen,
  aufFertig,
}: {
  bestehend: AnbieterZeile | null
  aufSchliessen: () => void
  aufFertig: () => void
}) {
  const { t } = useTranslation()
  const [f, setF] = useState(
    bestehend
      ? {
          kuerzel: bestehend.kuerzel,
          anzeigename: bestehend.anzeigename,
          issuer: bestehend.issuer,
          client_id: bestehend.client_id,
          client_secret: '',
          scopes: bestehend.scopes,
          aktiv: bestehend.aktiv,
        }
      : LEER,
  )
  const [fehler, setFehler] = useState('')
  const [laeuft, setLaeuft] = useState(false)

  async function speichern() {
    setFehler('')
    setLaeuft(true)
    try {
      // ⚠️ Leeres Geheimnis heißt „unverändert", nicht „keins" — dieselbe
      // Regel wie beim Postfach-Passwort.
      const nutzdaten = { ...f, client_secret: f.client_secret || null }
      if (bestehend) await api.aendern(`/api/oidc/anbieter/${bestehend.id}`, nutzdaten)
      else await api.senden('/api/oidc/anbieter', nutzdaten)
      aufFertig()
    } catch (fehl) {
      setFehler(servermeldung(fehl, t('anmeldung.fehler_allgemein')))
    } finally {
      setLaeuft(false)
    }
  }

  return (
    <Dialog open title={bestehend ? f.anzeigename : t('oidc.hinzufuegen')} onClose={aufSchliessen}>
      <div className="flex flex-col gap-4">
        <Input
          label={t('oidc.anzeigename')}
          hint={t('oidc.anzeigename_hinweis')}
          placeholder="Keycloak"
          value={f.anzeigename}
          onChange={(e) => setF({ ...f, anzeigename: e.target.value })}
        />
        <Input
          label={t('oidc.kuerzel')}
          hint={t('oidc.kuerzel_hinweis')}
          placeholder="keycloak"
          value={f.kuerzel}
          onChange={(e) => setF({ ...f, kuerzel: e.target.value.toLowerCase() })}
        />
        <Input
          label={t('oidc.issuer')}
          hint={t('oidc.issuer_hinweis')}
          placeholder="https://auth.example.org/realms/haushalt"
          value={f.issuer}
          onChange={(e) => setF({ ...f, issuer: e.target.value })}
        />
        <div className="grid grid-cols-2 gap-3">
          <Input
            label={t('oidc.client_id')}
            value={f.client_id}
            onChange={(e) => setF({ ...f, client_id: e.target.value })}
          />
          <Input
            label={t('oidc.client_secret')}
            type="password"
            autoComplete="new-password"
            hint={bestehend?.geheimnis_liegt_vor ? t('oidc.geheimnis_liegt_vor') : undefined}
            value={f.client_secret}
            onChange={(e) => setF({ ...f, client_secret: e.target.value })}
          />
        </div>
        <Input
          label={t('oidc.scopes')}
          hint={t('oidc.scopes_hinweis')}
          value={f.scopes}
          onChange={(e) => setF({ ...f, scopes: e.target.value })}
        />

        <Switch
          checked={f.aktiv}
          label={t('oidc.aktiv')}
          description={t('oidc.aktiv_hinweis')}
          onCheckedChange={(an) => setF({ ...f, aktiv: an })}
        />


        {fehler && (
          <p role="alert" className="mb-0 text-[13px] text-danger">
            {fehler}
          </p>
        )}

        <div className="flex gap-2">
          <Button
            variant="primary"
            loading={laeuft}
            disabled={!f.kuerzel || !f.anzeigename || !f.issuer || !f.client_id}
            onClick={() => void speichern()}
          >
            {t('verwaltung.speichern')}
          </Button>
          <Button variant="ghost" onClick={aufSchliessen}>
            {t('aktion.abbrechen')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
