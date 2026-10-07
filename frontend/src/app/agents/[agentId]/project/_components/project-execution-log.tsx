'use client'

import { useTranslations } from 'next-intl'
import {
  evidenceRecord,
  evidenceRecords,
  executionLog,
  type EvidenceRecord,
} from '../_lib/execution-log'

/** Render the retained data as fields and prose, preserving its actual values. */
export function ProjectEvidenceValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const t = useTranslations('agentProject.executionLog')
  if (value === undefined) return <span className="text-muted-foreground">{t('missing')}</span>
  if (value === null) return <span className="text-muted-foreground">{t('emptyValue')}</span>
  if (typeof value === 'string') {
    let parsed: unknown
    try {
      parsed = JSON.parse(value)
    } catch {
      /* Plain model text is displayed as returned. */
    }
    if (parsed !== null && typeof parsed === 'object')
      return <ProjectEvidenceValue value={parsed} depth={depth} />
    return <span className="whitespace-pre-wrap break-words">{value || t('emptyText')}</span>
  }
  if (typeof value === 'boolean') return <span>{t(value ? 'yes' : 'no')}</span>
  if (typeof value !== 'object') return <span>{String(value)}</span>
  if (depth >= 6)
    return (
      <details>
        <summary>{t('nestedData')}</summary>
        <pre className="whitespace-pre-wrap break-words">{JSON.stringify(value, null, 2)}</pre>
      </details>
    )
  if (Array.isArray(value))
    return value.length ? (
      <ul className="list-disc space-y-1 pl-5">
        {value.map((item, index) => (
          <li key={index}>
            <ProjectEvidenceValue value={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="text-muted-foreground">{t('emptyList')}</span>
    )
  const entries = Object.entries(value)
  return entries.length ? (
    <dl className="space-y-2">
      {entries.map(([key, item]) => (
        <div key={key} className="space-y-1">
          <dt className="font-medium">{t.has(`fields.${key}`) ? t(`fields.${key}`) : key}</dt>
          <dd className="pl-3">
            <ProjectEvidenceValue value={item} depth={depth + 1} />
          </dd>
        </div>
      ))}
    </dl>
  ) : (
    <span className="text-muted-foreground">{t('emptyObject')}</span>
  )
}

function ToolLog({ request, event }: { request?: EvidenceRecord; event?: EvidenceRecord }) {
  const t = useTranslations('agentProject.executionLog')
  const errorT = useTranslations('agentProject.executionErrors')
  return (
    <article className="space-y-2 rounded-lg border border-border p-3">
      <h5 className="font-medium">
        {t('toolCall')} · {String(event?.name ?? request?.name ?? t('missing'))}
      </h5>
      {event?.order != null && (
        <p className="text-xs text-muted-foreground">
          {t('toolOrder', { number: String(event.order) })}
        </p>
      )}
      <div>
        <p className="font-medium">{t('arguments')}</p>
        <ProjectEvidenceValue value={event?.arguments ?? request?.args} />
      </div>
      {event ? (
        <>
          {event.error != null && (
            <p className="text-destructive">
              {t('toolFailure')}:{' '}
              {errorT.has(String(event.error)) ? errorT(String(event.error)) : String(event.error)}
            </p>
          )}
          <div>
            <p className="font-medium">{t('toolResult')}</p>
            <ProjectEvidenceValue value={event.output} />
          </div>
          {event.state_before !== undefined &&
            event.state_after !== undefined &&
            JSON.stringify(event.state_before) !== JSON.stringify(event.state_after) && (
              <details>
                <summary>{t('stateChange')}</summary>
                <p className="mt-2 font-medium">{t('before')}</p>
                <ProjectEvidenceValue value={event.state_before} />
                <p className="mt-2 font-medium">{t('after')}</p>
                <ProjectEvidenceValue value={event.state_after} />
              </details>
            )}
          {event.latency_ms != null && (
            <p className="text-xs text-muted-foreground">
              {t('latency', { ms: String(event.latency_ms) })}
            </p>
          )}
        </>
      ) : (
        <p className="text-muted-foreground">{t('toolResultMissing')}</p>
      )}
    </article>
  )
}

function ModelLog({ call, number }: { call: EvidenceRecord; number: number }) {
  const t = useTranslations('agentProject.executionLog')
  const model = evidenceRecord(call.model)
  const status = typeof call.status === 'string' ? call.status : 'unknown'
  const messages = Array.isArray(call.input_messages)
    ? call.input_messages.flatMap(evidenceRecords)
    : []
  return (
    <div className="space-y-2">
      <h4 className="font-semibold">
        {t('modelCall', { number })} · {String(model.model_name ?? t('missing'))}
      </h4>
      <p className="text-sm text-muted-foreground">
        {t.has(`statuses.${status}`) ? t(`statuses.${status}`) : status}
      </p>
      {call.error != null && <p className="text-destructive">{String(call.error)}</p>}
      <details>
        <summary>{t('modelInput', { count: messages.length })}</summary>
        {messages.length ? (
          <ol className="mt-2 space-y-3">
            {messages.map((message, index) => {
              const role = typeof message.type === 'string' ? message.type : 'unknown'
              return (
                <li key={index}>
                  <p className="font-medium">
                    {t.has(`roles.${role}`) ? t(`roles.${role}`) : role}
                  </p>
                  <ProjectEvidenceValue value={message.content} />
                </li>
              )
            })}
          </ol>
        ) : (
          <p>{t('missing')}</p>
        )}
      </details>
      <details>
        <summary>{t('parameters')}</summary>
        <ProjectEvidenceValue value={call.invocation_parameters ?? model.parameters} />
      </details>
    </div>
  )
}

export function ProjectExecutionLog({
  evidence: raw,
  graded = false,
}: {
  evidence: unknown
  graded?: boolean
}) {
  const t = useTranslations('agentProject.executionLog')
  const { evidence, calls, otherTools } = executionLog(raw)
  const judges = evidenceRecords(evidence.judge_calls)
  const reason = typeof evidence.termination_reason === 'string' ? evidence.termination_reason : ''
  return (
    <div className="mt-3 space-y-4 text-sm">
      <p className="text-muted-foreground">{t('description')}</p>
      <ol className="space-y-4" aria-label={t('title')}>
        {calls.map(({ call, returns, tools }, index) => (
          <li key={index} className="space-y-3 border-l-2 border-border pl-4">
            <ModelLog call={call} number={index + 1} />
            {returns.map((response, number) => (
              <div key={number}>
                <p className="font-medium">{t('modelReturn')}</p>
                {response.content === '' && evidenceRecords(response.tool_calls).length ? (
                  <p>{t('toolRequestOnly')}</p>
                ) : (
                  <ProjectEvidenceValue value={response.content} />
                )}
              </div>
            ))}
            {!returns.length && <p className="text-muted-foreground">{t('returnMissing')}</p>}
            {tools.map(({ request, event }, number) => (
              <ToolLog key={number} request={request} event={event} />
            ))}
          </li>
        ))}
      </ol>
      {!calls.length && <p className="text-muted-foreground">{t('modelHistoryMissing')}</p>}
      {!!otherTools.length && (
        <div className="space-y-2">
          <h4 className="font-medium">{t('otherTools')}</h4>
          <p className="text-muted-foreground">{t('otherToolsHelp')}</p>
          {otherTools.map((event, index) => (
            <ToolLog key={index} event={event} />
          ))}
        </div>
      )}
      {!evidenceRecords(evidence.tool_trace).length && (
        <p className="text-muted-foreground">{t('noToolExecution')}</p>
      )}
      <div className="space-y-2">
        <h4 className="font-semibold">{t('finalReply')}</h4>
        <ProjectEvidenceValue value={evidence.output} />
      </div>
      <p>
        <strong>{t('termination')}: </strong>
        {reason
          ? t.has(`terminations.${reason}`)
            ? t(`terminations.${reason}`)
            : reason
          : t('missing')}
      </p>
      {evidence.final_state !== undefined && (
        <details>
          <summary>{t('finalState')}</summary>
          <ProjectEvidenceValue value={evidence.final_state} />
        </details>
      )}
      {graded && (
        <div className="space-y-3">
          <h4 className="font-semibold">{t('judge')}</h4>
          {!judges.length && <p className="text-muted-foreground">{t('judgeHistoryMissing')}</p>}
          {judges.map((call, index) => (
            <article key={index} className="space-y-2 rounded-lg border border-border p-3">
              <p className="font-medium">
                {t('judgeCall', { number: index + 1 })} ·{' '}
                {String(evidenceRecord(call.model).model_name ?? t('missing'))}
              </p>
              <p>
                {t.has(`statuses.${String(call.status)}`)
                  ? t(`statuses.${String(call.status)}`)
                  : String(call.status ?? t('missing'))}
              </p>
              {call.error != null && <p className="text-destructive">{String(call.error)}</p>}
              <details>
                <summary>{t('judgeInput')}</summary>
                <ProjectEvidenceValue
                  value={{ instruction: call.instruction, input: call.input }}
                />
              </details>
              <h5 className="font-medium">{t('judgeReturn')}</h5>
              <ProjectEvidenceValue value={call.output} />
            </article>
          ))}
        </div>
      )}
      <details>
        <summary>{t('technicalDetails')}</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words text-xs">
          {JSON.stringify(raw, null, 2)}
        </pre>
      </details>
    </div>
  )
}
