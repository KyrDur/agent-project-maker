"""Builder v3 — 基于 LangGraph StateGraph 的 8-phase 对话式构建器。

通过图拓扑强制顺序（LLM 无法违反）。
HiTL: ask_user / approval / image choice（基于 interrupt）。
复用与普通聊天相同的 streaming.py / checkpointer 基础设施。
"""
