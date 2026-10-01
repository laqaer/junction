import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  drawLabel,
  drawSpeechBubble,
  initTextCanvas,
  sceneFont,
  sceneFontSize,
  sceneLineHeight,
} from '../hooks/sceneText'

/** Record drawing commands with a deterministic four-pixel character width. */
function canvasContext() {
  const context = {
    font: '',
    fillStyle: '',
    textAlign: 'start',
    textBaseline: 'alphabetic',
    globalAlpha: 1,
    imageSmoothingEnabled: false,
    measureText: vi.fn((text: string) => ({ width: Array.from(text).length * 4 })),
    fillText: vi.fn(),
    fillRect: vi.fn(),
    scale: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    roundRect: vi.fn(),
    fill: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
  }
  return { context, drawing: context as unknown as CanvasRenderingContext2D }
}

const originalDpr = Object.getOwnPropertyDescriptor(window, 'devicePixelRatio')

afterEach(() => {
  vi.restoreAllMocks()
  if (originalDpr) Object.defineProperty(window, 'devicePixelRatio', originalDpr)
  else Reflect.deleteProperty(window, 'devicePixelRatio')
})

describe('scene text canvas', () => {
  it.each([2, 0])('maps scene coordinates onto the pixel buffer at DPR %s', (dpr) => {
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: dpr })
    const { context, drawing } = canvasContext()
    const canvas = document.createElement('canvas')
    vi.spyOn(canvas, 'getContext').mockReturnValue(drawing)

    expect(initTextCanvas(canvas, 100, 50, 3)).toBe(drawing)
    expect(canvas.width).toBe(dpr ? 600 : 300)
    expect(canvas.height).toBe(dpr ? 300 : 150)
    expect(context.scale).toHaveBeenCalledExactlyOnceWith(dpr || 1, dpr || 1)
    expect(context.imageSmoothingEnabled).toBe(true)
  })

  it('refuses to draw when the browser cannot supply a 2D context', () => {
    const canvas = document.createElement('canvas')
    vi.spyOn(canvas, 'getContext').mockReturnValue(null)
    expect(() => initTextCanvas(canvas, 100, 50, 1)).toThrow('Failed to get 2d context')
  })

  it('keeps font sizing and line spacing consistent across text roles', () => {
    for (const role of ['title', 'name', 'status', 'detail', 'label', 'spell'] as const) {
      const size = sceneFontSize(role)
      expect(size).toBeGreaterThan(0)
      expect(sceneFont(role)).toContain(`${size}px`)
      expect(sceneFont(role, 'bold')).toBe(`bold ${sceneFont(role)}`)
      expect(sceneLineHeight(role)).toBeGreaterThan(size)
    }
    expect(sceneFontSize('title')).toBeGreaterThan(sceneFontSize('detail'))
  })
})

