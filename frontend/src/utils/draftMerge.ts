/**
 * 外部数据刷新（如智能助笔应用了修改）时只更新作者没动过的字段（参考岚笺「只替换仍等于提交前快照的草稿字段」）：
 * 草稿值仍等于上一次的基准值 → 换成新值；作者已经改了的 → 保留作者的输入，不被刷新冲掉。
 */
export function mergeUntouched<T extends object>(draft: T, base: T, next: T): T {
  const out = { ...draft }
  for (const key of Object.keys(next) as (keyof T)[]) {
    if (Object.is(draft[key], base[key])) out[key] = next[key]
  }
  return out
}
