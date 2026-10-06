# Agent Edit Workbench — Design Spec

**Status**: Active
**Owner**: Satya（PO）/ Zuckerberg（实现）
**Plan**: `~/.claude/plans/image-41-ticklish-sky.md`
**Created**: 2026-04-28

---

## 1. 目标

将 `/agents/[agentId]/settings` 重新设计为**单一集成工作台**。
- 左侧：通过 form/visual toggle 编辑 agent 设置
- 右侧：Fix·测试·开场问题·日程·设置 5-tab panel（永久显示）
- Header：名称/说明 inline 编辑 + 小 avatar + 保存/删除

---

## 2. 页面树

```
AgentSettingsPage (page.tsx)
├── Header（inline）
│   ├── BackButton
│   ├── AgentAvatar (sm)
│   ├── InlineInput name (ghost)
│   ├── InlineInput description (ghost)
│   ├── DeleteButton
│   └── SaveButton (with isDirty)
└── MainGrid (lg:grid-cols-2 stack on mobile)
    ├── LeftPanel
    │   ├── Tabs [表单 | 可视化]
    │   └── TabsContent
    │       ├── 'form' → FormMode
    │       │   ├── SectionInstructions (collapsible, fullscreen, char-count)
    │       │   ├── SectionSubAgents（行 + [⚙]）
    │       │   ├── SectionModel（行 + [⚙]）
    │       │   └── ToolsMiddlewaresGrid (2col)
    │       │       ├── ToolsBox（[+工具]，行列表）
    │       │       └── MiddlewaresBox（[+中间件]，行列表）
    │       └── 'visual' → VisualSettingsFlow (inline, ReactFlowProvider)
    └── RightPanel
        ├── Tabs [Fix | 测试 | 开场问题 | 日程 | 设置]
        └── TabsContent
            ├── 'fix' → AssistantPanel (showHeader=false)
            ├── 'test' → TestChatPanel（新增）
            ├── 'opener' → OpenerEditor（新增）
            ├── 'schedule' → TriggersTab（复用）
            └── 'settings' → SettingsPanel（仅图像）

Dialogs (state-controlled)
├── ModelDialog（模型选择 + 参数 slider）
├── SubAgentsDialog（选择 skills）
├── AddToolModal（选择 tools）
└── AddMiddlewareModal（选择 middlewares）
```

---

## 3. Header inline 编辑模式

```tsx
<header className="flex items-start gap-3 border-b px-6 py-4">
  <Button variant="ghost" size="icon-sm" onClick={handleBack}>
    <ArrowLeftIcon className="size-4" />
  </Button>
  <AgentAvatar imageUrl={imageUrl} name={name} size="sm" />
  <div className="flex-1 min-w-0 space-y-0.5">
    <Input
      value={name}
      onChange={(e) => onNameChange(e.target.value)}
      className="border-0 bg-transparent px-0 text-lg font-semibold shadow-none focus-visible:ring-0 focus-visible:bg-muted/40"
      placeholder={t('namePlaceholder')}
    />
    <Input
      value={description}
      onChange={(e) => onDescriptionChange(e.target.value)}
      className="border-0 bg-transparent px-0 text-xs text-muted-foreground shadow-none focus-visible:ring-0 focus-visible:bg-muted/40"
      placeholder={t('descriptionPlaceholder')}
    />
  </div>
  <div className="flex items-center gap-2">
    <DeleteAlertDialog ... />
    <Button onClick={handleSave} disabled={!isDirty || isPending}>
      {isPending ? <Loader2Icon className="mr-1 size-4 animate-spin" /> : null}
      {t('save')}
    </Button>
  </div>
</header>
```

核心：用 ghost variant 让 input 平时看起来像 plain text，在 focus/hover 时用 muted 背景显示可编辑状态。

---

## 4. 左侧表单模式 section pattern

### 4.1 通用 section header（行模式）

```tsx
<div className="flex items-center justify-between rounded-md border px-4 py-3">
  <div className="flex items-center gap-2 min-w-0">
    <Icon className="size-4 text-muted-foreground" />
    <span className="text-sm font-medium">{label}</span>
    <span className="text-sm text-muted-foreground truncate">{summary}</span>
  </div>
  <Button variant="ghost" size="icon-sm" onClick={openDialog}>
    <SettingsIcon className="size-4" />
  </Button>
</div>
```

### 4.2 指令 section（collapsible + fullscreen）

