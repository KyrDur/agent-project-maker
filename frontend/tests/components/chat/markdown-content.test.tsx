import { fireEvent } from '@testing-library/react'
import { render, screen } from '../../test-utils'
import { MarkdownContent } from '@/components/chat/markdown-content'

describe('MarkdownContent', () => {
  it('renders paragraphs', () => {
    render(<MarkdownContent content="Hello world" />)
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('renders bold text', () => {
    render(<MarkdownContent content="This is **bold** text" />)
    const bold = screen.getByText('bold')
    expect(bold.tagName).toBe('STRONG')
  })

  it('renders italic text', () => {
    render(<MarkdownContent content="This is *italic* text" />)
    const italic = screen.getByText('italic')
    expect(italic.tagName).toBe('EM')
  })

  it('renders links with target=_blank', () => {
    render(<MarkdownContent content="Visit [Google](https://google.com)" />)
    const link = screen.getByText('Google')
    expect(link.tagName).toBe('A')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('href', 'https://google.com')
  })

  it('renders unordered lists', () => {
    const content = `- Item 1
- Item 2
- Item 3`
    render(<MarkdownContent content={content} />)
    expect(screen.getByText('Item 1')).toBeInTheDocument()
    expect(screen.getByText('Item 2')).toBeInTheDocument()
    expect(screen.getByText('Item 3')).toBeInTheDocument()
  })

  it('renders inline code', () => {
    render(<MarkdownContent content="Use `console.log` to debug" />)
    const code = screen.getByText('console.log')
    expect(code.tagName).toBe('CODE')
  })

  it('renders code blocks', () => {
    const { container } = render(<MarkdownContent content={'```js\nconst x = 1\n```'} />)
    // SyntaxHighlighter tokenizes code into multiple spans, so check the container text
    expect(container.textContent).toContain('const')
    expect(container.textContent).toContain('x')
    expect(container.textContent).toContain('1')
  })

  it('uses Korean copy text in code blocks', () => {
    render(<MarkdownContent content={'```js\nconst x = 1\n```'} />)

    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument()
  })

  it('renders fenced code as a plain block while streaming', () => {
    const { container } = render(<MarkdownContent content={'```js\nconst x = 1\n```'} isStreaming />)

    expect(screen.queryByRole('button', { name: '复制' })).not.toBeInTheDocument()
    expect(container.querySelector('.code-block-wrapper')).not.toBeInTheDocument()
    const code = container.querySelector('pre code')
    expect(code).toBeInTheDocument()
    expect(code).toHaveTextContent('const x = 1')
  })

  it('accepts custom className', () => {
    const { container } = render(<MarkdownContent content="Hello" className="custom-class" />)
    expect(container.firstChild).toHaveClass('custom-class')
  })

  it('renders ordered lists', () => {
    const content = `1. First\n2. Second\n3. Third`
    render(<MarkdownContent content={content} />)
    expect(screen.getByText('First')).toBeInTheDocument()
    expect(screen.getByText('Second')).toBeInTheDocument()
  })

  it('renders blockquotes', () => {
    render(<MarkdownContent content="> This is a quote" />)
    const quote = screen.getByText('This is a quote')
    expect(quote.closest('blockquote')).toBeInTheDocument()
  })

  it('renders headings', () => {
    render(<MarkdownContent content="# Heading 1" />)
    expect(screen.getByText('Heading 1')).toBeInTheDocument()
  })

  it('renders horizontal rules', () => {
    const content = 'above\n\n---\n\nbelow'
    const { container } = render(<MarkdownContent content={content} />)
    const hrs = container.querySelectorAll('hr')
    expect(hrs.length).toBeGreaterThanOrEqual(1)
  })

  it('renders h2 headings', () => {
    render(<MarkdownContent content="## Heading 2" />)
    expect(screen.getByText('Heading 2')).toBeInTheDocument()
  })

  it('renders h3 headings', () => {
    render(<MarkdownContent content="### Heading 3" />)
    expect(screen.getByText('Heading 3')).toBeInTheDocument()
  })

  it('uses Korean image error text', () => {
    render(<MarkdownContent content="![sample](/api/conversations/c1/files/missing.png)" />)

    fireEvent.error(screen.getByRole('img', { name: 'sample' }))
    fireEvent.error(screen.getByRole('img', { name: 'sample' }))
    expect(screen.getByText('图片加载失败')).toBeInTheDocument()
  })

  it('renders KaTeX math via remark-math + rehype-katex', () => {
    // inline 公式 — $E=mc^2$
    const { container } = render(<MarkdownContent content={'$E=mc^2$'} />)
    // rehype-katex 会创建带有 .katex 类的 span。
    expect(container.querySelector('.katex')).toBeInTheDocument()
  })

  it('renders mermaid code as a passthrough during streaming', () => {
    const code = 'graph TD\nA --> B'
    const { container } = render(
      <MarkdownContent content={`\`\`\`mermaid\n${code}\n\`\`\``} isStreaming />,
    )
    // 流式传输期间会退回 raw code block（防止不完整解析）。
    expect(container.textContent).toContain('graph TD')
  })

  it('remark-breaks: 将单个换行转换为 <br>', () => {
    // GitHub markdown 标准会忽略 single newline（视为空格），但 remarkBreaks 会
    // 转为 <br>，从而保留 LLM 的换行意图。
    const content = 'first line\nsecond line'
    const { container } = render(<MarkdownContent content={content} />)
    const br = container.querySelector('br')
    expect(br).toBeInTheDocument()
  })

  it('remark-breaks: 空行(double newline)仍保持为段落分隔', () => {
    const content = 'paragraph one\n\nparagraph two'
    const { container } = render(<MarkdownContent content={content} />)
    const ps = container.querySelectorAll('p')
    expect(ps.length).toBe(2)
  })
})
