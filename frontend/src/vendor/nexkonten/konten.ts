// nexkonten in the browser: the fields of every screen in their order, the rules, the username suggestion and the
// keys of the texts. No component and no look of its own: every app shows these with its own building blocks
// (field, button, card, dialog), so that the screens are the same in every app and look like the app.
//
// Copied unchanged into frontend/src/vendor/nexkonten/ by bauplaene/konten/tools/sync.py; changed only there.

/** The rules of a username, the same as the server's (names.py). */
export const USERNAME_MIN = 2
export const USERNAME_MAX = 64
export const USERNAME_PATTERN = /^[a-z0-9][a-z0-9._-]{1,63}$/
export const DISPLAY_NAME_MAX = 80
export const EMAIL_MAX = 254
export const PASSWORD_MIN = 12

/** The error codes of the server, in its order (errors.py). */
export const ACCOUNT_ERROR_CODES = [
  'setup_code_wrong',
  'already_set_up',
  'display_name_empty',
  'display_name_taken',
  'username_invalid',
  'username_taken',
  'email_invalid',
  'email_taken',
  'email_same',
  'password_too_short',
  'password_too_long',
  'wrong_password',
  'fresh_sign_in_needed',
  'wrong_credentials',
  'account_blocked',
  'not_allowed',
  'not_found',
  'use_account_page',
  'password_login_off',
  'invalid_days',
  'invite_invalid',
  'invite_expired',
  'reset_invalid',
  'reset_expired',
  'email_link_invalid',
  'email_link_expired',
  'no_pending_email',
  'code_wrong',
  'enrolment_expired',
  'sign_in_expired',
  'factor_missing',
  'factor_required',
  'passkeys_off',
  'passkey_invalid',
  'passkey_expired',
  'passkey_exists',
  'too_many_passkeys',
  'too_many_attempts',
  'avatar_too_large',
  'avatar_not_a_picture',
  'avatars_busy',
  'public_url_needed',
] as const

export type AccountErrorCode = (typeof ACCOUNT_ERROR_CODES)[number]

/** Codes whose sentence is one of the main texts rather than one under account.error. */
const MAIN_TEXT: Partial<Record<AccountErrorCode, string>> = {
  wrong_credentials: 'account.wrong',
  username_taken: 'account.usernameTaken',
  username_invalid: 'account.usernameRules',
  email_taken: 'account.emailTaken',
}

/** The text key for an error code from the server; never show the code itself. ``appCodes`` maps the app's own codes
 * of an older version to the module's (the server's AppConfig.error_codes the other way round), e.g.
 * { name_taken: 'username_taken' }. */
export function accountErrorKey(code: string | null | undefined, appCodes: Readonly<Record<string, string>> = {}): string {
  const given = code ?? ''
  const own = Object.hasOwn(appCodes, given) ? (appCodes[given] ?? '') : given
  const known = (ACCOUNT_ERROR_CODES as readonly string[]).includes(own)
  if (!known) return 'account.error.unknown'
  return MAIN_TEXT[own as AccountErrorCode] ?? `account.error.${own}`
}

/** Every field the module's screens know. */
export type AccountField =
  | 'setupCode'
  | 'displayName'
  | 'username'
  | 'email'
  | 'login'
  | 'password'
  | 'currentPassword'
  | 'newPassword'
  | 'passwordRepeat'
  | 'language'

export interface FieldSpec {
  /** The text key of the label. */
  label: string
  /** The text key of the hint under the field; '' for none. */
  hint: string
  type: 'text' | 'email' | 'password' | 'select'
  autoComplete: string
  required: boolean
  /** The longest value the field takes; 0 for no limit of the module's. */
  maxLength: number
}

