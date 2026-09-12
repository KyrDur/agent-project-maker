'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormFieldShell } from '@/components/shared/form-field-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ProjectSelect } from './project-select'
import type { EvaluationCase } from '../_lib/agent-project-types'

export function ProjectCaseEditor({
  initial,
  busy,
  onSave,
  onCancel,
}: {
  initial: EvaluationCase
  busy: boolean
  onSave: (value: EvaluationCase) => void
  onCancel: () => void
}) {
  const t = useTranslations('agentProject')
  const [draft, setDraft] = useState(initial)
  const [mockText, setMockText] = useState(JSON.stringify(initial.mock_tool_data ?? {}, null, 2))
  const [contextText, setContextText] = useState(JSON.stringify(initial.context, null, 2))
  const [jsonError, setJsonError] = useState(false)
  const [required, setRequired] = useState(initial.expected.required_tools.join(', '))
  const [forbidden, setForbidden] = useState(initial.expected.forbidden_tools.join(', '))
  const [tags, setTags] = useState(initial.tags.join(', '))
  const split = (value: string) =>
    value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
  return (
    <form
      className="mt-4 space-y-4"
      onSubmit={(event) => {
        event.preventDefault()
        let mocks: unknown
        let context: unknown
        try {
          mocks = JSON.parse(mockText)
          context = JSON.parse(contextText)
          if (!mocks || typeof mocks !== 'object' || Array.isArray(mocks)) throw new Error()
          if (
            Object.entries(mocks).some(
              ([name, value]) =>
                !/^[a-zA-Z0-9_-]{1,64}$/.test(name) ||
                !value ||
                typeof value !== 'object' ||
                Array.isArray(value),
            )
          )
            throw new Error()
          if (
            !Array.isArray(context) ||
            context.some(
              (item: unknown) =>
                !item ||
                typeof item !== 'object' ||
                !('role' in item) ||
                !('content' in item) ||
                !['user', 'assistant'].includes(String(item.role)) ||
                typeof item.content !== 'string',
            )
          )
            throw new Error()
        } catch {
          setJsonError(true)
          return
        }
        setJsonError(false)
        onSave({
          ...draft,
          mock_tool_data: mocks as EvaluationCase['mock_tool_data'],
          context: context as EvaluationCase['context'],
          tags: split(tags),
          expected: {
            ...draft.expected,
            required_tools: split(required),
            forbidden_tools: split(forbidden),
          },
        })
      }}
    >
      <FormFieldShell id="case-name" label={t('caseName')}>
        <Input
          id="case-name"
          required
          maxLength={200}
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
      </FormFieldShell>
      <FormFieldShell id="case-input" label={t('caseInput')}>
        <Textarea
          id="case-input"
          required
          maxLength={10000}
          value={draft.input}
          onChange={(e) => setDraft({ ...draft, input: e.target.value })}
        />
      </FormFieldShell>
      <FormFieldShell
        id="case-expected"
        label={t('expectedBehavior')}
        description={t('semanticExpected')}
      >
        <Textarea
          id="case-expected"
          maxLength={10000}
          value={draft.expected.answer ?? ''}
          onChange={(e) =>
            setDraft({ ...draft, expected: { ...draft.expected, answer: e.target.value || null } })
          }
        />
      </FormFieldShell>
      <FormFieldShell id="case-exact" label={t('exactAnswer')}>
        <Textarea
          id="case-exact"
          maxLength={10000}
          value={draft.expected.exact_answer ?? ''}
          onChange={(e) =>
            setDraft({
              ...draft,
              expected: { ...draft.expected, exact_answer: e.target.value || null },
            })
          }
        />
      </FormFieldShell>
      <FormFieldShell id="case-required" label={t('requiredTools')}>
        <Input id="case-required" value={required} onChange={(e) => setRequired(e.target.value)} />
      </FormFieldShell>
      <FormFieldShell id="case-forbidden" label={t('forbiddenTools')}>
        <Input
          id="case-forbidden"
          value={forbidden}
          onChange={(e) => setForbidden(e.target.value)}
        />
      </FormFieldShell>
      <FormFieldShell id="case-handoff" label={t('expectedHandoff')}>
        <Input
          id="case-handoff"
          maxLength={100}
          value={draft.expected.handoff ?? ''}
          onChange={(e) =>
            setDraft({ ...draft, expected: { ...draft.expected, handoff: e.target.value || null } })
          }
        />
      </FormFieldShell>
      <FormFieldShell id="case-tags" label={t('tags')}>
        <Input id="case-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
      </FormFieldShell>
      <ProjectSelect
        label={t('formatRule')}
        value={draft.expected.format_rule ?? 'none'}
        options={[
          { value: 'none', label: t('noFormatRule') },
          { value: 'json_object', label: t('jsonObject') },
          { value: 'json_array', label: t('jsonArray') },
        ]}
        onChange={(value) =>
          setDraft({
            ...draft,
            expected: {
              ...draft.expected,
              format_rule: value === 'json_object' || value === 'json_array' ? value : null,
            },
          })
        }
      />
      <FormFieldShell id="case-context" label={t('contextJson')}>
        <Textarea
          id="case-context"
          maxLength={100000}
          value={contextText}
          onChange={(e) => setContextText(e.target.value)}
        />
      </FormFieldShell>
      <FormFieldShell id="case-mocks" label={t('mockData')} description={t('mockDataHelp')}>
        <Textarea
          id="case-mocks"
          maxLength={100000}
          value={mockText}
          onChange={(e) => setMockText(e.target.value)}
        />
      </FormFieldShell>
      {jsonError && <p role="alert">{t('invalidCaseJson')}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {t('saveCase')}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t('cancel')}
        </Button>
      </div>
    </form>
  )
}
