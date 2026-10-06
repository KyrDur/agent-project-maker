import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyTextToClipboard, getMessageCopyText } from '../message-copy'

function setClipboard(clipboard: Pick<Clipboard, 'writeText'> | undefined) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: clipboard,
  })
}

describe('message copy helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('extracts only copyable text from mixed message content', () => {
    expect(
      getMessageCopyText([
        { type: 'text', text: '用户问题' },
        { type: 'tool-call' },
        { type: 'reasoning', text: '中间推理' },
        { type: 'image' },
      ]),
    ).toBe('用户问题\n\n中间推理')
  })

  it('passes string content through unchanged', () => {
    expect(getMessageCopyText('plain prompt')).toBe('plain prompt')
  })

  it('writes text through the async Clipboard API', async () => {
    const writeText = vi.fn<Clipboard['writeText']>().mockResolvedValue(undefined)
    setClipboard({ writeText })

    await copyTextToClipboard('要复制的消息')

    expect(writeText).toHaveBeenCalledWith('要复制的消息')
  })

  it('falls back to document copy command when Clipboard API is unavailable', async () => {
    const execCommand = vi.fn().mockReturnValue(true)
    setClipboard(undefined)
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    })

    await copyTextToClipboard('fallback text')

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.querySelector('textarea')).toBeNull()
  })
})
