import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '../../../../tests/test-utils'
import { SkillDetailPackageFooter } from '../skill-detail-package-footer'

function renderFooter(overrides: Partial<Parameters<typeof SkillDetailPackageFooter>[0]> = {}) {
  return render(
    <SkillDetailPackageFooter
      savePending={false}
      saveDisabled={false}
      sizeBytes={2048}
      version="1.0.0"
      usedByCount={3}
      onSave={vi.fn()}
      {...overrides}
    />,
  )
}

describe('SkillDetailPackageFooter', () => {
  it('渲染包摘要（大小·版本·连接数）和保存按钮 — Phase 2 源标签页契约', () => {
    renderFooter()

    // usedBy 摘要行始终显示 — 包总大小唯一的显示位置（审查 R）。
    expect(screen.getByText(/1\.0\.0/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存文件' })).toBeEnabled()
    // 删除/导出/关闭由设置标签页·行菜单负责 — 页脚中不应出现。
    expect(screen.queryByRole('button', { name: '导出.skill' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除技能' })).not.toBeInTheDocument()
  })

  it('反映保存禁用状态', () => {
    renderFooter({ saveDisabled: true })

    expect(screen.getByRole('button', { name: '保存文件' })).toBeDisabled()
  })
})
