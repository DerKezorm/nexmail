/* Rückfragen der Kontoseiten im Dialog des gemeinsamen Bausatzes (`ConfirmDialog`, bauplaene/ui), wie in nexnotes:
 * „Abbrechen“ links, der bestätigende Knopf rechts mit Art und Symbol aus `BUTTONS` (konten 0.3.8).
 *
 * Benutzt als Haken: `const { ask, dialog } = useAccountQuestion()`. `ask(...)` löst sich mit dem eingegebenen Text
 * (mit `field`), `true` (ohne) oder `null` (abgebrochen) auf; `dialog` gehört einmal in die Seite. */
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog, Field, type Confirm } from '../vendor/nexui'

export interface AccountQuestion {
  title: string
  text?: ReactNode
  confirm: Confirm
  /** Ein Feld in der Rückfrage: das eigene Passwort (`type: 'password'`) oder ein Name. */
  field?: { label: string; type?: string; initial?: string; autoComplete?: string }
}

export function useAccountQuestion() {
  const { t } = useTranslation()
  const [question, setQuestion] = useState<AccountQuestion | null>(null)
  const [value, setValue] = useState('')
  const answer = useRef<((result: string | true | null) => void) | null>(null)

  const ask = useCallback((next: AccountQuestion) => {
    setQuestion(next)
    setValue(next.field?.initial ?? '')
    return new Promise<string | true | null>((resolve) => {
      answer.current = resolve
    })
  }, [])

  const close = (result: string | true | null) => {
    answer.current?.(result)
    answer.current = null
    setQuestion(null)
  }

  const dialog = question && (
    <ConfirmDialog
      title={question.title}
      text={question.text}
      confirm={question.confirm}
      cancel={t('aktion.abbrechen')}
      closeLabel={t('aktion.schliessen')}
      confirmDisabled={Boolean(question.field && question.field.type === 'password' && !value)}
      onCancel={() => close(null)}
      onConfirm={() => close(question.field ? value : true)}
    >
      {question.field && (
        <Field
          label={question.field.label}
          type={question.field.type ?? 'text'}
          autoComplete={question.field.autoComplete ?? (question.field.type === 'password' ? 'current-password' : 'off')}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      )}
    </ConfirmDialog>
  )

  return { ask, dialog }
}