```tsx
<Collapsible defaultOpen>
  <div className="flex items-center justify-between">
    <CollapsibleTrigger className="flex items-center gap-1">
      <ChevronDownIcon /> 指令
    </CollapsibleTrigger>
    <Button variant="ghost" size="icon-sm" onClick={() => setFullscreen(true)}>
      <MaximizeIcon className="size-4" />
    </Button>
  </div>
  <CollapsibleContent>
    <Textarea value={systemPrompt} onChange={...} rows={12} className="font-mono text-xs" />
    <div className="text-right text-xs text-muted-foreground">{count} 字</div>
  </CollapsibleContent>
</Collapsible>

<Dialog open={fullscreen} onOpenChange={setFullscreen}>
  <DialogContent className="max-w-5xl">
    <Textarea value={systemPrompt} onChange={...} className="h-[70vh]" />
  </DialogContent>
</Dialog>
```

### 4.3 工具·中间件 grid（2 列）

```tsx
<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
  <ToolsBox tools={...} selectedIds={...} onAdd={openAddToolModal} onRemove={...} />
  <MiddlewaresBox middlewares={...} selectedTypes={...} onAdd={openAddMiddlewareModal} onRemove={...} />
</div>
```

每个 box 结构：
```tsx
<div className="rounded-md border">
  <div className="flex items-center justify-between border-b px-4 py-2">
    <CollapsibleTrigger className="flex items-center gap-1">
      <ChevronDownIcon /> {label}
    </CollapsibleTrigger>
    <Button size="sm" onClick={onAdd}>
      <PlusIcon className="size-4" /> {addLabel}
    </Button>
  </div>
  <div className="divide-y">
    {selected.map(item => (
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-2">
          <ItemIcon /> <span>{item.name}</span>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" onClick={() => onConfig(item)}>
            <SettingsIcon className="size-3.5" />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => onRemove(item)}>
            <Trash2Icon className="size-3.5" />
          </Button>
        </div>
      </div>
    ))}
    {selected.length === 0 && (
      <div className="px-4 py-6 text-center text-sm text-muted-foreground">
        {emptyLabel}
      </div>
    )}
  </div>
</div>
```

---

## 5. Dialog 规范

### 5.1 ModelDialog

```ts
interface ModelDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  modelId: string
  onModelIdChange: (v: string) => void
  temperature: number
  onTemperatureChange: (v: number) => void
  topP: number
  onTopPChange: (v: number) => void
  maxTokens: number
  onMaxTokensChange: (v: number) => void
  onReset: () => void
}
```
- 内容：保持现有 `ModelTab` 内容不变（ModelSelect + 3 个 slider + reset 按钮）
- 关闭时 changes 已经反映在页面 state 中（controlled）

### 5.2 SubAgentsDialog

```ts
interface SubAgentsDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  selectedSkillIds: Set<string>
  onToggleSkill: (id: string) => void
}
```
- 内容：`useSkills` hook + Checkbox 列表（复用当前 `tools-skills-tab.tsx` 的 skills 区域）
- 若为空则 link 到 `/skills` route

### 5.3 AddToolModal / AddMiddlewareModal

相同模式：
- 搜索 input（可选）+ 分类 category（可选）
- Checkbox 列表
- 已选择项显示“已添加” badge + Checkbox checked
- modal 关闭时 selection 反映到页面 state

---

## 6. 右侧 panel 规范

### 6.1 RightPanel（tab container）

```tsx
<Tabs value={tab} onValueChange={setTab}>
  <TabsList className="border-b bg-background sticky top-0 z-10">
    <TabsTrigger value="fix"><WrenchIcon /> Fix agent</TabsTrigger>
    <TabsTrigger value="test"><MessageSquareIcon /> 测试</TabsTrigger>
    <TabsTrigger value="opener"><HelpCircleIcon /> 开场问题</TabsTrigger>
    <TabsTrigger value="schedule"><ClockIcon /> 日程</TabsTrigger>
    <TabsTrigger value="settings"><SettingsIcon /> 设置</TabsTrigger>
  </TabsList>
  <TabsContent value="fix"><AssistantPanel showHeader={false} ... /></TabsContent>
  <TabsContent value="test"><TestChatPanel ... /></TabsContent>
  <TabsContent value="opener"><OpenerEditor questions onChange ... /></TabsContent>
  <TabsContent value="schedule"><TriggersTab agentId onRequestDelete ... /></TabsContent>
  <TabsContent value="settings"><SettingsPanel agentId imageUrl name ... /></TabsContent>
</Tabs>
```

### 6.2 TestChatPanel（新增）

- 普通 agent 聊天。对话 history 仅在 session 内由 local state 管理（不保存到服务器）
- 初始实现：不用 Fix 专用 `streamAssistant`，而是使用普通 conversation stream
- 空白页面 empty state 显示 `agent.opener_questions` 按钮 → 点击后注入 composer 文本（不发送）

