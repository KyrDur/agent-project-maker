export const semanticModel = 'all-MiniLM-L6-v2'
export const lexicalModel = 'sha256-lexical-bigram-v1'
export function embeddingLabel(index) {
  const snapshot = index?.embedding_snapshot
  if (!snapshot) return '尚未建立索引'
  return snapshot.model === semanticModel
    ? '本地语义检索 · all-MiniLM-L6-v2 · 384 维'
    : `词汇检索 · ${snapshot.model} · ${snapshot.dimension} 维`
}
