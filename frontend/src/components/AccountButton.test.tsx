// @vitest-environment jsdom
/** Galerie-Fund (26.11.): Größe, Art und Symbol eines Knopfs der Kontoseiten kommen aus der Tabelle des Moduls
 * (`BUTTONS`, `buttonSize`), wie in nexnotes; „Verwalten“ und die anderen kleinen Knöpfe sind `sm`. */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { BUTTONS, buttonSize, type ButtonName } from '../vendor/nexkonten/konten'
import { AccountButton } from './AccountButton'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let box: HTMLDivElement
let root: Root

beforeEach(() => {
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

function zeigen(name: ButtonName): HTMLElement {
  act(() => root.render(<AccountButton name={name} onClick={() => undefined} />))
  return box.querySelector('[data-size]') as HTMLElement
}

describe('AccountButton', () => {
  it('gibt einem kleinen Knopf des Moduls `data-size="sm"`, „Verwalten“ eingeschlossen', () => {
    const klein = (Object.keys(BUTTONS) as ButtonName[]).filter((name) => buttonSize(name) === 'sm')
    expect(klein).toContain('account.manage')
    for (const name of klein) expect(zeigen(name).dataset.size, name).toBe('sm')
  })

  it('lässt einen großen bei md', () => {
    const gross = (Object.keys(BUTTONS) as ButtonName[]).find((name) => buttonSize(name) === 'md') as ButtonName
    expect(zeigen(gross).dataset.size).toBe('md')
  })
})
