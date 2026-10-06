"""skill builder 测试共用 setup。

start v2 lazy-seed hidden builder agent 后，需要 ``models`` catalog row —
一次性创建 system LLM 设置和 Model row，避免各模块复制的 helper
彼此漂移（与共享 mock 规则目的相同）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials import service as credential_service
from app.models.model import Model
from app.models.user_llm_setting import UserLlmSetting
from tests.conftest import TEST_USER_ID

SYSTEM_MODEL_NAME = "gpt-5.4"


async def configure_system_llm(db: AsyncSession) -> None:
    """配置 text_primary system LLM + 匹配的 models catalog row。"""

    credential = await credential_service.create(
        db,
        user_id=TEST_USER_ID,
        definition_key="openai",
        name="builder-key",
        data={"api_key": "sk-test"},
        is_system=False,
    )
    db.add(
        UserLlmSetting(
            user_id=TEST_USER_ID,
            role="text_primary",
            credential_id=credential.id,
            model_name=SYSTEM_MODEL_NAME,
        )
    )
    db.add(
        Model(
            provider="openai",
            model_name=SYSTEM_MODEL_NAME,
            display_name="GPT-5.4",
        )
    )
    await db.commit()
