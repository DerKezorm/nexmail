/* Wer nexmail benutzen darf — der Reiter „Konten" in der Verwaltung, die Kontenliste des Betreibers aus dem
 * Kontenmodul (konten 0.3.9, `ACCOUNT_LIST`): je Konto eine Zeile mit Bild, Namen, Marken und „Benutzername · E-Mail“,
 * rechts „Verwalten“. Das öffnet das Fenster mit allen Angaben und beschrifteten Knöpfen (`MANAGE_DIALOG`: Ändern,
 * Rechte, Zugang, Beenden). In jeder nex-App gleich.
 *
 * nexmails Eigenes an den festen Plätzen des Moduls (`pages/kontenliste.ts`): „Betreiber übergeben“ in „Ändern“ vor
 * „Adresse entfernen“, nie am eigenen Konto; „KI erlaubt“ als Haken in „Rechte“; die Zahl der Postfächer als Angabe;
 * beim Löschen die Zahlen der Postfächer und Nachrichten und dass auf dem Mailserver alles bleibt.
 *
 * ⚠️ **Kein offenes Anmelden.** Wer hineindarf, entscheidet der Betreiber
 * einzeln. nexmail ist der Mail-Client eines Haushalts, keine Plattform.
 *
 * ⚠️ **Was fehlt, steht oben — bevor jemand tippt.** Ohne Postausgang geht
 * keine Mail hinaus; eine Einladung geht trotzdem, der Link steht dann zum
 * Weitergeben da.
 */
import { zeitpunkt } from '../lib/format'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Mail, Users } from 'lucide-react'
import { modulAnfrage, api } from '../api/client'
import type { Ich } from '../api/client'
import { AccountButton } from '../components/AccountButton'
import { confirmOf } from '../lib/accountButton'
import { servermeldung } from '../lib/servermeldung'
import {
  ACCOUNT_LIST,
  accountActions,
  accountBadges,
  accountCount,
  accountFacts,
  accountLine,
  accountName,
  accountPicture,
  confirmLine,
  DISPLAY_NAME_MAX,
  FACTOR_RESET_DEFAULTS,
  factorResetParts,
  INVITE_DIALOG,
  inviteFields,
  inviteRow,
  linkSubmit,
  MANAGE_CONFIRM,
  MANAGE_DIALOG,
  manageGroups,
  OPEN_INVITES,
  RESET_DAYS,
  RESET_DAYS_DEFAULT,
  RESET_LINK_DIALOG,
  removeLines,
  USERNAME_MAX,
  type AccountAction,
  type BadgeShown,
  type FactShown,
  type ListedAccount,
} from '../vendor/nexkonten/konten'
import {
  Avatar,
  Badge,
  ButtonGroup,
  Button,
  Card,
  CheckboxRow,
  ConfirmDialog,
  Dialog,
  Facts,
  Field,
  Notice,
  Row,
  Rows,
  SelectField,
  type IconName,
} from '../vendor/nexui'
import { WhatYouSeeCard } from '../vendor/nexkonten/AccountCards'
import { AllKeysCard } from '../vendor/nexschluessel/AllKeysCard'
import { alsEinladung, alsKonto, APP_CAPS, eigenes, type BenutzerZeile, type EinladungsZeile } from './kontenliste'

interface Bestand {
  benutzer: BenutzerZeile[]
  einladungen: EinladungsZeile[]
  postausgang_da: boolean
  adresse_da: boolean
}

/** Was ein Zurücksetzen des zweiten Faktors wegnähme (`GET /api/benutzer/{id}/zweiter-faktor-ueberblick`). */
interface FaktorUeberblick {
  authenticator: boolean
  codes: number
  passkeys: string[]
  geraete: string[]
}

/** Was am Konto hängt (`GET /api/benutzer/{id}/umfang`), für die Rückfrage vor dem Löschen. */
interface Umfang {
  postfaecher: number
  nachrichten: number
  kontakte: number
  regeln: number
  signaturen: number
}

