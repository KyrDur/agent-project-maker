# UX Improvement Design Spec

> **Author:** Tim Cook (TTH Designer/UX)
> **Date:** 2026-04-07
> **Status:** Draft
> **Target:** Moldy AI Agent Builder — Frontend UI/UX 全面改进

---

## 目录

1. [Coming Soon 模式](#1-coming-soon-模式)
2. [Agent 卡片重设计](#2-agent-卡片重设计)
3. [设置页面 tab 结构](#3-设置页面-tab-结构)
4. [Breadcrumb 设计](#4-breadcrumb-设计)
5. [App 设置页面](#5-app-设置页面)
6. [工具详情 Dialog](#6-工具详情-dialog)

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **Simplicity** | 去掉不必要的内容，本质就会显现 |
| **Consistency** | 相同模式用相同方式。Dialog 就是 Dialog，Badge 就是 Badge |
| **Accessibility** | WCAG 2.1 AA 标准。focus-visible、aria-label、4.5:1 对比度 |
| **Progressive Disclosure** | 只在需要时显示需要的信息。通过 hover/tab 渐进暴露 |

### Opacity 策略

按用途区分两种 opacity 模式：

| 模式 | class | 用途 |
|------|--------|------|
| **Dim（半透明）** | `opacity-50 hover:opacity-70` | 功能存在但尚未发布（Coming Soon） |
| **Show/Hide** | `opacity-0 group-hover:opacity-100` | 功能存在，但减少视觉噪音（卡片 action 按钮） |

Dim 表示“有，但还不能用”，Show/Hide 表示“有，但只在需要时显示”。

---

## 1. Coming Soon 模式

### 问题

当前 `disabled` 按钮（`opacity-40 cursor-not-allowed`）不会告诉用户为什么被禁用。点击没有任何反应，会让 UX 有被卡住的感觉。

### 解决方案

移除 `disabled` 属性，点击时通过 `toast.info` 显示“准备中”消息。视觉上暗示“即将推出”，但交互仍然可用。

### 视觉设计

```
┌─────────────────────────────┐
│  [📎] ← opacity-50，可点击     │
│        光标：pointer           │
│        hover 时 opacity-70     │
│        点击 → toast.info       │
└─────────────────────────────┘
```

### Tailwind class 指南

```tsx
// 通用 utility class（适用于所有 Coming Soon 元素）
const COMING_SOON_CLASSES = [
  "opacity-50",              // 默认状态：半透明
  "hover:opacity-70",        // hover：略微更清晰（交互提示）
  "cursor-pointer",          // 表示可点击
  "transition-opacity",      // 平滑过渡
  "duration-200",            // 200ms transition
].join(" ");
```

### Component 结构（JSX sketch）

```tsx
// components/shared/coming-soon-button.tsx
"use client";

import { Button, type ButtonProps } from "@/components/ui/button";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

interface ComingSoonButtonProps extends Omit<ButtonProps, "onClick" | "disabled"> {
  featureKey?: string;   // i18n key（例如 "fileAttach"）
  children: React.ReactNode;
}

export function ComingSoonButton({
  featureKey,
  children,
  className,
  ...props
}: ComingSoonButtonProps) {
  const t = useTranslations("common.comingSoon");

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    toast.info(featureKey ? t(featureKey) : t("default"));
    // default: “此功能正在准备中”
  };

  return (
    <Button
      {...props}
      onClick={handleClick}
      className={cn(
        "opacity-50 hover:opacity-70 cursor-pointer transition-opacity duration-200",
        className
      )}
    >
      {children}
    </Button>
  );
}
```

### 使用示例

```tsx
// Before（现有）
<Button disabled className="opacity-40 cursor-not-allowed">
  <PaperclipIcon className="size-4" />
</Button>

// After（改进）
<ComingSoonButton variant="ghost" size="icon-sm" featureKey="fileAttach">
  <PaperclipIcon className="size-4" />
</ComingSoonButton>
```

### shadcn/ui Component

- `Button` (variant: ghost)
- `toast.info` (sonner)

### 可访问性

- `aria-label` 包含“（准备中）”
- 移除 `disabled` → 可通过键盘 focus
- toast 通过 `role="status"` 传递给 screen reader

### Dark mode

- `opacity-50/70` 不受 theme 影响。无需额外 dark mode class。

### 响应式

- 按钮尺寸遵循现有 `size` prop。无需额外响应式处理。

---

## 2. Agent 卡片重设计

### 问题

1. 用逗号列出工具名称（`tools.map(t => t.name).join(', ')`），导致卡片高度参差不齐
2. 设置/视觉设置按钮始终显示，造成视觉噪音
3. metadata（工具列表）比 Agent 描述更醒目

### 解决方案

```
┌──────────────────────────────────────┐
│  ⭐ Agent Name                [active]│  ← 名称 + 状态 badge + 收藏
│                                      │
│  Agent 描述文本显示在这里             │  ← 强调描述（限制 2 行）
│  最多显示 2 行...                     │
│                                      │
│  🤖 GPT-4o  ·  🔧 3 tools           │  ← 模型 + 工具数量 badge
│──────────────────────────────────────│
│  2026-03-15            [⚙️][🎨][⭐]  │  ← 仅 hover 时显示 action 按钮
└──────────────────────────────────────┘
```

### Tailwind class 指南

```tsx
// 卡片 container
"h-full transition-colors hover:border-primary/40 group"

// 卡片描述（强调）
"text-sm text-muted-foreground line-clamp-2 min-h-[2.5rem]"
// 用 min-h 保证无描述卡片也保持相同高度

// metadata（模型 + 工具 badge）
"flex items-center gap-2 text-xs text-muted-foreground"

// 工具数量 badge
"inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium"

// action 按钮（仅 hover 时）
"opacity-0 group-hover:opacity-100 transition-opacity duration-200"
// 键盘 focus 时也显示
"focus-within:opacity-100"
```

### Component 结构（JSX sketch）

```tsx
// components/agent/agent-card.tsx
<Link href={`/agents/${agent.id}`}>
  <Card className="h-full transition-colors hover:border-primary/40 group">
    <CardHeader className="pb-2">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <CardTitle className="truncate group-hover:text-primary transition-colors">
            {agent.name}
          </CardTitle>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <FavoriteButton agent={agent} />
          <Badge variant={statusVariant}>{statusLabel}</Badge>
        </div>
      </div>

      {/* 强调描述 — 固定高度，使卡片一致 */}
      <p className="text-sm text-muted-foreground line-clamp-2 min-h-[2.5rem]">
        {agent.description || t("noDescription")}
      </p>
    </CardHeader>

    <CardContent className="pt-0">
      {/* 模型 + 工具数量（简洁） */}
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        {agent.model && (
          <span className="flex items-center gap-1">
            <CpuIcon className="size-3.5" />
            {agent.model.display_name}
          </span>
        )}
        {agent.tools.length > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 font-medium">
            <WrenchIcon className="size-3" />
            {agent.tools.length}
          </span>
        )}
      </div>
    </CardContent>

    <CardFooter>
      <div className="flex w-full items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {formattedDate}
        </span>

        {/* 仅 hover 时显示 action 按钮 */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-200">
          <Button variant="ghost" size="icon-sm" asChild>
            <Link href={`/agents/${agent.id}/visual`} onClick={stopProp}>
              <WorkflowIcon className="size-4" />
            </Link>
          </Button>
          <Button variant="ghost" size="icon-sm" asChild>
            <Link href={`/agents/${agent.id}/settings`} onClick={stopProp}>
              <Settings2Icon className="size-4" />
            </Link>
          </Button>
        </div>
      </div>
    </CardFooter>
  </Card>
</Link>
```

### 核心变更摘要

| 区域 | Before | After |
|------|--------|-------|
| 工具显示 | 列出名称（高度可变） | 数量 badge `🔧 3`（固定高度） |
| 描述 | `line-clamp-2` | `line-clamp-2` + `min-h-[2.5rem]` |
| action 按钮 | 始终显示 | `opacity-0 group-hover:opacity-100` |
| 收藏 | 混在 action 区域 | 名称旁独立位置 |
| 卡片高度 | 随工具数量变化 | 统一（保证 min-height） |

### shadcn/ui Component

- `Card`, `CardHeader`, `CardTitle`, `CardContent`, `CardFooter`
- `Badge`（状态显示）
- `Button` (variant: ghost, size: icon-sm)

### 响应式

- grid：`grid gap-4 sm:grid-cols-2 lg:grid-cols-3`（保持现有）
- 移动端（1col）：action 按钮始终显示（`@media (hover: none)` → `opacity-100`）

```tsx
// 在 touch device 上始终显示
"opacity-0 group-hover:opacity-100 focus-within:opacity-100 touch:opacity-100"
// Tailwind v4: @media (hover: none) { opacity: 1 }
```

### Dark mode

- `bg-muted` badge 自动适配 theme
- `text-muted-foreground` 也自动适配 theme
- 无需额外 dark mode class

### 可访问性

- hover 隐藏的按钮通过 `focus-within:opacity-100` 保证键盘可访问
- 必须有 `aria-label`：“设置”“视觉设置”
- 整张卡片是 `<Link>` — 内部按钮使用 `onClick={e => e.stopPropagation()}`

---

## 3. 设置页面 tab 结构

### 问题

当前是 565 行的单一滚动页面。认知负荷高，也很难找到目标 section。

### 解决方案

拆成 4 个 tab + 底部 sticky 保存栏。

```
┌─────────────────────────────────────────────┐
│  ← Back          Agent Name 设置             │
│─────────────────────────────────────────────│
│  [基本信息] [模型] [工具·技能] [触发器]       │  ← Tabs（sticky）
│─────────────────────────────────────────────│
│                                             │
│  （tab 内容区域 — 滚动）                     │
│                                             │
│                                             │
│─────────────────────────────────────────────│
│  [🗑 删除]                        [💾 保存]  │  ← sticky bar
└─────────────────────────────────────────────┘
```

### Tab 拆分

| tab | 内容 | 对应 section（现有行） |
|----|------|----------------------|
| **基本信息** | 名称、描述、system prompt | L181-205 |
| **模型** | 模型选择、Temperature、Top P、Max Tokens、reset | L207-283 |
| **工具·技能** | 工具 checklist、技能 checklist、middleware | L285-391 |
| **触发器** | 现有 trigger 列表、新增 trigger form | L393-520 |

### Tailwind class 指南

```tsx
// tab list（sticky）
"sticky top-0 z-10 bg-background/95 backdrop-blur-sm border-b"

// tab 内容区域
"flex-1 overflow-auto py-6"

// 各 tab 内容内部
"mx-auto w-full max-w-2xl space-y-6"

// 底部 sticky 保存栏
"sticky bottom-0 border-t bg-background/95 backdrop-blur-sm px-6 py-3"

// 保存栏 layout
"mx-auto flex w-full max-w-2xl items-center justify-between"
```

### Component 结构（JSX sketch）

```tsx
// app/agents/[agentId]/settings/page.tsx（重构后）
export default function AgentSettingsPage() {
  const [activeTab, setActiveTab] = useState("basic");

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* header */}
      <div className="px-6 pt-6 pb-4">
        <BackButton />
        <PageHeader title={`${agent.name} ${t("title")}`} />
      </div>

      {/* tab navigation（sticky） */}
      {/* i18n: useTranslations("agent.settings") → t("tabs.basic") = "agent.settings.tabs.basic" */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <div className="sticky top-0 z-10 bg-background/95 backdrop-blur-sm border-b px-6">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="basic">{t("tabs.basic")}</TabsTrigger>
            <TabsTrigger value="model">{t("tabs.model")}</TabsTrigger>
            <TabsTrigger value="tools">{t("tabs.tools")}</TabsTrigger>
            <TabsTrigger value="triggers">{t("tabs.triggers")}</TabsTrigger>
          </TabsList>
        </div>

        {/* tab 内容（scroll） */}
        <div className="flex-1 overflow-auto px-6 py-6">
          <div className="mx-auto w-full max-w-2xl">
            <TabsContent value="basic">
              <BasicInfoTab />
            </TabsContent>
            <TabsContent value="model">
              <ModelTab />
            </TabsContent>
            <TabsContent value="tools">
              <ToolsSkillsTab />
            </TabsContent>
            <TabsContent value="triggers">
              <TriggersTab />
            </TabsContent>
          </div>
        </div>
      </Tabs>

      {/* 底部 sticky 保存栏 */}
      <div className="sticky bottom-0 border-t bg-background/95 backdrop-blur-sm px-6 py-3">
        <div className="mx-auto flex w-full max-w-2xl items-center justify-between">
          <DeleteAgentButton agentId={agentId} />
          <Button onClick={handleSave} disabled={isSaving}>
            {isSaving ? <Loader2Icon className="size-4 animate-spin" /> : <SaveIcon className="size-4" />}
            {t("save")}
          </Button>
        </div>
      </div>
    </div>
  );
}
```

### 文件拆分指南

```
app/agents/[agentId]/settings/
├── page.tsx                    # tab container + 保存栏 (~80 行)
├── _components/
│   ├── basic-info-tab.tsx      # 名称、描述、system prompt (~60 行)
│   ├── model-tab.tsx           # 模型选择、参数 slider (~100 行)
│   ├── tools-skills-tab.tsx    # 工具/技能/middleware checklist (~120 行)
│   └── triggers-tab.tsx        # trigger 列表 + 新增 form (~150 行)
```

### shadcn/ui Component

- `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`
- 保留当前使用的所有 component（Badge, Button, Input, Textarea, Slider 等）

### 响应式

- tab：移动端允许 `overflow-x-auto` 横向滚动
- 保存栏：移动端 `flex-col gap-2` → 按钮纵向排列

```tsx
// 移动端 tab scroll
"overflow-x-auto scrollbar-none"

// 移动端保存栏
"flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between"
```

### Dark mode

- `bg-background/95 backdrop-blur-sm` 自动适配 theme
- `border-b`, `border-t` 也使用 theme variable，自动适配

### 可访问性

- `Tabs` 由 shadcn/ui 自动处理 aria-role（`role="tablist"`, `role="tab"`, `role="tabpanel"`）
- 键盘：左右箭头切换 tab
- 可考虑保存快捷键：`Ctrl+S` / `Cmd+S` 绑定（可选）

### 状态管理注意事项

- 切换 tab 时必须**保留 form 状态**。各 tab 共享父 component state。
- 将 `useState` 保留在 page.tsx，并通过 props 传给各 tab component。
- 或用 `useReducer` 统一管理 form state。

---

## 4. Breadcrumb 设计

### 问题

1. 当前 `app-header.tsx` 只有 `Separator(orientation="vertical")`，没有路径信息
2. 用户难以判断当前所在位置
3. 深层路径（Agent → 设置）返回不方便

### 解决方案

基于路径自动生成 breadcrumb。移除 Separator（竖线）。

```
┌─────────────────────────────────────────────────┐
│  [≡]  首页 / Agent / MyBot / 设置              │
└─────────────────────────────────────────────────┘
```

### 路径映射

| URL pattern | breadcrumb |
|----------|-----------|
| `/` | 首页 |
| `/agents/[id]` | 首页 / Agent / {agent.name} |
| `/agents/[id]/chat` | 首页 / Agent / {agent.name} / 聊天 |
| `/agents/[id]/settings` | 首页 / Agent / {agent.name} / 设置 |
| `/tools` | 首页 / 工具 |
| `/models` | 首页 / 模型 |
| `/usage` | 首页 / 使用量 |
| `/settings` | 首页 / 设置 |

### Tailwind class 指南

```tsx
// breadcrumb container
"flex items-center gap-1.5 text-sm"

// breadcrumb item（link）
"text-muted-foreground hover:text-foreground transition-colors duration-200"

// 当前页面（最后一个 item）
"text-foreground font-medium truncate max-w-[200px]"

// separator（chevron）
"text-muted-foreground/60 size-3.5"
```

### Component 结构（JSX sketch）

```tsx
// components/layout/breadcrumb-nav.tsx
"use client";

import { usePathname } from "next/navigation";
import { ChevronRightIcon, HomeIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

// static 路径 mapping
const ROUTE_LABELS: Record<string, string> = {
  agents: "nav.agents",
  tools: "nav.tools",
  models: "nav.models",
  usage: "nav.usage",
  settings: "nav.settings",
  chat: "nav.chat",
  create: "nav.create",
};

export function BreadcrumbNav() {
  const pathname = usePathname();
  const t = useTranslations();
  const segments = pathname.split("/").filter(Boolean);

  if (segments.length === 0) return null; // 首页隐藏

  const crumbs = segments.map((segment, index) => {
    const href = "/" + segments.slice(0, index + 1).join("/");
    const isLast = index === segments.length - 1;
    const isId = /^[0-9a-f-]+$/.test(segment); // 检测 UUID

    return { segment, href, isLast, isId };
  });

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm">
      {/* 首页 icon */}
      <Link
        href="/"
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        <HomeIcon className="size-4" />
      </Link>

      {crumbs.map(({ segment, href, isLast, isId }) => (
        <Fragment key={href}>
          <ChevronRightIcon className="size-3.5 text-muted-foreground/60" />
          {isLast ? (
            <span className="text-foreground font-medium truncate max-w-[200px]">
              {isId ? <AgentName id={segment} /> : t(ROUTE_LABELS[segment] ?? segment)}
            </span>
          ) : (
            <Link
              href={href}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              {isId ? <AgentName id={segment} /> : t(ROUTE_LABELS[segment] ?? segment)}
            </Link>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
```

### app-header.tsx 变更

```tsx
// Before
export function AppHeader() {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger />
      <Separator orientation="vertical" className="mr-2 h-4" />
    </header>
  );
}

// After
export function AppHeader() {
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4">
      <SidebarTrigger />
      <BreadcrumbNav />
    </header>
  );
}
```

### shadcn/ui Component

- 移除 `Separator`
- 自定义 `BreadcrumbNav` component（shadcn 若有 Breadcrumb 可利用，但 @base-ui 没有，因此自行实现）

### 响应式

- 移动端：只显示最后 2 个 segment + `...` 折叠

```tsx
// 移动端折叠（3 个以上 segment）
"hidden sm:flex"      // 隐藏中间 segment
"flex sm:hidden"      // 显示折叠（…）
```

### Dark mode

- `text-muted-foreground`, `text-foreground` 自动适配 theme
- 无需额外 dark mode class

### 可访问性

- `<nav aria-label="Breadcrumb">` landmark
- 当前页面：添加 `aria-current="page"`
- separator：`aria-hidden="true"`（screen reader 忽略）

### 动态名称解析

路径中存在 Agent ID(UUID) 时显示名称：
- 从 TanStack Query cache 查询 Agent 名称
- cache 中没有则显示缩略 ID（`agent-abc...`）

---

## 5. App 设置页面

### 问题

目前没有管理整个 App 设置（theme、language、profile）的页面。

### 解决方案

采用 card-based 设置 layout。每组设置拆成独立 card。

```
┌─────────────────────────────────────────────┐
│  App 设置                                     │
│─────────────────────────────────────────────│
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  👤 Profile                           │    │
│  │  名称：Mock User                     │    │
│  │  Email：mock@moldy.ai                │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌─────────────┐  ┌─────────────────────┐   │
│  │  🎨 Theme     │  │  🌐 Language         │   │
│  │             │  │                     │   │
│  │  ○ Light   │  │  ● 韩语                │   │
│  │  ● Dark    │  │  ○ English          │   │
│  │  ○ System  │  │                     │   │
│  └─────────────┘  └─────────────────────┘   │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  🔑 API key 管理                      │    │
│  │  OpenAI: ●●●●●●●●sk-...abc         │    │
│  │  Anthropic：未设置             [设置]  │    │
│  └─────────────────────────────────────┘    │
│                                             │
└─────────────────────────────────────────────┘
```

### Tailwind class 指南

```tsx
// 页面 container
"flex flex-1 flex-col gap-6 overflow-auto p-6"

// 内容区域
"mx-auto w-full max-w-2xl space-y-6"

// 设置 card
"rounded-xl ring-1 ring-foreground/10 bg-card p-6"

// card title
"flex items-center gap-2 text-base font-semibold"

// 设置 item row
"flex items-center justify-between py-3"

// divider
"border-t border-foreground/5"

// 2-column grid（theme + language）
"grid gap-4 sm:grid-cols-2"

// radio option
"flex items-center gap-3 rounded-lg border p-3 cursor-pointer hover:bg-accent transition-colors duration-200"
"data-[state=checked]:border-primary data-[state=checked]:bg-primary/5"
```

### Component 结构（JSX sketch）

```tsx
// app/settings/page.tsx
export default function SettingsPage() {
  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto p-6">
      <PageHeader title={t("title")} description={t("description")} />

      <div className="mx-auto w-full max-w-2xl space-y-6">
        {/* Profile card（full width） */}
        <ProfileCard />

        {/* Theme + Language（2-column） */}
        <div className="grid gap-4 sm:grid-cols-2">
          <ThemeCard />
          <LanguageCard />
        </div>

        {/* API key 管理（full width） */}
        <ApiKeysCard />
      </div>
    </div>
  );
}
```

```tsx
// theme card 示例
function ThemeCard() {
  const { theme, setTheme } = useTheme();
  const t = useTranslations("settings.theme");

  const themes = [
    { value: "light", label: t("light"), icon: SunIcon },
    { value: "dark", label: t("dark"), icon: MoonIcon },
    { value: "system", label: t("system"), icon: MonitorIcon },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <PaletteIcon className="size-4" />
          {t("title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {themes.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            onClick={() => setTheme(value)}
            className={cn(
              "flex w-full items-center gap-3 rounded-lg border p-3",
              "cursor-pointer hover:bg-accent transition-colors",
              theme === value && "border-primary bg-primary/5"
            )}
          >
            <Icon className="size-4" />
            <span className="text-sm font-medium">{label}</span>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
```

### shadcn/ui Component

- `Card`, `CardHeader`, `CardTitle`, `CardContent`
- `Button`
- `Input`（编辑 profile 时）
- `PageHeader`

### 响应式

- 2-column grid → 移动端 1-column：`grid gap-4 sm:grid-cols-2`
- API key 值：移动端 `truncate` + tooltip

### Dark mode

- theme toggle 位于该页面，因此需确认即时生效
- `bg-primary/5` 自动适配 theme

### 可访问性

- theme/language 选择：`role="radiogroup"` + `role="radio"` + `aria-checked`
- 或使用 semantic `<fieldset>` + `<input type="radio">`
- API key：masked value 加 `aria-label="API key (hidden)"`
- 每张 card：`<section aria-labelledby="section-title-id">` landmark
- focus 顺序：profile → theme → language → API key（与视觉顺序一致）
- theme 变更时在 `aria-live="polite"` 区域提示“主题已更改”

---

## 6. 工具详情 Dialog

### 问题

工具详情目前以 `Sheet`（侧栏）打开，但其他所有详情/编辑 UI 都使用 `Dialog`（中央 modal）。一致性被打破。

### 解决方案

将 `Sheet` → `Dialog`。保留现有内容结构。

```
┌──────────────────────────────────────────┐
│                                          │
│   ┌──────────────────────────────────┐   │
│   │  [×]                             │   │
│   │  Web Search (DuckDuckGo)         │   │
│   │  使用 DuckDuckGo 搜索引擎...       │   │
│   │                                  │   │
│   │  类型：prebuilt    标签：search     │   │
│   │                                  │   │
│   │  ┌──────────────────────────┐    │   │
│   │  │  参数                     │    │   │
│   │  │  query  string  必填     │    │   │
│   │  │  limit  integer 可选     │    │   │
│   │  └──────────────────────────┘    │   │
│   │                                  │   │
│   │  认证：已设置服务器 key ✓         │   │
│   │                                  │   │
│   └──────────────────────────────────┘   │
│                                          │
└──────────────────────────────────────────┘
```

### Tailwind class 指南

```tsx
// Dialog 内容（中央 modal）
"sm:max-w-lg max-h-[85vh] overflow-auto"

// section 间距
"space-y-5 pt-4"

// metadata badge 区域
"flex flex-wrap gap-2"

// 参数 table
"rounded-lg border divide-y"

// table row
"flex items-center px-3 py-2 text-sm"

// table cell
"flex-1" // 名称
"w-20 text-muted-foreground" // 类型
"w-16 text-right" // 必填/可选
```

### Component 结构（JSX sketch）

```tsx
// Before (Sheet)
<Sheet open={!!detailTool} onOpenChange={(open) => { if (!open) setDetailTool(null) }}>
  <SheetContent className="sm:max-w-lg overflow-auto">
    <SheetHeader>
      <SheetTitle>{detailTool.name}</SheetTitle>
      <SheetDescription>{detailTool.description}</SheetDescription>
    </SheetHeader>
    {/* ... 内容 ... */}
  </SheetContent>
</Sheet>

// After (Dialog)
<Dialog open={!!detailTool} onOpenChange={(open) => { if (!open) setDetailTool(null) }}>
  <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-auto">
    <DialogHeader>
      <DialogTitle>{detailTool.name}</DialogTitle>
      <DialogDescription>{detailTool.description}</DialogDescription>
    </DialogHeader>
    {/* ... 内容（相同） ... */}
  </DialogContent>
</Dialog>
```

### 变更范围

| 变更 | Before | After |
|------|--------|-------|
| Component | `Sheet` | `Dialog` |
| import | `SheetContent`, `SheetHeader`, `SheetTitle`, `SheetDescription` | `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription` |
| class | `sm:max-w-lg overflow-auto` | `sm:max-w-lg max-h-[85vh] overflow-auto` |
| 位置 | 右侧侧栏（slide） | 中央 modal（fade+zoom） |
| 内容 | 无变更 | 无变更 |

### shadcn/ui Component

- `Dialog`, `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription`
- `Badge`（显示类型、tag — 保持现有）

### 响应式

- `sm:max-w-lg`：桌面端限制宽度
- 移动端：Dialog 扩展到全宽（shadcn Dialog 默认行为）
- `max-h-[85vh] overflow-auto`：内容过长时 scroll

### Dark mode

- Dialog component 自动适配 theme（bg-background, text-foreground）
- 无需额外 dark mode class

### 可访问性

- Dialog 自动提供 modal focus trap（与 Sheet 相同）
- `Escape` 键关闭（与现有相同）
- 自动连接 `aria-labelledby`, `aria-describedby`
- 参数 table：`role="table"` + `role="row"` + `role="cell"` 或 semantic `<table>`
- 关闭按钮：`aria-label="关闭"`（自动应用到 DialogContent 的 X 按钮）
- 打开时首次 focus：移动到 DialogTitle（默认行为）

---

## 实现优先级

| 顺序 | 项目 | 难度 | 影响度 | 对应 story |
|------|------|--------|--------|------------|
| 1 | Coming Soon 模式 | 🟢 低 | 中 | S4 |
| 2 | 工具详情 Dialog | 🟢 低 | 中 | S3 |
| 3 | Agent 卡片重设计 | 🟡 中 | 高 | S4 |
| 4 | Breadcrumb 设计 | 🟡 中 | 高 | S5 |
| 5 | 设置页面 tab 结构 | 🔴 高 | 高 | S7 |
| 6 | App 设置页面 | 🟡 中 | 中 | S6 |

---

## 通用注意事项

### Tailwind v4 注意

- 建议直接使用 utility class，而不是 `@apply`
- 基于 CSS variable 的 theme：`bg-background`, `text-foreground` 等在 `@theme` block 中定义
- theme 自动切换依赖 CSS variable，而不是 `dark:` prefix

### shadcn/ui（基于 @base-ui）注意

- 某些情况下使用 `data-[...]` attribute，而不是 `data-[state=...]`
- 实现前必须检查 `frontend/src/components/ui/` 中对应 component 代码
- `Trigger` → `TabsTrigger`（shadcn），命名可能不同

### Transition 指南

| 用途 | Duration | Easing |
|------|----------|--------|
| hover 颜色变化 | 150ms | ease-out |
| opacity 过渡 | 200ms | ease-out |
| modal/sheet 进入 | 200ms | ease-out |
| tab 切换 | 150ms | ease-out |

### i18n key 结构

```json
{
  "common": {
    "comingSoon": {
      "default": "此功能正在准备中",
      "fileAttach": "文件附件功能正在准备中"
    }
  },
  "settings": {
    "title": "设置",
    "tabs": {
      "basic": "基本信息",
      "model": "模型",
      "tools": "工具·技能",
      "triggers": "触发器"
    },
    "theme": {
      "title": "主题",
      "light": "浅色",
      "dark": "深色",
      "system": "系统"
    },
    "language": {
      "title": "语言"
    }
  },
  "nav": {
    "agents": "Agent",
    "tools": "工具",
    "models": "模型",
    "usage": "使用量",
    "settings": "设置",
    "chat": "聊天",
    "create": "新建"
  }
}
```
