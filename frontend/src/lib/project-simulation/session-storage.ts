// 只保存会话引用；消息、密钥和模拟状态由后端保存并验证用户归属。
export function readSimulationSession(key: string): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}
export function saveSimulationSession(key: string, id: string): void {
  try {
    window.localStorage.setItem(key, id)
  } catch {
    /* 存储受限时当前会话仍可使用。 */
  }
}
