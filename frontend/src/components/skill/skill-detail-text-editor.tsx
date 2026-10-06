'use client'

import { useState } from 'react'
import { Loader2, Save } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useSkillContent, useUpdateSkillContent } from '@/lib/hooks/use-skills'

import type { SkillDetailTabRender } from './skill-detail-tab-shell'

/**
 * 源标签页(文本) 编辑器 — 只负责保存(=修订版)。删除/凭证由
 * 工作室设置标签页负责 (Phase 2 D1)。
 */
export function TextSkillEditor({
  children,
  skillId,
}: {
  readonly children: SkillDetailTabRender
  readonly skillId: string
}) {
  const t = useTranslations('skill.detailDialog')
  const { data: textContent } = useSkillContent(skillId, true)
  const update = useUpdateSkillContent()
  const [editor, setEditor] = useState('')
  const [seeded, setSeeded] = useState<string | undefined>(undefined)

  // 服务器内容变化时（例：版本标签页回滚后 stale 缓存 → refetch 落地）
  // 重新初始值 — hydrate-once 会锁住回滚前的缓存，导致界面看起来"回滚没生效"，
  // 并在保存时创建新修订版把回滚撤销 (R5)。但 dirty draft 需保护：
  // 如果用户已偏离最后一次初始值，则不覆盖编辑内容。
  if (textContent?.content !== undefined && textContent.content !== seeded) {
    const previousSeed = seeded
    setSeeded(textContent.content)
    if (previousSeed === undefined || editor === previousSeed) {
      setEditor(textContent.content)
    }
  }

  async function handleSave() {
    try {
      await update.mutateAsync({ id: skillId, data: { content: editor } })
      toast.success(t('saved'))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('saveFailed'))
    }
  }

  return children({
    body: (
      <>
        <Textarea
          value={editor}
          rows={20}
          className="h-full min-h-[400px] font-mono text-xs"
          onChange={(event) => setEditor(event.target.value)}
        />
      </>
    ),
    footer: (
      <>
        <Button onClick={handleSave} disabled={update.isPending}>
          {update.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          {t('save')}
        </Button>
      </>
    ),
  })
}