/** Ein Tag in der eingestellten Sprache, ohne Uhrzeit. */
function tag(wann: string, sprache: string): string {
  return new Date(wann).toLocaleDateString(sprache, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/** Tag und Uhrzeit, ohne Sekunden (wie unter Sicherheit). */
function tagUndZeit(wann: string, sprache: string): string {
  return new Date(wann).toLocaleString(sprache, { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** Ein Aufruf mit „läuft“ und dem Fehler als Satz. */
function useVorgang() {
  const { t } = useTranslation()
  const [laeuft, setLaeuft] = useState(false)
  const [fehler, setFehler] = useState('')
  const los = useCallback(
    async (aufruf: () => Promise<unknown>) => {
      setFehler('')
      setLaeuft(true)
      try {
        await aufruf()
        return true
      } catch (f) {
        setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
        return false
      } finally {
        setLaeuft(false)
      }
    },
    [t],
  )
  return { laeuft, fehler, setFehler, los }
}

/** Die Marken einer Zeile oder Einladung im Aussehen des Bausatzes; ein Tag in nexmails Schreibweise. */
function Marken({ marken }: { marken: BadgeShown[] }) {
  const { t, i18n } = useTranslation()
  return (
    <>
      {marken.map((marke, i) => (
        <Badge key={`${marke.badge}-${i}`} tone={marke.tone}>
          {marke.label ?? t(marke.text, marke.date ? { day: tag(marke.date, i18n.language) } : undefined)}
        </Badge>
      ))}
    </>
  )
}

/** Das Bild eines Kontos: das eigene, sonst der Buchstabe auf dem Farbton des Namens (wie überall in nexmail). */
function Bild({ konto, groesse }: { konto: ListedAccount; groesse: 32 | 48 }) {
  const bild = accountPicture(konto)
  return <Avatar src={bild.src} letter={bild.letter} hue={bild.hue} color={bild.color} size={groesse} />
}

export function Benutzerverwaltung({ ich, ichNeuLaden }: { ich?: Ich | null; ichNeuLaden?: () => void }) {
  const { t } = useTranslation()
  const [bestand, setBestand] = useState<Bestand | null>(null)
  const [fehler, setFehler] = useState('')
  const [einladen, setEinladen] = useState(false)
  const [offen, setOffen] = useState<string | null>(null)
  const [zuruecknehmen, setZuruecknehmen] = useState<EinladungsZeile | null>(null)
  const vorgang = useVorgang()

  const laden = useCallback(async () => {
    try {
      setBestand(await api.holen<Bestand>('/api/benutzer'))
    } catch (f) {
      setFehler(servermeldung(f, t('anmeldung.fehler_allgemein')))
    }
  }, [t])

  useEffect(() => {
    void laden()
  }, [laden])

  if (bestand === null) return <div className="h-24" />

  const eigeneId = ich?.id
  // Das eigene Konto zuerst, die anderen, wie der Server sie ordnet.
  const zeilen = [...bestand.benutzer.filter((z) => z.id === eigeneId), ...bestand.benutzer.filter((z) => z.id !== eigeneId)]
  const konten = zeilen.map((z) => alsKonto(z, eigeneId))
  const geoeffnet = offen === null ? null : (zeilen.find((z) => z.id === offen) ?? null)

  return (
    <>
      <Card id="accounts" icon={Users} title={t(ACCOUNT_LIST.title)} subtitle={t(ACCOUNT_LIST.subtitle, { count: accountCount(konten) })} testId="kontenliste">
        {/* nexmails Hinweis ohne Postausgang bleibt (aus post), jetzt in der Karte. */}
        {!bestand.postausgang_da && <Notice tone="warn">{t('verwaltung.kein_postausgang')}</Notice>}
        <div>
          <AccountButton name="account.invite" testId="einladen" onClick={() => setEinladen(true)} />
        </div>
        {fehler && <Notice tone="danger">{fehler}</Notice>}
        <Rows label={t(ACCOUNT_LIST.title)} testId="konten">
          {konten.map((konto) => (
            <Row
              key={konto.id}
              testId={`konto-${konto.username}`}
              lead={<Bild konto={konto} groesse={32} />}
              name={accountName(konto)}
              badge={<Marken marken={accountBadges(konto)} />}
              sub={accountLine(konto)}
              action={
                <AccountButton
                  name="account.manage"
                  aria-label={t(ACCOUNT_LIST.manageLabel, { name: accountName(konto) })}
                  testId="verwalten"
                  onClick={() => setOffen(String(konto.id))}
                >
                  {t(ACCOUNT_LIST.manage)}
                </AccountButton>
              }
            />
          ))}
        </Rows>
      </Card>

      {bestand.einladungen.length > 0 && (
        <Card id="invites" icon={Mail} title={t(OPEN_INVITES.title)} testId="offene-einladungen">
          <Rows label={t(OPEN_INVITES.title)}>
            {bestand.einladungen.map((e) => {
              /* ⚠️ Abgelaufene bleiben sichtbar — sonst verschwindet eine Einladung lautlos und der Betreiber
                 wartet auf jemanden, der nie einen gültigen Link hatte. */
              const zeile = inviteRow(alsEinladung(e))
              return (
                <Row
                  key={e.id}
                  testId="einladung"
                  icon={Mail}
                  name={zeile.name || t(zeile.nameText)}
                  badge={<Marken marken={zeile.badges} />}
                  sub={zeile.sub || undefined}
                  action={<AccountButton name="account.inviteWithdraw" onClick={() => setZuruecknehmen(e)} />}
                />
              )
            })}
          </Rows>
        </Card>
      )}

      {/* konten 1.1.0: „Was du siehst“, mit nexmails Satz. */}
      <WhatYouSeeCard t={t} text={t('verwaltung.was_du_siehst')} />

      {/* Modul schluessel: alle API-Schlüssel aller Konten, Sperren und Entsperren (neu in nexmail). */}
      <AllKeysCard request={modulAnfrage} when={zeitpunkt} words={{ rights: { count: t('apischluessel.stufe_kurz_anzahl'), headers: t('apischluessel.stufe_kurz_betreff') } }} />

      {geoeffnet && (
        <Verwalten
          zeile={geoeffnet}
          konto={alsKonto(geoeffnet, eigeneId)}
          betreiberHatPasswort={ich?.hat_kennwort !== false}
          postausgang={bestand.postausgang_da}
          aufSchliessen={() => setOffen(null)}
          aufGeaendert={(ichAuch) => {
            void laden()
            if (ichAuch) ichNeuLaden?.()
          }}
          aufWeg={() => {
            setOffen(null)
            void laden()
          }}
        />
      )}

      {einladen && (
        <Einladungsfenster
          postausgang={bestand.postausgang_da}
          aufSchliessen={() => setEinladen(false)}
          aufGemacht={() => void laden()}
        />
      )}

      {zuruecknehmen && (
        <ConfirmDialog
          title={t('account.inviteWithdraw')}
          text={t(MANAGE_CONFIRM['account.inviteWithdraw'].text)}
          confirm={confirmOf('account.inviteWithdraw', t('account.inviteWithdraw'))}
          cancel={t('aktion.abbrechen')}
          closeLabel={t('aktion.schliessen')}
          busy={vorgang.laeuft}
          error={vorgang.fehler || undefined}
          onCancel={() => {
            vorgang.setFehler('')
            setZuruecknehmen(null)
          }}
          onConfirm={() =>
            void vorgang
              .los(() => api.loeschen(`/api/benutzer/einladungen/${zuruecknehmen.id}`))
              .then((gut) => {
                if (!gut) return
                setZuruecknehmen(null)
                void laden()
              })
          }
        />
      )}
    </>
  )
}

/** Eine Handlung des Fensters, die auf ihre Bestätigung wartet. */
type Wartend = { handlung: Extract<AccountAction, { type: 'button' }>; umfang?: Umfang | null; ueberblick?: FaktorUeberblick | null }

/** Das Fenster „Verwalten“ (`MANAGE_DIALOG`): Kopf mit Bild, Namen, Marken und Zeile; die Angaben mit nexmails
 *  Postfächern; dann die Gruppen mit beschrifteten Knöpfen. Jede Handlung fragt, wie `MANAGE_CONFIRM` sagt. */
function Verwalten({
  zeile,
  konto,
  betreiberHatPasswort,
  postausgang,
  aufSchliessen,
  aufGeaendert,
  aufWeg,
}: {
  zeile: BenutzerZeile
  konto: ListedAccount
  betreiberHatPasswort: boolean
  postausgang: boolean
  aufSchliessen: () => void
  aufGeaendert: (ichAuch: boolean) => void
  aufWeg: () => void
}) {
  const { t, i18n } = useTranslation()
  const sprache = i18n.language
  const name = accountName(konto)
  const vorgang = useVorgang()
  const [wartend, setWartend] = useState<Wartend | null>(null)
  const [benennen, setBenennen] = useState<'benutzername' | 'anzeigename' | null>(null)
  const [link, setLink] = useState(false)

  const postfaecher: FactShown = { fact: 'mailboxes', label: 'verwaltung.postfaecher', raw: String(zeile.postfaecher) }
  const angaben = accountFacts(konto, [postfaecher]).map((angabe) => ({
    label: t(angabe.label),
    value: (
      <>
        {angabe.raw ?? (angabe.date ? tagUndZeit(angabe.date, sprache) : angabe.text ? t(angabe.text, angabe.values) : '')}
        {angabe.state && <span className="text-[var(--nexui-text-muted)]"> · {t(angabe.state)}</span>}
      </>
    ),
    note: angabe.note ? t(angabe.note) : undefined,
    testId: `angabe-${angabe.fact}`,
  }))
  const gruppen = manageGroups(accountActions(konto, APP_CAPS, eigenes()))

  const beginnen = (handlung: Extract<AccountAction, { type: 'button' }>) => {
    const grund = handlung.name.split(':')[0]
    if (grund === 'account.changeUsername') return setBenennen('benutzername')
    if (grund === 'account.changeDisplayName') return setBenennen('anzeigename')
    if (grund === 'account.resetLink') return setLink(true)
    if (grund === 'account.remove') {
      // ⚠️ **Zahlen statt „alle Daten".** „Wirklich entfernen?" beantwortet man mit Ja, ohne nachzudenken.
      // „3 Postfächer und 12.418 Nachrichten" liest man.
      return void api.holen<Umfang>(`/api/benutzer/${zeile.id}/umfang`).then(
        (umfang) => setWartend({ handlung, umfang }),
        () => setWartend({ handlung, umfang: null }),
      )
    }
    if (grund === 'account.factorReset') {
      return void api.holen<FaktorUeberblick>(`/api/benutzer/${zeile.id}/zweiter-faktor-ueberblick`).then(
        (ueberblick) => setWartend({ handlung, ueberblick }),
        () => setWartend({ handlung, ueberblick: null }),
      )
    }
    setWartend({ handlung })
  }

  /** Ein Haken in „Rechte“: sofort gespeichert, ohne Rückfrage.
   *
   * ⚠️ **„KI erlaubt“ ohne Rückfrage, anders als Löschen und Übergeben.** Es ist mit demselben Klick umkehrbar und
   * kostet niemandem seinen Zugang; die Schlüssel bleiben stehen. Eine Rückfrage für jeden Haken macht die
   * Verwaltung unbenutzbar, und dann wird sie umgangen. */
  const haken = (handlung: Extract<AccountAction, { type: 'check' }>, an: boolean) => {
    if (handlung.right !== 'ai') return
    void vorgang.los(() => api.aendern(`/api/benutzer/${zeile.id}/ki`, { erlaubt: an })).then((gut) => gut && aufGeaendert(konto.self))
  }

  return (
    <>
      <Dialog title={t(MANAGE_DIALOG.title, { name })} onClose={aufSchliessen} closeLabel={t('aktion.schliessen')} testId="verwalten-fenster">
        <div className="flex flex-col gap-4">
          <Rows>
            <Row lead={<Bild konto={konto} groesse={48} />} name={name} badge={<Marken marken={accountBadges(konto)} />} sub={accountLine(konto)} />
          </Rows>
          <Facts items={angaben} label={t(MANAGE_DIALOG.title, { name })} testId="verwalten-angaben" />
          {gruppen.map((gruppe) => (
            <ButtonGroup key={gruppe.group} title={t(gruppe.title)} layout={gruppe.layout} testId={`verwalten-${gruppe.group}`}>
              {gruppe.actions.map((handlung) =>
                handlung.type === 'button' ? (
                  <Button
                    key={handlung.name}
                    kind={handlung.kind}
                    icon={handlung.icon as IconName}
                    disabled={vorgang.laeuft}
                    onClick={() => beginnen(handlung)}
                    testId={`verwalten-${handlung.name}`}
                  >
                    {t(handlung.label, handlung.values)}
                  </Button>
                ) : (
                  <CheckboxRow
                    key={handlung.name}
                    label={t(handlung.label)}
                    checked={handlung.checked}
                    disabled={vorgang.laeuft}
                    onChange={(an) => haken(handlung, an)}
                    testId={`verwalten-${handlung.name}`}
                  />
                ),
              )}
            </ButtonGroup>
          ))}
          {vorgang.fehler && <Notice tone="danger">{vorgang.fehler}</Notice>}
        </div>
      </Dialog>
      {wartend && (
        <Bestaetigen
          zeile={zeile}
          name={name}
          wartend={wartend}
          betreiberHatPasswort={betreiberHatPasswort}
          aufAbbrechen={() => setWartend(null)}
          aufFertig={(weg, ichAuch) => {
            setWartend(null)
            if (weg) aufWeg()
            else aufGeaendert(ichAuch)
          }}
        />
      )}
      {benennen && (
        <Benennen
          zeile={zeile}
          feld={benennen}
          betreiberHatPasswort={betreiberHatPasswort}
          aufSchliessen={() => setBenennen(null)}
          aufGespeichert={() => aufGeaendert(konto.self)}
        />
      )}
      {link && (
        <PasswortLink zeile={zeile} name={name} postausgang={postausgang} betreiberHatPasswort={betreiberHatPasswort} aufSchliessen={() => setLink(false)} />
      )}
    </>
  )
}

/** Die Rückfrage einer Handlung: Titel und Knopf mit den Worten, der Art und dem Symbol der Handlung, der Satz des
 *  Moduls (`MANAGE_CONFIRM`), beim Löschen nexmails Zahlen und „auf dem Mailserver bleibt alles“, beim Zurücksetzen
 *  des zweiten Faktors seine Teile (`factorResetParts`); mit dem eigenen Passwort, wo sie eins verlangt. */
function Bestaetigen({
  zeile,
  name,
  wartend,
  betreiberHatPasswort,
  aufAbbrechen,
  aufFertig,
}: {
  zeile: BenutzerZeile
  name: string
  wartend: Wartend
  betreiberHatPasswort: boolean
  aufAbbrechen: () => void
  aufFertig: (weg: boolean, ichAuch: boolean) => void
}) {
  const { t, i18n } = useTranslation()
  const [passwort, setPasswort] = useState('')
  const [geraete, setGeraete] = useState<boolean>(FACTOR_RESET_DEFAULTS.factorResetDevices)
  const [passkeysWeg, setPasskeysWeg] = useState<boolean>(FACTOR_RESET_DEFAULTS.factorResetPasskeys)
  const vorgang = useVorgang()
  const handlung = wartend.handlung
  const grund = handlung.name.split(':')[0]
  const spec = grund in MANAGE_CONFIRM ? MANAGE_CONFIRM[grund as keyof typeof MANAGE_CONFIRM] : null
  const fragtPasswort = (spec?.confirm ?? 'password') === 'password'
  const feldZeigen = fragtPasswort && betreiberHatPasswort
  const werte = { name, provider: handlung.values?.provider ?? '', email: zeile.kontaktadresse ?? '', app: 'nexmail' }
  const passkeys = wartend.ueberblick?.passkeys ?? []

  const zeilen: ReactNode[] = []
  if (spec?.text && grund !== 'account.factorReset') {
    zeilen.push(<p key="text" className="m-0 text-sm">{t(spec.text, werte)}</p>)
  }
  if (grund === 'account.remove') {
    zeilen.push(
      <p key="zahlen" className="m-0 text-sm" data-testid="entfernen-zahlen">
        {wartend.umfang
          ? t('verwaltung.entfernen_zahlen', {
              postfaecher: t('verwaltung.postfaecher_zahl', { count: wartend.umfang.postfaecher }),
              nachrichten: t('verwaltung.nachrichten_zahl', {
                count: wartend.umfang.nachrichten,
                zahl: wartend.umfang.nachrichten.toLocaleString(i18n.language),
              }),
            })
          : t('verwaltung.entfernen_ohne_zahlen')}
      </p>,
    )
    for (const satz of removeLines(APP_CAPS)) zeilen.push(<p key={satz} className="m-0 text-sm">{t(satz)}</p>)
  }
  if (grund === 'account.factorReset') {
    for (const teil of factorResetParts({ passkeys })) {
      if (teil === 'factorResetHint') zeilen.push(<p key={teil} className="m-0 text-sm">{t('account.factorResetHint')}</p>)
      if (teil === 'passkeys') zeilen.push(<p key={teil} className="m-0 text-sm">{t('account.passkeys')}: {passkeys.join(', ')}</p>)
      if (teil === 'factorResetPasskeys') zeilen.push(<CheckboxRow key={teil} label={t('account.factorResetPasskeys')} checked={passkeysWeg} onChange={setPasskeysWeg} />)
      if (teil === 'factorResetDevices') zeilen.push(<CheckboxRow key={teil} label={t('account.factorResetDevices')} checked={geraete} onChange={setGeraete} />)
    }
  }
  if (fragtPasswort) zeilen.push(<p key="bestaetigen" className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(betreiberHatPasswort))}</p>)

  async function ausfuehren(): Promise<{ weg: boolean; ichAuch: boolean }> {
    const id = zeile.id
    // konten 1.1.0: Rollen (mehrere Betreiber), Sperren, Entsperren, Zurückholen, alle mit dem eigenen Passwort.
    if (grund === 'account.makeOperator' || grund === 'account.makeMember') {
      await api.aendern(`/api/benutzer/${id}/rolle`, { betreiber: grund === 'account.makeOperator', passwort })
      return { weg: false, ichAuch: false }
    }
    if (grund === 'account.block') await api.senden(`/api/benutzer/${id}/sperren`, { passwort })
    if (grund === 'account.unblock') await api.senden(`/api/benutzer/${id}/entsperren`, { passwort })
    if (grund === 'account.restore') await api.senden(`/api/benutzer/${id}/zurueckholen`, { passwort })
    if (grund === 'account.emailRemove') await api.senden(`/api/benutzer/${id}/kontaktadresse-entfernen`, { passwort })
    if (grund === 'account.factorReset') {
      await api.senden(`/api/benutzer/${id}/zweiter-faktor-zuruecksetzen`, {
        passwort,
        geraete_trennen: geraete,
        passkeys_entfernen: passkeysWeg && passkeys.length > 0,
      })
    }
    if (grund === 'account.unlinkProvider' && handlung.provider) {
      await api.loeschen(`/api/oidc/admin/accounts/${zeile.nummer}/links/${handlung.provider.id}`, { password: passwort })
    }
    if (grund === 'account.remove') {
      // Seit konten 1.1.0 bleibt das Konto 30 Tage in der Liste (zum Zurückholen).
      await api.loeschen(`/api/benutzer/${id}`, { passwort })
      return { weg: false, ichAuch: false }
    }
    return { weg: false, ichAuch: false }
  }

  return (
    <ConfirmDialog
      title={t(handlung.label, handlung.values)}
      confirm={confirmOf(handlung.button, t(handlung.label, handlung.values))}
      cancel={t('aktion.abbrechen')}
      closeLabel={t('aktion.schliessen')}
      busy={vorgang.laeuft}
      error={vorgang.fehler || undefined}
      confirmDisabled={feldZeigen && !passwort}
      onCancel={aufAbbrechen}
      onConfirm={() => {
        let ergebnis = { weg: false, ichAuch: false }
        void vorgang
          .los(async () => {
            ergebnis = await ausfuehren()
          })
          .then((gut) => gut && aufFertig(ergebnis.weg, ergebnis.ichAuch))
      }}
      testId="verwalten-frage"
    >
      {zeilen}
      {feldZeigen && (
        <Field
          label={t('account.currentPassword')}
          type="password"
          autoComplete="current-password"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
        />
      )}
    </ConfirmDialog>
  )
}

/** „Anzeigenamen ändern“ oder „Benutzernamen ändern“ (Felder und Hinweise des Moduls), mit dem eigenen Passwort. */
function Benennen({
  zeile,
  feld,
  betreiberHatPasswort,
  aufSchliessen,
  aufGespeichert,
}: {
  zeile: BenutzerZeile
  feld: 'benutzername' | 'anzeigename'
  betreiberHatPasswort: boolean
  aufSchliessen: () => void
  aufGespeichert: () => void
}) {
  const { t } = useTranslation()
  const [wert, setWert] = useState(feld === 'benutzername' ? zeile.benutzername : zeile.anzeigename)
  const [passwort, setPasswort] = useState('')
  const vorgang = useVorgang()
  const titel = feld === 'benutzername' ? t('account.changeUsername') : t('account.changeDisplayName')
  return (
    <Dialog title={titel} onClose={aufSchliessen} closeLabel={t('aktion.schliessen')} testId="benennen">
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          void vorgang
            .los(() => api.aendern(`/api/benutzer/${zeile.id}/${feld}`, { [feld]: wert.trim(), passwort }))
            .then((gut) => {
              if (!gut) return
              aufGespeichert()
              aufSchliessen()
            })
        }}
      >
        {feld === 'benutzername' && <p className="m-0 text-sm">{t('account.askChangeUsername', { name: zeile.anzeigename || zeile.benutzername })}</p>}
        <Field
          label={feld === 'benutzername' ? t('account.username') : t('account.displayName')}
          value={wert}
          onChange={(e) => setWert(e.target.value)}
          maxLength={feld === 'benutzername' ? USERNAME_MAX : DISPLAY_NAME_MAX}
          hints={[feld === 'benutzername' ? t('account.usernameRules') : t('account.displayNameHint')]}
        />
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(betreiberHatPasswort))}</p>
        {betreiberHatPasswort && (
          <Field label={t('account.currentPassword')} type="password" autoComplete="current-password" value={passwort} onChange={(e) => setPasswort(e.target.value)} />
        )}
        {vorgang.fehler && <Notice tone="danger">{vorgang.fehler}</Notice>}
        <div className="flex flex-wrap justify-end gap-2">
          <AccountButton name="cancel" onClick={aufSchliessen}>
            {t('aktion.abbrechen')}
          </AccountButton>
          <AccountButton
            name="account.save"
            type="submit"
            busy={vorgang.laeuft}
            disabled={(betreiberHatPasswort && !passwort) || (feld === 'benutzername' && !wert.trim())}
          />
        </div>
      </form>
    </Dialog>
  )
}