export const FIELDS: Record<AccountField, FieldSpec> = {
  setupCode: { label: 'account.setupCode', hint: 'account.setupCodeHint', type: 'text', autoComplete: 'off', required: true, maxLength: 0 },
  displayName: { label: 'account.displayName', hint: 'account.displayNameHint', type: 'text', autoComplete: 'name', required: true, maxLength: DISPLAY_NAME_MAX },
  username: { label: 'account.username', hint: 'account.usernameHint', type: 'text', autoComplete: 'username', required: true, maxLength: USERNAME_MAX },
  email: { label: 'account.email', hint: 'account.emailHint', type: 'email', autoComplete: 'email', required: false, maxLength: EMAIL_MAX },
  login: { label: 'account.login', hint: '', type: 'text', autoComplete: 'username', required: true, maxLength: EMAIL_MAX },
  password: { label: 'account.password', hint: '', type: 'password', autoComplete: 'current-password', required: true, maxLength: 0 },
  currentPassword: { label: 'account.currentPassword', hint: '', type: 'password', autoComplete: 'current-password', required: true, maxLength: 0 },
  newPassword: { label: 'account.newPassword', hint: 'account.passwordRules', type: 'password', autoComplete: 'new-password', required: true, maxLength: 0 },
  passwordRepeat: { label: 'account.passwordRepeat', hint: '', type: 'password', autoComplete: 'new-password', required: true, maxLength: 0 },
  language: { label: 'account.language', hint: '', type: 'select', autoComplete: 'language', required: true, maxLength: 0 },
}

/** The screens and their fields, top to bottom. Below the fields: the button, then (login and invitation) the
 * provider buttons of the OIDC module under "or". The setup has no language field: the language comes from the
 * browser silently and is changed in the profile. */
export const SCREENS = {
  setup: ['setupCode', 'displayName', 'username', 'email', 'newPassword', 'passwordRepeat'],
  invite: ['displayName', 'username', 'email', 'newPassword', 'passwordRepeat'],
  login: ['login', 'password'],
  forgot: ['login'],
  reset: ['newPassword', 'passwordRepeat'],
  profile: ['displayName', 'username', 'email', 'language'],
  operatorInvite: ['email', 'displayName'],
} as const satisfies Record<string, readonly AccountField[]>

export type AccountScreen = keyof typeof SCREENS

/** The parts of the account pages, top to bottom, each titled with ``account.<part>``. ``providerEmailOffer``
 * (since 0.3.3) shows only while the account has ``offered_email``: "Use the address from <provider>?" with
 * ``account.providerEmailTake`` and ``account.providerEmailDismiss`` (``{{provider}}`` the provider's label). "Mail me about a new sign-in"
 * sits under security next to the signed-in devices, not in the profile. ``operatorSignIn``: the operator's switches,
 * each with its hint (``account.factorRequiredSwitchHint``). */
export const SECTIONS = {
  profile: ['picture', 'displayName', 'username', 'email', 'providerEmailOffer', 'language', 'role'],
  /** Since 0.3.6: "Sign out everywhere else" is the button of ``sessions`` ("Signed-in devices"), see ``PAGES``. */
  security: ['password', 'secondFactor', 'recoveryCodes', 'passkeys', 'sessions', 'newSignInMail'],
  operatorSignIn: ['factorRequiredSwitch', 'passkeysAllowed'],
  /** Since 0.3.3: the operator's dialog "Reset the second factor" (``factor.reset_overview``): the account's
   * passkeys by name, then the two boxes, both ticked by default. */
  operatorFactorReset: ['factorResetHint', 'passkeys', 'factorResetPasskeys', 'factorResetDevices'],
} as const satisfies Record<string, readonly string[]>

/** Since 0.3.4: the parts of the operator's dialog "Reset the second factor" for one account (what
 * ``factor.reset_overview`` gave): the passkeys and the box "Remove the passkeys too" only when it has passkeys. The
 * same as ``ResetOverview.parts`` on the server. */
export function factorResetParts(overview: { passkeys: readonly unknown[] | number }): string[] {
  const count = typeof overview.passkeys === 'number' ? overview.passkeys : overview.passkeys.length
  return SECTIONS.operatorFactorReset.filter(
    (part: string) => count > 0 || (part !== 'passkeys' && part !== 'factorResetPasskeys'),
  )
}

