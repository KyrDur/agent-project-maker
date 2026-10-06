# Phase 2 — 分层·边界（refactor/phase2-layering, base f27e3453）

> 详细方案：docs/refactoring-plan-2026-07.md §4(BE-S2·S7)·§6(BE-D1·D2·D4)
> 原则：每项单独提交，功能变化 0，事务策略 = 服务 flush / 路由器 commit（沿用既有 create 模式）

- [ ] BE-S2a: 新增 `services/mcp_service.py` — 将 routers/mcp.py（825 行，raw DB 28 处）的 `_load_owned`/`_load_tools_for`/CRUD/import·export DB 操作移过去。路由器 只保留 服务 调用+模式 转换+防护。`_invalidate_runtime_mcp_cache`/`_record_mcp_audit` 副作用也移入 服务
- [ ] BE-S2b: 扩展 `tool_service.py` — 将 routers/tools.py 的 create（db.add+commit :135-136）·run_tool_endpoint（:251）逻辑移入
- [ ] BE-S2c: 新增 `model_service.py` — 移入 routers/models.py 的 in-use 检查（:254 count）等
- [ ] BE-S7: 新增 `credentials/oauth_service.py` — 移入 routers/credentials.py 的 OAuth 约 286 行（`_prepare_mcp_oauth_data` :491, `_persist_credential_payload` :574, `_gc_oauth_states` :584, `oauth2_auth_start` :617, `oauth2_callback` :708）。签名 `start_oauth(db,*,user,credential_id)`/`handle_callback(db,*,code,state)`。明确 mcp_oauth_client=底层 HTTP，oauth_service=DB 编排
- [x] BE-D2 ✅ def12f1b: raw `HTTPException(404|403)` 24 处 → 替换为 error_codes 工厂（credentials.py:110,247,422,735 / models.py:282,324,110 / mcp.py:99,357,365 / tools.py:73 / health.py:226,229 等）。仅少量新增缺失 工厂。已 grep 确认 前端 是否依赖 detail 字符串
- [ ] BE-D1: conversation 系列 3 行 所有权 块 30 处 → `Depends(owned_conversation)`（dependencies.py 工厂，统一封装 404 响应）→ 验证后向 agents 6 处扩散 `owned_agent`
- [x] BE-D4 ✅ 6ee572aa: system-or-owned 谓词 7 处 → `Tool.visible_to(user_id)` 模型辅助函数（禁止泛型 load_owned）
- [x] (S) ✅ 15b24557 放宽 integration 工作进程 测试 2s 超时（tests/integration/test_conversation_run_lifecycle.py — CI 偶发失败）

验证：每项执行 `uv run pytest tests/test_<域>*.py` + 最终 `SKILL_EVALUATION_ENABLED=true uv run --with pytest-xdist pytest -q -n 4` + ruff + 修改文件 pyright。PR 目标为 main。
