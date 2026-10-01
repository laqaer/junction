import { describe, expect, it } from 'vitest'

import idleSvg from '../../assets/pets/mochi_idle.svg?raw'
import doneSvg from '../../assets/pets/mochi_done.svg?raw'
import errorSvg from '../../assets/pets/mochi_error.svg?raw'
import sleepingSvg from '../../assets/pets/mochi_sleeping.svg?raw'
import thinkingSvg from '../../assets/pets/mochi_thinking.svg?raw'
import workingSvg from '../../assets/pets/mochi_working.svg?raw'
import { BUILTIN_PACK, builtinAnimations, builtinArt } from './builtinPet'

describe('the companion built-in pet', () => {
  it('keeps the pack identifier shared with the gallery and backend', () => {
    expect(BUILTIN_PACK).toBe('default-mochi')
  })

  it.each([
    ['idle', idleSvg],
    ['loading', thinkingSvg],
    ['done', doneSvg],
    ['error', errorSvg],
    ['happy', doneSvg],
    ['sleepy', sleepingSvg],
    ['curious', thinkingSvg],
    ['busy', workingSvg],
    ['scared', errorSvg],
  ])('draws the bundled art for %s', (state, art) => {
    expect(builtinArt(state)).toBe(art)
    expect(art).toContain('<svg')
  })

  it.each([undefined, null, '', 'unknown', '__proto__', 'constructor', 'toString'])(
    'falls back to the resting body for an unsupported key %s',
    (state) => {
      expect(builtinArt(state)).toBe(idleSvg)
    },
  )

  it('supplies every gallery slot as SVG text from the same bundled drawings', () => {
    expect(builtinAnimations()).toEqual({
      idle: { content: idleSvg, format: 'svg' },
      done: { content: doneSvg, format: 'svg' },
      error: { content: errorSvg, format: 'svg' },
      happy: { content: doneSvg, format: 'svg' },
      sleepy: { content: sleepingSvg, format: 'svg' },
      curious: { content: thinkingSvg, format: 'svg' },
      busy: { content: workingSvg, format: 'svg' },
      scared: { content: errorSvg, format: 'svg' },
    })
  })

  it('gives each gallery caller its own editable slot data', () => {
    const animations = builtinAnimations()
    animations.idle.content = 'custom art'
    delete animations.done

    expect(builtinAnimations().idle.content).toBe(idleSvg)
    expect(builtinAnimations().done).toEqual({ content: doneSvg, format: 'svg' })
    expect(builtinArt('idle')).toBe(idleSvg)
  })
})
