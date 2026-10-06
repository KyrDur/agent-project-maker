# 聊天 attachment 文件显示 — Phase 0 + P1（todo）

Source of truth: `docs/design-docs/chat-attachments-dev-plan.md`
Plan: `~/.claude/plans/frolicking-marinating-quilt.md`
范围：Phase 0（security）+ P1（显示）。**排除 P2（model multimodal）**。拆分 7 个 commit。

## commit 1 — fix(security): authn+ownership guard on GET /api/uploads/{id} (+ orphan GC) ✅ 615d661b
- [x] `get_upload` 加入 `Depends(get_current_user)` + ownership（`row.user_id == user.id`），不存在/无权限均 404
- [x] 注册 orphan GC job（message_id IS NULL AND created_at < now()-24h → 删除 row+disk）
- [x] pytest：未认证 401/其他用户 404，本人 200，GC unit
- [x] `uv run pytest` + `uv run ruff check .` green → commit

## commit 2 — feat(chat): backfill message_attachments.message_id on turn finalize (M1) ✅ 224d73cf
- [x] 验证测试：resolver id == list_messages_from_checkpointer user id（注入同一 tree）
- [x] `resolve_turn_user_message_id(db, conversation, *, tree)`（tree 最后一个 human → parse_msg_id）
- [x] `link_attachments_to_message(db, *, attachment_ids, message_id)` (WHERE id IN ids AND message_id IS NULL)
- [x] threading：start_conversation_run → _run_conversation → finalize 后立即 _backfill_turn_attachments
- [x] pytest：echo 开启时显示在正确气泡中、无 ID 时 idx fallback、多轮、空输入无操作、worker wiring
- [x] green → commit

## commit 3 — feat(chat): gate attachment hydration to authed views (M2) ✅ 0a891b41
- [x] 将 attachment hydration 包在 `if user_id is not None:` 中
- [x] pytest：认证 echo / shared（user_id=None）不暴露
- [x] green → commit

## commit 4 — feat(chat): unified conversation files endpoint (M3) ✅ ba78cd06
- [x] `GET /api/conversations/{id}/files`（merge generated+attachment，FileItem，source tag，created_at 排序，ownership guard）
- [x] 确认无 route 冲突（/files vs /files/{path}）— regression 36 通过
- [x] pytest：merge/排序/source/权限，排除 unsent，其他用户 404
- [x] green → commit（backend 全量 2473 passed）

## commit 5 — feat(chat): render user attachments inline（frontend）✅ 8170b392
- [x] UserMsg inline attachment render + attachment-to-artifact adapter + preview dialog
- [x] vitest + tsc + lint green → commit

## commit 6 — feat(chat): file list badge + jump-to-message（frontend）✅ e35d7031
- [x] /files API client + FileItem 类型 + useConversationFiles hook
- [x] rail：generated=chatArtifactsAtom（保持 live）+ attachment=/files hybrid（regression 0），generated/attachment badge，read-only
- [x] jumpToMessage（useSyncExternalStore+MutationObserver，无 virtualization DOM anchor）
- [x] i18n chat.files.* ko/en
- [x] vitest 1079 + tsc + lint green → commit

## commit 7 — test(e2e) ✅
- [x] throwaway stack（:5433/3100/8101）E2E 2/2 green：发送→inline→reload→messages echo→/files→download，shared exclusion+/files auth

## E2E 发现的修复（commits 69e6e67f, 275a913c）
- [x] backend：v3 chat 通过 agent-protocol run.start 发送 → attachment_ids threading 漏传到 worker → 未 backfill。修复 + unit test。
- [x] frontend：v3 runtime 是 LangGraph state message，因此 s.message.attachments 为空 → MessagePrimitive.Attachments 不工作。改为基于 message-id 查询 /files 的数据驱动 rendering。

## 最终
- [x] 满足 DoD，无 regression（backend 2473 / frontend vitest 1078 / tsc / lint / E2E 2/2）
- [ ] push（pre-push 阻塞时 SKILL_EVALUATION_ENABLED=true）

## 后续修复（1·2a·2b 本次处理）
- [x] (1) attachment-only 对话的 "文件" 按钮 — 从 composer toolbar 打开文件 panel(list)
- [x] (2a) run 完成时 invalidate /files → live 发送 attachment 在回答结束后立即 inline 显示
- [x] (2b) generated FileItem.message_id = linked_message_ids[0]（真实 message id）→ generated file jump 准确

## TODO（必须做，不在本次范围）
- [ ] **O2 upload 加密**：attachment·generated file 都以 plaintext 存在 disk（shutil.copy2 / write_bytes）。API 有 auth 保护。
      在政策决定（全部 / 仅敏感 MIME / 不加密）后，对 attachment+generated 一并应用。并非 attachment 新增的独有弱点（与现有 generated file 相同）。
