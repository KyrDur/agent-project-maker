# M3 删除分析报告

## 摘要
- **删除对象**：2 个文件（整体删除）、3 个函数（删除/简化）、2 个 config 设置、2 个 ruff 例外
- **测试影响**：1 个文件（`test_skill_package.py`）— 删除整个 2 个 class，修改 1 个 class
- **预计总删除行数**：~217 行（app/）+ ~180 行（tests/）

---

## 详细分析

### 1. skill_tool_factory.py（整体删除 — 124 行）

| 函数 | 外部引用（app/） | 测试引用 | 安全删除 | 备注 |
|------|------------------|-------------|-----------|------|
| `_load_skill_metadata()` | 0（仅内部） | 0 | ✅ | 仅在 create_skill_tools 中调用 |
| `create_skill_tools()` | executor.py:190（lazy import） | test_skill_package.py 6 项 | ⚠️ 有前置条件 | 删除 executor.py skill_package 分支后可删除 |

**依赖**：import `skill_executor.py`（L7）

### 2. skill_executor.py（整体删除 — 93 行）

| 函数/class | 外部引用（app/） | 测试引用 | 安全删除 | 备注 |
|-------------|------------------|-------------|-----------|------|
| `SkillScriptResult` | 0 | 0（间接使用） | ✅ | 仅在 skill_tool_factory 中使用 |
| `execute_skill_script()` | skill_tool_factory.py:7（import） | test_skill_package.py 7 项 | ⚠️ 有前置条件 | 删除 skill_tool_factory.py 后可删除 |

### 3. chat_service.py — 按函数分析

| 函数 | 行 | 外部引用（app/） | 测试引用 | action | 备注 |
|------|------|------------------|-------------|------|------|
| `get_agent_skill_contents()` | L145-163 | build_effective_prompt（同一文件，L168） | test_skill_package.py 3 项 | **删除** | 简化 build_effective_prompt 后引用为 0 |
| `build_effective_prompt()` | L166-172 | conversations.py:115, trigger_executor.py:43 | test_skill_package.py 2 项 | **简化** | 改为 `return agent.system_prompt`（删除 skill 注入） |
| `build_tools_config()` | L175-213 | conversations.py:116, trigger_executor.py:44 | test_skill_package.py 2 项 | **部分删除** | 删除 L197-213（skill_package block），只保留 tool_links 循环 |

**简化后的 build_effective_prompt()**：1 行函数。可 inline，但交由 S2 设计判断。

**build_tools_config() 后剩余**：只剩 tool_links 循环（L179-195）。功能正常。

#### chat_service.py import 整理

| import | 行 | 当前使用处 | 删除后使用处 | action |
|--------|------|-------------|----------------|------|
| `from pathlib import Path` | L7 | build_tools_config L202（skill_package block） | 无 | **删除** |
| `from app.config import settings` | L12 | build_tools_config L202（skill_package block） | 无 | **删除** |
| `from app.models.skill import AgentSkillLink` | L15 | get_agent_with_tools L139（selectinload） | get_agent_with_tools L139 | **保留**（S3 需要加载 skill_links） |

### 4. executor.py — skill_package 分支（L189-199）

| code block | 外部引用 | 安全删除 | 备注 |
|-----------|-----------|-----------|------|
| `elif tool_type == "skill_package":`（L189-199） | tools_config 中流入 skill_package 类型 | ✅ 与 chat_service.py 修改同时进行 | 从 chat_service.build_tools_config 删除 skill_package 创建后即不可达 |

```python
# 删除对象（executor.py L189-199）
elif tool_type == "skill_package":
    from app.agent_runtime.skill_tool_factory import create_skill_tools
    langchain_tools.extend(
        create_skill_tools(
            skill_id=tc["skill_id"],
            skill_dir=tc["skill_dir"],
            conversation_id=tc.get("conversation_id"),
            output_dir=tc.get("output_dir"),
        )
    )
```

### 5. config.py — 删除设置

| 设置 | 行 | 使用处 | 删除后使用处 | action |
|------|------|--------|----------------|------|
| `skill_script_timeout` | L45 | skill_executor.py:27 | 无 | **删除** |
| `skill_max_output_bytes` | L46 | skill_executor.py:28, skill_tool_factory.py:82 | 无 | **删除** |
| `skill_max_package_bytes` | L47 | skill_service.py（upload 验证） | skill_service.py | **保留**（upload 系统继续存在） |
| `skill_storage_dir` | L44 | skill_service.py（存储路径） | skill_service.py | **保留** |
| `conversation_output_dir` | L50 | chat_service.py:202, conversations.py:155 | conversations.py:155（文件服务） | **保留** |

### 6. pyproject.toml — ruff per-file-ignores

| 项目 | 行 | action |
|------|------|------|
| `"app/agent_runtime/skill_executor.py" = ["ASYNC240"]` | L97 | **删除** |
| `"app/agent_runtime/skill_tool_factory.py" = ["ASYNC240"]` | L98 | **删除** |

---

## 测试影响分析

### test_skill_package.py（唯一受影响文件）

