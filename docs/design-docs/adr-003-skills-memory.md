# ADR-003：Skill + Memory 迁移设计

## 状态：已批准

## 背景

当前 Moldy 的 skill 系统通过两条自定义路径运行：

1. **Text skill**：`build_effective_prompt()` 将 DB `content` 字段直接注入 system prompt
2. **Package skill**：`skill_tool_factory.py` 转换为 `run_*`、`read_*_file` LangChain 工具，`skill_executor.py` 执行 Python 脚本

该方式的问题：
- **没有渐进式披露**：所有 skill 内容一次性注入 system prompt，造成 token 浪费
- **双路径**：根据 text/package 类型走完全不同的代码路径，维护负担较大
- **自定义工具开销**：`skill_tool_factory.py` + `skill_executor.py` 手动创建 LangChain 工具
- **缺少 memory**：没有按 agent 区分的长期记忆（AGENTS.md）系统

M1 已完成向 `create_deep_agent` 的迁移，因此利用 deepagents 原生 `skills`/`memory` 参数统一 skill 与 memory 系统。

---

## 决定

### 1. Backend 选择：FilesystemBackend

```python
from deepagents.backends import FilesystemBackend

backend = FilesystemBackend(
    root_dir="./data",        # backend/data/ 目录
    virtual_mode=True,        # 安全：防止路径逃逸
)
```

**选择依据：**
- skill（SKILL.md）和 memory（AGENTS.md）都存在于磁盘 → FilesystemBackend 更自然
- CompositeBackend 的 StateBackend 默认路由没有必要（未使用 agent scratchpad）
- 用单一 backend 同时覆盖 `/skills/` 和 `/agents/` 路径
- 通过 `virtual_mode=True` 防止路径逃逸（`..`、`~`）

**虚拟路径映射：**

| 虚拟路径 | 磁盘路径 | 用途 |
|-----------|------------|------|
| `/skills/{skill_id}/SKILL.md` | `data/skills/{skill_id}/SKILL.md` | skill 加载 |
| `/skills/{skill_id}/references/` | `data/skills/{skill_id}/references/` | 参考文档 |
| `/agents/{agent_id}/AGENTS.md` | `data/agents/{agent_id}/AGENTS.md` | agent memory |

### 2. Skills 路径映射

#### `_list_skills` 行为分析

deepagents `SkillsMiddleware` 的 `_list_skills(backend, source_path)` 函数会：

1. `backend.ls_info(source_path)` → 列出 source 目录中的条目
2. 只筛选 `is_dir=True` 的条目（子目录）
3. 从每个子目录下载 `SKILL.md`
4. 解析 YAML frontmatter → 返回 `SkillMetadata`

**预期结构：**
```
source_path/           ← 传给 _list_skills 的路径
└── skill-name/        ← 子目录（is_dir=True）
    ├── SKILL.md       ← 必需（frontmatter: name, description）
    └── ...            ← 参考文档、脚本等
```

**当前磁盘结构：**
```
data/skills/                          ← source_path = "/skills/"
└── d9f14fdf-...-81ae53783ef4/        ← skill_id 子目录
    ├── SKILL.md                      ← ✅ 存在
    ├── scripts/
    ├── references/
    └── floor_images/
```

→ 传入 `skills=["/skills/"]` 后，`_list_skills` 会自动发现所有 skill。

#### Per-Agent skill 过滤

当前 `_list_skills` 会返回 source 目录中的**所有** skill。deepagents API 不直接支持按 agent 过滤。

**PoC 策略**：以 `/skills/` 作为单一 source 加载所有 skill。由于采用渐进式披露，agent 只会加载需要的 skill。通过 system prompt 明确 agent 已连接的 skill 名称进行引导。

**未来生产环境策略**（不属于 M3 scope）：
- 实现 `FilteringFilesystemBackend`（基于 agent_skills 过滤 ls_info 结果）
- 或使用 per-agent skill 目录（`data/agents/{agent_id}/skills/`）+ 文件复制

