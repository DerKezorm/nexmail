/**
 * A button of the account pages: kind, symbol and size come from the module's table (`BUTTONS`, konten 0.3.8; the
 * size since 1.1.0, `buttonSize`), never from the page (E39), so that the same button looks the same in nexmail and nexnotes. The words are the module's (`t(name)`) or,
 * for a button the app words itself (`signIn`, `done`, ...), the children.
 */
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { BUTTONS, buttonSize, type ButtonName } from '../vendor/nexkonten/konten'
import { Button, type ButtonProps, type IconName } from '../vendor/nexui'

export type AccountButtonProps = Omit<ButtonProps, 'kind' | 'icon' | 'size' | 'children'> & { name: ButtonName; children?: ReactNode }

export function AccountButton({ name, children, ...rest }: AccountButtonProps) {
  const { t } = useTranslation()
  const spec = BUTTONS[name]
  return (
    <Button {...rest} kind={spec.kind} icon={spec.icon as IconName} size={buttonSize(name)}>
      {children ?? t(name)}
    </Button>
  )
}
