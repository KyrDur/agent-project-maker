import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SearchRender } from '../search-tool-ui'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join('/')})` : key,
}))

const DONE = { type: 'complete' } as const

describe('SearchRender', () => {
  it('将 Tavily answer 渲染为摘要框', () => {
    render(
      <SearchRender
        args={{ query: 'agentic os' }}
        result={{
          answer: 'Agentic OS 就是这样的。',
          results: [{ title: '文件', url: 'https://docs.example' }],
        }}
        status={DONE}
      />,
    )
    const box = document.querySelector('[data-moldy-search-answer]')
    expect(box).not.toBeNull()
    expect(screen.getByText('Agentic OS 就是这样的。')).toBeInTheDocument()
    expect(screen.getByText('文件')).toBeInTheDocument()
  })

  it('将 Naver items shape 渲染成卡片（description → snippet）', () => {
    render(
      <SearchRender
        args={{ query: '美食店' }}
        result={JSON.stringify({
          http_status: 200,
          total: 2,
          items: [
            { title: '博客 A', link: 'https://a.example', description: '摘要 A' },
            { title: '博客 B', link: 'https://b.example', description: '摘要 B' },
          ],
        })}
        status={DONE}
      />,
    )
    expect(screen.getByText('博客 A')).toBeInTheDocument()
    expect(screen.getByText('摘要 A')).toBeInTheDocument()
    expect(screen.getByText('count(2)')).toBeInTheDocument()
  })

  it('购物结果渲染缩略图和价格', () => {
    render(
      <SearchRender
        args={{ query: '键盘' }}
        result={{
          items: [
            {
              title: '机械键盘',
              link: 'https://shop.example/1',
              image: 'https://img.example/kb.jpg',
              lprice: '12900',
              mallName: '商城',
            },
          ],
        }}
        status={DONE}
      />,
    )
    const thumbnail = document.querySelector('[data-moldy-search-thumbnail]')
    expect(thumbnail).not.toBeNull()
    expect(thumbnail).toHaveAttribute('src', 'https://img.example/kb.jpg')
    expect(document.querySelector('[data-moldy-search-price]')).not.toBeNull()
    expect(screen.getByText('price(12,900)')).toBeInTheDocument()
    expect(screen.getByText('商城')).toBeInTheDocument()
  })

  it('running 状态下不渲染结果/answer', () => {
    render(
      <SearchRender
        args={{ query: 'q' }}
        result={{ answer: '提前到达的 answer', results: [] }}
        status={{ type: 'running' }}
      />,
    )
    expect(screen.queryByText('提前到达的 answer')).not.toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
  })
})
