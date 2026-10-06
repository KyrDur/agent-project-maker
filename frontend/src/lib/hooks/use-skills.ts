'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { skillsApi } from '@/lib/api/skills'
import { ApiError } from '@/lib/api/errors'
import { skillQueryKeys, type SkillListQueryParams } from '@/lib/query-keys/skills'
import { requiredQueryValue } from './required-query-value'
import type {
  SkillContentUpdateRequest,
  SkillCreateRequest,
  SkillMetadataUpdateRequest,
} from '@/lib/types/skill'

/** Feature-level export adapter for route components. */
export function getSkillExportUrl(skillId: string): string {
  return skillsApi.exportUrl(skillId)
}

/** Treat a skill already deleted in another flow as an idempotent success. */
export function isSkillNotFoundError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

export function useSkills(params?: SkillListQueryParams) {
  return useQuery({
    queryKey: skillQueryKeys.list(params),
    queryFn: () => skillsApi.list(params),
    staleTime: 30_000,
  })
}

export function useSkill(id: string | null | undefined) {
  return useQuery({
    queryKey: skillQueryKeys.detail(id),
    queryFn: () => skillsApi.get(requiredQueryValue(id, 'skill id')),
    enabled: !!id,
    // studio 的 shell·breadcrumb·tab page 三处都订阅同一个 detail，并在每次 tab
    // 切换时 remount — 如果 staleTime 为 0，每次切换都会重新查询 enrichment。
    // mutation 通过 invalidate 更新，因此使用与列表（useSkills）相同的上限是安全的。
    staleTime: 30_000,
  })
}

export function useSkillFiles(id: string | null | undefined) {
  return useQuery({
    queryKey: skillQueryKeys.files(id),
    queryFn: () => skillsApi.listFiles(requiredQueryValue(id, 'skill id')),
    enabled: !!id,
  })
}

export function useSkillContent(id: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: skillQueryKeys.content(id),
    queryFn: () => skillsApi.getContent(requiredQueryValue(id, 'skill id')),
    enabled: !!id && enabled,
  })
}

export function useCreateTextSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SkillCreateRequest) => skillsApi.createText(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: skillQueryKeys.all }),
  })
}

export function useUploadPackageSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => skillsApi.uploadPackage(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: skillQueryKeys.all }),
  })
}

export function useUpdateSkillMetadata() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SkillMetadataUpdateRequest }) =>
      skillsApi.patchMetadata(id, data),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: skillQueryKeys.all })
      qc.invalidateQueries({ queryKey: skillQueryKeys.detail(id) })
    },
  })
}

export function useUpdateSkillContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SkillContentUpdateRequest }) =>
      skillsApi.putContent(id, data),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: skillQueryKeys.all })
      qc.invalidateQueries({ queryKey: skillQueryKeys.detail(id) })
      qc.invalidateQueries({ queryKey: skillQueryKeys.content(id) })
    },
  })
}

export function useDeleteSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => skillsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: skillQueryKeys.all }),
  })
}

export function useSetSkillFile(skillId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      skillsApi.setFile(skillId, path, content),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: skillQueryKeys.all })
      qc.invalidateQueries({ queryKey: skillQueryKeys.detail(skillId) })
      qc.invalidateQueries({ queryKey: skillQueryKeys.files(skillId) })
    },
  })
}

export function useDeleteSkillFile(skillId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (path: string) => skillsApi.deleteFile(skillId, path),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: skillQueryKeys.all })
      qc.invalidateQueries({ queryKey: skillQueryKeys.detail(skillId) })
      qc.invalidateQueries({ queryKey: skillQueryKeys.files(skillId) })
    },
  })
}
