import { AiModelSettings } from '@/features/ai-settings/ai-model-settings'
import { SettingsShell } from '../_components/settings-shell'

export default function Page() {
  return (
    <SettingsShell>
      <AiModelSettings />
    </SettingsShell>
  )
}
