import { describe, it, expect } from 'vitest'

import { BUILTIN_PACK, builtinAnimations, builtinArt } from '../apps/desk-companion/builtinPet'

describe('builtinPet', () => {
  it('names the pack the backend treats as the default', () => {
    expect(BUILTIN_PACK).toBe('default-mochi')
  })

  it('draws each display state and mood from the bundled art', () => {
    const idle = builtinArt('idle')
    expect(idle).toContain('<svg')
    // A pending turn reads as thinking, and a scared pet reuses the error face.
    expect(builtinArt('loading')).toBe(builtinArt('curious'))
    expect(builtinArt('scared')).toBe(builtinArt('error'))
    expect(builtinArt('happy')).toBe(builtinArt('done'))
    expect(builtinArt('busy')).not.toBe(idle)
    expect(builtinArt('sleepy')).not.toBe(idle)
  })

  it('falls back to the resting body for a key it has no drawing for', () => {
    const idle = builtinArt('idle')
    expect(builtinArt()).toBe(idle)
    expect(builtinArt(null)).toBe(idle)
    expect(builtinArt('breathe-in')).toBe(idle)
    // An inherited property name is not a drawing.
    expect(builtinArt('toString')).toBe(idle)
  })

  it('lists the gallery slots with the same art the live pet draws', () => {
    const slots = builtinAnimations()
    expect(Object.keys(slots)).toEqual(['idle', 'done', 'error', 'happy', 'sleepy', 'curious', 'busy', 'scared'])
    for (const [slot, anim] of Object.entries(slots)) {
      expect(anim).toEqual({ content: builtinArt(slot), format: 'svg' })
    }
  })
})