/** Ein Link zum Weitergeben: das Feld zum Lesen und der Knopf, der kopiert. */
function Kopierfeld({ wert, beschriftung, hinweis }: { wert: string; beschriftung: string; hinweis?: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-end gap-2">
      <div className="min-w-0 flex-1">
        <Field label={beschriftung} value={wert} readOnly mono hints={hinweis ? [hinweis] : undefined} onFocus={(e) => e.target.select()} />
      </div>
      <AccountButton name="copy" onClick={() => void navigator.clipboard?.writeText(wert)}>
        {t('aktion.kopieren')}
      </AccountButton>
    </div>
  )
}

/** „Link für ein neues Passwort“ (`RESET_LINK_DIALOG`): Der Betreiber setzt nie selbst ein Passwort. Mit Postausgang
 *  und einer Adresse geht der Link per Mail hin, sonst steht er einmal zum Weitergeben da. */
function PasswortLink({
  zeile,
  name,
  postausgang,
  betreiberHatPasswort,
  aufSchliessen,
}: {
  zeile: BenutzerZeile
  name: string
  postausgang: boolean
  betreiberHatPasswort: boolean
  aufSchliessen: () => void
}) {
  const { t } = useTranslation()
  const [tage, setTage] = useState(String(RESET_DAYS_DEFAULT))
  const [passwort, setPasswort] = useState('')
  const [fertig, setFertig] = useState<{ link: string; an: string } | null>(null)
  const vorgang = useVorgang()
  const sendet = postausgang && Boolean(zeile.kontaktadresse) && zeile.kontaktadresse_zaehlt !== false
  return (
    <Dialog title={t(RESET_LINK_DIALOG.title)} onClose={aufSchliessen} closeLabel={t('aktion.schliessen')} testId="passwort-link">
      {fertig ? (
        <div className="flex flex-col gap-3">
          {fertig.link ? (
            <>
              <p className="m-0 text-sm">{t(RESET_LINK_DIALOG.shown, { name })}</p>
              <Kopierfeld wert={fertig.link} beschriftung={t(RESET_LINK_DIALOG.title)} />
            </>
          ) : (
            <Notice tone="ok">{t(RESET_LINK_DIALOG.sent, { email: fertig.an, name })}</Notice>
          )}
          <div className="flex justify-end">
            <AccountButton name="done" onClick={aufSchliessen}>
              {t('aktion.fertig')}
            </AccountButton>
          </div>
        </div>
      ) : (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void vorgang.los(async () => {
              setFertig(await api.senden<{ link: string; an: string }>(`/api/benutzer/${zeile.id}/passwort-link`, { passwort, tage: Number(tage) }))
            })
          }}
        >
          <p className="m-0 text-sm">{t(RESET_LINK_DIALOG.text, { name })}</p>
          <SelectField
            label={t(RESET_LINK_DIALOG.days.label)}
            value={tage}
            onChange={(e) => setTage(e.target.value)}
            options={RESET_DAYS.map((d) => ({ value: String(d), label: t('account.days', { count: d }) }))}
          />
          <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(betreiberHatPasswort))}</p>
          {betreiberHatPasswort && (
            <Field label={t('account.currentPassword')} type="password" autoComplete="current-password" value={passwort} onChange={(e) => setPasswort(e.target.value)} />
          )}
          {vorgang.fehler && <Notice tone="danger">{vorgang.fehler}</Notice>}
          <div className="flex flex-wrap justify-end gap-2">
            <AccountButton name="cancel" onClick={aufSchliessen}>
              {t('aktion.abbrechen')}
            </AccountButton>
            <AccountButton name={linkSubmit(sendet)} type="submit" busy={vorgang.laeuft} disabled={betreiberHatPasswort && !passwort} />
          </div>
        </form>
      )}
    </Dialog>
  )
}

