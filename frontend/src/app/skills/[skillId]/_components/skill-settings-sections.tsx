'use client'

import { useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { Download, Trash2, UploadCloud } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog'
import { PublicationBadge } from '@/components/marketplace/badges/publication-badge'
import { Button } from '@/components/ui/button'
import { PublishWizard } from '@/components/marketplace/publish-wizard'
import { SkillCredentialBindingsPanel } from '@/components/skill/skill-credential-bindings-panel'
import { SkillMetadataTab } from '@/components/skill/skill-metadata-tab'
import type { SkillDetailTabSlots } from '@/components/skill/skill-detail-tab-shell'
import { getSkillExportUrl, useDeleteSkill } from '@/lib/hooks/use-skills'
import type { Skill } from '@/lib/types/skill'

/**
 * settings tab（Phase 2 决策 D1）— 保留 mock 5-tab 遗漏的凭据绑定·metadata
 * 编辑，并将 publish/export/delete 从 editor footer 移入本 tab 管理。
 */
export function SkillSettingsSections({ skill }: { readonly skill: Skill }) {
  const t = useTranslations('skill.studio.settings')
  const dialog = useTranslations('skill.detailDialog')
  const actions = useTranslations('skill.actions')
  const router = useRouter()
  const removeSkill = useDeleteSkill()
  const [publishOpen, setPublishOpen] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  async function handleDelete() {
    try {
      await removeSkill.mutateAsync(skill.id)
      toast.success(dialog('deleted'))
      router.push('/skills')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : dialog('deleteFailed'))
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8">
      <SettingsSection title={t('metadataTitle')}>
        <SkillMetadataTab skill={skill}>{renderSettingsSectionSlots}</SkillMetadataTab>
      </SettingsSection>

      <SettingsSection title={t('credentialsTitle')}>
        <SkillCredentialBindingsPanel
          skillId={skill.id}
          emptyFallback={
            <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              {dialog('credentialsEmpty')}
            </div>
          }
        />
      </SettingsSection>

      <SettingsSection title={t('actionsTitle')}>
        <div className="flex flex-wrap items-center gap-2">
          {/* 迁移旧 SkillCard 的 canPublish guard — 已发布 skill 只显示 status badge。 */}
          {!skill.publication_summary?.state ||
          skill.publication_summary.state === 'not_published' ? (
            <Button type="button" variant="outline" onClick={() => setPublishOpen(true)}>
              <UploadCloud className="size-4" />
              {actions('publish')}
            </Button>
          ) : (
            <PublicationBadge summary={skill.publication_summary} />
          )}
          {skill.kind === 'package' ? (
            <Button
              variant="outline"
              render={
                <a
                  href={getSkillExportUrl(skill.id)}
                  download
                  aria-label={dialog('exportPackage')}
                />
              }
            >
              <Download className="size-4" />
              {dialog('exportPackage')}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setConfirmingDelete(true)}
          >
            <Trash2 className="size-4" />
            {dialog('deleteSkill')}
          </Button>
        </div>
        <p className="moldy-ui-micro text-muted-foreground">
          {t('deleteHint', { count: skill.used_by_count })}
        </p>
      </SettingsSection>

      <PublishWizard
        skill={publishOpen ? skill : null}
        open={publishOpen}
        onOpenChange={(open) => setPublishOpen(open)}
      />
      <DeleteConfirmDialog
        open={confirmingDelete}
        onOpenChange={(open) => {
          if (!open) setConfirmingDelete(false)
        }}
        title={t('deleteTitle', { name: skill.name })}
        description={t('deleteDescription', { count: skill.used_by_count })}
        confirmLabel={dialog('deleteSkill')}
        isPending={removeSkill.isPending}
        onConfirm={handleDelete}
      />
    </div>
  )
}

function SettingsSection({
  title,
  children,
}: {
  readonly title: string
  readonly children: ReactNode
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  )
}

/** 将 SkillMetadataTab 的 4-slot 输出平铺到 settings section 中。 */
function renderSettingsSectionSlots(slots: SkillDetailTabSlots): ReactNode {
  return (
    <>
      {slots.body}
      <div className="flex items-center justify-end gap-2">{slots.footer}</div>
      {slots.overlay ?? null}
    </>
  )
}
