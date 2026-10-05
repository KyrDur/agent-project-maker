"""Runtime component clusters — 从 ``runtime_component_builder`` 拆分出的包（BE-S10）。

模块组成：

* ``models`` — 模型候选/回退/重试判定
* ``reliability`` — 空响应重试中间件 + 默认可靠性中间件组装
* ``interrupts`` — HiTL ``interrupt_on`` 策略组装
* ``prompts`` — 系统提示词块构建器
* ``memory_context`` — 长期记忆提示词/回忆 brief/写入策略

兼容性：现有符号继续由 ``app.agent_runtime.runtime_component_builder``
re-export，测试 monkeypatch 协议也继续以该模块路径为准。
"""
