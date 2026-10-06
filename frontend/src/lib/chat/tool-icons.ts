import {
  BookOpenIcon,
  BrainIcon,
  CalendarIcon,
  ClockIcon,
  FilePenIcon,
  FilePlusIcon,
  FileTextIcon,
  FolderIcon,
  GlobeIcon,
  ListChecksIcon,
  MailIcon,
  MessageCircleIcon,
  MessageSquareIcon,
  SearchIcon,
  ShieldCheckIcon,
  UsersIcon,
  WrenchIcon,
  type LucideIcon,
} from 'lucide-react'

// ──────────────────────────────────────────────
// toolIcon——解析聊天工具 pill/group header 的 leading 图标。
//
// runtime 注入的内置工具 + 已知 registry 工具属于"预定义集合"，因此按名称使用
// 固定映射。映射中没有的工具（任意 MCP 等）回退为 generic 扳手图标。
// （工具拥有的 backend ``icon_id`` 暴露到聊天中是后续事项 — 当前 ToolBrief
// 不携带 icon_id。）
// ──────────────────────────────────────────────

const EXACT_TOOL_ICONS: Readonly<Record<string, LucideIcon>> = {
  // temporal
  current_datetime: ClockIcon,
  resolve_relative_date: ClockIcon,
  // web / search
  web_search: SearchIcon,
  tavily_search: SearchIcon,
  google_search: SearchIcon,
  google_news_search: SearchIcon,
  web_scraper: GlobeIcon,
  http_request: GlobeIcon,
  // files (deepagents virtual FS)
  read_file: FileTextIcon,
  write_file: FilePlusIcon,
  edit_file: FilePenIcon,
  ls: FolderIcon,
  // planning / skills / delegation
  write_todos: ListChecksIcon,
  execute_in_skill: BookOpenIcon,
  task: UsersIcon,
  // HiTL
  ask_user: MessageCircleIcon,
  ask_clarifying_question: MessageCircleIcon,
  request_approval: ShieldCheckIcon,
  // google workspace
  gmail_send: MailIcon,
  google_calendar_event: CalendarIcon,
  google_chat_webhook: MessageSquareIcon,
  // memory
  propose_memory: BrainIcon,
  save_user_memory: BrainIcon,
  save_agent_memory: BrainIcon,
}

/** 前缀映射 — 同一系列的变体（google_search_web 等）一次性处理。 */
const PREFIX_TOOL_ICONS: ReadonlyArray<readonly [string, LucideIcon]> = [['google_', SearchIcon]]

/**
 * toolName → 内置固定映射图标。映射中没有则为 null（调用方回退到工具 icon_id 或
 * 扳手图标）。运行时注入的内置工具不在 agent.tools 中，因此没有 icon_id，所以此
 * 固定映射优先级最高。
 */
export function builtinToolIcon(toolName: string): LucideIcon | null {
  // Defensive: a tool fallback can render before its name resolves (undefined),
  // which previously threw on ``.startsWith``. Treat a missing name as unmapped.
  if (!toolName) return null
  const exact = EXACT_TOOL_ICONS[toolName]
  if (exact) return exact
  for (const [prefix, icon] of PREFIX_TOOL_ICONS) {
    if (toolName.startsWith(prefix)) return icon
  }
  return null
}

/** toolName → leading 图标。已知内置工具使用语义图标，否则回退到扳手图标。
 * （若还要考虑 icon_id，请在组件中使用 ``useToolIcon`` hook。） */
export function toolIcon(toolName: string): LucideIcon {
  return builtinToolIcon(toolName) ?? WrenchIcon
}
