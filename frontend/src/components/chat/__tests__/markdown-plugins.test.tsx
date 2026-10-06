import Markdown from 'react-markdown'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import '@testing-library/jest-dom/vitest'

import { CHAT_STREAMING_REMARK_PLUGINS } from '../markdown-streaming-plugins'

const TABLE_MARKDOWN = `| 时间段 | 地点 | 活动 |
|--------|------|------|
| 09:00 ~ 10:30 | 佛国寺 | 一早抵达，凉爽地游览遗迹 |
`

describe('chat markdown plugins', () => {
  it('parses GFM tables in streaming chat markdown', () => {
    render(<Markdown remarkPlugins={CHAT_STREAMING_REMARK_PLUGINS}>{TABLE_MARKDOWN}</Markdown>)

    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '时间段' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '佛国寺' })).toBeInTheDocument()
  })
})
