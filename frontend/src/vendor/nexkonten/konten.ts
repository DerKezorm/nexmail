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
    return { ...spec, field, autoComplete, required: optional ? false : spec.required }
  })
}

/** How long an invitation and a link of the operator may hold, in days, and the defaults. A link a person asks for
 * on the sign-in page holds one hour, always. */
export const INVITE_DAYS = [1, 7, 30] as const
export const INVITE_DAYS_DEFAULT = 7
export const RESET_DAYS = [1, 7, 30] as const
export const RESET_DAYS_DEFAULT = 1

/** What the app starts after setup, an invitation or a new password (the server's next). */
export const NEXT_STEPS = ['session', 'second_factor', 'second_factor_setup', 'sign_in'] as const

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

/** The default variables of i18next for the texts of this module: the app's name as its container is called and
 * the environment variable of the setup code. */
export function kontenVariables(app: string): { app: string; setupTokenEnv: string; minimum: number } {
  const name = app.trim().toLowerCase()
  return { app: name, setupTokenEnv: `${name.toUpperCase().replace(/-/g, '_')}_SETUP_TOKEN`, minimum: PASSWORD_MIN }
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
