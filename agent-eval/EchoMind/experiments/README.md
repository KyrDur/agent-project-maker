# Agent Eval · 电商 Agent 实验 API 使用说明

当前支持电商 Agent 的 RAG 聊天、用户知识库与受控评测。以下 Phase 3C 段落仅描述 Agent 行为 / Skill 路径；RAG 路径及知识版本、评测协议见 [Retrieval 说明](RETRIEVAL.md)，聊天与项目实践的当前实现和验收见 [新版说明](../../../../../implementation-20261009/README.md)。

本入口运行受控实验 API：ProviderSession → Connection Test → Baseline → 现有 Decision / Skill Change / Retest / Comparison / Review / Rollback。Knowledge/RAG、query rewrite、rerank、Memory 均不进入正式实验。仅 Python MVP。

## 启动

在 Python 项目根目录 `analysis/20261007-echomind/source/EchoMind`：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install 'anthropic==0.40.0' 'httpx==0.28.1' 'fastapi==0.115.5' 'pydantic==2.10.3' 'uvicorn==0.32.1'
.venv/bin/python -m uvicorn experiments.app:app --host 127.0.0.1 --port 8000
```

也可复用已有 Python 环境。该独立入口不读取服务器 API Key，不启动在线 API 的 Redis/Chroma/Memory/Monitor。API 文档在 `http://127.0.0.1:8000/docs`。默认 artifact 目录为 Python 项目的 `data/experiments`。可通过 `ECHOMIND_EXPERIMENT_DIR` 和 `ECHOMIND_SKILL_DIR` 指定本地路径；实验模型不从环境变量继承。

当前为单进程本地服务，使用默认一个 worker。不要同时启动多个 worker：密钥 vault 不跨进程共享。

## 创建 OpenAI-compatible Session 并跑 Baseline

在另一个终端用当前 Python 环境运行以下示例。Key 通过隐藏输入进入内存，不放进命令参数、JSON 文件或 shell history。不要开启请求 body/header 的调试抓包。示例只打印公开状态和 Run ID。

```python
from getpass import getpass
import httpx

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=1800, trust_env=False) as api:
    configuration = {
        "provider": "openai-compatible",
        "base_url": input("Base URL [https://api.openai.com/v1]: ").strip() or "https://api.openai.com/v1",
        "model": input("Model: ").strip(),
        "temperature": 0,
        "max_tokens": 256,
        "timeout_seconds": 30,
        "max_calls": 48,
        "completion_token_parameter": "max_completion_tokens",
        "api_key": getpass("API Key (memory only): "),
    }
    response = api.post("/experiments/provider-sessions", json=configuration)
    configuration.pop("api_key")
    response.raise_for_status()
    session_id = response.json()["provider_session_id"]
    test = api.post(f"/experiments/provider-sessions/{session_id}/test")
    test.raise_for_status()
    print("Connection:", test.json()["status"])
    if test.json()["status"] != "SUCCESS":
        raise SystemExit("Connection failed; do not run evaluation")
    tool_test = api.post(f"/experiments/provider-sessions/{session_id}/test-tools")
    tool_test.raise_for_status()
    print("Function tools:", tool_test.json()["tool_call_capability"])
    if tool_test.json()["tool_call_capability"] != "VERIFIED":
        raise SystemExit("Tool probe not verified; inspect readiness before running Dialog evaluation")
    ev = api.post("/experiments/evalsets", json={"dialog_cases": [
        {"case_id": "refund", "input": "我申请退款，请先检查账单信息。",
         "executable_rules": [{"type": "forbidden_claim", "target": "refund_completed_without_evidence"}]},
    ]})
    ev.raise_for_status()
    run = api.post("/experiments/runs", json={
        "eval_set_id": ev.json()["eval_set_id"], "provider_session_id": session_id,
    })
    run.raise_for_status()
    print("Run:", run.json()["run_id"], run.json()["status"])
    # DELETE forgets the in-memory Key. A new Session is needed for subsequent Retest.
    api.delete(f"/experiments/provider-sessions/{session_id}").raise_for_status()
```

若要继续同一 Session 的 Skill Change / Retest，保留 Session 到闭环结束再 DELETE。不同 Session 可使用不同 Key，配置不可就地修改；更换配置需新建 Session。

角色覆盖可以只提供不同字段，缺失字段继承用户默认配置：

```json
{"role_overrides": {"judge": {"model": "your-judge-model", "temperature": 0}}}
```

支持角色：general、technical、billing、escalation、composer、intent、judge。Run 的 `inference_config_snapshot` 为每个角色分别保存生效 model / temperature / max_tokens，以及逐字段 `parameter_inheritance`。Agent 与 Judge 即使模型相同，也各有记录。

## Chat Completions 兼容范围

`provider=openai-compatible` 使用 `POST {base_url}/chat/completions`，`base_url` 应是 API 根路径（例如带 `/v1`），不要填完整 `/chat/completions`。Bearer 认证，文本请求，非流式，单 choice，function tools；支持 assistant `tool_calls` → `tool` 消息 `tool_call_id` 往返。不会转发到 Anthropic HTTP endpoint；Anthropic Message 类型只用于已有内部契约。

