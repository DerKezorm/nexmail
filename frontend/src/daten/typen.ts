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
  id: string
  anzeigename: string
  adresse: string
  farbe: Postfachfarbe
  /** Freie Schlagworte zum Gruppieren — „privat", „arbeit", „verein". */
  tags: string[]
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
  anhaenge: Anhang[]
  /** Ob die Nachricht Bilder von aussen laedt - dann wird geblockt. */
  hatFremdbilder: boolean
}
