// @vitest-environment jsdom
/** Wo Menü und Untermenü stehen (gemessen 27.11.2026: 25 Einträge bei 800×600 liefen 118 px unten hinaus; ein
 * Untermenü blieb rechts außerhalb, wenn auch links kein Platz war). Beides muss immer ganz im Bild sein. */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'

import { Kontextmenue, hauptPosition, unterPosition } from './Kontextmenue'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const B = 232

describe('Hauptmenü', () => {
  it('bleibt, wo geklickt wurde, wenn es passt', () => {
    expect(hauptPosition(100, 100, B, 300, 800, 600)).toEqual({ x: 100, y: 100 })
  })

  it('kippt am rechten und am unteren Rand', () => {
    expect(hauptPosition(700, 500, B, 300, 800, 600)).toEqual({ x: 700 - B, y: 200 })
  })

  it('ein zu langes Menü steht oben auf 8 px und reicht bis 8 px über den unteren Rand', () => {
    // 25 Einträge zu 32 px = 800 px, das Fenster ist 600 hoch: max-height 584 (gemessene Höhe), oben auf 8.
    const { y } = hauptPosition(100, 300, B, 584, 800, 600)
    expect(y).toBe(8)
    expect(y + 584).toBe(592)
  })

  it('setzt max-height und scrollt in sich', async () => {
    const box = document.createElement('div')
    document.body.append(box)
    const root = createRoot(box)
    const eintraege = Array.from({ length: 25 }, (_, i) => ({ id: `e${i}`, text: `Eintrag ${i}` }))
    await act(async () => root.render(<Kontextmenue x={10} y={10} eintraege={eintraege} aufSchliessen={() => undefined} />))
    const menue = box.querySelector<HTMLElement>('[role="menu"]')!
    expect(menue.style.maxHeight).toBe('calc(100dvh - 16px)')
    expect(menue.className).toContain('overflow-y-auto')
    act(() => root.unmount())
    box.remove()
  })
})

describe('Untermenü', () => {
  it('rechts neben der Zeile, wo Platz ist', () => {
    expect(unterPosition({ left: 100, right: 332, top: 50 }, B, 200, 1200, 800)).toEqual({ left: 332, top: 50, links: false })
  })

  it('links daneben, wo rechts kein Platz ist', () => {
    expect(unterPosition({ left: 500, right: 732, top: 50 }, B, 200, 800, 800)).toEqual({ left: 268, top: 50, links: true })
  })

  it('auf keiner Seite Platz: an den rechten Rand geklemmt, ganz sichtbar', () => {
    // 400 px breit, Menü bei 100..332: rechts endet bei 564, links beginnt bei -132.
    const lage = unterPosition({ left: 100, right: 332, top: 50 }, B, 200, 400, 800)
    expect(lage.left).toBe(400 - 8 - B)
    expect(lage.left).toBeGreaterThanOrEqual(8)
    expect(lage.left + B).toBeLessThanOrEqual(400 - 8)
  })

  it('rückt am unteren Rand hoch, nie über den oberen', () => {
    expect(unterPosition({ left: 100, right: 332, top: 500 }, B, 300, 1200, 600)).toEqual({ left: 332, top: 292, links: false })
    expect(unterPosition({ left: 100, right: 332, top: 100 }, B, 700, 1200, 600).top).toBe(8)
  })
})
