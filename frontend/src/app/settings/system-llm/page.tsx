'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CredentialCreateModal } from '@/components/credential/credential-create-modal'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { FormFieldShell } from '@/components/shared/form-field-shell'
import { PageHeader } from '@/components/shared/page-header'
import { SettingsSectionCard } from '@/components/shared/settings-section-card'
import { useSession } from '@/lib/auth/session'
import { useCredentialTypes, useSystemCredentials } from '@/lib/hooks/use-credentials'
import { useDiscoverModels } from '@/lib/hooks/use-models'
import {
  useSystemLlmSettings,
  useTestSystemLlmSetting,
  useUpdateSystemLlmSetting,
} from '@/lib/hooks/use-system-llm-settings'
import type { Credential, CredentialDefinition } from '@/lib/types/credential'
import type { DiscoveredModel } from '@/lib/types/model'
import {
  SYSTEM_LLM_CREDENTIAL_KEYS,
  type SystemLlmSettingOut,
} from '@/lib/types/system-llm-setting'
import { getProviderLabel } from '@/lib/utils/provider'
import { SettingsShell } from '../_components/settings-shell'

const NONE_VALUE = '__none__'

const LLM_CREDENTIAL_KEYS = SYSTEM_LLM_CREDENTIAL_KEYS as readonly string[]
const LLM_CREDENTIAL_KEY_SET = new Set<string>(LLM_CREDENTIAL_KEYS)

function providerSortIndex(key: string) {
  const index = LLM_CREDENTIAL_KEYS.indexOf(key as (typeof SYSTEM_LLM_CREDENTIAL_KEYS)[number])
  return index === -1 ? Number.MAX_SAFE_INTEGER : index
}

function defaultProviderKey(providerOptions: CredentialDefinition[]) {
  return providerOptions.find((p) => p.key !== 'anthropic')?.key ?? providerOptions[0]?.key ?? null
}

function providerLabel(provider: string | null | undefined, definitions: CredentialDefinition[]) {
  if (!provider) return null
  return definitions.find((d) => d.key === provider)?.display_name ?? getProviderLabel(provider)
}

/**
 * AI Models — operators pick a System Credential + model for each platform
 * role slot. super_user only: Builder, Agent Project evaluation generation,
 * judge/optimizer and image generation read these at runtime. Credential
 * registration reuses the encrypted System Credentials flow.
 *
 * Backend enforces `require_super_user` on every endpoint; this guard hides
 * the chrome and avoids 403 noise for users who land via a bookmarked URL.
 */
export default function SystemLlmSettingsPage() {
  const t = useTranslations('systemLlm')
  const router = useRouter()
  const { data: user, isPending } = useSession()
  const denied = !isPending && !!user && !user.is_super_user

  useEffect(() => {
    if (denied) router.replace('/')
  }, [denied, router])

  if (isPending || denied) {
    return (
      <SettingsShell>
        <p className="text-sm text-muted-foreground">{t('loading')}</p>
      </SettingsShell>
    )
  }

  return (
    <SettingsShell>
      <SystemLlmSettingsPageInner />
    </SettingsShell>
  )
}