### 3. Text skill 统一：磁盘物化

要以 deepagents 原生方式统一 Text skill（仅有 DB `content` 字段，没有 `storage_path`），需要在磁盘上提供 `SKILL.md` 文件。

**物化策略：**

```python
# skill_service.py — 创建/修改 skill 时
def _materialize_skill_to_disk(skill: Skill) -> str:
    """将 text skill 的 content 写入 data/skills/{id}/SKILL.md。"""
    skill_dir = Path(settings.skills_data_dir) / str(skill.id)
    skill_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = f"---\nname: {skill.name}\ndescription: {skill.description or ''}\n---\n\n"
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(frontmatter + skill.content, encoding="utf-8")

    return str(skill_dir)
```

**执行时点：**
- **创建** skill 时：`create_skill()` → `_materialize_skill_to_disk()` → 设置 `storage_path`
- **修改** skill 时：`update_skill()` → `_materialize_skill_to_disk()` → 覆盖 SKILL.md
- **现有 text skill**：服务器启动时或首次使用时 lazy 物化

**DB 模型变更：**
- `Skill.type` 字段：保持不变（"text" | "package"），用于 UI 区分。
- `Skill.storage_path`：text skill 物化后也会设置。
- `Skill.content`：继续作为 **source of truth**。磁盘文件是派生物。

### 4. Memory 路径模式

```
data/agents/{agent_id}/AGENTS.md
```

**参数传递：**
```python
memory=[f"/agents/{agent_id}/AGENTS.md"]
```

**MemoryMiddleware 行为：**
1. `backend.download_files(["/agents/{agent_id}/AGENTS.md"])`
2. 文件存在时 → 将内容注入 system prompt
3. 文件不存在时 → `file_not_found` → 忽略（无错误）

**目录创建时点：**
- **创建 agent 时**：`agent_service.create_agent()` → 创建 `data/agents/{agent_id}/`
- 创建空 AGENTS.md（可选），或无文件启动 → MemoryMiddleware 忽略
- agent 可在对话中通过 Write 工具写入 AGENTS.md

**AGENTS.md 初始内容：**
```markdown
# Agent Memory

（agent 学到的内容会记录在这里）
```

### 5. `build_agent()` 签名变更

```python
def build_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    *,
    middleware: list | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
    backend: Any | None = None,
    skills: list[str] | None = None,       # ← 新增
    memory: list[str] | None = None,       # ← 新增
    name: str | None = None,
) -> Any:
    """Build a deep agent. Returns CompiledStateGraph."""
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware or (),
        checkpointer=checkpointer,
        store=store,
        backend=backend,
        skills=skills,
        memory=memory,
        name=name,
    )
```

### 6. `execute_agent_stream()` 变更

```python
async def execute_agent_stream(
    # ... 现有参数 ...
    agent_skills: list[dict] | None = None,   # ← 新增：[{skill_id, storage_path}]
    agent_id: str | None = None,               # ← 新增：用于 memory 路径
) -> AsyncGenerator[str, None]:
    # ... 创建现有工具 ...
    # 移除 skill_package 分支

    # 创建 Backend
    from deepagents.backends import FilesystemBackend
    backend = FilesystemBackend(
        root_dir=str(Path(__file__).resolve().parent.parent.parent / "data"),
        virtual_mode=True,
    )

    # 构建 Skills source
    skills_sources: list[str] | None = None
    if agent_skills:
        skills_sources = ["/skills/"]

    # 构建 Memory source
    memory_sources: list[str] | None = None
    if agent_id:
        memory_sources = [f"/agents/{agent_id}/AGENTS.md"]

    agent = build_agent(
        model,
        langchain_tools,
        system_prompt,
        middleware=middleware or None,
        checkpointer=get_checkpointer(),
        backend=backend,
        skills=skills_sources,
        memory=memory_sources,
        name=f"agent_{thread_id[:8]}",
    )
    # ... 现有 streaming ...
```

