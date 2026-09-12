'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormFieldShell } from '@/components/shared/form-field-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
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
        onSave({
          ...draft,
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
        description={t('manualReview')}
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
