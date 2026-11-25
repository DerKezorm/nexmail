/* Eine Karte der Einstellungen: seit dem Bauplan „Einstellungen" die `Card` des Bausatzes ui (Symbol in einer
 * Kachel, Titel, eine Zeile, darunter der Inhalt; `id` steht auch als `data-card`). Diese Hülle bleibt nur, damit die
 * Aufrufe mit nexmails Namen (`symbol`, `titel`, `text`) unverändert bleiben. */
import type { ReactNode } from 'react'

import { Card, type IconLike } from '../../vendor/nexui'

export function Karte({
  symbol,
  titel,
  text,
  children,
  id,
  testId,
  logo,
}: {
  symbol: IconLike
  titel: string
  text?: ReactNode
  children?: ReactNode
  id: string
  testId?: string
  logo?: string
}) {
  return (
    <Card id={id} icon={symbol} title={titel} subtitle={text} testId={testId} logo={logo}>
      {children}
    </Card>
  )
}