function SystemLlmSettingsPageInner() {
  const t = useTranslations('systemLlm')
  const { data: settings, isLoading } = useSystemLlmSettings()
  const { data: credentials } = useSystemCredentials()
  const { data: credentialTypes } = useCredentialTypes()

  const providerOptions = useMemo(() => {
    return (credentialTypes ?? [])
      .filter((d) => d.category === 'llm' && LLM_CREDENTIAL_KEY_SET.has(d.key))
      .sort((a, b) => providerSortIndex(a.key) - providerSortIndex(b.key))
  }, [credentialTypes])

  const llmCredentials = useMemo(
    () => (credentials ?? []).filter((c) => LLM_CREDENTIAL_KEYS.includes(c.definition_key)),
    [credentials],
  )

  const platformSettings = useMemo(
    () => (settings ?? []).filter((setting) => setting.role !== 'image'),
    [settings],
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t('title')} description={t('description')} />

      <div className="moldy-status-surface moldy-status-warn rounded-lg p-3 text-xs">
        <p className="flex items-center gap-2 font-medium">
          <SlidersHorizontal className="size-3.5" />
          {t('operatorOnly.title')}
        </p>
        <p className="moldy-status-muted-text mt-1">{t('operatorOnly.description')}</p>
      </div>

      {isLoading || !settings || !credentialTypes ? (
        <p className="text-sm text-muted-foreground">{t('loading')}</p>
      ) : (
        <div className="grid gap-4">
          <QuickSetupCard
            settings={platformSettings}
            credentials={llmCredentials}
            providerOptions={providerOptions}
          />
          {platformSettings.map((setting) => (
            <SlotCard
              key={setting.role}
              setting={setting}
              credentials={llmCredentials}
              providerOptions={providerOptions}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function QuickSetupCard({
  settings,
  credentials,
  providerOptions,
}: {
  settings: SystemLlmSettingOut[]
  credentials: Credential[]
  providerOptions: CredentialDefinition[]
}) {
  const t = useTranslations('systemLlm')
  const update = useUpdateSystemLlmSetting()
  const test = useTestSystemLlmSetting()
  const discover = useDiscoverModels()
  const [createOpen, setCreateOpen] = useState(false)
  const configured = settings.find((s) => s.provider && s.credential_id && s.model_name)
  const initialProvider =
    configured?.provider && providerOptions.some((option) => option.key === configured.provider)
      ? configured.provider
      : defaultProviderKey(providerOptions)
  const [provider, setProvider] = useState<string | null>(initialProvider)
  const [credentialId, setCredentialId] = useState<string | null>(
    configured?.credential_id ?? null,
  )
  const [modelName, setModelName] = useState<string | null>(configured?.model_name ?? null)
  const [models, setModels] = useState<DiscoveredModel[]>([])

  const compatibleCredentials = useMemo(
    () => credentials.filter((c) => c.definition_key === provider),
    [credentials, provider],
  )
  const selectedCredential = compatibleCredentials.find((c) => c.id === credentialId)
  const selectedProviderLabel = providerLabel(provider, providerOptions)

  function loadModels(id: string) {
    discover.mutate(id, {
      onSuccess: (list) => setModels(list),
      onError: (e) => toast.error(e instanceof Error ? e.message : t('toast.loadModelsFailed')),
    })
  }

  function handleProviderChange(nextProvider: string | null) {
    if (!nextProvider) return
    setProvider(nextProvider)
    setCredentialId(null)
    setModelName(null)
    setModels([])
  }

  function handleCredentialChange(value: string | null) {
    const id = value === NONE_VALUE || value === null ? null : value
    setCredentialId(id)
    setModelName(null)
    setModels([])
    if (id) loadModels(id)
  }

  const modelOptions = useMemo(() => {
    const names = models.map((m) => m.model_name)
    if (modelName && !names.includes(modelName)) return [modelName, ...names]
    return names
  }, [models, modelName])

  async function testSelectedSetup() {
    if (!provider || !credentialId || !modelName) return
    try {
      const result = await test.mutateAsync({
        provider,
        credential_id: credentialId,
        model_name: modelName,
      })
      if (result.success) {
        toast.success(t('toast.testSucceeded'))
      } else {
        toast.error(result.error?.message ?? t('toast.testFailed'))
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t('toast.testFailed'))
    }
  }

  async function applySimpleSetup() {
    if (!credentialId || !modelName) return
    try {
      await Promise.all(
        settings.map((setting) =>
          update.mutateAsync({
            role: setting.role,
            data: { credential_id: credentialId, model_name: modelName },
          }),
        ),
      )
      toast.success(t('toast.simpleSaved'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t('toast.saveFailed'))
    }
  }

  return (
    <SettingsSectionCard
      title={t('quickSetup.title')}
      description={t('quickSetup.description')}
    >
      <div className="grid gap-4 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end">
        <FormFieldShell id="quick-provider" label={t('provider')}>
          <Select
            value={provider ?? ''}
            onValueChange={handleProviderChange}
            disabled={providerOptions.length === 0}
          >
            <SelectTrigger id="quick-provider" className="w-full">
              <span className="truncate">{selectedProviderLabel ?? t('selectProvider')}</span>
            </SelectTrigger>
            <SelectContent>
              {providerOptions.map((option) => (
                <SelectItem key={option.key} value={option.key}>
                  {option.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormFieldShell>

        <FormFieldShell id="quick-system-credential" label={t('systemCredential')}>
          <Select
            value={credentialId ?? NONE_VALUE}
            onValueChange={handleCredentialChange}
            disabled={!provider || compatibleCredentials.length === 0}
          >
            <SelectTrigger id="quick-system-credential" className="w-full">
              <span className="truncate">{selectedCredential?.name ?? t('selectCredential')}</span>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE_VALUE}>{t('none')}</SelectItem>
              {compatibleCredentials.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {provider && compatibleCredentials.length === 0 && (
            <Button
              type="button"
              variant="link"
              className="h-auto px-0 text-xs"
              onClick={() => setCreateOpen(true)}
            >
              {t('quickSetup.addCredential')}
            </Button>
          )}
        </FormFieldShell>

        <FormFieldShell
          id="quick-system-model"
          label={t('model')}
          actions={
            credentialId ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => loadModels(credentialId)}
                disabled={discover.isPending}
              >
                {discover.isPending ? t('loading') : t('loadModels')}
              </Button>
            ) : null
          }
        >
          <Select
            value={modelName ?? ''}
            onValueChange={(value) => setModelName(value)}
            disabled={!credentialId || modelOptions.length === 0}
          >
            <SelectTrigger id="quick-system-model" className="w-full">
              <span className="truncate">{modelName ?? t('selectModel')}</span>
            </SelectTrigger>
            <SelectContent>
              {modelOptions.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormFieldShell>

        <Button
          type="button"
          variant="outline"
          onClick={testSelectedSetup}
          disabled={!provider || !credentialId || !modelName || test.isPending}
        >
          {test.isPending ? t('testing') : t('test')}
        </Button>

        <Button
          type="button"
          onClick={applySimpleSetup}
          disabled={!provider || !credentialId || !modelName || update.isPending}
        >
          {update.isPending ? t('saving') : t('quickSetup.apply')}
        </Button>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{t('quickSetup.note')}</p>
      <CredentialCreateModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        mode="system"
        presetDefinitionKey={provider ?? undefined}
        initialName={selectedProviderLabel ?? undefined}
        onCreated={(id) => {
          setCredentialId(id)
          setModelName(null)
          setModels([])
          loadModels(id)
        }}
      />
    </SettingsSectionCard>
  )
}

function SlotCard({
  setting,
  credentials,
  providerOptions,
}: {
  setting: SystemLlmSettingOut
  credentials: Credential[]
  providerOptions: CredentialDefinition[]
}) {
  const t = useTranslations('systemLlm')
  const update = useUpdateSystemLlmSetting()
  const test = useTestSystemLlmSetting()
  const discover = useDiscoverModels()
  const [createOpen, setCreateOpen] = useState(false)

  const [provider, setProvider] = useState<string | null>(
    setting.provider ?? defaultProviderKey(providerOptions),
  )
  const [credentialId, setCredentialId] = useState<string | null>(setting.credential_id)
  const [modelName, setModelName] = useState<string | null>(setting.model_name)
  const [models, setModels] = useState<DiscoveredModel[]>([])

  const compatibleCredentials = useMemo(
    () => credentials.filter((c) => c.definition_key === provider),
    [credentials, provider],
  )
  const selectedCredential = compatibleCredentials.find((c) => c.id === credentialId)
  const selectedProviderLabel = providerLabel(provider, providerOptions)

  function loadModels(id: string) {
    discover.mutate(id, {
      onSuccess: (list) => setModels(list),
      onError: (e) => toast.error(e instanceof Error ? e.message : t('toast.loadModelsFailed')),
    })
  }

  function handleProviderChange(nextProvider: string | null) {
    if (!nextProvider) return
    setProvider(nextProvider)
    setCredentialId(null)
    setModelName(null)
    setModels([])
  }

  function handleCredentialChange(value: string | null) {
    const id = value === NONE_VALUE || value === null ? null : value
    setCredentialId(id)
    setModelName(null)
    setModels([])
    if (id) loadModels(id)
  }

  // Discovered models, ensuring the currently-saved model stays selectable
  // even before the operator re-runs discovery.
  const modelOptions = useMemo(() => {
    const names = models.map((m) => m.model_name)
    if (modelName && !names.includes(modelName)) return [modelName, ...names]
    return names
  }, [models, modelName])

  const modelLabels = useMemo(() => {
    const map = new Map<string, string>()
    models.forEach((m) => map.set(m.model_name, m.display_name))
    return map
  }, [models])
  const selectedCredentialName = selectedCredential?.name ?? setting.credential_name
  const selectedModelLabel = modelName ? (modelLabels.get(modelName) ?? modelName) : null

  const dirty = credentialId !== setting.credential_id || modelName !== setting.model_name
  const canSave = dirty && (credentialId === null || !!modelName)

  async function testSelectedSetup() {
    if (!provider || !credentialId || !modelName) return
    try {
      const result = await test.mutateAsync({
        provider,
        credential_id: credentialId,
        model_name: modelName,
      })
      if (result.success) {
        toast.success(t('toast.testSucceeded'))
      } else {
        toast.error(result.error?.message ?? t('toast.testFailed'))
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t('toast.testFailed'))
    }
  }

  async function handleSave() {
    try {
      await update.mutateAsync({
        role: setting.role,
        data: { credential_id: credentialId, model_name: modelName },
      })
      toast.success(t('toast.saved', { role: t(`roles.${setting.role}.label`) }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t('toast.saveFailed'))
    }
  }

  return (
    <SettingsSectionCard
      title={t(`roles.${setting.role}.label`)}
      description={t(`roles.${setting.role}.description`)}
      actions={
        setting.configured ? (
          <Badge variant="default">{t('configured')}</Badge>
        ) : (
          <Badge variant="outline">{t('notConfigured')}</Badge>
        )
      }
    >
      <div className="space-y-4">
        <div className="grid gap-2 rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">{t('provider')}</span>
            <span className="font-medium text-foreground">{selectedProviderLabel ?? t('none')}</span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">{t('credential')}</span>
            <span className="font-medium text-foreground">
              {selectedCredentialName ?? t('none')}
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">{t('model')}</span>
            <span className="font-mono text-xs text-foreground">
              {selectedModelLabel ?? t('none')}
            </span>
          </div>
        </div>

        <FormFieldShell id={`${setting.role}-provider`} label={t('provider')}>
          <Select
            value={provider ?? ''}
            onValueChange={handleProviderChange}
            disabled={providerOptions.length === 0}
          >
            <SelectTrigger id={`${setting.role}-provider`} className="w-full">
              <span className="truncate">{selectedProviderLabel ?? t('selectProvider')}</span>
            </SelectTrigger>
            <SelectContent>
              {providerOptions.map((option) => (
                <SelectItem key={option.key} value={option.key}>
                  {option.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormFieldShell>

        <FormFieldShell
          id={`${setting.role}-credential`}
          label={t('systemCredential')}
          actions={
            provider ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => setCreateOpen(true)}>
                {t('quickSetup.addCredential')}
              </Button>
            ) : null
          }
        >
          <Select
            value={credentialId ?? NONE_VALUE}
            onValueChange={handleCredentialChange}
            disabled={!provider || compatibleCredentials.length === 0}
          >
            <SelectTrigger id={`${setting.role}-credential`} className="w-full">
              <span className="truncate">{selectedCredentialName ?? t('selectCredential')}</span>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE_VALUE}>{t('none')}</SelectItem>
              {compatibleCredentials.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {provider && compatibleCredentials.length === 0 && (
            <p className="text-xs text-muted-foreground">{t('emptyCredentials')}</p>
          )}
        </FormFieldShell>

        <FormFieldShell
          id={`${setting.role}-model`}
          label={t('model')}
          actions={
            credentialId ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => loadModels(credentialId)}
                disabled={discover.isPending}
              >
                {discover.isPending ? t('loading') : t('loadModels')}
              </Button>
            ) : null
          }
        >
          <Select
            value={modelName ?? ''}
            onValueChange={(value) => setModelName(value)}
            disabled={!credentialId || modelOptions.length === 0}
          >
            <SelectTrigger id={`${setting.role}-model`} className="w-full">
              <span className="truncate">{selectedModelLabel ?? t('selectModel')}</span>
            </SelectTrigger>
            <SelectContent>
              {modelOptions.map((name) => (
                <SelectItem key={name} value={name}>
                  {modelLabels.get(name) ?? name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!credentialId ? (
            <p className="text-xs text-muted-foreground">{t('selectCredentialFirst')}</p>
          ) : discover.isError ? (
            <p className="text-xs text-destructive">{t('modelLoadFailed')}</p>
          ) : !discover.isPending && modelOptions.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t('noModels')}</p>
          ) : null}
        </FormFieldShell>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {setting.base_url && (
            <span>
              {t('baseUrl')} <span className="font-mono">{setting.base_url}</span>
            </span>
          )}
        </div>
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={testSelectedSetup}
          disabled={!provider || !credentialId || !modelName || test.isPending}
        >
          {test.isPending ? t('testing') : t('test')}
        </Button>
        <Button onClick={handleSave} disabled={!canSave || update.isPending}>
          {update.isPending ? t('saving') : t('save')}
        </Button>
      </div>
      <CredentialCreateModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        mode="system"
        presetDefinitionKey={provider ?? undefined}
        initialName={selectedProviderLabel ?? undefined}
        onCreated={(id) => {
          setCredentialId(id)
          setModelName(null)
          setModels([])
          loadModels(id)
        }}
      />
    </SettingsSectionCard>
  )
}
