'use client'

import { useQuery } from '@tanstack/react-query'
import { conversationsApi } from '@/lib/api/conversations'
import { conversationKeys } from '@/lib/hooks/use-conversations'

/**
 * 获取对话文件列表（`GET /api/conversations/{id}/files`）。
 *
 * 右侧 rail 只使用该结果中的 `source==='attached'`（用户附件）。
 * 生成产物继续沿用 `useConversationArtifacts` + `chatArtifactsAtom`（streaming LIVE
 * 更新），因此这个 hook 不能成为生成产物的单一数据源。
 */
export function useConversationFiles(conversationId: string | null | undefined) {
  return useQuery({
    queryKey: conversationKeys.files(conversationId),
    queryFn: () => conversationsApi.files(conversationId ?? ''),
    enabled: Boolean(conversationId),
    staleTime: 15_000,
  })
}
