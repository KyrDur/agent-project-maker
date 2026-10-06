'use client'

import { Loader2, Save } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'

type SkillDetailPackageFooterProps = {
  readonly savePending: boolean
  readonly saveDisabled: boolean
  readonly sizeBytes: number
  readonly version: string | null
  readonly usedByCount: number
  readonly onSave: () => void
}

/**
 * 源标签页(包) 页脚 — 保存 + 包摘要（大小·版本·连接数）。
 * 删除/导出/关闭由工作室设置标签页·行菜单负责 (Phase 2 D1)。
 */
export function SkillDetailPackageFooter({
  savePending,
  saveDisabled,
  sizeBytes,
  version,
  usedByCount,
  onSave,
}: SkillDetailPackageFooterProps) {
  const t = useTranslations('skill.detailDialog')

  return (
    <>
      <span className="moldy-ui-micro mr-auto text-muted-foreground">
        {t('usedBy', {
          bytes: sizeBytes,
          version: version ?? '—',
          count: usedByCount,
        })}
      </span>
      <Button onClick={onSave} disabled={saveDisabled}>
        {savePending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
        {t('saveFile')}
      </Button>
    </>
  )
}