### 7. 调用方变更（conversations.py）

```python
# 现有
system_prompt = build_effective_prompt(agent)
tools_config = build_tools_config(agent, str(conversation.id))

# 变更后
system_prompt = agent.system_prompt  # 移除 build_effective_prompt
tools_config = build_tools_config(agent, str(conversation.id))  # 已移除 skill_package
agent_skills = [
    {"skill_id": str(link.skill.id), "storage_path": link.skill.storage_path}
    for link in agent.skill_links
    if link.skill and link.skill.storage_path
]

async for chunk in execute_agent_stream(
    ...,
    agent_skills=agent_skills or None,
    agent_id=str(agent.id),
):
    yield chunk
```

---

## 替代方案

### 方案 A：CompositeBackend（StateBackend + FilesystemBackend）

```python
backend = CompositeBackend(
    default=StateBackend,
    routes={
        "/skills/": FilesystemBackend(root_dir="./data/skills", virtual_mode=True),
        "/agents/": FilesystemBackend(root_dir="./data/agents", virtual_mode=True),
    }
)
```

**优点**：提供 agent scratchpad（ephemeral）
**缺点**：StateBackend 需要 factory 模式（`lambda rt: StateBackend(rt)`）。没有 scratchpad 使用场景，增加了不必要的复杂性。
**判断**：当前 scope 不需要 scratchpad → 否决

### 方案 B：StoreBackend（PostgresStore）

```python
backend = CompositeBackend(
    default=StateBackend,
    routes={
        "/memories/": StoreBackend,
        "/skills/": FilesystemBackend(...),
    }
)
```

**优点**：memory 存入 DB，可 cross-thread 共享，便于备份
**缺点**：StoreBackend 基于 namespace — 与 AGENTS.md 文件模式兼容较复杂。还需额外基础设施（PostgresStore）。MemoryMiddleware 使用 `download_files()` → 需要确认 StoreBackend 兼容性。
**判断**：PoC 阶段复杂度过高 → 否决。未来生产环境再评估。

### 方案 C：不使用 skills 参数，保留 system prompt

**优点**：变更最少
**缺点**：无法利用 deepagents 渐进式披露，无法达到 M3 目标。
**判断**：与目标不一致 → 否决

### 方案 D：Per-agent 符号链接

仅将每个 agent 已连接的 skill 符号链接到 `data/agents/{agent_id}/skills/` 目录。

**优点**：按 agent 隔离 skill
**缺点**：`FilesystemBackend` 通过 `O_NOFOLLOW` 标志阻止跟随符号链接（Linux/macOS），实际无法工作。
**判断**：技术上不可行 → 否决

---

## 设计详情

### 目录结构变更

```
data/
├── skills/                        # 保持现有
│   └── {skill_id}/
│       ├── SKILL.md               # frontmatter: name, description
│       ├── scripts/               # （package skill）
│       ├── references/
│       └── _outputs/
│
├── agents/                        # ← 新增
│   └── {agent_id}/
│       └── AGENTS.md              # agent 长期记忆
│
└── conversations/                 # 保持现有
    └── {conversation_id}/
```

### 待移除代码

| 文件 | 移除内容 | 原因 |
|------|-----------|------|
| `skill_tool_factory.py` | 全部删除 | 由 deepagents SkillsMiddleware 替代 |
| `skill_executor.py` | 全部删除 | 脚本执行由 agent 内置工具替代 |
| `chat_service.py` | `build_effective_prompt()` skill 注入逻辑 | 由 SkillsMiddleware 负责注入 system prompt |
| `chat_service.py` | `build_tools_config()` skill_package 逻辑 | 无需将 skill_package 转换为工具 |
| `executor.py` | `skill_package` 分支 | 改用 skills 参数而非创建工具 |

