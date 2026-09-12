import { beforeEach, describe, expect, it } from 'vitest'
import { PROJECT_HEADER, getActiveProjectId, setActiveProjectId, withProjectHeader } from './activeProject'

beforeEach(() => setActiveProjectId(null))

describe('activeProject', () => {
  it('未进入项目时不加头，且不改动传入对象', () => {
    const base = { 'Content-Type': 'application/json' }
    expect(withProjectHeader(base)).toEqual(base)
    expect(withProjectHeader(base)).not.toBe(base)
    expect(getActiveProjectId()).toBeNull()
  })

  it('进入项目后追加 X-Project-Id，离开后移除', () => {
    setActiveProjectId('p1')
    expect(PROJECT_HEADER).toBe('X-Project-Id')
    expect(withProjectHeader({})).toEqual({ 'X-Project-Id': 'p1' })
    setActiveProjectId(null)
    expect(withProjectHeader({})).toEqual({})
  })

  it('空白 id 视为未进入项目；有效 id 会裁空白', () => {
    setActiveProjectId('   ')
    expect(getActiveProjectId()).toBeNull()
    setActiveProjectId(' p2 ')
    expect(getActiveProjectId()).toBe('p2')
  })
})
