# Chat Transcript Stability QA

修改聊天运行时时，下面这一组应视为一个回归基准。修复其中一项时如果
其他项出现波动，就不视为通过。

## 自动执行

```bash
cd frontend
pnpm test:e2e:chat-transcript-stability
```

该 suite 使用真实 backend/frontend Playwright 服务器。应用默认聊天运行时是
`langgraph_v3`，因此也包含在完整 `pnpm test:e2e` 执行中。不过，
在显式设置 `NEXT_PUBLIC_CHAT_RUNTIME=legacy` 的 legacy 执行中会 skip。

## 固定基准

1. 新对话 `/conversations/new` 在发送消息之前不应创建实际 conversation row，
   切换到其他页面后也不应留下空 draft。
2. 在新对话发送第一条消息后，URL 应切换为实际 `conversationId`，侧边栏中的
   `新对话` 临时 row 应升级为实际对话 row。如果同一对话被重复添加成多个 row，
   则失败。
3. 第一条消息之后如果 opener/character empty state 再次出现，则失败。
4. 在新对话中连续发送 3 轮以上时，已有用户消息和 assistant 消息
   若消失后又重新出现，则失败。
5. 修改用户消息时，修改目标下方原有的 assistant 回复应立即移除，
   如果同一用户消息以临时 bubble 重复显示，则失败。
6. 多次修改用户消息后，应选择最新 branch。重新生成应基于最新
   用户 branch 执行，如果 branch index 被推回到旧 branch，则失败。
7. 重新生成 LLM 回复时，应把新的 assistant branch 显示为最后一个 branch。branch
   picker 在 hover 状态持续期间如果消失，则失败。
8. `ask_user` interrupt 对同一请求必须恰好只显示 1 张卡片。
   卡片出现期间，如果用户发送的句子消失或变成空 bubble，则失败。
9. 流式过程中，run notice/tool status 若把同一状态重复显示为多张卡片，则失败。
   如果要显示，就应稳定保持一个；如果不显示，就不应短暂出现后又消失，
   否则失败。
10. assistant rich output 遵循与普通文本相同的 transcript 稳定性规则。代码块、
    行内代码、GFM 表格/检查清单、KaTeX 公式、图片、链接、blockquote、Mermaid
    都应渲染并在 reload 后保持。如果这些输出中的任意一种消失，或用户的
    prompt 变成空 bubble，则失败。该路径应通过用户实际可能输入的
    自然语言请求来引导输出格式，而不是内部测试 marker。

## 测试映射

- `frontend/e2e/draft-conversation-langgraph-v3.spec.ts`
  - draft 创建/丢弃
  - `/new` → 实际 conversation 切换
  - 防止 empty state 再次出现
  - 3 轮以上消息稳定性
  - 用户消息修改与 branch 最新性
- `frontend/e2e/chat-langgraph-v3-regressions.spec.ts`
  - 重新生成 branch 恢复
  - 防止 slow stream reconnect 重复
  - interrupted/HITL 状态恢复
- `frontend/e2e/chat-transcript-stability.spec.ts`
  - `ask_user` 卡片单次显示
  - `ask_user` 渲染期间保留用户 prompt
  - `/new` draft promotion 与 `ask_user` 同时路径
  - rich assistant output 渲染：代码、表格、公式、图片、链接、引用、检查清单、Mermaid
  - rich output 渲染期间保留用户 prompt 和 reload persistence