### 保留项

| 项目 | 原因 |
|------|------|
| `Skill` DB 模型 | UI 仍需要 skill CRUD。`content` 字段作为 source of truth |
| `AgentSkillLink` 模型 | 管理 agent-skill 连接 |
| `skill_service.py` | skill CRUD 服务（新增物化逻辑） |
| `routers/skills.py` | skill API 端点 |
| `schemas/skill.py` | API schema |

### 数据流（M3 之后）

```
POST /api/conversations/{id}/messages
│
├─ 1. maybe_set_auto_title(content)
├─ 2. get_agent_with_tools(agent_id)  [包含 skill_links]
├─ 3. system_prompt = agent.system_prompt  ← 移除 build_effective_prompt
├─ 4. build_tools_config(agent)  ← 移除 skill_package 分支
├─ 5. agent_skills = [linked package skills]
│
├─ 6. execute_agent_stream(
│       ..., agent_skills=agent_skills, agent_id=str(agent.id))
│    │
│    ├─ 6a. create_chat_model()
│    ├─ 6b. create tools (builtin/prebuilt/custom/mcp)  ← 移除 skill_package
│    ├─ 6c. FilesystemBackend(root_dir=data/, virtual_mode=True)
│    ├─ 6d. build_agent(skills=["/skills/"], memory=["/agents/{id}/AGENTS.md"],
│    │       backend=backend, ...)
│    │    └─ create_deep_agent(skills=..., memory=..., backend=...)
│    │         ├─ SkillsMiddleware → before_agent: _list_skills("/skills/")
│    │         │   → 扫描子目录 → 解析 SKILL.md → 保存 metadata 状态
│    │         │   → wrap_model_call：向 system prompt 注入 skill 列表
│    │         └─ MemoryMiddleware → before_agent: download AGENTS.md
│    │             → wrap_model_call：向 system prompt 注入 memory 内容
│    └─ 6e. stream_agent_response()
│
└─ 7. StreamingResponse → Frontend (SSE)
```

### skill 创建/修改流程

```
POST /api/skills (create)  |  PUT /api/skills/{id} (update)
│
├─ skill_service.create_skill() / update_skill()
│   ├─ 在 DB 中保存 Skill 记录
│   └─ _materialize_skill_to_disk(skill)
│       ├─ 创建 data/skills/{skill.id}/ 目录
│       ├─ 写入 SKILL.md（frontmatter + content）
│       └─ 设置 skill.storage_path = str(skill_dir)
│
└─ Response: SkillResponse
```

---

## 结果

### 正面影响
- **渐进式披露**：skill 不会一次性全部加载，agent 按需探索
- **减少代码**：移除 `skill_tool_factory.py` + `skill_executor.py` + 相关逻辑（~150 行）
- **统一路径**：不再区分 text/package，所有 skill 都统一基于 SKILL.md
- **Memory 系统**：支持按 agent 区分的长期记忆（AGENTS.md）
- **利用框架能力**：使用 deepagents 原生 middleware，降低维护负担

### 负面影响
- **PoC 限制 — 无 skill 隔离**：所有 agent 都可探索完整 `/skills/`。按 agent 过滤依赖渐进式披露 + system prompt 引导
- **需要磁盘物化**：将 text skill 写入磁盘会增加 I/O。Content 字段与 SKILL.md 双重管理（DB 为 source of truth）
- **脚本执行方式变更**：现有 `skill_executor.py` 的隔离 Python 执行消失，改由 agent 通用工具执行，因此安全隔离减弱（PoC 阶段可接受）

### 后续事项（M3 之后）
- [ ] Per-agent skill 过滤（FilteringFilesystemBackend 或 custom middleware）
- [ ] memory 自动管理（摘要、整理、过期）
- [ ] 评估迁移到 StoreBackend（需要 cross-instance memory 共享时）
- [ ] skill 脚本隔离执行环境（sandbox）
