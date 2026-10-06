# Moldy Chat Design Contract

## Baseline

本文档是迁移到 assistant-ui 0.15 时需要保留的当前 Moldy 聊天的
源代码基线。并非通过观察外部产品或 Aside UI 后复制得到的基线。

- `@assistant-ui/react` 负责消息·composer·工具渲染表面。
- 现有 Moldy SSE 和 LangGraph v3 BFF 是执行状态的基准。UI 库
  更新不会改变传输协议或 checkpoint 生命周期。
- 基础对话、Builder、Assistant Panel 共享相同的消息 primitive，但
  保持各表面的工具及 HITL 策略。

## Layout and surfaces

- thread 使用完整纵向高度，并将可滚动的 transcript 与底部固定
  composer 分离。
- 普通 transcript 宽度为 `max-w-3xl`，Builder transcript 宽度为 `max-w-4xl`。
- 用户消息使用右对齐的 primary bubble 和用户 avatar。
  assistant 消息在左侧 avatar 后以平面 content column 渲染。
- artifact 和 subagent 详情在现有 right rail 中打开。移动端 artifact layer 和
  rail 宽度/resize 行为作为独立 Moldy surface 契约保留。
- surface, radius, shadow, status 使用 `moldy-*` 类和 semantic token。
- `DialogShell` 无论指定尺寸如何，都必须保持在 viewport 左右 1rem gutter 内
  。双列选择器在低于 1024px 时切换为单列，并限制当前选择列表的高度
  ，以便能在同一滚动流中使用后续浏览区域和关闭操作。
- 韩文说明文案使用 `break-keep` 和
  均衡的 wrapping，避免单词内部最后一个音节被孤立。对于 URL、电子邮件、用户输入等较长的不可分段值
  ，设置单独的 `break-words` 或横向滚动边界。
- 设置侧边栏的 navigation 区域与底部 utility footer 互不重叠。
  菜单增加时保持 navigation 滚动，并同时验证分组密度和底部边界，以免最后一项在 footer 边界处
  被部分裁切。

## Interaction contract

- 在重复导航之前放置可通过键盘聚焦的跳过正文链接，应用 shell 的
  `main` landmark 每个页面只保留一个。
- `primary-strong` 背景上的文本使用各主题的 `primary-strong-foreground` token
  ，小型状态徽标和侧边栏 caption 也必须满足 WCAG AA 明度对比度。
- Enter 用于发送，Shift+Enter 用于换行，在韩文 IME 组合过程中不发送。
- 运行中时，Stop 使用当前 run 的取消路径。失败消息保留在 transcript 中
  ，并提供重试 affordance。
- 附件保留在 composer 和消息中，并遵循 paste/add-attachment capability。
- 保持编辑、重新生成、branch picker、copy、feedback、token usage、timestamp 行为
  以及消息 metadata。
- streaming loading, tool state, HITL decision, subagent progress, artifact cards,
  reconnect indicator、memory/compaction 显示继续以服务器事件为准。
- `ask_user` 与 HITL 审批使用相同的 pending-interaction 卡片语法(状态头、正文、
  底部 action)。多个决策不纵向堆叠卡片，而是一次只显示一个步骤
  ，并在最后一步通过现有 LangGraph `Decision[]` 契约恢复一次。
- pending-interaction 卡片属于正常的用户判断步骤，因此使用 `bg-card` 中性表面
  。不使用代表危险·错误的整块警告色背景，状态区分仅限于
  头部图标和实际批准·拒绝 action 的颜色。
- 运行中的消息默认保存到服务器队列。Steer 使用 `等待 → 准备立即发送
→ 发送中` 的显式状态迁移，第一次点击只改变本地确认状态
  ，只有第二次点击 `立即发送` 时才请求取消当前 run 并优先执行。
  编辑、顺序变更、删除继续保留为每项的辅助菜单。
