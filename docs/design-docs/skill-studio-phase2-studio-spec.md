# SPEC — 技能工作室 Phase 2：6-tab 全页面 Studio

> Phase 1 spec：`skill-studio-phase1-builder-chat-spec.md`（§10 中为本范围预留）。
> 设计基准：`~/Downloads/Web-Prototype_skill/skill-studio.html`（repo 外部 static mockup）。
> 编写：2026-07-11，分支 `feature/skill-studio-phase2`（基于 origin/main fe6a8502）。

---

## 1. 背景与目标

### 1.1 当前状态（问题）

- `/skills` 是单页（card grid）+ `?detailId=&tab=` query dialog（5-tab：
  content/credentials/evaluation/history/metadata）结构。评估·版本·源码全部
  被限制在 dialog 宽度中。
- 列表只有 card grid — 无表格/排序/多选/bulk 操作。
- `Skill.used_by_count` 创建时只写 0，且没有同步，因此**始终为 0**
  （连接计数数据实际上不存在）。
- 版本 tab 只有 changed_files 文本摘要，没有 line diff。也没有读取 revision zip
  文件内容的 API。
- Phase 1 已将 builder chat 迁移到 `/skills/builder/[sessionId]` 全页面 —
  其余管理表面仍留在 dialog 中。

### 1.2 目标

按 mockup 的 5-tab Studio IA 实现真实路由，同时将 mockup 遗漏的功能（credential
绑定·metadata 编辑·发布）保留为第 6 个“设置”tab：

```
列表（表格+bulk 删除）/ builder（现有 chat）/ 评估 / 版本（+SKILL.md diff）/ 源码（直接编辑）/ 设置
```

共享元素：技能 context bar（名称/状态/slug/版本 + 通过率/连接 stats + skill switcher）。

### 1.3 已确认的产品决策（2026-07-11 用户）

| # | 决策 | 内容 |
|---|------|------|
| D1 | 新增设置 tab | credentials 绑定 + metadata + 发布/导出/删除放到第 6 个 tab。相对 mockup 5-tab 的有意改编 |
| D2 | 保留源码直接编辑 | 迁移现有 Package/Text editor（保存=revision）。并行保留 mockup 的“在 builder 中编辑”按钮 |
| D3 | bulk=仅删除 | 多选 + 批量删除（含连接 Agent 警告）。mockup bulk-bar 的“导出 package”有意删除（backlog） |

### 1.4 范围外（Phase 3 — 禁止伪数据原则）

- with/without A/B benchmark 对比图、人工反馈 UI、真实成本核算、按版本通过率
- 技能复制（mockup 行菜单中存在 — backlog）
- 批量 package 导出（D3）

### 1.5 相对 mockup 的有意改编（drift 记录）

实现中与 mockup（`skill-studio.html`）不同的地方全部是有意改编，并在此
记录（D1~D3 之外的新增项）：

| mockup 元素 | 实现 | 原因 |
|---|---|---|
| 列表顶部 stat-strip（全部/已验证/失败计数 4 张卡） | 用 `CountedLineTabs`（按 kind 计数）+ `SkillStateFilterChips`（按状态计数 chip）替代 | 现有 filter UI 已以计数暴露相同信息 — 4 张不可点击卡片重复。保持现有 filter 流程（成功标准 1） |
| 所有列排序 | 仅评估(pass_rate)·修改日期排序 | 名称/类型/状态已由 kind tab·状态 chip·搜索处理。排序只保留真正有使用价值的轴 |
| 'ready' 状态 filter preset | 未实现（backlog） | 状态 chip 已以计数暴露 health.state 全部类型 — 独立 preset 留到 Phase 3 根据使用数据决定 |

---

## 2. 成功标准（可验证）

1. `/skills` 以表格（DataTable）渲染，多选→批量删除（列出名称确认 +
   连接 Agent 警告）可用。保留现有 kind tab/状态 chip/搜索过滤。
2. 可直接进入 `/skills/{id}/evaluation|versions|source|settings`，
   6-tab + context bar（含真实数据连接计数）显示在所有 skill-scoped 路由。
   通过 skill switcher 切换时保持当前 active tab。
3. 列表连接计数为真实聚合（Agent 连接/解绑时反映，排除隐藏 Agent）。
4. 版本 tab 中选择 revision 后渲染 SKILL.md line diff（首次/pruned 显示
   placeholder），可通过“查看此版本源码”查看 read-only revision source。
5. legacy `/skills?detailId=X&tab=Y` 入口 redirect 到新路由
   （包括 marketplace/builder rail/finalize deeplink）。
