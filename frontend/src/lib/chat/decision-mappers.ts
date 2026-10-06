/**
 * 标准 ``Decision`` 对象 builder——将 HiTL ResumeRequest payload 的 4 种 action type
 * 用统一 helper 生成，而不是内联字面量。可在编译阶段阻止调用处遗漏 type 或错误的
 * 字段组合（例如给 respond 附加 edited_action）。
 *
 * 与 ADR-012 §Decision schema 一一对应。Decision shape 变化时，只需修改本文件一处，
 * 即可统一应用到所有调用方。
 */
import type { Decision } from '@/lib/types'
import type { UserInputOption, UserInputQuestion } from '@/lib/types'

export function toApprove(options?: { sessionScope?: boolean }): Decision {
  // Skill builder AD-4——选择"留出本次会议的剩余时间"时附加 scope:'session'。
  // backend 记录同意后移除该键，只把标准 approve 发送给 middleware。
  return options?.sessionScope ? { type: 'approve', scope: 'session' } : { type: 'approve' }
}

export function toReject(message?: string): Decision {
  return message !== undefined ? { type: 'reject', message } : { type: 'reject' }
}

export function toEdit(editedAction: NonNullable<Decision['edited_action']>): Decision {
  return { type: 'edit', edited_action: editedAction }
}

export function toRespond(message: string): Decision {
  return { type: 'respond', message }
}

export type SerializedUserInputResponse = {
  message: string
  displayText: string
}

type QuestionFlowAnswers = Record<string, string[] | string | null | undefined>

function optionId(option: UserInputOption): string {
  return option.id ?? option.label
}

function optionLabelById(options: UserInputOption[] | undefined, id: string): string {
  return options?.find((option) => optionId(option) === id)?.label ?? id
}

function questionId(question: UserInputQuestion, index: number): string {
  return question.id ?? question.label ?? question.question ?? `question_${index + 1}`
}

function questionLabel(question: UserInputQuestion, index: number): string {
  return question.label ?? question.question ?? question.id ?? `Question ${index + 1}`
}

function normalizeAnswer(value: string[] | string | null | undefined): string[] {
  if (Array.isArray(value)) return value
  if (typeof value === 'string' && value) return [value]
  return []
}

export function serializeQuestionFlowResponse(
  questions: UserInputQuestion[],
  answers: QuestionFlowAnswers,
): SerializedUserInputResponse & {
  summary: Array<{ id: string; label: string; value: string }>
} {
  const answerIds: Record<string, string[]> = {}
  const labels: Record<string, string | string[]> = {}
  const summary: Array<{ id: string; label: string; value: string }> = []

  questions.forEach((question, index) => {
    const id = questionId(question, index)
    const selected = normalizeAnswer(answers[id])
    const selectedLabels = selected.map((value) =>
      question.type === 'text' ? value : optionLabelById(question.options, value),
    )
    answerIds[id] = selected
    labels[id] = question.type === 'multi_select' ? selectedLabels : (selectedLabels[0] ?? '')
    summary.push({
      id,
      label: questionLabel(question, index),
      value: selectedLabels.join(', '),
    })
  })

  return {
    message: JSON.stringify({
      mode: 'question_flow',
      answers: answerIds,
      labels,
    }),
    displayText: summary.map((item) => `${item.label}: ${item.value}`).join(' | '),
    summary,
  }
}

export function serializeOptionListResponse(
  options: UserInputOption[],
  selection: string[] | string | null | undefined,
): SerializedUserInputResponse {
  const selected = normalizeAnswer(selection)
  const labels = selected.map((id) => optionLabelById(options, id))
  return {
    message: JSON.stringify({
      mode: 'option_list',
      selection: selected,
      labels,
    }),
    displayText: labels.join(', '),
  }
}
