"""M67: FK indexes for hot-path filters (BE-P6).

以下五个 FK/过滤列缺少索引，导致 seq scan：

- token_usages.agent_id — 用量卡片中的 SUM(...) WHERE agent_id (usage_service)
- token_usages.conversation_id — 删除对话时 ON DELETE CASCADE 会全表扫描
- message_attachments.conversation_id — GET /messages 轮询·/files 过滤
- mcp_servers.user_id — MCP 服务器列表 WHERE user_id
- agent_triggers.agent_id — 触发器列表/聚合（现有复合索引以 status 为首列，无法覆盖）

token_usages 是每个 LLM 轮次增加 1 行、增长最快的表，但没有非 PK 索引，
因此会随时间不断恶化。模型中也同时添加 index=True，
以保持与 metadata.create_all（测试/新环境）一致。
"""

from __future__ import annotations

from alembic import op

revision = "m67_hotpath_fk_indexes"
down_revision = "m66_template_skill_slugs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_token_usages_agent_id", "token_usages", ["agent_id"])
    op.create_index("ix_token_usages_conversation_id", "token_usages", ["conversation_id"])
    op.create_index(
        "ix_message_attachments_conversation_id", "message_attachments", ["conversation_id"]
    )
    op.create_index("ix_mcp_servers_user_id", "mcp_servers", ["user_id"])
    op.create_index("ix_agent_triggers_agent_id", "agent_triggers", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_triggers_agent_id", table_name="agent_triggers")
    op.drop_index("ix_mcp_servers_user_id", table_name="mcp_servers")
    op.drop_index("ix_message_attachments_conversation_id", table_name="message_attachments")
    op.drop_index("ix_token_usages_conversation_id", table_name="token_usages")
    op.drop_index("ix_token_usages_agent_id", table_name="token_usages")