6. 现有 `skill-builder-chat.spec.ts` 无修改通过（builder 路由/功能无回归），
   全套 suite（backend pytest、vitest、5 种 lint、build、相关 E2E）全绿。

---

## 3. 架构决策

### AD-1. 路由 = 真实 route segment，legacy 使用服务器 redirect

```
/skills                                → 列表 tab
/skills/[skillId]                      → /skills/[skillId]/source redirect
/skills/[skillId]/{evaluation,versions,source,settings}
/skills/builder                        → builder index（session 列表 + Start CTA）
/skills/builder/[sessionId]            → builder tab（Phase 1 路由不变）
```

- `builder` 是 static segment，因此不会与 `[skillId]` 冲突。
- legacy redirect 在 `app/skills/page.tsx`（服务器）中 `await searchParams` 后
  `redirect()`。tab mapping：`content→source, credentials→settings,
  evaluation→evaluation, history→versions, metadata→settings`
  （复用 `coerceSkillDetailTab`）。选择代码聚合而不是 next.config redirects。
  作为永久安全网保留（应对未来外部域名再次出现）。

### AD-2. Studio shell = layout 的 client component，通过 hook 派生 segment

- Next.js 中 layout 无法访问子 segment params（已查文档）—
  `SkillStudioShell`（client）通过 `useParams()` + `usePathname()` 派生 tab
  active/context。无需 jotai。
- context bar 数据：skill 路由使用 `useSkill(skillId)`，builder 路由使用
  `useSkillBuilderSession(sessionId)` → `source_skill_id ?? finalized_skill_id`
  → `useSkill` chain（共享 TanStack cache）。create 模式 session 显示“新技能 Draft”。
- shell 使用 `flex min-h-0 flex-1 flex-col` — 必须保持 builder chat 内部 scroll 契约
  （`app-layout.tsx` → `skill-builder-chat-client.tsx` flex chain）。
- 无需更改 `ScopedIntlProvider` namespace：shell 文案使用 `skill.studio.*`
  （skill namespace 同时包含在 /skills scope 和 builder scope 中）。

### AD-3. tab 迁移 = 向现有 4-slot render prop 契约注入 page renderer

