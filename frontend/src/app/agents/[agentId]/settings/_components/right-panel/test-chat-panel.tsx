'use client'

import { useCallback, useState, useMemo } from 'react'
import { MessageSquareIcon } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { AuiConfig, AssistantRuntimeProvider } from '@assistant-ui/react'
import { HiTLContext } from '@/lib/chat/hitl-context'
import { useChatRuntime } from '@/lib/chat/use-chat-runtime'
import type { Message } from '@/lib/types'
import { ALL_TOOLKIT, createMoldyChatTools } from '@/lib/chat/tool-ui-registry'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api/client'
import { agentQueryKeys } from '@/lib/query-keys/agents'
import { streamChat, streamStartConversation, type StreamChatOptions } from '@/lib/sse/stream-chat'
import { AssistantThread } from '@/components/chat/assistant-thread'

interface TestChatPanelProps {
  agentId: string
  agentName: string
  agentImageUrl?: string | null
}

/** Uses saved Agent configuration and the same durable chat/approval endpoints as production. */
export function TestChatPanel({ agentId, agentName, agentImageUrl }: TestChatPanelProps) {
  const [conversationId, setConversationId] = useState<string>()
  const config = AuiConfig({ tools: createMoldyChatTools(ALL_TOOLKIT, conversationId) })
  const readiness = useQuery({
    queryKey: agentQueryKeys.readiness(agentId),
    queryFn: () =>
      apiFetch<{ ready: boolean; code: string | null }>(`/api/agents/${agentId}/runtime-readiness`),
    staleTime: 0,
  })
  const t = useTranslations('agent.settings')
  const [localMessages, setLocalMessages] = useState<Message[]>([])

  const onMessagesCommit = useCallback((msgs: Message[]) => {
    setLocalMessages((prev) => [...prev, ...msgs])
  }, [])

  const streamFn = useCallback(
    (content: string, signal: AbortSignal, options?: StreamChatOptions) => {
      const transportOptions = {
        ...options,
        onConversationId: (id: string) => {
          setConversationId(id)
          options?.onConversationId?.(id)
        },
      }
      return conversationId
        ? streamChat(conversationId, content, signal, transportOptions)
        : streamStartConversation(agentId, content, signal, transportOptions)
    },
    [agentId, conversationId],
  )

  const { runtime, onResumeDecisions, registerDecision } = useChatRuntime({
    messages: localMessages,
    conversationId,
    streamFn,
    onMessagesCommit,
  })

  const hitlValue = useMemo(
    () => ({ onResumeDecisions, registerDecision }),
    [onResumeDecisions, registerDecision],
  )

  const emptyContent = (
    <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground">
      <MessageSquareIcon className="mb-3 size-8 text-primary-strong/40" />
      <p className="text-sm font-medium">{t('tabs.test')}</p>
    </div>
  )

  return (
    <div className="moldy-card flex h-full min-h-0 flex-col">
      <div className="moldy-status-surface moldy-status-warn border-x-0 border-t-0 px-4 py-2 text-xs">
        {t('testRuntimeInfo')}
      </div>
      {!readiness.data?.ready || readiness.isError ? (
        <div className="space-y-3 p-4" role="status">
          <p>
            {readiness.isPending
              ? t('testChecking')
              : t(
                  readiness.data?.code === 'llm_credential_required'
                    ? 'testMissingCredential'
                    : readiness.data?.code === 'no_model'
                      ? 'testMissingModel'
                      : readiness.data?.code === 'builder_tool_credential'
                        ? 'testMissingToolCredential'
                        : 'testUnavailable',
                )}
          </p>
          <Link className="underline" href="/credentials">
            {t('testConfigureCredentials')}
          </Link>
          {' · '}
          <Link className="underline" href="/models">
            {t('testConfigureModels')}
          </Link>
          {' · '}
          <Link className="underline" href="/tools">
            {t('testConfigureTools')}
          </Link>
          <button className="block underline" onClick={() => void readiness.refetch()}>
            {t('testCheckAgain')}
          </button>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <AssistantRuntimeProvider runtime={runtime} config={config}>
            <HiTLContext.Provider value={hitlValue}>
              <AssistantThread
                agentImageUrl={agentImageUrl}
                agentName={agentName}
                compact
                emptyContent={emptyContent}
              />
            </HiTLContext.Provider>
          </AssistantRuntimeProvider>
        </div>
      )}
    </div>
  )
}
