/* Server › Anmeldung, ganz aus den Modulen (Bauplan „Einstellungen", Anmeldung): `SignInPage` des Kontenmoduls 1.1.0
 * (Nothammer-Hinweis, „Bereit fürs Internet?", Karte „Anmeldung" in der Reihenfolge des Bauplans: Anmeldung mit
 * Passwort, Öffentliche Adresse mit Knopf auf Höhe des Felds, Zweiten Faktor für alle verlangen, Passkeys erlaubt),
 * danach die Karten „Anmeldeanbieter" und „authentik in einem Schritt" aus oidc 1.2.0.
 *
 * Die Wege: `/api/server/sign-in` (Schalter mit den Regeln des Moduls), `/api/server/sign-in/readiness`,
 * `/api/einstellungen` (öffentliche Adresse, mit der Rückfrage `public_url_change`), die Anbieter unter `/api/oidc`.
 * Der Klappzustand der Punkte von „Bereit fürs Internet?" gilt je Gerät (`nexmail.bereit.<punkt>`).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiFehler, api, type Ich } from '../../api/client'
import { useGemerkt } from '../../lib/haken'
import { servermeldung } from '../../lib/servermeldung'
import { SignInPage, type AddressQuestion, type SignInChange, type SignInView } from '../../vendor/nexkonten/SignInPage'
import type { Readiness } from '../../vendor/nexkonten/konten'
import { SignInProviders, type OidcAdminCalls, type OidcProviderRow } from '../../vendor/nexoidc/SignInProviders'

type Ansicht = SignInView & { public_url: string }

function frageAus(fehler: unknown): AddressQuestion | null {
  if (!(fehler instanceof ApiFehler) || fehler.status !== 409 || fehler.detail !== 'public_url_change') return null
  const w = fehler.werte as Partial<AddressQuestion>
  return { count: Number(w.count ?? 0), address: String(w.address ?? ''), hand: Number(w.hand ?? 0) }
}

const AUFRUFE: OidcAdminCalls = {
  providers: () => api.holen<OidcProviderRow[]>('/api/oidc/admin/providers'),
  add: (form) => api.senden('/api/oidc/admin/providers', form),
  save: (id, form) => api.aendern(`/api/oidc/admin/providers/${id}`, form),
  remove: (id) => api.loeschen(`/api/oidc/admin/providers/${id}`),
  impact: (id, issuer) =>
    api.holen(`/api/oidc/admin/providers/${id}/impact${issuer ? `?issuer=${encodeURIComponent(issuer)}` : ''}`),
  order: (ids) => api.aendern('/api/oidc/admin/providers/order', { ids }),
  authentik: (url, token, confirmIssuerChange, publicUrl) =>
    api.senden('/api/oidc/authentik/setup', { url, token, confirm_issuer_change: confirmIssuerChange, public_url: publicUrl }),
  authentikAddress: () => api.holen('/api/oidc/authentik/address'),
  authentikSaveAddress: (publicUrl, confirm) =>
    api.senden('/api/oidc/authentik/address', confirm ? { public_url: publicUrl, confirm: true } : { public_url: publicUrl }),
}

export function Anmeldung({ ich }: { ich: Ich | null }) {
  const { t } = useTranslation()
  const [ansicht, setAnsicht] = useState<Ansicht | null>(null)
  const [bereit, setBereit] = useState<Readiness | null>(null)
  const [offen, setOffen] = useGemerkt<Record<string, boolean>>('nexmail.bereit', {})

  const laden = useCallback(async () => {
    const [jetzt, punkte] = await Promise.all([
      api.holen<Ansicht>('/api/server/sign-in'),
      api.holen<Readiness>('/api/server/sign-in/readiness').catch(() => null),
    ])
    setAnsicht(jetzt)
    setBereit(punkte)
  }, [])
  useEffect(() => {
    void laden().catch(() => undefined)
  }, [laden])

  const fehlerText = useCallback((fehler: unknown) => servermeldung(fehler, t('anmeldung.fehler_allgemein')), [t])

  async function aendern(aenderung: SignInChange, passwort?: string) {
    const neu = await api.aendern<Ansicht>('/api/server/sign-in', { ...aenderung, password: passwort ?? '' })
    setAnsicht(neu)
    setBereit(await api.holen<Readiness>('/api/server/sign-in/readiness').catch(() => null))
  }

  async function adresseSpeichern(adresse: string, bestaetigt: boolean): Promise<AddressQuestion | null> {
    const jetzt = await api.holen<{ oeffentliche_adresse: string; zeitzone: string }>('/api/einstellungen')
    try {
      await api.aendern('/api/einstellungen', {
        oeffentliche_adresse: adresse.trim(),
        zeitzone: jetzt.zeitzone,
        adresse_bestaetigt: bestaetigt,
      })
    } catch (fehler) {
      const frage = frageAus(fehler)
      if (frage) return frage
      throw fehler
    }
    await laden()
    return null
  }

  const fehlerVon = useMemo(
    () => (fehler: unknown) =>
      fehler instanceof ApiFehler ? { code: fehler.detail, values: fehler.werte as Record<string, unknown> } : null,
    [],
  )

  return (
    <SignInPage
      t={t}
      app="nexmail"
      view={ansicht}
      readiness={bereit}
      publicUrl={ansicht?.public_url ?? ''}
      operatorHasPassword={ich?.hat_kennwort !== false}
      onChange={aendern}
      onSaveAddress={adresseSpeichern}
      errorText={fehlerText}
      saved={t('profil.gespeichert')}
      open={offen}
      onOpenChange={(punkt, auf) => setOffen({ ...offen, [punkt]: auf })}
      providers={
        <SignInProviders
          t={t}
          app="nexmail"
          apiPrefix="/api"
          calls={AUFRUFE}
          errorOf={fehlerVon}
          publicUrl={ansicht?.public_url ?? ''}
          onAddress={() => laden()}
        />
      }
    />
  )
}
