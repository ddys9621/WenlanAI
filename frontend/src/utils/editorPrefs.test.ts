import { describe, expect, it } from 'vitest'
import { DEFAULT_EDITOR_PREFS, loadEditorPrefs, saveEditorPrefs } from './editorPrefs'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    data,
    getItem: (key: string) => (key in data ? data[key] : null),
    setItem: (key: string, value: string) => { data[key] = value },
  }
}

describe('editorPrefs', () => {
  it('没有记录时用默认值：补全默认关（作者主动打开才调用模型）', () => {
    expect(loadEditorPrefs(memoryStorage())).toEqual(DEFAULT_EDITOR_PREFS)
    expect(DEFAULT_EDITOR_PREFS.completion).toBe(false)
  })

  it('保存后能原样读回', () => {
    const storage = memoryStorage()
    const prefs = { ...DEFAULT_EDITOR_PREFS, completion: true, completionLength: 'sentence' as const, fontSize: 19, paper: 'night' as const }
    saveEditorPrefs(prefs, storage)
    expect(loadEditorPrefs(storage)).toEqual(prefs)
  })

  it('坏数据逐项回落默认，数值夹在范围内', () => {
    const storage = memoryStorage()
    storage.setItem('wenlan-editor-prefs', JSON.stringify({ completion: 'yes', fontSize: 99, leading: 1, guideStyle: 'zigzag', paper: 'night' }))
    const prefs = loadEditorPrefs(storage)
    expect(prefs.completion).toBe(DEFAULT_EDITOR_PREFS.completion)
    expect(prefs.fontSize).toBe(22)
    expect(prefs.leading).toBe(1.6)
    expect(prefs.guideStyle).toBe(DEFAULT_EDITOR_PREFS.guideStyle)
    expect(prefs.paper).toBe('night')
    storage.setItem('wenlan-editor-prefs', '{不是 JSON')
    expect(loadEditorPrefs(storage)).toEqual(DEFAULT_EDITOR_PREFS)
  })

  it('存储不可用（隐私模式）时不抛错', () => {
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } }
    expect(loadEditorPrefs(broken)).toEqual(DEFAULT_EDITOR_PREFS)
    expect(() => saveEditorPrefs(DEFAULT_EDITOR_PREFS, broken)).not.toThrow()
  })
})
