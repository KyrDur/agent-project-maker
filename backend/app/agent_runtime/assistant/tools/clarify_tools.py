"""Assistant 澄清工具 — ask_clarifying_question（LangGraph interrupt 模式）。

向用户发送 3 个选项 + 直接输入的问题。
"""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from app.agent_runtime.builder_i18n import tr


def build_clarify_tools() -> list[StructuredTool]:
    """创建 1 个 Assistant 澄清工具。"""

    async def ask_clarifying_question(
        question: str,
        option_1: str,
        option_2: str,
        option_3: str,
    ) -> str:
        """向用户提出澄清问题（3 个选项 + 直接输入）。

        对模糊请求请使用此工具，而不是自行猜测。
        每次响应只允许提出恰好 1 个问题。

        Args:
            question: 要向用户询问的问题
            option_1: 第一个选项
            option_2: 第二个选项
            option_3: 第三个选项
        """
        return json.dumps(
            {
                "type": "clarifying_question",
                "question": question,
                "options": [option_1, option_2, option_3, tr("enter_your_own_answer_eb6130")],
            },
            ensure_ascii=False,
        )

    return [
        StructuredTool.from_function(
            coroutine=ask_clarifying_question,
            name="ask_clarifying_question",
            description=tr("clarification_question_to_user_options_eb65c7"),
        ),
    ]
