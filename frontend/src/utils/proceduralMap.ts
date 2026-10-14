/**
 * 程序化世界底图：按种子 + 地形提示确定性地生成纸质地图元素（海岸线 / 山脉 / 河流 / 林地 / 区域名）。
 * 同一种子与地形提示永远得到同一张底图（刷新、换设备都不跳）；坐标系是 1000×700 的画布，
 * 地点坐标仍以 0–100 百分比保存，渲染时用 toCanvas 换算。
 */
import type { MapTerrain } from '@/types/writing'

export const MAP_WIDTH = 1000
export const MAP_HEIGHT = 700

export type SeaSide = 'east' | 'west' | 'north' | 'south' | 'none'

export interface Peak { x: number; y: number; size: number }
export interface Grove { x: number; y: number; r: number }

export interface BaseMap {
  seaSide: SeaSide
  /** 陆地多边形（SVG path） */
  coastPath: string
  mountains: Peak[]
  rivers: string[]
  forests: Grove[]
  regions: { name: string; x: number; y: number }[]
}

const SIDES: SeaSide[] = ['east', 'south', 'west', 'north', 'none']
const COAST_STEP = 25

const r2 = (v: number) => Math.round(v * 100) / 100
const clampX = (v: number) => Math.min(MAP_WIDTH, Math.max(0, v))
const clampY = (v: number) => Math.min(MAP_HEIGHT, Math.max(0, v))

