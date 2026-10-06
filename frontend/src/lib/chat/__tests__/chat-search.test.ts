import { describe, expect, it } from 'vitest'
import { collectMatchRanges } from '../chat-search'

describe('collectMatchRanges', () => {
  it('按匹配消息收集搜索词出现位置的 Range（忽略大小写）', () => {
    document.body.innerHTML = `
      <div data-moldy-message-id="m1">会议准备和会议记录</div>
      <div data-moldy-message-id="m2">Hello WORLD</div>
      <div>没有锚点的节点</div>
    `
    const map = collectMatchRanges('会议')
    expect(Array.from(map.keys())).toEqual(['m1'])
    // "会议"在一个文本节点中出现 2 次 → 2 个 Range。
    expect(map.get('m1')?.length).toBe(2)
    // 忽略大小写。
    expect(Array.from(collectMatchRanges('world').keys())).toEqual(['m2'])
  })

  it('搜索时排除元数据行/sr-only 文本', () => {
    document.body.innerHTML = `
      <div data-moldy-message-id="m1">
        <div>正文会议内容</div>
        <div data-moldy-message-meta-row="true">复制 编辑 会议</div>
        <span class="sr-only">会议标签</span>
      </div>
    `
    const map = collectMatchRanges('会议')
    // 只计正文中的 1 个"会议"——排除元数据行/sr-only 中的"会议"。
    expect(map.get('m1')?.length).toBe(1)
  })

  it('按 root 限定 scope 时，排除 root 外的消息（应对设置页面双重挂载）', () => {
    document.body.innerHTML = `
      <div id="scope"><div data-moldy-message-id="m1">会议 A</div></div>
      <div data-moldy-message-id="m2">会议 B</div>
    `
    const scope = document.getElementById('scope')
    expect(scope).not.toBeNull()
    const map = collectMatchRanges('会议', scope as HTMLElement)
    expect(Array.from(map.keys())).toEqual(['m1'])
  })

  it('空/纯空白 query 返回空 map', () => {
    document.body.innerHTML = `<div data-moldy-message-id="m1">会议</div>`
    expect(collectMatchRanges('').size).toBe(0)
    expect(collectMatchRanges('   ').size).toBe(0)
  })
})