- `SkillDetailTabRender`(body/footer/sidebar/overlay —
  将 `components/skill/skill-detail-tab-shell.tsx` 的 DialogShell renderer
  替换为 page layout renderer。**必须渲染 overlay slot**
  （SkillHistoryTab rollback confirm dialog）。
- 评估=`SkillEvaluationTab`（无依赖，调整 full-width grid）/ 版本=`SkillHistoryTab`
  （移除 footer close）/ 源码=`PackageSkillEditor`+`TextSkillEditor`（footer→
  page toolbar，从 editor 提取删除/导出逻辑）/ 设置=绑定 panel+
  metadata form+`PublishWizard`+导出/删除。
- 全页面始终显示 6-tab + 各 tab 委托 empty state（`getVisibleSkillDetailTabs`
  条件隐藏在页面中废弃 — 因为需要支持 URL 直接进入）。

### AD-4. 后端新增 = 1 个聚合 + 2 个路由，0 个 migration

1. **连接计数**：在 `skill_response_enrichment.py` 增加 batch function（单次 GROUP BY，
   `Agent.user_id` + `runtime_profile == 'standard'` 过滤 — 遵守隐藏规则）→
   serializer 中覆盖 `used_by_count`。不删除列（保持 migration
   0 个，仅更新 stale 注释）。已连接 Agent **名称列表**无需新 API，
   前端从 `useAgents()` 的 `Agent.skills`（SkillBrief）反向派生。
2. **revision 文件**：`GET .../revisions/{rid}/files`（zip namelist+size）+
   `GET .../revisions/{rid}/files/content?path=`（精确匹配，8KB binary
   sniff + 2MB cap — 复用 `skill_draft_workspace.py` 常量模式）。zip
   复用 `_read_revision_bytes`，不解压到磁盘。对 `snapshot_pruned` 明确
   响应。统一 404（enumeration-safe）。
3. **builder session 列表**：`GET /api/skill-builder?skill_id=&status=&limit=` —
   user scope，`source_skill_id==X OR finalized_skill_id==X`（也捕获 create 模式
   session），`updated_at desc`（现有 index）。

### AD-5. 列表表格 = 复用 DataTable + 保留现有 filter toolbar

- `components/ui/data-table.tsx` + `settings/models/page.tsx` 先例。
  保留现有 `CountedLineTabs`/`SkillStateFilterChips`/`SearchInput`/`filterSkillList`
  toolbar，并注入过滤后的数组（`searchable=false`，toolbar slot=bulk bar）。
- DataTable 陷阱处理：`rowSelection` 是内部 state → bulk 删除后通过 **key
  remount 重置**；select-all 作用于页面 scope（保持先例）；被搜索隐藏的选择
  仍可能残留 → confirm dialog 中列出所选 skill 名称。
- bulk 删除 = 顺序调用现有 `DELETE /api/skills/{id}` + 部分失败摘要 +
  invalidate `skillQueryKeys.all`。`AgentSkillLink` 为 CASCADE，因此必须提示连接警告。

### AD-6. 版本 diff = 前端计算（jsdiff），后端只提供原文

- 增加 `diff`（jsdiff）依赖，SKILL.md line diff renderer 仅使用 semantic status token
  （`--status-success/danger`）（设计 guard）。
- 基准 = 所选 revision vs parent revision。首次（无 parent）/pruned 显示 placeholder
  （前端通过 `SkillRevisionDetail.metadata_json` 预判）。
- “查看此版本源码” → `/skills/{id}/source?revision={rid}` — source tab
  read-only 模式（使用 revision file API，禁用保存/删除，提供返回当前版本按钮）。

---

## 4. legacy `detailId` 生成处全量（全部更新）

| 位置 | 文件 |
|------|------|
| 前端 | `components/marketplace/marketplace-card.tsx`, `components/marketplace/install-wizard.tsx`, `app/skills/builder/[sessionId]/_components/skill-builder-rail.tsx` |
| 后端 | `app/services/skill_builder_finalize.py` `SKILL_DETAIL_DEEPLINK`（+`tests/test_skill_builder_finalize.py`） |
| E2E | `skill-builder-preview` `skill-history` `skill-builder-conflict` `skill-evaluation-actions`(×2) `skill-export` + 2 种 captures（`waitForURL(/\/skills\?detailId=/)`） |

---

## 5. 测试计划

- **后端**：聚合（连接 0/N、排除其他用户、排除隐藏 profile）、revision 文件
  （所有权统一 404、binary skip、pruned、path mismatch 404）、session 列表
  （user scope、source/finalized 匹配、状态过滤、排序）、finalize deeplink 变更。
- **vitest**：diff util、Studio shell tab 派生、bulk 选择/删除流程、
  迁移后的 tab renderer（含 overlay）、redirect mapper。
- **E2E**：更新现有 skill 相关 spec 8+、新增 Studio spec（表格/bulk/tab 导航/
  switcher/版本 diff/legacy redirect）、capture tour。`skill-builder-chat.spec.ts`
  无修改通过作为回归 gate。throwaway stack（fresh port，`E2E_LLM_*=''`，
  `E2E_SEED_USER_ENABLED=true`，scripted 验证前重建 DB）。

---

## 6. 实现里程碑（展开到 CHECKPOINT.md）

| M | 内容 | done-when |
|---|------|-----------|
| M0 | 分支 + spec + CHECKPOINT | spec commit |
| M1 | 后端 3 项 + pytest | `pytest -k skill` 全绿，ruff clean |
| M2a | shell + 路由 + tab 迁移 + 设置 tab（dialog 共存） | vitest/tsc/lint/build + builder E2E 回归 gate |
| M2b | legacy 切换 + 删除 dialog + 更新 E2E | 对应 E2E + finalize pytest 全绿 |
| M3 | 列表表格 + bulk 删除 | vitest + bulk E2E + design guard |
| M4 | 版本 diff + revision source 查看 | diff 测试 + skill-history E2E 扩展 |
| M5 | orphan sweep + Studio E2E/capture + 文档 | §2 成功标准全部满足，全套 suite 全绿 |

## 7. 风险与缓解

| 风险 | 缓解 |
|--------|------|
| builder chat viewport 崩坏（shell flex chain） | M2a 用 builder E2E 回归 gate |
| E2E 大面积破坏（8+ spec） | 按 milestone 分批更新（M2b/M3） |
| bulk 删除后 stale selection（DataTable 内部 state） | key remount + 列出名称确认 |
| i18n 过度 sweep → 渲染 raw key（`skill.detailDialog.*` 被迁移 tab 的 15 个文件共享） | 按 key grep 后移除，禁止整 namespace 删除 |
| revision zip 大文件/binary | 复用 2MB cap + 8KB sniff，pruned 明确响应 |