/** mulberry32：小而稳定的种子随机数 */
export function createRng(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function toCanvas(xPct: number, yPct: number): [number, number] {
  return [r2((xPct / 100) * MAP_WIDTH), r2((yPct / 100) * MAP_HEIGHT)]
}

export function toPercent(x: number, y: number): [number, number] {
  return [r2((x / MAP_WIDTH) * 100), r2((y / MAP_HEIGHT) * 100)]
}

interface Coast {
  path: string
  isSea: (x: number, y: number) => boolean
}

function buildCoast(rng: () => number, side: SeaSide): Coast {
  if (side === 'none') return { path: `M0,0 H${MAP_WIDTH} V${MAP_HEIGHT} H0 Z`, isSea: () => false }
  const horizontal = side === 'east' || side === 'west'
  const length = horizontal ? MAP_HEIGHT : MAP_WIDTH
  const span = horizontal ? MAP_WIDTH : MAP_HEIGHT
  const phase = rng() * Math.PI * 2
  const base = 0.18 + rng() * 0.08
  const depths: number[] = []
  for (let i = 0; i * COAST_STEP <= length; i += 1) {
    const wave = 0.05 * Math.sin(i * 0.33 + phase) + 0.025 * Math.sin(i * 0.9 + phase * 2)
    depths.push(r2((base + wave + (rng() - 0.5) * 0.03) * span))
  }
  const coastAt = (t: number) => depths[Math.min(depths.length - 1, Math.max(0, Math.round(t / COAST_STEP)))]
  const pts = depths.map((d, i) => {
    const t = Math.min(i * COAST_STEP, length)
    if (side === 'east') return [MAP_WIDTH - d, t]
    if (side === 'west') return [d, t]
    if (side === 'south') return [t, MAP_HEIGHT - d]
    return [t, d]
  })
  const line = pts.map(([x, y]) => `${r2(x)},${r2(y)}`).join(' L')
  let path: string
  if (side === 'east') path = `M0,0 L${line} L0,${MAP_HEIGHT} Z`
  else if (side === 'west') path = `M${MAP_WIDTH},0 L${line} L${MAP_WIDTH},${MAP_HEIGHT} Z`
  else if (side === 'south') path = `M0,0 L${line} L${MAP_WIDTH},0 Z`
  else path = `M0,${MAP_HEIGHT} L${line} L${MAP_WIDTH},${MAP_HEIGHT} Z`
  const isSea = (x: number, y: number) => {
    if (side === 'east') return x > MAP_WIDTH - coastAt(y)
    if (side === 'west') return x < coastAt(y)
    if (side === 'south') return y > MAP_HEIGHT - coastAt(x)
    return y < coastAt(x)
  }
  return { path, isSea }
}

function randomLandPoint(rng: () => number, coast: Coast, margin = 40): [number, number] {
  for (let tries = 0; tries < 12; tries += 1) {
    const x = margin + rng() * (MAP_WIDTH - margin * 2)
    const y = margin + rng() * (MAP_HEIGHT - margin * 2)
    if (!coast.isSea(x, y)) return [x, y]
  }
  return [MAP_WIDTH / 2, MAP_HEIGHT / 2]
}

function smoothPath(points: [number, number][]): string {
  if (points.length < 2) return ''
  const [first, ...rest] = points
  let d = `M${r2(first[0])},${r2(first[1])}`
  for (let i = 0; i < rest.length - 1; i += 1) {
    const [cx, cy] = rest[i]
    const [nx, ny] = rest[i + 1]
    d += ` Q${r2(cx)},${r2(cy)} ${r2((cx + nx) / 2)},${r2((cy + ny) / 2)}`
  }
  const last = rest[rest.length - 1]
  return `${d} L${r2(last[0])},${r2(last[1])}`
}

function buildMountains(rng: () => number, coast: Coast, terrain: MapTerrain): Peak[] {
  const peaks: Peak[] = []
  const hinted = terrain.mountains ?? []
  if (hinted.length > 0) {
    for (const m of hinted) {
      const [cx, cy] = toCanvas(m.x, m.y)
      const radius = (Math.max(3, m.r) / 100) * MAP_WIDTH * 0.6
      peaks.push({ x: clampX(cx), y: clampY(cy), size: 26 })
      const count = 3 + Math.floor(rng() * 4)
      for (let i = 0; i < count; i += 1) {
        const angle = rng() * Math.PI * 2
        const dist = rng() * radius
        peaks.push({ x: r2(clampX(cx + Math.cos(angle) * dist)), y: r2(clampY(cy + Math.sin(angle) * dist * 0.7)), size: r2(14 + rng() * 12) })
      }
    }
    return peaks
  }
  const ranges = 2 + Math.floor(rng() * 3)
  for (let r = 0; r < ranges; r += 1) {
    let [x, y] = randomLandPoint(rng, coast, 80)
    const angle = rng() * Math.PI * 2
    const count = 5 + Math.floor(rng() * 5)
    for (let i = 0; i < count; i += 1) {
      if (!coast.isSea(x, y)) peaks.push({ x: r2(clampX(x)), y: r2(clampY(y)), size: r2(14 + rng() * 14) })
      const step = 26 + rng() * 14
      x += Math.cos(angle + (rng() - 0.5) * 0.6) * step
      y += Math.sin(angle + (rng() - 0.5) * 0.6) * step * 0.7
    }
  }
  return peaks
}

function buildRivers(rng: () => number, coast: Coast, side: SeaSide, terrain: MapTerrain, peaks: Peak[]): string[] {
  const hinted = terrain.rivers ?? []
  if (hinted.length > 0) {
    return hinted
      .map((river) => smoothPath(river.points.map(([px, py]) => toCanvas(px, py))))
      .filter(Boolean)
  }
  const target: Record<SeaSide, [number, number]> = {
    east: [1, 0], west: [-1, 0], south: [0, 1], north: [0, -1], none: [rng() - 0.5, rng() - 0.5],
  }
  const rivers: string[] = []
  const count = 1 + Math.floor(rng() * 2)
  for (let i = 0; i < count; i += 1) {
    const source = peaks.length > 0 ? peaks[Math.floor(rng() * peaks.length)] : null
    let [x, y] = source ? [source.x, source.y + 12] : randomLandPoint(rng, coast)
    const [dx, dy] = target[side]
    const points: [number, number][] = [[x, y]]
    const steps = 10 + Math.floor(rng() * 7)
    for (let s = 0; s < steps; s += 1) {
      const angle = Math.atan2(dy, dx) + (rng() - 0.5) * 1.1
      x = clampX(x + Math.cos(angle) * 42)
      y = clampY(y + Math.sin(angle) * 42)
      points.push([x, y])
      if (coast.isSea(x, y) || x <= 0 || x >= MAP_WIDTH || y <= 0 || y >= MAP_HEIGHT) break
    }
    rivers.push(smoothPath(points))
  }
  return rivers
}

function buildForests(rng: () => number, coast: Coast, peaks: Peak[]): Grove[] {
  const groves: Grove[] = []
  const count = 18 + Math.floor(rng() * 14)
  for (let i = 0; i < count; i += 1) {
    const [x, y] = randomLandPoint(rng, coast, 30)
    if (peaks.some((p) => Math.hypot(p.x - x, p.y - y) < 22)) continue
    groves.push({ x: r2(clampX(x)), y: r2(clampY(y)), r: r2(6 + rng() * 8) })
  }
  return groves
}

export function buildBaseMap(seed: number, terrain: MapTerrain): BaseMap {
  const rng = createRng(seed)
  const pick = SIDES[Math.floor(rng() * SIDES.length)]
  const seaSide: SeaSide = terrain.sea ?? pick
  const coast = buildCoast(rng, seaSide)
  const mountains = buildMountains(rng, coast, terrain)
  const rivers = buildRivers(rng, coast, seaSide, terrain, mountains)
  const forests = buildForests(rng, coast, mountains)
  const regions = (terrain.regions ?? []).map((region) => {
    const [x, y] = toCanvas(region.x, region.y)
    return { name: region.name, x, y }
  })
  return { seaSide, coastPath: coast.path, mountains, rivers, forests, regions }
}
