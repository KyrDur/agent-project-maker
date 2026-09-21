import { describe, expect, it } from 'vitest'

import { render, screen } from '../../../../tests/test-utils'

import { PortableCompatibilityPanel } from '../portable-compatibility-panel'

describe('PortableCompatibilityPanel', () => {
  it('renders portable target chips with issue details', () => {
    render(
      <PortableCompatibilityPanel
        result={{
          targets: {
            openai_codex: { status: 'pass', issues: [] },
            claude_code: {
              status: 'warning',
              issues: [
                {
                  code: 'missing_agent_metadata',
                  severity: 'warning',
                  path: 'agents/claude.yaml',
                  message: 'Claude metadata is recommended.',
                },
              ],
            },
            vercel_agent_skills: {
              status: 'error',
              issues: [
                {
                  code: 'moldy_frontmatter',
                  severity: 'error',
                  path: 'SKILL.md',
                  message: 'Move Moldy-only fields out of frontmatter.',
                },
              ],
            },
          },
          error_count: 1,
          warning_count: 1,
          info_count: 0,
        }}
      />,
    )

    expect(screen.getByText('便携兼容性')).toBeInTheDocument()
    expect(screen.getByText('OpenAI/Codex')).toBeInTheDocument()
    expect(screen.getByText('Claude Code')).toBeInTheDocument()
    expect(screen.getByText('Vercel Agent Skills')).toBeInTheDocument()
    expect(screen.getByText('通行证')).toBeInTheDocument()
    expect(screen.getByText('警告')).toBeInTheDocument()
    expect(screen.getByText('错误')).toBeInTheDocument()
    expect(
      screen.getByText(/agents\/claude.yaml: Claude metadata is recommended\./),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/SKILL.md: Move Moldy-only fields out of frontmatter\./),
    ).toBeInTheDocument()
  })

  it('renders an empty state when no compatibility result exists', () => {
    render(<PortableCompatibilityPanel result={null} />)

    expect(screen.getByText('还没有兼容性结果。')).toBeInTheDocument()
  })
})
