import { describe, expect, it } from 'vitest'
import {
  looksLikeSearchResults,
  parseSearchResults,
  searchAnswerFromResult,
} from '../search-tool-data'

describe('parseSearchResults', () => {
  it('parses Tavily search response objects', () => {
    expect(
      parseSearchResults({
        query: 'agentic os',
        answer: 'summary',
        results: [
          {
            title: 'Spec',
            url: 'https://docs.example/spec',
            content: 'Architecture notes',
            score: 0.9,
            published_date: '2026-06-01',
          },
        ],
        response_time: 1.23,
      }),
    ).toEqual([
      {
        title: 'Spec',
        url: 'https://docs.example/spec',
        content: 'Architecture notes',
        score: 0.9,
        published_date: '2026-06-01',
      },
    ])
  })

  it('parses JSON string Tavily responses', () => {
    expect(
      parseSearchResults(
        '{"results":[{"title":"News","url":"https://news.example","content":"Snippet"}]}',
      ),
    ).toEqual([
      {
        title: 'News',
        url: 'https://news.example',
        content: 'Snippet',
      },
    ])
  })

  it('parses Naver items shape (link/description → url/snippet accessor 目标字段)', () => {
    expect(
      parseSearchResults({
        http_status: 200,
        total: 1234,
        items: [
          {
            title: '博客文章',
            link: 'https://blog.naver.example/1',
            description: '正文摘要',
            bloggername: '作者',
          },
        ],
      }),
    ).toEqual([
      {
        title: '博客文章',
        link: 'https://blog.naver.example/1',
        description: '正文摘要',
      },
    ])
  })

  it('parses Naver 购物 items (lprice/mallName/image 缩略图)', () => {
    expect(
      parseSearchResults({
        items: [
          {
            title: '机械键盘',
            link: 'https://shopping.naver.example/1',
            image: 'https://shopping-phinf.example/img.jpg',
            lprice: '12900',
            mallName: '商城名称',
          },
        ],
      }),
    ).toEqual([
      {
        title: '机械键盘',
        link: 'https://shopping.naver.example/1',
        thumbnail: 'https://shopping-phinf.example/img.jpg',
        price: 12900,
        mall_name: '商城名称',
      },
    ])
  })

  it('parses Google 图片 items (image.thumbnailLink 缩略图)', () => {
    expect(
      parseSearchResults({
        items: [
          {
            title: '图片',
            link: 'https://images.example/full.jpg',
            image: { thumbnailLink: 'https://images.example/thumb.jpg' },
          },
        ],
      }),
    ).toEqual([
      {
        title: '图片',
        link: 'https://images.example/full.jpg',
        thumbnail: 'https://images.example/thumb.jpg',
      },
    ])
  })

  it('unwraps MCP text-content wrapper([{type:text, text:JSON}])', () => {
    expect(
      parseSearchResults([
        {
          type: 'text',
          text: '{"results":[{"title":"MCP","url":"https://mcp.example"}]}',
        },
      ]),
    ).toEqual([{ title: 'MCP', url: 'https://mcp.example' }])
  })
})

describe('searchAnswerFromResult', () => {
  it('提取 Tavily answer 字段（包含 JSON 字符串）', () => {
    expect(searchAnswerFromResult({ answer: '摘要', results: [] })).toBe('摘要')
    expect(searchAnswerFromResult('{"answer":"摘要","results":[]}')).toBe('摘要')
  })

  it('answer 不存在或为空白时为 null', () => {
    expect(searchAnswerFromResult({ results: [] })).toBeNull()
    expect(searchAnswerFromResult({ answer: '  ' })).toBeNull()
    expect(searchAnswerFromResult('plain text')).toBeNull()
  })
})

describe('looksLikeSearchResults', () => {
  it('results|items 数组 + title + url|link 时为 true', () => {
    expect(looksLikeSearchResults({ results: [{ title: 'A', url: 'https://a.example' }] })).toBe(
      true,
    )
    expect(
      looksLikeSearchResults(
        '{"items":[{"title":"B","link":"https://b.example","description":"d"}]}',
      ),
    ).toBe(true)
  })

  it('缺少 title 或 url 时为 false（保守判定）', () => {
    expect(looksLikeSearchResults({ items: [{ title: 'no url' }] })).toBe(false)
    expect(looksLikeSearchResults({ results: [{ url: 'https://no-title.example' }] })).toBe(false)
    expect(looksLikeSearchResults({ total: 3 })).toBe(false)
    expect(looksLikeSearchResults('plain text')).toBe(false)
    expect(looksLikeSearchResults(null)).toBe(false)
  })
})

describe('URL sanitize（信任边界之外的工具结果）', () => {
  it('拦截 javascript: 等非 http(s) scheme 链接', async () => {
    const { searchItemUrl, sanitizeExternalUrl } = await import('../search-tool-data')
    expect(searchItemUrl({ url: 'javascript:alert(1)' })).toBeUndefined()
    expect(searchItemUrl({ link: 'data:text/html,<script>1</script>' })).toBeUndefined()
    expect(searchItemUrl({ url: 'https://ok.example/a' })).toBe('https://ok.example/a')
    expect(sanitizeExternalUrl('  http://ok.example ')).toBe('http://ok.example')
  })

  it('缩略图仅允许 http(s) + 本地相对路径（拦截 protocol-relative）', async () => {
    const { sanitizeThumbnailUrl } = await import('../search-tool-data')
    expect(sanitizeThumbnailUrl('https://img.example/a.jpg')).toBe('https://img.example/a.jpg')
    expect(sanitizeThumbnailUrl('/logo.webp')).toBe('/logo.webp')
    expect(sanitizeThumbnailUrl('//evil.example/a.jpg')).toBeUndefined()
    expect(sanitizeThumbnailUrl('javascript:alert(1)')).toBeUndefined()
  })
})