/** „Person einladen“ (`INVITE_DIALOG`): Adresse, Anzeigename, wie lange es gilt, „Per Mail senden“ nur mit
 *  Postausgang und Adresse; danach immer der Link zum Kopieren. Keine Rolle (nexmail lädt Mitglieder ein) und kein
 *  Benutzername: den wählt die Person selbst. */
function Einladungsfenster({
  postausgang,
  aufSchliessen,
  aufGemacht,
}: {
  postausgang: boolean
  aufSchliessen: () => void
  aufGemacht: () => void
}) {
  const { t, i18n } = useTranslation()
  const [adresse, setAdresse] = useState('')
  const [anzeigename, setAnzeigename] = useState('')
  const [tage, setTage] = useState(String(INVITE_DIALOG.days.default))
  const [senden, setSenden] = useState(true)
  const [gemacht, setGemacht] = useState<EinladungsZeile | null>(null)
  const vorgang = useVorgang()
  const felder = inviteFields(APP_CAPS, { mailServer: postausgang, email: adresse })
  const sendet = felder.includes('sendMail') && senden

  return (
    <Dialog title={t(INVITE_DIALOG.title)} onClose={aufSchliessen} closeLabel={t('aktion.schliessen')} testId="einladen-fenster">
      {gemacht ? (
        <div className="flex flex-col gap-3">
          {gemacht.gemailt && (
            <Notice tone="ok" testId="einladung-gesendet">
              {t(INVITE_DIALOG.done.sent, { email: gemacht.adresse })}
            </Notice>
          )}
          {gemacht.link && (
            <Kopierfeld
              wert={gemacht.link}
              beschriftung={t(INVITE_DIALOG.done.link)}
              hinweis={t(INVITE_DIALOG.done.linkHint, { day: tag(gemacht.laeuft_ab, i18n.language) })}
            />
          )}
          <div className="flex justify-end">
            <AccountButton name="done" onClick={aufSchliessen}>
              {t('aktion.fertig')}
            </AccountButton>
          </div>
        </div>
      ) : (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void vorgang.los(async () => {
              const zeile = await api.senden<EinladungsZeile>('/api/benutzer/einladungen', {
                adresse: adresse.trim(),
                anzeigename: anzeigename.trim(),
                tage: Number(tage),
                senden: sendet,
              })
              setGemacht(zeile)
              aufGemacht()
            })
          }}
        >
          {felder.includes('email') && (
            <Field
              type="email"
              label={t('account.email')}
              hints={[t(INVITE_DIALOG.emailHint)]}
              placeholder="name@example.com"
              value={adresse}
              onChange={(e) => setAdresse(e.target.value)}
            />
          )}
          {felder.includes('displayName') && (
            <Field label={t('account.displayName')} value={anzeigename} maxLength={DISPLAY_NAME_MAX} onChange={(e) => setAnzeigename(e.target.value)} />
          )}
          {felder.includes('days') && (
            <SelectField
              label={t(INVITE_DIALOG.days.label)}
              value={tage}
              onChange={(e) => setTage(e.target.value)}
              options={INVITE_DIALOG.days.options.map((d) => ({ value: String(d), label: t('account.days', { count: d }) }))}
            />
          )}
          {felder.includes('sendMail') && <CheckboxRow label={t(INVITE_DIALOG.sendMail)} checked={senden} onChange={setSenden} />}
          {vorgang.fehler && <Notice tone="danger">{vorgang.fehler}</Notice>}
          <div className="flex flex-wrap justify-end gap-2">
            <AccountButton name="cancel" onClick={aufSchliessen}>
              {t('aktion.abbrechen')}
            </AccountButton>
            <AccountButton
              name={linkSubmit(sendet)}
              type="submit"
              testId="einladung-abschicken"
              busy={vorgang.laeuft}
              disabled={Boolean(adresse.trim()) && !adresse.includes('@')}
            />
          </div>
        </form>
      )}
    </Dialog>
  )
}