/** The boxes of the operator's dialog "Reset the second factor" and how they start. */
export const FACTOR_RESET_DEFAULTS = { factorResetPasskeys: true, factorResetDevices: true } as const

/** One part of an account page (since 0.3.6): its heading or label, the hint under it, the buttons it may show (text
 * keys, in their order; which one shows depends on the state, e.g. ``totpSetup`` or ``totpRemove``). */
export interface PagePart {
  part: string
  title: string
  hint: string
  buttons: readonly string[]
}

/** Since 0.3.6: the pages "Profile" and "Security" as every app shows them, so that they look the same everywhere:
 * the page title, the parts top to bottom (the order of ``SECTIONS``) with their headings, hints and buttons, all
 * from the module's texts. ``stacked``: the fields stand one under the other, never side by side. In the profile the
 * username is changed right in its field; saving asks for the password (``account.confirmWithPassword``; without a
 * password a fresh sign-in, ``account.confirmFresh``). The role shows small at the end. The app's own parts (nexmail
 * "Google and Microsoft accounts", nexnotes "Links for reading") come after the module's (``pageOrder``). */
export const PAGES = {
  profile: {
    title: 'account.profile',
    layout: 'stacked',
    parts: [
      { part: 'picture', title: 'account.picture', hint: 'account.pictureHint', buttons: ['account.pictureUpload', 'account.pictureRemove'] },
      { part: 'displayName', title: 'account.displayName', hint: 'account.displayNameHint', buttons: [] },
      { part: 'username', title: 'account.username', hint: 'account.usernameHintProfile', buttons: ['account.save'] },
      { part: 'email', title: 'account.email', hint: 'account.emailHint', buttons: ['account.save'] },
      { part: 'providerEmailOffer', title: 'account.providerEmailOffer', hint: '', buttons: ['account.providerEmailTake', 'account.providerEmailDismiss'] },
      { part: 'language', title: 'account.language', hint: '', buttons: [] },
      { part: 'role', title: 'account.role', hint: '', buttons: [] },
    ],
  },
  security: {
    title: 'account.security',
    layout: 'stacked',
    parts: [
      { part: 'password', title: 'account.password', hint: '', buttons: ['account.passwordChange'] },
      { part: 'secondFactor', title: 'account.secondFactor', hint: 'account.secondFactorHint', buttons: ['account.totpSetup', 'account.totpRemove'] },
      { part: 'recoveryCodes', title: 'account.recoveryCodes', hint: 'account.recoveryCodesHint', buttons: ['account.recoveryCodesNew'] },
      { part: 'passkeys', title: 'account.passkeys', hint: 'account.passkeysHint', buttons: ['account.passkeyAdd'] },
      { part: 'sessions', title: 'account.sessions', hint: 'account.signOutEverywhereHint', buttons: ['account.signOutEverywhere'] },
      { part: 'newSignInMail', title: 'account.newSignInMail', hint: 'account.newSignInMailHint', buttons: [] },
    ],
  },
} as const satisfies Record<'profile' | 'security', { title: string; layout: 'stacked'; parts: readonly PagePart[] }>

/** Since 0.3.6: the parts a page shows, top to bottom: the module's first in their order, then the app's own. */
export function pageOrder(page: keyof typeof PAGES, own: readonly string[] = []): string[] {
  return [...PAGES[page].parts.map((entry: PagePart) => entry.part), ...own]
}

/** Since 0.3.6: what the second factor shows next to its heading, by the server's ``second_factor`` state: "Off"
 * while none is set up (also where one is required and missing), "On" with an authenticator or a passkey. */
export const SECOND_FACTOR_STATE = {
  none: 'account.stateOff',
  required: 'account.stateOff',
  active: 'account.stateOn',
  passkey: 'account.stateOn',
} as const

