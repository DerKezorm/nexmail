/* Die Formen, mit denen die Oberflaeche arbeitet.
 *
 * Sie sind bewusst so geschnitten, wie das Backend sie spaeter liefern soll -
 * die Attrappe fuellt dieselben Felder mit erfundenen Werten. Wenn Stufe 2
 * kommt, wird hier nichts umbenannt, es wird nur die Quelle getauscht.
 */

export type OrdnerRolle =
  | 'posteingang'
  | 'gesendet'
  | 'entwuerfe'
  | 'archiv'
  | 'junk'
  | 'papierkorb'
  | 'eigen'

/** 1 bis 6 - die geprueften Toene aus dem Design-System, in Vergabereihenfolge. */
export type Postfachfarbe = 1 | 2 | 3 | 4 | 5 | 6

export interface Konto {
  /** 'anmeldung', wenn der Mailserver die Zugangsdaten ablehnt. */
  stoerung?: string
  id: string
  anzeigename: string
  adresse: string
  farbe: Postfachfarbe
  /** Freie Schlagworte zum Gruppieren — „privat", „arbeit", „verein". */
  tags: string[]
  /** Weitere Absenderadressen dieses Postfachs. Leer bei fast allen. */
  aliase?: { adresse: string; name: string }[]
}

/** Ein Schlagwort fuer einzelne Mails — als IMAP-Keyword gespeichert.
 *
 *  `atom` ist das Keyword auf dem Mailserver (unveraenderlich), `name` die
 *  Anzeige. `farbe` kommt aus derselben geprueften Palette wie die
 *  Postfachfarben — keine eigene. */
export interface Schlagwort {
  id: number
  name: string
  atom: string
  farbe: Postfachfarbe
  /** Wie viele bekannte Mails das Schlagwort tragen. */
  anzahl: number
}

export interface Ordner {
  id: string
  kontoId: string
  /** Der Pfad, wie der Server ihn nennt — „INBOX", „Haus/Rechnungen".
   *  Daraus baut die Ordnerspalte den Baum. */
  pfad: string
  name: string
  rolle: OrdnerRolle
  ungelesen: number
  anzahl: number
}

export interface Person {
  name: string
  adresse: string
}

export interface Anhang {
  id: string
  dateiname: string
  groesse: number
  typ: string
}

export interface Nachricht {
  /** Nur in der Konversationsansicht > 1: wie viele Mails der Strang hat. */
  strangAnzahl?: number
  strangUngelesen?: number
  strangSchluessel?: string
  id: string
  kontoId: string
  ordnerId: string
  von: Person
  an: Person[]
  kopie?: Person[]
  betreff: string
  anreisser: string
  /** Bereinigtes HTML. In der Attrappe von Hand geschrieben. */
  koerper: string
  datum: string
  gelesen: boolean
  markiert: boolean
  beantwortet: boolean
  /** Aus den Kopfzeilen Importance/X-Priority gedeutet. Fehlt in der
   *  Attrappe — dort gilt „normal". */
  wichtigkeit?: 'hoch' | 'normal' | 'niedrig'
  anhaenge: Anhang[]
  /** Ob die Nachricht Bilder von aussen laedt - dann wird geblockt. */
  hatFremdbilder: boolean
  /** Die Schlagwort-Atome dieser Mail — die Definitionen dazu kommen aus
   *  `/api/schlagworte`. */
  schlagworte: string[]
}

/** Ein Eintrag im Postausgang — geplant oder liegen geblieben.
 *  Die Feldnamen sind die des Servers (`/api/verfassen/ausgang`). */
export interface Ausgangseintrag {
  id: string
  stand: 'wartet' | 'unterwegs' | 'gescheitert'
  betreff: string
  versuche: number
  letzter_fehler: string
  angelegt: string
  /** ISO-UTC. Gesetzt heißt: geplanter Versand ab diesem Zeitpunkt. */
  senden_ab: string | null
}
