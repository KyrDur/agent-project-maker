import { describe, expect, it } from 'vitest'
import { readQuoteSelection } from './quote-selection'
import {
  resourceContextReferencesSchema,
  addResourceContextReference,
} from '@/lib/chat/context/resource-context'

const id = '11111111-1111-4111-8111-111111111111'

function selectedText() {
  const root = document.createElement('div')
  const thread = document.createElement('div')
  thread.dataset.chatSelectionThread = id
  thread.dataset.chatSelectionTitle = '原始对话'
  const message = document.createElement('div')
  message.dataset.moldyMessageId = 'message-1'
  message.dataset.moldyMessageRole = 'assistant'
  const text = document.createElement('p')
  text.dataset.chatQuoteText = ''
  text.textContent = '选中的句子'
  const tool = document.createElement('button')
  tool.textContent = '工具'
  message.append(text, tool)
  thread.append(message)
  root.append(thread)
  document.body.replaceChildren(root)
  const paragraph = root.querySelector('p')
  if (!paragraph) throw new Error('Missing fixture paragraph')
  const range = document.createRange()
  range.selectNodeContents(paragraph)
  Object.defineProperty(range, 'getBoundingClientRect', {
    value: () => new DOMRect(20, 40, 120, 20),
  })
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
  return { root, paragraph, selection }
}

describe('selected message provenance', () => {
  it('captures source conversation, message and excerpt without changing the message', () => {
    const { root, selection } = selectedText()
    const quote = readQuoteSelection(root, selection)
    expect(quote?.reference).toEqual({
      kind: 'conversation',
      id,
      message_id: 'message-1',
      message_role: 'assistant',
      quote: '选中的句子',
      label: '原始对话',
    })
    expect(root.textContent).toBe('选中的句子工具')
  })
  it('excludes unrelated roots, in-progress text, and cross-element selections', () => {
    const { root, paragraph, selection } = selectedText()
    expect(readQuoteSelection(document.createElement('div'), selection)).toBeNull()
    paragraph.dataset.chatStreaming = 'true'
    expect(readQuoteSelection(root, selection)).toBeNull()
    delete paragraph.dataset.chatStreaming
    const range = selection?.getRangeAt(0)
    const button = root.querySelector('button')
    if (!range || !button) throw new Error('Missing fixture selection')
    range.setEndAfter(button)
    expect(readQuoteSelection(root, selection)).toBeNull()
  })
  it('validates quote contracts and keeps different excerpts from the same message', () => {
    const one = { kind: 'conversation', id, message_id: 'message-1', quote: '第一句' } as const
    expect(resourceContextReferencesSchema.safeParse([one]).success).toBe(true)
    expect(resourceContextReferencesSchema.safeParse([{ ...one, quote: undefined }]).success).toBe(
      false,
    )
    expect(addResourceContextReference([one], one).kind).toBe('duplicate')
    expect(addResourceContextReference([one], { ...one, quote: '其他句子' }).kind).toBe('added')
  })
})