describe('scene labels', () => {
  it('wraps at word boundaries and returns the height in lines for the next label', () => {
    const { context, drawing } = canvasContext()
    expect(drawLabel(drawing, 'one two three', 40, 20, {
      role: 'name', color: 'text-color', scale: 1, maxWidth: 28,
    })).toBe(2)
    expect(context.fillText.mock.calls).toEqual([
      ['one two', 40, 20],
      ['three', 40, 20 + sceneLineHeight('name')],
    ])
    expect(context.fillRect).not.toHaveBeenCalled()
    expect(context.textAlign).toBe('start')
    expect(context.textBaseline).toBe('alphabetic')
  })

  it('hard-breaks an overlong identifier without losing or reordering its characters', () => {
    const { context, drawing } = canvasContext()
    expect(drawLabel(drawing, 'abcdefghij', 0, 0, {
      role: 'detail', color: 'text-color', scale: 1, maxWidth: 12,
    })).toBe(4)
    const lines = context.fillText.mock.calls.map(([text]) => text as string)
    expect(lines).toEqual(['abc', 'def', 'ghi', 'j'])
    expect(lines.join('')).toBe('abcdefghij')
    expect(lines.every(line => context.measureText(line).width <= 12)).toBe(true)
  })

  it.each(['start', 'center', 'end'] as const)(
    'keeps a padded background aligned with %s-aligned text', (align) => {
      const { context, drawing } = canvasContext()
      expect(drawLabel(drawing, 'text', 40, 20, {
        role: 'status', weight: 'bold', color: 'text-color', bgColor: 'background-color',
        align, scale: 2, padX: 4, padY: 3,
      })).toBe(1)
      const [left, top, width, height] = context.fillRect.mock.calls[0] as number[]
      expect(width).toBe(32)
      expect(height).toBeGreaterThan(sceneFontSize('status'))
      expect(top + height / 2).toBe(20)
      const textLeft = align === 'center' ? 32 : align === 'end' ? 24 : 40
      expect(left).toBe(textLeft - 8)
      expect(left + width).toBe(textLeft + 16 + 8)
      expect(context.fillText).toHaveBeenCalledExactlyOnceWith('text', 40, 20)
      expect(context.fillStyle).toBe('text-color')
      expect(context.font).toBe(sceneFont('status', 'bold'))
    },
  )

  it('still paints whitespace when wrapping finds no words', () => {
    const { context, drawing } = canvasContext()
    expect(drawLabel(drawing, '   ', 4, 8, {
      role: 'label', color: 'text-color', scale: 1, maxWidth: 4,
    })).toBe(1)
    expect(context.fillText).toHaveBeenCalledExactlyOnceWith('   ', 4, 8)
  })
})

describe('agent speech bubbles', () => {
  it('does not draw an empty message or whitespace-only bubble', () => {
    const { context, drawing } = canvasContext()
    drawSpeechBubble(drawing, ' \n\t ', 30, 40, { scale: 1 })
    expect(context.fillText).not.toHaveBeenCalled()
    expect(context.roundRect).not.toHaveBeenCalled()
    expect(context.save).not.toHaveBeenCalled()
  })

  it('normalizes message whitespace and paints an unclipped short message', () => {
    const { context, drawing } = canvasContext()
    drawSpeechBubble(drawing, '  one\n\t two  ', 30, 40, { scale: 1 })
    expect(context.fillText.mock.calls.map(([text]) => text)).toEqual(['one two'])
    expect(context.roundRect).toHaveBeenCalledOnce()
    expect(context.save).toHaveBeenCalledOnce()
    expect(context.restore).toHaveBeenCalledOnce()
    expect(context.textAlign).toBe('start')
    expect(context.textBaseline).toBe('alphabetic')
  })

  it('limits tall messages with an ellipsis while keeping the tail anchored over the agent', () => {
    const { context, drawing } = canvasContext()
    const opacityAtPaint: number[] = []
    context.fill.mockImplementation(() => { opacityAtPaint.push(context.globalAlpha) })
    drawSpeechBubble(drawing, 'alpha beta gamma delta', 60, 80, {
      scale: 2, maxWidth: 20, maxLines: 2, alpha: 0.5,
    })
    expect(context.fillText.mock.calls.map(([text]) => text)).toEqual(['alpha', 'be…'])
    expect(opacityAtPaint).toEqual([0.5, 0.5])
    const [left, top, width, height] = context.roundRect.mock.calls[0] as number[]
    expect(left + width / 2).toBe(60)
    expect(width).toBe(20 + 16)
    expect(top + height).toBeLessThan(80)
    expect(context.moveTo.mock.calls[0][0]).toBeLessThan(60)
    expect(context.lineTo.mock.calls[0][0]).toBe(60)
    expect(context.lineTo.mock.calls[1][0]).toBeGreaterThan(60)
    expect(context.lineTo.mock.calls[0][1]).toBeLessThan(80)
    expect(context.restore).toHaveBeenCalledOnce()
  })
})
