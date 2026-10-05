"""Forest-trip（林业厅休养林预约）account — login credentials."""

from __future__ import annotations

from app.credentials.domain import CredentialDefinition
from app.credentials.field import FieldDef, FieldKind

definition = CredentialDefinition(
    key="foresttrip_account",
    display_name="Forest Trip Account",
    icon_id="tree",
    category="account",
    properties=[
        FieldDef(
            name="username",
            display_name="Username",
            kind=FieldKind.STRING,
            required=True,
            description="森林出行e会员 ID",
        ),
        FieldDef(
            name="password",
            display_name="Password",
            kind=FieldKind.PASSWORD,
            required=True,
            type_options={"password": True},
        ),
    ],
)
