"""m34 alembic migration — round-trip + SQLite batch_alter_table 回归守卫。

W3-out M2 — 新增 ``status`` + ``updated_at`` 列 + ``idx_message_events_status``
索引 + CHECK 约束。SQLite 不支持 ALTER TABLE DROP CONSTRAINT/COLUMN，因此
若 downgrade 不通过 ``op.batch_alter_table`` 绕过就会失败。本测试负责这一
回归守卫。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.database import Base

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "m34_message_events_streaming_status.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "m34_message_events_streaming_status_test_load", _MIGRATION
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_imports_with_expected_revision_chain() -> None:
    mod = _load_module()
    assert mod.revision == "m34_message_events_status"
    assert mod.down_revision == "m33_add_linked_message_ids"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


def test_metadata_includes_status_and_updated_at_columns() -> None:
    table = Base.metadata.tables.get("message_events")
    assert table is not None
    assert "status" in table.columns
    assert "updated_at" in table.columns


@pytest.mark.asyncio
async def test_upgrade_downgrade_roundtrip_sqlite() -> None:
    """``upgrade`` → ``downgrade`` → ``upgrade`` against in-memory SQLite.

    核心回归守卫：SQLite 对 ``ALTER TABLE DROP CONSTRAINT`` 和
    ``ALTER TABLE DROP COLUMN`` 不提供 native 支持，因此 downgrade
    若不通过 ``batch_alter_table`` 绕过，会发生 OperationalError。
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    mod = _load_module()
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            # m33 状态 — message_events 表 + linked_message_ids 为止。
            # m34 新增的 status / updated_at 尚不存在。
            conn.exec_driver_sql(
                "CREATE TABLE message_events ("
                "  id TEXT PRIMARY KEY,"
                "  conversation_id TEXT NOT NULL,"
                "  assistant_msg_id TEXT NOT NULL UNIQUE,"
                "  events JSON NOT NULL,"
                "  last_event_id TEXT,"
                "  linked_message_ids JSON,"
                "  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                "  completed_at TIMESTAMP"
                ")"
            )
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            from alembic import op as alembic_op

            alembic_op._proxy = op  # type: ignore[attr-defined]

            # 1) upgrade — 新增 status + updated_at + index
            mod.upgrade()
            inspector = inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("message_events")}
            assert "status" in cols
            assert "updated_at" in cols
            indexes = {ix["name"] for ix in inspector.get_indexes("message_events")}
            assert "idx_message_events_status" in indexes

            # 2) downgrade — 删除 status、updated_at、index、CHECK。
            #    若 batch_alter_table 绕过未生效，会在这里发生 OperationalError。
            mod.downgrade()
            inspector = inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("message_events")}
            assert "status" not in cols
            assert "updated_at" not in cols
            indexes = {ix["name"] for ix in inspector.get_indexes("message_events")}
            assert "idx_message_events_status" not in indexes

            # 3) re-upgrade — m34 是否可幂等地再次应用
            mod.upgrade()
            inspector = inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("message_events")}
            assert "status" in cols
            assert "updated_at" in cols
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_upgrade_preserves_existing_rows_with_default_status() -> None:
    """m33 之前的 row（无 status 列）→ upgrade 后自动填充 status='completed'。

    验证 DEFAULT 'completed' NOT NULL 的 backfill 行为。PoC 中 message_events
    为空，但可作为运行 DB 中 m33 之前 row 的回归信号。
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text

    mod = _load_module()
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE message_events ("
                "  id TEXT PRIMARY KEY,"
                "  conversation_id TEXT NOT NULL,"
                "  assistant_msg_id TEXT NOT NULL UNIQUE,"
                "  events JSON NOT NULL,"
                "  last_event_id TEXT,"
                "  linked_message_ids JSON,"
                "  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                "  completed_at TIMESTAMP"
                ")"
            )
            # 在 m33 时点 写入 1 条 row
            conn.exec_driver_sql(
                "INSERT INTO message_events "
                "(id, conversation_id, assistant_msg_id, events) "
                "VALUES ('e1', 'c1', 'msg-1', '[]')"
            )
            conn.commit()

            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            from alembic import op as alembic_op

            alembic_op._proxy = op  # type: ignore[attr-defined]

            mod.upgrade()

            row = conn.execute(
                text("SELECT status, updated_at FROM message_events WHERE id='e1'")
            ).first()
            assert row is not None
            assert row[0] == "completed"  # DEFAULT backfill
            assert row[1] is not None  # updated_at server_default(now)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_check_constraint_rejects_invalid_status() -> None:
    """验证是否应用 ``status IN ('streaming','completed','failed')`` CHECK 约束。"""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError

    mod = _load_module()
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE message_events ("
                "  id TEXT PRIMARY KEY,"
                "  conversation_id TEXT NOT NULL,"
                "  assistant_msg_id TEXT NOT NULL UNIQUE,"
                "  events JSON NOT NULL,"
                "  last_event_id TEXT,"
                "  linked_message_ids JSON,"
                "  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                "  completed_at TIMESTAMP"
                ")"
            )
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            from alembic import op as alembic_op

            alembic_op._proxy = op  # type: ignore[attr-defined]

            mod.upgrade()

            # 有效 status 为 OK
            conn.exec_driver_sql(
                "INSERT INTO message_events "
                "(id, conversation_id, assistant_msg_id, events, status) "
                "VALUES ('e1', 'c1', 'msg-1', '[]', 'streaming')"
            )
            # 无效 status 会被拒绝
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(
                    "INSERT INTO message_events "
                    "(id, conversation_id, assistant_msg_id, events, status) "
                    "VALUES ('e2', 'c1', 'msg-2', '[]', 'invalid')"
                )
    finally:
        engine.dispose()