### 6.3 OpenerEditor（新增）

```ts
interface OpenerEditorProps {
  questions: string[]
  onChange: (questions: string[]) => void
  max?: number  // default 12
}
```

布局：
- Header：“设置用户可用于开始对话的示例问题” + `n/12` counter + `[+ 添加]` 按钮
- 行：编号 + Input（1~200 字符）+ `[🗑]`
- 空状态：“没有示例问题” + 添加按钮

### 6.4 SettingsPanel（仅图像）

```tsx
<div className="flex flex-col items-center gap-4 p-6">
  <AgentAvatar imageUrl={imageUrl} name={name} size="xl" />
  <Button onClick={generate} disabled={isPending}>
    {imageUrl ? '重新生成图像' : '生成图像'}
  </Button>
  {imageUrl && (
    <Button variant="ghost" onClick={remove}>
      移除图像
    </Button>
  )}
</div>
```

---

## 7. State 流程

页面组件（`settings/page.tsx`）持有全部 form state：

```ts
const [name, setName] = useState('')
const [description, setDescription] = useState('')
const [systemPrompt, setSystemPrompt] = useState('')
const [modelId, setModelId] = useState('')
const [selectedToolIds, setSelectedToolIds] = useState<Set<string>>(new Set())
const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(new Set())
const [temperature, setTemperature] = useState(0.7)
const [topP, setTopP] = useState(1.0)
const [maxTokens, setMaxTokens] = useState(4096)
const [selectedMiddlewareTypes, setSelectedMiddlewareTypes] = useState<Set<string>>(new Set())
const [openerQuestions, setOpenerQuestions] = useState<string[]>([])  // 新增
```

dialog·modal·右侧 panel 全部 controlled — 直接操作页面 state。

`isDirty` = 将上述所有值与原始值（来自 useAgent 的 `agent`）比较。

保存使用单一 `[保存]` 按钮 → `useUpdateAgent.mutate({...all fields})`。

---

## 8. 新聊天空白页显示开场问题

进入新聊天时，如果存在 `agent.opener_questions`，则在 empty state 中渲染为按钮组：

```tsx
<div className="flex flex-wrap justify-center gap-2">
  {agent.opener_questions?.map((q) => (
    <button
      key={q}
      onClick={() => composer.setText(q)}  // 不发送，只注入输入框
      className="rounded-full border px-3 py-1 text-xs hover:bg-accent"
    >
      {q}
    </button>
  ))}
</div>
```

使用 `useComposer` hook（assistant-ui）。仅通过 `setText` 设置 composer 输入值，submit 留给用户操作。

---

## 9. i18n key

```jsonc
{
  "agent": {
    "settings": {
      "tabs": {
        "form": "表单", "visual": "可视化",
        "fix": "Fix agent", "test": "测试", "opener": "开场问题",
        "schedule": "日程", "settings": "设置"
      },
      "subAgents": "子 agent",
      "subAgentsEmpty": "没有子 agent",
      "model": "模型",
      "tools": "工具箱",
      "addTool": "+ 工具",
      "middlewares": "中间件",
      "addMiddleware": "+ 中间件",
      "instructionFullscreen": "全屏",
      "characterCount": "{count} 字"
    },
    "opener": {
      "title": "开场问题",
      "description": "设置用户可用于开始对话的示例问题",
      "counter": "{count}/{max}",
      "add": "+ 添加",
      "placeholder": "输入示例问题",
      "empty": "没有示例问题",
      "maxReached": "最多可添加 {max} 个"
    },
    "image": {
      "generate": "生成图像",
      "regenerate": "重新生成图像",
      "remove": "移除图像"
    }
  }
}
```

---

## 10. 验证场景

1. 进入 route `/agents/{id}/settings` → 左（表单）/右（Fix）分栏
2. 修改 header 名称/说明 → [保存] 激活
3. [表单] → [可视化] → 渲染 ReactFlow graph
4. 行 [⚙] → dialog → 修改 → 关闭 → 更新行摘要
5. [+工具] → modal → 勾选 → 关闭 → 在左侧 grid 的左列新增行
6. [+中间件] → modal → 勾选 → 关闭 → 在左侧 grid 的右列新增行
7. 行 [🗑] → 立即移除（保存前仅修改 page state）
8. 右侧 [开场问题] → 添加/删除/排序 → [保存]
9. 右侧 [设置] → 生成/重新生成/移除图像
10. 进入新对话 → empty state 显示开场问题按钮 → 点击 → 注入输入框（不发送）
11. 有未保存内容时点击 [←] → confirm
