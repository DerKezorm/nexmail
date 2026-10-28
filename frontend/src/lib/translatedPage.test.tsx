// @vitest-environment jsdom
/** Eine Seite, die der Browser uebersetzt hat: React muss weiterlaufen, nachdem die Textknoten in andere Elemente
 * gewickelt wurden. Der einzige Test mit Dokument (siehe `vite.config.ts`). */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeAll, beforeEach, expect, test } from 'vitest'

import { bearTranslatedPages } from './translatedPage'

let root: Root | null = null
let host: HTMLDivElement | null = null

beforeAll(() => {
  bearTranslatedPages()
})

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
})

/** Macht, was Chromes Uebersetzer tut: jeder Textknoten wird durch <font><font>…</font></font> ersetzt. */
function translateLikeChrome(within: Node) {
  const walker = document.createTreeWalker(within, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  while (walker.nextNode()) texts.push(walker.currentNode as Text)
  for (const text of texts) {
    const outer = document.createElement('font')
    const inner = document.createElement('font')
    inner.textContent = text.data
    outer.appendChild(inner)
    text.replaceWith(outer)
  }
}

function Line({ busy, note }: { busy: boolean; note: boolean }) {
  return (
    <p data-testid="line">
      {busy && <b>busy</b>}
      Saved
      {note && ' just now'}
    </p>
  )
}

const show = (busy: boolean, note: boolean) => act(() => root!.render(<Line busy={busy} note={note} />))
const line = () => host!.querySelector('[data-testid="line"]')!

test('a translated page keeps working when something appears before a text', () => {
  show(false, false)
  translateLikeChrome(line())

  show(true, false)

  // Wohin der Text gehoerte, weiss niemand mehr; das Neue steht dann am Ende statt gar nicht.
  expect(line().querySelector('b')).not.toBeNull()
})

test('something meant to go before a wrapped node goes before its wrapper', () => {
  const holder = document.createElement('p')
  const text = document.createTextNode('Saved')
  holder.append(document.createTextNode('a'), text)
  const wrapper = document.createElement('font')
  holder.replaceChild(wrapper, text)
  wrapper.appendChild(text)

  holder.insertBefore(document.createElement('b'), text)

  expect([...holder.childNodes].map((node) => node.nodeName)).toEqual(['#text', 'B', 'FONT'])
})

test('a translated page keeps working when a text goes away', () => {
  show(false, true)
  translateLikeChrome(line())

  show(false, false)

  expect(line().isConnected).toBe(true)
})

test('an untouched page still puts things where React wants them', () => {
  show(false, false)
  show(true, true)
  expect(line().textContent).toBe('busySaved just now')

  show(false, false)
  expect(line().textContent).toBe('Saved')
})
