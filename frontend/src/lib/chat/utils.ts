/** 从 AppendMessage content 中提取文本 */
export function extractText(content: readonly { type: string; text?: string }[]): string {
  return content
    .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
    .map((p) => p.text)
    .join('')
}