| 测试 class | 行范围 | 测试数 | action | 原因 |
|---------------|-----------|-----------|------|------|
| `TestUploadSkillPackage` | ~L118-275 | ~10 | **保留** | skill_service.upload_skill_package 测试，与 M3 无关 |
| `TestSkillRouter` | ~L240-275 | ~3 | **保留** | router endpoint 测试，与 M3 无关 |
| `TestPromptInjection` | L282-369 | 7 | **修改** | 参见下方详情 |
| `TestSkillExecutor` | L377-459 | 7 | **整体删除** | execute_skill_script 已删除 |
| `TestSkillToolFactory` | L467-549 | 6 | **整体删除** | create_skill_tools 已删除 |

#### TestPromptInjection 修改详情

| 测试 method | action | 原因 |
|---------------|------|------|
| `test_text_skill_content` | **删除** | 删除 get_agent_skill_contents |
| `test_package_skill_variable_substitution` | **删除** | 删除 get_agent_skill_contents |
| `test_claude_skill_dir_substitution` | **删除** | 删除 get_agent_skill_contents |
| `test_build_effective_prompt_no_skills` | **修改** | 验证简化后的行为（始终返回 system_prompt） |
| `test_build_effective_prompt_with_skills` | **删除或修改** | 不再注入 skill。可改为仅验证返回 system_prompt |
| `test_build_tools_config_with_package_skill` | **删除** | 不再生成 skill_package 类型 |
| `test_build_tools_config_text_skill_no_tool` | **删除** | skill 相关分支本身消失 |

**需要修改 import**（L18-22）：
```python
# 变更前
from app.services.chat_service import (
    build_effective_prompt,
    build_tools_config,
    get_agent_skill_contents,
)
# 变更后
from app.services.chat_service import (
    build_effective_prompt,
    build_tools_config,
)
```

---

## 删除顺序（基于依赖图）

```
Step 1: executor.py — 删除 skill_package elif 分支（L189-199）
        ↓（移除 skill_tool_factory 唯一的 app/ import）
Step 2: chat_service.py — 同时修改
        a) 删除 get_agent_skill_contents()
        b) 简化 build_effective_prompt()（return agent.system_prompt）
        c) 删除 build_tools_config() 的 skill_package block（L197-213）
        d) 整理 import（删除 Path, settings）
        ↓（完全移除 skill_package 类型创建路径）
Step 3: 删除 skill_tool_factory.py
        ↓（移除 skill_executor 唯一的外部 import）
Step 4: 删除 skill_executor.py
        ↓
Step 5: 附带整理（可并行）
        a) config.py：删除 skill_script_timeout, skill_max_output_bytes
        b) pyproject.toml：删除 2 行 ruff per-file-ignores
        c) test_skill_package.py：删除 TestSkillExecutor/TestSkillToolFactory，修改 TestPromptInjection
```

**顺序约束**：
- Step 1 → Step 3：skill_tool_factory 的 app/ 引用仅在 executor.py，因此完成 Step 1 后可安全删除
- Step 3 → Step 4：skill_executor 的 app/ 引用仅在 skill_tool_factory，因此完成 Step 3 后可安全删除
- Step 1 + Step 2：可同时执行（相互独立）
- Step 5：在完成 Step 3、4 后执行

---

## 保留项目（不能删除）

| 项目 | 原因 |
|------|------|
| `AgentSkillLink` model + `skill_links` relationship | S3 中映射 skills 路径需要 |
| `Skill` model | skill CRUD/upload 系统继续存在 |
| `skill_service.py` | skill upload/管理继续存在 |
| `skills.py` router | skill API 继续存在 |
| `get_agent_with_tools()` 内 `selectinload(Agent.skill_links)` | S3 中查询 skills 路径需要 |
| `config.skill_storage_dir` | skill 存储路径 |
| `config.skill_max_package_bytes` | upload 限制 |
| `config.conversation_output_dir` | conversations.py 文件服务中使用 |

---

## 检查表（集成验证用 — S5 贝索斯）

- [ ] `skill_tool_factory.py` 文件不存在
- [ ] `skill_executor.py` 文件不存在
- [ ] `grep -r "skill_tool_factory" backend/app/` → 0 项
- [ ] `grep -r "skill_executor" backend/app/` → 0 项
- [ ] `grep -r "create_skill_tools" backend/app/` → 0 项
- [ ] `grep -r "execute_skill_script" backend/app/` → 0 项
- [ ] `grep -r "SkillScriptResult" backend/app/` → 0 项
- [ ] `grep -r "get_agent_skill_contents" backend/app/` → 0 项
- [ ] `grep -r "skill_package" backend/app/` → 0 项
- [ ] `grep -r "skill_script_timeout" backend/app/` → 0 项（包括 config.py）
- [ ] `grep -r "skill_max_output_bytes" backend/app/` → 0 项（包括 config.py）
- [ ] `build_effective_prompt()` 返回 `agent.system_prompt`（无 skill 注入）
- [ ] `build_tools_config()` 中无 skill_package 分支
- [ ] pyproject.toml 中没有已删除文件的 ruff 例外
- [ ] `uv run ruff check .` 通过
- [ ] `uv run pytest` 通过（无 regression）
- [ ] `AgentSkillLink`, `skill_links` 引用正常（未删除）
- [ ] `skill_service.py`, `skills.py` router 正常工作
