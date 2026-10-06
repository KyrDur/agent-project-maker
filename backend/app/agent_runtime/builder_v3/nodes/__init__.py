"""Builder v3 图节点。

每个 phase 节点都具有 ``async def phase_X(state: BuilderState) -> dict | Command``
签名，返回 dict 时合并到 state，返回 Command 时进行分支/self-loop。
"""
