import { describe, expect, it, vi, beforeEach } from 'vitest'

import { render, screen, userEvent } from '../../../../tests/test-utils'
import type { SkillDetailTabSlots } from '../skill-detail-tab-shell'

import { TextSkillEditor } from '../skill-detail-text-editor'
import { PackageSkillEditor } from '../skill-detail-package-editor'

// 源标签页编辑·保存循环回归防护 — 填补因删除旧对话框测试产生的
// 覆盖率空白（审查 R / B3）。

function renderTestSlots(slots: SkillDetailTabSlots) {
  return (
    <>
      {slots.sidebar}
      {slots.body}
      {slots.footer}
      {slots.overlay}
    </>
  )
}

const mockUpdateContent = vi.fn()
const mockSetFile = vi.fn()
const mockDeleteFile = vi.fn()
// 用于模拟服务器内容变化（回滚等）的可变持有器 — 每次渲染读取最新值。
const textContentHolder = { content: '# 原始正文' }

vi.mock('@/lib/hooks/use-skills', () => ({
  useSkill: () => ({
    data: {
      id: 'skill-1',
      kind: 'package',
      size_bytes: 2048,
      version: '1.0.0',
      used_by_count: 1,
      content_hash: 'hash-1',
    },
  }),
  useSkillContent: () => ({ data: { content: textContentHolder.content } }),
  useUpdateSkillContent: () => ({ mutateAsync: mockUpdateContent, isPending: false }),
  useSkillFiles: () => ({
    data: [
      { path: 'SKILL.md', is_dir: false, size: 128 },
      { path: 'scripts/run.py', is_dir: false, size: 64 },
    ],
  }),
  useSetSkillFile: () => ({ mutateAsync: mockSetFile, isPending: false }),
  useDeleteSkillFile: () => ({ mutateAsync: mockDeleteFile, isPending: false }),
}))

vi.mock('../use-skill-file-remote-cache', () => ({
  useSkillFileRemoteCache: () => ({
    remoteCache: new Map([
      ['SKILL.md', '# SKILL.md 原文'],
      ['scripts/run.py', 'print("hi")'],
    ]),
    setRemoteCache: vi.fn(),
  }),
}))

describe('TextSkillEditor (源标签页)', () => {
  beforeEach(() => {
    mockUpdateContent.mockReset().mockResolvedValue(undefined)
    textContentHolder.content = '# 原始正文'
  })

  it('修改正文并保存后，PUT 载荷中包含编辑内容', async () => {
    const user = userEvent.setup()
    render(<TextSkillEditor skillId="skill-1">{renderTestSlots}</TextSkillEditor>)

    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveValue('# 原始正文')

    await user.clear(textarea)
    await user.type(textarea, '# 修改后的正文')
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(mockUpdateContent).toHaveBeenCalledWith({
      id: 'skill-1',
      data: { content: '# 修改后的正文' },
    })
  })

  it('服务器内容变化后（回滚后 refetch），重新为编辑器注入初始内容 — R5', () => {
    const { rerender } = render(
      <TextSkillEditor skillId="skill-1">{renderTestSlots}</TextSkillEditor>,
    )
    expect(screen.getByRole('textbox')).toHaveValue('# 原始正文')

    // 版本标签页回滚 → content 查询 refetch 落到新正文。
    textContentHolder.content = '# 回滚后的正文'
    rerender(<TextSkillEditor skillId="skill-1">{renderTestSlots}</TextSkillEditor>)

    // 如果是 hydrate-once，会锁住 stale '# 原始正文'，保存时反向撤销回滚。
    expect(screen.getByRole('textbox')).toHaveValue('# 回滚后的正文')
  })

  it('dirty draft 即使服务器内容变化落地也不会被覆盖', async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <TextSkillEditor skillId="skill-1">{renderTestSlots}</TextSkillEditor>,
    )

    const textarea = screen.getByRole('textbox')
    await user.clear(textarea)
    await user.type(textarea, '# 编辑中')

    textContentHolder.content = '# 后台更新'
    rerender(<TextSkillEditor skillId="skill-1">{renderTestSlots}</TextSkillEditor>)

    expect(screen.getByRole('textbox')).toHaveValue('# 编辑中')
  })
})

describe('PackageSkillEditor (源标签页)', () => {
  beforeEach(() => {
    mockSetFile.mockReset().mockResolvedValue(undefined)
  })

  it('添加文件时拒绝重复路径，新路径会去掉前导斜杠后创建', async () => {
    const user = userEvent.setup()
    render(<PackageSkillEditor skillId="skill-1">{renderTestSlots}</PackageSkillEditor>)

    await user.click(screen.getByRole('button', { name: '添加文件' }))
    const pathInput = screen.getByPlaceholderText('path/to/new-file.md')

    // 拒绝重复路径 — 不能让现有文件被空内容覆盖。
    await user.type(pathInput, 'SKILL.md')
    await user.click(screen.getByRole('button', { name: '创建' }))
    expect(mockSetFile).not.toHaveBeenCalled()

    await user.clear(pathInput)
    await user.type(pathInput, '/references/new.md')
    await user.click(screen.getByRole('button', { name: '创建' }))
    expect(mockSetFile).toHaveBeenCalledWith({ path: 'references/new.md', content: '' })
  })

  it('SKILL.md 以外的文件在删除确认后调用 DELETE', async () => {
    const user = userEvent.setup()
    render(<PackageSkillEditor skillId="skill-1">{renderTestSlots}</PackageSkillEditor>)

    // 删除按钮只在 SKILL.md（受保护）以外的文件上显示。树只显示 leaf 名称，
    // 因此通过 run.py 选择。
    await user.click(screen.getByRole('button', { name: /run\.py/ }))
    await user.click(screen.getByRole('button', { name: '删除文件' }))
    await user.click(screen.getByRole('button', { name: '确认删除' }))

    expect(mockDeleteFile).toHaveBeenCalledWith('scripts/run.py')
  })

  it('修改文件后启用保存，并在 PUT 中包含路径和内容', async () => {
    const user = userEvent.setup()
    render(<PackageSkillEditor skillId="skill-1">{renderTestSlots}</PackageSkillEditor>)

    // 默认选择 SKILL.md — 渲染原始内容。
    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveValue('# SKILL.md 原文')
    const save = screen.getByRole('button', { name: '保存文件' })
    expect(save).toBeDisabled()

    await user.clear(textarea)
    await user.type(textarea, '# 更新')
    expect(save).toBeEnabled()

    await user.click(save)
    expect(mockSetFile).toHaveBeenCalledWith({ path: 'SKILL.md', content: '# 更新' })
  })
})
