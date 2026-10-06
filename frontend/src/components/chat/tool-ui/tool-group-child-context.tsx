'use client'

import { createContext, useContext, type ReactNode } from 'react'

// ToolGroupContainer 渲染子项（连续相同工具调用）时启用此上下文。
// 子项 pill 读取该值以知道自己处于"分组内"，并以每次调用的参数/结果摘要
// 作为标题显示，而不是工具名（工具名已在分组标题区中，避免重复）。

const ToolGroupChildContext = createContext(false)

export function ToolGroupChildProvider({ children }: { children: ReactNode }) {
  return <ToolGroupChildContext.Provider value={true}>{children}</ToolGroupChildContext.Provider>
}

/** 当前渲染是否为 tool 分组容器的子项。 */
export function useIsToolGroupChild(): boolean {
  return useContext(ToolGroupChildContext)
}
