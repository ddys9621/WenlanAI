import { describe, expect, it } from 'vitest'
import { MAP_HEIGHT, MAP_WIDTH, buildBaseMap, createRng, toCanvas, toPercent } from './proceduralMap'

describe('createRng', () => {
  it('同一种子得到同一串随机数，不同种子不同', () => {
    const a = createRng(42), b = createRng(42), c = createRng(43)
    const seqA = [a(), a(), a()]
    expect([b(), b(), b()]).toEqual(seqA)
    expect([c(), c(), c()]).not.toEqual(seqA)
    seqA.forEach((v) => expect(v >= 0 && v < 1).toBe(true))
  })
})

describe('buildBaseMap', () => {
  it('同一种子 + 地形提示 → 底图完全一致（刷新不跳）', () => {
    expect(buildBaseMap(7, {})).toEqual(buildBaseMap(7, {}))
    expect(buildBaseMap(7, {})).not.toEqual(buildBaseMap(8, {}))
  })

  it('有地形提示时按提示放山脉 / 河流 / 区域名，海在指定一侧', () => {
    const map = buildBaseMap(1, {
      sea: 'east',
      mountains: [{ x: 30, y: 20, r: 10 }],
      rivers: [{ points: [[10, 40], [50, 55], [90, 60]] }],
      regions: [{ name: '东荒', x: 75, y: 40 }],
    })
    expect(map.seaSide).toBe('east')
    expect(map.mountains.length).toBeGreaterThan(0)
    const [mx, my] = toPercent(map.mountains[0].x, map.mountains[0].y)
    expect(Math.abs(mx - 30)).toBeLessThan(15)
    expect(Math.abs(my - 20)).toBeLessThan(15)
    expect(map.rivers).toHaveLength(1)
    expect(map.regions).toEqual([{ name: '东荒', x: toCanvas(75, 40)[0], y: toCanvas(75, 40)[1] }])
    expect(map.coastPath.startsWith('M')).toBe(true)
  })

  it('所有元素都在画布内', () => {
    const map = buildBaseMap(99, {})
    for (const m of [...map.mountains, ...map.forests]) {
      expect(m.x).toBeGreaterThanOrEqual(0)
      expect(m.x).toBeLessThanOrEqual(MAP_WIDTH)
      expect(m.y).toBeGreaterThanOrEqual(0)
      expect(m.y).toBeLessThanOrEqual(MAP_HEIGHT)
    }
  })
})

describe('坐标换算', () => {
  it('百分比 ↔ 画布坐标互逆', () => {
    const [x, y] = toCanvas(25, 60)
    expect(toPercent(x, y)).toEqual([25, 60])
  })
})
