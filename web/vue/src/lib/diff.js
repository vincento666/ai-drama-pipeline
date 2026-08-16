// P5 行级 diff 工具（docs/11 §10：diff 高亮 + 撤销）。
// 简单 LCS：公共前后缀裁剪 + 中间段动态规划（超出规模回退“全改”），够用即可。
// 输出行号均 1 起：added 基于新文本，removed 基于旧文本（对应 pre/div 渲染的索引 + 1）。
export function lineDiff(oldText, newText) {
  const a = String(oldText ?? '').split('\n')
  const b = String(newText ?? '').split('\n')
  // 公共前缀/后缀裁剪（行相等）
  let i = 0
  while (i < a.length && i < b.length && a[i] === b[i]) i++
  let j = 0
  while (j < a.length - i && j < b.length - i && a[a.length - 1 - j] === b[b.length - 1 - j]) j++
  const mid = lcsDiff(a.slice(i, a.length - j), b.slice(i, b.length - j))
  return {
    added: mid.added.map((n) => n + i),      // 1-based in new
    removed: mid.removed.map((n) => n + i),  // 1-based in old
  }
}

// 中间段 LCS（返回 1-based 于各自片段内的行号）
function lcsDiff(a, b) {
  const n = a.length
  const m = b.length
  if (n * m > 250000) {
    // 大文本回退：视为全部改动（行级高亮仍可用）
    return { added: b.map((_, k) => k + 1), removed: a.map((_, k) => k + 1) }
  }
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let x = n - 1; x >= 0; x--) {
    for (let y = m - 1; y >= 0; y--) {
      dp[x][y] = a[x] === b[y] ? dp[x + 1][y + 1] + 1 : Math.max(dp[x + 1][y], dp[x][y + 1])
    }
  }
  const added = []
  const removed = []
  let x = 0
  let y = 0
  while (x < n && y < m) {
    if (a[x] === b[y]) { x++; y++ }
    else if (dp[x + 1][y] >= dp[x][y + 1]) { removed.push(x + 1); x++ }
    else { added.push(y + 1); y++ }
  }
  while (x < n) { removed.push(x + 1); x++ }
  while (y < m) { added.push(y + 1); y++ }
  return { added, removed }
}

// doc 中文标签（agent_manager._doc_of 广播的 P3 载荷）↔ 英文 key（P5 /api/docs/revs）
// 英文 key 原样返回（restore 广播即英文）；未知标签原样返回（toast 不显示撤销）。
const DOC_KEY_MAP = { '分镜': 'board', '剧本': 'script', '小说': 'novel', '简报': 'brief', '资产': 'assets', '成片': 'compose' }
export const docKeyOf = (d) => DOC_KEY_MAP[d] || d
export const docLabelOf = (d) => {
  for (const k in DOC_KEY_MAP) if (DOC_KEY_MAP[k] === d) return k
  return d
}

// 视图归属：boardish（分镜/成片 → 画布刷新链路）；creative（剧本族 → 创意区刷新链路）
export const isBoardishDoc = (d) => d === '分镜' || d === '成片' || d === 'board' || d === 'compose'
