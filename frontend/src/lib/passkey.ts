/* Passkeys im Browser (Kontenmodul Teil 2): die Optionen des Servers (JSON, base64url) in das, was
 * `navigator.credentials` erwartet, und die Antwort zurück in JSON.
 *
 * ⚠️ **Von Hand statt `PublicKeyCredential.parseCreationOptionsFromJSON`:** Das gibt es erst in neueren Browsern
 * (Safari 18, Chrome 129, Firefox 119); ein älteres iPad bekäme sonst einen Knopf, der nichts tut. */

type Json = Record<string, unknown>

export function zuBytes(text: string): ArrayBuffer {
  const b64 = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4)
  const roh = atob(b64)
  const bytes = new Uint8Array(roh.length)
  for (let i = 0; i < roh.length; i++) bytes[i] = roh.charCodeAt(i)
  return bytes.buffer
}

export function zuText(daten: ArrayBuffer | null | undefined): string {
  if (!daten) return ''
  const bytes = new Uint8Array(daten)
  let roh = ''
  for (let i = 0; i < bytes.length; i++) roh += String.fromCharCode(bytes[i])
  return btoa(roh).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function ausweise(liste: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(liste)) return undefined
  return liste.map((eintrag) => {
    const e = eintrag as Json
    return { ...(e as object), id: zuBytes(String(e.id)), type: 'public-key' } as PublicKeyCredentialDescriptor
  })
}

export function anlegeOptionen(o: Json): PublicKeyCredentialCreationOptions {
  const user = o.user as Json
  return {
    ...(o as object),
    challenge: zuBytes(String(o.challenge)),
    user: { ...(user as object), id: zuBytes(String(user.id)) },
    excludeCredentials: ausweise(o.excludeCredentials),
  } as PublicKeyCredentialCreationOptions
}

export function anmeldeOptionen(o: Json): PublicKeyCredentialRequestOptions {
  return {
    ...(o as object),
    challenge: zuBytes(String(o.challenge)),
    allowCredentials: ausweise(o.allowCredentials),
  } as PublicKeyCredentialRequestOptions
}

/** Die Antwort des Browsers als JSON, wie der Server (py_webauthn) sie liest. */
export function alsJson(c: PublicKeyCredential): Json {
  const r = c.response as AuthenticatorAttestationResponse & AuthenticatorAssertionResponse
  const antwort: Json = { clientDataJSON: zuText(r.clientDataJSON) }
  if ('attestationObject' in r && r.attestationObject) {
    antwort.attestationObject = zuText(r.attestationObject)
    if (typeof r.getTransports === 'function') antwort.transports = r.getTransports()
  }
  if ('authenticatorData' in r && r.authenticatorData) {
    antwort.authenticatorData = zuText(r.authenticatorData)
    antwort.signature = zuText(r.signature)
    if (r.userHandle) antwort.userHandle = zuText(r.userHandle)
  }
  return {
    id: c.id,
    rawId: zuText(c.rawId),
    type: c.type,
    response: antwort,
    clientExtensionResults: c.getClientExtensionResults?.() ?? {},
  }
}

/** Ob dieser Browser Passkeys kann: im sicheren Kontext (https, oder localhost auch mit http). */
export function passkeyMoeglich(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext === true &&
    typeof window.PublicKeyCredential === 'function' &&
    !!navigator.credentials
  )
}

/** Ein Vorschlag für die Bezeichnung eines neuen Passkeys, aus dem System des Browsers („iPhone“, „Mac“ …). */
export function geraetename(agent: string = typeof navigator !== 'undefined' ? navigator.userAgent : ''): string {
  for (const [merkmal, name] of [
    ['iPhone', 'iPhone'],
    ['iPad', 'iPad'],
    ['Android', 'Android'],
    ['Mac OS X', 'Mac'],
    ['Windows', 'Windows'],
    ['Linux', 'Linux'],
  ] as const) {
    if (agent.includes(merkmal)) return name
  }
  return 'Passkey'
}