/** Since 0.3.6: the setup page's title and subtitle, the same in every app. Under the password no word about the
 * second factor while none is required; where the operator requires one (``factorRequired``), the page says so. */
export const SETUP_PAGE = { title: 'account.setupTitle', subtitle: 'account.setupSubtitle' } as const

export function setupNotes(options: { factorRequired?: boolean } = {}): string[] {
  return options.factorRequired ? ['account.factorRequired'] : []
}

/** Since 0.3.3: notices shown plainly at the top of every account page and of the operator's settings while the
 * server says so. ``secondFactorOff``: the emergency hammer is down (``factor.switched_off()``), with its hint
 * ``account.secondFactorOffHint``. */
export const NOTICES = ['secondFactorOff'] as const

export interface ScreenOptions {
  /** The app's own autocomplete of a field, e.g. { login: 'username webauthn' } where passkeys sign in too. */
  autoComplete?: Partial<Record<AccountField, string>>
}

/** The fields of a screen with their specs; on the profile the display name may stay empty (the username shows). */
export function screenFields(screen: AccountScreen, options: ScreenOptions = {}): Array<FieldSpec & { field: AccountField }> {
  return SCREENS[screen].map((field: AccountField) => {
    const spec = FIELDS[field]
    const optional = (screen === 'profile' || screen === 'operatorInvite') && field === 'displayName'
    const autoComplete = options.autoComplete?.[field] ?? spec.autoComplete
    // In the profile the username is changed right there: its hint says only what it is for.
    const hint = screen === 'profile' && field === 'username' ? 'account.usernameHintProfile' : spec.hint
    return { ...spec, field, autoComplete, hint, required: optional ? false : spec.required }
  })
}

/** How long an invitation and a link of the operator may hold, in days, and the defaults. A link a person asks for
 * on the sign-in page holds one hour, always. */
export const INVITE_DAYS = [1, 7, 30] as const
export const INVITE_DAYS_DEFAULT = 7
export const RESET_DAYS = [1, 7, 30] as const
export const RESET_DAYS_DEFAULT = 1

/** What the app starts after setup, an invitation or a new password (the server's next). */
export const NEXT_STEPS = ['session', 'second_factor', 'second_factor_setup', 'sign_in', 'passkey', 'show_codes'] as const

/** Since 0.3.5: the dialog "Session expired" (the session ended while a page was open; the page stays underneath):
 * its parts for each step, top to bottom, the same as ``common.SESSION_EXPIRED_PARTS`` on the server. It starts at
 * ``sign_in`` (``or``: "or" and the provider buttons as on the sign-in page; ``password`` and its button only where
 * the account has a password), then shows what the server's ``next`` says: the code, the passkey ("Sign in with a
 * passkey"), setting a factor up, the recovery codes. ``session``: the dialog closes and the page goes on. */
export const SESSION_EXPIRED = {
  sign_in: ['sessionExpiredHint', 'password', 'signInAgain', 'or'],
  second_factor: ['code', 'signInAgain'],
  passkey: ['passkeySignIn'],
  second_factor_setup: ['factorRequired', 'totpSetup', 'passkeyAdd'],
  show_codes: ['recoveryCodesHint', 'recoveryCodes'],
  session: [],
} as const satisfies Record<(typeof NEXT_STEPS)[number], readonly string[]>

/** Since 0.3.5: the parts of the dialog "Session expired" for the server's ``next``; an unknown one starts over. */
export function sessionExpiredParts(next: string): readonly string[] {
  return next in SESSION_EXPIRED ? SESSION_EXPIRED[next as keyof typeof SESSION_EXPIRED] : SESSION_EXPIRED.sign_in
}

export function normalizeUsername(raw: string): string {
  return raw.trim().toLowerCase()
}

export function usernameValid(name: string): boolean {
  return USERNAME_PATTERN.test(name) && !name.includes('@')
}

const GERMAN: Record<string, string> = { 'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss' }

