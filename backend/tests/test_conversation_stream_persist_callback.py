"""BE-P5(d) — ``build_persist_callback`` 的 run-scoped seen_event_ids cache 合约。

移除每次 partial flush 都对累计 chunk 的全部 event id 重新 SELECT 的 O(T²/64)
加载后，必须保持以下 invariant：

- 正常路径：第一个 flush 时 seed 1次后增量维护（之后 DB reload 0次）
- 重复 chunk 重传：按 cache dedup（无丢失也无重复）
- 失败路径：cache reset → retry chunk 走 DB reload 路径 dedup
  （若 cache 领先 DB，会出现 retry event 静默丢失的危险）
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.model import Model
from app.models.user import User
from app.services import trace_storage
from app.services.conversation_stream_service import build_persist_callback
from tests.conftest import TEST_USER_ID, TestSession


async def _seed_conversation() -> uuid.UUID:
    async with TestSession() as db:
        existing_user = await db.get(User, TEST_USER_ID)
        if existing_user is None:
            db.add(User(id=TEST_USER_ID, email="test@test.com", name="Test"))
        model = Model(provider="openai", model_name="gpt-4o", display_name="GPT-4o")
        db.add(model)
        await db.flush()
        agent = Agent(
            user_id=TEST_USER_ID,
            name="Persist Callback Tester",
            description=None,
            system_prompt="...",
            model_id=model.id,
            status="active",
        )
        db.add(agent)
        await db.flush()
        conv = Conversation(agent_id=agent.id, title="t1")
        db.add(conv)
        await db.commit()
        return conv.id


def _chunk(run_id: str, start_seq: int, count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{run_id}-{start_seq + i}",
            "event": "content_delta",
            "data": {"delta": f"chunk-{start_seq + i}"},
        }
        for i in range(count)
    ]


async def _stored_ids(run_id: str) -> list[str]:
    async with TestSession() as db:
        record = await trace_storage.get_trace_by_msg_id(db, run_id)
        assert record is not None
        return [event["id"] for event in record.events]


@pytest.mark.asyncio
async def test_persist_callback_seeds_once_then_dedups_without_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conv_id = await _seed_conversation()
    run_id = "run-cb-cache"
    callback = build_persist_callback(conv_id, run_id)

    seed_calls = 0
    real_seed = trace_storage.load_persisted_event_ids

    async def counting_seed(*args: Any, **kwargs: Any) -> set[str]:
        nonlocal seed_calls
        seed_calls += 1
        return await real_seed(*args, **kwargs)

    monkeypatch.setattr(trace_storage, "load_persisted_event_ids", counting_seed)

    async def _explode(*_args: object, **_kwargs: object) -> set[str]:
        raise AssertionError("cache 路径中不应发生累计 chunk 的 DB reload")

    monkeypatch.setattr(trace_storage, "_load_existing_event_ids", _explode)

    await callback(_chunk(run_id, 1, 3))
    # boundary 重复（id 3）+ 新增（4-5）重传 — 应仅靠 cache 完成 dedup。
    await callback(_chunk(run_id, 3, 3))

    assert seed_calls == 1
    assert await _stored_ids(run_id) == [f"{run_id}-{i}" for i in range(1, 6)]


@pytest.mark.asyncio
async def test_persist_callback_failure_resets_cache_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conv_id = await _seed_conversation()
    run_id = "run-cb-retry"
    callback = build_persist_callback(conv_id, run_id)

    seed_calls = 0
    real_seed = trace_storage.load_persisted_event_ids

    async def counting_seed(*args: Any, **kwargs: Any) -> set[str]:
        nonlocal seed_calls
        seed_calls += 1
        return await real_seed(*args, **kwargs)

    monkeypatch.setattr(trace_storage, "load_persisted_event_ids", counting_seed)

    await callback(_chunk(run_id, 1, 3))
    assert seed_calls == 1

    real_append = trace_storage.append_events
    fail_once = {"armed": True}

    async def flaky_append(*args: Any, **kwargs: Any) -> Any:
        if fail_once["armed"]:
            fail_once["armed"] = False
            raise RuntimeError("transient DB failure")
        return await real_append(*args, **kwargs)

    monkeypatch.setattr(trace_storage, "append_events", flaky_append)

    with pytest.raises(RuntimeError, match="transient DB failure"):
        await callback(_chunk(run_id, 4, 2))

    # streaming 侧 retry 语义 — 失败 chunk 恢复到 buffer 前部，并在下一次
    # flush 时与新事件一起重传。
    await callback([*_chunk(run_id, 4, 2), *_chunk(run_id, 6, 1)])

    # 失败会使 cache 失效，retry 必须走 DB 重新 seed 路径 — 若 cache
    # 领先 DB（误认为已经见过失败 chunk），retry event 会
    # 被 dedup 静默丢失。
    assert seed_calls == 2
    assert await _stored_ids(run_id) == [f"{run_id}-{i}" for i in range(1, 7)]
