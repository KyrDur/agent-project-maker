import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '../../test-utils'

const mocks = vi.hoisted(() => ({
  addAttachment: vi.fn(),
  composerText: '',
  hasQueue: false,
  isRunning: false,
  send: vi.fn(),
  setText: vi.fn(),
}))

vi.mock('@assistant-ui/react', () => ({
  unstable_useTriggerPopoverAriaProps: () => ({}),
  unstable_useTriggerPopoverRootContextOptional: () => null,
  useAui: () => ({
    composer: {
      addAttachment: mocks.addAttachment,
      getState: () => ({ isEditing: true, isEmpty: false, text: mocks.composerText }),
      send: mocks.send,
      setText: mocks.setText,
    },
    thread: {
      getState: () => ({
        capabilities: { attachments: false, queue: mocks.hasQueue },
        isRunning: mocks.isRunning,
      }),
    },
  }),
  useAuiState: (selector: (state: unknown) => unknown) =>
    selector({
      composer: { dictation: null, isEditing: true, runConfig: {}, text: mocks.composerText },
      thread: { isDisabled: false },
    }),
}))

import { ImeSafeComposerInput } from '@/components/chat/ime-safe-composer-input'

describe('ImeSafeComposerInput', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.composerText = ''
    mocks.hasQueue = false
    mocks.isRunning = false
  })

  it('focuses the composer input when auto focus is requested', () => {
    render(<ImeSafeComposerInput autoFocus placeholder="占位符" />)

    expect(screen.getByPlaceholderText('占位符')).toHaveFocus()
  })

  it('restores focus when submitted composer text is cleared', async () => {
    mocks.composerText = 'hello'
    const { rerender } = render(<ImeSafeComposerInput placeholder="占位符" />)
    const textarea = screen.getByPlaceholderText('占位符')

    expect(textarea).not.toHaveFocus()

    mocks.composerText = ''
    rerender(<ImeSafeComposerInput placeholder="占位符" />)

    await waitFor(() => {
      expect(textarea).toHaveFocus()
    })
  })

  it('keeps IME composition local until the syllable is committed', () => {
    render(<ImeSafeComposerInput placeholder="占位符" />)

    const textarea = screen.getByPlaceholderText('占位符')

    fireEvent.compositionStart(textarea)
    fireEvent.change(textarea, { target: { value: 'z' } })
    fireEvent.change(textarea, { target: { value: '中' } })

    expect(mocks.setText).not.toHaveBeenCalled()

    fireEvent.compositionEnd(textarea)

    expect(mocks.setText).toHaveBeenCalledWith('中')
  })

  it('inserts an IME syllable before a final dictated transcript that arrives during composition', () => {
    mocks.composerText = '草稿'
    const { rerender } = render(<ImeSafeComposerInput placeholder="占位符" />)
    const textarea = screen.getByPlaceholderText('占位符')

    textarea.setSelectionRange(2, 2)
    fireEvent.compositionStart(textarea)
    fireEvent.change(textarea, { target: { value: '草稿中' } })

    mocks.composerText = '草稿语音'
    rerender(<ImeSafeComposerInput placeholder="占位符" />)

    fireEvent.compositionEnd(textarea)

    expect(mocks.setText).toHaveBeenLastCalledWith('草稿中语音')
  })

  it('preserves a selected-text IME replacement when dictation updates during composition', () => {
    mocks.composerText = '首句草稿'
    const { rerender } = render(<ImeSafeComposerInput placeholder="占位符" />)
    const textarea = screen.getByPlaceholderText('占位符')

    textarea.setSelectionRange(2, 4)
    fireEvent.compositionStart(textarea)
    fireEvent.change(textarea, { target: { value: '首句替代文本' } })

    mocks.composerText = '首句草稿语音'
    rerender(<ImeSafeComposerInput placeholder="占位符" />)

    fireEvent.compositionEnd(textarea)

    expect(mocks.setText).toHaveBeenLastCalledWith('首句替代文本语音')
  })

  it('syncs ordinary changes immediately', () => {
    render(<ImeSafeComposerInput placeholder="占位符" />)

    fireEvent.change(screen.getByPlaceholderText('占位符'), {
      target: { value: 'hello' },
    })

    expect(mocks.setText).toHaveBeenCalledWith('hello')
  })

  it('marks ordinary Enter as non-steering when the server queue is available', () => {
    mocks.hasQueue = true
    mocks.isRunning = true
    render(<ImeSafeComposerInput submitMode="enter" placeholder="占位符" />)

    fireEvent.keyDown(screen.getByPlaceholderText('占位符'), { key: 'Enter' })

    expect(mocks.send).toHaveBeenCalledExactlyOnceWith({ steer: false })
  })

  it('uses explicit steer only for Shift plus Ctrl Enter', () => {
    mocks.hasQueue = true
    mocks.isRunning = true
    render(<ImeSafeComposerInput submitMode="enter" placeholder="占位符" />)

    fireEvent.keyDown(screen.getByPlaceholderText('占位符'), {
      key: 'Enter',
      shiftKey: true,
      ctrlKey: true,
    })

    expect(mocks.send).toHaveBeenCalledExactlyOnceWith({ steer: true })
  })
})