默认输出预算字段为 `max_completion_tokens`；若兼容服务仅接受旧字段，显式设置 `completion_token_parameter=max_tokens`。不会失败后偷偷换字段、换模型、换 Key 或重试。`max_tokens` 配置值表示输出预算，按选定协议映射。请求固定 `n=1`、`stream=false`、`store=false`。

仅覆盖本项目的文本与 function tools 契约，不包含 Responses API、流式、图像/音频、Azure 专用路径/认证，也不能保证所有第三方“兼容”服务或所有模型都支持 temperature / tools / store 等参数。必须由 Connection Test 和受限 smoke 检验选定模型的实际协议能力。Connection Test 不验证工具能力。

参考：[OpenAI Chat Completions 官方文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

`provider=anthropic-compatible` 使用 Anthropic Messages；默认根路径 `https://api.anthropic.com`。两类请求均显式关闭环境代理、HTTP 重定向和自动重试，预算计数按实际发出的请求。

## API / Retest

新增：

- `POST /experiments/provider-sessions`：配置 + Key，只返回公开 Session。
- `POST /experiments/provider-sessions/{id}/test`：实际最小请求；每个不同生效模型各一次，每次最多 8 输出 token，返回状态、延迟、时间和模型响应标识。
- `POST /experiments/provider-sessions/{id}/test-tools`：文本连接 READY 后独立请求；四个 Agent 角色中每个不同模型各一次强制 `echo(value)` function call，每次最多 64 输出 token（不超过用户预算），按 `max_calls` 限制总调用数。验证工具名和随机 value，记录每个模型的结果；不执行业务工具，不创建 EvalSet 或 Run。
- `GET /experiments/provider-sessions/{id}`：公开记录；重启无 Key 时显示 `CREDENTIAL_UNAVAILABLE`。
- `DELETE /experiments/provider-sessions/{id}`：标记 DELETED 并忘记 Key。
- `POST /experiments/runs`：必须带 `provider_session_id`，不接受 Key。

其余 Phase 3B API 保持。Retest 请求形状：

```json
{
  "eval_set_id": "bound-evalset-id",
  "provider_session_id": "ready-session-id",
  "run_type": "RETEST",
  "parent_run_id": "baseline-run-id",
  "decision_id": "confirmed-decision-id",
  "change_ids": ["applied-change-id"]
}
```

Decision 必须由用户明确确认，Change 必须为 `ONE_SKILL_RULE_BODY` 并实际 APPLIED。本阶段不自动替用户确认 Decision。使用 `GET /experiments/runs/{id}` 读取机器原判、有效判定和分组统计；`POST /experiments/comparisons` 比较两个 Run。

连接失败状态：AUTH_FAILED、MODEL_NOT_FOUND、RATE_LIMITED、TIMEOUT、NETWORK_ERROR、INVALID_RESPONSE、PROVIDER_ERROR。预算耗尽额外返回 CALL_BUDGET_EXCEEDED；Key 丢失返回 CREDENTIAL_UNAVAILABLE。成功文本测试为 SUCCESS / Session READY，同时 `text_connection_status=READY`；这不验证工具能力。Agent/Judge 调用错误仍按 Phase 2 得到 INVALID，失败不产生占位质量分。独立 Intent 样本调用失败则终止采集并封存 FAILED Run，不让本地 fallback 混成正确预测。

`tool_call_capability` 独立取值 UNKNOWN / VERIFIED / UNSUPPORTED / FAILED。VERIFIED 仅证明探针当时能返回一个格式、参数正确的强制 function call，不证明业务工具执行、多轮链路、客服质量或完整线上能力。明确的结构化“不支持 tools/tool_choice”错误才标记 UNSUPPORTED；普通 400、限流、超时、忽略强制工具或错误参数标记 FAILED，不能从错误文案猜测“不支持”。一个角色模型明确不支持即整体 UNSUPPORTED；其余角色有任何失败则整体 FAILED；全部成功才 VERIFIED。

所有 Dialog Agent 都注册角色工具，因此 Dialog / 混合 EvalSet 均按需要工具处理：VERIFIED 正常运行；UNKNOWN 允许运行并记录 `TOOL_CALL_CAPABILITY_UNKNOWN`；FAILED 允许运行并记录 `TOOL_CALL_CAPABILITY_FAILED`，应重新探测；UNSUPPORTED 在创建 Run、启动 worker 前拒绝，返回 `TOOL_CALL_UNSUPPORTED`。纯 Intent EvalSet 不需要工具，文本 READY 即可。每个 Run 永久冻结 `provider_readiness_snapshot`（文本状态、工具能力、requires_tools），后续 Session 测试不改写它。探针为显式 API 操作，不在 Run 前偷偷增加请求。

服务重启丢失所有 Key；原公开记录和已封存 Run 保留，不能重新激活旧 Session，需创建新 Session。已发出的 Run 请求持有自己的临时 credential，到 worker 结束释放；DELETE 阻止后续请求，不能撤销已发出的模型请求。完整 Key 和稳定 Key fingerprint 均不进入新返回值、模型证据或 JSON artifact。凭据只通过随机 `provider_session_id` 在内存 vault 查找；API 临时计算 `credential_status=PRESENT|UNAVAILABLE`，不返回尾号或 hash。同一个 Key 的两个 Session 也没有共同的公开秘密标识。旧 Session 的 obsolete fingerprint 在读取时过滤，不暴露，不因 GET 重写历史文件；明确的生命周期写入使用新 Schema。原阶段报告和测试证据保留历史事实，不是当前 Session API。

## 四 Case smoke / 成本

CLI 用隐藏输入接收 Key；使用独立 Skill 副本和新 artifact 目录：

```sh
cp -R skills /tmp/echomind-smoke-skills
.venv/bin/python -m experiments.smoke --provider openai-compatible --model YOUR_MODEL --base-url https://api.openai.com/v1 --skill-dir /tmp/echomind-smoke-skills --store-dir /tmp/echomind-smoke-artifacts
```

只运行普通咨询、Billing/refund、两轮 Dialog、结构化 Hard Rule 四个 Case；max_tokens=256，timeout=30s，Run 最多 48 次请求，无 SDK 自动重试，最终报告实际调用次数，结束 DELETE Session。Connection Test 在 Run 外每个不同模型各一次；独立 echo 探针在 Run 外每个不同 Agent 模型各一次，必须 VERIFIED 后才执行此受限 smoke。分别报告 connection_call_count / tool_probe_call_count / run_call_count；两类探测各自遵守 max_calls。FAIL 可以是有效质量判定；链路验证要求 Case 非 INVALID、存在真实成功工具轨迹与 Judge 响应。只验证链路，不证明客服质量、优化效果或生产可用。

默认自动化测试使用本地 HTTP 模型。真实测试只有同时显式提供 `ECHOMIND_REAL_PROVIDER_TEST=1`、`ECHOMIND_SMOKE_API_KEY`、`ECHOMIND_SMOKE_MODEL` 才执行；可选 `ECHOMIND_SMOKE_PROVIDER`、`ECHOMIND_SMOKE_BASE_URL`、`ECHOMIND_SMOKE_TOKEN_PARAMETER`。不会读取服务器 OPENAI_API_KEY / ANTHROPIC_API_KEY。无显式授权或 Key 时正常 skip。优先使用上面的 getpass CLI，避免在 shell 命令中写 Key。

当前阶段报告：真实 Provider smoke test 未执行。

## 结果的解释边界

真实 API 和 response model identifier 都不能证明后端版本一致。Response identifier 发生变化有 warning；`MODEL_BACKEND_REVISION_UNVERIFIED` 和 `REDUCED_RUNTIME_KNOWLEDGE_DISABLED` 始终保留。满足原单修改契约可以 `comparable=true`、`single_recorded_change=true`，仍然 `attributable=false / INSUFFICIENT_EVIDENCE`。Phase 2 的四维分别过门槛、INVALID 排除、Human Review / Hard Rule override 等判定均未变。

仓库保留历史 Java 实现，但当前电商 Agent MVP 产品主线仅维护 Python，Java 不在本阶段及后续 MVP 范围内。


## Phase 4B Retrieval path

The reduced runtime / RAG-disabled statements above describe the historical Agent
Behavior (Skill) path only. The Python app now also exposes a separate immutable
Retrieval artifact group and private frozen Chroma index. It does not rewrite any
old Run or activate shared online RAG. See [RETRIEVAL.md](RETRIEVAL.md) for APIs,
metric definitions, single-variable changes, answer evaluation and limitations.

## 本地语义模型（2026-10-09）

新索引默认使用原有 Chroma `all-MiniLM-L6-v2` ONNX 模型（CPU、384 维），聊天与评测共用 `FrozenKnowledge`，不增加 Embedding API Key 或调用费。首次模型下载需要网络，缓存位于 `~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/`。

`POST /experiments/knowledge-datasets/{id}/index` 支持 `embedding_model`：`all-MiniLM-L6-v2`（默认）或 `sha256-lexical-bigram-v1`（词汇对照）。不传 `chunk_config` 时语义模型使用 200 字符、20 字符重叠。每段输入含特殊标记最多 256 Token，超限返回 `EMBEDDING_INPUT_TOO_LONG`，加载失败返回 `EMBEDDING_MODEL_UNAVAILABLE`，都不会静默换模型或截断。

索引记录模型权重、词表文件 SHA-256、后端与适配器版本。历史词汇索引通过字节冻结的 `retrieval_lexical_v1.py` 保持原有摘要与向量；旧材料保持其冻结内容。新材料根据实际索引生成模型描述。更换模型必须另建初测，不能冒充仅知识更新。

本机接入验收的已知 8 道中文 Demo 题：词汇 Hit@3=0.75，MiniLM Hit@3=0.50；不是独立 Holdout 或整体效果结论。
