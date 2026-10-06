"""Integration test 共用 seed helper。

W3-out 之前，``test_stream_resume.py`` 的 ``_seed_conv`` 与
``test_broker_dual_write.py`` 的 ``_seed`` 几乎都在 hand-roll 同样的 User+Model+Agent+
Conversation 序列。统一到一处后，未来 model/schema 变更时只需改一个文件
（整理 W3-out retrospective MEDIUM follow-up）。

若新 integration test 需要相同模式，直接复用本 helper。
"""

from __future__ import annotations

import uuid

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.model import Model
from app.models.user import User
from tests.conftest import TEST_USER_ID, TestSession


async def seed_conversation_with_agent(
    *,
    agent_name: str = "Test Agent",
    conv_title: str = "Test Conv",
    system_prompt: str = "x",
    model_provider: str = "openai",
    model_name: str = "gpt-4o",
    model_display_name: str = "GPT-4o",
) -> uuid.UUID:
    """一行 seed User + Model + Agent + Conversation。返回新的 ``conversation.id``。

    User row 是 idempotent — autouse fixture 只创建 schema，不
    填 row，因此用同一 ``TEST_USER_ID`` 重复调用时，先检查是否已存在，以避免 second insert
    触发 unique 约束。Model/Agent/Conversation 每次
    都是 fresh row。
    """
    async with TestSession() as db:
        existing = await db.get(User, TEST_USER_ID)
        if existing is None:
            db.add(User(id=TEST_USER_ID, email="test@test.com", name="Test"))
        model = Model(
            provider=model_provider,
            model_name=model_name,
            display_name=model_display_name,
        )
        db.add(model)
        await db.flush()
        agent = Agent(
            user_id=TEST_USER_ID,
            name=agent_name,
            system_prompt=system_prompt,
            model_id=model.id,
        )
        db.add(agent)
        await db.flush()
        conv = Conversation(agent_id=agent.id, title=conv_title)
        db.add(conv)
        await db.commit()
        return conv.id