/** A username from a display name ('Max Müller' becomes 'max-mueller'); '' when nothing usable is left. The same
 * as the server's suggest_username. */
export function suggestUsername(displayName: string): string {
  let text = (displayName ?? '').normalize('NFC').toLowerCase().replace(/[äöüß]/g, (char) => GERMAN[char] ?? char)
  text = text.normalize('NFKD').replace(/\p{M}/gu, '')
  text = text.replace(/[^a-z0-9._-]+/g, '-').replace(/([._-])[._-]+/g, '$1')
  text = text.replace(/^[._-]+|[._-]+$/g, '')
  if (text.length > USERNAME_MAX) {
    const numbered = /^(.*?)(-\d+)$/.exec(text)
    const suffix = numbered?.[2] ?? ''
    const stem = numbered?.[1] ?? text
    text = stem.slice(0, USERNAME_MAX - suffix.length).replace(/[._-]+$/, '') + suffix
  }
  text = text.replace(/^[._-]+|[._-]+$/g, '')
  return usernameValid(text) ? text : ''
}

/** The username field follows the display name until somebody touches it. */
export function followUsername(state: { touched: boolean; username: string }, displayName: string): string {
  return state.touched ? state.username : suggestUsername(displayName)
}

/** The sign-in field holds an address when it has an @ (a username never has one). */
export function isEmailLogin(typed: string): boolean {
  return typed.includes('@')
}

/** What is wrong with a new password and its repetition, as a text key; '' when nothing. */
export function newPasswordProblem(password: string, repeat: string): string {
  if (password.length < PASSWORD_MIN) return 'account.error.password_too_short'
  if (password !== repeat) return 'account.passwordMismatch'
  return ''
}

/** What is wrong with a username before it goes to the server, as a text key; '' when nothing. */
export function usernameProblem(raw: string): string {
  return usernameValid(normalizeUsername(raw)) ? '' : 'account.usernameRules'
}

/** The default variables of i18next for the texts of this module: the app's name as its container is called, the
 * environment variables of the setup code and of the emergency hammer (since 0.3.3). */
export function kontenVariables(app: string): {
  app: string
  setupTokenEnv: string
  secondFactorOffEnv: string
  minimum: number
} {
  const name = app.trim().toLowerCase()
  const env = name.toUpperCase().replace(/-/g, '_')
  return {
    app: name,
    setupTokenEnv: `${env}_SETUP_TOKEN`,
    secondFactorOffEnv: `${env}_SECOND_FACTOR_OFF`,
    minimum: PASSWORD_MIN,
  }
}

// --- Since 0.3.0: second factor, sessions, passkeys, pictures ------------------------------------------------------

/** Digits of a time-based code; recovery codes are ``xxxxx-xxxxx``. */
export const CODE_DIGITS = 6
export const RECOVERY_CODES = 10
/** "Stay signed in" is ticked by default; ticked 30 days from the last use, else until the browser closes (12 h). */
export const STAY_SIGNED_IN_DEFAULT = true
export const REMEMBER_DAYS = 30
export const BROWSER_HOURS = 12

/** What the code field takes: digits of the authenticator app or a recovery code (letters, a hyphen). */
export function codeLooksValid(typed: string): boolean {
  const code = typed.trim().replace(/[\s-]/g, '')
  return /^[0-9]{6}$/.test(code) || /^[a-z2-9]{10}$/i.test(code)
}

/** The picture for an account without a photo: one letter and a hue (0 to 359) from the name, the same in every app
 * and in the iPhone apps (avatars.placeholder on the server). The app picks lightness and saturation for its look. */
export function avatarPlaceholder(name: string): { letter: string; hue: number } {
  const text = name.trim()
  const first = Array.from(text)[0] ?? ''
  const letter = first ? (Array.from(first.toUpperCase())[0] ?? '?') : '?'
  let hash = 0x811c9dc5
  for (const byte of new TextEncoder().encode(text.toLowerCase())) {
    hash ^= byte
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return { letter, hue: hash % 360 }
}