- 当前 Todo 保持模型发送的顺序，避免扭曲工作流。顶部计划在
  折叠状态下也汇总完成数量和当前进行项，transcript 中过去的
  `write_todos` 调用默认折叠，以减少与当前计划的视觉竞争。
- 当 transcript 离开底部时显示 scroll-to-bottom control，搜索仅在
  当前 viewport 可见时通过 Cmd/Ctrl+F 打开。

## assistant-ui 0.15 compatibility

- scope action 使用 `useAui()` 的 property accessor(`aui.thread`, `aui.composer`,
  `aui.message`)。如果 scope 为可选，则通过 `aui.optional.<scope>`
  检查 availability。
- 状态订阅使用 `useAuiState`。不使用已移除的 legacy runtime/context hook
  。
- LangChain 消息转换器遵循 0.0.29 的单-message 返回契约，同时保留 Moldy 的
  usage, branch, terminal notice, `moldy_ui` data part metadata。
- tool renderer 通过 `defineToolkit` domain registry 声明，并向各 runtime
  provider 注入 `AuiConfig({ tools: Tools({ toolkit }) })`。renderer
  只显示 backend 执行的 tool call，不添加 client executor。
- main chat 和 Assistant Panel 使用包含 approval 的 `ALL_TOOLKIT`，settings 测试
  chat 使用仅排除 paused-run HITL 的 `SETTINGS_TEST_TOOLKIT`，Builder 使用专用
  `BUILDER_TOOLKIT`。
- 未注册的 tool 由 grouped-parts fallback 处理，并保持 search-shaped 结果的
  rich rendering。`DataUI` 继续使用现有 `AssistantThread` 注册路径
  。

## Selected text and side chat

- Codex 参考图像提供三种操作(添加到聊天 / 查看更多详情 / 在侧边聊天中
  提问)作为白色选择菜单提供。工具输出或按钮文本不作为选择对象
  ，仅引用同一消息正文中选中的文本。
- 引用 chip 区分原文、来源对话、所选消息和用户评论。通过 hover·focus
  支持预览，点击可编辑评论·跳转原文，并可单独移除。原文不修改。
- 主聊天和侧边聊天使用同一个 agent，但将对话 ID、执行、输入草稿、
  队列和 runtime 状态分离。传递只使用明确选中的引用，不会自动复制整个
  对话。也不替代现有设置用 Assistant 或文件查看器。
- 侧边对话保存在服务器上，但不会自动显示在普通列表中。关闭面板
  不等于删除，而是通过显式保存操作转换为普通对话。不会标记为临时·自动删除
  。移动端使用单一焦点 dialog，桌面端使用右侧分栏面板。
- 父级-侧边连接存入 DB，刷新后仍打开同一对话。删除父级时
  隐藏的侧边记录保留在普通列表中。需要 M77 迁移。
- 使用 base-ui anchored popover 的 collision/focus/escape 行为。参考 beui tooltip 的
  hover·focus·touch 可访问性原则，但不安装额外 motion 库。
  颜色切换使用现有 150ms token，在 reduced-motion 下移除运动。

## MCP Apps policy

- MCP Apps 的 resource 读取和 tool 调用只使用与对话·run·tool-call 绑定的服务器 proxy
  。浏览器中的 URI, server ID, binding ID, URL, credential 不能作为权限依据
  。
- app iframe 在无额外 form, popup, download 权限的情况下隔离，resource CSP
  默认拒绝，仅允许服务器验证过的 HTTPS origin。
- 普通链接打开和对话消息发送在 Moldy host policy 中始终以错误拒绝。
  `@assistant-ui/react` 0.15.18 的公开 API 在省略 handler 时分别
  启用 `window.open` 和 thread append 默认值，提供拒绝 handler 时
  会在 initialize 响应中显示 capability。因此当前通过显式拒绝 handler
  阻止 side effect，并接受 widget 中先显示 action 后可能返回 policy error 的
  SDK 兼容性 debt。不使用私有 protocol shim 或 package patch
  。
