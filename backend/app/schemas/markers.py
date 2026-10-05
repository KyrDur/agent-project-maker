"""Reserved name prefixes used to identify rows created by migrations.

Split from schemas.connection to avoid circular imports between
schemas/connection ↔ services/env_var_resolver ↔ services/credential_service
↔ schemas/credential.
"""

# m10 migration 给基于 env 自动 seed 的 connection/credential 添加的 prefix。
# downgrade 会通过该 prefix 识别 seeded row 并反向删除，因此在 API 边界需要禁止用户
# 直接使用该 prefix（display_name / name 两个字段都保留）。
M10_SEED_MARKER = "[m10-auto-seed]"


def check_reserved_marker(value: str | None, field_name: str) -> str | None:
    """在 API 边界阻止使用 `M10_SEED_MARKER` prefix。

    connection.display_name 和 credential.name 都是 m10 auto-seed downgrade 的
    LIKE 匹配对象，因此如果用户可以直接使用该 prefix，rollback 时
    会连用户手动创建的数据也一起删除，造成数据丢失。

    None 直接 passthrough（考虑 PATCH 未发送 / Optional 字段）。
    """
    if value is None:
        return value
    if value.startswith(M10_SEED_MARKER):
        raise ValueError(
            f"{field_name} cannot start with the reserved marker "
            f"'{M10_SEED_MARKER}' — reserved for m10 auto-seeded rows so "
            "rollback can safely identify them."
        )
    return value
