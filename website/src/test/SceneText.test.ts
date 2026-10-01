import { describe, it, expect, vi } from 'vitest'

import {
  PIXEL_CANVAS_STYLE,
  SCENE_CONTAINER_STYLE,
  SPEECH_BUBBLE_MS,
  TEXT_CANVAS_STYLE,
  drawLabel,
  drawSpeechBubble,
  initTextCanvas,
  sceneFont,
  sceneFontSize,
  sceneLineHeight,
} from '../hooks/sceneText'

/** A 2D context double whose text is 10px per character, so wrapping is predictable. */
function fakeContext() {
  const filled: { text: string; x: number; y: number }[] = []
  const rects: number[][] = []
  const ctx = {
    font: '',
    fillStyle: '',
    textAlign: 'start',
    textBaseline: 'alphabetic',
    globalAlpha: 1,
    imageSmoothingEnabled: false,
    measureText: (text: string) => ({ width: text.length * 10 }),
    fillText: (text: string, x: number, y: number) => { filled.push({ text, x, y }) },
    fillRect: (...args: number[]) => { rects.push(args) },
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    roundRect: vi.fn(),
    fill: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    scale: vi.fn(),
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, filled, rects, raw: ctx }
}

describe('scene text metrics', () => {
  it('sizes each role from one base and adds the weight when given', () => {
    expect(sceneFontSize('title')).toBeGreaterThan(sceneFontSize('label'))
    expect(sceneFont('name')).toMatch(/^[\d.]+px /)
    expect(sceneFont('name', 'bold')).toMatch(/^bold [\d.]+px /)
    expect(sceneLineHeight('detail')).toBeCloseTo(sceneFontSize('detail') * 1.3)
  })
})

describe('drawLabel', () => {
  it('draws one line and restores the canvas text state', () => {
    const { ctx, filled, raw } = fakeContext()
    expect(drawLabel(ctx, 'hello', 5, 7, { role: 'name', color: '#fff', scale: 1 })).toBe(1)
    expect(filled).toEqual([{ text: 'hello', x: 5, y: 7 }])
    expect(raw.textAlign).toBe('start')
    expect(raw.textBaseline).toBe('alphabetic')
  })

  it('wraps words, hard-breaks a word longer than the line, and offsets each line', () => {
    const { ctx, filled } = fakeContext()
    const lines = drawLabel(ctx, 'ab cd abcdefgh', 0, 0, { role: 'detail', color: '#fff', scale: 1, maxWidth: 50 })
    expect(filled.map(f => f.text)).toEqual(['ab cd', 'abcde', 'fgh'])
    expect(lines).toBe(3)
    expect(filled[1].y).toBeCloseTo(sceneLineHeight('detail'))
  })

  it('keeps text that already fits on one line', () => {
    const { ctx, filled } = fakeContext()
    drawLabel(ctx, 'fits', 0, 0, { role: 'label', color: '#fff', scale: 1, maxWidth: 100 })
    expect(filled.map(f => f.text)).toEqual(['fits'])
  })

  it.each([
    ['start', 10],
    ['center', 10 - 20],
    ['end', 10 - 40],
  ] as const)('places the background box for %s alignment', (align, left) => {
    const { ctx, rects } = fakeContext()
    drawLabel(ctx, 'abcd', 10, 0, { role: 'status', color: '#fff', bgColor: '#000', align, scale: 2, padX: 3 })
    expect(rects).toHaveLength(1)
    expect(rects[0][0]).toBe(left - 3 * 2)
    expect(rects[0][2]).toBe(40 + 3 * 2 * 2)
  })
})

describe('drawSpeechBubble', () => {
  it('draws nothing for blank text', () => {
    const { ctx, filled, raw } = fakeContext()
    drawSpeechBubble(ctx, '   \n ', 50, 50, { scale: 1 })
    expect(filled).toEqual([])
    expect(raw.save).not.toHaveBeenCalled()
  })

  it('clamps to the line limit with an ellipsis and restores the canvas', () => {
    const { ctx, filled, raw } = fakeContext()
    drawSpeechBubble(ctx, 'one two three four five six', 100, 100, { scale: 1, maxWidth: 30, maxLines: 2, alpha: 0.5 })
    expect(filled).toHaveLength(2)
    expect(filled[1].text.endsWith('…')).toBe(true)
    expect(raw.roundRect).toHaveBeenCalledTimes(1)
    expect(raw.restore).toHaveBeenCalledTimes(1)
    expect(raw.textAlign).toBe('start')
  })
})

describe('initTextCanvas', () => {
  it('sizes the backing store for the device pixel ratio', () => {
    const { ctx, raw } = fakeContext()
    const canvas = { width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement
    const before = window.devicePixelRatio
    Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
    try {
      expect(initTextCanvas(canvas, 100, 50, 3)).toBe(ctx)
    } finally {
      Object.defineProperty(window, 'devicePixelRatio', { value: before, configurable: true })
    }
    expect(canvas.width).toBe(600)
    expect(canvas.height).toBe(300)
    expect(raw.scale).toHaveBeenCalledWith(2, 2)
    expect(raw.imageSmoothingEnabled).toBe(true)
  })

  it('refuses a canvas without a 2D context', () => {
    const canvas = { width: 0, height: 0, getContext: () => null } as unknown as HTMLCanvasElement
    expect(() => initTextCanvas(canvas, 10, 10, 1)).toThrow(/2d context/)
  })
})

describe('scene styles', () => {
  it('keeps the canvas layers stacked and the container at the scene aspect ratio', () => {
    expect(TEXT_CANVAS_STYLE.pointerEvents).toBe('none')
    expect(PIXEL_CANVAS_STYLE.imageRendering).toBe('pixelated')
    expect(SCENE_CONTAINER_STYLE(320, 180).aspectRatio).toBe('320/180')
    expect(SPEECH_BUBBLE_MS).toBeGreaterThan(0)
  })
})
