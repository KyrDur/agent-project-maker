'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { PartyPopperIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { DialogShell } from '@/components/shared/dialog-shell'
import { useSystemLlmReadiness } from '@/lib/hooks/use-system-llm-settings'
import { useSession } from '@/lib/auth/session'
import { dismissOnboarding, isOnboardingDismissed } from '@/lib/auth/session-flags'
import { useSuperUserWelcomeToast } from './use-super-user-welcome-toast'
import type { User } from '@/lib/types/user'

/**
 * Self-deciding root — reads session and only mounts the inner dialog when
 * onboarding should fire. The Inner component owns its own `open` state and
 * remounts via `key={user.id}` so we never need to sync prop→state in an
 * effect (React 19 anti-pattern, see frontend/AGENTS.md).
 */
export function OnboardingDialog() {
  const { data: user } = useSession()
  const readiness = useSystemLlmReadiness()
  if (!user || !readiness.data || readiness.data.every((role) => role.configured)) return null
  return <OnboardingDialogInner key={user.id} user={user} />
}

function OnboardingDialogInner({ user }: { user: User }) {
  const t = useTranslations('auth.onboarding')
  const router = useRouter()
  // Initial visibility computed once — no effect-driven setState.
  const [open, setOpen] = useState(() => !isOnboardingDismissed())

  useSuperUserWelcomeToast(user)

  function dismiss() {
    dismissOnboarding()
    setOpen(false)
  }

  function handleRegister() {
    dismiss()
    router.push('/settings/ai-models')
  }

  return (
    <DialogShell
      open={open}
      onOpenChange={(v) => (v ? setOpen(true) : dismiss())}
      size="md"
      height="auto"
    >
      <DialogShell.Header
        icon={
          <span className="flex size-9 items-center justify-center rounded-lg bg-status-accent/15 text-status-accent">
            <PartyPopperIcon className="size-5" aria-hidden />
          </span>
        }
        title={t('title')}
        description={t('subtitle')}
      />
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="space-y-6 text-sm">
          <p>{t('body')}</p>
          <div className="rounded-lg border border-border/60 bg-muted/40 p-4 space-y-2">
            <p className="font-medium">{t('providers')}</p>
            <ul className="list-disc pl-5 text-muted-foreground space-y-0.5">
              <li>{t('providerList.openai')}</li>
              <li>{t('providerList.anthropic')}</li>
              <li>{t('providerList.google')}</li>
            </ul>
          </div>
          <p className="text-muted-foreground">{t('encryptedNote')}</p>
        </div>
      </div>
      <DialogShell.Footer>
        <Button variant="ghost" onClick={dismiss}>
          {t('later')}
        </Button>
        <Button onClick={handleRegister}>
          {user.is_super_user ? t('registerPlatform') : t('register')}
        </Button>
      </DialogShell.Footer>
    </DialogShell>
  )
}
