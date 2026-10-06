'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { skillBuilderApi } from '@/lib/api/skill-builder'
import { skillQueryKeys } from '@/lib/query-keys/skills'
import { requireQueryId } from './query-id'
import type {
  SkillBuilderSessionListParams,
  SkillBuilderStartRequest,
  SkillDraftPackage,
} from '@/lib/types/skill-builder'

export const skillBuilderKeys = {
  all: ['skill-builder'] as const,
  lists: ['skill-builder', 'list'] as const,
  list: (params?: SkillBuilderSessionListParams) =>
    ['skill-builder', 'list', params ?? {}] as const,
  detail: (sessionId: string | null | undefined) => ['skill-builder', sessionId] as const,
  files: (sessionId: string | null | undefined) => ['skill-builder', sessionId, 'files'] as const,
  fileContent: (sessionId: string | null | undefined, path: string | null) =>
    ['skill-builder', sessionId, 'files', path] as const,
}

export function useSkillBuilderSessions(params?: SkillBuilderSessionListParams) {
  return useQuery({
    queryKey: skillBuilderKeys.list(params),
    queryFn: () => skillBuilderApi.list(params),
    staleTime: 15_000,
  })
}

export function useSkillBuilderSession(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: skillBuilderKeys.detail(sessionId),
    queryFn: () => skillBuilderApi.get(requireQueryId(sessionId, 'sessionId')),
    enabled: !!sessionId,
  })
}

export function useSkillBuilderFiles(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: skillBuilderKeys.files(sessionId),
    queryFn: () => skillBuilderApi.files(requireQueryId(sessionId, 'sessionId')),
    enabled: !!sessionId,
  })
}

export function useSkillBuilderFileContent(
  sessionId: string | null | undefined,
  path: string | null,
) {
  return useQuery({
    queryKey: skillBuilderKeys.fileContent(sessionId, path),
    queryFn: () => skillBuilderApi.fileContent(requireQueryId(sessionId, 'sessionId'), path ?? ''),
    enabled: !!sessionId && !!path,
  })
}

export function useStartSkillBuilder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SkillBuilderStartRequest) => skillBuilderApi.start(data),
    onSuccess: (session) => {
      qc.setQueryData(skillBuilderKeys.detail(session.id), session)
      // 让新 session 立即反映到 builder index 列表（staleTime 15s）中。
      qc.invalidateQueries({ queryKey: skillBuilderKeys.lists })
    },
  })
}

/**
 * builder session 启动 + 路由 + 失败 toast 的单一权威实现 — 3 个入口（列表行
 * "编辑"、context bar "通过聊天改进"、builder index/创建 dialog）共用。
 * 成功时移动到 session route 并返回 true。
 */
export function useBuilderSessionLauncher() {
  const router = useRouter()
  const t = useTranslations('skill.builderChat')
  const startBuilder = useStartSkillBuilder()

  async function launch(payload: SkillBuilderStartRequest): Promise<boolean> {
    // 中央双重提交 guard — 与各入口自身的 disabled 无关，阻止重复创建 session。
    if (startBuilder.isPending) return false
    const originHref = window.location.pathname + window.location.search
    try {
      const session = await startBuilder.mutateAsync(payload)
      // start 很慢时，如果用户已经移动到其他页面，则不要通过强制导航
      // 抢走编辑上下文 — session 会保留在 builder index 历史中。
      if (window.location.pathname + window.location.search === originHref) {
        router.push(`/skills/builder/${session.id}`)
      }
      return true
    } catch {
      toast.error(t('startFailed'))
      return false
    }
  }

  return {
    pending: startBuilder.isPending,
    startCreate: (request: string) => launch({ mode: 'create', user_request: request }),
    startImprove: (skillId: string) =>
      launch({
        mode: 'improve',
        user_request: t('improveDefaultRequest'),
        source_skill_id: skillId,
      }),
  }
}

export function useValidateSkillBuilderSession(sessionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (draft: SkillDraftPackage) => skillBuilderApi.validate(sessionId, draft),
    onSuccess: (session) => {
      qc.setQueryData(skillBuilderKeys.detail(session.id), session)
    },
  })
}

export function useConfirmSkillBuilderSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => skillBuilderApi.confirm(sessionId),
    onSuccess: (skill) => {
      invalidateInstalledSkillCaches(qc, skill.id)
    },
  })
}

function invalidateInstalledSkillCaches(
  qc: ReturnType<typeof useQueryClient>,
  skillId: string,
): void {
  qc.invalidateQueries({ queryKey: skillQueryKeys.all })
  qc.invalidateQueries({ queryKey: skillQueryKeys.detail(skillId) })
  qc.invalidateQueries({ queryKey: skillQueryKeys.files(skillId) })
  qc.invalidateQueries({ queryKey: skillQueryKeys.content(skillId) })
  // finalize/confirm 也会改变 session 状态（completed）— 同步 index 列表 badge。
  qc.invalidateQueries({ queryKey: skillBuilderKeys.lists })
}
