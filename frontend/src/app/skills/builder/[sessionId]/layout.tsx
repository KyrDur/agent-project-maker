import type { ReactNode } from 'react'
import { ScopedIntlProvider } from '@/i18n/scoped-messages'

// builder chat 直接挂载主 chat surface（ChatRuntimeSection），因此需要 `chat`
// namespace — 上级 /skills layout scope（credentials/
// marketplace/skill）中没有（scoped-messages 陷阱：scope 外的 component 会
// 渲染 raw i18n key）。与 agents chat layout 配置相同 + 保留 skill。
const BUILDER_CHAT_MESSAGE_NAMESPACES = ['agent', 'chat', 'model', 'skill', 'usage'] as const

export default function SkillBuilderChatLayout({ children }: { children: ReactNode }) {
  return (
    <ScopedIntlProvider namespaces={BUILDER_CHAT_MESSAGE_NAMESPACES}>{children}</ScopedIntlProvider>
  )
}
